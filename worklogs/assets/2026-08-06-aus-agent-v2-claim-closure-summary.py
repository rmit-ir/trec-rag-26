#!/usr/bin/env python3
"""Compare the old anchor validator with full claim-closure invariants offline."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OLD = ROOT / (
    "worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.json"
)
DEFAULT_NEW = ROOT / (
    "worklogs/assets/2026-08-06-aus-agent-v2-claim-closure-replay.json"
)
VALIDATOR = ROOT / "src/systems/aus_agent_v2/coverage_contract.py"


def _sha256(path: Path) -> str:
    """Identify every exact replay input and implementation."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    """Use repository-relative paths in durable output."""
    return str(path.resolve().relative_to(ROOT))


def _rows(matrix: dict[str, Any]) -> dict[tuple[Any, ...], dict[str, Any]]:
    """Index every row by its durable topic/batch/document/fact coordinates."""
    result = {}
    for batch in matrix["batch_matrix"]:
        for row in batch["rows"]:
            key = (
                batch["qid"],
                batch["batch_index"],
                row["document_index"],
                row["fact_index"],
            )
            result[key] = {"batch": batch, "row": row}
    return result


def _new_outcome(row: dict[str, Any]) -> str:
    """Split legacy `other_error` into the two new executable invariants."""
    outcome = str(row["outcome"])
    joined = " ; ".join(row.get("errors", []))
    if outcome != "other_error":
        return outcome
    if "value_scope contributes no exact" in joined:
        return "scope_not_carried"
    if "must_include omits quantitative/date literal" in joined:
        return "quantified_literal_not_carried"
    return "other_error"


def main() -> None:
    """Write complete transitions, topic counts, and representative raw rows."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--new", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    old_path = args.old.resolve()
    new_path = args.new.resolve()
    old = json.loads(old_path.read_text(encoding="utf-8"))
    new = json.loads(new_path.read_text(encoding="utf-8"))
    old_rows = _rows(old)
    new_rows = _rows(new)
    if old_rows.keys() != new_rows.keys():
        raise SystemExit("old and new replay row coordinates differ")

    totals: collections.Counter[str] = collections.Counter()
    transitions: collections.Counter[tuple[str, str]] = collections.Counter()
    by_topic: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    examples: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    rows = []
    for key in sorted(old_rows):
        old_entry = old_rows[key]
        new_entry = new_rows[key]
        old_row = old_entry["row"]
        new_row = new_entry["row"]
        old_outcome = str(old_row["outcome"])
        new_outcome = _new_outcome(new_row)
        qid = str(key[0])
        totals[new_outcome] += 1
        transitions[(old_outcome, new_outcome)] += 1
        by_topic[qid][new_outcome] += 1
        record = {
            "qid": qid,
            "batch_index": key[1],
            "document_index": key[2],
            "fact_index": key[3],
            "document_id": new_row["document_id"],
            "fact": new_row["fact"],
            "old_outcome": old_outcome,
            "new_outcome": new_outcome,
            "errors": new_row.get("errors", []),
        }
        rows.append(record)
        if len(examples[new_outcome]) < 5:
            examples[new_outcome].append(record)

    report = {
        "schema_version": 1,
        "method": (
            "Exact offline transition over all frozen historical fact cards. "
            "No model, provider, retrieval service, search, judge, or grader."
        ),
        "network_or_api_calls": 0,
        "paid_cost_usd": 0,
        "provenance": {
            "old_replay": _relative(old_path),
            "old_replay_sha256": _sha256(old_path),
            "new_replay": _relative(new_path),
            "new_replay_sha256": _sha256(new_path),
            "validator": _relative(VALIDATOR),
            "validator_sha256": _sha256(VALIDATOR),
        },
        "aggregate": {
            "topics": len(by_topic),
            "rows": len(rows),
            "old_valid": sum(
                count for (before, _), count in transitions.items()
                if before == "valid"
            ),
            "new_valid": totals["valid"],
            "new_outcomes": dict(sorted(totals.items())),
            "transition_matrix": [
                {"old": before, "new": after, "rows": count}
                for (before, after), count in sorted(transitions.items())
            ],
        },
        "topic_matrix": [
            {"qid": qid, "outcomes": dict(sorted(counts.items()))}
            for qid, counts in sorted(by_topic.items())
        ],
        "examples": dict(sorted(examples.items())),
        "row_matrix": rows,
        "limitations": [
            "Historical fact cards were not generated by the new tool schema.",
            "The replay diagnoses whether already-extracted fact fields formed "
            "an executable final-answer invariant; it does not forecast model "
            "correction success or rubric score.",
        ],
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["aggregate"], indent=2))


if __name__ == "__main__":
    main()
