"""mmap'd per-shard docstore reader.

On-disk layout is produced by tasks/custom_index/scripts/build_docstore.py:

  <root>/manifest.json
  <root>/zstd.dict                # only when compression != "none"
  <root>/shard_NNNNN.bin          # raw bytes or independently-decompressible zstd frames
  <root>/shard_NNNNN.offsets.bin  # uint64[N+1] start byte for each record

A docid ``<stem>_<row>`` maps to record ``row`` in that shard's pair.
"""
from __future__ import annotations

import concurrent.futures as _cf
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
    """Pure wall-clock latencies of a batch fetch, in milliseconds. Lives
    under ``SearchTimings.docstore`` -> response.timings.docstore."""
    open_ms: float = 0.0            # _get_handle: LRU touch + mmap open on miss
    read_ms: float = 0.0            # offset slice + .bin byte slice from mmap
    decompress_ms: float = 0.0      # zstd decompress (no-op when compression=none)
    decode_ms: float = 0.0          # UTF-8 decode

    def to_dict(self) -> dict:
        return {
            "open_ms": round(self.open_ms, 3),
            "read_ms": round(self.read_ms, 3),
            "decompress_ms": round(self.decompress_ms, 3),
            "decode_ms": round(self.decode_ms, 3),
        }


@dataclass
class DocstoreFetchStats:
    """Descriptive counts of what a batch fetch touched. Lives under
    ``SearchMeta.docstore`` -> response.metadata.docstore."""
    n_records: int = 0
    n_unique_shards: int = 0
    n_mmap_opens: int = 0           # shards that were NOT in the LRU

    def to_dict(self) -> dict:
        return {
            "n_records": self.n_records,
            "n_unique_shards": self.n_unique_shards,
            "n_mmap_opens": self.n_mmap_opens,
        }


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


def _fetch_chunk_worker(store: "FlatShardDocStore",
                         chunk: list[tuple["_ShardHandle", int, int]],
                         out: list[str], time_it: bool) -> tuple[float, float, float]:
    """Worker entrypoint for the parallel docstore fetch.

    Module-level so it doesn't capture extra closure state. Per-thread
    state lives on ``store._tls`` (e.g. the Zstd decoder), so each worker
    builds its own decoder on first call and reuses it.

    Returns (read_s, decompress_s, decode_s) for this thread's chunk.
    """
    t_read = t_decompress = t_decode = 0.0
    for h, row, orig_i in chunk:
        if time_it:
            t0 = time.perf_counter()
        raw = _read_slice(h, row)
        if time_it:
            t_read += time.perf_counter() - t0
            t0 = time.perf_counter()
        decompressed = store._decode(raw)
        if time_it:
            t_decompress += time.perf_counter() - t0
            t0 = time.perf_counter()
        out[orig_i] = decompressed.decode("utf-8")
        if time_it:
            t_decode += time.perf_counter() - t0
    return t_read, t_decompress, t_decode


class FlatShardDocStore:
    """LRU-cached reader. Open files are bounded to ``lru_size`` shards."""

    def __init__(self, root: Path, lru_size: int = 1024,
                  parallel: int = 8, parallel_min_k: int = 64):
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
        # Parallel-fetch config.
        # parallel       : N worker threads for get_texts. <=1 disables.
        # parallel_min_k : skip the parallel path (run serial) when the
        #                  batch has fewer than this many records — for
        #                  small batches the dispatch overhead exceeds
        #                  the page-fault parallelism win.
        self.parallel = max(1, parallel)
        self.parallel_min_k = max(1, parallel_min_k)
        self._pool: _cf.ThreadPoolExecutor | None = None
        self._pool_lock = threading.Lock()

    # ---- lifecycle -----------------------------------------------------

    def close(self) -> None:
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._pool = None
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
                  timings: DocstoreFetchTimings | None = None,
                  stats: DocstoreFetchStats | None = None) -> list[str]:
        """Batch fetch with per-shard coalescing.

        Optional ``timings`` and ``stats`` out-params capture the per-phase
        breakdown and the descriptive counts. Pass empty instances if you
        want them filled; omit for zero overhead.

        When the docstore was constructed with ``parallel>1`` and the batch
        is at least ``parallel_min_k`` records, the read / decompress /
        decode work fans out across a thread pool. Handles are always opened
        sequentially in the main thread so the LRU never needs locking.
        """
        # Phase 1: parse + group by shard.
        by_shard: dict[str, list[tuple[int, int]]] = {}
        order: list[str] = []
        for i, did in enumerate(docids):
            stem, row = split_docid(did)
            by_shard.setdefault(stem, []).append((i, row))
            order.append(did)
        n_records = len(order)
        out: list[str] = [""] * n_records

        use_parallel = (self.parallel > 1 and n_records >= self.parallel_min_k)

        # Phase 2: pre-open shard handles (serial; updates LRU under no lock).
        n_opens, handles, t_open = self._preopen_handles(by_shard, time_it=timings is not None)

        # Phase 3: read + decompress + decode.
        if use_parallel:
            t_read, t_decompress, t_decode = self._fetch_parallel(
                by_shard, handles, out, time_it=timings is not None,
            )
        else:
            t_read, t_decompress, t_decode = self._fetch_serial(
                by_shard, handles, out, time_it=timings is not None,
            )

        # Bring the LRU back under its cap now that all reads are done
        # against `handles` (local refs are still safe — `_trim_lru` only
        # touches entries _handles still holds).
        self._trim_lru()

        if timings is not None:
            timings.open_ms = t_open * 1000.0
            timings.read_ms = t_read * 1000.0
            timings.decompress_ms = t_decompress * 1000.0
            timings.decode_ms = t_decode * 1000.0
        if stats is not None:
            stats.n_records = n_records
            stats.n_unique_shards = len(by_shard)
            stats.n_mmap_opens = n_opens
        return out

    # ---- get_texts phase helpers ---------------------------------------

    def _preopen_handles(self, by_shard: dict[str, list[tuple[int, int]]],
                          time_it: bool) -> tuple[int, dict[str, _ShardHandle], float]:
        """Open every needed shard up-front. We bypass _get_handle's
        evict-on-overflow so a batch that touches more shards than the
        LRU's cap can keep all of them live for the duration of this call.
        ``_trim_lru()`` is called at the end of ``get_texts`` to bring the
        cache back under ``lru_size``."""
        n_opens = 0
        handles: dict[str, _ShardHandle] = {}
        t0 = time.perf_counter() if time_it else 0.0
        for stem in by_shard:
            cached = self._handles.get(stem)
            if cached is not None:
                self._handles.move_to_end(stem)
                handles[stem] = cached
            else:
                n_opens += 1
                h = _open_pair(self.root, stem)
                self._handles[stem] = h
                handles[stem] = h
        elapsed = (time.perf_counter() - t0) if time_it else 0.0
        return n_opens, handles, elapsed

    def _trim_lru(self) -> None:
        """Evict oldest entries until ``len(_handles) <= lru_size``."""
        while len(self._handles) > self._lru_size:
            _, evicted = self._handles.popitem(last=False)
            evicted.close()

    def _fetch_serial(self, by_shard, handles, out, *, time_it: bool):
        """Single-threaded read+decompress+decode loop. Returns
        (read_s, decompress_s, decode_s)."""
        t_read = t_decompress = t_decode = 0.0
        for stem, items in by_shard.items():
            h = handles[stem]
            for orig_i, row in items:
                if time_it:
                    t0 = time.perf_counter()
                raw = _read_slice(h, row)
                if time_it:
                    t_read += time.perf_counter() - t0
                    t0 = time.perf_counter()
                decompressed = self._decode(raw)
                if time_it:
                    t_decompress += time.perf_counter() - t0
                    t0 = time.perf_counter()
                out[orig_i] = decompressed.decode("utf-8")
                if time_it:
                    t_decode += time.perf_counter() - t0
        return t_read, t_decompress, t_decode

    def _fetch_parallel(self, by_shard, handles, out, *, time_it: bool):
        """Multi-threaded read+decompress+decode. Returns (read_s,
        decompress_s, decode_s) summed across ALL worker threads — i.e. it's
        CPU-time, not wall-clock. Compare against ``docstore_fetch_ms``
        (the caller's wall-clock) to gauge parallel efficiency:
        ``(read+decompress+decode) / fetch_ms`` ≈ effective parallelism."""
        # Flatten work into a single list of (handle, row, orig_i) so we can
        # chunk it evenly across threads. This keeps each thread's chunk
        # roughly the same size regardless of how the per-shard rows
        # were grouped.
        work: list[tuple[_ShardHandle, int, int]] = []
        for stem, items in by_shard.items():
            h = handles[stem]
            for orig_i, row in items:
                work.append((h, row, orig_i))

        pool = self._get_or_make_pool()
        n_threads = self.parallel
        # Chunk by striding so all threads get a near-equal share.
        chunks = [work[i::n_threads] for i in range(n_threads)]
        futures = [pool.submit(_fetch_chunk_worker, self, chunk, out, time_it)
                    for chunk in chunks]
        totals = [f.result() for f in futures]
        # Sum per-phase times across worker threads (CPU-time view).
        t_read = sum(t[0] for t in totals)
        t_decompress = sum(t[1] for t in totals)
        t_decode = sum(t[2] for t in totals)
        return t_read, t_decompress, t_decode

    def _get_or_make_pool(self) -> _cf.ThreadPoolExecutor:
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                self._pool = _cf.ThreadPoolExecutor(
                    max_workers=self.parallel,
                    thread_name_prefix="docstore-fetch",
                )
        return self._pool

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
