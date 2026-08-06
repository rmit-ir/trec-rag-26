"""The final handoff binds prose intentions to harness-owned evidence state.

These tests focus on the trust boundary: model-authored claim maps may describe
anything, but only committed unit ids and captured facts may reach the recency-
anchored packet used by the answer turn.
"""
from __future__ import annotations

from systems.aus_agent_v2.answer_blueprint import (
    build_answer_handoff,
    commit_context_tool_with_facts,
    normalize_answer_blueprint,
)


def test_commit_fact_schema_is_v2_local_and_leaves_baseline_unchanged() -> None:
    """The experimental extraction contract must not leak into aus_agent."""
    from aus_agent.tools import COMMIT_CONTEXT_TOOL

    enriched = commit_context_tool_with_facts()
    original_item = COMMIT_CONTEXT_TOOL["input_schema"]["properties"][
        "documents"]["items"]
    enriched_item = enriched["input_schema"]["properties"]["documents"][
        "items"]

    assert "facts" not in original_item["properties"]
    assert enriched_item["properties"]["facts"]["maxItems"] == 5


def test_blueprint_rejects_uncommitted_evidence_ids() -> None:
    """A polished claim must not turn a hallucinated docid into citation state."""
    blueprint, errors = normalize_answer_blueprint({
        "requirements": [{
            "requirement": "Quantify the measured effect.",
            "claims": [{
                "claim": "Traffic fell by 12% in the priced zone.",
                "evidence_ids": ["never_retrieved_p1"],
            }],
        }],
        "unresolved": [],
    }, {"committed_p2"})

    assert blueprint is None
    assert any("uncommitted evidence id" in error for error in errors)


def test_handoff_replays_only_facts_for_ids_mapped_to_claims() -> None:
    """Tail replay should stay compact and cannot smuggle unrelated facts in."""
    blueprint, errors = normalize_answer_blueprint({
        "requirements": [{
            "requirement": "Quantify the measured effect.",
            "claims": [{
                "claim": "Traffic fell by 12% in the priced zone in 2025.",
                "evidence_ids": ["kept_p2"],
            }],
        }],
        "unresolved": ["Long-run effects were not established."],
    }, {"kept_p2", "unused_p4"})

    assert errors == []
    assert blueprint is not None
    packet = build_answer_handoff(
        "Assess the policy.",
        "1. EFFECT: quantify traffic change.",
        blueprint,
        {
            "kept_p2": [{
                "claim": "Traffic volume",
                "value": "fell by 12%",
                "scope": "priced zone, 2025",
            }],
            "unused_p4": [{
                "claim": "Revenue",
                "value": "$1 billion",
            }],
        },
    )

    assert "Traffic fell by 12%" in packet
    assert "kept_p2" in packet
    assert "priced zone, 2025" in packet
    assert "Long-run effects" in packet
    assert "unused_p4" not in packet
    assert "$1 billion" not in packet
