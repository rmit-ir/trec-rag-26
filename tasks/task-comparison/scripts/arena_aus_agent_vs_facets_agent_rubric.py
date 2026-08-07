#!/usr/bin/env python3
"""Rubric-grounded pairwise arena: aus_agent vs facets_agent, over their
shared 15 topics (the same set used in ``arena_facets_agent_vs_facet_rag.py``
-- facet_rag's ``arena_15topic`` set), scored against the official
ResearchRubrics dev criteria for each topic.

Same execution pattern as ``arena_facets_agent_vs_facet_rag.py`` (RAGDoll's
prompt/parser contract, direct Azure OpenAI execution because the ``pi``
binary RAGDoll's own CLI needs isn't installed here, both battle orders
judged and pooled). Two things this script adds on top of that one:

- **Rubric-guided judging.** ``render_arena_prompt(..., rubric=...)`` selects
  ``PAIRWISE_ANSWER_COMPARISON_W_RUBRICS`` instead of the naive prompt. The
  rubric text comes from
  ``data/official/.../researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl``
  (the official per-topic ResearchRubrics criteria, ~31 weighted criteria per
  topic here), rendered with RAGDoll's own ``format_rubric_for_prompt`` for
  consistency with its documented output shape. That file's field names
  (``criterion``, ``axis``) differ from RAGDoll's own rubric schema
  (``text``, ``type``) -- mapped in ``load_research_rubrics`` below rather
  than writing an intermediate RAGDoll-shaped JSONL file.
- **Both answer sets come from ``ragrun.save_run`` artifacts**
  (``data/outputs/<system>/*.output.json``, filtered by ``run_id``), via one
  shared loader -- unlike the facet_rag comparison, where facet_rag's side
  was a fixed external snapshot.

Judge-identity note, same caveat as the facet_rag comparison but INVERTED
here: the default judge is ``gpt-5.6-terra``, which generated NEITHER
system's answers (both aus_agent and facets_agent ran on ``gpt-5.6-luna`` for
this comparison -- see the worklog for why the model was held fixed across
systems). Using a third model as judge removes the self-preference confound
that limited the facet_rag comparison's interpretability.

Usage (repo root; needs OPENAI creds -- see ``load_env``):

    uv run --group aus-agent python \
        tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation" / "ragdoll" / "src"))

from ragdoll.arena.prompts import (  # noqa: E402
    TIE_VERDICTS, parse_verdict, render_arena_prompt)
from ragdoll.arena.stages import RubricRecord, format_rubric_for_prompt  # noqa: E402

_VERDICT_ANYWHERE = re.compile(r"\[\[(A|B|Tie|Tie \(Both Bad\))\]\]")

RUN_IDS = {"aus_agent": "aus-agent-15topic", "facets_agent": "facets-agent-15topic"}
RESEARCH_RUBRICS = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
                    "development-data/researchrubrics-dev-rubrics/"
                    "research-rubrics-dev-rubrics.jsonl")
OUT_DIR = ROOT / "evaluation-results/arena/aus_agent-vs-facets_agent-15topic-rubric"
JUDGE_DIR = OUT_DIR / "raw-events"
LABELS = ["aus_agent", "facets_agent"]


def load_env() -> None:
    """See arena_facets_agent_vs_facet_rag.py::load_env -- same alias, same
    reason (this repo's .env carries the Azure key as AZURE_OPENAI_API_KEY,
    not the OPENAI_API_KEY name the openai-python SDK actually reads)."""
    import os
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]


def client():
    import os
    from openai import OpenAI
    return OpenAI(base_url=os.environ["OPENAI_BASE_URL"],
                  api_key=os.environ["OPENAI_API_KEY"],
                  timeout=300.0, max_retries=4)


def parse_pairwise_verdict(text: str) -> tuple[str | None, str]:
    strict = parse_verdict(text)
    if strict is not None:
        return strict, "strict"
    found = _VERDICT_ANYWHERE.findall(text)
    return (found[-1], "fallback") if found else (None, "unparsed")


def answer_text(answer: list[dict[str, Any]]) -> str:
    return "\n".join(item["text"] for item in answer)


def load_answers_from_outputs(system_dir: Path, run_id: str) -> dict[str, dict[str, Any]]:
    """Normalize ``ragrun.save_run`` artifacts into the flat
    ``{run_id, qid, query, answer, references}`` shape both arena scripts use.
    Works for any system -- the organizer output schema is shared.
    """
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(glob.glob(str(system_dir / "*.output.json"))):
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = obj.get("metadata", {})
        if metadata.get("run_id") != run_id:
            continue
        qid = metadata["narrative_id"]
        if qid in rows:
            raise ValueError(f"duplicate qid {qid!r} for run_id {run_id!r} "
                             f"in {system_dir}")
        rows[qid] = {"run_id": run_id, "qid": qid, "query": metadata["narrative"],
                     "answer": obj["answer"], "references": obj["references"]}
    return rows


def load_research_rubrics(path: Path) -> dict[str, str]:
    """Render each topic's official ResearchRubrics criteria with RAGDoll's
    own ``format_rubric_for_prompt``, mapping this file's field names
    (``criterion``, ``axis``) onto RAGDoll's (``text``, ``type``)."""
    rendered: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        criteria = [
            {"text": c["criterion"], "weight": c["weight"], "type": c["axis"]}
            for c in row.get("rubrics", [])
            if str(c.get("criterion", "")).strip()
        ]
        if not criteria:
            continue
        record = RubricRecord(qid=row["qid"], query="", criteria=criteria,
                              source=row)
        rendered[row["qid"]] = format_rubric_for_prompt(record)
    return rendered


def judge_one(api, model: str, task: dict[str, Any], cache: Path) -> dict[str, Any]:
    path = cache / f"{task['task_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    prompt = render_arena_prompt(query=task["query"], answer_a=task["text_a"],
                                 answer_b=task["text_b"], rubric=task["rubric"])
    try:
        response = api.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}])
        raw = (response.choices[0].message.content or "").strip()
        verdict, parse_path = parse_pairwise_verdict(raw)
        if verdict is None:
            record = {**task_meta(task), "judge_verdict": None,
                      "preferred_run_id": None, "raw_output": raw[:300],
                      "parse_path": parse_path, "status": "unparsed"}
        else:
            preferred = (None if verdict in TIE_VERDICTS
                         else (task["run_a"] if verdict == "A" else task["run_b"]))
            record = {**task_meta(task), "judge_verdict": verdict,
                      "preferred_run_id": preferred, "raw_output": raw[:300],
                      "parse_path": parse_path, "status": "completed"}
    except Exception as exc:  # noqa: BLE001
        record = {**task_meta(task), "judge_verdict": None,
                  "preferred_run_id": None,
                  "raw_output": f"{type(exc).__name__}: {exc}", "status": "failed"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def task_meta(task: dict[str, Any]) -> dict[str, Any]:
    return {k: task[k] for k in
            ("task_id", "topic_id", "run_a", "run_b", "pair_key", "orientation")}


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--aus-agent-run-id", default=RUN_IDS["aus_agent"])
    parser.add_argument("--facets-agent-run-id", default=RUN_IDS["facets_agent"])
    parser.add_argument(
        "--challenger-system", default="facets_agent",
        help="system to compare against aus_agent, by its data/outputs/<name> "
             "dir (default facets_agent, this script's original opponent -- "
             "byte-identical behavior when left at the default)")
    parser.add_argument(
        "--challenger-run-id", default=None,
        help="run_id for --challenger-system (default: --facets-agent-run-id "
             "when --challenger-system=facets_agent, for backward "
             "compatibility with every existing invocation; REQUIRED for any "
             "other --challenger-system)")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR,
                        help="where to write judgments.jsonl/summary.json "
                             "(default: the 15-topic dir; pass a new dir for "
                             "a different run/topic-set so it never overwrites)")
    args = parser.parse_args()
    out_dir = args.out_dir
    judge_dir = out_dir / "raw-events"
    challenger = args.challenger_system
    challenger_run_id = args.challenger_run_id
    if challenger_run_id is None:
        if challenger != "facets_agent":
            raise SystemExit("--challenger-run-id is required when "
                             "--challenger-system is not facets_agent")
        challenger_run_id = args.facets_agent_run_id
    labels = ["aus_agent", challenger]

    runs = {
        "aus_agent": load_answers_from_outputs(
            ROOT / "data/outputs/aus_agent", args.aus_agent_run_id),
        challenger: load_answers_from_outputs(
            ROOT / "data/outputs" / challenger, challenger_run_id),
    }
    rubrics = load_research_rubrics(RESEARCH_RUBRICS)

    qids = sorted(set(runs["aus_agent"]) & set(runs[challenger]))
    missing_rubric = [q for q in qids if q not in rubrics]
    if missing_rubric:
        raise SystemExit(f"no rubric for {len(missing_rubric)} shared topics: "
                         f"{missing_rubric}")
    for label in labels:
        missing = set(qids) - set(runs[label])
        if missing:
            print(f"note: {label} is missing {len(missing)} of the other "
                  f"system's topics (excluded from this comparison)",
                  file=sys.stderr)

    tasks = []
    for qid in qids:
        query = runs["aus_agent"][qid]["query"]
        pair_key = f"aus_agent|{challenger}"
        for orientation, (a, b) in enumerate(
                [("aus_agent", challenger), (challenger, "aus_agent")]):
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
