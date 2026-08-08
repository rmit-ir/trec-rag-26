#!/usr/bin/env python3
"""Offline semantic-closure audit for the typed aus_agent_v2 contract.

The current validator deliberately proves routing, exact literals, source
presence, counts of tagged items, and a few request-authorized forms; it does
not compare an answer item's meaning with the requirement it claims to close.
This audit quantifies that boundary against the frozen promoted 30-topic run.

It performs two complementary measurements:

* Every frozen planner/scout assertion is replayed in isolation with generic
  prose.  Research rows receive a valid but requirement-unrelated source anchor;
  structural rows receive no evidence.  This is an exact execution of the
  current deterministic validator, not a lexical approximation.
* Simple requirement-token and one-dedicated-item gates are calibrated against
  reward criteria that all three frozen Sol judge repeats marked ``satisfied``.
  A smaller plan-row cohort additionally requires a criterion to have at least
  0.5 token recall in one frozen planner/scout row.  These are conservative
  positive cohorts for estimating rejection of legitimate baseline prose.

Run from the repository root::

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src/systems:src \
      uv run --group aus-agent-v2 python \
      worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.py \
      --output \
      worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.json

The script never imports a provider, grader, retrieval client, or network
client.  It reads only committed source and frozen local JSON/JSONL artifacts.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import statistics
import subprocess
import sys
import types
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from aus_agent_v2.answer_form import infer_answer_form_policy


SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[2]
EXPECTED_HEAD = "5972ac3b76b5391cfb28d0cc5c1d9b8f64419bd2"
RUN_ID = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
OUTPUT_DIR = ROOT / "data/outputs/aus_agent_v2"
RESULT_LEDGER = ROOT / "docs/auto-optimize/rubric-results.jsonl"
RUBRICS = ROOT / "data/task-comparison/dev-rubrics-fixed.jsonl"
VERDICT_ROOT = ROOT / "data/task-comparison/rubric-eval/gpt-5.6-sol"
PRIOR_MATRIX = (
    ROOT / "worklogs/assets/"
    "2026-08-06-aus-agent-v2-criterion-union-reachability.json"
)
SOURCE_FILES = (
    ROOT / "src/systems/aus_agent_v2/coverage_contract.py",
    ROOT / "src/systems/aus_agent_v2/atomic_plan.py",
    ROOT / "src/systems/aus_agent_v2/answer_form.py",
)

TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[+.#/-][A-Za-z0-9]+)*")
PAREN_RE = re.compile(r"\([^()]*\)")
STOP = {
    "a", "about", "all", "an", "and", "any", "are", "as", "at", "be",
    "been", "being", "by", "contains", "create", "creates", "discuss",
    "discusses", "each", "either", "explain", "explains", "explicitly",
    "for", "from", "give", "gives", "identify", "identifies", "in",
    "include", "includes", "into", "is", "its", "mention", "mentions",
    "of", "on", "one", "only", "or", "present", "presents", "provide",
    "provides", "response", "show", "shows", "state", "states", "that",
    "the", "their", "this", "through", "to", "two", "three", "four",
    "use", "uses", "was", "were", "when", "while", "with",
}
GATE_THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)
UNRELATED_CLAIM = "Unrelated closure evidence"


def rows(path: Path) -> list[dict[str, Any]]:
    """Load non-empty JSONL rows."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def rel(path: Path) -> str:
    """Return a repository-relative path, or an absolute external output path."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def sha256(path: Path) -> str:
    """Hash one exact local input."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_head() -> str:
    """Return the exact implementation commit under audit."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def git_bytes(commit: str, path: str) -> bytes:
    """Read one committed file from the local Git object database."""
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"], cwd=ROOT
    )


def load_reviewed_contract_module() -> types.ModuleType:
    """Execute the exact committed validator despite concurrent tree edits."""
    source_path = "src/systems/aus_agent_v2/coverage_contract.py"
    source = git_bytes(EXPECTED_HEAD, source_path).decode("utf-8")
    name = "aus_agent_v2._semantic_closure_reviewed_coverage_contract"
    module = types.ModuleType(name)
    module.__file__ = f"git:{EXPECTED_HEAD}:{source_path}"
    module.__package__ = "aus_agent_v2"
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


REVIEWED_CONTRACT = load_reviewed_contract_module()
ContractItem = REVIEWED_CONTRACT.ContractItem
EvidenceLedger = REVIEWED_CONTRACT.EvidenceLedger
build_coverage_contract = REVIEWED_CONTRACT.build_coverage_contract
normalize_commit_supports = REVIEWED_CONTRACT.normalize_commit_supports
validate_submission = REVIEWED_CONTRACT.validate_submission
validate_support_routes = REVIEWED_CONTRACT.validate_support_routes


def strip_parentheticals(text: str) -> str:
    """Remove rubric examples using the earlier reachability convention."""
    old = None
    while old != text:
        old = text
        text = PAREN_RE.sub(" ", text)
    return " ".join(text.split())


def tokens(text: str, *, strip_examples: bool = False) -> set[str]:
    """Return deterministic content tokens for diagnostic lexical gates."""
    if strip_examples:
        text = strip_parentheticals(text)
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.casefold() not in STOP
    }


def recall(needle: set[str], haystack: set[str]) -> float:
    """Return content-token recall from ``needle`` in ``haystack``."""
    return len(needle & haystack) / len(needle) if needle else 0.0


def output_artifacts() -> dict[str, tuple[Path, dict[str, Any]]]:
    """Load exactly the frozen promoted output for every development topic."""
    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(OUTPUT_DIR.glob("*.output.json")):
        try:
            obj = load_json(path)
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if obj.get("metadata", {}).get("run_id") != RUN_ID:
            continue
        qid = str(obj.get("metadata", {}).get("narrative_id") or "")
        if not qid:
            raise RuntimeError(f"missing narrative id: {path}")
        if qid in selected:
            raise RuntimeError(f"duplicate frozen output for {qid}")
        if obj.get("trace", {}).get("status") != "completed":
            raise RuntimeError(f"incomplete frozen output: {path}")
        selected[qid] = (path, obj)
    if len(selected) != 30:
        raise RuntimeError(f"expected 30 frozen outputs, found {len(selected)}")
    return selected


def rubric_rows() -> dict[str, dict[str, Any]]:
    """Load the exact fixed development rubrics."""
    selected = {str(row["qid"]): row for row in rows(RUBRICS)}
    if len(selected) != 30:
        raise RuntimeError(f"expected 30 fixed rubrics, found {len(selected)}")
    return selected


def verdict_variant() -> str:
    """Resolve the frozen promoted run's exact judge-cache variant."""
    selected = [
        row for row in rows(RESULT_LEDGER)
        if row.get("run_id") == RUN_ID
        and row.get("topics") == 30
        and row.get("judge") == "gpt-5.6-sol"
    ]
    if not selected:
        raise RuntimeError(f"missing 30-topic result ledger row for {RUN_ID}")
    return str(selected[-1]["variant"])


def verdict_paths(variant: str, qid: str) -> list[Path]:
    """Return three frozen repeat paths in judge order."""
    return [
        VERDICT_ROOT / variant / f"{qid}.json",
        VERDICT_ROOT / variant / f"{qid}.r1.json",
        VERDICT_ROOT / variant / f"{qid}.r2.json",
    ]


def verdict_matrix(
    variant: str,
    rubrics: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[list[str]]], list[Path]]:
    """Load raw three-repeat verdict matrices for the promoted run."""
    matrix: dict[str, list[list[str]]] = {}
    paths_seen: list[Path] = []
    for qid, rubric in sorted(rubrics.items()):
        criteria = [item for item in rubric["criteria"] if not item["waived"]]
        repeats: list[list[str]] = []
        for path in verdict_paths(variant, qid):
            obj = load_json(path)
            verdicts = obj.get("verdicts")
            if obj.get("status") != "completed" or not isinstance(verdicts, list):
                raise RuntimeError(f"incomplete verdict cache: {path}")
            if len(verdicts) != len(criteria):
                raise RuntimeError(f"criterion count mismatch: {path}")
            repeats.append([str(value) for value in verdicts])
            paths_seen.append(path)
        matrix[qid] = [
            [repeat[index] for repeat in repeats]
            for index in range(len(criteria))
        ]
    return matrix, paths_seen


def contract_for_output(obj: dict[str, Any]) -> list[ContractItem]:
    """Replay current contract compilation over one frozen plan/scout handoff."""
    trace = obj.get("trace", {})
    trace_input = trace.get("input", {})
    if not isinstance(trace_input, dict):
        raise TypeError("frozen trace input is not an object")
    plan = str(
        trace_input.get("coverage_plan")
        or trace_input.get("coverage_plan_initial")
        or ""
    )
    if not plan:
        raise RuntimeError("frozen output has no coverage plan")
    critic = (
        trace_input.get("plan_critic")
        or trace.get("summary", {}).get("plan_critic")
        or {}
    )
    additions = critic.get("additions", []) if isinstance(critic, dict) else []
    query = str(obj.get("metadata", {}).get("narrative") or "")
    return build_coverage_contract(
        plan,
        list(additions) if isinstance(additions, list) else [],
        answer_form=infer_answer_form_policy(query),
    )


def serialized_row(item: ContractItem) -> dict[str, Any]:
    """Serialize a row without losing tuple-valued exact gates."""
    record = asdict(item)
    record["must_mention"] = list(item.must_mention)
    record["must_avoid"] = list(item.must_avoid)
    record["match_text"] = (
        item.requirement + " " + " ".join(item.must_mention)
    ).strip()
    record["content_tokens"] = sorted(tokens(record["match_text"]))
    return record


def generic_false_closure(item: ContractItem) -> dict[str, Any]:
    """Replay one row using generic or requirement-unrelated tagged prose."""
    ledger = EvidenceLedger()
    committed: set[str] = set()
    anchor_errors: list[str] = []
    route_errors: list[str] = []
    base = "Generic tagged prose"
    if item.must_research:
        document_id = f"unrelated-{item.id.casefold()}"
        arguments = {"documents": [{
            "id": document_id,
            "supports": [{
                "requirement_id": item.id,
                "claim": UNRELATED_CLAIM,
                "value_scope": "",
                "must_include": [UNRELATED_CLAIM],
            }],
        }]}
        supports, anchor_errors = normalize_commit_supports(arguments, [item])
        route_errors = validate_support_routes(
            supports,
            [{"id": document_id, "text": UNRELATED_CLAIM + "."}],
        )
        ledger.record_supports(supports)
        committed.add(document_id)
        base = UNRELATED_CLAIM
    if item.must_mention:
        base += ". Required literals: " + "; ".join(item.must_mention)
    base += "."
    count = max(1, item.minimum_count)
    answer_items = [{
        "kind": "prose",
        "text": base,
        "evidence_ids": list(committed),
        "satisfies": [item.id],
    } for _ in range(count)]
    answer, errors, stats = validate_submission(
        {"answer_items": answer_items, "unresolved": []},
        [item],
        ledger,
        committed,
    )
    return {
        "accepted": answer is not None,
        "errors": errors,
        "anchor_normalization_errors": anchor_errors,
        "support_route_errors": route_errors,
        "submitted_text": base,
        "submitted_identical_items": count,
        "stats": stats,
        "contains_requirement_content_token": bool(
            tokens(item.requirement) & tokens(base)
        ),
        "requirement_token_recall": recall(
            tokens(item.requirement), tokens(base)
        ),
    }


def lexical_echo_false_closure(item: ContractItem) -> dict[str, Any]:
    """Show that parroting the requirement defeats any overlap-only gate."""
    ledger = EvidenceLedger()
    committed: set[str] = set()
    text = "Requirement acknowledged: " + item.requirement
    if item.must_research:
        document_id = f"unrelated-echo-{item.id.casefold()}"
        supports, support_errors = normalize_commit_supports({
            "documents": [{
                "id": document_id,
                "supports": [{
                    "requirement_id": item.id,
                    "claim": UNRELATED_CLAIM,
                    "value_scope": "",
                    "must_include": [UNRELATED_CLAIM],
                }],
            }],
        }, [item])
        if support_errors:
            return {"accepted": False, "errors": support_errors}
        route_errors = validate_support_routes(
            supports,
            [{"id": document_id, "text": UNRELATED_CLAIM + "."}],
        )
        if route_errors:
            return {"accepted": False, "errors": route_errors}
        ledger.record_supports(supports)
        committed.add(document_id)
        text += ". " + UNRELATED_CLAIM
    if item.must_mention:
        text += ". Required literals: " + "; ".join(item.must_mention)
    text += "."
    answer, errors, _ = validate_submission(
        {"answer_items": [{
            "kind": "prose",
            "text": text,
            "evidence_ids": list(committed),
            "satisfies": [item.id],
        }], "unresolved": []},
        [item], ledger, committed,
    )
    return {
        "accepted": answer is not None,
        "errors": errors,
        "requirement_token_recall": recall(
            tokens(item.requirement), tokens(text)
        ),
    }


def maximum_distinct_assignment(edges: dict[int, list[int]]) -> int:
    """Return maximum rows assignable to different baseline answer items."""
    item_owner: dict[int, int] = {}

    def augment(row: int, seen: set[int]) -> bool:
        for answer_item in edges[row]:
            if answer_item in seen:
                continue
            seen.add(answer_item)
            if (
                answer_item not in item_owner
                or augment(item_owner[answer_item], seen)
            ):
                item_owner[answer_item] = row
                return True
        return False

    return sum(augment(row, set()) for row in edges)


def gate_stats(
    records_by_qid: dict[str, list[dict[str, Any]]],
    answer_tokens: dict[str, list[set[str]]],
) -> dict[str, Any]:
    """Measure response-wide, one-item, and distinct-item lexical gates."""
    aggregate: dict[str, Any] = {}
    per_topic: dict[str, dict[str, Any]] = {}
    for threshold in GATE_THRESHOLDS:
        total = 0
        whole_pass = 0
        any_item_pass = 0
        distinct_assigned = 0
        topic_values: dict[str, Any] = {}
        for qid, records in sorted(records_by_qid.items()):
            items = answer_tokens[qid]
            whole = set().union(*items) if items else set()
            edges: dict[int, list[int]] = {}
            topic_whole = 0
            topic_any = 0
            for index, record in enumerate(records):
                required = set(record["gate_tokens"])
                item_recalls = [recall(required, value) for value in items]
                record["gate_recalls"][str(threshold)] = {
                    "whole_answer_pass": recall(required, whole) >= threshold,
                    "one_item_pass": max(item_recalls, default=0.0) >= threshold,
                }
                topic_whole += recall(required, whole) >= threshold
                edges[index] = [
                    item_index
                    for item_index, value in enumerate(item_recalls)
                    if value >= threshold
                ]
                topic_any += bool(edges[index])
            matched = maximum_distinct_assignment(edges)
            count = len(records)
            total += count
            whole_pass += topic_whole
            any_item_pass += topic_any
            distinct_assigned += matched
            topic_values[qid] = {
                "records": count,
                "whole_answer_pass": topic_whole,
                "one_item_pass": topic_any,
                "distinct_item_assignment": matched,
            }
        key = str(threshold)
        aggregate[key] = {
            "cohort": total,
            "whole_answer_pass": whole_pass,
            "whole_answer_rejected": total - whole_pass,
            "whole_answer_rejection_rate": (
                (total - whole_pass) / total if total else 0.0),
            "one_item_pass": any_item_pass,
            "one_item_rejected": total - any_item_pass,
            "one_item_rejection_rate": (
                (total - any_item_pass) / total if total else 0.0),
            "distinct_item_assignment": distinct_assigned,
            "distinct_item_rejected": total - distinct_assigned,
            "distinct_item_rejection_rate": (
                (total - distinct_assigned) / total if total else 0.0),
            "additional_rejections_from_uniqueness": (
                any_item_pass - distinct_assigned),
        }
        per_topic[key] = topic_values
    return {"aggregate": aggregate, "per_topic": per_topic}


def top_answer_items(
    required: set[str],
    obj: dict[str, Any],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return lexical locators for reproducible gate inspection."""
    candidates = []
    for index, item in enumerate(obj.get("answer", [])):
        text = str(item.get("text") or "")
        value = tokens(text)
        candidates.append({
            "answer_item_index": index,
            "text": text,
            "citations": item.get("citations", []),
            "requirement_token_recall": recall(required, value),
            "matched_tokens": sorted(required & value),
        })
    candidates.sort(key=lambda value: (
        -value["requirement_token_recall"], value["answer_item_index"]
    ))
    return candidates[:limit]


def synthetic_count_replay() -> dict[str, Any]:
    """Prove that MIN counts array positions, not distinct semantic content."""
    item = ContractItem(
        id="P01",
        origin="planner",
        kind="example",
        requirement="Provide three distinct worked examples",
        must_research=False,
        must_answer=True,
        minimum_count=3,
    )
    repeated = {
        "kind": "prose",
        "text": "Generic tagged prose.",
        "evidence_ids": [],
        "satisfies": ["P01"],
    }
    arguments = {"answer_items": [repeated, repeated, repeated], "unresolved": []}
    answer, errors, stats = validate_submission(
        arguments, [item], EvidenceLedger(), set()
    )
    return {
        "item": serialized_row(item),
        "arguments": arguments,
        "accepted": answer is not None,
        "errors": errors,
        "stats": stats,
        "interpretation": (
            "Three byte-for-byte identical array elements satisfy MIN=3; "
            "the validator does not establish distinct examples."
        ),
    }


def counter(values: Iterable[Any]) -> dict[str, int]:
    """Serialize a frequency distribution with stable string keys."""
    return dict(sorted(collections.Counter(str(value) for value in values).items()))


def build_report() -> dict[str, Any]:
    """Build the complete replay and conservative baseline gate audit."""
    head = current_head()
    if head != EXPECTED_HEAD:
        raise RuntimeError(f"expected HEAD {EXPECTED_HEAD}, found {head}")

    artifacts = output_artifacts()
    rubrics = rubric_rows()
    if set(artifacts) != set(rubrics):
        raise RuntimeError("frozen output and rubric topic sets differ")
    variant = verdict_variant()
    verdicts, raw_verdict_paths = verdict_matrix(variant, rubrics)
    prior = load_json(PRIOR_MATRIX)
    prior_topics = {str(topic["qid"]): topic for topic in prior["topics"]}

    answer_tokens: dict[str, list[set[str]]] = {}
    criterion_cohort: dict[str, list[dict[str, Any]]] = {}
    aligned_rows: dict[str, dict[str, dict[str, Any]]] = {}
    topic_records: list[dict[str, Any]] = []
    all_row_records: list[dict[str, Any]] = []

    for qid, (path, obj) in sorted(artifacts.items()):
        items = contract_for_output(obj)
        rows_by_id = {item.id: item for item in items}
        answer_items = [
            item for item in obj.get("answer", []) if isinstance(item, dict)
        ]
        answer_tokens[qid] = [
            tokens(str(item.get("text") or "")) for item in answer_items
        ]

        row_records: list[dict[str, Any]] = []
        for item in items:
            record = serialized_row(item)
            record["qid"] = qid
            if (
                item.origin in {"planner", "scout"}
                and item.mode == "assert"
                and item.must_answer
            ):
                generic = generic_false_closure(item)
                echo = lexical_echo_false_closure(item)
                record["generic_false_closure"] = generic
                record["lexical_echo_false_closure"] = echo
            else:
                record["generic_false_closure"] = None
                record["lexical_echo_false_closure"] = None
            row_records.append(record)
            all_row_records.append(record)

        criteria = [
            item for item in rubrics[qid]["criteria"] if not item["waived"]
        ]
        prior_criteria = prior_topics[qid]["criteria"]
        if len(criteria) != len(prior_criteria):
            raise RuntimeError(f"prior matrix criterion mismatch for {qid}")
        cohort_records: list[dict[str, Any]] = []
        for index, criterion in enumerate(criteria):
            repeats = verdicts[qid][index]
            prior_repeats = prior_criteria[index]["raw_verdict_matrix"]["P"][
                "repeat_verdicts"
            ]
            if repeats != prior_repeats:
                raise RuntimeError(f"prior matrix verdict mismatch: {qid}/{index}")
            if float(criterion["signed_weight"]) <= 0:
                continue
            if repeats != ["satisfied", "satisfied", "satisfied"]:
                continue
            core_text = strip_parentheticals(str(criterion["text"]))
            required = tokens(core_text)
            whole = set().union(*answer_tokens[qid]) if answer_tokens[qid] else set()
            item_recalls = [
                recall(required, value) for value in answer_tokens[qid]
            ]
            match = prior_criteria[index]["current_contract_match"]
            record = {
                "qid": qid,
                "criterion_index": index,
                "cid": criterion["cid"],
                "text": criterion["text"],
                "core_text": core_text,
                "axis": criterion["axis"],
                "signed_weight": criterion["signed_weight"],
                "repeat_verdicts": repeats,
                "gate_tokens": sorted(required),
                "whole_answer_token_recall": recall(required, whole),
                "best_item_token_recall": max(item_recalls, default=0.0),
                "top_answer_items": top_answer_items(required, obj),
                "gate_recalls": {},
                "current_contract_single_row_max_recall": match[
                    "single_row_max_recall"
                ],
                "current_contract_top_row": (
                    match["top_row_matches"][0]
                    if match["top_row_matches"] else None
                ),
            }
            cohort_records.append(record)

            if (
                match["single_row_max_recall"] >= 0.5
                and match["top_row_matches"]
            ):
                row_id = str(match["top_row_matches"][0]["id"])
                item = rows_by_id.get(row_id)
                if (
                    item is not None
                    and item.origin in {"planner", "scout"}
                    and item.must_answer
                ):
                    current = aligned_rows.setdefault(qid, {}).setdefault(
                        row_id,
                        {
                            "qid": qid,
                            "row_id": row_id,
                            "origin": item.origin,
                            "kind": item.kind,
                            "must_research": item.must_research,
                            "requirement": item.requirement,
                            "must_mention": list(item.must_mention),
                            "gate_tokens": sorted(tokens(
                                item.requirement + " "
                                + " ".join(item.must_mention)
                            )),
                            "aligned_criteria": [],
                            "gate_recalls": {},
                        },
                    )
                    current["aligned_criteria"].append({
                        "cid": criterion["cid"],
                        "text": criterion["text"],
                        "row_recall_of_criterion": match[
                            "single_row_max_recall"
                        ],
                        "repeat_verdicts": repeats,
                    })
        criterion_cohort[qid] = cohort_records

        topic_records.append({
            "qid": qid,
            "query": obj.get("metadata", {}).get("narrative"),
            "artifact": rel(path),
            "answer_items": answer_items,
            "contract_rows": row_records,
            "unanimously_satisfied_reward_criteria": cohort_records,
        })

    aligned_cohort = {
        qid: list(by_id.values()) for qid, by_id in sorted(aligned_rows.items())
    }
    for qid, records in aligned_cohort.items():
        obj = artifacts[qid][1]
        for record in records:
            required = set(record["gate_tokens"])
            whole = set().union(*answer_tokens[qid]) if answer_tokens[qid] else set()
            record["whole_answer_token_recall"] = recall(required, whole)
            record["best_item_token_recall"] = max(
                (recall(required, value) for value in answer_tokens[qid]),
                default=0.0,
            )
            record["top_answer_items"] = top_answer_items(required, obj)

    criterion_gates = gate_stats(criterion_cohort, answer_tokens)
    aligned_row_gates = gate_stats(aligned_cohort, answer_tokens)

    susceptible = [
        row for row in all_row_records
        if row["generic_false_closure"] is not None
    ]
    accepted_generic = [
        row for row in susceptible
        if row["generic_false_closure"]["accepted"]
    ]
    accepted_echo = [
        row for row in susceptible
        if row["lexical_echo_false_closure"]["accepted"]
    ]
    no_literal = [row for row in susceptible if not row["must_mention"]]
    literal = [row for row in susceptible if row["must_mention"]]
    structural = [row for row in susceptible if not row["must_research"]]
    research = [row for row in susceptible if row["must_research"]]
    no_requirement_token = [
        row for row in susceptible
        if not row["generic_false_closure"][
            "contains_requirement_content_token"
        ]
    ]

    row_counts_by_topic = collections.Counter()
    for row in susceptible:
        row_counts_by_topic[row["qid"]] += 1
    criterion_total = sum(map(len, criterion_cohort.values()))
    aligned_total = sum(map(len, aligned_cohort.values()))
    all_plan_scout = [
        row for row in all_row_records if row["origin"] in {"planner", "scout"}
    ]
    planner_asserts = [
        row for row in susceptible if row["origin"] == "planner"
    ]
    scout_asserts = [
        row for row in susceptible if row["origin"] == "scout"
    ]

    source_paths: set[Path] = set()
    source_paths.update(path for path, _ in artifacts.values())
    source_paths.update(raw_verdict_paths)
    source_paths.update({RESULT_LEDGER, RUBRICS, PRIOR_MATRIX, SCRIPT})

    return {
        "schema_version": "aus-agent-v2-semantic-closure-risk-v1",
        "analysis_commit": head,
        "scope": {
            "run_id": RUN_ID,
            "topics": len(artifacts),
            "judge": "gpt-5.6-sol",
            "judge_variant": variant,
            "repeat_count": 3,
            "network_calls": 0,
            "provider_calls": 0,
            "paid_calls": 0,
            "incremental_cost_usd": 0.0,
            "typed_planner_limit": "10-24 rows per current atomic_plan.py",
            "empirical_inventory_note": (
                "No frozen full-30 run exists for the newly transported typed "
                "planner. The exact validator replay therefore compiles the "
                "frozen full-30 planner/scout inventories through the current "
                "compatible contract builder; unanimous rubric criteria form "
                "a separate atomic proxy cohort."
            ),
        },
        "methodology": {
            "false_closure_replay": (
                "Each planner/scout assert row is the only contract row. A "
                "structural row receives generic tagged prose. A research row "
                "receives a normalized, source-present 'Unrelated closure "
                "evidence' anchor mapped to that row plus prose repeating only "
                "that anchor and any must_mention literals. Acceptance is the "
                "actual current validate_submission result."
            ),
            "lexical_echo_probe": (
                "The same isolated row is closed with prose that parrots the "
                "requirement, establishing 1.0 requirement-token recall while "
                "remaining an acknowledgement rather than an answer."
            ),
            "criterion_positive_cohort": (
                "Every unwaived positive-weight criterion whose three raw "
                "promoted-run verdicts are all satisfied. Parenthetical rubric "
                "examples are removed before tokenization."
            ),
            "aligned_plan_row_positive_cohort": (
                "A conservative subset of the criterion cohort: the earlier "
                "frozen matrix must locate at least half the criterion's "
                "content tokens in one current planner/scout row. Topic/row "
                "pairs are deduplicated."
            ),
            "whole_answer_gate": (
                "Requirement-token recall is measured against the union of "
                "all baseline answer-item tokens."
            ),
            "one_item_gate": (
                "At least one existing baseline answer item must independently "
                "meet the requirement-token recall threshold."
            ),
            "distinct_item_gate": (
                "Maximum bipartite matching assigns each positive requirement "
                "to a different existing baseline answer item at the threshold."
            ),
            "lexical_role": (
                "Lexical overlap is only a gate-risk diagnostic. Frozen Sol "
                "verdicts, not overlap, define the legitimate positive cohort."
            ),
        },
        "summary": {
            "inventory": {
                "all_planner_scout_rows": len(all_plan_scout),
                "assert_must_answer_rows_tested": len(susceptible),
                "planner_assert_rows": len(planner_asserts),
                "scout_assert_rows": len(scout_asserts),
                "structural_assert_rows": len(structural),
                "research_assert_rows": len(research),
                "assert_rows_without_must_mention": len(no_literal),
                "assert_rows_with_must_mention": len(literal),
                "nonanswer_budget_rows": sum(
                    row["kind"] == "budget" and not row["must_answer"]
                    for row in all_plan_scout
                ),
                "avoidance_rows": sum(
                    row["mode"] == "avoid" for row in all_plan_scout
                ),
                "assert_rows_per_topic_min": min(row_counts_by_topic.values()),
                "assert_rows_per_topic_median": statistics.median(
                    row_counts_by_topic.values()
                ),
                "assert_rows_per_topic_max": max(row_counts_by_topic.values()),
                "by_origin": counter(row["origin"] for row in all_plan_scout),
                "by_kind": counter(row["kind"] for row in all_plan_scout),
            },
            "exact_false_closure": {
                "generic_or_unrelated_accepted": len(accepted_generic),
                "generic_or_unrelated_acceptance_rate": (
                    len(accepted_generic) / len(susceptible)
                ),
                "accepted_without_any_requirement_content_token": len(
                    no_requirement_token
                ),
                "accepted_without_any_requirement_content_token_rate": (
                    len(no_requirement_token) / len(susceptible)
                ),
                "structural_accepted": sum(
                    row["generic_false_closure"]["accepted"]
                    for row in structural
                ),
                "research_with_unrelated_anchor_accepted": sum(
                    row["generic_false_closure"]["accepted"]
                    for row in research
                ),
                "planner_rows_accepted": sum(
                    row["generic_false_closure"]["accepted"]
                    for row in planner_asserts
                ),
                "scout_rows_accepted": sum(
                    row["generic_false_closure"]["accepted"]
                    for row in scout_asserts
                ),
                "lexical_requirement_echo_accepted": len(accepted_echo),
                "lexical_requirement_echo_acceptance_rate": (
                    len(accepted_echo) / len(susceptible)
                ),
                "conclusion": (
                    "Routing, source presence, exact literals, and item counts "
                    "do not establish that prose semantically answers its "
                    "tagged requirement."
                ),
            },
            "rubric_grounded_atomic_proxy": {
                "unanimously_satisfied_positive_criteria": criterion_total,
                "topics": sum(bool(values) for values in criterion_cohort.values()),
                "gate_results": criterion_gates["aggregate"],
            },
            "rubric_aligned_plan_rows": {
                "deduplicated_rows": aligned_total,
                "topics": len(aligned_cohort),
                "planner_rows": sum(
                    row["origin"] == "planner"
                    for values in aligned_cohort.values() for row in values
                ),
                "scout_rows": sum(
                    row["origin"] == "scout"
                    for values in aligned_cohort.values() for row in values
                ),
                "structural_rows": sum(
                    not row["must_research"]
                    for values in aligned_cohort.values() for row in values
                ),
                "research_rows": sum(
                    row["must_research"]
                    for values in aligned_cohort.values() for row in values
                ),
                "gate_results": aligned_row_gates["aggregate"],
            },
            "small_gate_interpretation": {
                "at_0.10_atomic_proxy": criterion_gates["aggregate"]["0.1"],
                "at_0.20_atomic_proxy": criterion_gates["aggregate"]["0.2"],
                "at_0.10_aligned_rows": aligned_row_gates["aggregate"]["0.1"],
                "at_0.20_aligned_rows": aligned_row_gates["aggregate"]["0.2"],
                "conclusion": (
                    "Even low lexical/dedicated-item thresholds reject "
                    "judge-unanimous baseline content, while a model can defeat "
                    "overlap-only checks by parroting requirement text."
                ),
            },
            "architecture_implication": (
                "Do not promote requirement-text overlap or one-item-per-row "
                "to a hard semantic gate. Keep deterministic literals/forms/"
                "routing, but semantic closure needs an entailment-aware check "
                "or a writer-produced claim object whose relation to the "
                "requirement is evaluated; any such evaluator should be "
                "calibrated because lexical proxies have material false rejects."
            ),
        },
        "synthetic_replays": {
            "identical_items_satisfy_minimum_count": synthetic_count_replay(),
        },
        "gate_detail": {
            "criterion_positive_cohort": criterion_gates,
            "aligned_plan_row_positive_cohort": aligned_row_gates,
        },
        "topics": topic_records,
        "aligned_plan_row_records": aligned_cohort,
        "provenance": {
            "files": [
                {
                    "path": rel(path),
                    "sha256": hashlib.sha256(git_bytes(
                        EXPECTED_HEAD, rel(path)
                    )).hexdigest(),
                    "source": f"git:{EXPECTED_HEAD}",
                }
                for path in sorted(SOURCE_FILES)
            ] + [
                {"path": rel(path), "sha256": sha256(path)}
                for path in sorted(source_paths)
            ],
            "counts": {
                "source_files": len(SOURCE_FILES),
                "output_artifacts": len(artifacts),
                "verdict_cache_files": len(raw_verdict_paths),
                "rubric_files": 1,
                "prior_worklog_assets": 1,
            },
        },
        "limitations": [
            (
                "The exact closure replay proves validator susceptibility, not "
                "that the frozen model actually attempted adversarial closure."
            ),
            (
                "The current typed planner was committed after the frozen "
                "full-30 runs, so the empirical rows are compatible legacy "
                "planner/scout rows rather than observed typed-tool rows."
            ),
            (
                "Unanimous rubric satisfaction is a response-level positive; "
                "dedicated-item rejection can mean valid content is distributed "
                "across items, which is precisely the gate behavior measured."
            ),
            (
                "Lexical overlap does not establish either entailment or "
                "non-entailment and is never substituted for a frozen verdict."
            ),
        ],
    }


def print_summary(report: dict[str, Any]) -> None:
    """Print the compact operator-facing result captured by tee."""
    summary = report["summary"]
    inventory = summary["inventory"]
    closure = summary["exact_false_closure"]
    atomic = summary["rubric_grounded_atomic_proxy"]
    aligned = summary["rubric_aligned_plan_rows"]
    print(f"commit: {report['analysis_commit']}")
    print(f"topics: {report['scope']['topics']}")
    print(
        "planner/scout assert rows: "
        f"{inventory['assert_must_answer_rows_tested']} "
        f"(structural={inventory['structural_assert_rows']}, "
        f"research={inventory['research_assert_rows']})"
    )
    print(
        "generic/unrelated false closures accepted: "
        f"{closure['generic_or_unrelated_accepted']}/"
        f"{inventory['assert_must_answer_rows_tested']}"
    )
    print(
        "accepted with zero requirement content tokens: "
        f"{closure['accepted_without_any_requirement_content_token']}/"
        f"{inventory['assert_must_answer_rows_tested']}"
    )
    print(
        "requirement-echo closures accepted: "
        f"{closure['lexical_requirement_echo_accepted']}/"
        f"{inventory['assert_must_answer_rows_tested']}"
    )
    print(
        "unanimously satisfied reward criteria: "
        f"{atomic['unanimously_satisfied_positive_criteria']}"
    )
    for threshold in ("0.1", "0.2"):
        result = atomic["gate_results"][threshold]
        print(
            f"atomic proxy threshold {threshold}: "
            f"whole rejected={result['whole_answer_rejected']}, "
            f"one-item rejected={result['one_item_rejected']}, "
            f"distinct-item rejected={result['distinct_item_rejected']}"
        )
    print(f"rubric-aligned plan/scout rows: {aligned['deduplicated_rows']}")
    for threshold in ("0.1", "0.2"):
        result = aligned["gate_results"][threshold]
        print(
            f"aligned rows threshold {threshold}: "
            f"whole rejected={result['whole_answer_rejected']}, "
            f"one-item rejected={result['one_item_rejected']}, "
            f"distinct-item rejected={result['distinct_item_rejected']}"
        )
    counted = report["synthetic_replays"][
        "identical_items_satisfy_minimum_count"
    ]
    print(f"three identical items satisfy MIN=3: {counted['accepted']}")
    print("network/provider/paid calls: 0/0/0; incremental cost: $0.00")


def main() -> None:
    """Write the full JSON and print its compact audit summary."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT / "worklogs/assets/"
            "2026-08-06-aus-agent-v2-semantic-closure-risk.json"
        ),
    )
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(report)
    print(f"output: {rel(args.output)}")
    print(f"output bytes: {args.output.stat().st_size}")


if __name__ == "__main__":
    main()
