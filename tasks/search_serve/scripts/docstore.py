"""mmap'd per-shard docstore reader.

On-disk layout is produced by tasks/custom_index/scripts/build_docstore.py:

  <root>/manifest.json
  <root>/zstd.dict                # only when compression != "none"
  <root>/shard_NNNNN.bin          # raw bytes or independently-decompressible zstd frames
  <root>/shard_NNNNN.offsets.bin  # uint64[N+1] start byte for each record

A docid ``<stem>_<row>`` maps to record ``row`` in that shard's pair.
"""
from __future__ import annotations

import json
import mmap
import os
import re
import struct
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from errors import EngineLoadError, docstore_build_hint, ensure_path


@dataclass
class DocstoreFetchTimings:
    """Per-phase breakdown of a batch fetch — written by ``get_texts``
    when an empty instance is passed via the ``timings`` kwarg. All values
    are milliseconds, summed across the entire batch."""
    open_ms: float = 0.0            # _get_handle: LRU touch + mmap open on miss
    read_ms: float = 0.0            # offset slice + .bin byte slice from mmap
    decompress_ms: float = 0.0      # zstd decompress (no-op when compression=none)
    decode_ms: float = 0.0          # UTF-8 decode
    n_records: int = 0
    n_unique_shards: int = 0
    n_mmap_opens: int = 0           # how many shards were NOT in the LRU

    def timings_dict(self) -> dict:
        """Just the wall-clock latencies (ms). Goes under response.timings."""
        return {
            "open_ms": round(self.open_ms, 3),
            "read_ms": round(self.read_ms, 3),
            "decompress_ms": round(self.decompress_ms, 3),
            "decode_ms": round(self.decode_ms, 3),
        }

    def meta_dict(self) -> dict:
        """Counts of what the fetch did. Goes under response.metadata."""
        return {
            "n_records": self.n_records,
            "n_unique_shards": self.n_unique_shards,
            "n_mmap_opens": self.n_mmap_opens,
        }

    # Back-compat: callers asking for to_dict get the combined form (still
    # used in the structured server log line).
    def to_dict(self) -> dict:
        return {**self.timings_dict(), **self.meta_dict()}


_DOCID_RE = re.compile(r"^(.+)_(\d+)$")


def split_docid(docid: str) -> tuple[str, int]:
    m = _DOCID_RE.match(docid)
    if not m:
        raise ValueError(f"docid {docid!r} does not match `<stem>_<row>`")
    return m.group(1), int(m.group(2))


@dataclass
class _ShardHandle:
    bin_mm: mmap.mmap
    offs_mm: mmap.mmap
    bin_fd: int
    offs_fd: int

    def close(self) -> None:
        for closer in (self.bin_mm.close, self.offs_mm.close):
            try:
                closer()
            except OSError:
                pass
        for fd in (self.bin_fd, self.offs_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def _open_pair(root: Path, stem: str) -> _ShardHandle:
    bin_path = root / f"{stem}.bin"
    offs_path = root / f"{stem}.offsets.bin"
    if not (bin_path.exists() and offs_path.exists()):
        raise EngineLoadError(
            f"docstore is missing shard files for {stem!r}: "
            f"expected {bin_path.name} and {offs_path.name} under {root}.\n\n"
            f"{docstore_build_hint(root.parent)}"
        )
    bin_fd = os.open(bin_path, os.O_RDONLY)
    offs_fd = os.open(offs_path, os.O_RDONLY)
    bin_mm = mmap.mmap(bin_fd, os.fstat(bin_fd).st_size, prot=mmap.PROT_READ)
    offs_mm = mmap.mmap(offs_fd, os.fstat(offs_fd).st_size, prot=mmap.PROT_READ)
    return _ShardHandle(bin_mm=bin_mm, offs_mm=offs_mm,
                        bin_fd=bin_fd, offs_fd=offs_fd)


def _read_slice(h: _ShardHandle, row: int) -> bytes:
    a, b = struct.unpack_from("<QQ", h.offs_mm, row * 8)
    return bytes(h.bin_mm[a:b])


class FlatShardDocStore:
    """LRU-cached reader. Open files are bounded to ``lru_size`` shards."""

    def __init__(self, root: Path, lru_size: int = 1024):
        self.root = Path(root)
        ensure_path(self.root / "manifest.json", docstore_build_hint)
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        self.compression: str = self.manifest["compression"]
        self._dict_bytes: bytes | None = None
        if self.compression != "none":
            ensure_path(self.root / self.manifest["dict"], docstore_build_hint)
            self._dict_bytes = (self.root / self.manifest["dict"]).read_bytes()
        self._lru_size = lru_size
        self._handles: OrderedDict[str, _ShardHandle] = OrderedDict()
        # Zstd decoder is NOT thread-safe: instances maintain an internal
        # scratch buffer that races under FastAPI's sync-endpoint threadpool.
        # Hold one per thread via threading.local; lazy-built on first call.
        self._tls = threading.local()

    # ---- lifecycle -----------------------------------------------------

    def close(self) -> None:
        for h in self._handles.values():
            h.close()
        self._handles.clear()

    # ---- internals -----------------------------------------------------

    def _decode(self, raw: bytes) -> bytes:
        if self.compression == "none":
            return raw
        d = getattr(self._tls, "decoder", None)
        if d is None:
            import zstandard as zstd
            dd = zstd.ZstdCompressionDict(self._dict_bytes)
            d = zstd.ZstdDecompressor(dict_data=dd)
            self._tls.decoder = d
        return d.decompress(raw)

    def _get_handle(self, stem: str) -> _ShardHandle:
        h = self._handles.get(stem)
        if h is not None:
            self._handles.move_to_end(stem)
            return h
        # Evict BEFORE opening so we never transiently exceed the fd cap.
        # Under concurrent load the old eviction-after-open pattern raced
        # against RLIMIT_NOFILE and threw OSError(24) on the os.open call
        # before the eviction loop got a chance to run.
        while len(self._handles) >= self._lru_size:
            _, evicted = self._handles.popitem(last=False)
            evicted.close()
        h = _open_pair(self.root, stem)
        self._handles[stem] = h
        return h

    # ---- public --------------------------------------------------------

    def get_text(self, docid: str) -> str:
        stem, row = split_docid(docid)
        raw = _read_slice(self._get_handle(stem), row)
        return self._decode(raw).decode("utf-8")

    def get_texts(self, docids: Iterable[str], *,
                  timings: DocstoreFetchTimings | None = None) -> list[str]:
        """Per-shard coalescing to amortize LRU touches on batch fetches.

        Pass an empty ``DocstoreFetchTimings()`` instance to capture the
        per-phase breakdown (open / read / decompress / decode). All
        wall-clock totals across the entire batch."""
        by_shard: dict[str, list[tuple[int, int]]] = {}
        order: list[str] = []
        for i, did in enumerate(docids):
            stem, row = split_docid(did)
            by_shard.setdefault(stem, []).append((i, row))
            order.append(did)
        out: list[str] = [""] * len(order)
        record = timings is not None
        n_opens = 0
        t_open = t_read = t_decompress = t_decode = 0.0
        for stem, items in by_shard.items():
            if record:
                if stem not in self._handles:
                    n_opens += 1
                t0 = time.perf_counter()
            h = self._get_handle(stem)
            if record:
                t_open += time.perf_counter() - t0
            for orig_i, row in items:
                if record:
                    t0 = time.perf_counter()
                raw = _read_slice(h, row)
                if record:
                    t_read += time.perf_counter() - t0
                    t0 = time.perf_counter()
                decompressed = self._decode(raw)
                if record:
                    t_decompress += time.perf_counter() - t0
                    t0 = time.perf_counter()
                out[orig_i] = decompressed.decode("utf-8")
                if record:
                    t_decode += time.perf_counter() - t0
        if record:
            timings.open_ms = t_open * 1000.0
            timings.read_ms = t_read * 1000.0
            timings.decompress_ms = t_decompress * 1000.0
            timings.decode_ms = t_decode * 1000.0
            timings.n_records = len(order)
            timings.n_unique_shards = len(by_shard)
            timings.n_mmap_opens = n_opens
        return out

    def madvise_willneed(self) -> None:
        """Tell the kernel to pull every shard's offsets file into page cache."""
        for offs_path in sorted(self.root.glob("*.offsets.bin")):
            try:
                fd = os.open(offs_path, os.O_RDONLY)
                mm = mmap.mmap(fd, os.fstat(fd).st_size, prot=mmap.PROT_READ)
                mm.madvise(mmap.MADV_WILLNEED)
                mm.close()
                os.close(fd)
            except OSError:
                continue
