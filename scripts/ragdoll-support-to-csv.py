#!/usr/bin/env python3
"""Convert RAGDoll citation-support judgments into reviewable CSV files."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

LABEL_NAMES = {"FS": "Full Support", "PS": "Partial Support", "NS": "No Support"}


def compact(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def read_rows(path: Path) -> list[dict[str, Any]]:
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
    parser.add_argument("input", type=Path, help="RAGDoll support judgments JSONL.")
    parser.add_argument("--output", required=True, type=Path, help="Detailed CSV destination.")
    parser.add_argument(
        "--summary-output", type=Path, help="Run-level summary CSV (default: <output>.summary.csv)."
    )
    parser.add_argument("--citation-chars", type=int, default=500)
    args = parser.parse_args()
    if args.citation_chars < 1:
        parser.error("--citation-chars must be positive")

    rows = read_rows(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id", "qid", "sentence_index", "citation_index", "docid",
        "support_label", "support_verdict", "status", "statement",
        "citation_excerpt", "error", "task_id",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            label = row.get("support_label")
            writer.writerow({
                "run_id": metadata.get("run_id", ""),
                "qid": metadata.get("topic_id", ""),
                "sentence_index": metadata.get("sentence_index", ""),
                "citation_index": metadata.get("citation_index", ""),
                "docid": metadata.get("docid", ""),
                "support_label": label or "",
                "support_verdict": LABEL_NAMES.get(str(label), "Judge Error"),
                "status": row.get("status", ""),
                "statement": compact(row.get("statement"), 10_000),
                "citation_excerpt": compact(row.get("citation"), args.citation_chars),
                "error": compact(row.get("error"), 2_000),
                "task_id": row.get("task_id", ""),
            })

    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        run_id = str(metadata.get("run_id", ""))
        label = str(row.get("support_label") or "ERROR")
        grouped[run_id][label] += 1

    summary_output = args.summary_output or args.output.with_name(f"{args.output.stem}.summary.csv")
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    with summary_output.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = [
            "run_id", "total", "full_support", "partial_support", "no_support",
            "judge_errors", "full_support_rate", "partial_or_full_rate",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for run_id in sorted(grouped):
            counts = grouped[run_id]
            total = sum(counts.values())
            full = counts["FS"]
            partial = counts["PS"]
            writer.writerow({
                "run_id": run_id,
                "total": total,
                "full_support": full,
                "partial_support": partial,
                "no_support": counts["NS"],
                "judge_errors": counts["ERROR"],
                "full_support_rate": f"{full / total:.6f}" if total else "",
                "partial_or_full_rate": f"{(full + partial) / total:.6f}" if total else "",
            })

    print(f"wrote {len(rows)} judgment rows to {args.output}")
    print(f"wrote {len(grouped)} run summaries to {summary_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
