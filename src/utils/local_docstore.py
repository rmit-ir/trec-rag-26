"""Read full ClimbMix documents from the local flat-shard docstore.

The full-corpus build is keyed by the organizer docid ``<shard>_<row>``. Each
shard has a byte payload and a uint64 offset table, with records optionally
compressed as independent Zstandard frames. This small reader intentionally
opens only the two files needed for one fetch; coding-agent access is sparse
and random across 6,543 shards, so a large mmap/file-handle cache buys little
while multiplying resources across CLI subprocesses.
"""
from __future__ import annotations

import json
import os
import re
import struct
import threading
from pathlib import Path

_DOCID = re.compile(r"^(shard_[0-9]+)_([0-9]+)$")


class LocalDocStoreError(RuntimeError):
    """The local store is absent, malformed, or missing the requested row."""


class FullClimbMixDocStore:
    """Random-access reader for a ``stem_row`` ClimbMix flat docstore."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        manifest_path = self.root / "manifest.json"
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LocalDocStoreError(
                f"cannot read local docstore manifest {manifest_path}: {exc}") from exc
        keyed_by = self.manifest.get("keyed_by", "stem_row")
        if keyed_by != "stem_row":
            raise LocalDocStoreError(
                f"local full-document fetch needs keyed_by='stem_row', got {keyed_by!r}")
        self.compression = str(self.manifest.get("compression", "none"))
        self._dict_bytes: bytes | None = None
        dictionary = self.manifest.get("dict")
        if self.compression != "none" and dictionary:
            try:
                self._dict_bytes = (self.root / str(dictionary)).read_bytes()
            except OSError as exc:
                raise LocalDocStoreError(
                    f"cannot read local docstore dictionary {dictionary!r}: {exc}") from exc
        self._tls = threading.local()

    @staticmethod
    def _split_docid(docid: str) -> tuple[str, int]:
        match = _DOCID.fullmatch(docid)
        if not match:
            raise LocalDocStoreError(
                f"docid {docid!r} does not match 'shard_<digits>_<row>'")
        return match.group(1), int(match.group(2))

    def _decode(self, payload: bytes) -> bytes:
        if self.compression == "none":
            return payload
        if not self.compression.startswith("zstd"):
            raise LocalDocStoreError(
                f"unsupported local docstore compression {self.compression!r}")
        decoder = getattr(self._tls, "decoder", None)
        if decoder is None:
            import zstandard as zstd

            kwargs = {}
            if self._dict_bytes is not None:
                kwargs["dict_data"] = zstd.ZstdCompressionDict(self._dict_bytes)
            decoder = zstd.ZstdDecompressor(**kwargs)
            self._tls.decoder = decoder
        return decoder.decompress(payload)

    @staticmethod
    def _pread(path: Path, size: int, offset: int) -> bytes:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError as exc:
            raise LocalDocStoreError(f"cannot open local docstore shard {path}: {exc}") from exc
        try:
            return os.pread(fd, size, offset)
        finally:
            os.close(fd)

    def get_text(self, docid: str) -> str:
        """Return the exact full document text for one organizer docid."""
        stem, row = self._split_docid(docid)
        offsets = self.root / f"{stem}.offsets.bin"
        raw_offsets = self._pread(offsets, 16, row * 8)
        if len(raw_offsets) != 16:
            raise LocalDocStoreError(f"docid {docid!r} is outside {offsets.name}")
        start, end = struct.unpack("<QQ", raw_offsets)
        if end < start:
            raise LocalDocStoreError(
                f"docid {docid!r} has reversed offsets {start}>{end}")
        payload_path = self.root / f"{stem}.bin"
        payload = self._pread(payload_path, end - start, start)
        if len(payload) != end - start:
            raise LocalDocStoreError(
                f"docid {docid!r} is truncated in {payload_path.name}")
        try:
            return self._decode(payload).decode("utf-8")
        except LocalDocStoreError:
            raise
        except Exception as exc:
            raise LocalDocStoreError(f"cannot decode local document {docid!r}: {exc}") from exc
