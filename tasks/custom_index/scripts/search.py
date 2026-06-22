#!/usr/bin/env python3
"""Reference search: load a built DiskANN index and run queries.

The index dir is the only input — it must contain:
  - the DiskANN index files (ann_*.bin etc. from build_diskann_index.py)
  - docids.txt           (parallel to vector rows)
  - encoding_meta.json   {model, dim, normalize, ...}
  - index_meta.json      {kind, metric, ...}

This is the contract the Rust serve task will mirror.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_docids(path: Path) -> list[str]:
    with open(path, "rt", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def search(
    index_dir: Path,
    queries: list[str],
    k: int = 10,
    complexity: int = 64,
    beam_width: int = 2,
    index_prefix: str = "ann",
):
    import numpy as np
    import diskannpy
    from sentence_transformers import SentenceTransformer

    enc = json.loads((index_dir / "encoding_meta.json").read_text())
    idx_meta = json.loads((index_dir / "index_meta.json").read_text())
    docids = load_docids(index_dir / "docids.txt")

    model = SentenceTransformer(enc["model"],
                                trust_remote_code=bool(enc.get("trust_remote_code", False)))
    encode_kwargs = {}
    if enc.get("task"):
        encode_kwargs["task"] = enc["task"]
    if enc.get("query_prompt_name"):
        encode_kwargs["prompt_name"] = enc["query_prompt_name"]
    q_vecs = model.encode(queries, convert_to_numpy=True,
                          normalize_embeddings=enc["normalize"],
                          **encode_kwargs).astype(np.float32, copy=False)

    kind = idx_meta["kind"]
    if kind == "disk":
        idx = diskannpy.StaticDiskIndex(
            index_directory=str(index_dir),
            num_threads=0,
            num_nodes_to_cache=10_000,
            cache_mechanism=1,
            distance_metric=idx_meta["metric"],
            vector_dtype=np.float32,
            dimensions=enc["dim"],
            index_prefix=index_prefix,
        )
        results = idx.batch_search(
            queries=q_vecs, k_neighbors=k, complexity=complexity,
            beam_width=beam_width, num_threads=0,
        )
    else:
        idx = diskannpy.StaticMemoryIndex(
            index_directory=str(index_dir),
            num_threads=0,
            initial_search_complexity=complexity,
            distance_metric=idx_meta["metric"],
            vector_dtype=np.float32,
            dimensions=enc["dim"],
            index_prefix=index_prefix,
        )
        results = idx.batch_search(
            queries=q_vecs, k_neighbors=k, complexity=complexity, num_threads=0,
        )

    out = []
    for qi, q in enumerate(queries):
        hits = []
        for rank in range(k):
            row = int(results.identifiers[qi, rank])
            score = float(results.distances[qi, rank])
            if 0 <= row < len(docids):
                hits.append({"docid": docids[row], "score": score, "rank": rank + 1})
        out.append({"query": q, "hits": hits})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", required=True, type=Path)
    ap.add_argument("--query", action="append", required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--complexity", type=int, default=64)
    ap.add_argument("--beam-width", type=int, default=2)
    ap.add_argument("--index-prefix", default="ann")
    args = ap.parse_args()

    out = search(
        args.index_dir, args.query,
        k=args.k, complexity=args.complexity, beam_width=args.beam_width,
        index_prefix=args.index_prefix,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
