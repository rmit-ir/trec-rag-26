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
    parser.add_argument(
        "--run-id",
        help="Export only artifacts whose metadata.run_id exactly matches.",
    )
    parser.add_argument(
        "--topics",
        type=Path,
        help=("Optional narrative_id<TAB>narrative TSV. Require exactly one "
              "matching artifact per row and emit rows in TSV order."),
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

    expected: dict[str, str] | None = None
    if args.topics is not None:
        expected = {}
        for line_no, line in enumerate(
                args.topics.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            topic, separator, narrative = line.partition("\t")
            if not separator or not topic or not narrative:
                parser.error(
                    f"{args.topics}:{line_no}: expected "
                    "narrative_id<TAB>narrative")
            if topic in expected:
                parser.error(
                    f"{args.topics}:{line_no}: duplicate narrative_id {topic}")
            expected[topic] = narrative

    rows_by_topic: dict[str, str] = {}
    ignored_failed: list[Path] = []
    for path in files:
        internal = json.loads(path.read_text(encoding="utf-8"))
        metadata = internal.get("metadata", {})
        if args.run_id is not None and metadata.get("run_id") != args.run_id:
            continue

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
        if (status == "failed" and args.run_id is not None
                and expected is not None):
            # A resumable production run deliberately keeps failed attempts for
            # audit. A later completed artifact for the same run/topic should
            # supersede that attempt, while the --topics coverage gate below
            # still fails if no successful replacement exists.
            ignored_failed.append(path)
            continue
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
        if topic in rows_by_topic:
            print(f"FAIL duplicate narrative_id {topic}: {path}", file=sys.stderr)
            return 1
        if expected is not None:
            if topic not in expected:
                print(f"FAIL unexpected narrative_id {topic}: {path}",
                      file=sys.stderr)
                return 1
            actual_narrative = official["metadata"]["narrative"]
            if actual_narrative != expected[topic]:
                print(f"FAIL narrative text differs for {topic}: {path}",
                      file=sys.stderr)
                return 1
        rows_by_topic[topic] = jsonl_row(official)

    if not rows_by_topic:
        detail = f" for run-id {args.run_id!r}" if args.run_id else ""
        print(f"FAIL no matching output artifacts{detail}", file=sys.stderr)
        return 1

    if expected is not None:
        missing = [topic for topic in expected if topic not in rows_by_topic]
        if missing:
            print(f"FAIL missing {len(missing)} narrative(s): "
                  f"{', '.join(missing)}", file=sys.stderr)
            return 1
        order = list(expected)
    else:
        order = sorted(rows_by_topic)
    rows = [rows_by_topic[topic] for topic in order]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows to {args.output}")
    if ignored_failed:
        print(f"ignored {len(ignored_failed)} superseded failed attempt(s) "
              f"for run-id {args.run_id!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
