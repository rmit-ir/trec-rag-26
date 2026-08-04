#!/usr/bin/env python3
"""Audit the four comparison runs against every rule in ``rag-task.md``.

``validate_rag_output`` deliberately enforces only the **Validation Rules**
section, because the guidelines forbid inventing extra stylistic checks. This
script is the wider read: it also reports on the **Answer Rules** and on
properties the spec calls out as *not* rejectable but which still matter for the
score (uncited objects, duplicate references, citation ordering). Everything it
reports is labelled as either a hard violation or an advisory, so an advisory is
never mistaken for a spec breach.

    PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/scripts/audit_test119_conformance.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
sys.path.insert(0, str(ROOT / "src"))

from ragrun.outputs import validate_rag_output  # noqa: E402

EVAL_DIR = ROOT / "data/task-comparison/test119-eval"
TOPICS_TSV = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
              "/test-data/trec_rag_2026_queries.tsv")
LABELS = ["ours-semantic", "ours-keyword", "base-agentic-bm25", "base-singlepass"]
REQUIRED_META = ("team_id", "narrative_id", "narrative", "run_id", "run_desc")


def load_topics() -> dict[str, str]:
    topics = {}
    for line in TOPICS_TSV.read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid, _, narrative = line.partition("\t")
            topics[qid.strip()] = narrative.strip()
    return topics


def audit(label: str, rows: list[dict], topics: dict[str, str]) -> dict[str, Counter]:
    hard, advisory = Counter(), Counter()
    for row in rows:
        qid = row.get("metadata", {}).get("narrative_id", "?")

        # --- Validation Rules (hard) -------------------------------------
        for err in validate_rag_output(row):
            hard[err.split(":")[0].split("(")[0].strip()] += 1

        refs = row["references"]
        if len(refs) != len(set(refs)):
            hard["references contains duplicate docids"] += 1
        meta = row.get("metadata", {})
        for key in REQUIRED_META:
            if not str(meta.get(key, "")).strip():
                hard[f"metadata.{key} empty"] += 1
        # narrative must be "copied exactly" from column 2 of the TSV.
        if qid in topics and meta.get("narrative", "").strip() != topics[qid]:
            hard["metadata.narrative does not match the official TSV"] += 1

        # --- Answer Rules (advisory: real score impact, not rejections) ---
        for i, item in enumerate(row["answer"]):
            text, cits = item["text"], item["citations"]
            if not text.strip():
                hard["answer[].text is empty"] += 1
            if not cits:
                advisory["uncited answer object (scores 0 for weighted recall)"] += 1
            if len(cits) != len(set(map(str, cits))):
                advisory["duplicate citation inside one answer object"] += 1
            if len(text.split()) > 80:
                advisory["answer object over 80 words (not sentence-level)"] += 1
        used = set()
        for item in row["answer"]:
            for c in item["citations"]:
                used.add(refs[c] if isinstance(c, int) else c)
        if len(used) < len(refs):
            advisory["references listed but never cited (permitted)"] += len(refs) - len(used)
    return {"hard": hard, "advisory": advisory}


def main() -> int:
    topics = load_topics()
    print("Audit against skills/trec-rag-2026-track-guidelines/references/rag-task.md\n")
    exit_code = 0
    for label in LABELS:
        path = EVAL_DIR / f"{label}.jsonl"
        rows = [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = audit(label, rows, topics)
        print(f"### {label}  ({len(rows)} narratives)")
        if result["hard"]:
            exit_code = 1
            for msg, n in result["hard"].most_common():
                print(f"  VIOLATION  {msg}  x{n}")
        else:
            print("  VIOLATION  none — passes every Validation Rule")
        for msg, n in result["advisory"].most_common():
            print(f"  advisory   {msg}  x{n}")
        print()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
