#!/usr/bin/env python3
"""Replay frozen fact cards through the exact strict anchor normalizer.

This offline audit consumes the complete historical fact-card matrix produced
by the prior commit-validator replay. Every original row is mapped to one P01
support exactly as that audit specified, then passed through the current public
normalize_commit_supports and validate_support_routes functions against the
frozen local chunk docstore.

Run from the repository root:

    uv run --project tasks/search_serve python \
      worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.py \
      --output worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.json

No network, retrieval service, model provider, or grader is contacted.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[2]
INPUT = ROOT / (
    "worklogs/assets/"
    "2026-08-06-aus-agent-v2-commit-validator-replay.json"
)
VALIDATOR = ROOT / "src/systems/aus_agent_v2/coverage_contract.py"
DOCSTORE = ROOT / "data/built-indexes/climbmix-chunked/docstore"

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src/systems"))
sys.path.insert(0, str(ROOT / "tasks/search_serve/scripts"))

from systems.aus_agent_v2.coverage_contract import (  # noqa: E402
    ContractItem,
    normalize_commit_supports,
    validate_support_routes,
)
from docstore import FlatShardDocStore  # noqa: E402


ITEMS = [
    ContractItem(
        id="P01",
        origin="replay",
        kind="evidence",
        requirement="Replay one historical fact card.",
    )
]


def relative(path: Path) -> str:
    """Return one stable repository-relative path."""
    return str(path.resolve().relative_to(ROOT))


def sha256(path: Path) -> str:
    """Hash an input so the matrix identifies its exact source state."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(errors: list[str]) -> str:
    """Assign one exhaustive outcome to the exact current validation errors."""
    if not errors:
        return "valid"
    joined = " ; ".join(errors)
    if "must_include term; maximum is 80" in joined:
        return "oversized_term"
    if ("non-string must_include" in joined
            or "needs id and claim" in joined
            or "claim must be a string" in joined):
        return "malformed"
    if "uninformative must_include" in joined:
        return "checker_generic"
    if "outside its claim/scope" in joined:
        return "out_of_claim_scope"
    if "does not contain exact must_include" in joined:
        return "source_missing"
    return "other_error"


def validate_row(
    row: dict[str, Any],
    source_text: str,
) -> dict[str, Any]:
    """Run one historical mapping through both exact public validators."""
    fact = row.get("fact")
    fact = fact if isinstance(fact, dict) else {}
    arguments = {
        "documents": [{
            "id": row.get("document_id"),
            "reason": row.get("commit_reason"),
            "supports": [{
                "requirement_id": "P01",
                "claim": fact.get("claim"),
                "value_scope": fact.get("scope", ""),
                "must_include": [fact.get("value")],
            }],
        }],
    }
    supports, errors = normalize_commit_supports(arguments, ITEMS)
    if not errors:
        errors = validate_support_routes(supports, [{
            "id": row.get("document_id"),
            "text": source_text,
            "metadata": {"for_requirements": ["P01"]},
        }])
    normalized = []
    for anchor in supports.get("P01", []):
        normalized.append({
            "document_id": anchor.document_id,
            "claim": anchor.claim,
            "value_scope": anchor.value_scope,
            "must_include": list(anchor.must_include),
        })
    return {
        "document_index": row.get("document_index"),
        "fact_index": row.get("fact_index"),
        "document_id": row.get("document_id"),
        "commit_reason": row.get("commit_reason"),
        "fact": fact,
        "exact_mapping": arguments["documents"][0]["supports"][0],
        "normalized_anchors": normalized,
        "errors": errors,
        "outcome": classify(errors),
    }


def main() -> None:
    """Write the full deterministic row, batch, and topic result matrices."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=INPUT,
        help="Complete prior fact-card matrix.",
    )
    parser.add_argument(
        "--output", type=Path, default=SCRIPT.with_suffix(".json"),
        help="Output matrix path.",
    )
    args = parser.parse_args()
    input_path = args.input.resolve()
    source = json.loads(input_path.read_text(encoding="utf-8"))
    proxy = source["fact_card_proxy_replay"]
    store = FlatShardDocStore(DOCSTORE, lru_size=64)
    source_cache: dict[str, str] = {}
    aggregate: collections.Counter[str] = collections.Counter()
    topic_counts: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    batches: list[dict[str, Any]] = []
    try:
        for old_batch in proxy["batch_matrix"]:
            rows = []
            for old_row in old_batch["rows"]:
                document_id = str(old_row.get("document_id") or "")
                if document_id not in source_cache:
                    source_cache[document_id] = store.get_text(document_id)
                row = validate_row(old_row, source_cache[document_id])
                rows.append(row)
                aggregate[row["outcome"]] += 1
                topic_counts[old_batch["qid"]][row["outcome"]] += 1
            invalid_rows = sum(row["outcome"] != "valid" for row in rows)
            batches.append({
                "batch_index": old_batch["batch_index"],
                "qid": old_batch["qid"],
                "artifact": old_batch["artifact"],
                "trace_step": old_batch["trace_step"],
                "trace_turn": old_batch["trace_turn"],
                "fact_rows": len(rows),
                "invalid_rows": invalid_rows,
                "counterfactual_batch_result": (
                    "expire" if invalid_rows else "commit"
                ),
                "outcomes": dict(collections.Counter(
                    row["outcome"] for row in rows
                )),
                "rows": rows,
            })
    finally:
        store.close()

    topics = []
    old_topics = {
        topic["qid"]: topic for topic in proxy["topic_matrix"]
    }
    for qid in sorted(old_topics):
        old = old_topics[qid]
        selected = [batch for batch in batches if batch["qid"] == qid]
        topics.append({
            "qid": qid,
            "narrative": old["narrative"],
            "artifact": old["artifact"],
            "artifact_sha256": old["artifact_sha256"],
            "commit_batches": len(selected),
            "fact_rows": sum(batch["fact_rows"] for batch in selected),
            "invalid_batches": sum(
                batch["counterfactual_batch_result"] == "expire"
                for batch in selected
            ),
            "outcomes": dict(sorted(topic_counts[qid].items())),
        })

    invalid_batches = sum(
        batch["counterfactual_batch_result"] == "expire"
        for batch in batches
    )
    report = {
        "schema_version": 1,
        "audit": "strict aus_agent_v2 anchor validation replay",
        "network_or_api_calls": 0,
        "bedrock_cost_usd": 0,
        "exact_mapping": {
            "requirement_id": "P01",
            "claim": 'fact["claim"]',
            "value_scope": 'fact.get("scope", "")',
            "must_include": ['fact["value"]'],
        },
        "provenance": {
            "script": relative(SCRIPT),
            "script_sha256": sha256(SCRIPT),
            "input_matrix": relative(input_path),
            "input_matrix_sha256": sha256(input_path),
            "validator": relative(VALIDATOR),
            "validator_sha256": sha256(VALIDATOR),
            "docstore": relative(DOCSTORE),
            "docstore_manifest_sha256": sha256(DOCSTORE / "manifest.json"),
        },
        "aggregate": {
            "topics": len(topics),
            "commit_batches": len(batches),
            "fact_rows": sum(aggregate.values()),
            "invalid_batches": invalid_batches,
            "committing_batches": len(batches) - invalid_batches,
            "outcomes": dict(sorted(aggregate.items())),
        },
        "limitations": [
            "The mapping is a counterfactual proxy, not output from the contract prompt.",
            "Historical rows have no requirement ids; one valid P01 route is supplied.",
            "The new prompt explicitly asks for short source-verbatim literals.",
        ],
        "topic_matrix": topics,
        "batch_matrix": batches,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(f"wrote {relative(output)}")
    print(f"aggregate={report['aggregate']}")


if __name__ == "__main__":
    main()
