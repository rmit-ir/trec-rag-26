#!/usr/bin/env python3
"""Score one or more TREC run files against the ClimbMix UMBRELA qrels.

Reports BOTH the raw metrics (unjudged = non-relevant) and the pool-bias-corrected
CONDENSED metrics (unjudged docs dropped from each ranked list), plus a judged-
coverage diagnostic. See worklogs/2026-07-23-rag25dev-umbrela-eval.md for why the
raw numbers are structurally low against a pool a system didn't contribute to.

Run:
  uv run --project tasks/custom_index python tasks/custom_index/scripts/score_run.py \
    --qrels-dir .../rag25-dev-umbrela-qrels \
    --run climbmix-chunked=/tmp/climbmix-chunked.rag25dev.run \
    --run old-dense-768=/tmp/old-dense.rag25dev.run \
    --run bm25=/tmp/bm25.rag25dev.run
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytrec_eval

MEAS = {"ndcg_cut.10", "ndcg_cut.20", "ndcg_cut.100", "map", "P.10", "recall.100", "recall.1000"}
REP = ["ndcg_cut_10", "ndcg_cut_20", "P_10", "map", "recall_100", "recall_1000"]


def load_qrels(p: Path) -> dict[str, dict[str, int]]:
    q: dict[str, dict[str, int]] = {}
    for line in open(p):
        a = line.split()
        if len(a) == 4:
            q.setdefault(a[0], {})[a[2]] = int(a[3])
    return q


def load_run(p: Path) -> dict[str, dict[str, float]]:
    run: dict[str, dict[str, float]] = {}
    for line in open(p):
        a = line.split()
        if len(a) >= 6:
            run.setdefault(a[0], {})[a[2]] = float(a[4])
    return run


def agg(run, qrels) -> dict[str, float]:
    per = pytrec_eval.RelevanceEvaluator(qrels, MEAS).evaluate(run)
    n = len(per)
    return {m: (sum(x[m] for x in per.values()) / n if n else 0.0) for m in REP}


def condense(run, qrels) -> dict[str, dict[str, float]]:
    return {t: {d: s for d, s in docs.items() if d in qrels.get(t, {})}
            for t, docs in run.items()}


def coverage(run, qrels, k: int) -> tuple[float, float]:
    cov, rel = [], []
    for t in qrels:
        docs = sorted(run.get(t, {}).items(), key=lambda kv: kv[1], reverse=True)[:k]
        if not docs:
            continue
        cov.append(sum(1 for d, _ in docs if d in qrels[t]) / len(docs))
        rel.append(sum(1 for d, _ in docs if qrels[t].get(d, 0) >= 1) / len(docs))
    n = len(cov) or 1
    return sum(cov) / n, sum(rel) / n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qrels-dir", required=True, type=Path)
    ap.add_argument("--qrels-glob", default="*.qrels")
    ap.add_argument("--run", action="append", required=True,
                    help="NAME=path/to/run (repeatable)")
    args = ap.parse_args()

    runs = {}
    for spec in args.run:
        name, _, path = spec.partition("=")
        runs[name] = load_run(Path(path))

    qrels_files = sorted(args.qrels_dir.glob(args.qrels_glob))
    for qf in qrels_files:
        qrels = load_qrels(qf)
        judge = qf.name.replace("rag25-climbmix-umbrela-", "").replace(".qrels", "")
        print("=" * 108)
        print(f"JUDGE: {judge}")
        print("=" * 108)
        hdr = f"{'system':<20} {'set':<11} " + " ".join(f"{m:>11}" for m in REP) + "   jcov@10"
        print(hdr)
        print("-" * len(hdr))
        for name, run in runs.items():
            raw = agg(run, qrels)
            cnd = agg(condense(run, qrels), qrels)
            jc10, _ = coverage(run, qrels, 10)
            print(f"{name:<20} {'raw':<11} " + " ".join(f"{raw[m]:>11.4f}" for m in REP)
                  + f"   {jc10:>6.3f}")
            print(f"{'':<20} {'condensed':<11} " + " ".join(f"{cnd[m]:>11.4f}" for m in REP))
        print()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
