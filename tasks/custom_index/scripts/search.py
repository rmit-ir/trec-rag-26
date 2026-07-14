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


def _read_int(p: str) -> int | None:
    """Read an int from a /proc sysctl path; None if unreadable."""
    try:
        with open(p, "rt") as f:
            return int(f.read().strip())
    except OSError:
        return None


def log_aio_slots(stage: str, num_threads: int | None = None) -> None:
    """Print Linux libaio context budget + current usage.

    DiskANN calls io_setup() per search thread, reserving slots from the
    system-wide pool capped by /proc/sys/fs/aio-max-nr. Hitting the cap throws
    EAGAIN -> diskannpy C++ terminate. Useful to surface at startup so a
    crowded box is caught before we shell out to DiskANN.
    """
    used = _read_int("/proc/sys/fs/aio-nr")
    cap = _read_int("/proc/sys/fs/aio-max-nr")
    if used is None or cap is None:
        print(f"[aio {stage}] /proc/sys/fs/aio-{{nr,max-nr}} unreadable", flush=True)
        return
    free = cap - used
    extra = f"  num_threads={num_threads}" if num_threads is not None else ""
    print(f"[aio {stage}] used={used:,}  cap={cap:,}  free={free:,}{extra}",
          flush=True)


def search(
    index_dir: Path,
    queries: list[str],
    k: int = 10,
    complexity: int = 64,
    beam_width: int = 2,
    num_threads: int = 4,
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
    # Matryoshka index: queries must get the same truncate + L2 renorm the
    # document vectors got (see truncate_vectors.py).
    if enc.get("matryoshka_truncated_from"):
        q_vecs = np.ascontiguousarray(q_vecs[:, : int(enc["dim"])])
        norms = np.linalg.norm(q_vecs, axis=1, keepdims=True)
        np.divide(q_vecs, norms, out=q_vecs, where=norms > 0)

    kind = idx_meta["kind"]
    log_aio_slots("before", num_threads=num_threads)
    if kind == "disk":
        idx = diskannpy.StaticDiskIndex(
            index_directory=str(index_dir),
            num_threads=num_threads,
            num_nodes_to_cache=10_000,
            cache_mechanism=1,
            distance_metric=idx_meta["metric"],
            vector_dtype=np.float32,
            dimensions=enc["dim"],
            index_prefix=index_prefix,
        )
        log_aio_slots("after StaticDiskIndex", num_threads=num_threads)
        results = idx.batch_search(
            queries=q_vecs, k_neighbors=k, complexity=complexity,
            beam_width=beam_width, num_threads=num_threads,
        )
    else:
        idx = diskannpy.StaticMemoryIndex(
            index_directory=str(index_dir),
            num_threads=num_threads,
            initial_search_complexity=complexity,
            distance_metric=idx_meta["metric"],
            vector_dtype=np.float32,
            dimensions=enc["dim"],
            index_prefix=index_prefix,
        )
        results = idx.batch_search(
            queries=q_vecs, k_neighbors=k, complexity=complexity,
            num_threads=num_threads,
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
    ap.add_argument("--num-threads", type=int, default=4,
                    help="DiskANN search-thread count. Each thread allocates one "
                         "libaio io_context from /proc/sys/fs/aio-max-nr, so "
                         "keep this low for shared boxes. 0 = let DiskANN pick.")
    ap.add_argument("--index-prefix", default="ann")
    args = ap.parse_args()

    out = search(
        args.index_dir, args.query,
        k=args.k, complexity=args.complexity, beam_width=args.beam_width,
        num_threads=args.num_threads, index_prefix=args.index_prefix,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
