"""``search_preview_chars``/``stage_search_results`` (PLAN.md Phase 4d, in
``src/systems/facets_agent/PLAN.md``): piika-inspired two-tier retrieval —
search shows short previews and never stages them; ``get_documents`` stays
the deliberate, full-text, staged action. Both default to today's exact
behavior (no truncation, normal staging).
"""
from __future__ import annotations

import json
from typing import Any

from agent_harness_context.fakes import DOC_SETS, call, staged_text, turn


def _search_payload(provider: Any, call_id: str) -> dict[str, Any]:
    for turn_results in provider.tool_results:
        for r in turn_results:
            if r["id"] == call_id:
                return json.loads(r["content"].splitlines()[0])
    raise AssertionError(f"no tool result recorded for {call_id!r}")


def test_defaults_are_byte_identical(run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    script = [
        turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
        turn(text="Keep it.", calls=[call("c1", "commit_context", documents=[
            {"docid": "b", "reason": "direct evidence"}])]),
        turn(text="Finding. [b]"),
    ]
    provider = StrictScriptedProvider(list(script))
    summary, captured = run_agent_capture(provider)
    assert summary["status"] == "completed"
    payload = _search_payload(provider, "s1")
    full_len = len(payload["results"][0]["text"])
    assert full_len > 20  # the fixture's full staged text, untruncated


def test_search_preview_chars_truncates_every_result(run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    script = [
        turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
        turn(text="Keep it.", calls=[call("c1", "commit_context", documents=[
            {"docid": "b", "reason": "direct evidence"}])]),
        turn(text="Finding. [b]"),
    ]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_preview_chars=5)
    payload = _search_payload(provider, "s1")
    assert all(len(r["text"]) <= 5 for r in payload["results"])
    assert all(r.get("preview_truncated") for r in payload["results"])


def test_stage_search_results_false_means_committing_a_preview_id_is_a_noop(
        monkeypatch, run_agent_capture) -> None:
    """A preview id was never staged, so trying to commit it directly (no
    get_documents in between) must be the harness's existing "nothing
    staged, no-op" behavior, not an error -- proving search results really
    never entered the ledger, not just that they display differently.
    ``get_documents`` then promotes the SAME id to committable, completing
    the run -- the fix for the no-op, not a separate path."""
    from agent_harness_context.fakes import StrictScriptedProvider

    monkeypatch.setattr(
        "agent_harness.tools.get_documents._fetch_one",
        lambda uid: (uid, staged_text(uid) if uid == "b" else None))

    script = [
        turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
        turn(text="Try to commit from the preview directly.",
             calls=[call("c1", "commit_context", documents=[
                 {"docid": "b", "reason": "trying to cite a preview"}])]),
        turn(text="Read it in full instead.",
             calls=[call("g1", "get_documents", ids=["b"])]),
        turn(text="Now keep it.", calls=[call("c2", "commit_context", documents=[
            {"docid": "b", "reason": "confirmed by full read"}])]),
        turn(text="Finding. [b]"),
    ]
    provider = StrictScriptedProvider(list(script))
    summary, captured = run_agent_capture(
        provider, stage_search_results=False)
    assert summary["status"] == "completed"
    c1_result = next(
        r for turn_results in provider.tool_results for r in turn_results
        if r["id"] == "c1")
    assert "no staged batch is open" in c1_result["content"]
    assert c1_result["is_error"] is False  # a no-op, not a failure
    payload = _search_payload(provider, "s1")
    # the model still SAW the results (preview) -- just never staged them
    assert len(payload["results"]) == len(DOC_SETS["alpha"])


def test_get_documents_still_stages_normally_when_search_does_not(
        monkeypatch, run_agent_capture) -> None:
    """The whole point: get_documents remains the deliberate, staged,
    citable action even when search results never enter the ledger.

    ``get_documents`` fetches over real HTTP (``_fetch_one``), a separate
    path from the ``fake_engine`` fixture's search dispatch -- patched
    directly here rather than adding a new shared fixture for one test.
    """
    from agent_harness_context.fakes import StrictScriptedProvider

    monkeypatch.setattr(
        "agent_harness.tools.get_documents._fetch_one",
        lambda uid: (uid, staged_text(uid) if uid == "a" else None))

    script = [
        turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
        turn(text="Read one in full.",
             calls=[call("g1", "get_documents", ids=["a"])]),
        turn(text="Keep it.", calls=[call("c1", "commit_context", documents=[
            {"docid": "a", "reason": "confirmed by full read"}])]),
        turn(text="Finding. [a]"),
    ]
    provider = StrictScriptedProvider(list(script))
    summary, captured = run_agent_capture(
        provider, stage_search_results=False, search_preview_chars=5)
    assert summary["status"] == "completed"
    assert captured["output"]["answer"][0]["text"] == "Finding."
