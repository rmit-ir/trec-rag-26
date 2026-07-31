#!/usr/bin/env python3
"""Convert injected RAG answers to UMBRELA query-candidate requests."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "answers.injected.jsonl"
DEFAULT_OUTPUT = SCRIPT_DIR / "ragdoll-relevance" / "requests.jsonl"


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON") from exc


def build_requests(path: Path) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()
    for number, row in read_jsonl(path):
        run_id = str(row.get("run_id") or "").strip()
        qid = str(row.get("qid") or row.get("topic_id") or "").strip()
        query = str(row.get("query") or row.get("topic") or "").strip()
        answer = row.get("answer_text")
        if not run_id or not qid or not query:
            raise ValueError(
                f"{path}:{number}: missing run_id, qid/topic_id, or query/topic")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"{path}:{number}: missing answer_text")
        task_id = f"{run_id}::{qid}"
        if task_id in seen_task_ids:
            raise ValueError(f"{path}:{number}: duplicate task_id {task_id!r}")
        seen_task_ids.add(task_id)
        requests.append({
            "task_id": task_id,
            "query": {"qid": task_id, "text": query},
            "candidates": [{
                "doc": {
                    "docid": "injected-answer",
                    "segment": answer.strip(),
                },
            }],
            "metadata": {
                "run_id": run_id,
                "qid": qid,
                "candidate_kind": "injected_answer",
            },
        })
    return requests


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(
                    row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    requests = build_requests(args.input)
    atomic_write_jsonl(args.output, requests)
    print(f"wrote {len(requests)} UMBRELA requests to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
