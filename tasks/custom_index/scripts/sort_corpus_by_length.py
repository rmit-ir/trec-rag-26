#!/usr/bin/env python3
"""Sort a corpus-jsonl by contents length (longest first by default).

Length-bucketed batches encode faster: every batch then contains documents
with similar token counts, so padding waste shrinks and per-batch wall time
drops. Docids are preserved verbatim; only the row order changes — which is
fine because the docid contract only forbids reorder *before* docid
assignment, and the skill script has already assigned ids at this point.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    ap.add_argument("--order", choices=["desc", "asc"], default="desc",
                    help="desc = longest first (default; ensures OOM hits early)")
    args = ap.parse_args()

    records = []
    with open(args.input, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    records.sort(key=lambda r: len(r.get("contents", "")),
                 reverse=(args.order == "desc"))

    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wt", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(args.output)
    print(f"[sort] {args.input.name}: {len(records)} records, order={args.order}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
