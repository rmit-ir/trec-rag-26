#!/usr/bin/env python3
"""Export one complete TREC RAG 2026 run as organizer-safe JSONL.

Internal ``*.output.json`` files may contain a top-level ``trace`` object. This
exporter strips it, validates every organizer-facing row, verifies exact
coverage of the 119 official test narratives, and writes rows in official topic
order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ragrun import jsonl_row, submission_output, validate_rag_output  # noqa: E402
from ragrun.outputs import atomic_write_text  # noqa: E402

DEFAULT_TOPICS = (
    REPO_ROOT
    / "data/official/trec-rag-2026-data/trec-rag-2026/test-data"
    / "trec_rag_2026_queries.tsv"
)
OFFICIAL_NARRATIVE_IDS = tuple(f"rag2026-{index}" for index in range(119))
FINISHED_STATUSES = {"completed", "budget_exhausted"}
CONSISTENT_METADATA_FIELDS = ("team_id", "run_id", "run_desc")


class ExportError(ValueError):
    """Raised when inputs cannot form one complete official submission."""


def _preview(values: Sequence[str], limit: int = 8) -> str:
    shown = ", ".join(values[:limit])
    if len(values) > limit:
        shown += f", ... ({len(values)} total)"
    return shown


def load_official_topics(path: Path) -> tuple[list[tuple[str, str]], str]:
    """Load and validate the canonical 119-row test-narrative TSV."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ExportError(f"cannot read topics file {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExportError(f"topics file is not valid UTF-8: {path}: {exc}") from exc

    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    topics: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if not line:
            raise ExportError(f"topics file has a blank row at line {lineno}")
        fields = line.split("\t")
        if len(fields) != 2:
            raise ExportError(
                f"topics line {lineno} must contain exactly two tab-separated "
                f"fields, got {len(fields)}"
            )
        narrative_id, narrative = fields
        if not narrative_id or not narrative:
            raise ExportError(
                f"topics line {lineno} has an empty narrative ID or narrative"
            )
        if narrative_id in seen:
            raise ExportError(
                f"duplicate narrative ID {narrative_id!r} in topics lines "
                f"{seen[narrative_id]} and {lineno}"
            )
        seen[narrative_id] = lineno
        topics.append((narrative_id, narrative))

    actual_ids = tuple(narrative_id for narrative_id, _ in topics)
    if actual_ids != OFFICIAL_NARRATIVE_IDS:
        expected = set(OFFICIAL_NARRATIVE_IDS)
        actual = set(actual_ids)
        missing = [qid for qid in OFFICIAL_NARRATIVE_IDS if qid not in actual]
        unexpected = [qid for qid in actual_ids if qid not in expected]
        details: list[str] = []
        if missing:
            details.append(f"missing: {_preview(missing)}")
        if unexpected:
            details.append(f"unexpected: {_preview(unexpected)}")
        if not details:
            details.append("all IDs are present but not in official order")
        raise ExportError(
            "topics file must contain exactly rag2026-0 through rag2026-118 "
            f"in official order ({'; '.join(details)})"
        )

    return topics, hashlib.sha256(raw).hexdigest()


def input_files(items: Sequence[Path]) -> list[Path]:
    """Resolve explicit artifacts and top-level artifacts in input directories."""
    files: list[Path] = []
    for item in items:
        if item.is_dir():
            files.extend(sorted(item.glob("*.output.json")))
        elif item.is_file() and item.name.endswith(".output.json"):
            files.append(item)
        elif not item.exists():
            raise ExportError(f"input does not exist: {item}")
        else:
            raise ExportError(f"not an output artifact or directory: {item}")
    files = sorted(dict.fromkeys(path.resolve() for path in files))
    if not files:
        raise ExportError("no *.output.json files found")
    return files


def _load_artifact(path: Path) -> dict[str, Any]:
    try:
        internal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"cannot read output artifact {path}: {exc}") from exc
    if not isinstance(internal, dict):
        raise ExportError(f"{path}: output artifact must be a JSON object")

    trace = internal.get("trace")
    status = trace.get("status") if isinstance(trace, dict) else None
    if status is None:
        raise ExportError(f"{path}: no trace.status; cannot confirm the run succeeded")
    if not isinstance(status, str) or status not in FINISHED_STATUSES:
        raise ExportError(f"{path}: run status is {status!r}, not a finished run")

    errors = validate_rag_output(internal)
    if errors:
        detail = "\n".join(f"  - {error}" for error in errors)
        raise ExportError(f"{path}: invalid RAG output\n{detail}")
    return submission_output(internal)


def build_submission_rows(
    files: Sequence[Path],
    topics: Sequence[tuple[str, str]],
    *,
    expected_team_id: str,
    expected_run_id: str,
) -> list[str]:
    """Validate artifacts as one run and serialize them in official order."""
    expected_narratives = dict(topics)
    by_topic: dict[str, tuple[Path, dict[str, Any]]] = {}
    run_metadata: dict[str, Any] | None = None

    for path in files:
        official = _load_artifact(path)
        metadata = official["metadata"]
        narrative_id = metadata["narrative_id"]
        if not isinstance(narrative_id, str):
            raise ExportError(
                f"{path}: metadata.narrative_id must be a string, got "
                f"{type(narrative_id).__name__}"
            )
        if narrative_id not in expected_narratives:
            raise ExportError(
                f"{path}: narrative_id {narrative_id!r} is not in the official "
                "test topics"
            )
        if narrative_id in by_topic:
            previous = by_topic[narrative_id][0]
            raise ExportError(
                f"duplicate narrative_id {narrative_id!r}: {previous} and {path}"
            )
        if metadata["narrative"] != expected_narratives[narrative_id]:
            raise ExportError(
                f"{path}: metadata.narrative does not exactly match the official "
                f"text for {narrative_id}"
            )
        if metadata["team_id"] != expected_team_id:
            raise ExportError(
                f"{path}: metadata.team_id is {metadata['team_id']!r}, expected "
                f"{expected_team_id!r}"
            )
        if metadata["run_id"] != expected_run_id:
            raise ExportError(
                f"{path}: metadata.run_id is {metadata['run_id']!r}, expected "
                f"{expected_run_id!r}"
            )

        if run_metadata is None:
            run_metadata = {
                field: metadata[field] for field in CONSISTENT_METADATA_FIELDS
            }
        else:
            for field in CONSISTENT_METADATA_FIELDS:
                if metadata[field] != run_metadata[field]:
                    raise ExportError(
                        f"{path}: metadata.{field} is {metadata[field]!r}, but "
                        f"the run started with {run_metadata[field]!r}"
                    )
        by_topic[narrative_id] = (path, official)

    missing = [narrative_id for narrative_id, _ in topics if narrative_id not in by_topic]
    if missing:
        raise ExportError(f"submission is missing narratives: {_preview(missing)}")

    return [jsonl_row(by_topic[narrative_id][1]) for narrative_id, _ in topics]


def export_submission(
    inputs: Sequence[Path],
    *,
    topics_path: Path,
    output_path: Path,
    expected_team_id: str,
    expected_run_id: str,
) -> tuple[int, str]:
    """Validate and atomically write one complete official submission."""
    topics, topics_sha256 = load_official_topics(topics_path)
    files = input_files(inputs)
    resolved_output = output_path.resolve()
    if resolved_output == topics_path.resolve() or resolved_output in files:
        raise ExportError("--output must not overwrite a topics or input artifact file")

    rows = build_submission_rows(
        files,
        topics,
        expected_team_id=expected_team_id,
        expected_run_id=expected_run_id,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, "\n".join(rows) + "\n")
    return len(rows), topics_sha256


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Internal *.output.json files or directories containing them.",
    )
    parser.add_argument(
        "--topics",
        type=Path,
        default=DEFAULT_TOPICS,
        help=f"Official 119-row test TSV (default: {DEFAULT_TOPICS}).",
    )
    parser.add_argument(
        "--team-id",
        required=True,
        help="Expected metadata.team_id in every artifact.",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Expected metadata.run_id in every artifact.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination rag_output_trec_rag_2026.jsonl.",
    )
    args = parser.parse_args(argv)
    if not args.team_id or not args.run_id:
        parser.error("--team-id and --run-id must be non-empty")

    try:
        count, topics_sha256 = export_submission(
            args.inputs,
            topics_path=args.topics,
            output_path=args.output,
            expected_team_id=args.team_id,
            expected_run_id=args.run_id,
        )
    except ExportError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1

    print(
        f"validated {count} official narratives for team_id={args.team_id!r}, "
        f"run_id={args.run_id!r}; topics_sha256={topics_sha256}"
    )
    print(f"wrote {count} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
