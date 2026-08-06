"""Coverage verification converts only valid, material omissions into repairs."""
from __future__ import annotations

import json

from aus_agent_v2.coverage_verify import (
    COVERAGE_VERIFY_SYSTEM,
    coverage_repair_request,
    coverage_verify_request,
    normalize_coverage_audit,
)


def test_request_keeps_plan_and_draft_in_a_small_isolated_packet() -> None:
    """The verifier should regain salience without inheriting retrieval noise."""
    packet = coverage_verify_request(
        "Explain the study.",
        "10. EVIDENCE: include a prior prevalence result.",
        "The study uses EHR data. [doc1]",
    )

    assert "ORIGINAL RESEARCH REQUEST" in packet
    assert "PRE-RESEARCH COVERAGE PLAN" in packet
    assert "CITED DRAFT TO VERIFY" in packet
    assert "prior prevalence result" in packet


def test_audit_normalizer_rejects_malformed_or_empty_repairs() -> None:
    """An auxiliary formatting failure must not trap a valid report in a loop."""
    assert normalize_coverage_audit("not JSON")["parse_error"] is True
    assert normalize_coverage_audit(json.dumps({
        "verdict": "repair", "missing": [{"wrong": "shape"}],
    })) == {"verdict": "pass", "missing": []}


def test_audit_normalizer_keeps_only_four_highest_priority_gaps() -> None:
    """An unbounded audit turns one finishing pass into another research loop."""
    audit = normalize_coverage_audit(json.dumps({
        "verdict": "repair",
        "missing": [{
            "plan_item": index,
            "requirement": f"requirement {index}",
            "draft_gap": f"gap {index}",
        } for index in range(1, 8)],
    }))

    assert [item["plan_item"] for item in audit["missing"]] == [1, 2, 3, 4]


def test_repair_request_replays_only_normalized_concrete_findings() -> None:
    """The evidence-owning writer needs an actionable gap, not another essay."""
    audit = normalize_coverage_audit(json.dumps({
        "verdict": "repair",
        "missing": [{
            "plan_item": 11,
            "requirement": "Name HIPAA explicitly.",
            "draft_gap": "Only generic privacy approval is stated.",
        }],
    }))

    feedback = coverage_repair_request(audit, "11. SAFETY: cover HIPAA.")

    assert audit["verdict"] == "repair"
    assert "plan item 11" in feedback
    assert "Name HIPAA explicitly" in feedback
    assert "COMPLETE draft" in feedback
    assert "1,024 words" in feedback
    assert "numerical prevalence value" in feedback
    assert "at most one parallel search batch" in feedback


def test_verifier_prioritizes_uncited_sensitive_synthesis_and_precedent() -> None:
    """The two observed severe-penalty paths must outrank optional breadth."""
    compact = " ".join(COVERAGE_VERIFY_SYSTEM.split())

    assert "uncited sentence" in compact
    assert "medical" in compact
    assert "no exact study was established" in compact
    assert "closest credible precedent" in compact
