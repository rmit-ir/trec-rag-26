"""The independent plan challenge stays additive, structured, and bounded."""
from __future__ import annotations

import json

from aus_agent_v2.plan_critic import (
    PLAN_CRITIC_SYSTEM,
    merge_plan_critique,
    normalize_plan_critique,
    plan_critic_request,
)


def test_request_contains_only_the_original_request() -> None:
    """The first plan, a hidden rubric, or retrieval would anchor independent recall."""
    packet = plan_critic_request("Compare A and B.")

    assert packet == (
        "ORIGINAL RESEARCH REQUEST\n\nCompare A and B."
    )


def test_normalizer_rejects_malformed_or_unbounded_findings() -> None:
    """Unstructured criticism must not enter the research context as instructions."""
    assert normalize_plan_critique("not JSON")["parse_error"] is True
    raw = json.dumps({
        "verdict": "add",
        "additions": [{
            "requirement": f"requirement {index}",
            "reason": "material",
            "search_leads": ["one", "two", "three", "four"],
        } for index in range(8)],
    })

    audit = normalize_plan_critique(raw)

    assert len(audit["additions"]) == 8
    assert all(len(item["search_leads"]) == 1 for item in audit["additions"])


def test_merge_appends_numbered_requirements_without_rewriting_plan() -> None:
    """The critic closes omissions but never receives authority to delete coverage."""
    plan = "1. DELIVERABLE: report.\n2. EVIDENCE: primary sources."
    audit = {
        "verdict": "add",
        "additions": [{
            "requirement": "Define the standard failure mechanism.",
            "reason": "The requested guarantee otherwise lacks a boundary case.",
            "search_leads": ["standard failure mechanism primary source"],
        }],
    }

    merged = merge_plan_critique(plan, audit)

    assert merged.startswith(plan)
    assert "3. SCOUT: Define the standard failure mechanism." in merged
    assert "WHY:" not in merged
    assert "SEARCH: standard failure mechanism primary source" in merged


def test_prompt_demands_canonical_terms_but_forbids_answering() -> None:
    """The second context should discover scope, not become an ungrounded expert."""
    assert "canonical concepts and terminology" in PLAN_CRITIC_SYSTEM
    assert "Coverage diversity comes before depth" in PLAN_CRITIC_SYSTEM
    assert "Do not propose fewer parts" in PLAN_CRITIC_SYSTEM
    assert "Do not answer the request" in PLAN_CRITIC_SYSTEM
    assert "at most twelve additions" in PLAN_CRITIC_SYSTEM
    assert "A novice research guide" in PLAN_CRITIC_SYSTEM
    assert "A board strategy" in PLAN_CRITIC_SYSTEM
    assert "A society-wide judgment" in PLAN_CRITIC_SYSTEM
    assert "intelligence-feedback dynamics" in PLAN_CRITIC_SYSTEM
    assert "prior measurement that studies that combination" in " ".join(
        PLAN_CRITIC_SYSTEM.split())
    assert "one `safety` obligation" in PLAN_CRITIC_SYSTEM
    assert "one `penalty`" in PLAN_CRITIC_SYSTEM


def test_normalizer_preserves_atomic_exact_terms() -> None:
    """A named obligation cannot survive only as a disposable search hint."""
    audit = normalize_plan_critique(json.dumps({
        "verdict": "add",
        "additions": [{
            "kind": "safety",
            "requirement": "Name the governing health-privacy rule.",
            "must_mention": ["HIPAA"],
            "reason": "Generic privacy language misses the applicable rule.",
            "search_leads": ["HIPAA de-identified EHR research"],
        }],
    }))

    assert audit["additions"][0]["kind"] == "safety"
    assert audit["additions"][0]["must_mention"] == ["HIPAA"]
    assert "EXACT: HIPAA" in merge_plan_critique("1. CORE: explain.", audit)


def test_merge_drops_a_whole_finding_instead_of_cutting_its_sentence() -> None:
    """A raw word slice can turn a search lead into a corrupt instruction."""
    plan = "1. DELIVERABLE: concise report."
    audit = {"additions": [{
        "requirement": "Define the complete standard mechanism clearly.",
        "reason": "material",
        "search_leads": ["standard mechanism authoritative source"],
    }]}

    merged = merge_plan_critique(plan, audit, max_words=6)

    assert merged == plan


def test_compact_merge_drops_search_scaffolding_but_keeps_obligations() -> None:
    """Retrieval phrasing must not crowd evaluator-visible requirements out."""
    audit = {
        "verdict": "add",
        "additions": [{
            "kind": "term",
            "requirement": "Define the non-inferiority margin.",
            "must_mention": ["non-inferiority margin"],
            "reason": "The decision needs an explicit threshold.",
            "search_leads": ["diagnostic model noninferiority margin study"],
        }],
    }

    merged = merge_plan_critique(
        "1. EXPLICIT: Sketch the experiment.",
        audit,
        include_search_leads=False,
    )

    assert "Define the non-inferiority margin" in merged
    assert "EXACT: non-inferiority margin" in merged
    assert "SEARCH:" not in merged
