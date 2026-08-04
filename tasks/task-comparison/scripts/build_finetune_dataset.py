#!/usr/bin/env python3
"""Derive a single embedding fine-tuning file from aus_agent run artifacts.

The strict ``trajectory.json`` keeps ``returned``/``returned_docids`` at PARENT
docid granularity because that is the organizer-facing contract. The retrieval
unit the engine actually scored is the chunk (``<docid>_p<chunk>``), and its
text is present but buried inside the ``output`` string of each tool call.

This script lifts both back out into ONE new JSONL side-car. The source
``trajectory.json``/``output.json`` are never modified or rewritten -- they
stay byte-identical to the run artifacts.

One row per search call::

    {run_id, engine, query_id, topic, call_index,
     search_query, k,
     results: [{id, docid, chunk, rank, score, label, reason,
                prefix_chars, text, commit_reason?}, ...],
     n_positive, n_negative, n_unjudged}

``results`` stays in engine rank order. Labels come from the agent's own commit
ledger, but the raw ledger is NOT a clean positive/negative split -- see
``classify``.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
from typing import Any

# Chunks after the first carry a literal "Page N of document: <title>\n\n"
# prefix inside their text (chunker `title_chunks=1`). It is layout metadata
# that leaked into content; we report its length rather than shipping a second
# stripped copy of every passage, so callers can do text[prefix_chars:].
PAGE_PREFIX = re.compile(r"^Page \d+ of document: [^\n]*\n\n")

# The tool output string ends with a human-readable budget footer that is not
# part of the JSON payload.
BUDGET_FOOTER = "\n[context budget"

# Rejection reasons that are NOT a judgement of irrelevance.
DUPLICATE_MARK = "duplicate/already committed"
EXPIRED_MARK = "staged batch expired after invalid commit_context"


def parse_tool_output(raw: str) -> dict[str, Any] | None:
    """Strip the budget footer and decode a tool output payload."""
    cut = raw.rfind(BUDGET_FOOTER)
    if cut >= 0:
        raw = raw[:cut]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def split_unit_id(unit_id: str) -> tuple[str, int | None]:
    """``shard_1_2_p4`` -> ``("shard_1_2", 4)``. Rows are pure digits, so the
    final ``_p`` split is unambiguous."""
    parent, sep, page = unit_id.rpartition("_p")
    if sep and page.isdigit():
        return parent, int(page)
    return unit_id, None


def prefix_chars(text: str) -> int:
    match = PAGE_PREFIX.match(text or "")
    return match.end() if match else 0


def classify(unit_id: str, committed: set[str],
             reasons: dict[str, list[str]]) -> tuple[str, str]:
    """Resolve one retrieved chunk to a training label.

    The ledger's ``rejected`` list is not the same thing as "the agent judged
    this irrelevant". Three cases have to be pulled apart or the negatives get
    poisoned:

    * committed anywhere in the topic -> positive, even if some other step also
      listed it as rejected (it is re-staged whenever a later search returns
      it again).
    * rejected as a duplicate of something already committed -> positive.
    * rejected because the whole staged batch was voided by a failed
      commit_context call -> no judgement was ever made -> unjudged.
    """
    if unit_id in committed:
        return "positive", "committed"
    unit_reasons = reasons.get(unit_id, [])
    if any(DUPLICATE_MARK in reason for reason in unit_reasons):
        return "positive", "duplicate of committed"
    if not unit_reasons:
        return "unjudged", "never reached a commit decision"
    judged = [r for r in unit_reasons if EXPIRED_MARK not in r]
    if not judged:
        return "unjudged", "staged batch voided by a failed commit_context"
    return "negative", judged[0]


def read_ledger(items: list[dict[str, Any]]) -> tuple[
        set[str], dict[str, str], dict[str, list[str]]]:
    """Collect committed ids, the agent's stated commit reason per id, and
    every rejection reason seen per id, across the whole topic."""
    committed: set[str] = set()
    commit_reasons: dict[str, str] = {}
    reject_reasons: dict[str, list[str]] = collections.defaultdict(list)
    for item in items:
        if item.get("tool_name") != "commit_context":
            continue
        payload = parse_tool_output(item.get("output") or "")
        if payload:
            committed.update(str(x) for x in payload.get("committed", []))
            for entry in payload.get("rejected", []):
                # NB: the ledger calls this key "docid" but it holds a unit id.
                reject_reasons[str(entry.get("docid"))].append(
                    str(entry.get("reason", "")))
        # The model's own justification per committed chunk lives in the call
        # arguments -- a free relevance rationale worth keeping.
        try:
            args = json.loads(item.get("arguments") or "{}")
        except json.JSONDecodeError:
            continue
        for doc in args.get("documents", []) or []:
            if isinstance(doc, dict) and doc.get("id"):
                commit_reasons.setdefault(str(doc["id"]),
                                          str(doc.get("reason", "")))
    return committed, commit_reasons, dict(reject_reasons)


def rows_for(path: pathlib.Path) -> list[dict[str, Any]]:
    """One row per search call in a single topic's trajectory."""
    traj = json.loads(path.read_text())
    items = [i for i in traj.get("result", []) if i.get("type") == "tool_call"]
    committed, commit_reasons, reject_reasons = read_ledger(items)

    metadata = traj.get("metadata", {})
    engines = metadata.get("engines") or []
    rows: list[dict[str, Any]] = []
    call_index = 0

    for item in items:
        if item.get("tool_name") != "search":
            continue
        payload = parse_tool_output(item.get("output") or "")
        call_index += 1
        if not payload:
            continue

        results = []
        counts: collections.Counter = collections.Counter()
        for hit in payload.get("results", []):
            unit_id = str(hit.get("id", ""))
            parent, chunk = split_unit_id(unit_id)
            text = hit.get("text") or ""
            label, reason = classify(unit_id, committed, reject_reasons)
            counts[label] += 1
            result = {
                "id": unit_id,
                "docid": str(hit.get("docid", parent)),
                "chunk": chunk,
                "rank": hit.get("rank"),
                "score": hit.get("score"),
                "label": label,
                "reason": reason,
                "prefix_chars": prefix_chars(text),
                "text": text,
            }
            if label == "positive" and commit_reasons.get(unit_id):
                result["commit_reason"] = commit_reasons[unit_id]
            results.append(result)
        if not results:
            continue

        rows.append({
            "run_id": metadata.get("run_id"),
            # The engine actually used for THIS call; the run-level arm is
            # single-engine, but the call carries its own field.
            "engine": payload.get("engine")
                      or (engines[0] if len(engines) == 1 else engines),
            "query_id": traj.get("query_id"),
            "topic": metadata.get("query_source"),
            "call_index": call_index,
            "search_query": payload.get("query"),
            "k": payload.get("k"),
            "n_positive": counts["positive"],
            "n_negative": counts["negative"],
            "n_unjudged": counts["unjudged"],
            "results": results,
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, type=pathlib.Path,
                    help="bundle dir holding <arm>/*.trajectory.json")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="destination .jsonl (single file, all arms)")
    args = ap.parse_args()

    paths = sorted(args.src.glob("*/*.trajectory.json"))
    if not paths:
        print(f"no trajectories under {args.src}", file=sys.stderr)
        return 1

    totals: collections.Counter = collections.Counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as out:
        for path in paths:
            for row in rows_for(path):
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                totals["rows"] += 1
                totals["positive"] += row["n_positive"]
                totals["negative"] += row["n_negative"]
                totals["unjudged"] += row["n_unjudged"]
                if row["n_positive"] and row["n_negative"]:
                    totals["rows_with_both"] += 1
        totals["topics"] = len(paths)

    print(f"{args.out}: " + "  ".join(
        f"{k}={v}" for k, v in sorted(totals.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
