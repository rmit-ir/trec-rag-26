#!/usr/bin/env python3
"""Sanity-judge the fine-tuned model on the single test index.

Two checks:
  1. Self-retrieval: take the first ~15 words of N random chunks as queries;
     a healthy embedding space ranks the *source chunk* (or a sibling chunk of
     the same parent doc) at/near the top. Reports hit@1/@10 + MRR — objective,
     no human judgment needed.
  2. Topical queries: run a handful of natural questions, print the top-10 chunk
     texts so relevance can be judged by reading.

CPU only (GPUs hidden by caller). Query encoding uses the index's own model +
prompt scheme (Query:) via search.search().
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path("/mnt/raid10/e128356/projects/trec-rag-26")
sys.path.insert(0, str(REPO / "tasks/custom_index/scripts"))
from search import search  # noqa: E402


def load_corpus(shard: Path) -> dict[str, str]:
    d = {}
    with open(shard, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                d[r["id"]] = r["contents"]
    return d


def parent(cid: str) -> str:
    return cid.rsplit("_p", 1)[0]


def snippet(t: str, n: int = 220) -> str:
    return re.sub(r"\s+", " ", t)[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", required=True, type=Path)
    ap.add_argument("--corpus-shard", required=True, type=Path)
    ap.add_argument("--n-self", type=int, default=40)
    ap.add_argument("--complexity", type=int, default=200)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    corpus = load_corpus(args.corpus_shard)
    ids = list(corpus)
    print(f"[judge] corpus chunks in shard: {len(ids):,}")

    # ---- 1. self-retrieval ----
    import random
    rng = random.Random(args.seed)
    picks = rng.sample(ids, min(args.n_self, len(ids)))
    queries = []
    for cid in picks:
        words = corpus[cid].split()
        # skip trivially short chunks; take a mid-slice so it's not always the head
        q = " ".join(words[:18]) if len(words) >= 8 else corpus[cid]
        queries.append(q)
    res = search(args.index_dir, queries, k=10, complexity=args.complexity,
                 beam_width=4, num_threads=8)
    hit1 = hit10 = 0
    mrr = 0.0
    sib10 = 0
    for cid, r in zip(picks, res):
        got = [h["docid"] for h in r["hits"]]
        rank = got.index(cid) + 1 if cid in got else 0
        if rank == 1:
            hit1 += 1
        if rank:
            hit10 += 1
            mrr += 1.0 / rank
        if any(parent(g) == parent(cid) for g in got):
            sib10 += 1
    n = len(picks)
    print(f"\n=== self-retrieval (n={n}, query=first 18 words) ===")
    print(f"  hit@1  (exact chunk): {hit1}/{n} = {hit1/n:.2f}")
    print(f"  hit@10 (exact chunk): {hit10}/{n} = {hit10/n:.2f}")
    print(f"  hit@10 (same parent): {sib10}/{n} = {sib10/n:.2f}")
    print(f"  MRR@10 (exact chunk): {mrr/n:.3f}")

    # ---- 2. topical queries ----
    topical = [
        "What causes inflation in an economy?",
        "How do vaccines train the immune system?",
        "symptoms and treatment of type 2 diabetes",
        "How does a solar panel convert sunlight into electricity?",
        "best practices for training deep neural networks",
    ]
    tres = search(args.index_dir, topical, k=10, complexity=args.complexity,
                  beam_width=4, num_threads=8)
    print("\n=== topical top-10 (judge by reading) ===")
    for q, r in zip(topical, tres):
        print(f"\n>>> QUERY: {q}")
        for h in r["hits"]:
            txt = corpus.get(h["docid"], "<text missing>")
            print(f"  [{h['rank']:>2}] {h['docid']}  score={h['score']:.4f}")
            print(f"       {snippet(txt)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
