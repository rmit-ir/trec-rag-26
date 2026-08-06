"""Contract tests for answer selection, whose safety depends on no rewriting."""
from __future__ import annotations

import json

from systems.aus_agent_v2.ensemble_select import (
    _answer_with_docids,
    _stable_order,
    normalize_rubric,
    normalize_rubric_scores,
    normalize_selection,
    selector_packet,
    weighted_candidate_scores,
)


def _candidate(text: str = "A supported sentence.") -> dict:
    return {
        "references": ["doc-a", "doc-b"],
        "answer": [{"text": text, "citations": [1, "doc-a"]}],
    }


def test_normalize_selection_requires_an_assessment_for_every_candidate() -> None:
    """A partial vote can otherwise hide that the model never compared one draft."""
    winner, errors = normalize_selection(
        json.dumps({"winner": "A", "assessments": {"A": "better"}}),
        ["A", "B"],
    )
    assert winner is None
    assert errors


def test_normalize_selection_accepts_the_exact_contract() -> None:
    """Validated labels are the only model output allowed to control routing."""
    winner, errors = normalize_selection(
        json.dumps({
            "winner": "B",
            "assessments": {"A": "misses a case", "B": "covers both cases"},
        }),
        ["A", "B"],
    )
    assert winner == "B"
    assert errors == []


def test_answer_rendering_maps_indices_to_docids_without_changing_text() -> None:
    """Stable ids let the selector inspect citation placement without remapping output."""
    assert _answer_with_docids(_candidate()) == (
        "A supported sentence. [doc-b] [doc-a]")


def test_selector_packet_marks_candidate_text_as_separate_data() -> None:
    """Explicit boundaries reduce the chance that candidate prose is followed as input."""
    packet = selector_packet(
        "Compare the cases.", [("A", _candidate("First.")),
                               ("B", _candidate("Second."))])
    assert packet.startswith("ORIGINAL REQUEST\nCompare the cases.")
    assert "\n\nCANDIDATE A\nFirst." in packet
    assert "\n\nCANDIDATE B\nSecond." in packet


def test_stable_order_is_repeatable_and_contains_every_run() -> None:
    """A deterministic shuffle makes retries auditable while removing chronology cues."""
    run_ids = ["old", "middle", "new"]
    first = _stable_order("qid-1", run_ids)
    assert first == _stable_order("qid-1", run_ids)
    assert set(first) == set(run_ids)


def test_rubric_and_score_matrix_are_complete_before_routing() -> None:
    """Missing criteria must fail closed because the harness computes the winner."""
    criteria = [
        {"id": f"R{i}", "kind": "reward", "weight": 5,
         "text": f"Observable requirement {i}"}
        for i in range(1, 11)
    ]
    rubric, errors = normalize_rubric(json.dumps({"criteria": criteria}))
    assert errors == []
    matrix, errors = normalize_rubric_scores(
        json.dumps({
            "scores": {
                "A": {f"R{i}": 1 for i in range(1, 11)},
                "B": {f"R{i}": 0.5 for i in range(1, 11)},
            },
            "notes": {"A": "complete", "B": "partial"},
        }),
        ["A", "B"],
        [f"R{i}" for i in range(1, 11)],
    )
    assert errors == []
    assert weighted_candidate_scores(rubric, matrix) == {"A": 1.0, "B": 0.5}


def test_penalties_subtract_in_harness_score() -> None:
    """Signed arithmetic must not rely on a model correctly applying penalties."""
    rubric = [
        {"id": "R1", "kind": "reward", "weight": 5, "text": "coverage"},
        {"id": "R2", "kind": "penalty", "weight": 2, "text": "unsafe claim"},
    ]
    scores = weighted_candidate_scores(
        rubric, {"A": {"R1": 1.0, "R2": 1.0},
                 "B": {"R1": 0.5, "R2": 0.0}})
    assert scores == {"A": 0.6, "B": 0.5}
