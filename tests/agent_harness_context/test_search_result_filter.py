"""``search_result_filter`` (PLAN.md Phase 4c, in
``src/systems/facets_agent/PLAN.md``): a caller-supplied post-search
reduction/reordering pass, applied before staging. The harness-side
contract this file protects (gpt-5.6-terra's review of the plan, point #9):
a filter can only choose WHICH of the ORIGINAL documents to keep and in
what order, plus attach a ``judge_verdict`` label — it can never inject,
duplicate, or mutate content, and any exception must fail open (keep
everything) rather than starve a facet of evidence.
"""
from __future__ import annotations

import json
from typing import Any

from agent_harness_context.fakes import DOC_SETS, call, turn

from agent_harness.agent import SearchResultPass


def _search_payload(provider: Any, call_id: str) -> dict[str, Any]:
    """The search call's result payload AS FIRST STAGED -- from
    ``provider.tool_results`` (one immutable snapshot per turn), not
    ``provider.raw_messages`` (mutated in place once a later commit_context
    compacts this same call's entry)."""
    for turn_results in provider.tool_results:
        for r in turn_results:
            if r["id"] == call_id:
                return json.loads(r["content"].splitlines()[0])
    raise AssertionError(f"no tool result recorded for {call_id!r}")


def _staged_ids(provider: Any, call_id: str) -> list[str]:
    return [r["id"] for r in _search_payload(provider, call_id)["results"]]


REPORT_SCRIPT_TAIL = [
    turn(text="Keep it.", calls=[call("c1", "commit_context", documents=[
        {"docid": "b", "reason": "direct evidence"}])]),
    turn(text="Finding. [b]"),
]


def test_no_filter_is_byte_identical(run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_filter=None)
    assert _staged_ids(provider, "s1") == list(DOC_SETS["alpha"])


def test_a_filter_that_drops_results_actually_removes_them_from_the_ledger(
        run_agent_capture) -> None:
    """The dropped id must be gone from BOTH the text the model reads AND
    the ledger -- committing it afterward must fail, proving it was never
    staged, not just hidden from one view."""
    from agent_harness_context.fakes import StrictScriptedProvider

    def keep_only_a(requirement: str, documents: list[dict]) -> SearchResultPass:
        return SearchResultPass(documents=[{"id": "a"}])

    script = [
        turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
        turn(text="Try to commit a filtered-out id.", calls=[
            call("c1", "commit_context", documents=[
                {"docid": "b", "reason": "should not be committable"}])]),
    ]
    provider = StrictScriptedProvider(list(script))
    summary, captured = run_agent_capture(
        provider, search_result_filter=keep_only_a)
    assert _staged_ids(provider, "s1") == ["a"]
    # committing "b" (filtered out) must be treated as an invalid selection
    # -- the harness compacts the batch as a failure, not a silent no-op.
    c1_result = next(
        m for m in provider.raw_messages
        if isinstance(m, dict) and m.get("tool_call_id") == "c1")
    assert c1_result["is_error"] is True


def test_a_fabricated_id_is_dropped_not_staged(run_agent_capture) -> None:
    """A filter cannot inject a document that was never in the original
    results -- the harness validates ids against the original set (terra's
    review, point #9), not the filter's own claim."""
    from agent_harness_context.fakes import StrictScriptedProvider

    def inject_fake(requirement: str, documents: list[dict]) -> SearchResultPass:
        return SearchResultPass(documents=[
            {"id": "a"}, {"id": "not-a-real-result", "text": "fabricated"}])

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_filter=inject_fake)
    assert _staged_ids(provider, "s1") == ["a"]


def test_a_filter_cannot_mutate_the_original_text(run_agent_capture) -> None:
    """A filter's own copy of a document's text/metadata is IGNORED -- only
    its id and an optional judge_verdict are trusted; the real text always
    comes from the original result."""
    from agent_harness_context.fakes import StrictScriptedProvider

    def rewrite_text(requirement: str, documents: list[dict]) -> SearchResultPass:
        return SearchResultPass(documents=[
            {"id": "a", "text": "REWRITTEN, NOT THE REAL DOCUMENT"},
            {"id": "b"}, {"id": "c"},
        ])

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_filter=rewrite_text)
    payload = _search_payload(provider, "s1")
    assert "REWRITTEN" not in payload["results"][0]["text"]


def test_a_raising_filter_fails_open_and_keeps_everything(
        run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    def boom(requirement: str, documents: list[dict]) -> SearchResultPass:
        raise RuntimeError("judge backend unreachable")

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_filter=boom)
    assert _staged_ids(provider, "s1") == list(DOC_SETS["alpha"])


def test_judge_verdict_annotation_is_carried_onto_the_staged_result(
        run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    def annotate(requirement: str, documents: list[dict]) -> SearchResultPass:
        return SearchResultPass(documents=[
            {"id": d["id"], "judge_verdict": "adjacent_not_relevant"}
            for d in documents
        ], note="none dropped, just labeled")

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_filter=annotate)
    payload = _search_payload(provider, "s1")
    assert all(r["judge_verdict"] == "adjacent_not_relevant"
              for r in payload["results"])
    assert payload["filter_note"] == "none dropped, just labeled"
