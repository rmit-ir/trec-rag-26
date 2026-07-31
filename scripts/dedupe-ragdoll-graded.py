#!/usr/bin/env python3
"""Keep the last occurrence of each task in a RAGDOLL graded JSONL file."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def dedupe_rows(path: Path) -> list[dict]:
    """Return the latest row for every task_id in last-occurrence order."""
    # Repeated RAGDOLL runs append another row with the same task_id. Storing
    # rows in a dictionary makes the most recently encountered row win.
    by_task: dict[str, tuple[int, dict]] = {}
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            row = json.loads(line)
            task_id = str(row.get("task_id", "")).strip()
            if not task_id:
                raise ValueError(f"{path}: row {index + 1} has no task_id")
            # Retain the source position so final rows remain deterministically
            # ordered by where their latest judgments appeared.
            by_task[task_id] = (index, row)
    # Sorting dictionary values by their saved positions reconstructs the
    # last run's ordering without changing any judgment content.
    return [row for _, row in sorted(by_task.values())]


def atomic_write(path: Path, rows: list[dict]) -> None:
    """Write a complete sibling file before atomically replacing the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        # The temporary file prevents readers from observing partial JSONL.
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main() -> int:
    """Parse paths, deduplicate the source, and materialize the clean output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    rows = dedupe_rows(args.input)
    atomic_write(args.output, rows)
    print(f"wrote {len(rows)} deduplicated rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
