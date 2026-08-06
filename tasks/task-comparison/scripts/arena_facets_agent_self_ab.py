#!/usr/bin/env python3
"""Self-arena: facets_agent vs itself, two different configurations of the
same code, over the SAME topics -- both arms are ``data/outputs/facets_agent``
with different ``run_id``s, unlike ``arena_aus_agent_vs_facets_agent_rubric.py``
which compares two different systems. Written for PLAN.md Phase 4c's A/B
(Version A ``minimize_filter`` vs Version B ``rank_filter``), but the two
run-ids and labels are all CLI flags so it works for any same-system,
different-run-id comparison -- exactly the "thin variant" that script's own
Tier 3 note anticipated (``load_answers_from_outputs`` is already generic).

Reuses every piece of the two-system arena's machinery via import rather
than duplicating it -- only ``main()`` differs (both arms point at the same
directory, and the pair_key/labels are CLI-driven instead of hardcoded).

Usage (repo root; needs OPENAI creds -- see ``load_env``):

    uv run --group aus-agent python \
        tasks/task-comparison/scripts/arena_facets_agent_self_ab.py \
        --run-id-a facets-agent-sample15-minimize --label-a minimize \
        --run-id-b facets-agent-sample15-rank --label-b rank \
        --out-dir evaluation-results/arena/facets_agent-minimize-vs-rank-sample15
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from arena_aus_agent_vs_facets_agent_rubric import (  # noqa: E402
    RESEARCH_RUBRICS,
    client,
    judge_one,
    load_answers_from_outputs,
    load_env,
    load_research_rubrics,
    answer_text,
)


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--system-dir", default="facets_agent",
                        help="both arms read data/outputs/<system-dir>/ "
                             "(default: facets_agent)")
    parser.add_argument("--run-id-a", required=True)
    parser.add_argument("--run-id-b", required=True)
    parser.add_argument("--label-a", required=True,
                        help="short name for arm A, e.g. 'minimize'")
    parser.add_argument("--label-b", required=True,
                        help="short name for arm B, e.g. 'rank'")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    out_dir = args.out_dir
    judge_dir = out_dir / "raw-events"
    label_a, label_b = args.label_a, args.label_b

    system_dir = ROOT / "data/outputs" / args.system_dir
    runs = {
        label_a: load_answers_from_outputs(system_dir, args.run_id_a),
        label_b: load_answers_from_outputs(system_dir, args.run_id_b),
    }
    rubrics = load_research_rubrics(RESEARCH_RUBRICS)

    qids = sorted(set(runs[label_a]) & set(runs[label_b]))
    missing_rubric = [q for q in qids if q not in rubrics]
    if missing_rubric:
        raise SystemExit(f"no rubric for {len(missing_rubric)} shared topics: "
                         f"{missing_rubric}")
    for label in (label_a, label_b):
        missing = set(qids) - set(runs[label])
        if missing:
            print(f"note: {label} is missing {len(missing)} of the other "
                  f"arm's topics (excluded)", file=sys.stderr)

    tasks = []
    for qid in qids:
        query = runs[label_a][qid]["query"]
        pair_key = f"{label_a}|{label_b}"
        for orientation, (a, b) in enumerate(
                [(label_a, label_b), (label_b, label_a)]):
            tasks.append({
                "task_id": f"{qid}__{a}__{b}__o{orientation}",
                "topic_id": qid, "pair_key": pair_key, "orientation": orientation,
                "run_a": a, "run_b": b, "query": query,
                "text_a": answer_text(runs[a][qid]["answer"]),
                "text_b": answer_text(runs[b][qid]["answer"]),
                "rubric": rubrics[qid],
            })

    cache = judge_dir / args.model
    todo = [t for t in tasks if not (cache / f"{t['task_id']}.json").exists()]
    print(f"{len(qids)} shared topics x 1 pair x 2 orders = {len(tasks)} "
          f"battles, {len(todo)} not cached, judge={args.model}")

    api = client()
    done, lock = 0, threading.Lock()

    def work(task):
        nonlocal done
        record = judge_one(api, args.model, task, cache)
        with lock:
            done += 1
            print(f"  [{done}/{len(todo)}] {task['task_id']}", flush=True)
        return record

    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(work, t) for t in todo]):
                future.result()

    records = [json.loads((cache / f"{t['task_id']}.json").read_text(encoding="utf-8"))
              for t in tasks]

    from arena_aus_agent_vs_facets_agent_rubric import TIE_VERDICTS  # noqa: E402
    counts = defaultdict(lambda: {"wins": defaultdict(int), "ties": 0, "n": 0})
    flips = defaultdict(lambda: {"agree": 0, "disagree": 0})
    by_cell: dict[tuple[str, str], dict[int, str | None]] = defaultdict(dict)
    per_topic: dict[str, dict[int, str | None]] = defaultdict(dict)
    bad = 0
    for record in records:
        if record["status"] != "completed":
            bad += 1
            continue
        key = record["pair_key"]
        counts[key]["n"] += 1
        if record["judge_verdict"] in TIE_VERDICTS:
            counts[key]["ties"] += 1
        else:
            counts[key]["wins"][record["preferred_run_id"]] += 1
        by_cell[(record["topic_id"], key)][record["orientation"]] = \
            record["preferred_run_id"]
        per_topic[record["topic_id"]][record["orientation"]] = record["preferred_run_id"]
    for (_qid, key), orientations in by_cell.items():
        if len(orientations) == 2:
            a, b = orientations[0], orientations[1]
            flips[key]["agree" if a == b else "disagree"] += 1

    print("\n=== per-topic (orientation 0 pref, orientation 1 pref) ===")
    for qid in qids:
        o = per_topic.get(qid, {})
        print(f"  {qid}: o0={o.get(0)!r} o1={o.get(1)!r}")

    print("\n=== pairwise preference (both orders pooled, ties split) ===")
    for key, item in sorted(counts.items()):
        left, right = key.split("|")
        n = item["n"]
        left_rate = (item["wins"][left] + 0.5 * item["ties"]) / n if n else float("nan")
        agree = flips[key]["agree"]
        total_flip = agree + flips[key]["disagree"]
        consistency = round(agree / total_flip, 3) if total_flip else None
        print(f"  {left} vs {right}: {item['wins'][left]}-{item['wins'][right]}"
              f"-{item['ties']} (n={n}) | {left}_pref_rate={round(left_rate, 4)} "
              f"| order_consistency={consistency}")

    totals = defaultdict(lambda: {"score": 0.0, "n": 0})
    for key, item in counts.items():
        left, right = key.split("|")
        for run in (left, right):
            totals[run]["score"] += item["wins"][run] + 0.5 * item["ties"]
            totals[run]["n"] += item["n"]
    print("\n=== overall preference rate ===")
    for run, item in sorted(totals.items(), key=lambda kv: -kv[1]["score"] / kv[1]["n"]):
        print(f"  {run:14s} {item['score'] / item['n']:.4f}  ({item['n']} battles)")
    if bad:
        print(f"\n{bad} battles were unparsed or failed and are excluded")

    out_dir.mkdir(parents=True, exist_ok=True)
    judgments_path = out_dir / "judgments.jsonl"
    judgments_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8")
    summary = {
        "pairs": {key: {
            "wins": dict(item["wins"]), "ties": item["ties"], "n": item["n"],
        } for key, item in counts.items()},
        "overall": {r: round(i["score"] / i["n"], 4) for r, i in totals.items()},
        "unparsed_or_failed": bad,
        "judge_model": args.model,
        "shared_topics": len(qids),
        "rubric_source": str(RESEARCH_RUBRICS.relative_to(ROOT)),
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {judgments_path}\nwrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
