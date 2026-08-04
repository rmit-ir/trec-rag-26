#!/usr/bin/env python3
"""Dump a fixed 10-narrative sample as readable text for hand judging.

Deterministic sample (every 12th narrative in official order) so the graded set
is reproducible and re-readable. Each block carries the narrative, our answer
with per-object citation docids, and the stronger baseline's answer for the same
narrative, so a human grader sees both without switching files.

    PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/scripts/dump_sample_for_hand_judging.py \
        --run ours-semantic --out /tmp/sample.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
EVAL_DIR = ROOT / "data/task-comparison/test119-eval"


def load(label: str) -> dict[str, dict]:
    rows = {}
    for line in (EVAL_DIR / f"{label}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            rows[obj["metadata"]["narrative_id"]] = obj
    return rows


def render(row: dict, *, show_docids: bool) -> str:
    refs = row["references"]
    lines = []
    for i, item in enumerate(row["answer"]):
        cits = item["citations"]
        if show_docids:
            names = [refs[c] if isinstance(c, int) else c for c in cits]
            tag = f"  [{', '.join(names)}]" if names else "  [NO CITATION]"
        else:
            tag = f"  {cits}" if cits else "  [NO CITATION]"
        lines.append(f"  {i:2d}. {item['text']}{tag}")
    words = sum(len(s["text"].split()) for s in row["answer"])
    return f"({words} words, {len(row['answer'])} objects, {len(refs)} refs)\n" + "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="ours-semantic")
    parser.add_argument("--compare", default="base-agentic-bm25")
    parser.add_argument("--every", type=int, default=12)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    ours, theirs = load(args.run), load(args.compare)
    qids = list(ours)[::args.every][:args.limit]

    blocks = [f"# Hand-judging sample — {args.run} vs {args.compare}\n"
              f"{len(qids)} narratives: {', '.join(qids)}\n"]
    for qid in qids:
        row = ours[qid]
        blocks.append(f"\n{'=' * 78}\n## {qid}\n\nNARRATIVE:\n{row['metadata']['narrative']}\n")
        blocks.append(f"\n--- {args.run} ---\n{render(row, show_docids=True)}\n")
        if qid in theirs:
            blocks.append(f"\n--- {args.compare} ---\n"
                          f"{render(theirs[qid], show_docids=False)}\n")
    args.out.write_text("\n".join(blocks), encoding="utf-8")
    print(f"wrote {len(qids)} narratives -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
