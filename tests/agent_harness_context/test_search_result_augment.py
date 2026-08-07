"""``search_result_augment`` -- the mirror image of ``search_result_filter``
(see that hook's own test file for the "filter can only narrow, never
inject" contract). This one can only WIDEN a search's staged set: given the
documents a search actually returned, a caller may return extra documents
(each carrying its own real id/text, e.g. an adjacent paginated chunk
fetched via ``tools.get_documents``) to merge in after the originals.
Original hits are never removed, reordered, or mutated; a returned entry
whose id already exists in the original set is dropped as a no-op rather
than treated as an edit; any exception fails open (no augmentation).
"""
from __future__ import annotations

import json
from typing import Any

from agent_harness_context.fakes import DOC_SETS, call, turn


def _search_payload(provider: Any, call_id: str) -> dict[str, Any]:
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


def test_no_augment_is_byte_identical(run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_augment=None)
    assert _staged_ids(provider, "s1") == list(DOC_SETS["alpha"])


def test_an_augment_adding_a_new_document_gets_staged_after_the_originals(
        run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    def add_neighbor(documents: list[dict]) -> list[dict]:
        return [{"id": "z-adjacent", "docid": "z", "text": "neighboring page"}]

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_augment=add_neighbor)
    staged = _staged_ids(provider, "s1")
    assert staged == [*DOC_SETS["alpha"], "z-adjacent"]


def test_augmented_document_is_actually_committable(run_agent_capture) -> None:
    """The added document must be a REAL staged entry, not cosmetic --
    committing it must succeed exactly like an original hit."""
    from agent_harness_context.fakes import StrictScriptedProvider

    def add_neighbor(documents: list[dict]) -> list[dict]:
        return [{"id": "z-adjacent", "docid": "z", "text": "neighboring page"}]

    script = [
        turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
        turn(text="Keep the neighbor.", calls=[call("c1", "commit_context", documents=[
            {"docid": "z-adjacent", "reason": "adjacent context"}])]),
        turn(text="Finding. [z-adjacent]"),
    ]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_augment=add_neighbor)
    c1_result = next(
        m for m in provider.raw_messages
        if isinstance(m, dict) and m.get("tool_call_id") == "c1")
    assert c1_result.get("is_error") is not True


def test_an_id_duplicating_an_original_hit_is_not_re_added(
        run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    def readd_existing(documents: list[dict]) -> list[dict]:
        # documents[0] is already an original hit -- returning it again must
        # be a no-op, not a duplicate staged entry.
        return [dict(documents[0])]

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_augment=readd_existing)
    staged = _staged_ids(provider, "s1")
    assert staged == list(DOC_SETS["alpha"])
    assert len(staged) == len(set(staged))


def test_original_hits_are_never_reordered_by_augmentation(
        run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    def add_two(documents: list[dict]) -> list[dict]:
        return [{"id": "z2", "text": "..."}, {"id": "z1", "text": "..."}]

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_augment=add_two)
    staged = _staged_ids(provider, "s1")
    assert staged[:len(DOC_SETS["alpha"])] == list(DOC_SETS["alpha"])
    assert staged[len(DOC_SETS["alpha"]):] == ["z2", "z1"]


def test_a_raising_augment_fails_open_and_adds_nothing(
        run_agent_capture) -> None:
    from agent_harness_context.fakes import StrictScriptedProvider

    def boom(documents: list[dict]) -> list[dict]:
        raise RuntimeError("fetch backend unreachable")

    script = [turn(text="Search.", calls=[call("s1", "search", query="alpha")]),
              *REPORT_SCRIPT_TAIL]
    provider = StrictScriptedProvider(list(script))
    run_agent_capture(provider, search_result_augment=boom)
    assert _staged_ids(provider, "s1") == list(DOC_SETS["alpha"])
