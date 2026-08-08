#!/usr/bin/env python3
"""Freeze the dev / confirm / holdout topic splits for the prompt-optimization loop.

The optimization loop needs splits that are **fixed before the first variant is
scored**, because the whole failure mode of a hill-climb over an LLM judge is
that the same topics get re-used until a prompt fits their idiosyncrasies. Once
written, these three files do not change; a variant is screened on dev20,
confirmed on confirm40, and the 59 holdout topics are touched at most once, at
the very end.

**Stratified on the outcome we are trying to move**, not on topic text. Every
topic gets a difficulty score in [0, 1] = the mean of the two published runs'
(``ours-semantic``, ``ours-keyword``) both-order arena outcome against
``base-agentic-bm25``, read out of the cached judgments in
``data/task-comparison/test119-eval/arena-judgments/``. Topics we already lose in
both orders score 0; topics we already win score 1. Sorting by that score and
assigning positions ``i % 6`` gives each split the same win/split/loss mix as the
full 119 — which matters because 2026-08-05 showed ``topics10`` (``rag2026-0..9``)
is *not* representative: ``base-agentic-bm25`` scores 9.6 numerals/1k there
against 15.6 over all 119.

Deterministic — no RNG, no seed to record. Re-running reproduces the same files.

    uv run --no-project python \
        tasks/task-comparison/scripts/make_optimize_splits.py
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVAL = ROOT / "data/task-comparison/test119-eval"
ARENA = EVAL / "arena-judgments/gpt-5.6-luna"
TOPICS_TSV = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
              / "test-data/trec_rag_2026_queries.tsv")
OUT_DIR = ROOT / "data/task-comparison"
OPPONENT = "base-agentic-bm25"
OURS = ("ours-semantic", "ours-keyword")

# (filename stem, modulus residues that land in it). 119 topics, i % 6:
# residue 0 -> 20 topics, residues 1,2 -> 40, residues 3,4,5 -> 59.
SPLITS = (("topics-dev20", {0}), ("topics-confirm40", {1, 2}),
          ("topics-holdout59", {3, 4, 5}))


def load_topics() -> dict[str, str]:
    """narrative_id -> narrative text, in the official file's order."""
    topics: dict[str, str] = {}
    for line in TOPICS_TSV.read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid, _, narrative = line.partition("\t")
            topics[qid.strip()] = narrative.strip()
    return topics


def both_order_outcome(label: str) -> dict[str, float]:
    """1.0 if ``label`` won both presentation orders, 0.0 if it lost both, else 0.5.

    A topic where the judge flips on order carries no preference signal, so it
    scores exactly halfway rather than being dropped — dropping them would bias
    the strata toward topics the judge happens to find easy.
    """
    seen: dict[str, dict[int, str | None]] = collections.defaultdict(dict)
    for path in ARENA.glob(f"*__{label}__{OPPONENT}__o*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("status") == "completed":
            seen[rec["topic_id"]][rec["orientation"]] = rec["preferred_run_id"]
    out = {}
    for qid, orientations in seen.items():
        if len(orientations) < 2:
            continue
        votes = list(orientations.values())
        if all(v == label for v in votes):
            out[qid] = 1.0
        elif all(v == OPPONENT for v in votes):
            out[qid] = 0.0
        else:
            out[qid] = 0.5
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--force", action="store_true",
                        help="overwrite splits that already exist")
    args = parser.parse_args()

    topics = load_topics()
    outcomes = {label: both_order_outcome(label) for label in OURS}
    scored = []
    for qid in topics:
        votes = [outcomes[label][qid] for label in OURS if qid in outcomes[label]]
        # A topic with no cached judgment sorts to the middle rather than to an
        # edge, so a partially-judged tree still produces balanced splits.
        scored.append((sum(votes) / len(votes) if votes else 0.5, qid))
    scored.sort(key=lambda pair: (pair[0], int(pair[1].split("-")[1])))

    existing = [name for name, _ in SPLITS
                if (args.out_dir / f"{name}.tsv").exists()]
    if existing and not args.force:
        print(f"refusing to overwrite {existing} — these are frozen by design.\n"
              f"pass --force only if no variant has been scored against them yet.")
        return 1

    assigned: dict[str, list[str]] = {name: [] for name, _ in SPLITS}
    for i, (_score, qid) in enumerate(scored):
        for name, residues in SPLITS:
            if i % 6 in residues:
                assigned[name].append(qid)
                break

    lookup = dict((qid, score) for score, qid in scored)
    for name, _ in SPLITS:
        qids = sorted(assigned[name], key=lambda q: int(q.split("-")[1]))
        path = args.out_dir / f"{name}.tsv"
        path.write_text("".join(f"{q}\t{topics[q]}\n" for q in qids),
                        encoding="utf-8")
        mix = collections.Counter(lookup[q] for q in qids)
        current = sum(lookup[q] for q in qids) / len(qids)
        print(f"{path.name:22s} {len(qids):3d} topics  "
              f"current both-order rate {current:.3f}  "
              f"strata {dict(sorted(mix.items()))}")

    overall = sum(s for s, _ in scored) / len(scored)
    print(f"\nfull 119                current both-order rate {overall:.3f}"
          f"  (mean of ours-semantic and ours-keyword vs {OPPONENT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
