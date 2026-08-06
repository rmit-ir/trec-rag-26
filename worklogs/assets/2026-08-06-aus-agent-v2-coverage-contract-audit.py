#!/usr/bin/env python3
"""Audit the executable contract against the saved 30-topic winner.

This is deliberately offline: it reads organizer outputs already on disk and
never constructs a provider or search client.  The full topic matrix is meant
to survive in the paired ``.log`` asset rather than in a session transcript.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

from aus_agent_v2.answer_form import infer_answer_form_policy
from aus_agent_v2.coverage_contract import build_coverage_contract


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "outputs" / "aus_agent_v2"
RUN_ID = "sol-aus-v2-research-first-pre-repair-dev30-20260806"

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_()+.-]*")
CODE_RE = re.compile(
    r"\b(?:include|provide|write|show)\s+(?:[A-Za-z-]+\s+){0,3}"
    r"(?:python\s+)?code\b|\bcode\s+for\b",
    re.IGNORECASE,
)
SERIES_RE = re.compile(r"\bseries\s+of\s+(?:blog\s+)?posts\b", re.IGNORECASE)
TABLE_RE = re.compile(r"\btable\b|\btabular\b", re.IGNORECASE)
SECTION_RE = re.compile(r"\bsections?\b", re.IGNORECASE)
STOP = {
    "a", "about", "all", "an", "and", "answer", "as", "at", "be",
    "by", "cover", "describe", "discuss", "explain", "for", "from",
    "give", "in", "include", "into", "is", "it", "its", "of", "on",
    "or", "provide", "report", "response", "should", "state", "such",
    "that", "the", "their", "these", "this", "to", "use", "using",
    "with", "without", "write",
}


def tokens(text: str) -> set[str]:
    """Return content-bearing lexical units for a conservative carryover check."""
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text)
        if len(token) > 2 and token.casefold() not in STOP
    }


def load_rows() -> list[dict]:
    """Select exactly one completed organizer artifact per development topic."""
    by_qid: dict[str, dict] = {}
    for path in sorted(OUTPUT_DIR.glob("*.output.json")):
        try:
            row = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        metadata = row.get("metadata", {})
        if metadata.get("run_id") != RUN_ID:
            continue
        qid = str(metadata.get("narrative_id") or "")
        if qid in by_qid:
            raise RuntimeError(f"duplicate topic {qid}: {path}")
        row["_path"] = str(path.relative_to(ROOT))
        by_qid[qid] = row
    if len(by_qid) != 30:
        raise RuntimeError(f"expected 30 topics, found {len(by_qid)}")
    return [by_qid[qid] for qid in sorted(by_qid)]


def main() -> None:
    """Print a complete Markdown matrix plus reproducible aggregate findings."""
    rows = load_rows()
    matrix: list[dict] = []
    kinds: Counter[str] = Counter()
    for row in rows:
        metadata = row["metadata"]
        trace = row.get("trace", {})
        plan = str(trace.get("input", {}).get("coverage_plan") or "")
        additions = trace.get("summary", {}).get("plan_critic", {}).get(
            "additions", [])
        narrative = str(metadata.get("narrative") or "")
        answer_form = infer_answer_form_policy(narrative)
        contract = build_coverage_contract(
            plan, additions, answer_form=answer_form)
        kinds.update(item.kind for item in contract)
        answer_text = "\n".join(
            str(item.get("text") or "") for item in row.get("answer", [])
        )
        answer_terms = tokens(answer_text)
        recalls = []
        for item in contract:
            needed = tokens(item.requirement)
            if needed:
                recalls.append(len(needed & answer_terms) / len(needed))
        exact = [term for item in contract for term in item.must_mention]
        exact_present = sum(term.casefold() in answer_text.casefold() for term in exact)
        cues = []
        if CODE_RE.search(narrative):
            cues.append("code")
        if SERIES_RE.search(narrative):
            cues.append("series")
        if TABLE_RE.search(narrative):
            cues.append("table")
        if SECTION_RE.search(narrative):
            cues.append("section")
        matrix.append({
            "qid": metadata["narrative_id"],
            "cues": ",".join(cues) or "-",
            "items": len(contract),
            "answer": sum(item.must_answer for item in contract),
            "research": sum(item.must_research for item in contract),
            "structural": sum(not item.must_research for item in contract),
            "exact": len(exact),
            "exact_present": exact_present,
            "lex50": sum(value >= 0.5 for value in recalls),
            "lexn": len(recalls),
            "words": len(answer_text.split()),
            "path": row["_path"],
        })

    print(f"run_id: {RUN_ID}")
    print(f"topics: {len(matrix)}")
    print()
    print("| qid | request cues | rows | must answer | must research | structural | exact present | requirement lexical ≥.50 | answer words |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for item in matrix:
        print(
            f"| `{item['qid']}` | {item['cues']} | {item['items']} | "
            f"{item['answer']} | {item['research']} | {item['structural']} | "
            f"{item['exact_present']}/{item['exact']} | "
            f"{item['lex50']}/{item['lexn']} | {item['words']} |"
        )

    print()
    print("Aggregate")
    for key in ("items", "answer", "research", "structural", "words"):
        values = [item[key] for item in matrix]
        print(
            f"- {key}: min={min(values)}, median={statistics.median(values):g}, "
            f"mean={statistics.mean(values):.2f}, max={max(values)}"
        )
    total_exact = sum(item["exact"] for item in matrix)
    present_exact = sum(item["exact_present"] for item in matrix)
    total_lex = sum(item["lexn"] for item in matrix)
    present_lex = sum(item["lex50"] for item in matrix)
    print(f"- exact-term carryover: {present_exact}/{total_exact}")
    print(f"- requirement lexical carryover ≥.50: {present_lex}/{total_lex}")
    print("- request cues: " + ", ".join(
        f"{name}={sum(name in item['cues'].split(',') for item in matrix)}"
        for name in ("code", "series", "table", "section")
    ))
    print("- contract kinds: " + ", ".join(
        f"{name}={count}" for name, count in sorted(kinds.items())
    ))
    print()
    print("Source artifacts")
    for item in matrix:
        print(f"- `{item['qid']}`: `{item['path']}`")
    print()
    print("Exact offline audit inputs (JSONL)")
    for row in rows:
        trace = row.get("trace", {})
        print(json.dumps({
            "qid": row["metadata"]["narrative_id"],
            "query": row["metadata"]["narrative"],
            "coverage_plan": trace.get("input", {}).get("coverage_plan"),
            "scout_additions": trace.get("summary", {}).get(
                "plan_critic", {}).get("additions", []),
            "answer": row.get("answer", []),
        }, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
