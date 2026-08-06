"""Hermetic checks for the extractive complete-answer union boundary.

The selector sees already-paid complete answers and may choose only immutable
item ids. These tests defend citation preservation, the anchor floor, the word
cap, complete audit mappings, and exact fallback when the model misbehaves.
"""
from __future__ import annotations

import json

import pytest
from conftest import ScriptedProvider, model_turn, tool_call

from aus_agent_v2.candidate_union import (
    CANDIDATE_UNION_SYSTEM,
    CANDIDATE_UNION_TOOL,
    MAX_ANSWER_WORDS,
    build_candidate_union_packet,
    candidate_union_request,
    normalize_candidate_union,
    select_candidate_union,
)
from aus_agent_v2.pipeline import run_candidate_union_one
from ragrun.outputs import validate_rag_output
from ragrun.trajectory import TRACE_SCHEMA_VERSION


QUERY = "Compare Alpha and Beta for a general reader."


def _output(
    run_id: str,
    items: list[tuple[str, list[int | str]]],
    *,
    references: list[str] | None = None,
    narrative: str = QUERY,
    qid: str = "q1",
) -> dict:
    """Build a strict organizer output with controllable citation forms."""
    return {
        "metadata": {
            "team_id": "rmit-ir",
            "narrative_id": qid,
            "narrative": narrative,
            "run_id": run_id,
            "run_desc": "fixture",
        },
        "references": references or ["d1", "d2", "d3"],
        "answer": [
            {"text": text, "citations": citations}
            for text, citations in items
        ],
    }


def _candidates() -> list[dict]:
    """Return one anchor and one complementary complete answer."""
    return [
        _output("anchor-run", [
            ("Alpha is the first option.", [0]),
            ("It costs ten units monthly.", [1]),
            ("The main limitation is latency.", [2]),
        ]),
        _output("alternative-run", [
            ("Beta is the second option.", ["d2"]),
            ("A controlled trial found lower errors.", [2]),
            ("The comparison depends on workload.", [0, 1]),
        ]),
    ]


def _packet(candidates: list[dict] | None = None) -> dict:
    """Build the deterministic qid-shuffled packet used by the fixtures."""
    return build_candidate_union_packet(
        QUERY,
        candidates or _candidates(),
        expected_qid="q1",
        anchor_run_id="anchor-run",
    )


def _candidate_item_ids(packet: dict) -> tuple[list[str], list[str]]:
    """Resolve anchor and complementary ids without assuming visible positions."""
    anchor_id = packet["anchor_candidate_id"]
    anchor = next(
        candidate for candidate in packet["candidates"]
        if candidate["candidate_id"] == anchor_id)
    alternative = next(
        candidate for candidate in packet["candidates"]
        if candidate["candidate_id"] != anchor_id)
    return (
        [item["item_id"] for item in anchor["items"]],
        [item["item_id"] for item in alternative["items"]],
    )


def _valid_arguments(packet: dict) -> dict:
    """Select a bounded sequence that retains the anchor floor."""
    anchor, alternative = _candidate_item_ids(packet)
    return {
        "selected_item_ids": [
            anchor[0], alternative[0], anchor[1], anchor[2],
        ],
        "coverage": [{
            "requirement": "Explain both options.",
            "item_ids": [anchor[0], alternative[0]],
        }, {
            "requirement": "Give cost and limitation context.",
            "item_ids": [anchor[1], anchor[2]],
        }],
        "anchor_replacements": [],
    }


def test_packet_anonymizes_runs_and_preserves_exact_candidate_items() -> None:
    """Model-visible labels must not leak run names or alter cited prose."""
    packet = _packet()
    serialized = candidate_union_request(packet)

    assert packet["query_id"] == "q1"
    alternative = next(
        candidate for candidate in packet["candidates"]
        if not candidate["anchor"])
    assert alternative["items"][0] == {
        "item_id": f"{alternative['candidate_id']}:I01",
        "text": "Beta is the second option.",
        "source_ids": ["d2"],
        "word_count": 5,
    }
    assert "anchor-run" not in serialized
    assert "alternative-run" not in serialized
    assert "Australia" not in CANDIDATE_UNION_SYSTEM
    assert "AUS" not in CANDIDATE_UNION_SYSTEM


def test_valid_union_copies_text_and_remaps_original_citations() -> None:
    """Selection may reorder evidence, but it cannot rewrite or recite sources."""
    packet = _packet()

    normalized, errors, stats = normalize_candidate_union(
        _valid_arguments(packet), packet)

    assert errors == []
    assert normalized is not None
    assert [item["text"] for item in normalized["answer"]] == [
        "Alpha is the first option.",
        "Beta is the second option.",
        "It costs ten units monthly.",
        "The main limitation is latency.",
    ]
    assert normalized["references"] == ["d1", "d2", "d3"]
    assert [item["citations"] for item in normalized["answer"]] == [
        [0], [1], [1], [2],
    ]
    assert stats["anchor_items_retained"] == 3
    anchor_id = packet["anchor_candidate_id"]
    nonanchor_id = next(
        candidate["candidate_id"] for candidate in packet["candidates"]
        if candidate["candidate_id"] != anchor_id)
    assert stats["contribution"][nonanchor_id] == {"items": 1, "words": 5}


def test_union_rejects_anchor_reordering_and_unmapped_selection() -> None:
    """A selector cannot scramble the coherent base or hide an item from audit."""
    packet = _packet()
    anchor, alternative = _candidate_item_ids(packet)
    arguments = _valid_arguments(packet)
    arguments["selected_item_ids"] = [
        anchor[1], anchor[0], anchor[2], alternative[0],
    ]
    arguments["coverage"][0]["item_ids"] = [anchor[0], alternative[0]]
    arguments["coverage"][1]["item_ids"] = [anchor[1]]

    normalized, errors, _stats = normalize_candidate_union(arguments, packet)

    assert normalized is None
    assert any("relative order" in error for error in errors)
    assert any(f"lack coverage rows: {anchor[2]}" in error for error in errors)


def test_union_enforces_official_word_cap_across_valid_candidates() -> None:
    """Two individually legal answers cannot compile into an oversized one."""
    anchor_text = " ".join(["anchor"] * 700)
    alternative_text = " ".join(["alternative"] * 400)
    candidates = [
        _output("anchor-run", [(anchor_text, [0])]),
        _output("alternative-run", [(alternative_text, [1])]),
    ]
    packet = _packet(candidates)
    anchor, alternative = _candidate_item_ids(packet)
    arguments = {
        "selected_item_ids": [anchor[0], alternative[0]],
        "coverage": [{
            "requirement": "Cover both.",
            "item_ids": [anchor[0], alternative[0]],
        }],
        "anchor_replacements": [],
    }

    normalized, errors, stats = normalize_candidate_union(arguments, packet)

    assert normalized is None
    assert stats["answer_words"] == 1_100
    assert any(f"maximum is {MAX_ANSWER_WORDS}" in error for error in errors)


def test_selector_accepts_one_typed_extract_and_records_complete_input() -> None:
    """The runnable stage must expose its full packet and provider history."""
    provider = ScriptedProvider([model_turn(tool_calls=[tool_call(
        CANDIDATE_UNION_TOOL["name"],
        _valid_arguments(_packet()),
        id="union-1")])])

    result = select_candidate_union(
        QUERY,
        _candidates(),
        expected_qid="q1",
        anchor_run_id="anchor-run",
        provider_factory=lambda: provider,
    )

    assert result["accepted"] is True
    assert result["fallback"] is None
    assert result["attempts"][0]["errors"] == []
    assert json.loads(provider.user_messages[0]) == result["packet"]
    assert provider.tools == [CANDIDATE_UNION_TOOL]


def test_selector_falls_back_to_exact_anchor_after_two_protocol_faults() -> None:
    """A failed union may not consume or partially mutate a complete answer."""
    candidates = _candidates()
    candidates[0]["references"].append("unused-anchor-reference")
    providers = iter([
        ScriptedProvider([model_turn(text="I would choose the anchor.")]),
        ScriptedProvider([model_turn(tool_calls=[tool_call(
            CANDIDATE_UNION_TOOL["name"], {
                "selected_item_ids": ["C99:I99"],
                "coverage": [{
                    "requirement": "Unknown.",
                    "item_ids": ["C99:I99"],
                }],
                "anchor_replacements": [],
            }, id="union-bad")])]),
    ])

    result = select_candidate_union(
        QUERY,
        candidates,
        expected_qid="q1",
        anchor_run_id="anchor-run",
        provider_factory=lambda: next(providers),
    )

    anchor = candidates[0]
    assert result["accepted"] is False
    assert result["fallback"] == "anchor_after_invalid_union"
    assert result["answer"] == anchor["answer"]
    assert result["references"] == anchor["references"]
    assert len(result["attempts"]) == 2
    assert result["errors"]


def test_public_union_pipeline_saves_a_cost_visible_valid_artifact() -> None:
    """The method must be runnable and budget-auditable, not just a pure helper."""
    provider = ScriptedProvider([model_turn(
        tool_calls=[tool_call(
            CANDIDATE_UNION_TOOL["name"],
            _valid_arguments(_packet()),
            id="union-1")],
        usage={
            "inputTokens": 700,
            "outputTokens": 90,
            "cacheReadInputTokens": 20,
            "cacheWriteInputTokens": 0,
        },
    )])

    summary = run_candidate_union_one(
        qid="q1",
        narrative=QUERY,
        run_id="candidate-union.mock",
        candidate_outputs=_candidates(),
        anchor_run_id="anchor-run",
        provider_factory=lambda: provider,
    )
    output = json.loads(summary["paths"]["output"].read_text())
    trajectory = json.loads(summary["paths"]["trajectory"].read_text())

    assert summary["status"] == "completed"
    assert summary["accepted"] is True
    assert validate_rag_output(output) == []
    assert tuple(trajectory) == (
        "metadata", "query_id", "tool_call_counts", "tool_call_counts_all",
        "status", "retrieved_docids", "result", "raw_messages",
    )
    assert "trace" not in trajectory
    assert output["trace"]["schema_version"] == TRACE_SCHEMA_VERSION
    assert output["trace"]["status"] == "completed"
    assert all(
        {"type", "id", "parent_id", "t_start", "t_end"} <= set(step)
        for step in output["trace"]["steps"])
    assert output["trace"]["metadata"]["model"] == "scripted/test-model"
    assert output["trace"]["summary"]["tokens"] == {
        "reasoning": 0,
        "input": 720,
        "input_uncached": 700,
        "output": 90,
        "cache_read": 20,
        "cache_write": 0,
        "total": 810,
        "processed_input": 700,
        "processed": 790,
    }
    assert output["trace"]["summary"]["candidate_union"]["candidate_runs"] == [
        "anchor-run", "alternative-run"]


def test_packet_rejects_cross_topic_candidate_contamination() -> None:
    """A fluent answer from another topic must never enter the selector packet."""
    candidates = _candidates()
    candidates[1] = _output(
        "alternative-run",
        [("Unrelated but valid prose.", [0])],
        narrative="Explain an unrelated subject.",
    )

    with pytest.raises(ValueError, match="narrative does not match"):
        build_candidate_union_packet(
            QUERY, candidates, expected_qid="q1", anchor_run_id="anchor-run")


def test_packet_rejects_same_text_attached_to_a_different_qid() -> None:
    """Narrative equality alone cannot make a different topic safe to combine."""
    candidates = _candidates()
    candidates[1] = _output(
        "alternative-run",
        [("Beta is the second option.", [0])],
        qid="q-other",
    )

    with pytest.raises(ValueError, match="narrative_id does not match"):
        build_candidate_union_packet(
            QUERY, candidates, expected_qid="q1", anchor_run_id="anchor-run")


def test_dropped_anchor_item_needs_an_explicit_selected_replacement() -> None:
    """Volume ratios cannot silently discard a short but important anchor fact."""
    packet = _packet()
    anchor, alternative = _candidate_item_ids(packet)
    arguments = {
        "selected_item_ids": [anchor[0], alternative[0], anchor[1]],
        "coverage": [{
            "requirement": "Retain the comparison while replacing one limitation.",
            "item_ids": [anchor[0], alternative[0], anchor[1]],
        }],
        "anchor_replacements": [],
    }

    normalized, errors, _ = normalize_candidate_union(arguments, packet)
    assert normalized is None
    assert any(anchor[2] in error and "lack" in error for error in errors)

    arguments["anchor_replacements"] = [{
        "dropped_anchor_item_id": anchor[2],
        "replacement_item_ids": [alternative[0]],
    }]
    normalized, errors, _ = normalize_candidate_union(arguments, packet)
    assert errors == []
    assert normalized is not None


def test_anchor_only_selection_is_a_visible_exact_fallback() -> None:
    """An accepted union must actually contain complementary source content."""
    packet = _packet()
    anchor, _alternative = _candidate_item_ids(packet)
    arguments = {
        "selected_item_ids": anchor,
        "coverage": [{
            "requirement": "Retain the anchor.",
            "item_ids": anchor,
        }],
        "anchor_replacements": [],
    }
    provider = ScriptedProvider([model_turn(tool_calls=[tool_call(
        CANDIDATE_UNION_TOOL["name"], arguments, id="union-anchor")])])

    result = select_candidate_union(
        QUERY,
        _candidates(),
        expected_qid="q1",
        anchor_run_id="anchor-run",
        provider_factory=lambda: provider,
    )

    assert result["accepted"] is False
    assert result["fallback"] == "anchor_no_union"
    assert result["answer"] == _candidates()[0]["answer"]
