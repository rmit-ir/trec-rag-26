#!/usr/bin/env python3
"""Convert ClimbMix parquet shards -> Anserini JsonCollection (.jsonl).

Each parquet shard ``shard_NNNNN.parquet`` (single ``text`` column) becomes one
``shard_NNNNN.jsonl`` with one JSON object per row:

    {"id": "shard_NNNNN_<row>", "contents": "<text>"}

The ``id`` scheme mirrors the dense index / docstore
(``build_docstore.py``: docid ``<shard_stem>_<row>``, row 0-based), so BM25
docids line up 1:1 with the DiskANN side for later fusion.

Anserini indexes files in parallel across the output directory, so one .jsonl
per input shard gives natural parallelism for ``-threads N``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq

_SHARD_RE = re.compile(r"shard_(\d{5})\.parquet$")


def shard_num(p: Path) -> int:
    m = _SHARD_RE.search(p.name)
    if not m:
        raise ValueError(f"not a shard_NNNNN.parquet file: {p}")
    return int(m.group(1))


def convert_one(src: Path, out_dir: Path, batch_rows: int = 8192,
                overwrite: bool = False) -> tuple[str, int]:
    n = shard_num(src)
    stem = f"shard_{n:05d}"
    dst = out_dir / f"{stem}.jsonl"
    tmp = out_dir / f"{stem}.jsonl.tmp"
    if dst.exists() and not overwrite:
        return stem, -1  # already done, sentinel

    pf = pq.ParquetFile(src)
    row = 0
    # dumps once, fast path; ensure_ascii=False keeps UTF-8 bytes compact
    with tmp.open("w", encoding="utf-8") as fh:
        for batch in pf.iter_batches(batch_size=batch_rows, columns=["text"]):
            texts = batch.column(0).to_pylist()
            buf = []
            for t in texts:
                buf.append(json.dumps(
                    {"id": f"{stem}_{row}", "contents": t if t is not None else ""},
                    ensure_ascii=False))
                row += 1
            fh.write("\n".join(buf))
            fh.write("\n")
    tmp.rename(dst)
    return stem, row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True,
                    help="dir of shard_NNNNN.parquet")
    ap.add_argument("--out", type=Path, required=True,
                    help="output dir for .jsonl files")
    ap.add_argument("--start", type=int, default=0, help="first shard num (incl)")
    ap.add_argument("--end", type=int, default=None,
                    help="last shard num (excl); default = all")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel shard converters (process pool)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    shards = sorted(args.corpus.glob("shard_*.parquet"), key=shard_num)
    shards = [s for s in shards if shard_num(s) >= args.start
              and (args.end is None or shard_num(s) < args.end)]
    if not shards:
        print(f"[convert] no shards in range under {args.corpus}", file=sys.stderr)
        return 1

    n = len(shards)
    total_docs = 0
    done = 0
    if args.workers <= 1:
        for src in shards:
            stem, rows = convert_one(src, args.out, overwrite=args.overwrite)
            done += 1
            tag = "(skip, exists)" if rows < 0 else f"{rows:,} docs"
            total_docs += max(rows, 0)
            print(f"[convert] {stem}  {tag}  [{done}/{n}]", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(convert_one, src, args.out, 8192, args.overwrite): src
                    for src in shards}
            for fut in as_completed(futs):
                stem, rows = fut.result()
                done += 1
                tag = "(skip, exists)" if rows < 0 else f"{rows:,} docs"
                total_docs += max(rows, 0)
                print(f"[convert] {stem}  {tag}  [{done}/{n}]", flush=True)
    print(f"[convert] done: {n} shards, {total_docs:,} new docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
