"""``generate_snippets`` (PLAN.md Phase 4d follow-on, in
``src/systems/facets_agent/PLAN.md``): LLM-generated, query-relevant search
previews -- the user's follow-up after the plain positional-truncation
two-tier prototype's citation-support regression didn't fully resolve on a
whitespace/word-boundary fix alone (see
``worklogs/2026-08-06-facets-agent-two-tier-snippet-diagnosis.md``).
"""
from __future__ import annotations

import json
from typing import Any

from conftest import ScriptedProvider, model_turn

from agent_harness.tools.snippet import generate_snippets

DOCS = [
    {"id": "a", "text": "Document A discusses the history of geometry."},
    {"id": "b", "text": "Document B is about unrelated topics entirely."},
]


def test_no_query_or_no_documents_short_circuits_without_a_model_call(
        monkeypatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(
        "agent_harness.agent.make_provider",
        lambda *a, **kw: calls.append(1) or ScriptedProvider([]))
    assert generate_snippets("", DOCS) == {}
    assert generate_snippets("query", []) == {}
    assert not calls


def test_successful_generation_returns_snippets_by_id(monkeypatch) -> None:
    verdict_json = json.dumps({"snippets": [
        {"id": "a", "snippet": "History of geometry, per document A."},
        {"id": "b", "snippet": "Unrelated content."},
    ]})
    provider = ScriptedProvider([model_turn(text=verdict_json)])
    monkeypatch.setattr(
        "agent_harness.agent.make_provider", lambda backend, model: provider)
    out = generate_snippets("geometry history", DOCS)
    assert out == {
        "a": "History of geometry, per document A.",
        "b": "Unrelated content.",
    }
    assert "geometry history" in provider.user_messages[0]


def test_snippets_longer_than_max_chars_are_hard_capped(monkeypatch) -> None:
    long_snippet = "x" * 1000
    verdict_json = json.dumps(
        {"snippets": [{"id": "a", "snippet": long_snippet}]})
    provider = ScriptedProvider([model_turn(text=verdict_json)])
    monkeypatch.setattr(
        "agent_harness.agent.make_provider", lambda backend, model: provider)
    out = generate_snippets("q", DOCS, max_chars=50)
    assert len(out["a"]) == 50


def test_a_markdown_fenced_response_is_still_parsed(monkeypatch) -> None:
    fenced = "```json\n" + json.dumps(
        {"snippets": [{"id": "a", "snippet": "fenced snippet"}]}) + "\n```"
    provider = ScriptedProvider([model_turn(text=fenced)])
    monkeypatch.setattr(
        "agent_harness.agent.make_provider", lambda backend, model: provider)
    assert generate_snippets("q", DOCS) == {"a": "fenced snippet"}


def test_a_model_exception_returns_empty_not_a_raise(monkeypatch) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("unreachable")

    monkeypatch.setattr("agent_harness.agent.make_provider", boom)
    assert generate_snippets("q", DOCS) == {}


def test_a_missing_or_malformed_snippet_for_one_id_is_simply_absent(
        monkeypatch) -> None:
    """Partial coverage (the model only answered for "a") must not raise or
    invent an entry for "b" -- the caller (agent.py::_apply_search_preview)
    is what falls back to positional truncation for ids this misses."""
    verdict_json = json.dumps(
        {"snippets": [{"id": "a", "snippet": "only a, covered"}]})
    provider = ScriptedProvider([model_turn(text=verdict_json)])
    monkeypatch.setattr(
        "agent_harness.agent.make_provider", lambda backend, model: provider)
    out = generate_snippets("q", DOCS)
    assert out == {"a": "only a, covered"}
    assert "b" not in out
