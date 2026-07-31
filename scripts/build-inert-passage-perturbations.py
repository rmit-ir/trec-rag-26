#!/usr/bin/env python3
"""Build inert passage-perturbation rows from resolved RAG answers.

Each output row contains one cited passage formatted as:

    Title: <query>

    <passage>. [CONTROL: <marker>]

The marker is deliberately restricted to a short identifier, not free-form
instructions.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

MARKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{number}: invalid JSON") from exc


def query_for(row: dict[str, Any], number: int) -> str:
    query = row.get("query") or row.get("topic")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"row {number}: missing query/topic")
    return query.strip()


def qid_for(row: dict[str, Any], number: int) -> str:
    qid = row.get("qid") or row.get("topic_id")
    if qid is None or not str(qid).strip():
        raise ValueError(f"row {number}: missing qid/topic_id")
    return str(qid).strip()


def punctuate(passage: str) -> str:
    passage = passage.strip()
    if not passage:
        raise ValueError("empty passage")
    return passage if passage[-1] in ".!?" else passage + "."


def build_text(query: str, passage: str, marker: str) -> str:
    return f"Title: {query}\n\n{punctuate(passage)} [CONTROL: {marker}]"


def build_rows(source: Path, marker: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, row in iter_jsonl(source):
        query = query_for(row, number)
        qid = qid_for(row, number)
        segments = row.get("segments")
        if not isinstance(segments, dict):
            raise ValueError(f"row {number}: segments must be an object")
        for docid, passage in segments.items():
            if not isinstance(docid, str) or not docid:
                raise ValueError(f"row {number}: invalid segment docid")
            if not isinstance(passage, str) or not passage.strip():
                raise ValueError(
                    f"row {number}: segment {docid!r} has no passage text")
            rows.append({
                "qid": qid,
                "docid": docid,
                "query": query,
                "marker": marker,
                "text": build_text(query, passage, marker),
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--marker", required=True,
        help="inert identifier: letters, digits, underscore, dot, or hyphen")
    args = parser.parse_args()
    if not MARKER_RE.fullmatch(args.marker):
        parser.error(
            "--marker must be a 1-64 character inert identifier containing "
            "only letters, digits, underscore, dot, or hyphen")

    rows = build_rows(args.input, args.marker)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(rows)} passage rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
