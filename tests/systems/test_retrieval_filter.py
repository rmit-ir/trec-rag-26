"""Unit coverage for ``src/systems/brief_revise_agent/retrieval_filter.py``
-- iteration 3's ``search_result_filter`` (see its own module docstring for
the design rationale: a genuinely different axis from iterations 1-2's
brief/review work, after iteration 2 regressed on the full 15-topic set).

Every fail-open case matters more here than the happy path: the harness's
own ``_apply_search_result_filter`` (agent_harness/agent.py) already fails
open on an exception from this module, but sol's spec deliberately makes
THIS module fail open on its own malformed/ambiguous LLM output too --
never retry, never partially trust a judgment -- so most of these tests are
"garbage in -> original batch out, unchanged" rather than "garbage in ->
crash", which is the property that actually matters for never starving a
topic of evidence.
"""
from __future__ import annotations

import json

from conftest import ScriptedProvider, model_turn

from brief_revise_agent import retrieval_filter


def _docs(n: int) -> list[dict]:
    return [{"id": f"d{i}", "text": f"document {i} text " * 5} for i in range(n)]


def _labels_turn(labels: dict[str, str]) -> dict:
    return model_turn(text=json.dumps({"documents": [
        {"id": k, "label": v, "reason": "because"} for k, v in labels.items()]}))


REQ = "the exact date and location of the treaty signing"  # >20 chars


def test_direct_and_lead_kept_off_topic_removed() -> None:
    """8 documents, only 2 OFF_TOPIC: well above the retention floor (4,
    see the dedicated floor tests below), so removal is not overridden."""
    docs = _docs(8)
    labels = {"d0": "DIRECT", "d1": "LEAD", "d2": "OFF_TOPIC", "d3": "DIRECT",
             "d4": "OFF_TOPIC", "d5": "LEAD", "d6": "DIRECT", "d7": "LEAD"}
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert {d["id"] for d in result.documents} == {
        "d0", "d1", "d3", "d5", "d6", "d7"}


def test_original_document_order_preserved() -> None:
    docs = _docs(4)
    labels = {"d0": "OFF_TOPIC", "d1": "DIRECT", "d2": "OFF_TOPIC", "d3": "LEAD"}
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    # 4-or-fewer floor restores everything (see the dedicated test below),
    # but order must still match the ORIGINAL list, not label groupings.
    assert [d["id"] for d in result.documents] == ["d0", "d1", "d2", "d3"]


def test_ten_documents_cannot_be_reduced_below_five() -> None:
    docs = _docs(10)
    labels = {f"d{i}": "OFF_TOPIC" if i < 9 else "DIRECT" for i in range(10)}
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert len(result.documents) == 5


def test_six_documents_cannot_be_reduced_below_four() -> None:
    docs = _docs(6)
    labels = {f"d{i}": "OFF_TOPIC" if i < 5 else "DIRECT" for i in range(6)}
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert len(result.documents) == 4


def test_four_or_fewer_documents_never_removed() -> None:
    docs = _docs(4)
    labels = {f"d{i}": "OFF_TOPIC" for i in range(4)}
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert len(result.documents) == 4


def test_all_off_topic_returns_the_original_batch() -> None:
    docs = _docs(8)
    labels = {f"d{i}": "OFF_TOPIC" for i in range(8)}
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert len(result.documents) == 8


def test_invalid_json_returns_the_original_batch() -> None:
    docs = _docs(5)
    provider = ScriptedProvider([model_turn(text="not json at all")])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert result.documents == docs


def test_missing_id_returns_the_original_batch() -> None:
    docs = _docs(3)
    labels = {"d0": "DIRECT", "d1": "DIRECT"}  # d2 missing
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert result.documents == docs


def test_duplicate_id_returns_the_original_batch() -> None:
    docs = _docs(2)
    provider = ScriptedProvider([model_turn(text=json.dumps({"documents": [
        {"id": "d0", "label": "DIRECT"}, {"id": "d0", "label": "OFF_TOPIC"},
        {"id": "d1", "label": "DIRECT"}]}))])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert result.documents == docs


def test_invented_id_returns_the_original_batch() -> None:
    docs = _docs(2)
    labels = {"d0": "DIRECT", "d1": "DIRECT", "d99": "DIRECT"}
    provider = ScriptedProvider([_labels_turn(labels)])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert result.documents == docs


def test_invalid_label_returns_the_original_batch() -> None:
    docs = _docs(2)
    provider = ScriptedProvider([model_turn(text=json.dumps({"documents": [
        {"id": "d0", "label": "MAYBE"}, {"id": "d1", "label": "DIRECT"}]}))])
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert result.documents == docs


def test_provider_exception_returns_the_original_batch() -> None:
    docs = _docs(3)
    provider = ScriptedProvider([])  # empty queue raises on run_turn()
    result = retrieval_filter.make_filter(provider)(REQ, docs)
    assert result.documents == docs


def test_blank_or_short_requirement_returns_original_batch_without_an_llm_call() -> None:
    """A ``requirement`` under 20 characters skips the LLM call entirely --
    a ``ScriptedProvider([])`` would raise on any ``run_turn()`` call, so
    this test doubles as proof no call was attempted."""
    docs = _docs(3)
    provider = ScriptedProvider([])
    result = retrieval_filter.make_filter(provider)("too short", docs)
    assert result.documents == docs


def test_empty_documents_returns_empty_without_an_llm_call() -> None:
    provider = ScriptedProvider([])
    result = retrieval_filter.make_filter(provider)(REQ, [])
    assert result.documents == []
