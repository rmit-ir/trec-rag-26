#!/usr/bin/env python3
"""Compare index-server search results against an Anserini reference TREC run.

Queries index-server's REST API for each topic, builds a TREC run, and diffs it
against an Anserini-produced run: per-query exact-order match, top-k doc overlap,
and max score delta. Used to prove BM25 and BM25+RM3 parity with Anserini.

Usage:
  compare.py --topics topics.tsv --ref runs/anserini.bm25.txt \
             --url http://127.0.0.1:8080 --hits 20 [--prf rm3 ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


def load_trec_run(path: Path) -> dict[str, list[tuple[str, float]]]:
    """qid -> [(docid, score), ...] in rank order."""
    run: dict[str, list[tuple[str, float]]] = {}
    for line in path.read_text().splitlines():
        p = line.split()
        if len(p) < 6:
            continue
        qid, _, docid, _, score, _ = p[:6]
        run.setdefault(qid, []).append((docid, float(score)))
    return run


def query_index_server(url: str, query: str, hits: int, prf: str | None,
                        prf_params: dict) -> list[tuple[str, float]]:
    body: dict = {"query": query, "hits": hits}
    if prf and prf != "none":
        body["prf"] = prf
        body.update(prf_params)
    req = urllib.request.Request(
        f"{url}/api/search", method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.load(r)
    out = []
    for h in resp["hits"]["hits"]:
        out.append((h["_id"], float(h["_score"])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", type=Path, required=True)
    ap.add_argument("--ref", type=Path, required=True, help="Anserini TREC run")
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--hits", type=int, default=20)
    ap.add_argument("--prf", default=None, help="none|rm3|rocchio")
    ap.add_argument("--fbTerms", type=int, default=10)
    ap.add_argument("--fbDocs", type=int, default=10)
    ap.add_argument("--originalQueryWeight", type=float, default=0.5)
    ap.add_argument("--score-tol", type=float, default=1e-3,
                    help="abs score tolerance for 'identical'")
    ap.add_argument("--out", type=Path, default=None, help="write our run here")
    args = ap.parse_args()

    prf_params = {"fbTerms": args.fbTerms, "fbDocs": args.fbDocs,
                  "originalQueryWeight": args.originalQueryWeight}

    ref = load_trec_run(args.ref)
    topics = {}
    for line in args.topics.read_text().splitlines():
        if not line.strip():
            continue
        qid, q = line.split("\t", 1)
        topics[qid] = q

    our_run_lines = []
    n_exact = 0
    n_topk_match = 0
    worst_score_delta = 0.0
    total = 0
    print(f"{'qid':>4} {'exact_order':>11} {'top10_overlap':>13} {'max_score_delta':>15}")
    for qid, q in topics.items():
        total += 1
        ours = query_index_server(args.url, q, args.hits, args.prf, prf_params)
        refs = ref.get(qid, [])
        for rank, (docid, score) in enumerate(ours, 1):
            our_run_lines.append(f"{qid} Q0 {docid} {rank} {score:.6f} index-server")

        our_ids = [d for d, _ in ours]
        ref_ids = [d for d, _ in refs]
        k = min(10, len(our_ids), len(ref_ids))
        exact = our_ids[:len(ref_ids)] == ref_ids[:len(our_ids)]
        topk_overlap = len(set(our_ids[:k]) & set(ref_ids[:k]))
        # score delta on shared docids by rank position
        ref_score = {d: s for d, s in refs}
        deltas = [abs(s - ref_score[d]) for d, s in ours if d in ref_score]
        maxd = max(deltas) if deltas else float("nan")
        worst_score_delta = max(worst_score_delta,
                                maxd if maxd == maxd else 0.0)
        if exact:
            n_exact += 1
        if topk_overlap == k:
            n_topk_match += 1
        print(f"{qid:>4} {str(exact):>11} {f'{topk_overlap}/{k}':>13} {maxd:>15.6f}")

    print("-" * 48)
    print(f"exact-order queries : {n_exact}/{total}")
    print(f"top10 full-overlap  : {n_topk_match}/{total}")
    print(f"worst score delta   : {worst_score_delta:.6f} "
          f"(tol {args.score_tol})")
    verdict = (n_exact == total and worst_score_delta <= args.score_tol)
    print(f"VERDICT: {'MATCH' if verdict else 'MISMATCH'}")

    if args.out:
        args.out.write_text("\n".join(our_run_lines) + "\n")
        print(f"wrote our run -> {args.out}")
    return 0 if verdict else 2


if __name__ == "__main__":
    raise SystemExit(main())
