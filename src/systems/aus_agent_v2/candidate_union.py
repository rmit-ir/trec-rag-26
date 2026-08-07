"""Citation-preserving extractive union over complete research answers.

Independent complete runs contain complementary rubric value: the frozen
criterion oracle exceeds 0.80 even though no single answer does.  This
stage exposes those complete answers to one fresh selector, but never asks it
to rewrite prose.  It returns item ids only; the harness copies the selected
sentences and their original citations byte-for-byte into a bounded answer.

An anchor answer supplies a conservative floor.  A valid union must retain a
majority of its items and words, explicitly map each dropped anchor item to
selected non-anchor replacements, preserve every source's relative order, fit
the official 1,024-word limit, and audit-account for every selected item. Any
provider or protocol failure falls back to the exact anchor output.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any, Callable

from agent_harness.providers.base import Provider
from ragrun.outputs import validate_rag_output
from ragrun.trajectory import now_iso


MAX_CANDIDATES = 8
MAX_ITEMS_PER_CANDIDATE = 96
MAX_TOTAL_ITEMS = MAX_CANDIDATES * MAX_ITEMS_PER_CANDIDATE
MAX_SELECTED_ITEMS = 96
MAX_COVERAGE_ROWS = 32
MAX_UNION_PACKET_CHARS = 140_000
MAX_ANSWER_WORDS = 1_024
MIN_ANCHOR_ITEM_FRACTION = 0.60
MIN_ANCHOR_WORD_FRACTION = 0.65


CANDIDATE_UNION_SYSTEM = """\
You are the extractive union compiler for a research agent. You receive one
original request and several already-complete candidate answers. One candidate
is the anchor. Each candidate item has an immutable item_id, text, and source
document ids.

Construct the strongest answer by selecting whole items only. Never rewrite,
join, split, paraphrase, or invent prose, citations, facts, requirements, or
formatting. Preserve the anchor's useful coverage and every source's relative
order, replacing or supplementing it only with materially more complete
candidate items. Cover
the explicit request, necessary implied criteria, requested examples or counts,
comparisons, mechanisms, qualifications, audience, and requested answer form.
Prefer concrete names, numbers, scopes, and causal or comparative relationships
over generic summary. Avoid duplicated claims, contradictions, repeated
introductions, and fragments that depend on omitted context.

The compiled sequence must stay at or below max_answer_words. Do not introduce
headings, tables, bullets, labels, or code unless the original request calls for
that form and the selected candidate item already contains it. Every selected
item must appear in at least one coverage row. For every omitted anchor item,
provide exactly one anchor_replacements row mapping its immutable id to one or
more selected non-anchor item ids. Coverage and replacement rows are
model-supplied audit accounting; they are not proof of criterion coverage and
are not answer prose. A valid union must select at least one non-anchor item.

Call submit_candidate_union exactly once and emit no prose outside the tool
call.\
"""


CANDIDATE_UNION_TOOL: dict[str, Any] = {
    "name": "submit_candidate_union",
    "description": (
        "Select and order immutable candidate item ids, with an auditable "
        "request-coverage mapping. This is the only valid response."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "selected_item_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_SELECTED_ITEMS,
                "items": {"type": "string"},
            },
            "coverage": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_COVERAGE_ROWS,
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement": {
                            "type": "string", "maxLength": 400,
                        },
                        "item_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["requirement", "item_ids"],
                    "additionalProperties": False,
                },
            },
            "anchor_replacements": {
                "type": "array",
                "maxItems": MAX_ITEMS_PER_CANDIDATE,
                "items": {
                    "type": "object",
                    "properties": {
                        "dropped_anchor_item_id": {"type": "string"},
                        "replacement_item_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "dropped_anchor_item_id", "replacement_item_ids",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "selected_item_ids", "coverage", "anchor_replacements",
        ],
        "additionalProperties": False,
    },
}


def _compact(value: Any, limit: int) -> str:
    """Collapse whitespace in bounded model-visible fields."""
    return " ".join(str(value or "").split())[:limit]


def _normalized_text(value: Any, field: str) -> str:
    """Normalize all whitespace without truncating identity-bearing text."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return " ".join(value.split())


def _stable_candidate_order(
    expected_qid: str,
    candidate_outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove caller chronology as an anonymous candidate-position cue."""
    return sorted(
        candidate_outputs,
        key=lambda output: hashlib.sha256(
            f"{expected_qid}\0{output.get('metadata', {}).get('run_id', '')}".encode(
                "utf-8")
        ).digest(),
    )


def _word_count(text: str) -> int:
    """Use the official answer-word norm for one opaque item."""
    return len(text.split())


def _citation_docids(output: dict[str, Any], item: dict[str, Any]) -> list[str]:
    """Resolve either allowed citation representation to immutable docids."""
    references = output.get("references")
    citations = item.get("citations")
    if not isinstance(references, list) or not isinstance(citations, list):
        raise ValueError("candidate references/citations must be arrays")
    resolved: list[str] = []
    for citation in citations:
        if type(citation) is int and 0 <= citation < len(references):
            document_id = references[citation]
        elif isinstance(citation, str) and citation in references:
            document_id = citation
        else:
            raise ValueError(f"candidate has invalid citation {citation!r}")
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("candidate citation resolved to an invalid docid")
        if document_id not in resolved:
            resolved.append(document_id)
    return resolved


def build_candidate_union_packet(
    query: str,
    candidate_outputs: list[dict[str, Any]],
    *,
    expected_qid: str,
    anchor_run_id: str,
) -> dict[str, Any]:
    """Normalize complete same-topic artifacts into an anonymous union packet."""
    if not 2 <= len(candidate_outputs) <= MAX_CANDIDATES:
        raise ValueError(
            f"candidate union needs 2-{MAX_CANDIDATES} complete answers")
    if not isinstance(expected_qid, str) or not expected_qid.strip():
        raise ValueError("candidate union expected_qid is empty")
    normalized_query = _normalized_text(query, "candidate union query")
    if not normalized_query:
        raise ValueError("candidate union query is empty")

    packet_candidates: list[dict[str, Any]] = []
    anchor_ids: list[str] = []
    total_items = 0
    seen_runs: set[str] = set()
    ordered_outputs = _stable_candidate_order(expected_qid, candidate_outputs)
    for candidate_number, output in enumerate(ordered_outputs, 1):
        violations = validate_rag_output(output)
        if violations:
            raise ValueError(
                "candidate output violates RAG format: " + "; ".join(violations))
        metadata = output.get("metadata") or {}
        candidate_qid = metadata.get("narrative_id")
        if candidate_qid != expected_qid:
            raise ValueError(
                "candidate narrative_id does not match the expected qid")
        run_id = str(metadata.get("run_id") or "")
        if not run_id or run_id in seen_runs:
            raise ValueError("candidate run ids must be non-empty and unique")
        seen_runs.add(run_id)
        candidate_query = _normalized_text(
            metadata.get("narrative"), "candidate narrative")
        if candidate_query != normalized_query:
            raise ValueError("candidate narrative does not match the union request")
        candidate_id = f"C{candidate_number:02d}"
        is_anchor = run_id == anchor_run_id
        if is_anchor:
            anchor_ids.append(candidate_id)
        raw_answer = output.get("answer") or []
        if not 1 <= len(raw_answer) <= MAX_ITEMS_PER_CANDIDATE:
            raise ValueError(
                f"candidate {candidate_id} has an invalid answer-item count")
        items: list[dict[str, Any]] = []
        for item_number, raw_item in enumerate(raw_answer, 1):
            if not isinstance(raw_item, dict):
                raise ValueError(f"candidate {candidate_id} item is not an object")
            text = raw_item.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError(f"candidate {candidate_id} item text is invalid")
            item_id = f"{candidate_id}:I{item_number:02d}"
            items.append({
                "item_id": item_id,
                "text": text,
                "source_ids": _citation_docids(output, raw_item),
                "word_count": _word_count(text),
            })
        total_items += len(items)
        packet_candidates.append({
            "candidate_id": candidate_id,
            "anchor": is_anchor,
            "items": items,
        })
    if len(anchor_ids) != 1:
        raise ValueError("anchor_run_id must identify exactly one candidate")
    if total_items > MAX_TOTAL_ITEMS:
        raise ValueError(
            f"candidate union has {total_items} items; maximum is {MAX_TOTAL_ITEMS}")
    return {
        "packet_version": "candidate-union-v1",
        "query_id": expected_qid,
        "original_request": normalized_query,
        "max_answer_words": MAX_ANSWER_WORDS,
        "anchor_candidate_id": anchor_ids[0],
        "minimum_anchor_item_fraction": MIN_ANCHOR_ITEM_FRACTION,
        "minimum_anchor_word_fraction": MIN_ANCHOR_WORD_FRACTION,
        "candidates": packet_candidates,
    }


def candidate_union_request(packet: dict[str, Any]) -> str:
    """Serialize the exact complete packet without truncating candidate prose."""
    text = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_UNION_PACKET_CHARS:
        raise ValueError(
            f"candidate union packet is {len(text)} characters; maximum is "
            f"{MAX_UNION_PACKET_CHARS}")
    return text


def _packet_items(
    packet: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Index trusted packet items and their original per-candidate order."""
    by_id: dict[str, dict[str, Any]] = {}
    order: dict[str, list[str]] = {}
    for candidate in packet.get("candidates") or []:
        candidate_id = str(candidate.get("candidate_id") or "")
        order[candidate_id] = []
        for item in candidate.get("items") or []:
            item_id = str(item.get("item_id") or "")
            by_id[item_id] = {**item, "candidate_id": candidate_id}
            order[candidate_id].append(item_id)
    return by_id, order


def normalize_candidate_union(
    arguments: Any,
    packet: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    """Compile a strict extractive selection or return complete audit errors."""
    errors: list[str] = []
    stats: dict[str, Any] = {}
    if not isinstance(arguments, dict) or set(arguments) != {
            "selected_item_ids", "coverage", "anchor_replacements"}:
        return None, [
            "candidate union arguments must contain only selected_item_ids, "
            "coverage, and anchor_replacements"
        ], stats
    selected_raw = arguments.get("selected_item_ids")
    coverage_raw = arguments.get("coverage")
    replacements_raw = arguments.get("anchor_replacements")
    if (not isinstance(selected_raw, list)
            or not 1 <= len(selected_raw) <= MAX_SELECTED_ITEMS):
        errors.append(
            f"selected_item_ids must contain 1-{MAX_SELECTED_ITEMS} ids")
        selected_raw = []
    if (not isinstance(coverage_raw, list)
            or not 1 <= len(coverage_raw) <= MAX_COVERAGE_ROWS):
        errors.append(f"coverage must contain 1-{MAX_COVERAGE_ROWS} rows")
        coverage_raw = []
    if (not isinstance(replacements_raw, list)
            or len(replacements_raw) > MAX_ITEMS_PER_CANDIDATE):
        errors.append(
            "anchor_replacements must be an array with at most "
            f"{MAX_ITEMS_PER_CANDIDATE} rows")
        replacements_raw = []

    by_id, candidate_order = _packet_items(packet)
    selected: list[str] = []
    for raw in selected_raw:
        item_id = str(raw).strip() if isinstance(raw, str) else ""
        if item_id not in by_id:
            errors.append(f"selected unknown candidate item {item_id!r}")
        elif item_id in selected:
            errors.append(f"selected duplicate candidate item {item_id!r}")
        else:
            selected.append(item_id)

    selected_set = set(selected)
    coverage: list[dict[str, Any]] = []
    covered_items: set[str] = set()
    seen_requirements: set[str] = set()
    for row_number, raw in enumerate(coverage_raw, 1):
        if not isinstance(raw, dict) or set(raw) != {"requirement", "item_ids"}:
            errors.append(f"coverage row {row_number} has an invalid field set")
            continue
        requirement_raw = raw.get("requirement")
        requirement = ""
        if not isinstance(requirement_raw, str):
            errors.append(
                f"coverage row {row_number} requirement must be a string")
        elif len(requirement_raw) > 400:
            errors.append(
                f"coverage row {row_number} requirement must be at most "
                "400 characters")
        else:
            requirement = " ".join(requirement_raw.split())
        requirement_key = requirement.casefold()
        item_ids_raw = raw.get("item_ids")
        if not requirement:
            errors.append(f"coverage row {row_number} has an empty requirement")
        elif requirement_key in seen_requirements:
            errors.append(
                f"coverage row {row_number} duplicates normalized requirement text")
        else:
            seen_requirements.add(requirement_key)
        if not isinstance(item_ids_raw, list) or not 1 <= len(item_ids_raw) <= 8:
            errors.append(f"coverage row {row_number} must name 1-8 selected items")
            continue
        item_ids: list[str] = []
        for raw_id in item_ids_raw:
            item_id = str(raw_id).strip() if isinstance(raw_id, str) else ""
            if item_id not in selected_set:
                errors.append(
                    f"coverage row {row_number} names unselected item {item_id!r}")
            elif item_id in item_ids:
                errors.append(
                    f"coverage row {row_number} duplicates item {item_id!r}")
            else:
                item_ids.append(item_id)
                covered_items.add(item_id)
        coverage.append({"requirement": requirement, "item_ids": item_ids})
    uncovered = [item_id for item_id in selected if item_id not in covered_items]
    if uncovered:
        errors.append("selected items lack coverage rows: " + ", ".join(uncovered))

    fingerprints: set[str] = set()
    for item_id in selected:
        fingerprint = " ".join(
            str(by_id[item_id]["text"]).split()).casefold().rstrip(".!?")
        if fingerprint in fingerprints:
            errors.append(f"selected duplicate normalized text at {item_id}")
        fingerprints.add(fingerprint)

    answer_words = sum(int(by_id[item_id]["word_count"]) for item_id in selected)
    if answer_words > MAX_ANSWER_WORDS:
        errors.append(
            f"compiled answer is {answer_words} words; maximum is {MAX_ANSWER_WORDS}")

    anchor_id = str(packet.get("anchor_candidate_id") or "")
    anchor_order = candidate_order.get(anchor_id, [])
    selected_anchor = [item_id for item_id in selected if item_id in anchor_order]
    for candidate_id, original_order in candidate_order.items():
        source_selection = [
            item_id for item_id in selected
            if by_id[item_id]["candidate_id"] == candidate_id
        ]
        if source_selection != sorted(source_selection, key=original_order.index):
            errors.append(
                f"selected {candidate_id} items changed their original relative order")

    dropped_anchor = [
        item_id for item_id in anchor_order if item_id not in selected_set]
    replacement_rows: list[dict[str, Any]] = []
    replacement_by_anchor: dict[str, list[str]] = {}
    for row_number, raw in enumerate(replacements_raw, 1):
        if not isinstance(raw, dict) or set(raw) != {
                "dropped_anchor_item_id", "replacement_item_ids"}:
            errors.append(
                f"anchor replacement row {row_number} has an invalid field set")
            continue
        dropped_raw = raw.get("dropped_anchor_item_id")
        dropped_id = dropped_raw if isinstance(dropped_raw, str) else ""
        if not isinstance(dropped_raw, str):
            errors.append(
                f"anchor replacement row {row_number} dropped id must be a string")
        elif dropped_id not in anchor_order:
            errors.append(
                f"anchor replacement row {row_number} names non-anchor item "
                f"{dropped_id!r}")
        elif dropped_id in selected_set:
            errors.append(
                f"anchor replacement row {row_number} names retained anchor item "
                f"{dropped_id!r}")
        elif dropped_id in replacement_by_anchor:
            errors.append(
                f"anchor replacement row {row_number} duplicates dropped anchor "
                f"item {dropped_id!r}")
        replacement_ids_raw = raw.get("replacement_item_ids")
        if (not isinstance(replacement_ids_raw, list)
                or not 1 <= len(replacement_ids_raw) <= 8):
            errors.append(
                f"anchor replacement row {row_number} must name 1-8 selected "
                "non-anchor items")
            continue
        replacement_ids: list[str] = []
        for replacement_raw in replacement_ids_raw:
            replacement_id = (
                replacement_raw if isinstance(replacement_raw, str) else "")
            if not isinstance(replacement_raw, str):
                errors.append(
                    f"anchor replacement row {row_number} replacement ids must "
                    "be strings")
            elif replacement_id not in selected_set:
                errors.append(
                    f"anchor replacement row {row_number} names unselected item "
                    f"{replacement_id!r}")
            elif by_id[replacement_id]["candidate_id"] == anchor_id:
                errors.append(
                    f"anchor replacement row {row_number} names anchor item "
                    f"{replacement_id!r} as a replacement")
            elif replacement_id in replacement_ids:
                errors.append(
                    f"anchor replacement row {row_number} duplicates replacement "
                    f"item {replacement_id!r}")
            else:
                replacement_ids.append(replacement_id)
        if dropped_id in dropped_anchor and dropped_id not in replacement_by_anchor:
            replacement_by_anchor[dropped_id] = replacement_ids
        replacement_rows.append({
            "dropped_anchor_item_id": dropped_id,
            "replacement_item_ids": replacement_ids,
        })
    missing_replacements = [
        item_id for item_id in dropped_anchor
        if not replacement_by_anchor.get(item_id)
    ]
    if missing_replacements:
        errors.append(
            "dropped anchor items lack selected non-anchor replacements: "
            + ", ".join(missing_replacements))
    anchor_words = sum(int(by_id[item_id]["word_count"]) for item_id in anchor_order)
    selected_anchor_words = sum(
        int(by_id[item_id]["word_count"]) for item_id in selected_anchor)
    minimum_anchor_items = math.ceil(
        len(anchor_order) * MIN_ANCHOR_ITEM_FRACTION)
    minimum_anchor_words = math.ceil(anchor_words * MIN_ANCHOR_WORD_FRACTION)
    if len(selected_anchor) < minimum_anchor_items:
        errors.append(
            f"compiled answer retains {len(selected_anchor)}/{len(anchor_order)} "
            f"anchor items; minimum is {minimum_anchor_items}")
    if selected_anchor_words < minimum_anchor_words:
        errors.append(
            f"compiled answer retains {selected_anchor_words}/{anchor_words} "
            f"anchor words; minimum is {minimum_anchor_words}")

    contribution: dict[str, dict[str, int]] = {}
    for item_id in selected:
        candidate_id = str(by_id[item_id]["candidate_id"])
        entry = contribution.setdefault(candidate_id, {"items": 0, "words": 0})
        entry["items"] += 1
        entry["words"] += int(by_id[item_id]["word_count"])
    nonanchor_items = sum(
        entry["items"] for candidate_id, entry in contribution.items()
        if candidate_id != anchor_id)
    if nonanchor_items < 1:
        errors.append("candidate union has no non-anchor contribution")
    stats = {
        "selected_items": len(selected),
        "answer_words": answer_words,
        "anchor_items_retained": len(selected_anchor),
        "anchor_items_total": len(anchor_order),
        "anchor_words_retained": selected_anchor_words,
        "anchor_words_total": anchor_words,
        "coverage_rows": len(coverage),
        "anchor_replacement_rows": len(replacement_rows),
        "nonanchor_items": nonanchor_items,
        "contribution": contribution,
    }
    if errors:
        return None, errors, stats

    references: list[str] = []
    answer: list[dict[str, Any]] = []
    for item_id in selected:
        item = by_id[item_id]
        citations: list[int] = []
        for document_id in item["source_ids"]:
            if document_id not in references:
                references.append(document_id)
            citations.append(references.index(document_id))
        answer.append({"text": item["text"], "citations": citations})
    return {
        "selected_item_ids": selected,
        "coverage": coverage,
        "anchor_replacements": replacement_rows,
        "references": references,
        "answer": answer,
    }, [], stats


def _anchor_fallback(
    packet: dict[str, Any],
    candidate_outputs: list[dict[str, Any]],
    anchor_run_id: str,
) -> dict[str, Any]:
    """Return the complete anchor byte-for-byte, including unused references."""
    anchor_id = str(packet["anchor_candidate_id"])
    [anchor] = [
        candidate for candidate in packet["candidates"]
        if candidate["candidate_id"] == anchor_id
    ]
    selected: list[str] = []
    for item in anchor["items"]:
        selected.append(item["item_id"])
    [anchor_output] = [
        output for output in candidate_outputs
        if output.get("metadata", {}).get("run_id") == anchor_run_id
    ]
    return {
        "selected_item_ids": selected,
        "coverage": [],
        "anchor_replacements": [],
        "references": copy.deepcopy(anchor_output["references"]),
        "answer": copy.deepcopy(anchor_output["answer"]),
    }


def select_candidate_union(
    query: str,
    candidate_outputs: list[dict[str, Any]],
    *,
    expected_qid: str,
    anchor_run_id: str,
    provider_factory: Callable[[], Provider],
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Run a fresh typed selector, falling back exactly to the anchor."""
    if not 1 <= max_attempts <= 2:
        raise ValueError("candidate union permits one or two isolated attempts")
    packet = build_candidate_union_packet(
        query, candidate_outputs, expected_qid=expected_qid,
        anchor_run_id=anchor_run_id)
    request = candidate_union_request(packet)
    errors: list[str] = []
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        provider: Provider | None = None
        attempt_started_at = now_iso()
        attempt_request = request
        if errors:
            attempt_request += "\n\nPREVIOUS PROTOCOL ERRORS\n" + json.dumps(
                errors, ensure_ascii=False)
        try:
            provider = provider_factory()
            provider.start(CANDIDATE_UNION_SYSTEM, [CANDIDATE_UNION_TOOL])
            provider.add_user_message(attempt_request)
            turn = provider.run_turn()
            calls = list(turn.get("tool_calls") or [])
            valid_calls = [
                call for call in calls
                if call.get("name") == CANDIDATE_UNION_TOOL["name"]
            ]
            attempt_errors: list[str] = []
            if len(calls) != 1 or len(valid_calls) != 1:
                attempt_errors.append(
                    "call submit_candidate_union exactly once and no other tool")
            if str(turn.get("text") or "").strip():
                attempt_errors.append(
                    "do not include prose outside submit_candidate_union")
            normalized = None
            stats: dict[str, Any] = {}
            if not attempt_errors:
                normalized, normalize_errors, stats = normalize_candidate_union(
                    valid_calls[0].get("arguments"), packet)
                attempt_errors.extend(normalize_errors)
            attempts.append({
                "attempt": attempt,
                "started_at": attempt_started_at,
                "ended_at": now_iso(),
                "errors": list(attempt_errors),
                "stats": stats,
                "model_id": str(provider.model_id),
                "usage": dict(turn.get("usage") or {}),
                "raw_messages": list(provider.raw_messages),
            })
            if normalized is not None:
                return {
                    **normalized,
                    "accepted": True,
                    "fallback": None,
                    "errors": errors,
                    "attempts": attempts,
                    "packet_chars": len(request),
                    "packet": packet,
                }
            errors.extend(
                f"attempt {attempt}: {error}" for error in attempt_errors)
            if attempt_errors == [
                    "candidate union has no non-anchor contribution"]:
                fallback = _anchor_fallback(
                    packet, candidate_outputs, anchor_run_id)
                return {
                    **fallback,
                    "accepted": False,
                    "fallback": "anchor_no_union",
                    "errors": errors,
                    "attempts": attempts,
                    "packet_chars": len(request),
                    "packet": packet,
                }
        except Exception as exc:  # provider failures are bounded and auditable
            message = f"attempt {attempt}: {type(exc).__name__}: {exc}"
            errors.append(message)
            attempts.append({
                "attempt": attempt,
                "started_at": attempt_started_at,
                "ended_at": now_iso(),
                "errors": [message],
                "stats": {},
                "model_id": str(getattr(provider, "model_id", "")),
                "usage": {},
                "raw_messages": list(
                    getattr(provider, "raw_messages", []) if provider else []),
            })

    fallback = _anchor_fallback(packet, candidate_outputs, anchor_run_id)
    return {
        **fallback,
        "accepted": False,
        "fallback": "anchor_after_invalid_union",
        "errors": errors,
        "attempts": attempts,
        "packet_chars": len(request),
        "packet": packet,
    }


def candidate_union_usage(attempts: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate provider-native token counters for budget accounting."""
    total = {
        "reasoning": 0,
        "input": 0,
        "input_uncached": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": 0,
        "total": 0,
        "processed_input": 0,
        "processed": 0,
    }
    for attempt in attempts:
        usage = attempt.get("usage") or {}
        uncached = int(
            usage.get("inputTokens", usage.get("input_tokens", 0)) or 0)
        output = int(
            usage.get("outputTokens", usage.get("output_tokens", 0)) or 0)
        cache_read = int(usage.get(
            "cacheReadInputTokens",
            usage.get("cache_read_input_tokens", 0),
        ) or 0)
        cache_write = int(usage.get(
            "cacheWriteInputTokens",
            usage.get("cache_write_input_tokens", 0),
        ) or 0)
        reasoning = int(usage.get("reasoning_tokens", 0) or 0)
        logical_input = uncached + cache_read + cache_write
        processed_input = uncached + cache_write
        values = {
            "reasoning": reasoning,
            "input": logical_input,
            "input_uncached": uncached,
            "output": output,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "total": logical_input + output,
            "processed_input": processed_input,
            "processed": processed_input + output,
        }
        for key, value in values.items():
            total[key] += value
    return total
