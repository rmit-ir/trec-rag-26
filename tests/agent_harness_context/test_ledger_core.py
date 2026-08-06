"""``ContextLedger`` mechanics: staging, committing, and what survives verbatim.

The ledger is the one place that decides which document text stays in the model's
context, so it is the highest-value unit in ``aus_agent``: every token the agent
spends after a search is a consequence of this class. This module covers the
happy path and the shape guarantees — a committed document keeps its full text,
the tool result keeps its original JSON shape and its budget footer, and the
ledger's cumulative sets track what has been decided. Duplicate handling lives in
``test_ledger_dedup.py`` and the reject/validate paths in
``test_ledger_rejection.py``.
"""
from __future__ import annotations

import json

import pytest
from agent_harness_context.fakes import (
    STATUS_LINE,
    first_line_json,
    results_by_docid,
    search_payload,
    staged_output,
    staged_text,
)

from agent_harness.context import (
    DUPLICATE_PREFIX,
    REJECTION_PREFIX,
    CommitDecision,
    ContextLedger,
    StagedResult,
    rejection_marker,
)
from agent_harness.tools import documents_from_search


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------
def test_fresh_ledger_has_nothing_staged_or_committed() -> None:
    """A run's first turn must owe no commit decision.

    ``has_staged`` gates a branch in ``run_agent`` that expires the batch and
    burns the turn's other actions. A ledger that reported a phantom batch on
    round one would compact a batch that does not exist and hand the model an
    error before it has done anything.
    """
    ledger = ContextLedger()
    assert ledger.pending == []
    assert ledger.committed_ids == set()
    assert ledger.rejected_ids == set()
    assert ledger.staged_ids == []
    assert ledger.has_staged is False


def test_staging_a_batch_lists_its_docids_in_rank_order(ledger_with) -> None:
    """Rank order is the order the model saw, so it is the order it selects in.

    ``staged_ids`` is what the commit validator checks a selection against
    and what the trace shows as the batch. Reordering it would make the trace
    disagree with the tool result the model actually read.
    """
    ledger = ledger_with(("search-1", "alpha"))
    assert ledger.has_staged is True
    assert ledger.staged_ids == ["a", "b", "c"]
    assert len(ledger.pending) == 1
    assert ledger.pending[0].call_id == "search-1"
    assert ledger.pending[0].tool_name == "search"


def test_staging_an_empty_document_list_is_dropped_entirely() -> None:
    """A zero-hit or failed search must not open a batch nobody can resolve.

    If it did, the next turn would owe a ``commit_context`` for nothing: the
    harness would find ``has_staged`` true, expire the empty batch, and refuse
    or complicate that turn's real work — a whole turn spent on bookkeeping
    caused by a search that returned nothing.
    """
    ledger = ContextLedger()
    ledger.stage("search-1", "search", "{}", [])
    assert ledger.pending == []
    assert ledger.has_staged is False


def test_staged_ids_dedupes_across_batches_keeping_first_order(
        ledger_with) -> None:
    """The commit contract is one decision per docid, not per occurrence.

    Parallel queries overlap constantly, so the same docid arrives from several
    calls. The model is asked to decide about documents; making it name the same
    docid once per occurrence would be both confusing and a validation trap.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "beta"), ("q3", "alpha"))
    assert ledger.staged_ids == ["a", "b", "c", "d", "e", "f"]


def test_staged_result_ids_dedupes_within_one_result() -> None:
    """The batch is keyed on the retrieval-unit id, deduped per result.

    A repeated unit id within one result is one decision, not two — otherwise a
    single selection would appear to leave an occurrence unresolved. Note the
    unit is the *chunk*: two pages of one document are DISTINCT units under
    chunk-native commit, and collapsing to the parent docid happens only at the
    submission boundary (``agent._collapse_to_docs``).
    """
    result = StagedResult(
        call_id="q1", tool_name="search", output="{}",
        documents=[{"id": "a"}, {"id": "a"}, {"id": "b"}])
    assert result.ids == ["a", "b"]

    paged = StagedResult(
        call_id="q2", tool_name="search", output="{}",
        documents=[{"id": "a_p1", "docid": "a"}, {"id": "a_p2", "docid": "a"}])
    assert paged.ids == ["a_p1", "a_p2"]


# ---------------------------------------------------------------------------
# Committing
# ---------------------------------------------------------------------------
def test_commit_keeps_selected_text_and_replaces_rejected_text(
        ledger_with) -> None:
    """The core economics: one document's text is retained, the rest evaporate.

    This single assertion is why the whole staged-context design exists. A
    regression that kept every result's text would silently multiply the run's
    context cost by the batch size (10 results by default), blowing the 500k
    budget in a handful of rounds while every other test still passed.
    """
    ledger = ledger_with(("search-1", "alpha"))

    decision = ledger.commit(
        [{"docid": "b", "reason": "direct evidence"}], max_documents=2)

    compacted_text = decision.replacements["search-1"]
    compacted = first_line_json(compacted_text)
    assert decision.committed == ["b"]
    assert [r["docid"] for r in decision.rejected] == ["a", "c"]
    # Rank order is preserved, so results[1] is still `b` — with its text.
    assert "text" in compacted["results"][1]
    assert "text" not in compacted["results"][0]
    assert compacted["results"][0]["decision"].startswith(REJECTION_PREFIX)
    # The budget footer the agent appended survives compaction verbatim.
    assert compacted_text.endswith(STATUS_LINE)
    assert ledger.has_staged is False


def test_commit_clears_pending_and_updates_the_cumulative_sets(
        ledger_with) -> None:
    """Clearing ``pending`` is what makes a batch resolvable exactly once.

    ``BedrockProvider`` keys its rolling cache checkpoint off this invariant
    (see its module docstring: "the commit that triggers it clears pending, so
    each tool result is compacted exactly once"). A ledger that left the batch
    pending would let a second commit rewrite already-settled history, which the
    provider treats as final — invalidating the cache and corrupting the trace.
    """
    ledger = ledger_with(("search-1", "alpha"))
    ledger.commit([{"docid": "b", "reason": "evidence"}], max_documents=3)
    assert ledger.pending == []
    assert ledger.committed_ids == {"b"}
    assert ledger.rejected_ids == {"a", "c"}


def test_commit_returns_the_selected_documents_with_their_reason(
        ledger_with) -> None:
    """The reason is the audit trail for a retention, and it must survive.

    ``output.json.trace`` records docids and decisions but no document text, so
    ``commit_reason`` is the only surviving explanation of why a run kept a
    document. Losing it leaves a reviewer with a bare docid list and no way to
    judge the agent's selection behaviour.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit(
        [{"docid": "b", "reason": "the distinct contribution"}],
        max_documents=3)

    assert [d["docid"] for d in decision.documents] == ["b"]
    document = decision.documents[0]
    assert document["text"] == staged_text("b")
    assert document["metadata"]["commit_reason"] == "the distinct contribution"
    # ...and the staging metadata documents_from_search built is preserved.
    assert document["metadata"]["query"] == "alpha"


def test_commit_reasons_are_stripped_and_the_first_entry_wins(
        ledger_with) -> None:
    """A model that lists a docid twice gets one deterministic recorded reason.

    Whitespace-only reasons are also the ``missing_reasons`` validation trigger,
    so stripping has to happen before that check — otherwise ``"   "`` passes as
    a distinct evidence reason and the whole point of requiring one is lost.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([
        {"docid": "  b  ", "reason": "  padded reason  "},
        {"docid": "b", "reason": "a later contradictory reason"},
    ], max_documents=3)

    assert decision.committed == ["b"]
    assert (decision.documents[0]["metadata"]["commit_reason"]
            == "padded reason")


def test_commit_order_follows_the_staged_order_not_the_selection_order(
        ledger_with) -> None:
    """Committed/rejected are projections of the batch, not of the model's list.

    Reading the trace means comparing "what the search returned" against "what
    was kept from it"; both lists must therefore be in the same order the batch
    was. Ordering by the selection instead would make a reviewer's diff of the
    two lists meaningless, and makes the strict output's reference order depend
    on how the model happened to enumerate its choices.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([
        {"docid": "c", "reason": "third"},
        {"docid": "a", "reason": "first"},
    ], max_documents=3)
    assert decision.committed == ["a", "c"]
    assert decision.staged == ["a", "b", "c"]


def test_commit_is_chunk_native_and_keeps_the_page_level_unit_id() -> None:
    """The page must survive the commit; doc-level collapse is a later step.

    A reviewer (and any citation-support judgement) needs to know it was page 2
    that supported the claim, so the ledger commits the exact unit id. The
    strict output still cites ``shard_00459_61697`` — but that collapse happens
    at the submission boundary, not here. Committing a bare parent docid must
    NOT silently match a staged chunk.
    """
    payload = json.dumps({
        "query": "alpha",
        "results": [{
            "rank": 1, "id": "shard_00459_61697_p2",
            "docid": "shard_00459_61697", "kind": "chunk", "score": 1.0,
            "text": "the supporting page",
        }],
    })
    ledger = ContextLedger()
    ledger.stage("search-1", "search", payload,
                 documents_from_search(json.loads(payload)))
    assert ledger.staged_ids == ["shard_00459_61697_p2"]

    decision = ledger.commit(
        [{"id": "shard_00459_61697_p2", "reason": "the page"}],
        max_documents=3)

    assert decision.committed == ["shard_00459_61697_p2"]
    assert ledger.committed_ids == {"shard_00459_61697_p2"}

    # The parent docid alone is not a staged unit — it must be rejected rather
    # than resolved to whichever page happened to be staged.
    with pytest.raises(ValueError, match="outside the staged context"):
        ledger.commit([{"docid": "shard_00459_61697", "reason": "the doc"}],
                      max_documents=3)


def test_commit_accepts_the_legacy_docid_key_for_a_doc_level_unit() -> None:
    """Doc-level engines return no separate ``id``, so ``docid`` must still work.

    ``documents_from_search`` falls back to ``docid`` for the unit id, so for an
    unpaginated result the two are equal and a selection keyed on the legacy
    ``docid`` key commits normally.
    """
    ledger = ContextLedger()
    ledger.stage("search-1", "search", "{}", [{"id": "a", "docid": "a",
                                               "text": "t"}])
    decision = ledger.commit([{"docid": "a", "reason": "kept"}],
                             max_documents=3)
    assert decision.committed == ["a"]
    assert ledger.committed_ids == {"a"}


def test_commit_decision_context_is_the_trace_projection(ledger_with) -> None:
    """``context`` is the strict/rich boundary: decisions in, document text out.

    It goes straight onto a trace step, so any extra key leaks here — notably
    ``replacements`` (every rejected document's compacted payload) and
    ``documents`` (full text). The exact key set is asserted because that leak
    would not fail any other test; it would just quietly put document text into
    an artifact the design says never carries it.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([{"docid": "a", "reason": "kept"}],
                             max_documents=3)
    assert decision.context == {
        "staged": ["a", "b", "c"],
        "committed": ["a"],
        "rejected": decision.rejected,
    }
    assert set(decision.context) == {"staged", "committed", "rejected"}


def test_commit_decision_is_constructible_as_a_plain_record() -> None:
    """The dataclass must stay a dumb record with no ledger-derived defaults.

    ``expire_staged`` and the failure paths in ``run_agent`` build and read
    decisions directly. Giving ``CommitDecision`` computed state or required
    extras would couple those recovery paths to a live ledger, which is exactly
    what they cannot assume — they run *because* the ledger was rolled back.
    """
    decision = CommitDecision(staged=["a"], committed=[], rejected=[],
                              replacements={}, documents=[])
    assert decision.context == {"staged": ["a"], "committed": [],
                                "rejected": []}


# ---------------------------------------------------------------------------
# Sequential commits across turns
# ---------------------------------------------------------------------------
def test_committed_ids_accumulate_across_batches(ledger_with) -> None:
    """The committed set is the run's citable universe, built up over turns.

    ``run_agent`` passes ``set(ledger.committed_ids)`` to the final-report
    parser, which drops any citation outside it. A ledger that reset per batch
    would make every document from an earlier round uncitable, and the model's
    correctly-cited report would come back stripped of its references.
    """
    ledger = ledger_with(("q1", "alpha"))
    ledger.commit([{"docid": "a", "reason": "first"}], max_documents=3)
    ledger.stage("q2", "search", staged_output("beta"),
                 documents_from_search(json.loads(search_payload("beta"))))
    ledger.commit([{"docid": "d", "reason": "second"}], max_documents=3)

    assert ledger.committed_ids == {"a", "d"}
    assert ledger.rejected_ids == {"b", "c", "e", "f"}


def test_a_docid_rejected_then_committed_leaves_the_rejected_set(
        ledger_with) -> None:
    """``rejected_ids`` means "never committed", not "some copy was compacted".

    The two sets are written side by side into
    ``trace.summary.context.{committed,rejected}``. Without the
    ``difference_update``, a docid the agent passed on in round one and kept in
    round three appears on both lists at once — a reviewer reading the summary
    cannot tell which decision stood.
    """
    ledger = ledger_with(("q1", "alpha"))
    ledger.commit([{"docid": "a", "reason": "first"}], max_documents=3)
    assert "b" in ledger.rejected_ids

    ledger.stage("q2", "search", staged_output("alpha"),
                 documents_from_search(json.loads(search_payload("alpha"))))
    ledger.commit([{"docid": "b", "reason": "worth keeping after all"}],
                  max_documents=3)

    assert ledger.committed_ids == {"a", "b"}
    assert "b" not in ledger.rejected_ids
    assert ledger.rejected_ids == {"c"}


# ---------------------------------------------------------------------------
# _compact_output shape preservation
# ---------------------------------------------------------------------------
def test_compaction_keeps_the_identifying_fields_of_a_rejected_result(
        ledger_with) -> None:
    """A tombstone has to stay recognisable, or the model re-searches for it.

    The model's own history is its memory of what it has already seen. A
    tombstone that dropped ``docid``/``rank``/``score`` would read as "something
    was here", and the cheapest way for the model to find out what is to run the
    query again — paying the full batch cost a second time to rediscover a
    document it already declined.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([{"docid": "b", "reason": "kept"}],
                             max_documents=3)
    rejected = results_by_docid(decision.replacements["search-1"])["a"]
    assert set(rejected) == {"rank", "id", "docid", "kind", "score",
                             "decision", "reason"}
    assert rejected["rank"] == 1
    assert rejected["kind"] == "document"


def test_compaction_preserves_the_payloads_non_result_fields(
        ledger_with) -> None:
    """The compacted result must still say which query produced it.

    ``query`` and ``k`` are how the model tells its several parallel searches
    apart in history. Dropping them turns three compacted batches into three
    indistinguishable lists of tombstones, and the model can no longer reason
    about which phrasings it has already tried.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = ledger.commit([{"docid": "b", "reason": "kept"}],
                             max_documents=3)
    payload = first_line_json(decision.replacements["search-1"])
    assert payload["query"] == "alpha"
    assert payload["k"] == 10


def test_compaction_without_a_status_line_appends_none(ledger_with) -> None:
    """Compaction re-attaches the budget footer only when one was there.

    ``_compact_output`` splits on the footer's literal marker and re-joins it,
    so a naive implementation invents a trailing newline (or a bare separator)
    for callers that never sent one — ``expire_staged`` and any non-search tool.
    That trailing junk lands in provider history verbatim.
    """
    ledger = ledger_with(("search-1", "alpha"), with_status_line=False)
    decision = ledger.commit([{"docid": "b", "reason": "kept"}],
                             max_documents=3)
    compacted = decision.replacements["search-1"]
    assert "\n" not in compacted
    assert "[context budget:" not in compacted


def test_compaction_leaves_a_non_json_tool_result_untouched() -> None:
    """An unparseable tool result is returned whole rather than destroyed.

    Compaction is a byte-level rewrite of provider history: whatever it returns
    *replaces* the message. Raising or returning a partial value on a payload it
    cannot parse would either kill the run (the harness treats a compaction
    failure as fatal) or blank a message the model still needs.
    """
    ledger = ContextLedger()
    output = "this tool result is not JSON at all"
    ledger.stage("search-1", "search", output,
                 [{"id": "a", "docid": "a", "text": "t"}])
    decision = ledger.commit([], max_documents=3)
    assert decision.replacements["search-1"] == output


def test_compaction_of_a_non_search_tool_reserializes_without_pruning() -> None:
    """Only the ``search`` shape is understood, so other tools keep their text.

    The pruning rule is specific to ``search``'s result schema; the ledger has
    no idea which field of an arbitrary tool's payload is document text.
    Guessing would silently truncate a future tool's output, so the shape is
    round-tripped instead. Documents the blast radius of adding a staged tool.
    """
    ledger = ContextLedger()
    output = json.dumps({"results": [{"docid": "a", "text": "kept whole"}]})
    ledger.stage("call-1", "some_other_tool", output,
                 [{"id": "a", "docid": "a", "text": "kept whole"}])
    decision = ledger.commit([], max_documents=3)
    assert json.loads(decision.replacements["call-1"]) == {
        "results": [{"docid": "a", "text": "kept whole"}]}


@pytest.mark.parametrize("results", [
    pytest.param(["a bare string, not an object"], id="non-dict-entry"),
    pytest.param([{"rank": 1, "text": "no docid at all"}], id="no-docid"),
])
def test_compaction_passes_through_result_entries_it_cannot_identify(
        results: list[object]) -> None:
    """A row with no docid cannot be attributed to a decision, so it is kept.

    Both shapes are reachable from a backend change, and both hit the same
    guard. Dropping such a row would make the compacted result shorter than the
    one the model read, so its ranks stop lining up with what it remembers; an
    unguarded ``raw["docid"]`` would instead raise inside compaction and take
    the run down.
    """
    ledger = ContextLedger()
    output = json.dumps({"results": results})
    ledger.stage("search-1", "search", output, [{"id": "a", "docid": "a"}])
    decision = ledger.commit([], max_documents=3)
    assert first_line_json(decision.replacements["search-1"])["results"] \
        == results


def test_compaction_ignores_a_payload_whose_results_are_not_a_list() -> None:
    """The ``isinstance(..., list)`` guard is what keeps an error envelope safe.

    ``run_search_tool`` answers a backend failure with ``{"error": ...}`` and no
    ``results`` key at all; a malformed one could carry a non-list. Iterating it
    would raise inside compaction, which ``run_agent`` treats as fatal — a
    transient search failure would end the whole run.
    """
    ledger = ContextLedger()
    output = json.dumps({"results": "unexpected shape"})
    ledger.stage("search-1", "search", output, [{"id": "a", "docid": "a"}])
    decision = ledger.commit([], max_documents=3)
    assert first_line_json(decision.replacements["search-1"]) == {
        "results": "unexpected shape"}


# ---------------------------------------------------------------------------
# rejection_marker
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("reason,expected_prefix", [
    pytest.param(None, REJECTION_PREFIX, id="no-reason"),
    pytest.param("", REJECTION_PREFIX, id="empty-reason"),
    pytest.param("not selected for committed context", REJECTION_PREFIX,
                 id="unselected"),
    pytest.param("selection exceeded per-step maximum of 3", REJECTION_PREFIX,
                 id="overflow"),
    pytest.param("duplicate/already committed; later occurrence compacted",
                 DUPLICATE_PREFIX, id="duplicate-later"),
    pytest.param("duplicate/already committed; repeated occurrence within the "
                 "staged batch compacted", DUPLICATE_PREFIX,
                 id="duplicate-parallel"),
])
def test_rejection_marker_prefix_follows_the_reason(
        reason: str | None, expected_prefix: str) -> None:
    """The two markers tell the model two different things about a tombstone.

    ``REJECTION_PREFIX`` says "you judged this irrelevant" — do not fetch it
    again. ``DUPLICATE_PREFIX`` says "you already have this, verbatim, earlier in
    this conversation" — go read it there. Mislabelling the duplicate case makes
    the model believe it rejected evidence it is in fact holding, and it stops
    citing a document it committed.

    The trigger is a string prefix match on the reason (``context.py:21``), so
    every reason the ledger generates is enumerated here: a reworded reason that
    stops matching silently downgrades a duplicate to a rejection.
    """
    marker = rejection_marker("a", reason)
    assert marker == f"{expected_prefix} a"


def test_the_two_prefixes_are_distinguishable() -> None:
    """Neither constant may be a prefix of the other, or the tests go blind.

    Every assertion about compaction is of the form "contains DUPLICATE_PREFIX"
    or "startswith REJECTION_PREFIX". If one constant were reworded into a
    prefix of the other, those checks would pass for both cases and the whole
    duplicate-vs-rejection distinction above would stop being tested at all.
    """
    assert not REJECTION_PREFIX.startswith(DUPLICATE_PREFIX)
    assert not DUPLICATE_PREFIX.startswith(REJECTION_PREFIX)
