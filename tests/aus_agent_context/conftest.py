"""Fixtures scoped to the aus_agent staged-context tests.

Everything here layers on the repo-wide fixtures in ``tests/conftest.py`` (which
stay in force: ``no_network``, ``isolated_data_dir``, and ``no_ambient_creds``
are autouse). Three additions, each because the shared layer cannot express what
these tests assert — see ``fakes.py``'s docstring for the reasoning:

- ``fake_engine`` patches ``tools.search_tool._DISPATCH`` with the disjoint
  alpha/beta/gamma result sets. Patching the dispatch table rather than
  ``aus_agent.tools.search.run_search_tool`` (what the old suite did) keeps the
  real serialization, the ``{"error": ...}`` envelope, and the per-result
  truncation under test — strictly more production code than before.
- ``ledger_with`` builds a ``ContextLedger`` with staged batches, using the real
  ``documents_from_search`` so the staged document shape is production's.
- ``run_agent_capture`` drives a whole ``run_agent`` against a scripted provider
  and hands back the trajectory/output objects the final save would have
  written.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from aus_agent_context.fakes import DOC_SETS, STATUS_LINE, search_payload, staged_text

from utils.search_types import make_hit


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Patch every ``tools.search_tool`` engine with the alpha/beta/gamma sets.

    Returns a ``calls`` record like the shared ``stub_search_tool``'s, so a test
    can assert engine routing and forwarded kwargs. An unmapped query raises,
    which ``run_search_tool`` converts into its ``{"error": ...}`` envelope —
    that is the failed-search path, reachable without any network.
    """
    from tools import search_tool

    calls: dict[str, list[dict[str, Any]]] = {}

    def _make(engine: str) -> Callable[..., list[dict[str, Any]]]:
        def _fake(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
            calls.setdefault(engine, []).append({"query": query, "k": k, **kw})
            if query not in DOC_SETS:
                raise ValueError(f"no scripted result set for {query!r}")
            return [
                make_hit(docid, score=1 / rank, rank=rank,
                         text=staged_text(docid), meta={"source": engine})
                for rank, docid in enumerate(DOC_SETS[query], 1)
            ]
        return _fake

    monkeypatch.setattr(
        search_tool, "_DISPATCH",
        {engine: _make(engine) for engine in search_tool._DISPATCH})
    return calls


@pytest.fixture
def ledger_with() -> Callable[..., Any]:
    """Build a ``ContextLedger`` holding one or more staged batches.

    ``ledger_with(("search-1", "alpha"))`` stages alpha's three documents under
    call id ``search-1``. ``with_status_line=False`` omits the budget footer, for
    the tests that assert it is only re-appended when it was there to begin with.
    """
    from aus_agent.context import ContextLedger
    from aus_agent.tools import documents_from_search

    def _build(*batches: tuple[str, str], with_status_line: bool = True) -> Any:
        ledger = ContextLedger()
        for call_id, query in batches:
            payload = search_payload(query)
            output = (payload + "\n" + STATUS_LINE
                      if with_status_line else payload)
            ledger.stage(call_id, "search", output,
                         documents_from_search(json.loads(payload)))
        return ledger

    return _build


@pytest.fixture
def run_agent_capture(monkeypatch: pytest.MonkeyPatch,
                      fake_engine: dict[str, list[dict]],
                      ) -> Callable[..., tuple[dict, dict]]:
    """Run ``agent.run_agent`` against a scripted provider, capturing the save.

    ``save_run`` is intercepted rather than allowed to write, because these tests
    assert on the in-memory trajectory/output objects; the on-disk behaviour is
    ``test_incremental_save.py``'s subject. Partial saves are progress-only
    (``validate=False``), so only the final save populates ``captured`` — every
    save is still recorded under ``captured["saves"]``.
    """
    from aus_agent import agent

    def _run(provider: Any, **kwargs: Any) -> tuple[dict, dict]:
        captured: dict[str, Any] = {}
        saves: list[dict[str, Any]] = []

        def save_run(system: str, query: str, *, trajectory: Any, output: Any,
                     **rest: Any) -> dict[str, str]:
            saves.append({"system": system, "query": query,
                          "trajectory": trajectory, "output": output, **rest})
            if rest.get("validate", True):
                captured.update(system=system, query=query,
                                trajectory=trajectory, output=output, **rest)
            return {"trajectory": "trajectory.json", "output": "output.json"}

        monkeypatch.setattr(agent, "make_provider", lambda *a, **kw: provider)
        monkeypatch.setattr(agent, "save_run", save_run)
        summary = agent.run_agent("qid", "research query", **{
            "context_token_budget": 10_000,
            "safety_max_rounds": 20,
            "max_committed_per_step": 3,
            **kwargs,
        })
        captured["saves"] = saves
        return summary, captured

    return _run
