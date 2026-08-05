"""End-to-end coverage for ``src/systems/facets_agent`` — a thin configuration
of the shared ``aus_agent.agent.run_agent`` staged-context harness.

``facets_agent.agent.run_agent`` reimplements nothing: it renders this
package's own minimal prompt and calls straight into
``aus_agent.agent.run_agent`` with ``system_name="facets_agent"``, the three
natural-language retrieval engines enabled (``ssr``/``lucene_bool`` are no
longer supported), and a wider default ``k`` for the ``hybrid`` engine. The
loop mechanics themselves (staged/committed evidence, the final-report
contract, citation parsing) are already covered by
``tests/systems/test_aus_agent.py`` against the same shared code — this file
only proves facets_agent's OWN configuration actually reaches the harness:
its artifacts land under its own system name, its tool definition advertises
exactly those three engines, and an omitted ``k`` on a ``hybrid`` call gets
the wider default rather than the plain one.

Provider substitution follows the same pattern as ``test_aus_agent.py``:
``ScriptedProvider`` stands in for the model, patched onto
``aus_agent.agent.make_provider`` (where the shared harness actually
constructs it) rather than on ``facets_agent.agent`` — the wrapper module
never calls ``make_provider`` itself.
"""
from __future__ import annotations

from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn, tool_call

from aus_agent import agent as aus_agent_mod

from facets_agent.agent import DEFAULT_ENGINES, DEFAULT_HYBRID_K, SYSTEM_NAME
from facets_agent.agent import run_agent as facets_run_agent

QID = "mock_facets_001"
QUERY = "How effective is congestion pricing at reducing traffic?"
D = CLIMBMIX_DOCIDS


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch,
          stub_search_tool: dict[str, list[dict[str, Any]]]
          ) -> Callable[..., dict[str, Any]]:
    """Run ``facets_agent.agent.run_agent`` against a scripted provider."""
    def _drive(script: list[dict[str, Any]], *, query_id: str = QID,
               query: str = QUERY, **kwargs: Any) -> dict[str, Any]:
        provider = ScriptedProvider(script)
        monkeypatch.setattr(aus_agent_mod, "make_provider",
                            lambda backend, model: provider)
        kwargs.setdefault("safety_max_rounds", 20)
        summary = facets_run_agent(query_id, query, **kwargs)
        return {"summary": summary, "provider": provider,
                "calls": stub_search_tool}
    return _drive


HAPPY_SCRIPT = [
    model_turn(reasoning=["Search hybrid first; it's the safe default."],
               tool_calls=[tool_call(
                   "search", {"query": "congestion pricing revenue plan",
                              "search_engine": "hybrid"}, id="s1")]),
    model_turn(text="One of those is worth keeping.",
               tool_calls=[tool_call("commit_context", {"documents": [
                   {"docid": D[0], "reason": "revenue allocation"}]}, id="c1")]),
    model_turn(text=f"Toll revenue funds the capital plan [{D[0]}]."),
]


def test_run_writes_valid_artifacts_under_its_own_system_name(
        drive: Callable[..., dict[str, Any]]) -> None:
    """facets_agent must never write into aus_agent's output tree.

    Both systems share the harness code, so the one thing that actually
    distinguishes their artifacts on disk is ``system_name`` reaching
    ``ragrun.save_run`` — this is the regression a copy-paste of aus_agent's
    hardcoded ``"aus_agent"`` string would silently reintroduce.
    """
    from ragrun import validate_rag_output

    result = drive(list(HAPPY_SCRIPT))
    summary = result["summary"]
    assert summary["status"] == "completed"
    paths = summary["paths"]
    assert paths["output"].parent.name == SYSTEM_NAME == "facets_agent"
    assert paths["trajectory"].parent.name == "facets_agent"
    output = __import__("json").loads(paths["output"].read_text())
    assert validate_rag_output(output) == []
    assert output["references"]


def test_only_the_three_nl_engines_are_advertised_to_the_model(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The search tool's enum must list exactly semantic/keyword/hybrid by
    default — ssr/lucene_bool are no longer supported and must not appear."""
    result = drive(list(HAPPY_SCRIPT))
    search_tool_def = next(
        t for t in result["provider"].tools if t["name"] == "search")
    assert (search_tool_def["input_schema"]["properties"]["search_engine"]
            ["enum"]) == DEFAULT_ENGINES
    assert set(DEFAULT_ENGINES) == {"semantic", "keyword", "hybrid"}


def test_hybrid_search_defaults_to_a_wider_k_than_other_engines(
        drive: Callable[..., dict[str, Any]]) -> None:
    """An omitted ``k`` on a ``hybrid`` call must widen to DEFAULT_HYBRID_K.

    The prompt already asks the model to request more results from hybrid
    (its HyDE-style query benefits from a wider net), but the model is not
    guaranteed to comply — this is the code-level guarantee that backs it up.
    """
    result = drive(list(HAPPY_SCRIPT))
    hybrid_calls = result["calls"]["hybrid"]
    assert hybrid_calls, "the scripted hybrid search never reached the engine"
    assert hybrid_calls[0]["k"] == DEFAULT_HYBRID_K


def test_get_documents_tool_is_available(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The fetch-full-document tool must be wired in like aus_agent's."""
    result = drive(list(HAPPY_SCRIPT))
    names = {t["name"] for t in result["provider"].tools}
    assert {"search", "get_documents", "commit_context"} <= names


@pytest.mark.live
def test_run_agent_live() -> None:
    """Same path against the real ClimbMix + OpenAI endpoints (needs creds)."""
    summary = facets_run_agent(
        "live_smoke", QUERY, safety_max_rounds=20, k=5)
    assert summary["status"] in ("completed", "budget_exhausted")
    assert summary["n_references"] > 0
