#!/usr/bin/env python3
"""Append text to judged content in RAGDOLL support or relevance JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def transform_answers(
    answer: list[Any], suffix: str, source: Path, line_number: int
) -> int:
    changed = 0
    for sentence_index, sentence in enumerate(answer):
        if not isinstance(sentence, dict) or not isinstance(sentence.get("text"), str):
            raise ValueError(
                f"{source}:{line_number}: answer[{sentence_index}].text must be a string"
            )
        sentence["text"] += suffix
        changed += 1
    return changed


def transform_candidates(
    candidates: list[Any], suffix: str, source: Path, line_number: int
) -> int:
    changed = 0
    for candidate_index, candidate in enumerate(candidates):
        doc = candidate.get("doc") if isinstance(candidate, dict) else None
        if not isinstance(doc, dict) or not isinstance(doc.get("segment"), str):
            raise ValueError(
                f"{source}:{line_number}: "
                f"candidates[{candidate_index}].doc.segment must be a string"
            )
        doc["segment"] += suffix
        changed += 1
    return changed


def transform_row(row: dict[str, Any], suffix: str, source: Path, line_number: int) -> int:
    answer = row.get("answer")
    candidates = row.get("candidates")
    if isinstance(answer, list):
        return transform_answers(answer, suffix, source, line_number)
    if isinstance(candidates, list):
        return transform_candidates(candidates, suffix, source, line_number)
    raise ValueError(
        f"{source}:{line_number}: expected an 'answer' or 'candidates' list"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        help="RAGDOLL support answers or UMBRELA relevance JSONL file.",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output JSONL file.")
    parser.add_argument(
        "--append-text",
        required=True,
        help="Exact text appended to every answer sentence or candidate segment.",
    )
    args = parser.parse_args()

    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must differ")

    rows: list[dict[str, Any]] = []
    item_count = 0
    try:
        with args.input.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{args.input}:{line_number}: expected a JSON object")
                item_count += transform_row(row, args.append_text, args.input, line_number)
                rows.append(row)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {len(rows)} rows and updated {item_count} judged text items to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
