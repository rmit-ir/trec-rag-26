#!/usr/bin/env python3
"""Standalone rubric grading for ONE system/run -- no opponent, no arena.

Reuses `rubric_scorecard_aus_agent_vs_facets_agent.py`'s own `score_one`
(one judge call per topic, grades EVERY official rubric criterion 0-2 plus
a holistic 0-3 `overall`) directly, rather than reimplementing a second
grader. Built for the brief_revise_agent-vs-aus_agent_v2 factorial-analysis
grid (worklogs/2026-08-07-brief-revise-agent-llm-factorial-*): sol's design
made this the PRIMARY evaluation for each grid cell -- 15 calls/cell instead
of arena's 30 (15 topics x 2 battle orders), no opponent answer needed, no
position-bias confound, and a genuinely ordinal 0-3 score per criterion
(31ish per topic) instead of a categorical win/loss/tie.

Usage (repo root; needs OPENAI creds -- see `load_env`):

    uv run --group aus-agent python \
        tasks/task-comparison/scripts/standalone_rubric_score.py \
        --system brief_revise_agent --run-id br-model-main-terra-exp15-b1 \
        --out-dir evaluation-results/factorial/br-model-main-terra-exp15-b1
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rubric_scorecard_aus_agent_vs_facets_agent import (  # noqa: E402
    client, load_answers_from_outputs, load_criteria, load_env, score_one)

RESEARCH_RUBRICS = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
                    "development-data/researchrubrics-dev-rubrics/"
                    "research-rubrics-dev-rubrics.jsonl")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", required=True,
                        help="system dir name under data/outputs/, e.g. brief_revise_agent")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="where to write scores.jsonl/summary.json "
                             "(one dir per factorial cell, never overwritten "
                             "by another cell)")
    parser.add_argument("--topics", type=Path, default=None,
                        help="restrict scoring to the qids in this topics "
                             "TSV (qid<TAB>narrative) -- for comparing a "
                             "system's wider run against one factorial "
                             "cell's own topic subset, e.g. a baseline run "
                             "covering 30 topics scored fairly against a "
                             "15-topic cell")
    args = parser.parse_args()

    answers = load_answers_from_outputs(
        ROOT / "data/outputs" / args.system, args.run_id)
    criteria_by_qid = load_criteria(RESEARCH_RUBRICS)
    qids = sorted(set(answers) & set(criteria_by_qid))
    if args.topics:
        wanted = {line.split("\t", 1)[0].strip()
                 for line in args.topics.read_text().splitlines() if line.strip()}
        qids = [q for q in qids if q in wanted]
    missing = set(answers) - set(criteria_by_qid)
    if missing:
        print(f"note: {len(missing)} answered topics have no rubric, excluded",
              file=sys.stderr)

    cache = args.out_dir / "raw-events" / args.model
    cache.mkdir(parents=True, exist_ok=True)
    todo = [q for q in qids if not (cache / f"{args.system}__{q}.json").exists()]
    print(f"{len(qids)} topics, {len(todo)} not cached, judge={args.model}, "
         f"system={args.system!r} run_id={args.run_id!r}")

    api = client()
    done, lock = 0, threading.Lock()

    def work(qid: str):
        nonlocal done
        record = score_one(api, args.model, args.system, qid,
                           answers[qid]["query"], answers[qid]["answer_text"],
                           criteria_by_qid[qid], cache)
        with lock:
            done += 1
            print(f"  [{done}/{len(todo)}] {qid} -> overall={record.get('overall')}",
                 flush=True)
        return record

    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(work, q) for q in todo]):
                future.result()

    records = [json.loads((cache / f"{args.system}__{q}.json").read_text())
              for q in qids]
    completed = [r for r in records if r["status"] == "completed"]
    failed = len(records) - len(completed)

    # Per-criterion aggregate across all topics: axis -> [grades].
    by_axis: dict[str, list[int]] = defaultdict(list)
    axis_by_cid: dict[tuple[str, int], str] = {}
    for qid in qids:
        for c in criteria_by_qid[qid]:
            axis_by_cid[(qid, c["cid"])] = c["axis"]
    for r in completed:
        for cov in r["criteria_coverage"]:
            axis = axis_by_cid.get((r["qid"], cov["cid"]))
            if axis:
                by_axis[axis].append(cov["grade"])

    overall_mean = (sum(r["overall"] for r in completed) / len(completed)
                    if completed else None)
    axis_means = {axis: sum(gs) / len(gs) for axis, gs in by_axis.items()}

    print(f"\noverall mean (0-3): {overall_mean}")
    for axis, mean in sorted(axis_means.items()):
        print(f"  {axis:35s} n={len(by_axis[axis]):3d} mean(0-2)={mean:.3f}")
    if failed:
        print(f"\n{failed} topics failed/unparsed and are excluded from means")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    scores_path = args.out_dir / "scores.jsonl"
    scores_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8")
    summary = {
        "system": args.system, "run_id": args.run_id, "judge_model": args.model,
        "n_topics": len(qids), "n_completed": len(completed), "n_failed": failed,
        "overall_mean": overall_mean, "axis_means": axis_means,
        "rubric_source": str(RESEARCH_RUBRICS.relative_to(ROOT)),
    }
    summary_path = args.out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {scores_path}\nwrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
