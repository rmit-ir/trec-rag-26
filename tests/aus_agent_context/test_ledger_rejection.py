"""Rejection paths: validation, the per-step cap, and ``REJECTION_PREFIX``.

Three ways a staged document ends up compacted rather than retained, each with
its own reason string and each visible to the model:

- **unselected** — the model simply did not list it (the common case);
- **overflow** — it listed more than ``max_documents``, and the tail is cut;
- **invalid selection** — an unstaged docid or a reason-less entry, which raises
  and (in ``run_agent``) expires the whole batch.

The reason strings are asserted verbatim throughout, for two reasons. They are
the model's only feedback about a rejection — it acts on them next turn — and
``rejection_marker`` switches to ``DUPLICATE_PREFIX`` on a *string prefix match*
against the reason, so any rewording silently reclassifies tombstones (see
``test_ledger_core.py::test_rejection_marker_prefix_follows_the_reason``).
"""
from __future__ import annotations

import json

import pytest

from aus_agent_context.fakes import (
    DOC_SETS,
    first_line_json,
    results_by_docid,
    staged_text,
)

from aus_agent.context import DUPLICATE_PREFIX, REJECTION_PREFIX, ContextLedger

UNSELECTED_REASON = "not selected for committed context"


# ---------------------------------------------------------------------------
# Validation — a bad selection raises rather than being silently coerced
# ---------------------------------------------------------------------------
def test_committing_a_docid_outside_the_staged_batch_raises(
        ledger_with) -> None:
    """A hallucinated docid must not become a citable reference.

    ``committed_docids`` is exactly the set the final-report parser accepts
    citations from, so a docid admitted here is a docid the run will happily cite
    in its submitted answer — with no retrieved document behind it. Raising is
    what turns a fabricated id into an expired batch and a correction turn
    instead of an unsupported citation in the output.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError, match="outside the staged"):
        ledger.commit([{"docid": "missing", "reason": "no"}], max_documents=2)


def test_the_error_names_every_unstaged_docid_it_rejected(
        ledger_with) -> None:
    """The message is fed back to the model, so it must name all the offenders.

    ``run_agent`` puts ``f"{type(e).__name__}: {e}"`` straight into the tool
    result. Naming only the first bad id would have the model fix that one and
    re-fail on the next — one wasted round per hallucinated docid, at full
    context size.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError) as excinfo:
        ledger.commit([
            {"docid": "a", "reason": "fine"},
            {"docid": "nope", "reason": "bad"},
            {"docid": "also-nope", "reason": "bad"},
        ], max_documents=3)
    message = str(excinfo.value)
    assert "nope" in message and "also-nope" in message


@pytest.mark.parametrize("reason", [
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace-only"),
])
def test_committing_without_an_evidence_reason_raises(
        ledger_with, reason: str) -> None:
    """The reason requirement is the anti-hoarding control, so it must bind.

    Requiring a distinct evidence reason per document is what stops the model
    retaining the whole batch: it has to articulate what each one uniquely adds.
    Accepting an empty or whitespace-only string makes the requirement free to
    satisfy and the control decorative — and leaves the trace with retentions
    that carry no explanation at all.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError, match="distinct evidence reason"):
        ledger.commit([{"docid": "a", "reason": reason}], max_documents=2)


def test_a_validation_failure_leaves_the_batch_staged(ledger_with) -> None:
    """Raising must not half-apply: the ledger has to survive for the rollback.

    ``run_agent`` catches the exception, restores ``pending``/``committed``/
    ``rejected`` from its own snapshot, and then calls ``expire_staged`` to
    compact the batch properly. A ``commit`` that mutated state before raising
    would leave that recovery compacting a partially-cleared batch — and the
    provider would be asked to rewrite tool results that no longer match.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError):
        ledger.commit([{"docid": "missing", "reason": "no"}], max_documents=2)

    assert ledger.has_staged is True
    assert ledger.staged_docids == ["a", "b", "c"]
    assert ledger.committed_docids == set()
    assert ledger.rejected_docids == set()


def test_an_entry_with_a_blank_docid_is_ignored_not_an_error(
        ledger_with) -> None:
    """A blank docid is dropped silently — the batch still resolves.

    Unlike a *wrong* docid, an empty one carries no claim to validate: there is
    nothing to hallucinate about. Raising would expire the whole batch (losing
    the valid selections alongside it) over what is at worst a malformed tool
    argument, so the entry is skipped and ``b`` is still retained.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([
        {"docid": "", "reason": "nothing"},
        {"docid": "   ", "reason": "nothing"},
        {"docid": "b", "reason": "real evidence"},
    ], max_documents=3)
    assert decision.committed == ["b"]


def test_a_selection_entry_may_omit_the_docid_key_entirely(
        ledger_with) -> None:
    """A missing key behaves as a blank docid, not an ``AttributeError``.

    ``docid`` is declared required in the tool schema, but schema enforcement is
    the provider's and models do emit malformed arguments. ``.get`` with a
    default is what keeps that a dropped entry rather than an exception type the
    caller's ``except`` clause reports to the model as an internal fault.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([
        {"reason": "no docid key at all"},
        {"docid": "a", "reason": "real evidence"},
    ], max_documents=3)
    assert decision.committed == ["a"]


def test_an_entry_may_omit_the_reason_key_and_fails_validation(
        ledger_with) -> None:
    """A missing reason must fail the same way an empty one does.

    Otherwise the anti-hoarding control has a trivial bypass: omit the key
    instead of sending ``""``. Both paths land on the same
    ``missing_reasons`` check because the reason is read with ``.get(...,"")``.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError, match="distinct evidence reason"):
        ledger.commit([{"docid": "a"}], max_documents=3)


# ---------------------------------------------------------------------------
# The per-step maximum
# ---------------------------------------------------------------------------
def test_an_oversized_selection_is_clamped_and_the_tail_explained(
        ledger_with) -> None:
    """Over-selection is clamped rather than refused, and the tail is told why.

    The cap is the hard limit on how fast context can grow; a run that honoured
    a 10-document selection under a cap of 2 would defeat it. But refusing the
    whole call would also throw away two good retentions, so the head is kept and
    the tail gets its own reason — distinct from "not selected", because the model
    *did* select these and needs to know they lost to the cap, not to its
    judgement.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([
        {"docid": "a", "reason": "one"},
        {"docid": "b", "reason": "two"},
        {"docid": "c", "reason": "three"},
    ], max_documents=2)

    assert decision.committed == ["a", "b"]
    assert decision.rejected == [
        {"docid": "c", "reason": "selection exceeded per-step maximum of 2"}]


def test_the_overflow_reason_quotes_the_actual_cap(ledger_with) -> None:
    """The number in the message is the live cap, not a hardcoded string.

    ``max_committed_per_step`` is a run config knob and the same value is
    interpolated into the system prompt. A stale literal here would tell the
    model a limit that differs from the one it was briefed on and the one being
    enforced.

    ``c`` is in the batch but unselected, so the two reason kinds appear side by
    side — the overflow label attaches only to what the cap actually cut.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([
        {"docid": "a", "reason": "one"},
        {"docid": "b", "reason": "two"},
    ], max_documents=1)
    assert decision.committed == ["a"]
    assert decision.rejected == [
        {"docid": "b", "reason": "selection exceeded per-step maximum of 1"},
        {"docid": "c", "reason": UNSELECTED_REASON},
    ]


def test_the_clamp_keeps_the_models_own_priority_order(ledger_with) -> None:
    """The cut follows the model's selection order, so its ranking is respected.

    The model lists documents in the order it values them; cutting by staged rank
    instead would drop the document it named first because the engine happened to
    rank it third. ``committed`` is still reported in staged order (that is the
    trace's contract) — the *selection* order only decides which entries survive
    the cap, which is why both orderings appear in one assertion here.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([
        {"docid": "c", "reason": "most important to me"},
        {"docid": "a", "reason": "second"},
        {"docid": "b", "reason": "least"},
    ], max_documents=2)
    assert decision.committed == ["a", "c"]
    assert [r["docid"] for r in decision.rejected] == ["b"]


def test_a_zero_maximum_rejects_the_whole_selection(ledger_with) -> None:
    """``max_documents=0`` retains nothing, and says so per document.

    Degenerate but reachable via config, and the arithmetic is a slice bound
    (``[:max_documents]``) — an off-by-one that let one document through would
    make a "retain nothing" configuration silently retain something.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([{"docid": "a", "reason": "one"}],
                             max_documents=0)
    assert decision.committed == []
    assert decision.rejected == [
        {"docid": "a", "reason": "selection exceeded per-step maximum of 0"},
        {"docid": "b", "reason": UNSELECTED_REASON},
        {"docid": "c", "reason": UNSELECTED_REASON},
    ]
    assert ledger.committed_docids == set()


# ---------------------------------------------------------------------------
# Reject-all and the unselected reason
# ---------------------------------------------------------------------------
def test_an_empty_selection_rejects_the_whole_batch(ledger_with) -> None:
    """An empty selection is a legitimate decision, not an error.

    "None of these are useful" is the honest outcome of a bad query, and
    ``run_agent`` relies on it: a turn with no ``commit_context`` at all is
    routed through this exact path (``expire_staged`` passes ``[]``). If it
    raised or carried the batch forward, the harness's cheapest recovery would
    become its most expensive one.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([], max_documents=3)

    assert decision.committed == []
    assert [r["docid"] for r in decision.rejected] == ["a", "b", "c"]
    assert {r["reason"] for r in decision.rejected} == {UNSELECTED_REASON}
    assert ledger.committed_docids == set()
    assert ledger.rejected_docids == set(DOC_SETS["alpha"])
    assert ledger.has_staged is False


def test_rejecting_everything_strips_all_text_from_the_tool_result(
        ledger_with) -> None:
    """Reject-all is the case that has to reclaim the entire batch's tokens.

    This is the load-bearing path for the whole design: a fruitless search costs
    nothing beyond the turn it took. Any text left behind here is text the agent
    explicitly declined, carried for the rest of the run — and it is the batch
    size (10 by default), not one document.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([], max_documents=3)
    compacted = decision.replacements["search-1"]

    for docid in DOC_SETS["alpha"]:
        assert staged_text(docid) not in compacted
    for entry in first_line_json(compacted)["results"]:
        assert "text" not in entry
        assert entry["decision"].startswith(REJECTION_PREFIX)


def test_every_staged_batch_gets_a_replacement_even_when_untouched(
        ledger_with) -> None:
    """All pending call ids appear in ``replacements``, one per batch.

    ``run_agent`` hands the dict straight to ``provider.compact_tool_results``,
    and the ledger clears ``pending`` immediately afterwards. A batch omitted
    here is never compacted and can never be compacted later — its full text is
    stranded in provider history for the rest of the run, invisible to every
    other assertion.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "beta"))
    decision = ledger.commit([{"docid": "a", "reason": "kept"}],
                             max_documents=3)
    assert set(decision.replacements) == {"q1", "q2"}


def test_a_custom_unselected_reason_replaces_the_default(ledger_with) -> None:
    """``unselected_reason`` is how ``expire_staged`` explains an expiry.

    The reason is stamped on every rejected docid, so it stays terse — the agent
    docstring records that a shared long explanation turned a 10-document batch
    into 600 words of identical text. This parameter is what separates the terse
    per-document label from the one-off note above it.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([], max_documents=3,
                             unselected_reason="not retained")

    assert {r["reason"] for r in decision.rejected} == {"not retained"}
    entry = results_by_docid(decision.replacements["search-1"])["a"]
    assert entry["reason"] == "not retained"
    # Still an ordinary rejection: only a `duplicate/already committed` prefix
    # switches the marker.
    assert entry["decision"].startswith(REJECTION_PREFIX)


def test_a_custom_reason_that_looks_like_a_duplicate_switches_the_marker(
        ledger_with) -> None:
    """CURRENT BEHAVIOUR — the reason string, not the ledger, picks the marker.

    ``rejection_marker`` (context.py:20-23) dispatches on
    ``reason.startswith("duplicate/already committed")``, so a caller-supplied
    ``unselected_reason`` beginning with that text yields ``DUPLICATE_PREFIX``
    for a docid that was never committed — telling the model to look for full
    text that does not exist.

    Not reachable today: the only callers are ``run_agent`` (``"not retained"``)
    and its invalid-commit path (``"staged batch expired after invalid ..."``).
    Pinned so the coupling is visible if a new expiry reason is ever worded that
    way. Asserting actual behaviour; no ``src/`` change from this migration.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit(
        [], max_documents=3,
        unselected_reason="duplicate/already committed by mistake")
    entry = results_by_docid(decision.replacements["search-1"])["a"]
    assert entry["decision"].startswith(DUPLICATE_PREFIX)
    assert "a" not in ledger.committed_docids


def test_the_rejection_marker_names_the_docid_it_replaced(ledger_with) -> None:
    """Each tombstone's marker names its own docid, not a shared string.

    The marker is the sentence the model reads in place of the document, and
    several tombstones sit side by side in one compacted result. A marker that
    named the wrong docid — or none — would make that list unattributable, and
    the model could not tell which of its candidates it had already dismissed.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([], max_documents=3)
    by_docid = results_by_docid(decision.replacements["search-1"])
    for docid in DOC_SETS["alpha"]:
        assert by_docid[docid]["decision"] == f"{REJECTION_PREFIX} {docid}"


def test_a_rejected_document_is_absent_from_the_decisions_documents(
        ledger_with) -> None:
    """``documents`` carries retained text only — it is the rich-trace payload.

    ``run_agent`` passes ``decision.documents`` on as the step's documents, so a
    rejected document appearing here would put text the agent explicitly declined
    into ``output.json``. The docid still appears in ``rejected``, which is the
    decision record; the two lists are deliberately not symmetric.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([{"docid": "b", "reason": "kept"}],
                             max_documents=3)
    assert [d["docid"] for d in decision.documents] == ["b"]
    assert json.dumps(decision.documents).count(staged_text("a")) == 0


def test_rejecting_a_batch_twice_over_is_not_possible(ledger_with) -> None:
    """A second commit on a cleared ledger is a no-op, not a double rejection.

    ``run_agent`` can reach ``commit`` twice around a recovery path, and the
    provider has already been sent the first call's replacements. A second call
    that re-reported the same rejections would double
    ``summary.rejected_documents`` and hand the provider replacement ids for
    messages it has already settled — which the real backend rejects outright.
    """
    ledger = ledger_with(("search-1", "alpha"))
    first = ledger.commit([], max_documents=3)
    assert len(first.rejected) == 3

    second = ledger.commit([], max_documents=3)
    assert second.staged == []
    assert second.rejected == []
    assert second.replacements == {}


def test_committing_against_an_empty_ledger_returns_an_empty_decision() -> None:
    """The no-op shape ``run_agent`` relies on when nothing is staged.

    The harness answers a stray ``commit_context`` with a "nothing to commit"
    note, and ``expire_staged`` may also be reached with an empty ledger. Both
    need a well-formed ``CommitDecision`` — a ``None`` or a raise here would turn
    a harmless model mistake into a failed run.
    """
    ledger = ContextLedger()
    decision = ledger.commit([], max_documents=3)
    assert decision.staged == []
    assert decision.committed == []
    assert decision.rejected == []
    assert decision.replacements == {}
    assert decision.documents == []
