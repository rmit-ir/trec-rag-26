#!/usr/bin/env python3
"""Build a chunk-id-keyed flat docstore, in parallel with encoding.

The docstore is the index's complement: whatever id the vector index stores
(here a chunk id ``shard_NNNNN_<docrow>_p<page>``), the docstore maps that SAME
id to its text. It is a sibling of the encode stage — both consume the chunking
output (chunk id + text exist the moment chunking finishes, before the encode's
internal length-sort), so this runs concurrently with encode_pretokenized.py on
CPU while the GPUs encode.

Why a new builder vs build_docstore.py: that one reads parquet and addresses
records positionally (docid ``<stem>_<row>`` == row-th record). Chunk ids are
NOT row-addressable (docs yield a variable number of chunks), and the encode
reorders rows by length, so serve must resolve by the chunk-id STRING. Hence a
per-shard id index.

Per corpus shard ``shard_NNNNN.jsonl`` (records {"id", "contents"}), writes:
  shard_NNNNN.bin          concatenated independently-decompressible zstd frames
  shard_NNNNN.offsets.bin  uint64[N+1] LE byte offsets into .bin (frame i = [i,i+1])
  shard_NNNNN.ids.bin      the N chunk ids, '\n'-joined, in the SAME row order
  (manifest.json: compression, dict, keyed_by="chunk_id", totals)

Lookup (reader side, added to FlatShardDocStore later):
  stem = chunk_id.rsplit("_p",1)[0].rsplit("_",1)[0]   # shard_NNNNN
  row  = {id: i for i, id in enumerate(ids_of(stem))}[chunk_id]
  text = zstd_decompress(bin[offsets[row]:offsets[row+1]])

Resumable: per-shard atomic (.tmp + rename); a shard is skipped when .bin,
.offsets.bin and .ids.bin all exist and the id count matches the offset table.

Run (parallel with encode; CPU-only):
  uv run --project tasks/custom_index python \
    tasks/custom_index/scripts/build_chunk_docstore.py \
    --corpus tasks/custom_index/work/climbmix-chunked/corpus \
    --out    data/built-indexes/climbmix-chunked/docstore \
    --compression zstd-9 --parallel 48
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
from dataclasses import dataclass
from pathlib import Path

CODECS = ("none", "zstd-3", "zstd-9", "zstd-19")


def parse_codec(s: str) -> tuple[str, int | None]:
    if s == "none":
        return "none", None
    if not s.startswith("zstd-"):
        raise ValueError(f"unsupported --compression {s!r}; choose from {CODECS}")
    level = int(s.split("-", 1)[1])
    if not (1 <= level <= 22):
        raise ValueError(f"zstd level must be in [1,22], got {level}")
    return "zstd", level


def _iter_jsonl(path: Path):
    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            yield r["id"], r["contents"]


# ---- dict training ----------------------------------------------------------

def _sample_from_shard(path: Path, max_bytes: int) -> list[bytes]:
    out, total = [], 0
    for _id, text in _iter_jsonl(path):
        b = text.encode("utf-8")
        out.append(b); total += len(b)
        if total >= max_bytes:
            break
    return out


def train_dict(shards: list[Path], dict_size: int, sample_shards: int,
               sample_bytes: int, seed: int = 0) -> bytes:
    import zstandard as zstd
    rng = random.Random(seed)
    pool = shards[:]; rng.shuffle(pool); pool = pool[:sample_shards]
    print(f"[dict] training on {len(pool)} sample shard(s), <= {sample_bytes/1e6:.0f} MB each",
          flush=True)
    samples: list[bytes] = []
    for sh in pool:
        recs = _sample_from_shard(sh, sample_bytes)
        samples.extend(recs)
        print(f"[dict]   {sh.name}: {len(recs):,} records", flush=True)
    t0 = time.perf_counter()
    cd = zstd.train_dictionary(dict_size, samples)
    print(f"[dict] trained {dict_size//1024} KB dict in {time.perf_counter()-t0:.1f}s", flush=True)
    return cd.as_bytes()


# ---- per-shard worker -------------------------------------------------------

@dataclass
class ShardResult:
    stem: str
    n_records: int
    raw_bytes: int
    written_bytes: int
    skipped: bool


_W: dict = {}


def _worker_init(family: str, level: int | None, dict_bytes: bytes | None) -> None:
    _W.update(family=family, level=level)
    if family == "zstd":
        import zstandard as zstd
        if dict_bytes:
            dd = zstd.ZstdCompressionDict(dict_bytes)
            _W["compressor"] = zstd.ZstdCompressor(level=level, dict_data=dd)
        else:
            _W["compressor"] = zstd.ZstdCompressor(level=level)


def _encode(b: bytes) -> bytes:
    if _W["family"] == "none":
        return b
    return _W["compressor"].compress(b)


def _complete(bin_p: Path, offs_p: Path, ids_p: Path) -> bool:
    if not (bin_p.exists() and offs_p.exists() and ids_p.exists()):
        return False
    # offsets has N+1 uint64; ids has N '\n'-terminated lines
    n_offs = offs_p.stat().st_size // 8 - 1
    if n_offs < 0:
        return False
    # cheap consistency: id line count == n_offs
    with open(ids_p, "rb") as f:
        n_ids = sum(1 for _ in f)
    return n_ids == n_offs and bin_p.stat().st_size >= 0


def _process_shard(args: tuple[Path, Path]) -> ShardResult:
    shard, out_dir = args
    stem = shard.stem
    bin_p = out_dir / f"{stem}.bin"
    offs_p = out_dir / f"{stem}.offsets.bin"
    ids_p = out_dir / f"{stem}.ids.bin"

    if _complete(bin_p, offs_p, ids_p):
        return ShardResult(stem, offs_p.stat().st_size // 8 - 1, 0,
                           bin_p.stat().st_size, True)

    tmp_bin = bin_p.with_suffix(".bin.tmp")
    tmp_offs = offs_p.with_suffix(".offsets.bin.tmp")
    tmp_ids = ids_p.with_suffix(".ids.bin.tmp")
    raw = written = n = 0
    with open(tmp_bin, "wb", buffering=1 << 20) as bf, \
         open(tmp_offs, "wb", buffering=1 << 20) as of, \
         open(tmp_ids, "wb", buffering=1 << 20) as idf:
        of.write(struct.pack("<Q", 0))
        for cid, text in _iter_jsonl(shard):
            rb = text.encode("utf-8")
            wb = _encode(rb)
            bf.write(wb)
            raw += len(rb); written += len(wb); n += 1
            of.write(struct.pack("<Q", written))
            idf.write(cid.encode("utf-8") + b"\n")
    os.replace(tmp_bin, bin_p)
    os.replace(tmp_offs, offs_p)
    os.replace(tmp_ids, ids_p)
    return ShardResult(stem, n, raw, written, False)


def _human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.2f} {u}"
        n /= 1024


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a chunk-id-keyed docstore.")
    ap.add_argument("--corpus", required=True, type=Path, help="dir of shard_*.jsonl (chunk jsonl)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--compression", default="zstd-9", choices=CODECS)
    ap.add_argument("--dict-size", type=int, default=1024 * 1024)
    ap.add_argument("--dict-sample-shards", type=int, default=1)
    ap.add_argument("--dict-sample-bytes-per-shard", type=int, default=270 * 1024 * 1024)
    ap.add_argument("--parallel", type=int, default=48)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    shards = sorted(args.corpus.glob("shard_*.jsonl"))
    if not shards:
        print(f"[build_chunk_docstore] no shard_*.jsonl under {args.corpus}", file=sys.stderr)
        return 2

    family, level = parse_codec(args.compression)
    use_dict = family == "zstd"
    print("=" * 72)
    print(f"build_chunk_docstore  corpus={args.corpus}  shards={len(shards):,}")
    print(f"  out={args.out}  compression={args.compression}  parallel={args.parallel}")
    print("=" * 72, flush=True)

    dict_bytes = None
    dict_path = args.out / "zstd.dict"
    if use_dict:
        if dict_path.exists():
            dict_bytes = dict_path.read_bytes()
            print(f"[dict] reuse {dict_path} ({len(dict_bytes):,} B)", flush=True)
        else:
            dict_bytes = train_dict(shards, args.dict_size, args.dict_sample_shards,
                                    args.dict_sample_bytes_per_shard, args.seed)
            tmp = dict_path.with_suffix(".dict.tmp")
            tmp.write_bytes(dict_bytes); os.replace(tmp, dict_path)

    t0 = time.perf_counter()
    tasks = [(sh, args.out) for sh in shards]
    raw_t = wr_t = rec_t = skip = done = last = 0
    log_every = max(1, len(shards) // 50)
    ctx = mp.get_context("forkserver")
    pool = ctx.Pool(args.parallel, initializer=_worker_init,
                    initargs=(family, level, dict_bytes))
    try:
        for r in pool.imap_unordered(_process_shard, tasks, chunksize=1):
            done += 1; raw_t += r.raw_bytes; wr_t += r.written_bytes
            rec_t += r.n_records; skip += int(r.skipped)
            if done - last >= log_every or done == len(shards):
                el = time.perf_counter() - t0
                eta = el / done * (len(shards) - done)
                print(f"[build] {done:>5}/{len(shards):,}  records={rec_t:>13,}  "
                      f"written={_human(wr_t)}  {rec_t/max(el,1e-6)/1e3:6.1f} kr/s  "
                      f"eta={eta/60:5.1f} min  (skipped={skip})", flush=True)
                last = done
    finally:
        pool.close(); pool.join()
    el = time.perf_counter() - t0

    manifest = {
        "version": 1,
        "compression": args.compression,
        "dict": ("zstd.dict" if use_dict else None),
        "dict_size_bytes": (len(dict_bytes) if dict_bytes else 0),
        "keyed_by": "chunk_id",
        "id_index": "ids.bin",
        "shard_of_rule": "chunk_id.rsplit('_p',1)[0].rsplit('_',1)[0]",
        "n_shards": len(shards),
        "n_records": rec_t,
        "raw_bytes": raw_t,
        "written_bytes": wr_t,
        "ratio_x": (raw_t / wr_t) if wr_t else None,
        "build_seconds": round(el, 2),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("=" * 72)
    print(f"done in {el/60:.1f} min  records={rec_t:,}  written={_human(wr_t)}  "
          f"ratio={raw_t/wr_t:.2f}x" if wr_t else "done")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
