#!/usr/bin/env python3
"""Anonymized pairwise battles across the four-run comparison set.

This mirrors what the organizers say they will run: "responses from two
submitted systems will be paired for side-by-side comparison, with system
identities hidden and presentation order randomized" (`rag-task.md`). It needs
no rubrics, nuggets, or qrels, so it works on the unjudged test narratives.

RAGDoll owns the judging contract — ``render_arena_prompt`` (its naive pairwise
prompt), ``parse_pairwise_verdict``, and ``TIE_VERDICTS``. Only execution is
ours, because RAGDoll drives models through the ``pi`` binary, which is not
installed on this host.

Two design choices that keep the numbers honest:

- **Every pair is judged in both orders** and the results are pooled. LLM judges
  carry a real position bias; running A/B and B/A and reporting the disagreement
  rate makes that bias measurable instead of silently baked into the ranking.
- **Citations are stripped** from the presented answers. Our runs and the
  baselines mark citations differently, so leaving them in lets the judge
  identify the system and turns a blind comparison into a sighted one.

Judge-identity caveat: the judge is ``gpt-5.6-luna``, which also generated our
two runs, while the baselines came from ``gpt-5.6-sol``. Unlike support
judging, a preference vote is exactly where self-preference bias shows up.
Read our-vs-baseline numbers here as suggestive, and lean on the ours-semantic
vs ours-keyword comparison, where both sides share the generator.

    PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/scripts/judge_test119_arena.py --workers 16
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation/ragdoll/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import judge_client  # noqa: E402

from ragdoll.arena.prompts import (  # noqa: E402
    TIE_VERDICTS, parse_verdict, render_arena_prompt)

_VERDICT_ANYWHERE = __import__("re").compile(r"\[\[(A|B|Tie|Tie \(Both Bad\))\]\]")


def parse_pairwise_verdict(text: str) -> tuple[str | None, str]:
    """RAGDoll's parser first, then a narrow documented fallback.

    ``ragdoll.arena.prompts.parse_verdict`` uses ``fullmatch``, so any stray
    token around the verdict — a reasoning model's trailing newline commentary,
    say — drops the battle entirely. Rather than silently lose those, fall back
    to the last well-formed ``[[...]]`` marker in the reply and record which
    path produced the label, so the strict-parse rate stays auditable.
    """
    strict = parse_verdict(text)
    if strict is not None:
        return strict, "strict"
    found = _VERDICT_ANYWHERE.findall(text)
    return (found[-1], "fallback") if found else (None, "unparsed")

EVAL_DIR = ROOT / "data/task-comparison/test119-eval"
JUDGE_DIR = EVAL_DIR / "arena-judgments"
LABELS = ["ours-semantic", "ours-keyword", "base-agentic-bm25", "base-singlepass"]


def load_env() -> None:
    import os
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def client():
    return judge_client.client()


def answer_text(row: dict) -> str:
    """The answer as prose, with citation markers absent by construction.

    The organizer schema keeps citations in a separate field from ``text``, so
    joining the texts already yields an unattributed answer — no stripping
    needed, and nothing that identifies which system wrote it.
    """
    return "\n".join(item["text"] for item in row["answer"])


def judge_one(api, model: str, task: dict, cache: Path) -> dict:
    path = cache / f"{task['task_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    prompt = render_arena_prompt(query=task["query"], answer_a=task["text_a"],
                                 answer_b=task["text_b"])
    try:
        raw = judge_client.complete(api, model, prompt).strip()
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


def task_meta(task: dict) -> dict:
    return {k: task[k] for k in
            ("task_id", "topic_id", "run_a", "run_b", "pair_key", "orientation")}


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--every", type=int, default=1)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--model", default=judge_client.default_model())
    args = parser.parse_args()

    runs = {}
    for label in LABELS:
        runs[label] = {json.loads(l)["metadata"]["narrative_id"]: json.loads(l)
                       for l in (EVAL_DIR / f"{label}.jsonl").read_text(
                           encoding="utf-8").splitlines() if l.strip()}
    qids = list(runs[LABELS[0]])[::args.every]

    tasks = []
    for qid in qids:
        for first, second in itertools.combinations(LABELS, 2):
            query = runs[first][qid]["metadata"]["narrative"]
            pair_key = f"{first}|{second}"
            # Both orientations: (first as A) and (second as A).
            for orientation, (a, b) in enumerate([(first, second), (second, first)]):
                tasks.append({
                    "task_id": f"{qid}__{first}__{second}__o{orientation}",
                    "topic_id": qid, "pair_key": pair_key, "orientation": orientation,
                    "run_a": a, "run_b": b, "query": query,
                    "text_a": answer_text(runs[a][qid]),
                    "text_b": answer_text(runs[b][qid]),
                })

    cache = JUDGE_DIR / judge_client.canonical(args.model)
    todo = [t for t in tasks if not (cache / f"{t['task_id']}.json").exists()]
    print(f"{len(qids)} narratives x {len(list(itertools.combinations(LABELS, 2)))} "
          f"pairs x 2 orders = {len(tasks)} battles, {len(todo)} not cached")

    api = client()
    done, lock = 0, threading.Lock()

    def work(task):
        nonlocal done
        record = judge_one(api, args.model, task, cache)
        with lock:
            done += 1
            if done % 100 == 0:
                print(f"  judged {done}/{len(todo)}", flush=True)
        return record

    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(work, t) for t in todo]):
                future.result()

    records = [json.loads((cache / f"{t['task_id']}.json").read_text(encoding="utf-8"))
               for t in tasks]

    # Pool both orientations per (topic, pair). Ties split evenly, exactly as
    # RAGDoll's pairwise_rows does.
    from collections import defaultdict
    counts = defaultdict(lambda: {"wins": defaultdict(int), "ties": 0, "n": 0})
    flips = defaultdict(lambda: {"agree": 0, "disagree": 0})
    by_cell = defaultdict(dict)
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
    rows = []
    for key, item in sorted(counts.items()):
        left, right = key.split("|")
        n = item["n"]
        left_rate = (item["wins"][left] + 0.5 * item["ties"]) / n if n else float("nan")
        agree = flips[key]["agree"]
        total_flip = agree + flips[key]["disagree"]
        rows.append({
            "pair": key, "battles": n,
            f"wins": f"{item['wins'][left]}-{item['wins'][right]}-{item['ties']}",
            "left_pref_rate": round(left_rate, 4),
            "order_consistency": (round(agree / total_flip, 3) if total_flip else None),
        })
    cols = ["pair", "battles", "wins", "left_pref_rate", "order_consistency"]
    width = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print(" | ".join(c.ljust(width[c]) for c in cols))
    print("-+-".join("-" * width[c] for c in cols))
    for row in rows:
        print(" | ".join(str(row[c]).ljust(width[c]) for c in cols))
    print("\n(wins column is left-right-ties; left_pref_rate is for the LEFT run)")

    # Overall preference rate per run across every opponent.
    totals = defaultdict(lambda: {"score": 0.0, "n": 0})
    for key, item in counts.items():
        left, right = key.split("|")
        for run, other in ((left, right), (right, left)):
            totals[run]["score"] += item["wins"][run] + 0.5 * item["ties"]
            totals[run]["n"] += item["n"]
    print("\n=== overall preference rate vs all opponents ===")
    for run, item in sorted(totals.items(), key=lambda kv: -kv[1]["score"] / kv[1]["n"]):
        print(f"  {run:20s} {item['score'] / item['n']:.4f}  ({item['n']} battles)")
    if bad:
        print(f"\n{bad} battles were unparsed or failed and are excluded")

    out = EVAL_DIR / "arena-summary.json"
    out.write_text(json.dumps({"pairs": rows, "overall": {
        r: round(i["score"] / i["n"], 4) for r, i in totals.items()}}, indent=2) + "\n",
        encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
