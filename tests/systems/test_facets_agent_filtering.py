"""facets_agent's ``search_result_filter`` configurations (PLAN.md Phase
4c): ``minimize_filter`` (Version A, drops non-relevant) and
``rank_filter`` (Version B, gpt-5.6-terra's alternative, drops nothing).
Both call ``agent_harness.tools.judge_documents`` -- mocked here so these
tests exercise the filtering LOGIC, not the judge call itself (already
covered by ``tests/agent_harness_context/test_judge_tool.py``).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from facets_agent.filtering import (
    MAX_JUDGED_PER_SEARCH, minimize_filter, rank_filter)

DOCS = [
    {"id": "a", "text": "doc a"},
    {"id": "b", "text": "doc b"},
    {"id": "c", "text": "doc c"},
]


def _verdicts(**by_id: str) -> dict[str, Any]:
    return {"verdicts": [{"id": k, "verdict": v} for k, v in by_id.items()]}


def test_minimize_filter_keeps_only_relevant() -> None:
    with patch("facets_agent.filtering.judge_documents",
              return_value=_verdicts(a="relevant", b="adjacent_not_relevant",
                                     c="irrelevant")):
        result = minimize_filter("what a is", DOCS)
    assert [d["id"] for d in result.documents] == ["a"]
    assert result.documents[0]["judge_verdict"] == "relevant"
    assert "2 of 3" in result.note


def test_minimize_filter_keeps_all_when_all_relevant() -> None:
    with patch("facets_agent.filtering.judge_documents",
              return_value=_verdicts(a="relevant", b="relevant", c="relevant")):
        result = minimize_filter("what a is", DOCS)
    assert {d["id"] for d in result.documents} == {"a", "b", "c"}
    assert result.note is None


def test_minimize_filter_fails_open_on_judge_error() -> None:
    """A broken judge call must never reduce a facet's evidence to zero --
    this is the central safety property gpt-5.6-terra's review demanded."""
    with patch("facets_agent.filtering.judge_documents",
              return_value={"error": "judge call failed: timeout"}):
        result = minimize_filter("what a is", DOCS)
    assert {d["id"] for d in result.documents} == {"a", "b", "c"}


def test_minimize_filter_fails_open_when_judge_omits_a_document() -> None:
    """A partial judge response (missing one id) must keep that document,
    not silently drop it -- fail-open applies per-document, not just to
    total failure."""
    with patch("facets_agent.filtering.judge_documents",
              return_value=_verdicts(a="irrelevant")):  # b, c never verdicted
        result = minimize_filter("what a is", DOCS)
    assert {d["id"] for d in result.documents} == {"b", "c"}


def test_minimize_filter_no_requirement_keeps_everything_without_calling_judge() -> None:
    with patch("facets_agent.filtering.judge_documents") as mock_judge:
        result = minimize_filter("", DOCS)
    assert not mock_judge.called
    assert {d["id"] for d in result.documents} == {"a", "b", "c"}


def test_rank_filter_drops_nothing_and_reorders_by_verdict() -> None:
    with patch("facets_agent.filtering.judge_documents",
              return_value=_verdicts(a="irrelevant", b="relevant",
                                     c="adjacent_not_relevant")):
        result = rank_filter("what a is", DOCS)
    assert {d["id"] for d in result.documents} == {"a", "b", "c"}
    assert [d["id"] for d in result.documents] == ["b", "c", "a"]


def test_rank_filter_preserves_original_order_on_total_judge_failure() -> None:
    """Python's stable sort + every doc unverdicted (None) means a total
    failure degrades to a no-op reordering, not a scramble."""
    with patch("facets_agent.filtering.judge_documents",
              return_value={"error": "unreachable"}):
        result = rank_filter("what a is", DOCS)
    assert [d["id"] for d in result.documents] == ["a", "b", "c"]


def test_overflow_beyond_batch_cap_passes_through_unjudged() -> None:
    many_docs = [{"id": str(i), "text": f"doc {i}"}
                for i in range(MAX_JUDGED_PER_SEARCH + 5)]
    judged_verdicts = _verdicts(**{
        str(i): "relevant" for i in range(MAX_JUDGED_PER_SEARCH)})
    with patch("facets_agent.filtering.judge_documents",
              return_value=judged_verdicts) as mock_judge:
        result = minimize_filter("req", many_docs)
    # only the first MAX_JUDGED_PER_SEARCH were sent to the judge
    (sent_requirement, sent_docs), _ = mock_judge.call_args
    assert len(sent_docs) == MAX_JUDGED_PER_SEARCH
    # all judged (relevant) + all overflow (passed through) are kept
    assert len(result.documents) == len(many_docs)
