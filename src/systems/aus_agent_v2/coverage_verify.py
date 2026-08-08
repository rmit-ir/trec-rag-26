"""Fresh-context coverage verification for a completed research draft.

The planner can identify a requirement and the research loop can retrieve its
evidence, yet a long-context drafting turn may still omit it. This stage reads
only the request, the compact plan, and the draft. It diagnoses material
omissions; the research conversation, which still owns the committed evidence,
performs at most one repair turn.
"""
from __future__ import annotations

import json
from typing import Any


COVERAGE_VERIFY_SYSTEM = """\
You are the independent coverage verifier between a cited research draft and
final acceptance. Compare the draft with the original request and the numbered
pre-research plan. Do not answer the request, rewrite prose, judge citation
support, or invent facts. You may check whether a citation marker is present;
do not decide whether the cited source actually entails the sentence.

A requirement counts as covered only when the draft states it concretely. A
related topic, generic synonym, or plan intention is not enough. Prioritize:
- penalty prevention before optional coverage: flag any uncited sentence that
  generalizes a health, safety, medical, legal, or causal outcome across a
  population, even when it is a synthesis or takeaway sentence;
- every explicit requested component and required deliverable form;
- an element the user requires in every repeated post, example, or section;
- named safety, legal, temporal, or jurisdictional constraints;
- concrete prior studies, measurements, comparisons, or examples the plan
  marked necessary to establish context;
- definitions needed by the stated audience.

A sentence saying that no exact study was established does not cover a plan
item requiring prior measured context. When the draft contains any related
measurement, require it to name the closest credible precedent and state the
population, outcome, or scope mismatch rather than leaving the context empty.

Internal plan labels and word allocations are not visible-format requirements.
The organizer accepts plain prose sentences; never demand headings, section
labels, tables, bullets, or numbering unless the original request explicitly
requires that presentation.

Rank gaps by expected coverage gained per answer word and by whether the live
research context can repair them with evidence it likely already owns. Prefer
missing per-part structure, definitions, comparisons, and decisive evidence
over replacing already-valid examples, diversifying sources for its own sake,
or chasing a missing archive code. Do not require changing selected cases or
finding new provenance unless the original request explicitly makes that
particular identity or mix mandatory.

Preserve the requirement's exact evidence type; never weaken it into an
alternative. A model-performance metric is not a prevalence rate, incidence is
not prevalence, a date range is not a measured result, a generic example is not
a named case study, and covering an element in one post does not cover a demand
that it appear in every post. When a quantitative result is required, specify
that its value, population or sample, and time/scope are missing.

Do not demand optional breadth or every suggestion in an otherwise complete
plan. Return JSON only in exactly one of these shapes:
{"verdict":"pass","missing":[]}
{"verdict":"repair","missing":[{"plan_item":10,"requirement":"short concrete requirement","draft_gap":"what is absent or only generic"}]}

List at most four material gaps, ordered by importance. Use a null plan_item
only for an explicit user requirement absent from the plan.
"""

COVERAGE_REPAIR_PREAMBLE = """\
Your first valid draft is not accepted yet. A fresh-context coverage verifier
found the material omissions below. Revise the COMPLETE draft once in this
conversation, using only evidence already committed or new evidence you
retrieve. Preserve the supported coverage already present. Repair every finding
concretely; use the actual name, comparison, measurement, example, or limitation
the requirement calls for rather than generic adjacent language. Preserve the
exact evidence type: for example, a requested prevalence result needs a
numerical prevalence value with its population and time/scope, not an NLP
accuracy metric or merely the name of a prevalence study. You may use at most one parallel search batch for all findings; prioritize existing committed
evidence and synthesis over exhaustive retrieval. If the evidence is
unavailable, state that precise limitation instead of inventing. Return only
the full cited report in plain prose, one sentence per line, at no more than
1,024 words.
"""

MAX_VERIFY_PACKET_CHARS = 30_000
MAX_AUDIT_ITEMS = 4


def coverage_verify_request(query: str, plan: str, draft: str) -> str:
    """Build the small isolated context that makes omissions salient again."""
    packet = (
        "ORIGINAL RESEARCH REQUEST\n\n"
        + query.strip()
        + "\n\nPRE-RESEARCH COVERAGE PLAN\n\n"
        + plan.strip()
        + "\n\nCITED DRAFT TO VERIFY\n\n"
        + draft.strip()
    )
    return packet[:MAX_VERIFY_PACKET_CHARS].rstrip()


def _json_object(text: str | None) -> dict[str, Any] | None:
    candidate = (text or "").strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_coverage_audit(text: str | None) -> dict[str, Any]:
    """Fail closed to no repair when an auxiliary verifier breaks contract.

    A malformed verifier must never trap a valid report in a correction loop.
    The raw response remains in the trace for diagnosis.
    """
    parsed = _json_object(text)
    if parsed is None or set(parsed) != {"verdict", "missing"}:
        return {"verdict": "pass", "missing": [], "parse_error": True}
    verdict = parsed.get("verdict")
    missing = parsed.get("missing")
    if verdict not in {"pass", "repair"} or not isinstance(missing, list):
        return {"verdict": "pass", "missing": [], "parse_error": True}

    clean: list[dict[str, Any]] = []
    for item in missing[:MAX_AUDIT_ITEMS]:
        if not isinstance(item, dict) or set(item) != {
                "plan_item", "requirement", "draft_gap"}:
            continue
        plan_item = item["plan_item"]
        if plan_item is not None and not isinstance(plan_item, int):
            continue
        requirement = str(item["requirement"]).strip()
        draft_gap = str(item["draft_gap"]).strip()
        if requirement and draft_gap:
            clean.append({
                "plan_item": plan_item,
                "requirement": requirement[:500],
                "draft_gap": draft_gap[:500],
            })
    if verdict == "pass" or not clean:
        return {"verdict": "pass", "missing": []}
    return {"verdict": "repair", "missing": clean}


def coverage_repair_request(audit: dict[str, Any], plan: str) -> str:
    """Replay diagnosed obligations to the evidence-owning research context."""
    findings = []
    for item in audit.get("missing", []):
        label = (
            f"plan item {item['plan_item']}"
            if item.get("plan_item") is not None else "original request"
        )
        findings.append(
            f"- {label}: {item['requirement']} — gap: {item['draft_gap']}"
        )
    return (
        COVERAGE_REPAIR_PREAMBLE
        + "\nMATERIAL COVERAGE FINDINGS\n"
        + "\n".join(findings)
        + "\n\nPLAN REPLAY\n"
        + plan.strip()
    )
