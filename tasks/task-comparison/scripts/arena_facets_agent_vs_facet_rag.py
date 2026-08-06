#!/usr/bin/env python3
"""Anonymized pairwise arena: facets_agent vs facet_rag over their shared 15
topics (facet_rag's ``arena_15topic`` set — see
``evaluation-results/arena/answers/facet_rag.15topic.jsonl``).

Follows the same pattern as ``judge_test119_arena.py``: RAGDoll owns the
judging contract (``render_arena_prompt``, ``parse_verdict``, ``TIE_VERDICTS``
from ``evaluation/ragdoll/src/ragdoll/arena/prompts.py``), but execution goes
straight through the Azure OpenAI client rather than RAGDoll's own
``ragdoll arena compare-all`` CLI, because that CLI drives models through the
``pi`` binary and ``pi`` is not installed on this host (confirmed:
``which pi`` -> nothing, and ``ragdoll.config``'s ``agent_binary`` defaults to
``"pi"`` with no alternative backend).

Two design choices carried over from ``judge_test119_arena.py``, both load-
bearing for a fair comparison:

- **Every pair is judged in both orders** (facets_agent-as-A / facet_rag-as-A)
  and pooled, so position bias is measured (``order_consistency``) rather than
  silently baked into the result.
- Citations are NOT explicitly stripped because they don't need to be: the
  organizer ``answer[].text`` field never carries inline ``[docid]``
  markers — those are stripped by each system's own harness before the
  sentence is written into that field. Joining the sentence texts already
  yields a citation-free, system-unidentifiable answer.

Judge-identity caveat, same as ``judge_test119_arena.py``: the judge is
``gpt-5.6-luna``, which is also facets_agent's own generator. Read the
facets_agent-vs-facet_rag numbers with that self-preference risk in mind —
facet_rag's generators (gpt-oss-120b orchestrator, Qwen3 analyzer) are
different models, so a genuine self-preference effect would favor
facets_agent.

Usage (repo root; needs OPENAI creds -- see ``load_env`` for why
``OPENAI_API_KEY`` is aliased from ``AZURE_OPENAI_API_KEY`` on this host):

    uv run --group aus-agent python \
        tasks/task-comparison/scripts/arena_facets_agent_vs_facet_rag.py
"""
from __future__ import annotations

import argparse
import glob
import itertools
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

_VERDICT_ANYWHERE = re.compile(r"\[\[(A|B|Tie|Tie \(Both Bad\))\]\]")

FACETS_AGENT_RUN_ID = "facets-agent-15topic"
FACET_RAG_ANSWERS = ROOT / "evaluation-results/arena/answers/facet_rag.15topic.jsonl"
OUT_DIR = ROOT / "evaluation-results/arena/facets_agent-vs-facet_rag-15topic"
JUDGE_DIR = OUT_DIR / "raw-events"
LABELS = ["facets_agent", "facet_rag"]


def load_env() -> None:
    """Auto-load ``.env`` and alias ``OPENAI_API_KEY`` from
    ``AZURE_OPENAI_API_KEY`` -- this repo's ``.env`` carries the Azure key
    under its own name, but the openai-python SDK only looks for
    ``OPENAI_API_KEY`` (same gotcha ``facets_agent/run.py``'s launch script
    just worked around; see worklogs/2026-08-05-facets-agent-new-system.md).
    """
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
    """RAGDoll's strict parser first, then a narrow documented fallback for a
    verdict with stray surrounding text (see ``judge_test119_arena.py``)."""
    strict = parse_verdict(text)
    if strict is not None:
        return strict, "strict"
    found = _VERDICT_ANYWHERE.findall(text)
    return (found[-1], "fallback") if found else (None, "unparsed")


def answer_text(answer: list[dict[str, Any]]) -> str:
    return "\n".join(item["text"] for item in answer)


def load_facets_agent_answers(run_id: str) -> dict[str, dict[str, Any]]:
    """Read this system's own ``ragrun.save_run`` artifacts and normalize them
    into the same flat ``{run_id, qid, query, answer, references}`` shape
    ``facet_rag.15topic.jsonl`` already uses -- one artifact IS one topic's
    row, so no aggregation is needed, just a field rename.
    """
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(glob.glob(str(ROOT / "data/outputs/facets_agent/*.output.json"))):
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = obj.get("metadata", {})
        if metadata.get("run_id") != run_id:
            continue
        qid = metadata["narrative_id"]
        if qid in rows:
            raise ValueError(f"duplicate qid {qid!r} for run_id {run_id!r} "
                             f"(two artifacts under the same run_id/topic)")
        rows[qid] = {
            "run_id": run_id,
            "qid": qid,
            "query": metadata["narrative"],
            "answer": obj["answer"],
            "references": obj["references"],
        }
    return rows


def load_facet_rag_answers(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        rows[obj["qid"]] = obj
    return rows


def judge_one(api, model: str, task: dict[str, Any], cache: Path) -> dict[str, Any]:
    path = cache / f"{task['task_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    prompt = render_arena_prompt(query=task["query"], answer_a=task["text_a"],
                                 answer_b=task["text_b"])
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
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--facets-agent-run-id", default=FACETS_AGENT_RUN_ID)
    args = parser.parse_args()

    runs = {
        "facets_agent": load_facets_agent_answers(args.facets_agent_run_id),
        "facet_rag": load_facet_rag_answers(FACET_RAG_ANSWERS),
    }
    qids = sorted(set(runs["facets_agent"]) & set(runs["facet_rag"]))
    missing_fa = set(runs["facet_rag"]) - set(runs["facets_agent"])
    missing_fr = set(runs["facets_agent"]) - set(runs["facet_rag"])
    if missing_fa or missing_fr:
        print(f"warning: {len(missing_fa)} topics only in facet_rag, "
              f"{len(missing_fr)} only in facets_agent -- judging only the "
              f"{len(qids)} shared topics", file=sys.stderr)

    tasks = []
    for qid in qids:
        query = runs["facets_agent"][qid]["query"]
        pair_key = "facets_agent|facet_rag"
        for orientation, (a, b) in enumerate(
                [("facets_agent", "facet_rag"), ("facet_rag", "facets_agent")]):
            tasks.append({
                "task_id": f"{qid}__{a}__{b}__o{orientation}",
                "topic_id": qid, "pair_key": pair_key, "orientation": orientation,
                "run_a": a, "run_b": b, "query": query,
                "text_a": answer_text(runs[a][qid]["answer"]),
                "text_b": answer_text(runs[b][qid]["answer"]),
            })

    cache = JUDGE_DIR / args.model
    todo = [t for t in tasks if not (cache / f"{t['task_id']}.json").exists()]
    print(f"{len(qids)} shared topics x 1 pair x 2 orders = {len(tasks)} "
          f"battles, {len(todo)} not cached")

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
    for (_qid, key), orientations in by_cell.items():
        if len(orientations) == 2:
            a, b = orientations[0], orientations[1]
            flips[key]["agree" if a == b else "disagree"] += 1

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
        for run, other in ((left, right), (right, left)):
            totals[run]["score"] += item["wins"][run] + 0.5 * item["ties"]
            totals[run]["n"] += item["n"]
    print("\n=== overall preference rate ===")
    for run, item in sorted(totals.items(), key=lambda kv: -kv[1]["score"] / kv[1]["n"]):
        print(f"  {run:14s} {item['score'] / item['n']:.4f}  ({item['n']} battles)")
    if bad:
        print(f"\n{bad} battles were unparsed or failed and are excluded")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    judgments_path = OUT_DIR / "judgments.jsonl"
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
        "missing_from_facets_agent": sorted(missing_fr),
        "missing_from_facet_rag": sorted(missing_fa),
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {judgments_path}\nwrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
