"""``judge_relevance`` (PLAN.md Phase 4b §7.4, in
``src/systems/facets_agent/PLAN.md``): the global, opt-in tool that spins up
a SEPARATE model to check whether staged/committed documents actually
support a requirement.

Two layers, tested separately: ``execute_judge_relevance`` itself (a pure
handler given a ``ContextLedger`` and a fresh mocked judge provider — no
``run_agent`` loop needed) and the harness wiring (``judge_tool`` advertises
the tool only when passed, and the dispatch branch in ``run_agent`` reaches
the handler and survives a scripted call). Keeping these apart means the
harness-level test can mock the handler itself rather than juggling two
different providers (the main loop's and the judge's) sharing one
``make_provider`` monkeypatch.
"""
from __future__ import annotations

import json
from typing import Any

from agent_harness_context.fakes import call, turn

from conftest import ScriptedProvider, model_turn

from agent_harness.tools.judge import (
    JUDGE_RELEVANCE_TOOL, _documents_by_id, execute_judge_relevance)

# ---------------------------------------------------------------------------
# execute_judge_relevance — pure handler, mocked judge provider
# ---------------------------------------------------------------------------
def test_missing_requirement_short_circuits_without_a_model_call(
        monkeypatch, ledger_with) -> None:
    ledger = ledger_with(("s1", "alpha"))
    calls: list[Any] = []
    monkeypatch.setattr(
        "agent_harness.agent.make_provider",
        lambda *a, **kw: calls.append(1) or ScriptedProvider([]))
    out = json.loads(execute_judge_relevance(
        {"requirement": "", "document_ids": ["a"]}, ledger))
    assert "error" in out
    assert not calls


def test_no_matching_document_ids_short_circuits_and_names_them_missing(
        monkeypatch, ledger_with) -> None:
    ledger = ledger_with(("s1", "alpha"))
    calls: list[Any] = []
    monkeypatch.setattr(
        "agent_harness.agent.make_provider",
        lambda *a, **kw: calls.append(1) or ScriptedProvider([]))
    out = json.loads(execute_judge_relevance(
        {"requirement": "something", "document_ids": ["never-staged"]},
        ledger))
    assert "error" in out
    assert out["missing"] == ["never-staged"]
    assert not calls


def test_successful_judge_call_returns_parsed_verdicts(
        monkeypatch, ledger_with) -> None:
    ledger = ledger_with(("s1", "alpha"))
    verdict_json = json.dumps({
        "verdicts": [{"id": "a", "verdict": "relevant",
                      "reason": "names it directly"}],
        "suggested_reformulation": None,
    })
    provider = ScriptedProvider([model_turn(text=verdict_json)])
    monkeypatch.setattr(
        "agent_harness.agent.make_provider", lambda backend, model: provider)
    out = json.loads(execute_judge_relevance(
        {"requirement": "what alpha is", "document_ids": ["a", "b"]}, ledger))
    assert out["verdicts"][0] == {
        "id": "a", "verdict": "relevant", "reason": "names it directly"}
    assert out["missing"] == []
    assert "what alpha is" in provider.user_messages[0]
    assert "[a]" in provider.user_messages[0]


def test_a_markdown_fenced_response_is_still_parsed(
        monkeypatch, ledger_with) -> None:
    """Judge models routinely wrap JSON in ```json fences despite being
    told not to (the same leniency every other JSON-mode caller in this
    repo needs) -- this must not degrade to a parse-error envelope."""
    ledger = ledger_with(("s1", "alpha"))
    fenced = "```json\n" + json.dumps({
        "verdicts": [{"id": "a", "verdict": "irrelevant", "reason": "no"}],
        "suggested_reformulation": "try a narrower phrase",
    }) + "\n```"
    provider = ScriptedProvider([model_turn(text=fenced)])
    monkeypatch.setattr(
        "agent_harness.agent.make_provider", lambda backend, model: provider)
    out = json.loads(execute_judge_relevance(
        {"requirement": "x", "document_ids": ["a"]}, ledger))
    assert out["suggested_reformulation"] == "try a narrower phrase"


def test_a_judge_exception_degrades_to_an_error_envelope(
        monkeypatch, ledger_with) -> None:
    ledger = ledger_with(("s1", "alpha"))

    def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("no creds in this environment")

    monkeypatch.setattr("agent_harness.agent.make_provider", boom)
    out = json.loads(execute_judge_relevance(
        {"requirement": "x", "document_ids": ["a"]}, ledger))
    assert "judge call failed" in out["error"]
    assert "no creds in this environment" in out["error"]


def test_documents_by_id_resolves_committed_and_rejected_alike(
        ledger_with) -> None:
    """A document the model wants judged may already be committed, already
    rejected, or still pending -- ``call_history`` (not ``pending``, which
    clears on commit) is what makes all three resolvable."""
    ledger = ledger_with(("s1", "alpha"))
    ledger.commit([{"id": "a", "reason": "keep"}], max_documents=3)
    by_id = _documents_by_id(ledger)
    assert set(by_id) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Harness wiring — advertising + dispatch, via run_agent_capture
# ---------------------------------------------------------------------------
MINIMAL_SCRIPT = [
    turn(text="Search once.", calls=[call("s1", "search", query="alpha")]),
    turn(text="Keep it.", calls=[call("c1", "commit_context", documents=[
        {"docid": "b", "reason": "direct evidence"}])]),
    turn(text="Finding. [b]"),
]


def test_judge_tool_is_not_advertised_by_default(run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    provider = StrictScriptedProvider(list(MINIMAL_SCRIPT))
    run_agent_capture(provider)
    assert {t["name"] for t in provider.tools} == {
        "search", "get_documents", "commit_context"}


def test_judge_tool_is_advertised_when_opted_in(run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    provider = StrictScriptedProvider(list(MINIMAL_SCRIPT))
    run_agent_capture(provider, judge_tool=JUDGE_RELEVANCE_TOOL)
    assert "judge_relevance" in {t["name"] for t in provider.tools}


def test_a_scripted_judge_relevance_call_reaches_the_handler_and_returns(
        monkeypatch, run_agent_capture) -> None:
    """Proves the dispatch plumbing (a 4th tool-call bucket, ``result_by_id``
    populated for it, no ``KeyError`` at ``add_tool_results``) — the
    handler's OWN logic is already covered above, so this stubs it out
    rather than juggling a second mocked judge provider on top of the
    scripted main one."""
    from agent_harness_context.fakes import StrictScriptedProvider

    seen_calls: list[dict[str, Any]] = []

    def fake_judge(arguments: dict[str, Any], ledger: Any) -> str:
        seen_calls.append(arguments)
        return json.dumps({"verdicts": [], "suggested_reformulation": None})

    monkeypatch.setattr("agent_harness.agent.execute_judge_relevance", fake_judge)

    script = [
        turn(text="Search once.", calls=[call("s1", "search", query="alpha")]),
        # commit_context must resolve the staged batch on the very next turn
        # (or it expires) -- judge_relevance rides alongside it in the same
        # turn, checking the just-committed id, which is the realistic shape
        # (a post-hoc sanity check, not a block on committing).
        turn(text="Keep it, but double-check.", calls=[
            call("c1", "commit_context", documents=[
                {"docid": "b", "reason": "direct evidence"}]),
            call("j1", "judge_relevance",
                 requirement="what alpha is", document_ids=["a", "b"]),
        ]),
        turn(text="Finding. [b]"),
    ]
    provider = StrictScriptedProvider(list(script))
    summary, captured = run_agent_capture(
        provider, judge_tool=JUDGE_RELEVANCE_TOOL)
    assert summary["status"] == "completed"
    assert seen_calls == [
        {"requirement": "what alpha is", "document_ids": ["a", "b"]}]
    j1_result = next(
        m for m in provider.raw_messages
        if isinstance(m, dict) and m.get("tool_call_id") == "j1")
    assert json.loads(j1_result["content"].splitlines()[0]) == {
        "verdicts": [], "suggested_reformulation": None}
