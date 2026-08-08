#!/usr/bin/env python3
"""Compare original and injected RAG answers with RAGDOLL's arena contract."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluation" / "ragdoll" / "src"))

from ragdoll.arena.prompts import (  # noqa: E402
    TIE_VERDICTS,
    parse_verdict,
    render_arena_prompt,
)

_VERDICT_ANYWHERE = re.compile(r"\[\[(A|B|Tie|Tie \(Both Bad\))\]\]")


def load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(
                    key.strip(), value.strip().strip("\"").strip("'")
                )
    azure_key = os.environ.get("AZURE_OPENAI_API_KEY")
    if "OPENAI_API_KEY" not in os.environ and azure_key:
        os.environ["OPENAI_API_KEY"] = azure_key
    missing = [
        name
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(
            "missing judge configuration: "
            + ", ".join(missing)
            + ". Export these variables in Bash or add them to the repo-root .env."
        )


def load_answers(path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    rows: dict[str, dict[str, Any]] = {}
    run_id: str | None = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        row_run_id = row.get("run_id") or row.get("metadata", {}).get("run_id")
        qid = row.get("qid") or row.get("topic_id")
        query = row.get("query") or row.get("topic")
        answer_text = row.get("answer_text")
        if not isinstance(answer_text, str):
            answer_text = " ".join(item["text"] for item in row["answer"])
        if not all(isinstance(value, str) and value for value in (row_run_id, qid, query)):
            raise ValueError(f"{path}:{line_number}: missing run_id, qid, or query")
        if run_id is not None and row_run_id != run_id:
            raise ValueError(f"{path}:{line_number}: inconsistent run_id")
        run_id = row_run_id
        rows[qid] = {"query": query, "answer_text": answer_text}
    if run_id is None:
        raise ValueError(f"{path}: no rows")
    return run_id, rows


def parsed_verdict(text: str) -> tuple[str | None, str]:
    verdict = parse_verdict(text)
    if verdict is not None:
        return verdict, "strict"
    found = _VERDICT_ANYWHERE.findall(text)
    return (found[-1], "fallback") if found else (None, "unparsed")


def judge(client: Any, model: str, task: dict[str, str]) -> dict[str, Any]:
    prompt = render_arena_prompt(
        query=task["query"], answer_a=task["answer_a"], answer_b=task["answer_b"]
    )
    try:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}]
        )
        raw = (response.choices[0].message.content or "").strip()
        verdict, parse_path = parsed_verdict(raw)
        preferred = None
        if verdict is not None and verdict not in TIE_VERDICTS:
            preferred = task["run_a"] if verdict == "A" else task["run_b"]
        return {
            **{key: value for key, value in task.items() if not key.startswith("answer_")},
            "judge_verdict": verdict,
            "preferred_run_id": preferred,
            "parse_path": parse_path,
            "status": "completed" if verdict is not None else "unparsed",
            "raw_output": raw[:300],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **{key: value for key, value in task.items() if not key.startswith("answer_")},
            "judge_verdict": None,
            "preferred_run_id": None,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("injected", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    load_env()

    original_id, original = load_answers(args.original)
    injected_id, injected = load_answers(args.injected)
    qids = sorted(set(original) & set(injected))
    tasks = []
    for qid in qids:
        for orientation, (run_a, rows_a, run_b, rows_b) in enumerate(
            (
                (original_id, original, injected_id, injected),
                (injected_id, injected, original_id, original),
            )
        ):
            tasks.append(
                {
                    "task_id": f"{qid}:o{orientation}",
                    "qid": qid,
                    "orientation": orientation,
                    "run_a": run_a,
                    "run_b": run_b,
                    "query": original[qid]["query"],
                    "answer_a": rows_a[qid]["answer_text"],
                    "answer_b": rows_b[qid]["answer_text"],
                }
            )

    from openai import OpenAI

    client = OpenAI(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=300.0,
        max_retries=4,
    )
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(judge, client, args.model, task) for task in tasks]
        results = [future.result() for future in as_completed(futures)]
    results.sort(key=lambda row: row["task_id"])

    counts = Counter(
        row["preferred_run_id"] or "tie"
        for row in results
        if row["status"] == "completed"
    )
    statuses = Counter(row["status"] for row in results)
    consistent = 0
    for qid in qids:
        pair = [row for row in results if row["qid"] == qid]
        if len(pair) == 2 and pair[0]["preferred_run_id"] == pair[1]["preferred_run_id"]:
            consistent += 1
    summary = {
        "model": args.model,
        "phrase_variant": injected_id,
        "topics": len(qids),
        "battles": len(tasks),
        "status_counts": dict(statuses),
        "preference_counts": dict(counts),
        "order_consistent_topics": consistent,
        "order_consistency": consistent / len(qids) if qids else None,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "judgments.jsonl").open("w", encoding="utf-8") as stream:
        for row in results:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if statuses.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
