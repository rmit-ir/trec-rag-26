#!/usr/bin/env python3
"""Extract query IDs and text from RAGDOLL/UMBRELA JSONL rows."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must differ")

    extracted: list[dict[str, str]] = []
    try:
        with args.input.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                query = row.get("query") if isinstance(row, dict) else None
                if not isinstance(query, dict):
                    raise ValueError(f"{args.input}:{line_number}: query must be an object")
                qid, text = query.get("qid"), query.get("text")
                if not isinstance(qid, str) or not isinstance(text, str):
                    raise ValueError(
                        f"{args.input}:{line_number}: query.qid and query.text must be strings"
                    )
                extracted.append({"qid": qid, "text": text})

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as stream:
            for query in extracted:
                stream.write(json.dumps(query, ensure_ascii=False, separators=(",", ":")) + "\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {len(extracted)} queries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
