"""The audience audit must stay plan-free, strict, and cheap to repair."""
from __future__ import annotations

import json

from aus_agent_v2.audience_verify import (
    apply_audience_insertions,
    AUDIENCE_VERIFY_SYSTEM,
    audience_verify_request,
    build_audience_patch_packet,
    normalize_audience_audit,
)


def test_request_contains_query_and_draft_but_no_plan_slot() -> None:
    """Omitting the plan is what lets this stage catch the planner's blind spots."""
    packet = audience_verify_request("Explain the project.", "Draft answer.")

    assert "ORIGINAL RESEARCH REQUEST" in packet
    assert "CITED DRAFT TO AUDIT" in packet
    assert "Explain the project." in packet
    assert "Draft answer." in packet
    assert "PRE-RESEARCH" not in packet


def test_normalizer_bounds_findings_and_rejects_wrong_shapes() -> None:
    """A malformed or expansive critic must never restart unbounded research."""
    assert normalize_audience_audit("not JSON")["parse_error"] is True
    raw = json.dumps({
        "verdict": "repair",
        "missing": [{
            "requirement": f"requirement {index}",
            "draft_gap": f"gap {index}",
            "search_lead": "compact query",
        } for index in range(6)],
    })

    audit = normalize_audience_audit(raw)

    assert len(audit["missing"]) == 2
    assert audit["missing"][-1]["requirement"] == "requirement 1"


def test_prompt_prefers_names_and_workflows_over_deeper_proofs() -> None:
    """The audit targets breadth because research already had a chance at depth."""
    assert "at most 40 words" in AUDIENCE_VERIFY_SYSTEM
    assert "specific product or technical advantage" in AUDIENCE_VERIFY_SYSTEM
    assert "do not spend an item strengthening its formalism" in (
        AUDIENCE_VERIFY_SYSTEM)
    assert "at most two omissions" in AUDIENCE_VERIFY_SYSTEM


def test_patch_packet_grants_authority_per_finding_not_per_draft() -> None:
    """A latent addition may cite relevant committed evidence without laundering it."""
    audit = {"missing": [{
        "requirement": "Name the accountable transport authority.",
        "draft_gap": "The implementation owner is absent.",
        "search_lead": "transport authority oversight",
    }]}
    documents = {
        "doc_a": {"text": "The transport authority reports capital spending."},
        "doc_b": {"text": "A completely unrelated medical observation."},
    }

    built = build_audience_patch_packet(
        "Assess the policy.", "Traffic fell. [doc_a]", audit, documents,
        documents_per_finding=1)

    assert built is not None
    packet, allowed = built
    assert "ALLOWED CITATION: [doc_a]" in packet
    assert allowed == {1: {"doc_a"}}


def test_insertion_application_preserves_original_lines_and_word_cap() -> None:
    """The failed rewrite arm cannot recur when old prose is immutable in code."""
    draft = "Traffic fell. [doc_a]\nRevenue funds transit. [doc_a]"
    response = json.dumps({"insertions": [{
        "finding": 1,
        "after_line": 1,
        "sentence": "The transport authority owns implementation. [doc_a]",
    }]})

    patched, stats, errors = apply_audience_insertions(
        draft, response, {1: {"doc_a"}})

    assert patched.splitlines()[0] == draft.splitlines()[0]
    assert patched.splitlines()[2] == draft.splitlines()[1]
    assert stats == {"proposed": 1, "accepted": 1, "rejected": 0}
    assert errors == []


def test_insertion_rejects_cross_finding_citations() -> None:
    """Relevance selection cannot authorize a different source at generation time."""
    response = json.dumps({"insertions": [{
        "finding": 1,
        "after_line": 1,
        "sentence": "A new claim appears. [doc_b]",
    }]})

    patched, stats, errors = apply_audience_insertions(
        "Original claim. [doc_a]", response, {1: {"doc_a"}})

    assert patched == "Original claim. [doc_a]"
    assert stats["accepted"] == 0
    assert errors
