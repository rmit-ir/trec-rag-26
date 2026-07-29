#!/usr/bin/env python3
"""Merge run-level RAGDoll request rows into one nugget-creation row per qid."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    return parser.parse_args()


def candidate_key(candidate: Any) -> tuple[str, str]:
    if isinstance(candidate, str):
        return ("text", candidate)
    if isinstance(candidate, dict):
        if isinstance(candidate.get("text"), str):
            return ("text", candidate["text"])
        doc = candidate.get("doc")
        if isinstance(doc, dict):
            docid = str(doc.get("docid", ""))
            segment = str(doc.get("segment", ""))
            return (docid, segment)
    return ("json", json.dumps(candidate, sort_keys=True, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    topics: OrderedDict[str, dict[str, Any]] = OrderedDict()

    with args.input_file.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]

    queries_by_qid: dict[str, set[str]] = {}
    normalized_rows = []
    for line_number, row in enumerate(rows, start=1):
        metadata = row.get("metadata") or {}
        query = row.get("query") or {}
        query_qid = query.get("qid") if isinstance(query, dict) else None
        qid = str(metadata.get("qid") or query_qid or row.get("qid") or "")
        query_text = query.get("text") if isinstance(query, dict) else query
        if not qid:
            raise ValueError(f"missing qid on line {line_number}")
        if not isinstance(query_text, str) or not query_text:
            raise ValueError(f"missing query text on line {line_number} for qid={qid}")
        queries_by_qid.setdefault(qid, set()).add(query_text)
        normalized_rows.append((row, metadata, qid, query_text))

    collision_qids = {qid for qid, queries in queries_by_qid.items() if len(queries) > 1}
    for row, metadata, original_qid, query_text in normalized_rows:
        qid = original_qid
        if qid in collision_qids:
            digest = hashlib.sha256(query_text.encode("utf-8")).hexdigest()[:12]
            qid = f"{qid}-{digest}"

        topic = topics.setdefault(
            qid,
            {
                "task_id": qid,
                "query": {"qid": qid, "text": query_text},
                "candidates": [],
                "_candidate_keys": set(),
                "_run_ids": [],
                "_original_qid": original_qid,
            },
        )

        run_id = metadata.get("run_id") or row.get("run_id")
        if run_id and run_id not in topic["_run_ids"]:
            topic["_run_ids"].append(run_id)
        candidates = row.get("candidates")
        if not isinstance(candidates, list):
            segments = row.get("segments") or {}
            candidates = [
                {"doc": {"docid": str(docid), "segment": str(segment)}}
                for docid, segment in segments.items()
            ]
        for candidate in candidates:
            key = candidate_key(candidate)
            if key not in topic["_candidate_keys"]:
                topic["_candidate_keys"].add(key)
                topic["candidates"].append(candidate)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    candidate_count = 0
    with args.output_file.open("w", encoding="utf-8", newline="\n") as handle:
        for topic in topics.values():
            candidate_count += len(topic["candidates"])
            output = {
                "task_id": topic["task_id"],
                "query": topic["query"],
                "candidates": topic["candidates"],
                "metadata": {
                    "original_qid": topic["_original_qid"],
                    "source_run_ids": topic["_run_ids"],
                },
            }
            handle.write(json.dumps(output, ensure_ascii=False) + "\n")

    print(f"topics={len(topics)} candidates={candidate_count} output={args.output_file}")


if __name__ == "__main__":
    main()
