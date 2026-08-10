#!/usr/bin/env python3
"""Validate and structurally compare two organizer-format test119 runs."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from ragrun.outputs import validate_rag_output


def load(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["metadata"]["narrative_id"]: row for row in rows}


def summarize(rows: dict[str, dict], topics: dict[str, str]) -> dict:
    values = list(rows.values())
    words = [sum(len(item["text"].split()) for item in row["answer"]) for row in values]
    objects = [len(row["answer"]) for row in values]
    references = [len(row["references"]) for row in values]
    citations = [len(item["citations"]) for row in values for item in row["answer"]]
    violations = [
        {"qid": qid, "error": error}
        for qid, row in rows.items()
        for error in validate_rag_output(row)
    ]
    return {
        "run_id": values[0]["metadata"]["run_id"],
        "rows": len(values),
        "missing_qids": sorted(set(topics) - set(rows)),
        "extra_qids": sorted(set(rows) - set(topics)),
        "narrative_mismatches": sorted(
            qid for qid, row in rows.items() if topics.get(qid) != row["metadata"]["narrative"]
        ),
        "validation_violations": violations,
        "words": {
            "mean": round(statistics.mean(words), 2),
            "min": min(words),
            "max": max(words),
        },
        "answer_objects_mean": round(statistics.mean(objects), 2),
        "references_mean": round(statistics.mean(references), 2),
        "citations_per_object_mean": round(statistics.mean(citations), 3),
        "uncited_objects": sum(value == 0 for value in citations),
        "uncited_object_rate": round(sum(value == 0 for value in citations) / len(citations), 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("topics", type=Path)
    args = parser.parse_args()

    topics = {
        qid.strip(): narrative.strip()
        for line in args.topics.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for qid, _, narrative in [line.partition("\t")]
    }
    left = load(args.left)
    right = load(args.right)
    shared = sorted(set(left) & set(right))
    jaccards = []
    for qid in shared:
        left_refs = set(left[qid]["references"])
        right_refs = set(right[qid]["references"])
        union = left_refs | right_refs
        jaccards.append(len(left_refs & right_refs) / len(union) if union else 1.0)

    print(
        json.dumps(
            {
                "left": summarize(left, topics),
                "right": summarize(right, topics),
                "shared_qids": len(shared),
                "mean_reference_jaccard": round(statistics.mean(jaccards), 6),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
