#!/usr/bin/env python3
"""Measure streaming-encode throughput on a full shard at multiple orderings.

Mimics what encode_documents.py actually does in production: streams a shard
of texts and calls ``model.encode([batch])`` per batch of size --batch-size,
so sentence-transformers can only length-sort *within* a batch — not across
the whole shard.

We then run the same shard under several orderings (e.g. ``original`` and
``sorted-desc``) and report docs/s for each. This isolates the speedup that
prepare_corpus.sh's SORT=desc step actually delivers on the production code
path (separate from the tuner's bulk-encode, which secretly benefits from
ST's internal sort).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def load_all(shard: Path, limit: int = 0) -> list[str]:
    texts: list[str] = []
    with open(shard, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            texts.append(json.loads(line)["contents"])
            if limit and len(texts) >= limit:
                break
    return texts


def reorder(texts: list[str], order: str) -> list[str]:
    if order == "original":
        return list(texts)
    if order == "sorted-desc":
        return sorted(texts, key=len, reverse=True)
    if order == "sorted-asc":
        return sorted(texts, key=len)
    if order == "shuffled":
        import random
        out = list(texts)
        random.Random(0).shuffle(out)
        return out
    raise ValueError(f"unknown --order: {order}")


def stream_encode(model, texts: list[str], batch_size: int, encode_kwargs: dict,
                  log_every_docs: int = 10_000) -> tuple[float, float]:
    """Encode in small batches like encode_documents.py does. Returns
    (docs_per_sec, total_seconds)."""
    import torch

    n = len(texts)
    t0 = time.time()
    last_log = 0
    for i in range(0, n, batch_size):
        batch = texts[i:i + batch_size]
        model.encode(
            batch,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            **encode_kwargs,
        )
        if (i + batch_size) - last_log >= log_every_docs:
            torch.cuda.synchronize()
            elapsed = time.time() - t0
            rate = (i + batch_size) / max(elapsed, 1e-6)
            print(f"    {i + batch_size}/{n}  ({rate:.1f} docs/s)", flush=True)
            last_log = i + batch_size
    torch.cuda.synchronize()
    elapsed = time.time() - t0
    return n / elapsed, elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--batch-size", type=int, required=True)
    ap.add_argument("--max-seq-len", type=int, required=True)
    ap.add_argument("--orders", nargs="+", default=["original", "sorted-desc"],
                    choices=["original", "sorted-desc", "sorted-asc", "shuffled"])
    ap.add_argument("--limit", type=int, default=0, help="0 = full shard")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--task", default="retrieval")
    ap.add_argument("--prompt-name", default="document")
    ap.add_argument("--trust-remote-code", action="store_true", default=True)
    ap.add_argument("--dtype", default="bfloat16",
                    choices=["float32", "float16", "bfloat16"])
    args = ap.parse_args()

    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)

    import torch
    from sentence_transformers import SentenceTransformer

    if not torch.cuda.is_available():
        print("[bench] no CUDA available — aborting", file=sys.stderr)
        return 2

    dtype = {"float32": torch.float32, "float16": torch.float16,
             "bfloat16": torch.bfloat16}[args.dtype]

    print(f"[bench] gpu={args.gpu} model={args.model} dtype={dtype} "
          f"batch={args.batch_size} seq_len={args.max_seq_len}", flush=True)
    model = SentenceTransformer(
        args.model,
        device="cuda",
        trust_remote_code=args.trust_remote_code,
        model_kwargs={"dtype": dtype},
    )
    model.max_seq_length = args.max_seq_len

    encode_kwargs: dict = {}
    if args.task:
        encode_kwargs["task"] = args.task
    if args.prompt_name:
        encode_kwargs["prompt_name"] = args.prompt_name

    texts = load_all(args.shard, args.limit)
    print(f"[bench] loaded {len(texts)} docs from {args.shard.name}", flush=True)

    # Warmup — kernels JIT once, not counted in any timed run.
    print(f"[bench] warmup...", flush=True)
    model.encode(texts[:32], batch_size=args.batch_size, convert_to_numpy=True,
                 normalize_embeddings=True, show_progress_bar=False,
                 **encode_kwargs)
    torch.cuda.synchronize()

    results: list[tuple[str, float, float]] = []
    for order in args.orders:
        print(f"\n=== order = {order} ===", flush=True)
        run_texts = reorder(texts, order)
        rate, elapsed = stream_encode(model, run_texts, args.batch_size, encode_kwargs)
        print(f"  → {order}: {rate:.1f} docs/s ({elapsed:.1f}s for {len(run_texts)} docs)",
              flush=True)
        results.append((order, rate, elapsed))

    print("\nsummary:")
    print(f"{'order':>14} {'docs/s':>10} {'seconds':>10}")
    print("-" * 38)
    for order, rate, elapsed in results:
        print(f"{order:>14} {rate:>10.1f} {elapsed:>10.1f}")
    if len(results) >= 2:
        base = results[0][1]
        for order, rate, _ in results[1:]:
            pct = 100.0 * (rate - base) / base if base > 0 else 0.0
            print(f"   {order} vs {results[0][0]}: {pct:+.1f}% ({rate - base:+.1f} docs/s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
