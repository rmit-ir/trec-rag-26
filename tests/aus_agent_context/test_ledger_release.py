"""``ContextLedger.release_committed`` — dropping a document AFTER it was
committed, normally because a better one replaced it.

Unlike everything in ``test_ledger_core.py``/``test_ledger_dedup.py``, this is
not scoped to the currently staged batch: a released id can have been
committed on any earlier turn, so the ledger has to recompact a HISTORICAL
tool result — one whose call is no longer in ``pending`` at all. That is the
one thing these tests exist to prove works, on top of the ordinary
committed/rejected bookkeeping ``commit`` already covers.
"""
from __future__ import annotations

import json

import pytest
from aus_agent_context.fakes import (
    STATUS_LINE,
    first_line_json,
    results_by_docid,
    search_payload,
    staged_output,
)

from aus_agent.context import RELEASE_PREFIX, ContextLedger, rejection_marker
from aus_agent.tools import documents_from_search


def test_release_recompacts_the_original_historical_call(ledger_with) -> None:
    """The released id's full text must disappear from the call that held it,
    even though that call is long out of ``pending`` by the time it happens.
    """
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([{"docid": "b", "reason": "kept"}], max_documents=3)
    assert ledger.committed_ids == {"b"}
    assert ledger.pending == []  # the originating call is no longer staged

    decision = ledger.release_committed(
        [{"id": "b", "reason": "a later document says this more precisely"}])

    assert decision.released == [
        {"docid": "b", "reason": "a later document says this more precisely"}]
    entry = results_by_docid(decision.replacements["search-1"])["b"]
    assert "text" not in entry
    assert entry["decision"] == f"{RELEASE_PREFIX} b"
    assert entry["reason"] == "a later document says this more precisely"


def test_release_updates_the_cumulative_sets(ledger_with) -> None:
    """A released id must stop being citable and start reading as declined."""
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([{"docid": "b", "reason": "kept"}], max_documents=3)
    ledger.release_committed([{"id": "b", "reason": "superseded"}])

    assert ledger.committed_ids == set()
    assert "b" in ledger.rejected_ids


def test_release_leaves_other_committed_units_from_the_same_call_alone(
        ledger_with) -> None:
    """Releasing one unit must not disturb a sibling still committed from the
    SAME original search call.

    ``_compact_output`` is recomputed from scratch for the affected call, so
    this is the test that the recompute correctly re-derives "keep" for
    everything except the one unit actually being released.
    """
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([
        {"docid": "a", "reason": "kept-1"},
        {"docid": "b", "reason": "kept-2"},
    ], max_documents=3)

    decision = ledger.release_committed(
        [{"id": "b", "reason": "superseded"}])

    payload = first_line_json(decision.replacements["search-1"])
    kept = results_by_docid(decision.replacements["search-1"])["a"]
    assert "text" in kept  # "a" is untouched
    released = results_by_docid(decision.replacements["search-1"])["b"]
    assert "text" not in released
    assert payload["query"] == "alpha"  # non-result fields still round-trip


def test_release_only_recompacts_the_call_that_actually_holds_the_text(
        ledger_with) -> None:
    """A release must not touch an unrelated call's history.

    Two separate turns each commit a different docid from a different search
    call; releasing the first must leave the second's compacted output
    byte-identical.
    """
    ledger = ledger_with(("q1", "alpha"))
    ledger.commit([{"docid": "a", "reason": "first"}], max_documents=3)

    ledger.stage("q2", "search", staged_output("beta"),
                documents_from_search(json.loads(search_payload("beta"))))
    ledger.commit([{"docid": "d", "reason": "second"}], max_documents=3)
    assert ledger.committed_ids == {"a", "d"}

    decision = ledger.release_committed(
        [{"id": "a", "reason": "superseded"}])

    # Only q1 (which held "a") is recompacted -- q2 never appears at all, so
    # whatever it currently holds for "d" is left completely alone.
    assert set(decision.replacements) == {"q1"}
    assert ledger.committed_ids == {"d"}


def test_release_recomputes_from_the_original_text_not_a_prior_compaction(
        ledger_with) -> None:
    """Releasing must key off the ORIGINAL full-text output, not whatever the
    provider currently holds -- proving the recompute-from-scratch design
    (``call_history``) rather than a patch-in-place that would need reading
    provider state back out.
    """
    ledger = ledger_with(("search-1", "alpha"))
    first = ledger.commit([{"docid": "a", "reason": "kept-a"}],
                          max_documents=3)
    # "b" and "c" are already tombstoned here -- release must still recompute
    # correctly using stored history, not this (rejected, not kept) output.
    assert "text" not in results_by_docid(first.replacements["search-1"])["b"]

    decision = ledger.release_committed(
        [{"id": "a", "reason": "superseded"}])
    payload = first_line_json(decision.replacements["search-1"])
    assert payload["query"] == "alpha"
    for entry in payload["results"]:
        assert "text" not in entry


def test_release_preserves_the_status_line(ledger_with) -> None:
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([{"docid": "b", "reason": "kept"}], max_documents=3)
    decision = ledger.release_committed([{"id": "b", "reason": "superseded"}])
    assert decision.replacements["search-1"].endswith(STATUS_LINE)


def test_release_rejects_an_id_that_was_never_committed(ledger_with) -> None:
    """A release must name something the ledger actually kept in full.

    Otherwise the model could "release" a staged-but-not-yet-decided id to
    dodge the ordinary commit/reject decision entirely.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError, match="not currently committed"):
        ledger.release_committed([{"id": "a", "reason": "whatever"}])


def test_release_rejects_a_missing_reason(ledger_with) -> None:
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([{"docid": "b", "reason": "kept"}], max_documents=3)
    with pytest.raises(ValueError, match="needs a reason"):
        ledger.release_committed([{"id": "b", "reason": "  "}])


def test_release_accepts_the_legacy_docid_key(ledger_with) -> None:
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([{"docid": "b", "reason": "kept"}], max_documents=3)
    decision = ledger.release_committed(
        [{"docid": "b", "reason": "superseded"}])
    assert decision.released == [{"docid": "b", "reason": "superseded"}]


def test_a_released_document_can_be_recommitted_later(ledger_with) -> None:
    """Releasing is a decision, not a permanent ban -- the agent may change
    its mind again if the document turns out to matter after all."""
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([{"docid": "b", "reason": "kept"}], max_documents=3)
    ledger.release_committed([{"id": "b", "reason": "superseded"}])
    assert ledger.committed_ids == set()

    ledger.stage("search-2", "search", staged_output("alpha"),
                documents_from_search(json.loads(search_payload("alpha"))))
    decision = ledger.commit([{"docid": "b", "reason": "worth it after all"}],
                             max_documents=3)
    assert decision.committed == ["b"]
    assert ledger.committed_ids == {"b"}


def test_rejection_marker_released_takes_precedence_over_duplicate() -> None:
    """A released unit gets its own distinct wording, not the duplicate one.

    The model needs to tell "I released this on purpose" apart from "a full
    copy already lives elsewhere" -- conflating them would make a released
    document look like it is still available to read somewhere in history.
    """
    marker = rejection_marker("a", "duplicate/already committed; later "
                              "occurrence compacted", duplicate=True,
                              released=True)
    assert marker == f"{RELEASE_PREFIX} a"
