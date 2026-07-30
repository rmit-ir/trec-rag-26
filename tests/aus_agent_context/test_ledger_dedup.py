"""Duplicate suppression: every committed docid stays verbatim exactly once.

``DUPLICATE_PREFIX`` exists because a document can reach the model's context more
than once for two structurally different reasons, and both waste the same tokens:

1. **Across turns** — the model re-searches and re-selects a docid it already
   committed. The commit is dropped (it is already retained) and the new
   occurrence becomes a tombstone.
2. **Within one turn** — two parallel queries both return the docid. Exactly one
   occurrence keeps its text; the rest are tombstoned even though the docid *is*
   committed.

Both paths are reported as rejections with a ``duplicate/already committed``
reason, which is the sole trigger that swaps ``REJECTION_PREFIX`` for
``DUPLICATE_PREFIX`` in the marker (see ``context.rejection_marker``). Getting
this wrong is invisible in the output and doubles the context cost of a batch, so
the assertions here are about *which occurrence* kept its text, not just that one
did.
"""
from __future__ import annotations

import json

from aus_agent_context.fakes import (
    first_line_json,
    results_by_docid,
    search_payload,
    staged_output,
    staged_text,
)

from aus_agent.context import DUPLICATE_PREFIX, REJECTION_PREFIX
from aus_agent.tools import documents_from_search

# Deliberately re-stated rather than imported from ``context``: these are the
# model-facing prose the agent reads, so a reword in ``src/`` should fail a test
# rather than travel silently into the prompt.
LATER_OCCURRENCE_REASON = (
    "duplicate/already committed; later occurrence compacted")
PARALLEL_OCCURRENCE_REASON = (
    "duplicate/already committed; repeated occurrence within the staged batch "
    "compacted")


def _restage(ledger, call_id: str, query: str) -> None:
    """Stage the same query's results again, as a later turn's search would."""
    ledger.stage(call_id, "search", staged_output(query),
                 documents_from_search(json.loads(search_payload(query))))


# ---------------------------------------------------------------------------
# Across turns
# ---------------------------------------------------------------------------
def test_already_committed_docid_is_never_retained_twice(ledger_with) -> None:
    """The across-turns base case: re-selecting a held docid costs no context.

    An agent that re-runs a productive query — the normal way it broadens a
    facet — sees the same top hits again and will happily re-select them. Without
    this filter each re-selection appends a second full copy of the document to
    history, so a document the agent keeps returning to is paid for once per
    round for the rest of the run.

    Note ``a`` leaves ``committed`` entirely rather than being re-committed: the
    retention already happened, so reporting it again would double-count it in
    ``summary.committed_documents``.
    """
    ledger = ledger_with(("first", "alpha"))
    first = ledger.commit([{"docid": "a", "reason": "first distinct fact"}],
                          max_documents=3)
    assert first.committed == ["a"]

    _restage(ledger, "second", "alpha")
    second = ledger.commit([
        {"docid": "a", "reason": "same fact again"},
        {"docid": "b", "reason": "materially different evidence"},
    ], max_documents=3)

    # `a` drops out of the commit list entirely — it is already retained.
    assert second.committed == ["b"]
    assert {"docid": "a", "reason": LATER_OCCURRENCE_REASON} in second.rejected

    by_docid = results_by_docid(second.replacements["second"])
    assert "text" not in by_docid["a"]
    assert DUPLICATE_PREFIX in by_docid["a"]["decision"]
    assert "text" in by_docid["b"]


def test_the_earlier_occurrence_keeps_its_text_across_turns(
        ledger_with) -> None:
    """*Which* copy survives matters: it must be the older, already-cached one.

    The angle the test above does not cover. ``BedrockProvider`` puts its rolling
    cache checkpoint at the settled boundary, so the earlier occurrence sits
    inside the cached prefix. Retaining the newer copy instead would be correct
    on token count and wrong on cost — it rewrites a settled message, invalidating
    the cached prefix and re-billing the entire conversation as cache writes.
    """
    ledger = ledger_with(("first", "alpha"))
    first = ledger.commit([{"docid": "a", "reason": "kept"}], max_documents=3)
    assert staged_text("a") in first.replacements["first"]

    _restage(ledger, "second", "alpha")
    second = ledger.commit([], max_documents=3)
    assert staged_text("a") not in second.replacements["second"]


def test_an_unselected_already_committed_docid_still_reads_as_duplicate(
        ledger_with) -> None:
    """The trigger is the ledger's memory, not the model's selection.

    Third angle: the model does not re-select ``a`` at all. Labelling that
    occurrence a plain rejection would tell the model it judged ``a``
    irrelevant — a document it is still holding and expected to cite. It would
    stop citing committed evidence on the strength of a mislabelled tombstone.

    ``c`` in the same batch pins the contrast: an ordinary unselected document
    still gets ``REJECTION_PREFIX``, so the duplicate label is not just leaking
    onto everything.
    """
    ledger = ledger_with(("first", "alpha"))
    ledger.commit([{"docid": "a", "reason": "kept"}], max_documents=3)

    _restage(ledger, "second", "alpha")
    second = ledger.commit([{"docid": "b", "reason": "new evidence"}],
                           max_documents=3)

    reasons = {item["docid"]: item["reason"] for item in second.rejected}
    assert reasons["a"] == LATER_OCCURRENCE_REASON
    assert reasons["c"] == "not selected for committed context"
    by_docid = results_by_docid(second.replacements["second"])
    assert DUPLICATE_PREFIX in by_docid["a"]["decision"]
    assert by_docid["c"]["decision"].startswith(REJECTION_PREFIX)


def test_a_duplicate_docid_does_not_consume_the_per_step_maximum(
        ledger_with) -> None:
    """Filter order: duplicates are dropped BEFORE the ``max_documents`` clamp.

    Swap the two steps and a wasted selection silently costs real evidence — with
    ``max_documents=2``, "``a`` (already held), ``b``, ``d``" would clamp to
    ``[a, b]``, discard ``a`` as a duplicate, and commit only ``b``. The agent
    loses ``d`` for a whole round and is told it hit the per-step cap, which is
    the one reason it will not simply re-select.

    The negative assertion is the point: no overflow reason may appear at all.
    """
    ledger = ledger_with(("first", "alpha"))
    ledger.commit([{"docid": "a", "reason": "kept"}], max_documents=3)

    _restage(ledger, "second", "alpha")
    ledger.stage("third", "search", staged_output("beta"),
                 documents_from_search(json.loads(search_payload("beta"))))
    second = ledger.commit([
        {"docid": "a", "reason": "already have it"},
        {"docid": "b", "reason": "one"},
        {"docid": "d", "reason": "two"},
    ], max_documents=2)

    assert second.committed == ["b", "d"]
    reasons = {item["docid"]: item["reason"] for item in second.rejected}
    assert reasons["a"] == LATER_OCCURRENCE_REASON
    assert "exceeded per-step maximum" not in json.dumps(second.rejected)


# ---------------------------------------------------------------------------
# Within one staged batch (parallel queries)
# ---------------------------------------------------------------------------
def test_parallel_duplicate_occurrence_is_kept_in_full_only_once(
        ledger_with) -> None:
    """The within-batch case, which no cumulative check can catch.

    Structurally different from the across-turns path above: ``a`` is genuinely
    being committed here — it is not in ``committed_ids`` yet — so the
    already-committed filter never fires. Overlap is the norm rather than the
    exception, because the system prompt actively tells the agent to run
    complementary queries in parallel; two of them hitting the same strong
    document is the expected outcome, not a rare collision.

    ``remaining_to_keep`` is what draws the line: the first occurrence in pending
    order claims the full copy and the rest tombstone. Without it, a docid pays
    once per query that found it, on the very turns the agent fans out widest.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "alpha"))

    decision = ledger.commit(
        [{"docid": "a", "reason": "the one distinct retained fact"}],
        max_documents=3)

    first_a = results_by_docid(decision.replacements["q1"])["a"]
    second_a = results_by_docid(decision.replacements["q2"])["a"]
    # The first occurrence in pending order wins the full copy.
    assert "text" in first_a
    assert "text" not in second_a
    assert DUPLICATE_PREFIX in second_a["decision"]
    assert {"docid": "a",
            "reason": PARALLEL_OCCURRENCE_REASON} in decision.rejected


def test_a_parallel_duplicate_is_reported_once_per_extra_occurrence(
        ledger_with) -> None:
    """Scales past two: N occurrences yield N-1 duplicates and one full copy.

    The angle the two-batch test cannot distinguish — with two batches, "one per
    surplus occurrence" and "one flag per duplicated docid" give the same answer.
    Three separates them, and the count is load-bearing: ``rejected`` is what
    ``summary.rejected_documents`` sums, the number a reviewer reads to judge how
    much of a run's retrieval was redundant. Collapsing the surplus to a single
    entry understates fan-out waste exactly when it is worst.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "alpha"), ("q3", "alpha"))
    decision = ledger.commit([{"docid": "a", "reason": "kept"}],
                             max_documents=3)

    duplicates = [item for item in decision.rejected
                  if item["docid"] == "a"
                  and item["reason"] == PARALLEL_OCCURRENCE_REASON]
    assert len(duplicates) == 2
    kept = [call_id for call_id in ("q1", "q2", "q3")
            if "text" in results_by_docid(decision.replacements[call_id])["a"]]
    assert kept == ["q1"]


def test_an_uncommitted_docid_repeated_across_batches_is_a_plain_rejection(
        ledger_with) -> None:
    """The negative case that keeps ``DUPLICATE_PREFIX`` meaningful.

    Repetition alone is not duplication: what the marker promises is "the full
    text is somewhere earlier in this conversation". For a docid nobody kept
    there is no such copy anywhere, so labelling it a duplicate would send the
    model looking through its history for text that was never retained — and
    exactly one duplicate flag would be reported, inflating the redundancy count
    with an occurrence that cost nothing.

    Both occurrences are asserted, because with an unselected docid neither is
    privileged; the guard is ``elif docid in committed``, and dropping that
    condition is what would break this.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "alpha"))
    decision = ledger.commit([{"docid": "b", "reason": "kept"}],
                             max_documents=3)

    reasons = [item["reason"] for item in decision.rejected
               if item["docid"] == "a"]
    assert reasons == ["not selected for committed context"]
    for call_id in ("q1", "q2"):
        entry = results_by_docid(decision.replacements[call_id])["a"]
        assert entry["decision"].startswith(REJECTION_PREFIX)
        assert "text" not in entry


def test_two_pages_of_one_document_are_independent_commit_decisions() -> None:
    """Chunk-native commit makes the page — not the parent doc — the unit.

    Two chunks of one parent docid in ONE search result list are two DISTINCT
    staged units, so each is decided on its own: commit page 1 and page 2
    survives or dies on its own merits rather than riding along on its parent's
    id. This is what makes a chunk-granularity index safe to commit against —
    under a doc-level unit the two pages collapsed into one decision and the
    unselected page kept its text for free.

    Parent-doc collapse is a submission-format concern only, and lives in
    ``agent._collapse_to_docs``.
    """
    payload = json.dumps({
        "query": "alpha",
        "results": [
            {"rank": 1, "id": "doc_p1", "docid": "doc", "kind": "chunk",
             "score": 1.0, "text": "page one"},
            {"rank": 2, "id": "doc_p2", "docid": "doc", "kind": "chunk",
             "score": 0.5, "text": "page two"},
        ],
    })
    from aus_agent.context import ContextLedger

    ledger = ContextLedger()
    ledger.stage("q1", "search", payload,
                 documents_from_search(json.loads(payload)))
    assert ledger.staged_ids == ["doc_p1", "doc_p2"]

    decision = ledger.commit([{"id": "doc_p1", "reason": "kept"}],
                             max_documents=3)

    # Page 1 committed and keeps its text; page 2 was never selected, so it is
    # rejected and its text is replaced — the whole point of the protocol.
    assert decision.committed == ["doc_p1"]
    assert ledger.committed_ids == {"doc_p1"}
    assert [r["docid"] for r in decision.rejected] == ["doc_p2"]

    results = first_line_json(decision.replacements["q1"])["results"]
    assert results[0]["text"] == "page one"
    assert "text" not in results[1]
    assert results[1]["decision"].startswith(REJECTION_PREFIX)


def test_both_pages_of_one_document_can_be_committed_together() -> None:
    """Committing two pages of one document is legal and keeps both texts.

    Reading adjacent pages of a strong source is encouraged, so the ledger must
    not treat the second page as a duplicate of the first just because they
    share a parent docid.
    """
    payload = json.dumps({
        "query": "alpha",
        "results": [
            {"rank": 1, "id": "doc_p1", "docid": "doc", "kind": "chunk",
             "score": 1.0, "text": "page one"},
            {"rank": 2, "id": "doc_p2", "docid": "doc", "kind": "chunk",
             "score": 0.5, "text": "page two"},
        ],
    })
    from aus_agent.context import ContextLedger

    ledger = ContextLedger()
    ledger.stage("q1", "search", payload,
                 documents_from_search(json.loads(payload)))

    decision = ledger.commit([{"id": "doc_p1", "reason": "page one fact"},
                              {"id": "doc_p2", "reason": "page three fact"}],
                             max_documents=3)

    assert decision.committed == ["doc_p1", "doc_p2"]
    assert decision.rejected == []
    results = first_line_json(decision.replacements["q1"])["results"]
    assert results[0]["text"] == "page one"
    assert results[1]["text"] == "page two"


def test_the_marker_comes_from_the_ledger_not_from_the_reason_wording(
        ledger_with) -> None:
    """Rewording a duplicate reason must not change which marker is used.

    ``rejection_marker`` once inferred duplicate-ness from
    ``reason.startswith(...)``, which coupled the model-facing marker to the exact
    prose of a message intended for humans — so editing the wording would have
    silently downgraded real duplicates to plain rejections. The ledger now says
    ``duplicate=`` outright, and ``DUPLICATE_PREFIX`` is what tells the model its
    full text is still available further up the context.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "alpha"))
    decision = ledger.commit([{"docid": "a", "reason": "kept"}],
                             max_documents=3)

    second_a = results_by_docid(decision.replacements["q2"])["a"]
    assert second_a["decision"].startswith(DUPLICATE_PREFIX)
    # The reason still travels alongside, but it is not what chose the prefix.
    assert second_a["reason"] == PARALLEL_OCCURRENCE_REASON
    # And the occurrence that kept its text is not marked at all.
    assert "decision" not in results_by_docid(decision.replacements["q1"])["a"]


def test_the_duplicate_reason_is_carried_onto_the_tombstone_entry(
        ledger_with) -> None:
    """The tombstone carries the prose reason, not just the marker prefix.

    The prefix says "you already have this"; the reason says *where* — an earlier
    occurrence in this same batch, versus a commit from a previous round. Those
    imply different recovery actions for the model, and the reason is also what a
    reviewer sees in ``trace.steps[].context.rejected``. ``_compact_output``
    attaches it only when one was supplied, so it is worth pinning: the marker
    would still look correct with the explanation silently dropped.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "alpha"))
    decision = ledger.commit([{"docid": "a", "reason": "kept"}],
                             max_documents=3)
    second_a = results_by_docid(decision.replacements["q2"])["a"]
    assert second_a["reason"] == PARALLEL_OCCURRENCE_REASON
