#!/usr/bin/env python3
"""Report pairwise preference by system and randomized display position."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    judgments = [
        json.loads(line)
        for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cells: dict[tuple[str, str, str], dict[str, float]] = defaultdict(
        lambda: {"n": 0, "score": 0.0}
    )
    for row in judgments:
        pair = "|".join(row["pair"])
        for run_id, position in (
            (row["assistant_a_run_id"], "A"),
            (row["assistant_b_run_id"], "B"),
        ):
            cell = cells[(pair, run_id, position)]
            cell["n"] += 1
            if row["preferred_run_id"] == run_id:
                cell["score"] += 1
            elif row["judge_verdict"] in {"Tie", "Tie (Both Bad)"}:
                cell["score"] += 0.5

    print("pair\trun_id\tposition\tn\tpreference_rate")
    for (pair, run_id, position), cell in sorted(cells.items()):
        print(
            f"{pair}\t{run_id}\t{position}\t{int(cell['n'])}"
            f"\t{cell['score'] / cell['n']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
