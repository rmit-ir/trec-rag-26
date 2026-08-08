"""Tests for v2's evidence cards and non-destructive patch application.

The original fact-extraction arm proved the model would emit structured facts,
but not that the pipeline retained, selected, or used them.  These tests defend
the missing handoff: only accepted evidence enters the ledger, and revision
suggestions stay local to the document a draft sentence already cites.
"""
from __future__ import annotations

from aus_agent_v2.finish_review import (
    apply_evidence_patches,
    build_coverage_audit_request,
    build_finish_review_packet,
    build_finish_review_feedback,
    capture_committed_facts,
)


def test_coverage_audit_receives_requirements_plan_and_draft_without_sources() -> None:
    """The verifier's only job is omission detection, not evidence relitigation."""
    request = build_coverage_audit_request(
        "Write two beginner posts.",
        "Post one explains saving. [doc_a]",
        "1. AUDIENCE: assume no experience.",
    )

    assert "ORIGINAL RESEARCH REQUEST" in request
    assert "PRE-RESEARCH COVERAGE PLAN" in request
    assert "DRAFT TO AUDIT" in request
    assert "source excerpt" not in request.lower()


def test_capture_keeps_facts_only_for_ids_the_handler_committed() -> None:
    """A model selection beyond the per-step cap must not become usable evidence."""
    ledger = {}
    added = capture_committed_facts(
        {"documents": [
            {"id": "doc_a", "facts": [
                {"claim": "A rate was measured", "value": "34%",
                 "scope": "survey respondents"},
            ]},
            {"id": "doc_b", "facts": [
                {"claim": "An unaccepted result says something",
                 "value": "99%"},
            ]},
        ]},
        ["doc_a"],
        ledger,
    )

    assert added == 1
    assert ledger == {
        "doc_a": [{"claim": "A rate was measured", "value": "34%",
                   "scope": "survey respondents"}],
    }


def test_finish_feedback_uses_only_unused_facts_from_the_same_citation() -> None:
    """The review may sharpen a point, never launder another document into it."""
    ledger = {
        "doc_a": [
            {"claim": "The pilot reduced traffic", "value": "by 17%",
             "scope": "weekday entries"},
        ],
        "doc_b": [
            {"claim": "The pilot raised revenue", "value": "$48 million"},
        ],
    }
    draft = "The pilot reduced traffic materially. [doc_a]"

    feedback = build_finish_review_feedback(draft, ledger)

    assert feedback is not None
    assert "by 17%" in feedback
    assert "weekday entries" in feedback
    assert "$48 million" not in feedback
    assert "Preserve every accurate, supported point" in feedback


def test_finish_feedback_skips_a_specific_already_present_in_the_draft() -> None:
    """A revision turn with no new opportunity is pure cost and must be avoided."""
    ledger = {
        "doc_a": [
            {"claim": "The pilot reduced traffic", "value": "by 17%",
             "scope": "weekday entries"},
        ],
    }
    draft = "The pilot reduced weekday entries by 17%. [doc_a]"

    assert build_finish_review_feedback(draft, ledger) is None


def test_finish_feedback_caps_the_revision_payload() -> None:
    """The failed all-tools arm showed that finishing context can be crowded out."""
    ledger = {
        f"doc_{index}": [
            {"claim": f"Measure {index} changed", "value": f"{index}%"},
        ]
        for index in range(5)
    }
    draft = "\n".join(
        f"Measure {index} changed. [doc_{index}]" for index in range(5)
    )

    feedback = build_finish_review_feedback(draft, ledger, max_suggestions=2)

    assert feedback is not None
    assert feedback.count("\n- line ") == 2


def test_source_packet_works_when_sol_emits_no_optional_facts() -> None:
    """The target model's empty fact fields cannot disable the review stage."""
    draft = "The pilot reduced traffic materially. [doc_a]"
    documents = {
        "doc_a": {"id": "doc_a", "text": (
            "The transport agency reported that weekday entries into the "
            "charging zone fell 17 percent during the first full month.")},
    }

    built = build_finish_review_packet(
        "Assess the traffic pilot.", draft, documents, {})

    assert built is not None
    packet, stats = built
    assert "weekday entries" in packet
    assert "17 percent" in packet
    assert "ALLOWED CITATION: [doc_a]" in packet
    assert stats == {"cards": 1, "documents": 1,
                     "packet_chars": len(packet), "inferred_citations": 0}


def test_source_packet_never_borrows_an_uncited_document() -> None:
    """A good passage elsewhere in context must not launder a weak citation."""
    documents = {
        "doc_a": {"id": "doc_a", "text": "The pilot began in January."},
        "doc_b": {"id": "doc_b", "text":
                  "Weekday traffic fell exactly 17 percent."},
    }

    built = build_finish_review_packet(
        "Assess the pilot.", "Traffic fell 17 percent. [doc_a]", documents)

    assert built is not None
    packet, _stats = built
    assert "pilot began in January" in packet
    assert "Weekday traffic fell exactly" not in packet
    assert "[doc_b]" not in packet


def test_source_packet_caps_cards_before_context_can_crowd_the_writer() -> None:
    """A long report needs a deterministic ceiling on the fresh writer input."""
    documents = {
        f"doc_{index}": {"id": f"doc_{index}",
                         "text": f"Measure {index} changed by {index} percent."}
        for index in range(5)
    }
    draft = "\n".join(
        f"Measure {index} changed. [doc_{index}]" for index in range(5))

    built = build_finish_review_packet(
        "Compare measures.", draft, documents, max_cards=2)

    assert built is not None
    packet, stats = built
    assert stats["cards"] == 2
    assert "CARD 2" in packet
    assert "CARD 3" not in packet


def test_source_packet_adds_evidence_for_a_supported_uncited_draft_point() -> None:
    """Coverage should be cited from committed text instead of cut wholesale."""
    documents = {
        "doc_a": {"id": "doc_a", "text":
                  "Competition problems reward recognizing hidden structure."},
        "doc_b": {"id": "doc_b", "text":
                  "The course includes three-dimensional measurement."},
    }

    built = build_finish_review_packet(
        "Contrast two teaching styles.",
        "Competitions reward recognizing hidden structure.", documents)

    assert built is not None
    packet, stats = built
    assert "DRAFT CITATION STATUS: missing" in packet
    assert "ALLOWED CITATION: [doc_a]" in packet
    assert "[doc_b]" not in packet
    assert stats["inferred_citations"] == 1


def test_patch_application_preserves_every_unmentioned_line() -> None:
    """The primary regression guard is structural, not a prompt aspiration."""
    draft = (
        "The pilot reduced traffic. [doc_a]\n"
        "The pilot also funded transit. [doc_b]"
    )
    packet = """\
CARD 1 — draft line 1
DRAFT CLAIM: The pilot reduced traffic.
ALLOWED CITATION: [doc_a]
SOURCE EXCERPT 1: Weekday traffic fell 17 percent.
"""
    response = (
        '{"edits":[{"line":1,"replacement":'
        '"The pilot reduced traffic by 17 percent. [doc_a]"}]}'
    )

    patched, stats, errors = apply_evidence_patches(draft, response, packet)

    assert patched.splitlines()[1] == draft.splitlines()[1]
    assert "by 17 percent" in patched
    assert stats == {"proposed": 1, "accepted": 1, "rejected": 0}
    assert errors == []


def test_patch_application_rejects_cross_claim_citation_laundering() -> None:
    """A card for one line cannot authorize evidence on another draft claim."""
    draft = "The pilot reduced traffic. [doc_a]"
    packet = """\
CARD 1 — draft line 1
DRAFT CLAIM: The pilot reduced traffic.
ALLOWED CITATION: [doc_a]
SOURCE EXCERPT 1: Weekday traffic fell 17 percent.
"""
    response = (
        '{"edits":[{"line":1,"replacement":'
        '"The pilot reduced traffic by 17 percent. [doc_b]"}]}'
    )

    patched, stats, errors = apply_evidence_patches(draft, response, packet)

    assert patched == draft
    assert stats == {"proposed": 1, "accepted": 0, "rejected": 1}
    assert errors == ["line 1 used a non-card citation"]
