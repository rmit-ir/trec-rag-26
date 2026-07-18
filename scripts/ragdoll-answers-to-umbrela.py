#!/usr/bin/env python3
"""Convert resolved RAGDoll answers into UMBRELA relevance requests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(value)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Resolved RAGDoll answers JSONL.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    output_rows: list[dict[str, Any]] = []
    candidate_count = 0
    for row_number, row in enumerate(read_jsonl(args.input), start=1):
        run_id = str(row.get("run_id") or "run")
        qid = str(row.get("qid") or row.get("topic_id") or "")
        query = str(row.get("query") or row.get("topic") or "").strip()
        references = row.get("references")
        segments = row.get("segments")
        if not qid or not query:
            raise ValueError(f"row {row_number}: missing qid or query")
        if not isinstance(references, list) or not isinstance(segments, dict):
            raise ValueError(f"row {row_number}: missing references or resolved segments")

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for reference in references:
            docid = str(reference)
            if docid in seen:
                continue
            seen.add(docid)
            text = segments.get(docid)
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"row {row_number}: reference {docid!r} has no segment text")
            candidates.append({"doc": {"docid": docid, "segment": text}})

        output_rows.append({
            "task_id": f"{run_id}::{qid}",
            "query": {"qid": f"{run_id}::{qid}", "text": query},
            "candidates": candidates,
            "metadata": {"run_id": run_id, "qid": qid},
        })
        candidate_count += len(candidates)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in output_rows),
        encoding="utf-8",
    )
    print(f"wrote {len(output_rows)} queries and {candidate_count} cited candidates to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
