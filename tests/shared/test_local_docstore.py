"""Local full-ClimbMix docstore reads used by CLI research agents.

These tests build tiny stores in the production offset/payload layout. They
defend the parent-docid mapping and decoding boundary without requiring the
multi-terabyte local artifact in CI.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from utils.local_docstore import FullClimbMixDocStore, LocalDocStoreError


def _store(tmp_path: Path, texts: list[str], *, compressed: bool = False) -> Path:
    """Create a two-file shard whose rows exercise real byte offsets."""
    root = tmp_path / "docstore"
    root.mkdir()
    payloads = [text.encode("utf-8") for text in texts]
    compression = "none"
    if compressed:
        import zstandard as zstd

        compressor = zstd.ZstdCompressor(level=3)
        payloads = [compressor.compress(payload) for payload in payloads]
        compression = "zstd-3"
    offsets = [0]
    for payload in payloads:
        offsets.append(offsets[-1] + len(payload))
    (root / "manifest.json").write_text(json.dumps({
        "version": 1, "compression": compression, "keyed_by": "stem_row",
    }), encoding="utf-8")
    (root / "shard_00001.bin").write_bytes(b"".join(payloads))
    (root / "shard_00001.offsets.bin").write_bytes(
        struct.pack(f"<{len(offsets)}Q", *offsets))
    return root


@pytest.mark.parametrize("compressed", [False, True])
def test_reads_the_exact_parent_row(tmp_path: Path, compressed: bool) -> None:
    """Offsets select one organizer document, not a neighboring row or chunk."""
    root = _store(tmp_path, ["zero", "Café — 東京 full document"],
                  compressed=compressed)

    text = FullClimbMixDocStore(root).get_text("shard_00001_1")

    assert text == "Café — 東京 full document"


def test_rejects_chunk_ids_and_path_traversal(tmp_path: Path) -> None:
    """Only exact organizer parent docids may become filesystem paths."""
    store = FullClimbMixDocStore(_store(tmp_path, ["zero"]))

    for docid in ("shard_00001_0_p1", "../manifest_0", "shard_x_0"):
        with pytest.raises(LocalDocStoreError, match="does not match"):
            store.get_text(docid)


def test_an_out_of_range_row_is_a_loud_error(tmp_path: Path) -> None:
    """A missing document must not decode as empty evidence and authorize a citation."""
    store = FullClimbMixDocStore(_store(tmp_path, ["only row"]))

    with pytest.raises(LocalDocStoreError, match="outside"):
        store.get_text("shard_00001_9")


def test_refuses_a_chunk_keyed_store(tmp_path: Path) -> None:
    """Chunk rows cannot masquerade as the full documents promised by `fetch`."""
    root = _store(tmp_path, ["chunk"])
    (root / "manifest.json").write_text(json.dumps({
        "compression": "none", "keyed_by": "chunk_id",
    }), encoding="utf-8")

    with pytest.raises(LocalDocStoreError, match="stem_row"):
        FullClimbMixDocStore(root)
