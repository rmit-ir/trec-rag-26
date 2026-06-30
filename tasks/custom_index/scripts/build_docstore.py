#!/usr/bin/env python3
"""Build a per-shard flat docstore alongside the DiskANN index.

For each parquet shard the builder writes two files into ``--out``:

  shard_NNNNN.bin           concatenated record payloads (UTF-8 bytes, or
                            independently-decompressible zstd frames when
                            ``--compression zstd-*`` is set).
  shard_NNNNN.offsets.bin   uint64[N+1] little-endian: byte offsets into .bin,
                            offsets[i]/offsets[i+1] frame record i. Same shape
                            regardless of compression.

A ``manifest.json`` summarises the codec, dict id, shard list, and totals.
A docid ``<shard_stem>_<row>`` maps to record ``row`` in that shard's pair.

Why Python over Rust: the per-shard work is dominated by zstd encode (C
library underneath ``zstandard``) and parquet decode (pyarrow C++). Single-
core throughput is already at the codec floor; Rust would shave the small
Python orchestration cost but not the encode. Multiprocessing across shards
gets near-perfect speedup on the 128-core host — same model as
``encode_documents.py``.

Resumability: per-shard outputs are written atomically (``.tmp`` + rename),
so a re-run skips any shard whose ``.bin`` AND ``.offsets.bin`` both exist
and whose offset-table row count matches the parquet row count.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import struct
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


CODECS = ("none", "zstd-3", "zstd-9", "zstd-19")


def parse_codec(s: str) -> tuple[str, int | None]:
    """Returns (family, level) — family in {'none','zstd'}; level is None for 'none'."""
    if s == "none":
        return "none", None
    if not s.startswith("zstd-"):
        raise ValueError(f"unsupported --compression {s!r}; choose from {CODECS}")
    try:
        level = int(s.split("-", 1)[1])
    except ValueError:
        raise ValueError(f"bad --compression {s!r}; expected zstd-<level>")
    if not (1 <= level <= 22):
        raise ValueError(f"zstd level must be in [1,22], got {level}")
    return "zstd", level


# ---------------------------------------------------------------------------
# Dictionary training
# ---------------------------------------------------------------------------

def _sample_records_from_shard(parquet: Path, max_bytes: int) -> list[bytes]:
    """Stream parquet rows into a list of UTF-8 byte records, capped at
    ``max_bytes`` total. Reads row_groups in order — caller picks shards."""
    import pyarrow.parquet as pq
    out: list[bytes] = []
    total = 0
    pf = pq.ParquetFile(parquet)
    for batch in pf.iter_batches(batch_size=8192, columns=["text"]):
        for s in batch.column("text").to_pylist():
            b = s.encode("utf-8")
            out.append(b); total += len(b)
            if total >= max_bytes:
                return out
    return out


def train_dict(shards: list[Path], dict_size: int, sample_shards: int,
               sample_bytes_per_shard: int, seed: int = 0) -> bytes:
    """Train a Zstd dictionary from ``sample_shards`` randomly-chosen parquet
    shards. Returns the serialized dict bytes."""
    import zstandard as zstd
    rng = random.Random(seed)
    pool = shards[:]
    rng.shuffle(pool)
    pool = pool[:sample_shards]
    print(f"[dict] training on {len(pool)} sample shard(s), "
          f"<= {sample_bytes_per_shard/1e6:.0f} MB each", flush=True)
    samples: list[bytes] = []
    for sh in pool:
        recs = _sample_records_from_shard(sh, sample_bytes_per_shard)
        print(f"[dict]   {sh.name}: {len(recs):,} records, "
              f"{sum(len(r) for r in recs)/1e6:.1f} MB", flush=True)
        samples.extend(recs)
    t0 = time.perf_counter()
    cd = zstd.train_dictionary(dict_size, samples)
    print(f"[dict] trained {dict_size//1024} KB dict in {time.perf_counter()-t0:.1f}s "
          f"(samples: {len(samples):,} records, "
          f"{sum(len(s) for s in samples)/1e6:.0f} MB)", flush=True)
    return cd.as_bytes()


# ---------------------------------------------------------------------------
# Per-shard worker
# ---------------------------------------------------------------------------

@dataclass
class ShardResult:
    stem: str
    n_records: int
    raw_bytes: int
    written_bytes: int
    elapsed_s: float
    skipped: bool


# Per-process state, lazily initialised on first task in the worker.
_WORKER_STATE: dict = {}


def _worker_init(model_name: str, codec_family: str, codec_level: int | None,
                 dict_bytes: bytes | None) -> None:
    """multiprocessing.Pool initializer — sets up the per-process compressor."""
    state = {"family": codec_family, "level": codec_level}
    if codec_family == "zstd":
        import zstandard as zstd
        if dict_bytes:
            dd = zstd.ZstdCompressionDict(dict_bytes)
            state["compressor"] = zstd.ZstdCompressor(level=codec_level, dict_data=dd)
        else:
            state["compressor"] = zstd.ZstdCompressor(level=codec_level)
    _WORKER_STATE.update(state)


def _encode_record(b: bytes) -> bytes:
    if _WORKER_STATE["family"] == "none":
        return b
    return _WORKER_STATE["compressor"].compress(b)


def _existing_shard_is_complete(bin_path: Path, offs_path: Path, expected_records: int) -> bool:
    if not (bin_path.exists() and offs_path.exists()):
        return False
    # offsets has N+1 uint64 entries
    expected_offs_bytes = (expected_records + 1) * 8
    return offs_path.stat().st_size == expected_offs_bytes and bin_path.stat().st_size > 0


def _process_shard(args: tuple[Path, Path]) -> ShardResult:
    parquet, out_dir = args
    import pyarrow.parquet as pq
    stem = parquet.stem
    bin_path = out_dir / f"{stem}.bin"
    offs_path = out_dir / f"{stem}.offsets.bin"

    pf = pq.ParquetFile(parquet)
    n_rows = pf.metadata.num_rows

    if _existing_shard_is_complete(bin_path, offs_path, n_rows):
        return ShardResult(stem=stem, n_records=n_rows,
                           raw_bytes=0, written_bytes=bin_path.stat().st_size,
                           elapsed_s=0.0, skipped=True)

    tmp_bin = bin_path.with_suffix(".bin.tmp")
    tmp_offs = offs_path.with_suffix(".offsets.bin.tmp")
    t0 = time.perf_counter()
    raw_bytes = 0
    written = 0
    offs = [0]
    with open(tmp_bin, "wb", buffering=1 << 20) as bf, \
         open(tmp_offs, "wb", buffering=1 << 20) as of:
        of.write(struct.pack("<Q", 0))
        for batch in pf.iter_batches(batch_size=8192, columns=["text"]):
            for s in batch.column("text").to_pylist():
                rb = s.encode("utf-8")
                wb = _encode_record(rb)
                bf.write(wb)
                raw_bytes += len(rb)
                written += len(wb)
                of.write(struct.pack("<Q", written))
    os.replace(tmp_bin, bin_path)
    os.replace(tmp_offs, offs_path)
    return ShardResult(stem=stem, n_records=n_rows,
                       raw_bytes=raw_bytes, written_bytes=written,
                       elapsed_s=time.perf_counter() - t0, skipped=False)


# ---------------------------------------------------------------------------
# CLI / orchestrator
# ---------------------------------------------------------------------------

def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a flat per-shard docstore.")
    ap.add_argument("--corpus", required=True, type=Path,
                    help="directory containing shard_*.parquet")
    ap.add_argument("--out", required=True, type=Path,
                    help="output docstore directory (will be created)")
    ap.add_argument("--compression", default="zstd-9", choices=CODECS,
                    help="per-record codec (default zstd-9)")
    ap.add_argument("--dict-size", type=int, default=1024 * 1024,
                    help="trained Zstd dictionary size in bytes (default 1048576). "
                         "Ignored when --compression none.")
    ap.add_argument("--dict-sample-shards", type=int, default=1,
                    help="number of parquet shards to sample for dict training (default 1)")
    ap.add_argument("--dict-sample-bytes-per-shard", type=int, default=270 * 1024 * 1024,
                    help="cap on bytes pulled from each sample shard during training")
    ap.add_argument("--parallel", type=int, default=64,
                    help="number of worker processes (default 64)")
    ap.add_argument("--seed", type=int, default=0,
                    help="seed for shard sampling during dict training")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    shards = sorted(args.corpus.glob("shard_*.parquet"))
    if not shards:
        print(f"[build_docstore] no shard_*.parquet under {args.corpus}", file=sys.stderr)
        return 2

    family, level = parse_codec(args.compression)
    use_dict = family == "zstd"

    # ---- Upfront summary -------------------------------------------------
    print("=" * 72)
    print("build_docstore")
    print("=" * 72)
    print(f"  input corpus    : {args.corpus}")
    print(f"  parquet shards  : {len(shards):,}")
    print(f"  first/last      : {shards[0].name} ... {shards[-1].name}")
    print(f"  output dir      : {args.out}")
    print(f"  compression     : {args.compression}")
    if use_dict:
        print(f"  dict size       : {args.dict_size:,} bytes ({args.dict_size//1024} KB)")
        print(f"  dict sample sh. : {args.dict_sample_shards}")
        print(f"  dict sample max : {args.dict_sample_bytes_per_shard:,} B per shard")
    print(f"  parallel workers: {args.parallel}")
    print("=" * 72, flush=True)

    # ---- Train (or load existing) dict ----------------------------------
    dict_bytes: bytes | None = None
    dict_path = args.out / "zstd.dict"
    if use_dict:
        if dict_path.exists():
            dict_bytes = dict_path.read_bytes()
            print(f"[dict] reusing existing dict {dict_path} ({len(dict_bytes):,} B)",
                  flush=True)
        else:
            dict_bytes = train_dict(
                shards, args.dict_size,
                args.dict_sample_shards,
                args.dict_sample_bytes_per_shard,
                seed=args.seed,
            )
            tmp = dict_path.with_suffix(".dict.tmp")
            tmp.write_bytes(dict_bytes)
            os.replace(tmp, dict_path)
            print(f"[dict] wrote {dict_path}", flush=True)

    # ---- Spawn pool ------------------------------------------------------
    print(f"[build] starting {args.parallel} workers over {len(shards):,} shards "
          f"({args.compression})", flush=True)
    t_build = time.perf_counter()
    tasks = [(sh, args.out) for sh in shards]
    raw_total = 0
    written_total = 0
    n_records_total = 0
    n_skipped = 0
    n_done = 0
    last_log = 0
    log_every_n = max(1, len(shards) // 50)  # ~50 progress lines

    # use_spawn=True (default on linux is "fork" but we want to be explicit).
    ctx = mp.get_context("forkserver")
    pool = ctx.Pool(
        processes=args.parallel,
        initializer=_worker_init,
        initargs=(None, family, level, dict_bytes),
    )
    try:
        for res in pool.imap_unordered(_process_shard, tasks, chunksize=1):
            n_done += 1
            raw_total += res.raw_bytes
            written_total += res.written_bytes
            n_records_total += res.n_records
            if res.skipped:
                n_skipped += 1
            if n_done - last_log >= log_every_n or n_done == len(shards):
                elapsed = time.perf_counter() - t_build
                eta = (elapsed / n_done) * (len(shards) - n_done) if n_done else 0
                rate_recs = n_records_total / max(elapsed, 1e-6)
                rate_mb = written_total / max(elapsed, 1e-6) / 1e6
                print(f"[build] {n_done:>5}/{len(shards):,}  "
                      f"records={n_records_total:>13,}  "
                      f"written={_human_bytes(written_total)}  "
                      f"{rate_recs/1e3:6.1f} kr/s  {rate_mb:6.1f} MB/s  "
                      f"eta={eta/60:5.1f} min  (skipped={n_skipped})",
                      flush=True)
                last_log = n_done
    finally:
        pool.close()
        pool.join()
    elapsed = time.perf_counter() - t_build

    # ---- Manifest + summary ---------------------------------------------
    manifest = {
        "version": 1,
        "compression": args.compression,
        "dict": ("zstd.dict" if use_dict else None),
        "dict_size_bytes": (len(dict_bytes) if dict_bytes else 0),
        "dict_sample_shards": args.dict_sample_shards if use_dict else 0,
        "n_shards": len(shards),
        "n_records": n_records_total,
        "raw_bytes": raw_total,
        "written_bytes": written_total,
        "ratio_x": (raw_total / written_total) if written_total else None,
        "build_seconds": round(elapsed, 2),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print("=" * 72)
    print(f"build_docstore done in {elapsed/60:.1f} min")
    print(f"  shards            : {len(shards):,} ({n_skipped} skipped)")
    print(f"  records           : {n_records_total:,}")
    print(f"  raw bytes         : {_human_bytes(raw_total)}")
    print(f"  written bytes     : {_human_bytes(written_total)}")
    if written_total and raw_total:
        print(f"  compression ratio : {raw_total/written_total:.3f}x")
        print(f"  saved             : {_human_bytes(raw_total - written_total)}")
    print(f"  manifest          : {args.out / 'manifest.json'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
