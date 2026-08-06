"""``run_agent``'s ``pre_final_hook`` (PLAN.md Phase 4 §7.1, facets_agent's
coverage gate): a caller-supplied check that gets exactly one look at a
would-be-final report before the harness accepts it.

Three things the hook mechanism has to prove, all failure modes the design
was explicit about avoiding (see its param docstring in ``agent.py``):
fires at most once (so it cannot loop), is a true no-op when absent (every
other caller's behavior stays byte-identical), and receives
``last_commit_arguments`` as a normalized dict rather than provider-native
``raw_messages`` (a hook that parsed the latter would only work against one
backend — the bug this test suite exists to keep out).
"""
from __future__ import annotations

from typing import Any

from agent_harness_context.fakes import call, turn

ONE_SHOT_REPORT = [
    turn(text="Search once.", calls=[call("s1", "search", query="alpha")]),
    turn(text="Keep it.", calls=[call("c1", "commit_context", documents=[
        {"docid": "b", "reason": "direct evidence"}])]),
    turn(text="Supported finding. [b]"),
]


def test_hook_absent_is_byte_identical_to_no_hook(run_agent_capture) -> None:
    """The default (no ``pre_final_hook`` passed) must be unaffected — this is
    what makes the parameter safe to add to shared code aus_agent/facet_rag
    never opt into."""
    from agent_harness_context.fakes import StrictScriptedProvider

    summary, captured = run_agent_capture(StrictScriptedProvider(list(ONE_SHOT_REPORT)))
    assert captured["output"]["answer"][0]["text"] == "Supported finding."
    assert summary["status"] == "completed"


def test_hook_returning_none_accepts_the_report_and_fires_once(
        run_agent_capture) -> None:
    """A hook that always returns ``None`` never changes the outcome, and
    ``last_commit_arguments`` reaches it as the normalized dict, not a
    provider-native message."""
    from agent_harness_context.fakes import StrictScriptedProvider

    calls_seen: list[dict[str, Any]] = []

    def hook(context: dict[str, Any]) -> str | None:
        calls_seen.append(context)
        return None

    summary, captured = run_agent_capture(
        StrictScriptedProvider(list(ONE_SHOT_REPORT)), pre_final_hook=hook)
    assert summary["status"] == "completed"
    assert len(calls_seen) == 1
    assert calls_seen[0]["last_commit_arguments"]["documents"] == [
        {"docid": "b", "reason": "direct evidence"}]
    assert calls_seen[0]["query_id"] == "qid"
    assert calls_seen[0]["candidate_sentences"][0]["text"] == "Supported finding."


def test_hook_feedback_sends_the_model_back_exactly_once(
        run_agent_capture) -> None:
    """A hook that objects gets one continuation turn, then is not consulted
    again even if the second attempt would also trip its own check — firing
    at most once is what makes an infinite loop structurally impossible."""
    from agent_harness_context.fakes import StrictScriptedProvider

    script = [
        *ONE_SHOT_REPORT,
        turn(text="Revised finding. [b]"),
    ]
    call_count = 0

    def hook(context: dict[str, Any]) -> str | None:
        nonlocal call_count
        call_count += 1
        return "not good enough, try again"

    provider = StrictScriptedProvider(list(script))
    summary, captured = run_agent_capture(provider, pre_final_hook=hook)
    assert call_count == 1
    assert summary["status"] == "completed"
    assert captured["output"]["answer"][0]["text"] == "Revised finding."
    assert provider.user_messages[-1] == "not good enough, try again"


def test_no_commit_yet_gives_the_hook_last_commit_arguments_none(
        run_agent_capture) -> None:
    """A report accepted with nothing ever committed (the harness's own
    ``allow_uncited`` escape hatch, reached here via an immediate budget hit)
    must not crash a hook that reads ``last_commit_arguments`` — it is
    ``None``, not a missing key."""
    from agent_harness_context.fakes import StrictScriptedProvider

    script = [turn(text="No evidence needed.", input_tokens=100)]
    seen: dict[str, Any] = {}

    def hook(context: dict[str, Any]) -> str | None:
        seen.update(context)
        return None

    # A budget below the scripted turn's own input_tokens makes `finishing`
    # true on turn 0 itself, so the uncited report is allowed immediately
    # rather than needing MAX_UNCITED_REFUSALS rejections first.
    run_agent_capture(
        StrictScriptedProvider(list(script)), pre_final_hook=hook,
        context_token_budget=50)
    assert seen["last_commit_arguments"] is None
