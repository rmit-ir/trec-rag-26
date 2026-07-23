#!/usr/bin/env python3
"""Evaluate a built index on the RAG25 dev topics against the ClimbMix UMBRELA qrels.

The official dev data ships UMBRELA relevance judgments *projected onto ClimbMix*
(``rag25-climbmix-umbrela-*.qrels``), keyed by PARENT docid ``shard_NNNNN_docrow``.
Our index returns CHUNK ids ``shard_NNNNN_docrow_pN`` (one doc -> many page chunks),
so we run each topic, collapse chunk hits to their parent doc (keeping the best-
scoring chunk per doc = max-pooling over pages), and score the resulting doc run
with pytrec_eval against every judge variant.

Notes / caveats:
  - The qrels are POOLED (LLM judgments over a candidate pool, not corpus-wide),
    so anything we retrieve outside the pool is treated as non-relevant by
    trec_eval. Absolute recall is bounded by the pool; nDCG@10 is the headline
    metric UMBRELA is designed for.
  - Scores are graded 0-4; nDCG uses the grades, MAP/recall use rel>=1.

Run:
  uv run --project tasks/custom_index python \
    tasks/custom_index/scripts/eval_umbrela.py \
    --index-dir data/built-indexes/climbmix-chunked \
    --topics data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/rag25-topics-dev.tsv \
    --qrels-dir data/official/trec-rag-2026-data/trec-rag-2026/development-data/rag25-dev-umbrela-qrels \
    --k 2000 --complexity 2000 --depth 1000 --num-threads 8 --beam-width 4 \
    --run-out /tmp/climbmix-chunked.rag25dev.run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytrec_eval

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search import search  # noqa: E402


def load_topics(path: Path) -> list[tuple[str, str]]:
    topics = []
    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            qid, _, query = line.partition("\t")
            topics.append((qid.strip(), query.strip()))
    return topics


def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) != 4:
                continue
            qid, _, docid, rel = parts
            qrels.setdefault(qid, {})[docid] = int(rel)
    return qrels


def parent_of(chunk_id: str) -> str:
    """shard_NNNNN_docrow_pN -> shard_NNNNN_docrow (parent doc, qrels key)."""
    return chunk_id.rsplit("_p", 1)[0]


def build_run(topics, results, depth: int) -> dict[str, dict[str, float]]:
    run: dict[str, dict[str, float]] = {}
    for (qid, _q), res in zip(topics, results):
        best: dict[str, float] = {}
        for h in res["hits"]:
            d = parent_of(h["docid"])
            s = h["score"]
            if d not in best or s > best[d]:  # max-pool pages -> doc
                best[d] = s
        top = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:depth]
        run[qid] = {d: float(s) for d, s in top}
    return run


def write_trec_run(run: dict[str, dict[str, float]], path: Path, tag: str) -> None:
    with open(path, "wt", encoding="utf-8") as f:
        for qid, docs in run.items():
            for rank, (docid, score) in enumerate(
                sorted(docs.items(), key=lambda kv: kv[1], reverse=True), start=1
            ):
                f.write(f"{qid} Q0 {docid} {rank} {score:.6f} {tag}\n")


MEASURES = {"ndcg_cut.10", "ndcg_cut.20", "ndcg_cut.100",
            "recall.100", "recall.1000", "map", "P.10"}
REPORT = ["ndcg_cut_10", "ndcg_cut_20", "ndcg_cut_100",
          "map", "recall_100", "recall_1000", "P_10"]


def evaluate(run, qrels) -> tuple[dict[str, float], int]:
    ev = pytrec_eval.RelevanceEvaluator(qrels, MEASURES)
    per_q = ev.evaluate(run)
    n = len(per_q)
    agg = {}
    for m in REPORT:
        agg[m] = sum(q[m] for q in per_q.values()) / n if n else 0.0
    return agg, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", required=True, type=Path)
    ap.add_argument("--topics", required=True, type=Path)
    ap.add_argument("--qrels-dir", required=True, type=Path)
    ap.add_argument("--qrels-glob", default="*.qrels")
    ap.add_argument("--k", type=int, default=2000, help="chunks retrieved per query")
    ap.add_argument("--complexity", type=int, default=2000)
    ap.add_argument("--beam-width", type=int, default=4)
    ap.add_argument("--num-threads", type=int, default=8)
    ap.add_argument("--depth", type=int, default=1000, help="docs kept per query in the run")
    ap.add_argument("--run-out", type=Path, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    topics = load_topics(args.topics)
    print(f"[eval] {len(topics)} topics; retrieving k={args.k} chunks "
          f"(complexity={args.complexity}) then collapsing to <= {args.depth} docs",
          flush=True)

    results = search(
        args.index_dir, [q for _, q in topics],
        k=args.k, complexity=args.complexity,
        beam_width=args.beam_width, num_threads=args.num_threads,
    )
    run = build_run(topics, results, args.depth)
    avg_docs = sum(len(v) for v in run.values()) / len(run)
    print(f"[eval] built run: mean {avg_docs:.0f} unique docs/topic "
          f"(from {args.k} chunks)", flush=True)

    if args.run_out:
        write_trec_run(run, args.run_out, tag="climbmix-chunked")
        print(f"[eval] wrote TREC run -> {args.run_out}", flush=True)

    qrels_files = sorted(args.qrels_dir.glob(args.qrels_glob))
    print(f"[eval] scoring against {len(qrels_files)} qrels variant(s)\n", flush=True)

    summary = {}
    header = f"{'judge qrels':<52} " + " ".join(f"{m:>12}" for m in REPORT)
    print(header)
    print("-" * len(header))
    for qf in qrels_files:
        qrels = load_qrels(qf)
        agg, n = evaluate(run, qrels)
        summary[qf.name] = {"n_topics": n, **agg}
        name = qf.name.replace("rag25-climbmix-umbrela-", "").replace(".qrels", "")
        print(f"{name:<52} " + " ".join(f"{agg[m]:>12.4f}" for m in REPORT))

    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2))
        print(f"\n[eval] wrote metrics -> {args.json_out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
