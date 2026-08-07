#!/usr/bin/env python3
"""Re-synthesize a saved first draft in a fresh, evidence-bounded context.

Planning, retrieval, commits, and the original research draft are frozen from
the 30-topic research-first run.  Only the final synthesis context and prompt
change, which isolates whether the long research conversation is hiding facts
and requirements from the writer.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from systems.aus_agent.providers.openai import OpenAIProvider
from systems.aus_agent_v2.agent import (
    _collapse_to_docs,
    _map_citations,
    _parse_final_prose,
    _word_count,
)
from systems.aus_agent_v2.finish_review import build_finish_review_packet


SOURCE_RUN = "sol-aus-v2-research-first-dev30-20260806"
OUTPUT_DIR = Path("data/outputs/aus_agent_v2")

CONSERVATIVE_SYSTEM = """\
You are the final synthesis stage of a research system. You receive the exact
request, a pre-research coverage plan, a complete cited draft, and
citation-local excerpts from the committed evidence.

Revise the draft once. Preserve every distinct accurate point and all requested
deliverables, but make the prose answer the request directly instead of reading
like research notes. Complete a claim when its card supplies a missing exact
name, value, comparison, mechanism, population, date, scope, source, or
limitation. Narrow or remove a claim only when its cited excerpt exposes it as
unsupported. Do not add factual material from memory.

Keep the revision between 90% and 105% of the draft word count unless the draft
is already above 1,024 words, and never exceed 1,024 words. Use the exact
evidence-unit ids printed in the packet; every factual sentence must end with
one to three [unit_id] citations that directly support the whole sentence.
Directly cite every population-level medical, safety, legal, or causal claim.

Return plain flowing prose with exactly one sentence per line. Do not use
Markdown headings, tables, lists, numbering, bold, fences, a references
section, or commentary about the packet or editing process. Return only the
complete revised cited report.
"""

ATOMIC_SYSTEM = """\
You are the fresh-context evidence compiler at the end of a research pipeline.
The long research context has been removed deliberately. You receive the exact
request, its coverage plan, the researcher's complete cited draft, and
citation-local excerpts from committed evidence.

Before writing, silently make two ledgers: every explicit deliverable and
high-priority plan obligation, and every distinct draft claim with its allowed
evidence. Then emit one final report that preserves the draft's supported
coverage while repairing the highest-value incompleteness.

A finished factual claim states the relevant subject and relationship plus the
exact value, comparison, mechanism, population, date, scope, source, or
limitation available in its evidence; a topic name or vague direction is not a
finished claim. Prefer fewer fully stated sentences over fragments, but never
delete a requested part, worked example, definition, comparison, practical
step, or limitation merely to become shorter. Do not introduce facts, named
examples, or causal conclusions from memory. If the cards cannot support a
detail, retain the draft's appropriately qualified wording.

Keep 90% to 105% of the draft's word count and never exceed 1,024 words. Use
only exact [unit_id] identifiers printed in the packet, with one to three
directly supporting citations after every factual sentence. Population-level
medical, safety, legal, and causal claims must be directly cited and scoped no
more broadly than their evidence.

Write plain flowing prose, exactly one sentence per line. Do not use Markdown
headings, tables, bullets, numbering, bold, fences, a references section, or
meta-commentary. Return only the final cited report.
"""


def newest_source(qid: str) -> tuple[Path, dict[str, Any]]:
    """Find the newest exact source-run artifact for one topic."""
    found: list[tuple[str, Path, dict[str, Any]]] = []
    for path in OUTPUT_DIR.glob("*.output.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (obj.get("metadata", {}).get("run_id") == SOURCE_RUN
                and obj.get("metadata", {}).get("narrative_id") == qid
                and obj.get("trace", {}).get("status") == "completed"):
            found.append((path.name.split(".", 1)[0], path, obj))
    if not found:
        raise RuntimeError(f"no source artifact for {qid}")
    _stamp, path, obj = max(found, key=lambda item: item[0])
    return path, obj


def candidate_reports(obj: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Recover valid unit-cited drafts in generation order."""
    committed = set(obj["trace"]["summary"]["context"]["committed"])
    reports: list[tuple[str, list[dict[str, Any]]]] = []
    for step in obj["trace"]["steps"]:
        output = step.get("output")
        if step.get("type") != "generation" or not isinstance(output, dict):
            continue
        if output.get("tool_calls") or not output.get("text"):
            continue
        parsed, _errors, _repairs = _parse_final_prose(
            output["text"], committed, allow_uncited=True)
        if parsed is not None and any(line["citations"] for line in parsed):
            reports.append((str(output["text"]), parsed))
    return reports


def source_documents(path: Path, committed: set[str]) -> dict[str, dict[str, Any]]:
    """Recover the full text retained in provider messages for committed units."""
    trajectory_path = Path(str(path).replace(".output.json", ".trajectory.json"))
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    documents: dict[str, dict[str, Any]] = {}
    # The rich trace keeps the immutable tool payload; raw provider messages
    # are later compacted and therefore contain full text only for a subset.
    raw_payloads = [
        step.get("output")
        for step in trajectory.get("steps", [])
        if step.get("type") == "tool_call" and step.get("tool_name") == "search"
    ]
    raw_payloads.extend(
        item.get("output")
        for item in trajectory.get("raw_messages", [])
        if item.get("type") == "function_call_output"
    )
    for raw in raw_payloads:
        if not isinstance(raw, str):
            continue
        try:
            # Live tool feedback appends a human-readable budget line after
            # the JSON transport payload; it is not part of retrieval data.
            payload = json.loads(raw.split("\n[context budget:", 1)[0])
        except json.JSONDecodeError:
            continue
        for result in payload.get("results", []) if isinstance(payload, dict) else []:
            if not isinstance(result, dict):
                continue
            unit_id = str(result.get("id") or "")
            if unit_id in committed and result.get("text"):
                documents[unit_id] = result
    missing = committed - set(documents)
    if missing:
        raise RuntimeError(
            f"{path.name}: missing retained text for {len(missing)} committed ids: "
            + ", ".join(sorted(missing)[:5]))
    return documents


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qid", required=True)
    parser.add_argument("--mode", choices=("conservative", "atomic"), required=True)
    args = parser.parse_args()

    path, obj = newest_source(args.qid)
    committed = set(obj["trace"]["summary"]["context"]["committed"])
    reports = candidate_reports(obj)
    repair = obj["trace"]["summary"]["coverage_verify"]
    repair_active = bool(repair["research_repair_active"])
    if repair_active and len(reports) < 2:
        raise RuntimeError(f"{args.qid}: expected a pre-repair draft")
    draft, original_sentences = reports[-2] if repair_active else reports[-1]
    expected_words = int(repair["research_repair_original_words"] or 0)
    if repair_active and _word_count(original_sentences) != expected_words:
        raise RuntimeError(f"{args.qid}: pre-repair word count mismatch")

    query = str(obj["trace"]["metadata"]["query_source"])
    plan = str(obj["trace"]["input"].get("coverage_plan") or "")
    documents = source_documents(path, committed)
    built = build_finish_review_packet(
        query, draft, documents, coverage_plan=plan,
        max_cards=64, max_packet_chars=110_000)
    if built is None:
        raise RuntimeError(f"{args.qid}: no evidence packet")
    packet, packet_stats = built

    system = CONSERVATIVE_SYSTEM if args.mode == "conservative" else ATOMIC_SYSTEM
    provider = OpenAIProvider("openai.gpt-5.6-sol", max_tokens=6_000)
    provider.start(system, [])
    provider.add_user_message(packet)
    turn = provider.run_turn()
    raw = str(turn.get("text") or "")
    revised, errors, notes = _parse_final_prose(
        raw, committed, allow_uncited=True)
    attempts = 1
    if revised is None or _word_count(revised) > 1_024:
        provider.add_user_message(
            "The proposed report failed the submission contract: "
            + "; ".join(errors)
            + ". Correct it now, preserving the draft's coverage and returning "
              "only plain cited prose of at most 1,024 words."
        )
        turn = provider.run_turn()
        raw = str(turn.get("text") or "")
        revised, errors, notes = _parse_final_prose(
            raw, committed, allow_uncited=True)
        attempts = 2

    fallback_reason = ""
    if revised is None:
        revised = original_sentences
        notes = ["fresh synthesis invalid; retained exact original draft"]
        fallback_reason = "invalid"
    original_words = _word_count(original_sentences)
    revised_words = _word_count(revised)
    if original_words <= 1_024 and revised_words < int(0.85 * original_words):
        revised = original_sentences
        notes = ["fresh synthesis shrank below 85%; retained exact original draft"]
        fallback_reason = "coverage"
        revised_words = original_words

    unit_refs, unit_answer = _map_citations(revised, committed)
    references, answer = _collapse_to_docs(unit_refs, unit_answer)
    target_run = f"sol-aus-v2-fresh-{args.mode}-low8-20260806"
    counterfactual = copy.deepcopy(obj)
    counterfactual["metadata"]["run_id"] = target_run
    counterfactual["metadata"]["run_desc"] = (
        f"Fresh {args.mode} synthesis of frozen pre-repair draft from {SOURCE_RUN}."
    )
    counterfactual["references"] = references
    counterfactual["answer"] = answer
    counterfactual["trace"]["summary"]["fresh_synthesis"] = {
        "source_run_id": SOURCE_RUN,
        "mode": args.mode,
        "source_path": str(path),
        "system_prompt": system,
        "user_packet": packet,
        "raw_response": raw,
        "attempts": attempts,
        "packet": packet_stats,
        "original_words": original_words,
        "revision_words": revised_words,
        "fallback_reason": fallback_reason or None,
        "validation_errors": errors,
        "validation_notes": notes,
        "usage": turn.get("usage") or {},
    }
    stamp = path.name.split(".", 1)[0]
    target = OUTPUT_DIR / f"{stamp}.fresh_{args.mode}_counterfactual.output.json"
    target.write_text(
        json.dumps(counterfactual, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "qid": args.qid,
        "mode": args.mode,
        "source": str(path),
        "target": str(target),
        "packet": packet_stats,
        "original_words": original_words,
        "revision_words": revised_words,
        "attempts": attempts,
        "fallback_reason": fallback_reason or None,
        "references": len(references),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
