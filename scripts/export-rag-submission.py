#!/usr/bin/env python3
"""Export internal *.output.json artifacts as organizer-safe TREC JSONL.

The internal files may contain a top-level ``trace`` object. This exporter
writes only ``metadata``, ``references``, and ``answer`` and validates every
row before producing the submission file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ragrun import jsonl_row, submission_output, validate_rag_output  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Internal *.output.json files or directories containing them.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination rag_output_trec_rag_2026.jsonl.",
    )
    args = parser.parse_args()

    files: list[Path] = []
    for item in args.inputs:
        if item.is_dir():
            files.extend(sorted(item.glob("*.output.json")))
        elif item.name.endswith(".output.json"):
            files.append(item)
        else:
            parser.error(f"not an output artifact: {item}")
    files = sorted(dict.fromkeys(path.resolve() for path in files))
    if not files:
        parser.error("no *.output.json files found")

    rows: list[str] = []
    seen_topics: set[str] = set()
    for path in files:
        internal = json.loads(path.read_text(encoding="utf-8"))

        # A crashed run still writes a schema-valid artifact: the answer is a
        # single "Run failed: ..." sentence with no references, which passes
        # every rule in validate_rag_output. An expired AWS token once turned
        # all 119 test topics into exactly that. The run's own status is the
        # only thing that can tell them apart, so gate on it before the
        # schema check.
        status = internal.get("trace", {}).get("status")
        if status is None:
            print(f"FAIL {path}", file=sys.stderr)
            print("  - no trace.status; cannot confirm the run succeeded",
                  file=sys.stderr)
            return 1
        if status not in ("completed", "budget_exhausted"):
            print(f"FAIL {path}", file=sys.stderr)
            print(f"  - run status is {status!r}, not a finished run",
                  file=sys.stderr)
            return 1

        official = submission_output(internal)
        errors = validate_rag_output(official)
        if errors:
            print(f"FAIL {path}", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1
        topic = str(official["metadata"]["narrative_id"])
        if topic in seen_topics:
            print(f"FAIL duplicate narrative_id {topic}: {path}", file=sys.stderr)
            return 1
        seen_topics.add(topic)
        rows.append(jsonl_row(official))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
