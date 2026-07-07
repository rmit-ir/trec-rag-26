#!/usr/bin/env python3
"""Create a reproducible ClimbMix shard sample manifest."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--total-shards", type=int, default=6543)
    ap.add_argument("--sample-shards", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.total_shards <= 0:
        raise SystemExit("--total-shards must be positive")
    if not (1 <= args.sample_shards <= args.total_shards):
        raise SystemExit("--sample-shards must be in [1, total-shards]")

    rng = random.Random(args.seed)
    indices = sorted(rng.sample(range(args.total_shards), args.sample_shards))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    txt_path = args.out_dir / "sampled_shards.txt"
    jsonl_path = args.out_dir / "sample_manifest.jsonl"
    meta_path = args.out_dir / "sample_meta.json"

    with txt_path.open("wt", encoding="utf-8") as f_txt, \
            jsonl_path.open("wt", encoding="utf-8") as f_jsonl:
        for pos, idx in enumerate(indices, start=1):
            filename = f"shard_{idx:05d}.parquet"
            rec = {
                "sample_position": pos,
                "shard_index": idx,
                "filename": filename,
                "repo_path": filename,
                "seed": args.seed,
                "sample_method": "uniform_without_replacement_over_shard_indices",
            }
            f_txt.write(filename + "\n")
            f_jsonl.write(json.dumps(rec, sort_keys=True) + "\n")

    meta = {
        "seed": args.seed,
        "total_shards": args.total_shards,
        "sample_shards": args.sample_shards,
        "indices": indices,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[sample_shards] wrote {jsonl_path}")
    print(f"[sample_shards] sampled {len(indices)} / {args.total_shards} shards")
    print(f"[sample_shards] first/last: {indices[0]} / {indices[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

