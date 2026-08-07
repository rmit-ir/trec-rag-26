#!/usr/bin/env python3
"""Replay the v2 commit-anchor validator against frozen local artifacts.

This is an offline counterfactual audit.  The best pre-repair aus_agent_v2
artifacts predate ``supports`` and contain no support annotations, so they can
establish only the number and size of commit decisions exposed to the new
failure path.  The closest saved annotation behavior is the 30-topic
``v2l-dev30-facts`` arm.  For that arm, this script maps every historical fact
card to one hypothetical support anchor as follows::

    claim         = fact["claim"]
    value_scope   = fact.get("scope", "")
    must_include  = [fact["value"]]

The script applies the exact private helpers imported from the current
``coverage_contract.py`` and then checks the normalized term against the exact
local chunk text.  Requirement-id and search-route checks are intentionally
out of scope: historical fact cards and searches have no contract ids.

Run from the repository root, using the docstore task environment::

    uv run --project tasks/search_serve python \
      worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.py \
      --output worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.json

No network service, model provider, or search API is contacted.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[2]
V2_OUTPUTS = ROOT / "data/outputs/aus_agent_v2"
FACT_OUTPUTS = ROOT / "data/outputs/aus_agent"
DOCSTORE_ROOT = ROOT / "data/built-indexes/climbmix-chunked/docstore"
VALIDATOR_PATH = ROOT / "src/systems/aus_agent_v2/coverage_contract.py"
FACT_RUN_ID = "v2l-dev30-facts"
BEST_RUN_ID = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
ANSWER_CITATION_RE = re.compile(r"\[shard_\d+_\d+(?:_p\d+)?\]")
PAGE_SUFFIX_RE = re.compile(r"_p\d+$")

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src/systems"))
sys.path.insert(0, str(ROOT / "tasks/search_serve/scripts"))

from systems.aus_agent_v2.coverage_contract import (  # noqa: E402
    _compact,
    _contains_exact_term,
    _material_anchor_term,
)
from docstore import FlatShardDocStore  # noqa: E402


def relative(path: Path) -> str:
    """Return a stable repository-relative artifact path."""
    return str(path.resolve().relative_to(ROOT))


def sha256_file(path: Path) -> str:
    """Hash a local input without loading large artifacts into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load one saved artifact and require its JSON object shape."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object in {path}")
    return value


def newest_fact_artifacts() -> dict[str, tuple[Path, dict[str, Any]]]:
    """Match the historical audit's newest-completed-per-topic selection."""
    newest: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    for path in FACT_OUTPUTS.glob("*.output.json"):
        try:
            obj = load_json(path)
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if obj.get("metadata", {}).get("run_id") != FACT_RUN_ID:
            continue
        if obj.get("trace", {}).get("status") != "completed":
            continue
        qid = str(obj["metadata"]["narrative_id"])
        stamp = path.name.split(".", 1)[0]
        old = newest.get(qid)
        if old is None or stamp > old[0]:
            newest[qid] = (stamp, path, obj)
    return {
        qid: (path, obj)
        for qid, (_stamp, path, obj) in sorted(newest.items())
    }


def first_cited_draft_step(obj: dict[str, Any]) -> int:
    """Locate the first cited prose draft before verifier-directed repair."""
    for index, step in enumerate(obj.get("trace", {}).get("steps", [])):
        output = step.get("output")
        text = output.get("text") if isinstance(output, dict) else None
        if (
            step.get("type") == "generation"
            and isinstance(text, str)
            and ANSWER_CITATION_RE.search(text)
        ):
            return index
    raise ValueError(
        f"no cited draft in {obj.get('metadata', {}).get('narrative_id')}"
    )


def best_v2_matrix() -> tuple[dict[str, Any], list[Path]]:
    """Describe all best-run commit calls before each first valid draft."""
    topics: list[dict[str, Any]] = []
    paths: list[Path] = []
    total_batches = 0
    total_selected = 0
    total_fact_cards = 0
    total_support_rows = 0
    for path in sorted(V2_OUTPUTS.glob("*.pre_repair_counterfactual.output.json")):
        obj = load_json(path)
        metadata = obj.get("metadata", {})
        if metadata.get("run_id") != BEST_RUN_ID:
            continue
        cutoff = first_cited_draft_step(obj)
        cited_parents = set(str(value) for value in obj.get("references", []))
        batches: list[dict[str, Any]] = []
        for step_index, step in enumerate(obj.get("trace", {}).get("steps", [])[:cutoff]):
            if not (
                step.get("type") == "tool_call"
                and step.get("tool_name") == "commit_context"
            ):
                continue
            arguments = step.get("arguments") or {}
            documents = arguments.get("documents", [])
            if not isinstance(documents, list):
                documents = []
            selected: list[dict[str, Any]] = []
            for document in documents:
                if not isinstance(document, dict):
                    continue
                unit_id = str(document.get("id") or "")
                facts = document.get("facts", [])
                supports = document.get("supports", [])
                fact_count = len(facts) if isinstance(facts, list) else 0
                support_count = len(supports) if isinstance(supports, list) else 0
                total_fact_cards += fact_count
                total_support_rows += support_count
                selected.append({
                    "id": unit_id,
                    "reason": document.get("reason"),
                    "fact_cards": fact_count,
                    "support_rows": support_count,
                    "parent_cited_in_counterfactual_answer": bool(
                        PAGE_SUFFIX_RE.sub("", unit_id) in cited_parents
                    ),
                })
            batches.append({
                "trace_step": step_index,
                "trace_turn": step.get("turn"),
                "selected_count": len(selected),
                "selected": selected,
            })
        total_batches += len(batches)
        total_selected += sum(batch["selected_count"] for batch in batches)
        paths.append(path)
        topics.append({
            "qid": str(metadata["narrative_id"]),
            "narrative": metadata.get("narrative"),
            "artifact": relative(path),
            "artifact_sha256": sha256_file(path),
            "first_cited_draft_trace_step": cutoff,
            "commit_batches": len(batches),
            "selected_units": sum(batch["selected_count"] for batch in batches),
            "batches": batches,
        })
    if len(topics) != 30:
        raise RuntimeError(f"expected 30 best-v2 artifacts, found {len(topics)}")
    return ({
        "run_id": BEST_RUN_ID,
        "interpretation": (
            "Direct exposure matrix only: these traces predate supports, so "
            "they cannot supply an observed support-validation failure rate."
        ),
        "aggregate": {
            "topics": len(topics),
            "pre_draft_commit_batches": total_batches,
            "selected_units": total_selected,
            "fact_cards": total_fact_cards,
            "support_rows": total_support_rows,
        },
        "topics": topics,
    }, paths)


def fact_batches(
    artifacts: dict[str, tuple[Path, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract every historical fact card and its commit-batch identity."""
    batches: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for qid, (path, obj) in artifacts.items():
        for step_index, step in enumerate(obj.get("trace", {}).get("steps", [])):
            if not (
                step.get("type") == "tool_call"
                and step.get("tool_name") == "commit_context"
            ):
                continue
            arguments = step.get("arguments") or {}
            documents = arguments.get("documents", [])
            if not isinstance(documents, list):
                documents = []
            rows: list[dict[str, Any]] = []
            for document_index, document in enumerate(documents, 1):
                if not isinstance(document, dict):
                    continue
                unit_id = str(document.get("id") or "")
                raw_facts = document.get("facts", [])
                if not isinstance(raw_facts, list):
                    raw_facts = []
                for fact_index, fact in enumerate(raw_facts, 1):
                    if not isinstance(fact, dict):
                        continue
                    source_ids.add(unit_id)
                    rows.append({
                        "document_index": document_index,
                        "fact_index": fact_index,
                        "document_id": unit_id,
                        "commit_reason": document.get("reason"),
                        "fact": fact,
                    })
            batches.append({
                "batch_index": len(batches) + 1,
                "qid": qid,
                "artifact": relative(path),
                "trace_step": step_index,
                "trace_turn": step.get("turn"),
                "selected_documents": len([
                    value for value in documents if isinstance(value, dict)
                ]),
                "rows": rows,
            })
    return batches, sorted(source_ids)


def load_source_texts(source_ids: list[str]) -> dict[str, str]:
    """Read exact local chunk units sequentially to stay under RLIMIT_NOFILE."""
    store = FlatShardDocStore(DOCSTORE_ROOT, lru_size=64)
    texts: dict[str, str] = {}
    try:
        for unit_id in source_ids:
            texts[unit_id] = store.get_text(unit_id)
    finally:
        store.close()
    return texts


def classify_fact(row: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Apply the term-related validator path to one mapped historical card."""
    fact = row["fact"]
    claim = _compact(fact.get("claim"), 500)
    value_scope = _compact(fact.get("scope"), 300)
    raw_value = fact.get("value")
    normalized_term = _compact(raw_value, 80)
    full_compacted_value = _compact(raw_value, 600)

    malformed = not claim or not isinstance(raw_value, str) or not full_compacted_value
    material = _material_anchor_term(normalized_term)
    in_claim_scope = (
        _contains_exact_term(f"{claim} {value_scope}", normalized_term)
        if material else False
    )
    in_source = (
        _contains_exact_term(source_text.casefold(), normalized_term)
        if material else False
    )
    if malformed:
        outcome = "malformed"
    elif not material:
        outcome = "checker_generic"
    elif not in_claim_scope:
        outcome = "out_of_claim_scope"
    elif not in_source:
        outcome = "source_missing"
    else:
        outcome = "valid"

    return {
        **row,
        "mapping": {
            "claim": claim,
            "value_scope": value_scope,
            "must_include": [raw_value],
        },
        "normalized_must_include": normalized_term,
        "flags": {
            "malformed": malformed,
            "material_by_current_checker": material,
            "exact_in_claim_or_scope": in_claim_scope,
            "exact_in_source": in_source,
            "raw_value_exceeds_80_chars": len(full_compacted_value) > 80,
        },
        "outcome": outcome,
    }


def replay_fact_proxy() -> tuple[dict[str, Any], list[Path]]:
    """Build the complete 83-batch counterfactual validation matrix."""
    artifacts = newest_fact_artifacts()
    if len(artifacts) != 30:
        raise RuntimeError(f"expected 30 fact-arm artifacts, found {len(artifacts)}")
    batches, source_ids = fact_batches(artifacts)
    texts = load_source_texts(source_ids)

    aggregate: collections.Counter[str] = collections.Counter()
    topic_counters: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    completed_batches: list[dict[str, Any]] = []
    for batch in batches:
        classified = [
            classify_fact(row, texts.get(row["document_id"], ""))
            for row in batch.pop("rows")
        ]
        outcomes = collections.Counter(row["outcome"] for row in classified)
        for outcome, count in outcomes.items():
            aggregate[outcome] += count
            topic_counters[batch["qid"]][outcome] += count
        long_values = sum(
            row["flags"]["raw_value_exceeds_80_chars"] for row in classified
        )
        aggregate["raw_value_exceeds_80_chars"] += long_values
        topic_counters[batch["qid"]]["raw_value_exceeds_80_chars"] += long_values
        invalid_rows = sum(row["outcome"] != "valid" for row in classified)
        completed_batches.append({
            **batch,
            "fact_rows": len(classified),
            "outcome_counts": dict(sorted(outcomes.items())),
            "invalid_rows": invalid_rows,
            "counterfactual_batch_result": (
                "expire" if invalid_rows else "commit"
            ),
            "rows": classified,
        })

    topic_matrix: list[dict[str, Any]] = []
    for qid, (path, obj) in artifacts.items():
        topic_batches = [batch for batch in completed_batches if batch["qid"] == qid]
        topic_matrix.append({
            "qid": qid,
            "narrative": obj.get("metadata", {}).get("narrative"),
            "artifact": relative(path),
            "artifact_sha256": sha256_file(path),
            "commit_batches": len(topic_batches),
            "fact_rows": sum(batch["fact_rows"] for batch in topic_batches),
            "expired_batches": sum(
                batch["counterfactual_batch_result"] == "expire"
                for batch in topic_batches
            ),
            "outcomes": dict(sorted(topic_counters[qid].items())),
        })

    if len(completed_batches) != 83:
        raise RuntimeError(
            f"expected 83 fact-arm commit batches, found {len(completed_batches)}"
        )
    if sum(batch["fact_rows"] for batch in completed_batches) != 1223:
        raise RuntimeError("expected 1,223 fact rows")

    invalid_batches = sum(
        batch["counterfactual_batch_result"] == "expire"
        for batch in completed_batches
    )
    empty_batches = sum(batch["fact_rows"] == 0 for batch in completed_batches)
    source_units = {
        unit_id: {
            "characters": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        for unit_id, text in sorted(texts.items())
    }
    paths = [path for path, _obj in artifacts.values()]
    return ({
        "run_id": FACT_RUN_ID,
        "interpretation": (
            "Closest saved annotation-behavior proxy, not a direct forecast. "
            "The old fact schema did not require value to occur verbatim in "
            "claim/scope; the new support prompt does."
        ),
        "replay_mapping": {
            "claim": "fact.claim",
            "value_scope": "fact.scope or empty string",
            "must_include": "single-element array [fact.value]",
            "requirement_id_and_route_validation": "not replayed: absent historically",
            "term_normalization": "whitespace-collapse then first 80 characters",
            "batch_policy": (
                "any invalid mapped row expires the entire staged batch, "
                "matching the current agent exception path"
            ),
        },
        "aggregate": {
            "topics": len(artifacts),
            "commit_batches": len(completed_batches),
            "fact_rows": sum(batch["fact_rows"] for batch in completed_batches),
            "unique_source_units": len(source_units),
            "invalid_batches": invalid_batches,
            "committing_batches": len(completed_batches) - invalid_batches,
            "empty_fact_batches": empty_batches,
            "outcomes": dict(sorted(aggregate.items())),
        },
        "input_artifacts": [relative(path) for path in paths],
        "topic_matrix": topic_matrix,
        "batch_matrix": completed_batches,
        "source_units": source_units,
    }, paths)


def build_report() -> dict[str, Any]:
    """Assemble provenance, direct exposure, and proxy replay sections."""
    best, best_paths = best_v2_matrix()
    proxy, proxy_paths = replay_fact_proxy()
    manifest_path = DOCSTORE_ROOT / "manifest.json"
    return {
        "schema_version": 1,
        "audit": "aus_agent_v2 commit supports validator offline replay",
        "network_or_api_calls": 0,
        "bedrock_cost_usd": 0,
        "provenance": {
            "script": relative(SCRIPT_PATH),
            "script_sha256": sha256_file(SCRIPT_PATH),
            "validator_source": relative(VALIDATOR_PATH),
            "validator_source_sha256": sha256_file(VALIDATOR_PATH),
            "docstore": relative(DOCSTORE_ROOT),
            "docstore_manifest": relative(manifest_path),
            "docstore_manifest_sha256": sha256_file(manifest_path),
            "best_v2_input_artifacts": [relative(path) for path in best_paths],
            "fact_proxy_input_artifacts": [relative(path) for path in proxy_paths],
        },
        "limitations": [
            "The best v2 traces contain no supports rows, so no direct failure rate exists.",
            "The fact-card mapping is counterfactual and deliberately lexical.",
            "Historical artifacts lack requirement ids, so route validation is excluded.",
            "A new prompt that explicitly requests verbatim overlap may perform better.",
        ],
        "best_v2_direct_exposure": best,
        "fact_card_proxy_replay": proxy,
    }


def main() -> None:
    """Write the deterministic JSON report and print a concise run summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=SCRIPT_PATH.with_suffix(".json"),
        help="JSON report path (default: matching .json beside this script)",
    )
    args = parser.parse_args()
    report = build_report()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    best = report["best_v2_direct_exposure"]["aggregate"]
    proxy = report["fact_card_proxy_replay"]["aggregate"]
    print(f"wrote {relative(output)}")
    print(f"best_v2={best}")
    print(f"fact_proxy={proxy}")


if __name__ == "__main__":
    main()
