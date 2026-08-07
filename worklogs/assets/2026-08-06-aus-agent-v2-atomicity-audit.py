#!/usr/bin/env python3
"""Reproduce e89fbe98 closure defects and audit all 30 saved planner outputs.

This script is intentionally offline.  It reads already-saved organizer
artifacts and the reviewed coverage-contract source from the local Git object
database.  It never imports a provider, constructs a search client, or uses the
network.  Loading the reviewed source from Git makes the reproducer stable even
after the working tree receives a fix.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "outputs" / "aus_agent_v2"
RUN_ID = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
REVIEWED_COMMIT = "e89fbe982ac9edf6ee2f30731e120102eff52388"
REVIEWED_SOURCE = "src/systems/aus_agent_v2/coverage_contract.py"

PLAN_ROW_RE = re.compile(
    r"(?ms)^\s*(?P<number>\d+)\.\s*(?P<raw>.*?)"
    r"(?=^\s*\d+\.|\Z)"
)
LABEL_RE = re.compile(
    r"^(?:\*\*)?(?P<label>[A-Z][A-Z _/-]{1,30}):(?:\*\*)?\s*"
)
CLAUSE_BOUNDARY_RE = re.compile(
    r"\s*;\s*|(?<=[.!?])\s+(?=[A-Z0-9])"
)
COORDINATED_DIRECTIVE_RE = re.compile(
    r"(?:,\s*)?\band\s+(?:also\s+)?(?P<verb>"
    r"address|allocate|analyze|assess|avoid|build|check|clarify|compare|"
    r"cover|date-stamp|define|distinguish|document|emphasize|ensure|"
    r"evaluate|examine|explain|flag|give|identify|include|investigate|"
    r"locate|maintain|map|model|normalize|outline|present|prioritize|"
    r"produce|propose|qualify|recommend|record|research|search|select|"
    r"show|specify|state|treat|triangulate|use|verify|write"
    r")\b",
    re.IGNORECASE,
)
LIST_CUE_RE = re.compile(
    r":|\b(?:including|such as|covering|across|especially|namely)\b",
    re.IGNORECASE,
)
LIST_TAIL_RE = re.compile(r"^(?:and|or)\b", re.IGNORECASE)


def git_text(commit: str, path: str) -> str:
    """Read one reviewed file from the local Git object database."""
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def load_reviewed_contract_module() -> types.ModuleType:
    """Execute the exact reviewed module under its real package namespace."""
    source = git_text(REVIEWED_COMMIT, REVIEWED_SOURCE)
    name = "aus_agent_v2._reviewed_e89fbe98_coverage_contract"
    module = types.ModuleType(name)
    module.__file__ = f"git:{REVIEWED_COMMIT}:{REVIEWED_SOURCE}"
    module.__package__ = "aus_agent_v2"
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def reproduce_closure_behaviors() -> list[dict[str, Any]]:
    """Run minimal counterexamples against the exact reviewed implementation."""
    contract = load_reviewed_contract_module()

    def validate(
        name: str,
        items: list[Any],
        ledger: Any,
        arguments: dict[str, Any],
        committed: set[str],
        defect_if_accepted: str,
    ) -> dict[str, Any]:
        answer, errors, stats = contract.validate_submission(
            arguments, items, ledger, committed)
        return {
            "name": name,
            "defect_if_accepted": defect_if_accepted,
            "accepted": answer is not None,
            "projected_answer": answer,
            "errors": errors,
            "stats": stats,
            "arguments": arguments,
        }

    research = [contract.ContractItem(
        "P01", "planner", "evidence", "Compare Alpha and Beta")]
    ledger = contract.EvidenceLedger()
    ledger.record_search(["P01"], "alpha beta")
    ledger.record_supports({
        "P01": [
            contract.EvidenceAnchor(
                "d1", "Alpha contribution", must_include=("Alpha",)),
            contract.EvidenceAnchor(
                "d2", "Beta contribution", must_include=("Beta",)),
        ],
    })
    cases = [validate(
        "compound_one_of_two",
        research,
        ledger,
        {
            "answer_items": [{
                "kind": "prose",
                "text": "Alpha is documented.",
                "evidence_ids": ["d1"],
                "satisfies": ["P01"],
            }],
            "unresolved": [],
        },
        {"d1", "d2"},
        "One mapped anchor closes a row whose second independent claim is absent.",
    )]
    cases.append(validate(
        "supported_but_unresolved",
        research,
        ledger,
        {
            "answer_items": [{
                "kind": "prose",
                "text": "Background context.",
                "evidence_ids": ["d1"],
                "satisfies": [],
            }],
            "unresolved": ["P01"],
        },
        {"d1"},
        "A row with committed mapped support can be discarded as unresolved.",
    ))
    structural = [contract.ContractItem(
        "P01",
        "planner",
        "deliverable",
        "Produce three distinct recommendations",
        must_research=False,
        must_answer=True,
    )]
    cases.append(validate(
        "structural_unresolved",
        structural,
        contract.EvidenceLedger(),
        {
            "answer_items": [{
                "kind": "prose",
                "text": "A generic response.",
                "evidence_ids": [],
                "satisfies": [],
            }],
            "unresolved": ["P01"],
        },
        set(),
        "A request-derived structural obligation can be waived without evidence.",
    ))
    route_errors = contract.validate_support_routes(
        {"P02": [contract.EvidenceAnchor(
            "d1", "Beta contribution", must_include=("Beta",))]},
        [{
            "id": "d1",
            "text": "Alpha and Beta contributions are documented.",
            "metadata": {"for_requirements": ["P01"]},
        }],
    )
    cases.append({
        "name": "cross_route_exact_support",
        "defect_if_rejected": (
            "Exact source-backed support discovered during a P01 search cannot "
            "be mapped to the already-known P02 row."
        ),
        "accepted": not route_errors,
        "errors": route_errors,
        "supports": {
            "P02": {
                "document_id": "d1",
                "claim": "Beta contribution",
                "must_include": ["Beta"],
            },
        },
        "staged_document": {
            "id": "d1",
            "text": "Alpha and Beta contributions are documented.",
            "for_requirements": ["P01"],
        },
    })
    return cases


def load_promoted_rows() -> list[dict[str, Any]]:
    """Select exactly one saved promoted-run artifact for each of 30 topics."""
    by_qid: dict[str, dict[str, Any]] = {}
    for path in sorted(OUTPUT_DIR.glob("*.output.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        metadata = row.get("metadata", {})
        if metadata.get("run_id") != RUN_ID:
            continue
        qid = str(metadata.get("narrative_id") or "")
        if not qid:
            raise RuntimeError(f"missing narrative_id: {path}")
        if qid in by_qid:
            raise RuntimeError(
                f"duplicate promoted-run artifact for {qid}: "
                f"{by_qid[qid]['_path']} and {path}"
            )
        row["_path"] = str(path.relative_to(ROOT))
        by_qid[qid] = row
    if len(by_qid) != 30:
        raise RuntimeError(
            f"expected 30 exact-metadata promoted-run topics, found {len(by_qid)}"
        )
    return [by_qid[qid] for qid in sorted(by_qid)]


def serial_list_parts(clause: str) -> list[str]:
    """Return conservative serial-list parts, or an empty list when ambiguous."""
    parts = [part.strip() for part in clause.split(",") if part.strip()]
    if len(parts) < 3:
        return []
    has_tail = bool(LIST_TAIL_RE.match(parts[-1]))
    if not has_tail and not LIST_CUE_RE.search(clause):
        return []
    return parts


def analyze_plan_row(number: int, raw: str) -> dict[str, Any]:
    """Estimate independent answer units while retaining the exact raw row."""
    raw = raw.rstrip()
    label_match = LABEL_RE.match(raw)
    label = label_match.group("label").strip() if label_match else "UNPARSED"
    body = raw[label_match.end():].strip() if label_match else raw
    base_clauses = [
        clause.strip()
        for clause in CLAUSE_BOUNDARY_RE.split(body)
        if clause.strip()
    ]
    strict_clause_units = 0
    likely_independent_units = 0
    clause_audit: list[dict[str, Any]] = []
    for clause in base_clauses or [body]:
        coordinated = [
            match.group("verb") for match in COORDINATED_DIRECTIVE_RE.finditer(
                clause)
        ]
        strict_units = 1 + len(coordinated)
        list_parts = serial_list_parts(clause)
        likely_units = max(strict_units, len(list_parts) or 1)
        strict_clause_units += strict_units
        likely_independent_units += likely_units
        clause_audit.append({
            "raw": clause,
            "coordinated_directives": coordinated,
            "serial_list_parts": list_parts,
            "strict_clause_units": strict_units,
            "likely_independent_units": likely_units,
        })
    signals: list[str] = []
    if len(base_clauses) > 1:
        signals.append("multiple_sentence_or_semicolon_clauses")
    if any(item["coordinated_directives"] for item in clause_audit):
        signals.append("coordinated_directives")
    if any(item["serial_list_parts"] for item in clause_audit):
        signals.append("serial_list_dimensions")
    return {
        "number": number,
        "label": label,
        "raw": f"{number}. {raw}",
        "body": body,
        "strict_clause_units": strict_clause_units,
        "likely_independent_units": likely_independent_units,
        "compound": likely_independent_units > 1,
        "signals": signals,
        "clauses": clause_audit,
    }


def audit_topics() -> list[dict[str, Any]]:
    """Return the complete topic/row matrix over exact saved planner text."""
    topics: list[dict[str, Any]] = []
    for artifact in load_promoted_rows():
        metadata = artifact["metadata"]
        trace_input = artifact.get("trace", {}).get("input", {})
        # The merged ``coverage_plan`` also contains the independent critic's
        # SCOUT rows.  Those were explicitly prompted to be atomic; the defect
        # under review is that each broad numbered row from the primary planner
        # becomes one Pxx contract item.  Audit the exact isolated planner output
        # and report merged/scout counts separately so the populations cannot be
        # confused.
        plan = str(trace_input.get("coverage_plan_initial") or "")
        merged_plan = str(trace_input.get("coverage_plan") or "")
        merged_rows = list(PLAN_ROW_RE.finditer(merged_plan))
        plan_critic = trace_input.get("plan_critic")
        scout_additions = (
            plan_critic.get("additions", [])
            if isinstance(plan_critic, dict) else []
        )
        rows = [
            analyze_plan_row(int(match.group("number")), match.group("raw"))
            for match in PLAN_ROW_RE.finditer(plan)
        ]
        if not rows:
            raise RuntimeError(
                f"no numbered planner rows for {metadata['narrative_id']}"
            )
        topics.append({
            "qid": metadata["narrative_id"],
            "query": metadata.get("narrative"),
            "source_artifact": artifact["_path"],
            "coverage_plan_initial": plan,
            "merged_plan_row_count": len(merged_rows),
            "structured_scout_additions": len(scout_additions),
            "row_count": len(rows),
            "compound_rows": sum(row["compound"] for row in rows),
            "strict_clause_units": sum(
                row["strict_clause_units"] for row in rows),
            "likely_independent_units": sum(
                row["likely_independent_units"] for row in rows),
            "max_row_units": max(
                row["likely_independent_units"] for row in rows),
            "rows": rows,
        })
    return topics


def recommendation() -> dict[str, Any]:
    """Record the smallest-safe-fix assessment and its explicit tradeoffs."""
    return {
        "choice": "b_candidate_specific_atomic_planner",
        "why": (
            "It reuses the existing isolated planning call, changes only the "
            "ungraded lean candidate, and lets the semantic model distinguish "
            "required answer claims from corroborating sources or descriptive "
            "lists. The harness can then assign one stable id per emitted atom."
        ),
        "options": [
            {
                "option": "a_require_every_committed_anchor",
                "code_size": "smallest",
                "safety": "unsafe",
                "false_positive_tradeoff": (
                    "Anchors are presently alternatives and corroborating "
                    "sources, not declared conjunctive subclaims. Requiring all "
                    "makes duplicate or conflicting evidence mandatory and makes "
                    "closure harder whenever the agent commits more evidence."
                ),
                "word_cap_tradeoff": (
                    "Every extra anchor adds exact terms and possibly another "
                    "citation; one answer item permits only three evidence ids, "
                    "and the whole answer is capped at 1,024 words."
                ),
            },
            {
                "option": "b_candidate_specific_atomic_planner",
                "code_size": "small",
                "safety": "recommended",
                "false_positive_tradeoff": (
                    "A semantic planner can still over-split or omit an atom, "
                    "but a strict JSON schema, one-check-per-row instruction, "
                    "and saved raw output make those failures visible. It avoids "
                    "treating every source list as answer content."
                ),
                "word_cap_tradeoff": (
                    "Emit priority plus a per-row answer-word allowance and cap "
                    "the combined planner/scout must-answer inventory before "
                    "research. A practical candidate should target roughly 18-24 "
                    "answer atoms within a 900-950 word planned budget."
                ),
            },
            {
                "option": "c_separate_compiler",
                "code_size": "largest",
                "safety": "not the smallest safe fix",
                "false_positive_tradeoff": (
                    "A deterministic punctuation compiler cannot reliably tell "
                    "independent criteria from synonyms, examples, source lists, "
                    "or one inseparable comparison. An LLM compiler adds another "
                    "semantic handoff that can alter or drop obligations."
                ),
                "word_cap_tradeoff": (
                    "Mechanical splitting tends to maximize row count; an LLM "
                    "compiler adds tokens, latency, and paid spend before any "
                    "evidence is retrieved."
                ),
            },
        ],
        "minimum_design": {
            "scope": "lean-contract candidate only; confirmed run_one unchanged",
            "planner_output": (
                "JSON rows with kind, one atomic requirement, must_mention, "
                "must_research, must_answer, priority, and answer_word_budget"
            ),
            "invariants": [
                "one independently checkable answer claim or form obligation per row",
                "no row joins independent checks with a serial list or coordinated directive",
                "harness assigns stable ids after schema validation",
                "combined planner/scout answer-word budgets stay at or below 950",
                "every atomic required row closes independently",
            ],
        },
    }


def build_audit() -> dict[str, Any]:
    """Assemble reproduction, complete raw matrix, totals, and recommendation."""
    topics = audit_topics()
    labels = Counter(
        row["label"] for topic in topics for row in topic["rows"])
    total_rows = sum(topic["row_count"] for topic in topics)
    compound_rows = sum(topic["compound_rows"] for topic in topics)
    strict_units = sum(topic["strict_clause_units"] for topic in topics)
    likely_units = sum(topic["likely_independent_units"] for topic in topics)
    return {
        "reviewed_commit": REVIEWED_COMMIT,
        "reviewed_subject": "Add lean executable-contract pipeline",
        "run_id": RUN_ID,
        "offline": True,
        "method": {
            "artifact_selection": (
                "metadata.run_id exact match; exactly one artifact for each of "
                "30 narrative_id values"
            ),
            "plan_population": (
                "trace.input.coverage_plan_initial only. The later merged plan "
                "contains separately prompted atomic SCOUT rows; their counts are "
                "reported per topic but they are not relabeled as planner rows."
            ),
            "raw_rows": (
                "Every numbered coverage-plan row is retained verbatim, including "
                "its number and label markup."
            ),
            "strict_clause_units": (
                "Sentence/semicolon clauses plus a conservative set of explicit "
                "coordinated directive verbs."
            ),
            "likely_independent_units": (
                "Strict clause units, expanded by a transparent serial-list "
                "heuristic when a clause has at least three comma parts and an "
                "Oxford-list tail or explicit list cue. This is an audit signal, "
                "not a semantic ground truth; exact splits are included for review."
            ),
            "compound_row": "likely_independent_units greater than one",
        },
        "reproduction": reproduce_closure_behaviors(),
        "summary": {
            "topics": len(topics),
            "planner_rows": total_rows,
            "compound_rows": compound_rows,
            "compound_row_rate": compound_rows / total_rows,
            "strict_clause_units": strict_units,
            "likely_independent_units": likely_units,
            "likely_units_per_planner_row": likely_units / total_rows,
            "labels": dict(sorted(labels.items())),
        },
        "topics": topics,
        "smallest_safe_fix": recommendation(),
    }


def render_log(audit: dict[str, Any]) -> str:
    """Render a human-readable complete matrix without omitting raw rows."""
    summary = audit["summary"]
    lines = [
        "AUS agent v2 atomicity audit",
        f"reviewed_commit: {audit['reviewed_commit']}",
        f"run_id: {audit['run_id']}",
        "network_or_api_calls: 0",
        "",
        "Reproduce from repository root",
        (
            "PYTHONPATH=src/systems:src uv run --group aus-agent-v2 python "
            "worklogs/assets/2026-08-06-aus-agent-v2-atomicity-audit.py "
            "--format json > "
            "worklogs/assets/2026-08-06-aus-agent-v2-atomicity-audit.json"
        ),
        (
            "PYTHONPATH=src/systems:src uv run --group aus-agent-v2 python "
            "worklogs/assets/2026-08-06-aus-agent-v2-atomicity-audit.py "
            "--format log > "
            "worklogs/assets/2026-08-06-aus-agent-v2-atomicity-audit.log"
        ),
        "",
        "Method",
        f"- plan population: {audit['method']['plan_population']}",
        f"- strict units: {audit['method']['strict_clause_units']}",
        f"- likely units: {audit['method']['likely_independent_units']}",
        f"- compound row: {audit['method']['compound_row']}",
        "",
        "Reproduction against reviewed commit",
    ]
    for case in audit["reproduction"]:
        lines.append(
            f"- {case['name']}: accepted={case['accepted']} "
            f"errors={json.dumps(case.get('errors', []), ensure_ascii=False)}"
        )
    lines.extend([
        "",
        "Aggregate",
        f"- topics: {summary['topics']}",
        f"- planner rows: {summary['planner_rows']}",
        f"- compound rows: {summary['compound_rows']} "
        f"({summary['compound_row_rate']:.1%})",
        f"- strict clause units: {summary['strict_clause_units']}",
        f"- likely independent units: {summary['likely_independent_units']}",
        f"- likely units/planner row: "
        f"{summary['likely_units_per_planner_row']:.2f}",
        "- labels: " + json.dumps(summary["labels"], sort_keys=True),
        "",
        "Per-topic matrix",
        "qid\trows\tcompound\tstrict_units\tlikely_units\tmax_row_units\tsource",
    ])
    for topic in audit["topics"]:
        lines.append(
            f"{topic['qid']}\t{topic['row_count']}\t"
            f"{topic['compound_rows']}\t{topic['strict_clause_units']}\t"
            f"{topic['likely_independent_units']}\t{topic['max_row_units']}\t"
            f"{topic['source_artifact']}"
        )
    lines.extend(["", "Complete exact planner rows and heuristic splits"])
    for topic in audit["topics"]:
        lines.extend([
            "",
            f"=== {topic['qid']} ===",
            f"query: {topic['query']}",
            f"source: {topic['source_artifact']}",
        ])
        for row in topic["rows"]:
            lines.append(row["raw"])
            lines.append(
                "  audit: "
                f"compound={row['compound']} "
                f"strict={row['strict_clause_units']} "
                f"likely={row['likely_independent_units']} "
                f"signals={','.join(row['signals']) or '-'}"
            )
            for index, clause in enumerate(row["clauses"], 1):
                lines.append(
                    f"  clause {index}: {clause['raw']}"
                )
                if clause["serial_list_parts"]:
                    for part_index, part in enumerate(
                        clause["serial_list_parts"], 1
                    ):
                        lines.append(f"    list {part_index}: {part}")
                if clause["coordinated_directives"]:
                    lines.append(
                        "    coordinated directives: "
                        + ", ".join(clause["coordinated_directives"])
                    )
    fix = audit["smallest_safe_fix"]
    lines.extend([
        "",
        "Smallest safe fix assessment",
        f"choice: {fix['choice']}",
        f"why: {fix['why']}",
    ])
    for option in fix["options"]:
        lines.extend([
            f"- {option['option']} [{option['safety']}; "
            f"code_size={option['code_size']}]",
            f"  false-positive tradeoff: {option['false_positive_tradeoff']}",
            f"  word-cap tradeoff: {option['word_cap_tradeoff']}",
        ])
    return "\n".join(lines) + "\n"


def main() -> None:
    """Emit either the machine-readable audit or the complete readable log."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("json", "log"), default="log")
    args = parser.parse_args()
    audit = build_audit()
    if args.format == "json":
        print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_log(audit), end="")


if __name__ == "__main__":
    main()
