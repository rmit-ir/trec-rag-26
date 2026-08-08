#!/usr/bin/env python3
"""Offline answer/criterion oracle analysis over already-paid rubric verdicts.

No provider is imported or called.  The script consumes the append-only result
ledger plus rubric-eval caches, and prints every topic-level routing decision so
the aggregate cannot hide an overfit or a missing topic.
"""
from __future__ import annotations

import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs/auto-optimize/rubric-results.jsonl"
RUBRICS = ROOT / "data/task-comparison/dev-rubrics-fixed.jsonl"
CACHE = ROOT / "data/task-comparison/rubric-eval/gpt-5.6-sol"
BEST = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
VALUE = {"not_satisfied": 0.0, "partially_satisfied": 0.5, "satisfied": 1.0}


def load_jsonl(path: Path) -> list[dict]:
    """Read one durable JSON object per nonblank line."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def full_sol_rows() -> dict[str, dict]:
    """Newest complete 30-topic Sol-judge row keyed by exact run id.

    The result ledger's ``run_id`` names the saved generation, while
    ``variant`` names the rubric-cache directory.  They are usually identical,
    but the frozen Sol baseline is ``v2-dev30-default`` in the ledger and
    ``sol-default`` on disk.  Keep both names or criterion oracles silently
    omit that arm.
    """
    rows: dict[str, dict] = {}
    for row in load_jsonl(RESULTS):
        if row.get("topics") == 30 and row.get("judge") == "gpt-5.6-sol":
            rows[str(row["run_id"])] = row
    return rows


def is_sol_written(run_id: str) -> bool:
    """Select runs whose answer generator was Sol, not merely their judge."""
    return run_id.startswith(("v2-dev30-", "sol-dev30-", "sol-aus-v2-"))


def oracle(rows: dict[str, dict], run_ids: list[str], label: str) -> None:
    """Print a one-answer-per-topic oracle and every selected source run."""
    qids = sorted(rows[run_ids[0]]["per_topic"])
    chosen: list[tuple[str, float, str]] = []
    for qid in qids:
        score, run_id = max((float(rows[r]["per_topic"][qid]), r) for r in run_ids)
        chosen.append((qid, score, run_id))
    print(f"\n=== {label}: answer-level oracle ===")
    print(f"runs={len(run_ids)} topics={len(chosen)} mean={st.mean(x[1] for x in chosen):.4f} "
          f"below_065={sum(x[1] < .65 for x in chosen)}")
    for run_id, count in Counter(x[2] for x in chosen).most_common():
        print(f"  selected {count:2d}  {run_id}")
    print("qid\tscore\tselected_run")
    for qid, score, run_id in chosen:
        print(f"{qid}\t{score:.4f}\t{run_id}")


def repeat_verdicts(run_id: str, qid: str) -> list[list[str]]:
    """Return every complete cached repeat for one answer/topic pair."""
    paths = [CACHE / run_id / f"{qid}.json",
             CACHE / run_id / f"{qid}.r1.json",
             CACHE / run_id / f"{qid}.r2.json"]
    verdicts = []
    for path in paths:
        if not path.exists():
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("status") == "completed" and obj.get("verdicts"):
            verdicts.append(obj["verdicts"])
    return verdicts


def criterion_values(run_id: str, qid: str, n: int) -> list[float] | None:
    """Average the three paid judge repeats criterion by criterion."""
    repeats = repeat_verdicts(run_id, qid)
    if not repeats or any(len(row) != n for row in repeats):
        return None
    return [st.mean(VALUE[row[i]] for row in repeats) for i in range(n)]


def criterion_union(rubrics: dict[str, dict], rows: dict[str, dict],
                    run_ids: list[str], label: str) -> None:
    """Upper bound if supported criterion fragments could be combined safely."""
    topic_scores: list[tuple[str, float]] = []
    missing = []
    for qid, rubric in sorted(rubrics.items()):
        criteria = [c for c in rubric["criteria"] if not c["waived"]]
        candidates = [v for run_id in run_ids
                      if (v := criterion_values(
                          rows[run_id]["variant"], qid,
                          len(criteria))) is not None]
        if not candidates:
            missing.append(qid)
            continue
        denominator = sum(c["signed_weight"] for c in criteria
                          if c["signed_weight"] > 0)
        numerator = 0.0
        for i, criterion in enumerate(criteria):
            values = [row[i] for row in candidates]
            value = (max(values) if criterion["signed_weight"] > 0
                     else min(values))
            numerator += criterion["signed_weight"] * value
        topic_scores.append((qid, numerator / denominator))
    print(f"\n=== {label}: criterion-union upper bound ===")
    print(f"runs={len(run_ids)} topics={len(topic_scores)} mean="
          f"{st.mean(x[1] for x in topic_scores):.4f} "
          f"below_065={sum(x[1] < .65 for x in topic_scores)} missing={missing}")
    print("qid\tunion_score")
    for qid, score in topic_scores:
        print(f"{qid}\t{score:.4f}")


def best_gap_matrix(rubrics: dict[str, dict]) -> None:
    """Decompose the promoted run's remaining positive-weight deficit."""
    by_axis: defaultdict[str, float] = defaultdict(float)
    by_type: defaultdict[str, float] = defaultdict(float)
    by_tier: defaultdict[str, float] = defaultdict(float)
    rows: list[tuple[float, str, str, str]] = []
    total_positive = 0.0
    total_missing = 0.0
    for qid, rubric in sorted(rubrics.items()):
        criteria = [c for c in rubric["criteria"] if not c["waived"]]
        values = criterion_values(BEST, qid, len(criteria))
        if values is None:
            continue
        for criterion, value in zip(criteria, values):
            weight = float(criterion["signed_weight"])
            if weight <= 0:
                continue
            deficit = weight * (1.0 - value)
            total_positive += weight
            total_missing += deficit
            by_axis[str(criterion.get("axis") or "Unknown")] += deficit
            by_type[str(criterion.get("type") or "unknown")] += deficit
            by_tier[str(criterion.get("tier") or "unknown")] += deficit
            if deficit:
                rows.append((deficit, qid, criterion["cid"], criterion["text"]))
    print("\n=== promoted-run positive reward deficit ===")
    print(f"positive_weight={total_positive:.1f} missing_weight={total_missing:.1f} "
          f"reward_coverage={1-total_missing/total_positive:.4f}")
    for name, groups in (("axis", by_axis), ("type", by_type), ("tier", by_tier)):
        print(f"  by {name}")
        for key, value in sorted(groups.items(), key=lambda item: -item[1]):
            print(f"    {value:7.2f}  {key}")
    print("top individual deficits")
    for deficit, qid, cid, text in sorted(rows, reverse=True)[:50]:
        print(f"  {deficit:4.1f}\t{qid}\t{cid}\t{text}")


def main() -> None:
    """Run all fixed candidate sets and print reproducible full matrices."""
    rows = full_sol_rows()
    rubrics = {row["qid"]: row for row in load_jsonl(RUBRICS)}
    integrated = [
        "v2-dev30-default",
        "sol-aus-v2-research-first-dev30-20260806",
        BEST,
        "sol-aus-v2-adaptive-dev30-20260806",
    ]
    sol_written = sorted(run_id for run_id in rows if is_sol_written(run_id))
    all_sol_judged = sorted(rows)
    for run_id in integrated + sol_written:
        if run_id not in rows:
            raise SystemExit(f"missing complete result row: {run_id}")
    oracle(rows, integrated, "four architecture candidates")
    oracle(rows, sol_written, "all Sol-written full-30 candidates")
    oracle(rows, all_sol_judged, "all Sol-judged full-30 candidates")
    criterion_union(rubrics, rows, integrated, "four architecture candidates")
    criterion_union(rubrics, rows, sol_written,
                    "all Sol-written full-30 candidates")
    best_gap_matrix(rubrics)


if __name__ == "__main__":
    main()
