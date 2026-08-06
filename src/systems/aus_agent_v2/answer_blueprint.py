"""Evidence-to-answer handoff for the final research turn.

Commit-time fact extraction is useful only if the writer sees those facts when
it decides what to say.  This module makes that handoff explicit: the research
model must map request requirements to complete intended claims and committed
unit ids, then the harness replays that normalized map, the coverage plan, and
the selected fact cards at the tail of the conversation immediately before the
answer turn.

The handoff is deliberately not an answer rewriter.  It cannot add evidence,
alter citations, or emit submission prose; it only turns already-committed
state into a compact, recency-anchored writing checklist.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from aus_agent.tools import COMMIT_CONTEXT_TOOL

from .finish_review import FactLedger


def commit_context_tool_with_facts() -> dict[str, Any]:
    """Return a v2-local commit schema that captures source-grounded facts.

    The original system remains untouched.  Fact cards are optional because a
    document can be worth retaining for context even when the model cannot
    reduce it safely to a compact claim/value record.
    """
    tool = copy.deepcopy(COMMIT_CONTEXT_TOOL)
    item = tool["input_schema"]["properties"]["documents"]["items"]
    item["properties"]["facts"] = {
        "type": "array",
        "description": (
            "Zero to five concrete facts from this result that may be used in "
            "the final answer. Extract while the source text is visible. Each "
            "card must preserve the source's value, scope, and attribution; "
            "do not infer or generalize beyond the result."
        ),
        "maxItems": 5,
        "items": {
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "What the fact establishes.",
                },
                "value": {
                    "type": "string",
                    "description": (
                        "The concrete finding, figure, date, definition, or "
                        "comparison stated by the source."
                    ),
                },
                "scope": {
                    "type": "string",
                    "description": (
                        "Population, jurisdiction, period, conditions, or "
                        "other boundary on the finding."
                    ),
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Named study, institution, author, or publication "
                        "when the result identifies one."
                    ),
                },
            },
            "required": ["claim", "value"],
        },
    }
    return tool


PREPARE_ANSWER_TOOL: dict[str, Any] = {
    "name": "prepare_answer",
    "description": (
        "Create the evidence-backed writing blueprint immediately before the "
        "final report. Call only after research is complete and no staged "
        "batch remains. Map every material request or plan requirement to one "
        "or more complete intended claims, and attach only exact ids already "
        "committed. A complete claim includes the value or finding and its "
        "scope rather than a topic label. This is a required handoff when the "
        "tool is available; write the report on the following turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement": {
                            "type": "string",
                            "description": (
                                "The explicit or implied request requirement "
                                "this part of the answer must satisfy."
                            ),
                        },
                        "claims": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "claim": {
                                        "type": "string",
                                        "description": (
                                            "A complete sentence-level point "
                                            "including its finding/value and "
                                            "scope; not a topic label."
                                        ),
                                    },
                                    "evidence_ids": {
                                        "type": "array",
                                        "minItems": 1,
                                        "maxItems": 3,
                                        "items": {"type": "string"},
                                        "description": (
                                            "Exact committed unit ids that "
                                            "directly support this claim."
                                        ),
                                    },
                                },
                                "required": ["claim", "evidence_ids"],
                            },
                        },
                    },
                    "required": ["requirement", "claims"],
                },
            },
            "unresolved": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string"},
                "description": (
                    "Material requirements that the committed evidence cannot "
                    "establish and therefore must be omitted or narrowly "
                    "qualified."
                ),
            },
        },
        "required": ["requirements", "unresolved"],
    },
}


def normalize_answer_blueprint(
    arguments: dict[str, Any],
    committed_ids: set[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate and normalize a blueprint against harness-owned evidence ids."""
    errors: list[str] = []
    raw_requirements = arguments.get("requirements")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        return None, ["requirements must be a non-empty array"]

    requirements: list[dict[str, Any]] = []
    for req_index, raw_requirement in enumerate(raw_requirements[:16], 1):
        if not isinstance(raw_requirement, dict):
            errors.append(f"requirement {req_index} is not an object")
            continue
        requirement = " ".join(
            str(raw_requirement.get("requirement") or "").split())
        raw_claims = raw_requirement.get("claims")
        if not requirement:
            errors.append(f"requirement {req_index} has no text")
        if not isinstance(raw_claims, list) or not raw_claims:
            errors.append(f"requirement {req_index} has no claims")
            continue
        claims: list[dict[str, Any]] = []
        for claim_index, raw_claim in enumerate(raw_claims[:4], 1):
            if not isinstance(raw_claim, dict):
                errors.append(
                    f"requirement {req_index} claim {claim_index} is not an object")
                continue
            claim = " ".join(str(raw_claim.get("claim") or "").split())
            raw_ids = raw_claim.get("evidence_ids")
            if not claim:
                errors.append(
                    f"requirement {req_index} claim {claim_index} has no text")
            if not isinstance(raw_ids, list) or not raw_ids:
                errors.append(
                    f"requirement {req_index} claim {claim_index} has no evidence_ids")
                continue
            evidence_ids: list[str] = []
            for value in raw_ids[:3]:
                unit_id = str(value).strip()
                if not unit_id or unit_id in evidence_ids:
                    continue
                if unit_id not in committed_ids:
                    errors.append(
                        f"uncommitted evidence id {unit_id!r} in requirement "
                        f"{req_index} claim {claim_index}")
                    continue
                evidence_ids.append(unit_id)
            if claim and evidence_ids:
                claims.append({"claim": claim, "evidence_ids": evidence_ids})
        if requirement and claims:
            requirements.append({"requirement": requirement, "claims": claims})

    raw_unresolved = arguments.get("unresolved", [])
    if not isinstance(raw_unresolved, list):
        errors.append("unresolved must be an array")
        unresolved: list[str] = []
    else:
        unresolved = []
        for value in raw_unresolved[:8]:
            item = " ".join(str(value).split())
            if item and item not in unresolved:
                unresolved.append(item)

    if errors or not requirements:
        if not requirements and not errors:
            errors.append("blueprint contains no valid requirements")
        return None, errors
    return {"requirements": requirements, "unresolved": unresolved}, []


def build_answer_handoff(
    query: str,
    coverage_plan: str,
    blueprint: dict[str, Any],
    facts: FactLedger,
) -> str:
    """Render a bounded, citation-safe handoff as the final tool result."""
    used_ids = {
        unit_id
        for requirement in blueprint["requirements"]
        for claim in requirement["claims"]
        for unit_id in claim["evidence_ids"]
    }
    lines = [
        "ANSWER BLUEPRINT ACCEPTED.",
        "Use this as a coverage and evidence checklist, not as the report's "
        "layout. On the next turn write only the requested plain cited prose. "
        "Finish each selected claim with its value/finding and scope, preserve "
        "all material requested parts, and cite only its mapped ids.",
        "",
        "ORIGINAL REQUEST",
        query.strip(),
    ]
    if coverage_plan.strip():
        lines.extend(["", "PRE-RESEARCH COVERAGE PLAN", coverage_plan.strip()])
    lines.extend(["", "NORMALIZED CLAIM MAP"])
    for index, requirement in enumerate(blueprint["requirements"], 1):
        lines.append(f"{index}. REQUIREMENT: {requirement['requirement']}")
        for claim in requirement["claims"]:
            citations = " ".join(f"[{unit_id}]" for unit_id in claim["evidence_ids"])
            lines.append(f"   CLAIM: {claim['claim']} EVIDENCE: {citations}")
    if blueprint["unresolved"]:
        lines.extend(["", "UNRESOLVED — OMIT OR QUALIFY NARROWLY"])
        lines.extend(f"- {item}" for item in blueprint["unresolved"])

    selected_facts = {
        unit_id: facts[unit_id]
        for unit_id in sorted(used_ids)
        if facts.get(unit_id)
    }
    if selected_facts:
        lines.extend([
            "",
            "COMMIT-TIME FACT CARDS FOR MAPPED EVIDENCE",
            json.dumps(selected_facts, ensure_ascii=False, separators=(",", ":")),
        ])
    return "\n".join(lines)


def answer_blueprint_request(coverage_plan: str) -> str:
    """Prompt emitted when the model first tries to answer without the handoff."""
    anchor = (
        " Re-read the pre-research coverage plan already in this conversation "
        "and map every material item."
        if coverage_plan.strip() else
        " Infer the explicit and implied requirements from the request."
    )
    return (
        "Research is complete, but the required evidence-to-answer handoff has "
        "not been made. Do not write or revise the report yet. Call "
        "prepare_answer now with complete intended claims and exact committed "
        "evidence ids; put unsupported material in unresolved."
        + anchor
        + " The harness will replay the normalized blueprint and fact cards, "
          "then you will write the report on the following turn."
    )
