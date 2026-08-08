#!/usr/bin/env python3
"""Audit whether the frozen lean contract can carry the 0.8048 oracle union.

The audit is fully offline.  It joins:

* the four complete 30-topic candidate outputs used by the reported oracle;
* all three frozen Sol rubric-verdict repeats for every candidate/topic;
* every unwaived fixed rubric criterion; and
* the planner/blind-scout rows frozen in the promoted pre-repair run.

Criterion judgments remain authoritative.  Lexical matching is used only to
locate where a judged criterion appears in planner/scout rows and answer items;
it is never substituted for a rubric verdict.  The paired JSON records every
criterion, raw repeat verdict, candidate item locator, row match, and ceiling.

Run from the repository root at commit e89fbe98::

    PYTHONPATH=src/systems:src uv run --group aus-agent-v2 python \
      worklogs/assets/2026-08-06-aus-agent-v2-criterion-union-reachability.py \
      --output worklogs/assets/2026-08-06-aus-agent-v2-criterion-union-reachability.json

No provider, model, grader, retrieval service, or network client is imported.
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
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from aus_agent_v2.answer_form import infer_answer_form_policy
from aus_agent_v2.coverage_contract import ContractItem, build_coverage_contract


SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[2]
EXPECTED_HEAD = "e89fbe982ac9edf6ee2f30731e120102eff52388"
RESULTS = ROOT / "docs/auto-optimize/rubric-results.jsonl"
RUBRICS = ROOT / "data/task-comparison/dev-rubrics-fixed.jsonl"
CACHE = ROOT / "data/task-comparison/rubric-eval/gpt-5.6-sol"
OUTPUT_ROOTS = (
    ROOT / "data/outputs/aus_agent",
    ROOT / "data/outputs/aus_agent_v2",
)

RUNS = {
    "B": "v2-dev30-default",
    "P": "sol-aus-v2-research-first-pre-repair-dev30-20260806",
    "R": "sol-aus-v2-research-first-dev30-20260806",
    "A": "sol-aus-v2-adaptive-dev30-20260806",
}
PROMOTED = RUNS["P"]
VALUE = {
    "not_satisfied": 0.0,
    "partially_satisfied": 0.5,
    "satisfied": 1.0,
}
REPRESENTATION_THRESHOLDS = (0.4, 0.5, 0.6)

TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[+.#/-][A-Za-z0-9]+)*")
PAREN_RE = re.compile(r"\([^()]*\)")
STOP = {
    "a", "about", "all", "an", "and", "any", "are", "as", "at",
    "be", "been", "being", "by", "contains", "create", "creates",
    "discuss", "discusses", "each", "either", "explain", "explains",
    "explicitly", "for", "from", "give", "gives", "identify",
    "identifies", "in", "include", "includes", "into", "is", "its",
    "mention", "mentions", "of", "on", "one", "only", "or", "present",
    "presents", "provide", "provides", "response", "show", "shows",
    "state", "states", "that", "the", "their", "this", "through", "to",
    "two", "three", "four", "use", "uses", "was", "were", "when",
    "while", "with",
}
FORMAT_PATTERNS = {
    "table": re.compile(r"\b(?:table|tabular)\b", re.I),
    "subheading": re.compile(r"\b(?:subheadings?|headings?)\b", re.I),
    "labeled_sections": re.compile(
        r"\b(?:clearly\s+label(?:ed)?\s+sections?|"
        r"separate(?:\s+and)?\s+clearly\s+labeled\s+sections?)\b", re.I),
    "chart": re.compile(
        r"\b(?:line chart|bar chart|scalability curve)\b", re.I),
}
COUNT_RE = re.compile(
    r"\b(?:at least|at most|exactly|between|each|every|all|separate)\b|"
    r"\b\d+\s+(?:examples?|differences?|sections?|posts?|domains?|cases?|"
    r"features?|sources?|pilots?|brokers?|indexes?|categories?|steps?)\b",
    re.I,
)
LITERAL_RE = re.compile(
    r"(?:[$€£]?\b\d[\d,./%–—-]*\b)|"
    r"(?:\b[A-Z]{2,}(?:[-/][A-Z0-9]+)*\b)|"
    r"(?:\b[A-Z][a-z]+(?:[A-Z][A-Za-z]*)+\b)|"
    r"(?:\b[A-Z](?:[-&][A-Za-z]+)+\b)"
)


def rel(path: Path) -> str:
    """Return a stable repository-relative path."""
    return str(path.resolve().relative_to(ROOT))


def sha256(path: Path) -> str:
    """Hash one exact local input."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_json(path: Path) -> dict[str, Any]:
    """Load one saved JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def strip_parentheticals(text: str) -> str:
    """Match the earlier handoff audit by removing rubric examples."""
    old = None
    while old != text:
        old = text
        text = PAREN_RE.sub(" ", text)
    return " ".join(text.split())


def tokens(text: str, *, strip_examples: bool = True) -> set[str]:
    """Return deterministic content-token sets for diagnostic recall."""
    if strip_examples:
        text = strip_parentheticals(text)
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.casefold() not in STOP
    }


def recall(needle: set[str], haystack: set[str]) -> float:
    """Measure criterion-token recall, the frozen audit's direction."""
    return len(needle & haystack) / len(needle) if needle else 0.0


def precision(needle: set[str], haystack: set[str]) -> float:
    """Measure what fraction of a locator's tokens belong to the criterion."""
    return len(needle & haystack) / len(haystack) if haystack else 0.0


def extract_literals(text: str) -> list[str]:
    """Extract only mechanically identifiable numeric/acronym-like literals."""
    return list(dict.fromkeys(
        match.group().strip() for match in LITERAL_RE.finditer(text)
        if match.group().strip()
    ))


def format_requirements(text: str) -> list[str]:
    """Return output forms forbidden by the current ordinary terminal policy."""
    return [name for name, pattern in FORMAT_PATTERNS.items() if pattern.search(text)]


def current_head() -> str:
    """Pin the analysis to the requested committed implementation."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def ledger_rows() -> dict[str, dict[str, Any]]:
    """Select the newest complete Sol-judge ledger row for each run."""
    selected: dict[str, dict[str, Any]] = {}
    for row in rows(RESULTS):
        if row.get("topics") == 30 and row.get("judge") == "gpt-5.6-sol":
            selected[str(row["run_id"])] = row
    for run_id in RUNS.values():
        if run_id not in selected:
            raise RuntimeError(f"missing ledger row: {run_id}")
    return selected


def rubric_rows() -> dict[str, dict[str, Any]]:
    """Load the exact fixed rubric set."""
    return {str(row["qid"]): row for row in rows(RUBRICS)}


def output_artifacts() -> dict[str, dict[str, tuple[Path, dict[str, Any]]]]:
    """Load exactly one complete output per run and development topic."""
    selected: dict[str, dict[str, tuple[Path, dict[str, Any]]]] = {
        run_id: {} for run_id in RUNS.values()
    }
    for output_root in OUTPUT_ROOTS:
        for path in output_root.glob("*.output.json"):
            try:
                obj = load_json(path)
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            metadata = obj.get("metadata", {})
            run_id = str(metadata.get("run_id") or "")
            if run_id not in selected:
                continue
            qid = str(metadata.get("narrative_id") or "")
            if qid in selected[run_id]:
                raise RuntimeError(f"duplicate output for {run_id}/{qid}")
            if obj.get("trace", {}).get("status") != "completed":
                raise RuntimeError(f"incomplete output: {path}")
            selected[run_id][qid] = (path, obj)
    for run_id, by_qid in selected.items():
        if len(by_qid) != 30:
            raise RuntimeError(f"expected 30 outputs for {run_id}, got {len(by_qid)}")
    return selected


def repeat_paths(variant: str, qid: str) -> list[Path]:
    """Return the three exact cache paths in grading order."""
    return [
        CACHE / variant / f"{qid}.json",
        CACHE / variant / f"{qid}.r1.json",
        CACHE / variant / f"{qid}.r2.json",
    ]


def verdict_matrix(
    ledger: dict[str, dict[str, Any]],
    rubrics: dict[str, dict[str, Any]],
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[tuple[str, str], list[float]],
    list[Path],
]:
    """Load every raw repeat and average values criterion by criterion."""
    raw: dict[tuple[str, str], list[dict[str, Any]]] = {}
    values: dict[tuple[str, str], list[float]] = {}
    paths_seen: list[Path] = []
    for run_id in RUNS.values():
        variant = str(ledger[run_id]["variant"])
        for qid, rubric in sorted(rubrics.items()):
            criteria = [item for item in rubric["criteria"] if not item["waived"]]
            repeats: list[dict[str, Any]] = []
            for path in repeat_paths(variant, qid):
                obj = load_json(path)
                verdicts = obj.get("verdicts")
                if obj.get("status") != "completed" or not isinstance(verdicts, list):
                    raise RuntimeError(f"incomplete verdict cache: {path}")
                if len(verdicts) != len(criteria):
                    raise RuntimeError(f"criterion mismatch: {path}")
                repeats.append({
                    "path": rel(path),
                    "verdicts": verdicts,
                })
                paths_seen.append(path)
            raw[(run_id, qid)] = repeats
            values[(run_id, qid)] = [
                statistics.mean(VALUE[repeat["verdicts"][index]] for repeat in repeats)
                for index in range(len(criteria))
            ]
    return raw, values, paths_seen


def serialized_row(item: ContractItem) -> dict[str, Any]:
    """Serialize a contract row with the exact text used for lexical matching."""
    value = asdict(item)
    value["must_mention"] = list(value["must_mention"])
    value["match_text"] = (
        item.requirement + " " + " ".join(item.must_mention)
    ).strip()
    value["tokens"] = sorted(tokens(value["match_text"]))
    return value


def contract_for_output(obj: dict[str, Any]) -> list[ContractItem]:
    """Replay the e89 builder over one frozen plan/scout handoff."""
    trace = obj.get("trace", {})
    trace_input = trace.get("input", {})
    plan = str(
        trace_input.get("coverage_plan")
        or trace_input.get("coverage_plan_initial")
        or ""
    )
    if not plan:
        return []
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


def topic_contracts(
    artifacts: dict[str, dict[str, tuple[Path, dict[str, Any]]]],
    qids: Iterable[str],
) -> tuple[dict[str, list[ContractItem]], dict[str, list[dict[str, Any]]]]:
    """Build promoted rows and the optimistic union of every frozen plan row."""
    current: dict[str, list[ContractItem]] = {}
    frozen_union: dict[str, list[dict[str, Any]]] = {}
    for qid in qids:
        current[qid] = contract_for_output(artifacts[PROMOTED][qid][1])
        seen: set[tuple[Any, ...]] = set()
        additions: list[dict[str, Any]] = []
        for alias, run_id in RUNS.items():
            for item in contract_for_output(artifacts[run_id][qid][1]):
                fingerprint = (
                    item.kind, item.requirement, item.must_mention,
                    item.must_research, item.must_answer,
                )
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                row = serialized_row(item)
                row["source_run"] = alias
                additions.append(row)
        frozen_union[qid] = additions
    return current, frozen_union


def greedy_cover(
    criterion_tokens: set[str],
    row_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Select rows that add the most uncovered criterion tokens."""
    uncovered = set(criterion_tokens)
    chosen: list[dict[str, Any]] = []
    remaining = list(row_records)
    while uncovered and remaining:
        scored = [
            (len(uncovered & set(row["tokens"])), index, row)
            for index, row in enumerate(remaining)
        ]
        added_count, index, row = max(scored, key=lambda value: (value[0], -value[1]))
        if not added_count:
            break
        added = sorted(uncovered & set(row["tokens"]))
        chosen.append({"id": row["id"], "added_tokens": added})
        uncovered.difference_update(added)
        remaining.pop(index)
    return chosen, criterion_tokens - uncovered


def row_match(
    criterion_text: str,
    row_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return single-row and inventory-level coverage diagnostics."""
    criterion_tokens = tokens(criterion_text)
    scored = []
    for row in row_records:
        row_tokens = set(row["tokens"])
        scored.append({
            "id": row["id"],
            "origin": row["origin"],
            "kind": row["kind"],
            "recall": recall(criterion_tokens, row_tokens),
            "matched_tokens": sorted(criterion_tokens & row_tokens),
        })
    scored.sort(key=lambda item: (-item["recall"], item["id"]))
    greedy, covered = greedy_cover(criterion_tokens, row_records)
    inventory_recall = recall(criterion_tokens, covered)
    origin_recall = {}
    for origin in ("planner", "scout", "request"):
        origin_tokens = set().union(*(
            set(row["tokens"])
            for row in row_records
            if row["origin"] == origin
        )) if any(row["origin"] == origin for row in row_records) else set()
        origin_recall[origin] = recall(criterion_tokens, origin_tokens)
    mentions = [
        mention
        for row in row_records
        for mention in row.get("must_mention", [])
    ]
    literals = extract_literals(criterion_text)
    enforced_literals = [
        literal for literal in literals
        if any(literal.casefold() == mention.casefold() for mention in mentions)
    ]
    return {
        "criterion_core_text": strip_parentheticals(criterion_text),
        "criterion_tokens": sorted(criterion_tokens),
        "single_row_max_recall": scored[0]["recall"] if scored else 0.0,
        "top_row_matches": scored[:5],
        "greedy_inventory_rows": greedy,
        "inventory_recall": inventory_recall,
        "origin_inventory_recall": origin_recall,
        "represented_by_origin_at_0.5": {
            origin: value >= 0.5 for origin, value in origin_recall.items()
        },
        "represented": {
            str(threshold): inventory_recall >= threshold
            for threshold in REPRESENTATION_THRESHOLDS
        },
        "atomic_row_represented_at_0.5": bool(
            scored and scored[0]["recall"] >= 0.5
        ),
        "mechanical_literals": literals,
        "literals_declared_by_must_mention": enforced_literals,
    }


def fact_cards(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract historical cards if a candidate happened to contain any."""
    found: list[dict[str, Any]] = []
    for step in obj.get("trace", {}).get("steps", []):
        arguments = step.get("arguments") or {}
        if not isinstance(arguments, dict):
            continue
        for document in arguments.get("documents", []):
            if not isinstance(document, dict):
                continue
            for fact in document.get("facts", []):
                if isinstance(fact, dict):
                    found.append({"document_id": document.get("id"), **fact})
    return found


def resolve_citations(obj: dict[str, Any], citations: Any) -> list[str]:
    """Resolve organizer citation indexes while preserving literal ids."""
    references = obj.get("references", [])
    resolved: list[str] = []
    if not isinstance(citations, list):
        return resolved
    for value in citations:
        if isinstance(value, int) and 0 <= value < len(references):
            resolved.append(str(references[value]))
        elif isinstance(value, str):
            resolved.append(value)
    return resolved


def answer_item_locators(
    criterion_text: str,
    obj: dict[str, Any],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Locate the most lexically relevant items inside an authoritative answer."""
    core_tokens = tokens(criterion_text)
    full_tokens = tokens(criterion_text, strip_examples=False)
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(obj.get("answer", [])):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        item_tokens = tokens(text, strip_examples=False)
        candidates.append({
            "answer_item_index": index,
            "text": text,
            "citations": item.get("citations", []),
            "resolved_citations": resolve_citations(obj, item.get("citations")),
            "core_token_recall": recall(core_tokens, item_tokens),
            "full_token_recall": recall(full_tokens, item_tokens),
            "token_precision": precision(full_tokens, item_tokens),
        })
    candidates.sort(key=lambda item: (
        -max(item["core_token_recall"], item["full_token_recall"]),
        -item["token_precision"],
        item["answer_item_index"],
    ))
    return candidates[:limit]


def preservation_analysis(
    criterion: dict[str, Any],
    match: dict[str, Any],
    rows_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Classify what the current semantic-light validator can actually retain."""
    weight = float(criterion["signed_weight"])
    forms = format_requirements(str(criterion["text"]))
    count_semantics = bool(COUNT_RE.search(str(criterion["text"])))
    top = match["top_row_matches"][0] if match["top_row_matches"] else None
    top_row = rows_by_id.get(top["id"]) if top else None
    atomic = bool(match["atomic_row_represented_at_0.5"])
    inventory = bool(match["represented"]["0.5"])
    special_form = bool(
        top_row and top_row["kind"] in {"python_code", "repeated_labels"}
    )
    deterministic = bool(
        weight > 0
        and atomic
        and top_row
        and top_row["must_answer"]
        and not forms
        and (not count_semantics or special_form)
        and (
            top_row["must_research"]
            or top_row["must_mention"]
            or special_form
        )
    )
    gaps: list[str] = []
    if not inventory:
        gaps.append("planner_scout_inventory_omission")
    elif not atomic:
        gaps.append("criterion_scattered_without_one_atomic_row")
    if weight < 0:
        gaps.append("penalty_rows_are_not_terminally_enforced")
    if forms:
        gaps.append("terminal_answer_form_not_authorized")
    if count_semantics and not special_form:
        gaps.append("count_or_list_semantics_not_validated")
    literals = match["mechanical_literals"]
    declared = match["literals_declared_by_must_mention"]
    if literals and len(declared) < len(literals):
        gaps.append("criterion_literals_not_fully_declared_by_rows")
    if atomic and top_row and not top_row["must_research"] and not special_form:
        gaps.append("structural_row_closes_by_tag_without_semantic_check")
    return {
        "format_requirements": forms,
        "count_or_list_semantics": count_semantics,
        "top_atomic_row": top_row["id"] if atomic and top_row else None,
        "top_atomic_row_kind": top_row["kind"] if atomic and top_row else None,
        "top_atomic_row_must_research": (
            top_row["must_research"] if atomic and top_row else None
        ),
        "top_atomic_row_must_answer": (
            top_row["must_answer"] if atomic and top_row else None
        ),
        "deterministically_preservable_by_current_validator": deterministic,
        "gaps": gaps,
    }


def score(criteria: list[dict[str, Any]], values: list[float]) -> float:
    """Apply the fixed signed-weight score used by the oracle script."""
    denominator = sum(
        float(item["signed_weight"])
        for item in criteria
        if float(item["signed_weight"]) > 0
    )
    numerator = sum(
        float(item["signed_weight"]) * value
        for item, value in zip(criteria, values)
    )
    return numerator / denominator


def desired_value(weight: float, run_values: dict[str, float]) -> float:
    """Select max reward or minimum incurred penalty exactly like the oracle."""
    return max(run_values.values()) if weight > 0 else min(run_values.values())


def improved(weight: float, promoted: float, oracle: float) -> bool:
    """Return whether the criterion contributes an oracle improvement over P."""
    return oracle > promoted if weight > 0 else oracle < promoted


def build_report() -> dict[str, Any]:
    """Construct the full per-topic/per-criterion reachability matrix."""
    head = current_head()
    if head != EXPECTED_HEAD:
        raise RuntimeError(f"expected HEAD {EXPECTED_HEAD}, found {head}")

    ledger = ledger_rows()
    rubrics = rubric_rows()
    artifacts = output_artifacts()
    raw_verdicts, criterion_values, verdict_paths = verdict_matrix(ledger, rubrics)
    current_contracts, frozen_contract_union = topic_contracts(
        artifacts, sorted(rubrics)
    )

    topic_matrix: list[dict[str, Any]] = []
    all_criterion_rows: list[dict[str, Any]] = []
    baseline_scores: list[float] = []
    oracle_scores: list[float] = []
    inventory_scores: dict[float, list[float]] = {
        threshold: [] for threshold in REPRESENTATION_THRESHOLDS
    }
    atomic_scores: list[float] = []
    strict_scores: list[float] = []
    frozen_inventory_scores: list[float] = []
    content_only_asymptote_scores: list[float] = []
    dynamic_curves: dict[str, dict[int, list[float]]] = {
        "inventory_typed": {cap: [] for cap in range(0, 11)},
        "atomic_typed": {cap: [] for cap in range(0, 11)},
        "inventory_content_only": {cap: [] for cap in range(0, 11)},
        "atomic_content_only": {cap: [] for cap in range(0, 11)},
    }
    aggregate = collections.Counter()
    gain_by_axis: collections.Counter[str] = collections.Counter()
    gain_by_gap: collections.Counter[str] = collections.Counter()
    input_artifact_paths: set[Path] = set()

    for qid, rubric in sorted(rubrics.items()):
        criteria = [item for item in rubric["criteria"] if not item["waived"]]
        current_rows = [serialized_row(item) for item in current_contracts[qid]]
        rows_by_id = {row["id"]: row for row in current_rows}
        frozen_rows = frozen_contract_union[qid]
        promoted_path, promoted_obj = artifacts[PROMOTED][qid]
        input_artifact_paths.add(promoted_path)
        topic_criteria: list[dict[str, Any]] = []
        condition_values: dict[str, list[float]] = {
            "promoted": [], "oracle": [], "atomic": [], "strict": [],
            "frozen_inventory": [],
            **{
                f"inventory_{threshold}": []
                for threshold in REPRESENTATION_THRESHOLDS
            },
        }
        dynamic_candidates: dict[str, list[tuple[float, int]]] = {
            name: [] for name in dynamic_curves
        }

        for index, criterion in enumerate(criteria):
            weight = float(criterion["signed_weight"])
            values_by_alias = {
                alias: criterion_values[(run_id, qid)][index]
                for alias, run_id in RUNS.items()
            }
            promoted_value = values_by_alias["P"]
            oracle_value = desired_value(weight, values_by_alias)
            is_improved = improved(weight, promoted_value, oracle_value)
            oracle_aliases = [
                alias for alias, value in values_by_alias.items()
                if abs(value - oracle_value) < 1e-12
            ]
            current_match = row_match(str(criterion["text"]), current_rows)
            frozen_match = row_match(str(criterion["text"]), frozen_rows)
            preservation = preservation_analysis(
                criterion, current_match, rows_by_id
            )

            candidates = []
            for alias in oracle_aliases:
                if alias == "P" and is_improved:
                    continue
                run_id = RUNS[alias]
                path, obj = artifacts[run_id][qid]
                input_artifact_paths.add(path)
                cards = fact_cards(obj)
                candidates.append({
                    "alias": alias,
                    "run_id": run_id,
                    "artifact": rel(path),
                    "judged_value": values_by_alias[alias],
                    "answer_item_locators": answer_item_locators(
                        str(criterion["text"]), obj
                    ),
                    "fact_cards_in_artifact": len(cards),
                    "fact_locators": [],
                })

            raw_by_alias = {
                alias: {
                    "variant": str(ledger[run_id]["variant"]),
                    "repeat_verdicts": [
                        repeat["verdicts"][index]
                        for repeat in raw_verdicts[(run_id, qid)]
                    ],
                    "value": values_by_alias[alias],
                }
                for alias, run_id in RUNS.items()
            }
            numerator_gain = (
                weight * (oracle_value - promoted_value) if is_improved else 0.0
            )
            criterion_record = {
                "criterion_index": index,
                "cid": criterion["cid"],
                "text": criterion["text"],
                "signed_weight": weight,
                "kind": criterion["kind"],
                "type": criterion["type"],
                "tier": criterion["tier"],
                "axis": criterion["axis"],
                "raw_verdict_matrix": raw_by_alias,
                "promoted_value": promoted_value,
                "oracle_value": oracle_value,
                "oracle_improves_promoted": is_improved,
                "oracle_numerator_gain": numerator_gain,
                "oracle_source_aliases": oracle_aliases,
                "supporting_candidates": candidates,
                "current_contract_match": current_match,
                "all_frozen_contract_rows_match": frozen_match,
                "preservation": preservation,
            }
            topic_criteria.append(criterion_record)
            all_criterion_rows.append({"qid": qid, **criterion_record})

            condition_values["promoted"].append(promoted_value)
            condition_values["oracle"].append(oracle_value)
            for threshold in REPRESENTATION_THRESHOLDS:
                represented = current_match["represented"][str(threshold)]
                condition_values[f"inventory_{threshold}"].append(
                    oracle_value if is_improved and represented else promoted_value
                )
            atomic = current_match["atomic_row_represented_at_0.5"]
            strict = preservation[
                "deterministically_preservable_by_current_validator"
            ]
            frozen_rep = frozen_match["represented"]["0.5"]
            condition_values["atomic"].append(
                oracle_value if is_improved and atomic else promoted_value
            )
            condition_values["strict"].append(
                oracle_value if is_improved and strict else promoted_value
            )
            condition_values["frozen_inventory"].append(
                oracle_value if is_improved and frozen_rep else promoted_value
            )

            if is_improved:
                aggregate["oracle_improved_criteria"] += 1
                aggregate["oracle_numerator_gain"] += numerator_gain
                aggregate[
                    "oracle_improved_penalties" if weight < 0
                    else "oracle_improved_rewards"
                ] += 1
                gain_by_axis[str(criterion["axis"])] += numerator_gain
                for threshold in REPRESENTATION_THRESHOLDS:
                    if current_match["represented"][str(threshold)]:
                        aggregate[f"inventory_represented_at_{threshold}"] += 1
                        aggregate[
                            f"inventory_represented_gain_at_{threshold}"
                        ] += numerator_gain
                for origin, represented in current_match[
                    "represented_by_origin_at_0.5"
                ].items():
                    if represented:
                        aggregate[f"{origin}_represented_at_0.5"] += 1
                        aggregate[f"{origin}_represented_gain_at_0.5"] += (
                            numerator_gain
                        )
                if atomic:
                    aggregate["atomic_row_represented_at_0.5"] += 1
                    aggregate["atomic_row_represented_gain"] += numerator_gain
                if frozen_rep:
                    aggregate["all_frozen_inventory_represented_at_0.5"] += 1
                    aggregate["all_frozen_inventory_represented_gain"] += numerator_gain
                if strict:
                    aggregate["strictly_preservable"] += 1
                    aggregate["strictly_preservable_gain"] += numerator_gain
                for gap in preservation["gaps"]:
                    gain_by_gap[gap] += numerator_gain

                blocked_content = bool(
                    weight < 0 or preservation["format_requirements"]
                )
                for prefix, represented in (
                    ("inventory", current_match["represented"]["0.5"]),
                    ("atomic", atomic),
                ):
                    if not represented:
                        dynamic_candidates[f"{prefix}_typed"].append(
                            (numerator_gain, index)
                        )
                    if not represented and not blocked_content:
                        dynamic_candidates[f"{prefix}_content_only"].append(
                            (numerator_gain, index)
                        )

        baseline_scores.append(score(criteria, condition_values["promoted"]))
        oracle_scores.append(score(criteria, condition_values["oracle"]))
        for threshold in REPRESENTATION_THRESHOLDS:
            inventory_scores[threshold].append(score(
                criteria, condition_values[f"inventory_{threshold}"]
            ))
        atomic_scores.append(score(criteria, condition_values["atomic"]))
        strict_scores.append(score(criteria, condition_values["strict"]))
        frozen_inventory_scores.append(score(
            criteria, condition_values["frozen_inventory"]
        ))

        for mode, by_cap in dynamic_curves.items():
            prefix = "inventory" if mode.startswith("inventory") else "atomic"
            base_values = list(condition_values[
                "inventory_0.5" if prefix == "inventory" else "atomic"
            ])
            content_only = mode.endswith("content_only")
            if content_only:
                for index, criterion in enumerate(criteria):
                    record = topic_criteria[index]
                    blocked = bool(
                        float(criterion["signed_weight"]) < 0
                        or record["preservation"]["format_requirements"]
                    )
                    if blocked:
                        base_values[index] = record["promoted_value"]
            ranked = sorted(
                dynamic_candidates[mode], key=lambda value: (-value[0], value[1])
            )
            for cap in by_cap:
                selected_indexes = {index for _gain, index in ranked[:cap]}
                values_for_cap = list(base_values)
                for index in selected_indexes:
                    values_for_cap[index] = topic_criteria[index]["oracle_value"]
                by_cap[cap].append(score(criteria, values_for_cap))

        content_values = list(condition_values["oracle"])
        for index, criterion in enumerate(criteria):
            if (
                float(criterion["signed_weight"]) < 0
                or topic_criteria[index]["preservation"]["format_requirements"]
            ):
                content_values[index] = topic_criteria[index]["promoted_value"]
        content_only_asymptote_scores.append(score(criteria, content_values))

        topic_matrix.append({
            "qid": qid,
            "query": rubric["query"],
            "domain": rubric.get("domain"),
            "promoted_artifact": rel(promoted_path),
            "current_answer_form_policy": infer_answer_form_policy(
                str(rubric["query"])
            ).trace(),
            "frozen_observable_scout_rows": 0,
            "current_observable_scout_capacity": 6,
            "current_contract_rows": current_rows,
            "all_frozen_contract_row_union": frozen_rows,
            "scores": {
                "promoted": baseline_scores[-1],
                "oracle": oracle_scores[-1],
                **{
                    f"inventory_gate_{threshold}": inventory_scores[threshold][-1]
                    for threshold in REPRESENTATION_THRESHOLDS
                },
                "atomic_row_gate_0.5": atomic_scores[-1],
                "strict_current_preservation": strict_scores[-1],
                "all_frozen_inventory_gate_0.5": frozen_inventory_scores[-1],
                "content_only_oracle_asymptote": content_only_asymptote_scores[-1],
            },
            "criteria": topic_criteria,
        })

    aggregate["all_unwaived_criteria"] = len(all_criterion_rows)
    means = {
        "promoted_actual": statistics.mean(baseline_scores),
        "four_core_criterion_union": statistics.mean(oracle_scores),
        **{
            f"current_inventory_gate_{threshold}": statistics.mean(scores)
            for threshold, scores in inventory_scores.items()
        },
        "current_atomic_row_gate_0.5": statistics.mean(atomic_scores),
        "current_strict_preservation_gate": statistics.mean(strict_scores),
        "all_frozen_planner_scout_inventory_gate_0.5": statistics.mean(
            frozen_inventory_scores
        ),
        "content_only_oracle_asymptote": statistics.mean(
            content_only_asymptote_scores
        ),
    }
    curve_means = {
        mode: {
            str(cap): statistics.mean(values)
            for cap, values in by_cap.items()
        }
        for mode, by_cap in dynamic_curves.items()
    }
    smallest_caps = {}
    for mode, curve in curve_means.items():
        caps = [int(cap) for cap, value in curve.items() if value >= 0.8]
        smallest_caps[mode] = min(caps) if caps else None

    artifact_provenance = [
        {"path": rel(path), "sha256": sha256(path)}
        for run_id in RUNS.values()
        for path, _obj in [
            artifacts[run_id][qid] for qid in sorted(artifacts[run_id])
        ]
    ]
    verdict_provenance = [
        {"path": rel(path), "sha256": sha256(path)}
        for path in sorted(set(verdict_paths))
    ]
    source_paths = [
        ROOT / "src/systems/aus_agent_v2/coverage_contract.py",
        ROOT / "src/systems/aus_agent_v2/answer_form.py",
        ROOT / "src/systems/aus_agent_v2/observable_scout.py",
        ROOT / "src/systems/aus_agent_v2/coverage_plan.py",
        ROOT / "src/systems/aus_agent_v2/plan_critic.py",
        ROOT / "src/systems/aus_agent_v2/prompts/system/contract-lean.md",
    ]

    recommendation = {
        "smallest_architecture_change": (
            "Replace the fixed semantic-light row ledger with a bounded typed "
            "mutable ledger: let the existing researcher promote up to six "
            "retrieval-discovered atomic requirements, and give rows enforced "
            "assert/avoid/form modes with required literals and minimum counts. "
            "This adds no selector, writer, or provider pass."
        ),
        "why_both_parts_are_required": (
            "Dynamic content rows alone asymptote below 0.8 because current "
            "penalty rows are not validated and requested tables/non-blog "
            "section labels are prohibited by the terminal policy."
        ),
        "quantified_ceiling": {
            "fixed_current_inventory": means["current_inventory_gate_0.5"],
            "unlimited_content_only": means["content_only_oracle_asymptote"],
            "ideal_six_typed_dynamic_from_inventory": curve_means[
                "inventory_typed"
            ]["6"],
            "ideal_six_typed_dynamic_from_atomic_rows": curve_means[
                "atomic_typed"
            ]["6"],
            "full_four_core_union": means["four_core_criterion_union"],
        },
        "important_caveat": (
            "The dynamic ceilings assume perfect selection of the highest-value "
            "missing criteria and reuse already-judged candidate content; they "
            "are upper bounds, not an achieved score or a model forecast."
        ),
    }

    return {
        "schema_version": 1,
        "audit": "lean-contract reachability of the reported 0.8048 criterion union",
        "head": head,
        "network_or_api_calls": 0,
        "bedrock_cost_usd": 0,
        "method": {
            "authoritative_signal": (
                "Three-repeat frozen Sol verdicts determine criterion values."
            ),
            "diagnostic_row_match": (
                "Remove parenthetical rubric examples, drop fixed boilerplate "
                "tokens, and measure criterion-token recall against individual "
                "rows and the union of all current row tokens."
            ),
            "representation_thresholds": list(REPRESENTATION_THRESHOLDS),
            "oracle": (
                "For each positive-weight criterion choose the maximum of B/P/R/A; "
                "for each penalty choose the minimum, then apply signed weights."
            ),
            "missed_criterion": (
                "A criterion whose oracle value improves over promoted P in the "
                "signed-weight desired direction."
            ),
            "candidate_item_locator": (
                "The verdict identifies the supporting answer globally; up to "
                "three answer items are included as lexical locators, not new judgments."
            ),
            "dynamic_ceiling": (
                "Per topic, add the highest signed-numerator-gain currently "
                "unrepresented criteria, one ideal atomic row per criterion."
            ),
        },
        "runs": {
            alias: {
                "run_id": run_id,
                "variant": ledger[run_id]["variant"],
                "mean_score": ledger[run_id]["mean_score"],
            }
            for alias, run_id in RUNS.items()
        },
        "summary": {
            "counts_and_weighted_gains": dict(sorted(aggregate.items())),
            "oracle_gain_by_axis": dict(sorted(gain_by_axis.items())),
            "oracle_gain_by_preservation_gap": dict(sorted(gain_by_gap.items())),
            "mean_score_ceilings": means,
            "ideal_dynamic_row_cap_curves": curve_means,
            "smallest_cap_reaching_0.8": smallest_caps,
        },
        "recommendation": recommendation,
        "topics": topic_matrix,
        "provenance": {
            "script": rel(SCRIPT),
            "script_sha256": sha256(SCRIPT),
            "result_ledger": {"path": rel(RESULTS), "sha256": sha256(RESULTS)},
            "fixed_rubrics": {"path": rel(RUBRICS), "sha256": sha256(RUBRICS)},
            "committed_sources": [
                {"path": rel(path), "sha256": sha256(path)}
                for path in source_paths
            ],
            "candidate_outputs": artifact_provenance,
            "verdict_caches": verdict_provenance,
        },
        "limitations": [
            "No full-30 observable-scout outputs exist; its six-row capacity is modeled, not observed.",
            "Lexical row and item matches are locators and may undercount paraphrases.",
            "The 0.8048 union combines fragments from different answers and is not an achieved answer.",
            "Dynamic-row curves assume perfect criterion targeting and successful evidence reuse.",
        ],
    }


def main() -> None:
    """Write the full JSON matrix and print its decision-grade summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
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
    summary = report["summary"]
    print(f"wrote {rel(output)}")
    print("counts=" + json.dumps(
        summary["counts_and_weighted_gains"], sort_keys=True
    ))
    print("means=" + json.dumps(
        summary["mean_score_ceilings"], sort_keys=True
    ))
    print("smallest_caps=" + json.dumps(
        summary["smallest_cap_reaching_0.8"], sort_keys=True
    ))
    print("recommendation=" + report["recommendation"]["smallest_architecture_change"])


if __name__ == "__main__":
    main()
