"""The ``commit_context`` tool surface: its schema, ``apply_commit``, ``expire_staged``.

This module sits between the ledger tests and the loop tests. The ledger decides
*what* is retained; ``run_agent`` decides *when* a decision is due. In between,
``tools/commit_context.py`` is the narrow adapter — it validates the model's raw
tool arguments (which are untrusted: a model can send anything the provider will
serialize), builds the payload the model reads back, and provides the
``expire_staged`` entry point every recovery path in the loop goes through.

The tool DEFINITION is tested too, not just the handler. It is the only
instruction the model gets about the protocol beyond the system prompt, and a
provider rejects a malformed ``input_schema`` outright — a run would die at
``start()`` rather than fail a test.
"""
from __future__ import annotations

import pytest

from aus_agent_context.fakes import first_line_json, results_by_docid

from aus_agent.context import REJECTION_PREFIX, ContextLedger
from aus_agent.tools import COMMIT_CONTEXT_TOOL, apply_commit, expire_staged
from aus_agent.tools.commit_context import CommitHandlerResult


# ---------------------------------------------------------------------------
# The tool definition
# ---------------------------------------------------------------------------
def test_the_tool_definition_is_shaped_for_every_provider() -> None:
    """Anthropic-style keys are the contract both backends convert from.

    ``providers/base.py`` documents tool defs as ``name``/``description``/
    ``input_schema``, and each provider maps them to its native schema in
    ``start()`` (Bedrock reads ``t["input_schema"]`` by subscript). A renamed key
    would raise a ``KeyError`` at conversation start, before any test-visible
    behaviour — so the key names are pinned here.
    """
    assert set(COMMIT_CONTEXT_TOOL) == {"name", "description", "input_schema"}
    assert COMMIT_CONTEXT_TOOL["name"] == "commit_context"


def test_the_schema_requires_a_documents_array_of_docid_reason_pairs() -> None:
    """The schema is what makes the provider enforce the reason requirement.

    ``reason`` being ``required`` per item is the first line of the anti-hoarding
    control — the ledger's ``ValueError`` is the second. Dropping it from the
    schema moves every reason-less selection from "the provider rejects it for
    free" to "the agent burns a round on an expired batch".
    """
    schema = COMMIT_CONTEXT_TOOL["input_schema"]
    assert schema["required"] == ["documents"]
    documents = schema["properties"]["documents"]
    assert documents["type"] == "array"
    item = documents["items"]
    assert set(item["properties"]) == {"id", "reason"}
    assert sorted(item["required"]) == ["id", "reason"]


def test_the_description_states_the_one_turn_window_and_the_empty_case() -> None:
    """The description carries the two rules the model gets wrong most.

    Both correspond to expensive recovery paths in ``run_agent``: missing the
    one-turn window expires a batch, and not knowing that ``[]`` is legal makes
    the model invent a selection to avoid sending an empty one. Stating them in
    the tool the model is looking at when it decides is cheaper than either.
    """
    description = COMMIT_CONTEXT_TOOL["description"]
    assert "MOST RECENT" in description
    assert "first control action" in description
    empty_case = (COMMIT_CONTEXT_TOOL["input_schema"]["properties"]
                  ["documents"]["description"])
    assert "empty" in empty_case and "rejects the whole staged batch" in empty_case


def test_the_reason_field_describes_what_distinct_means() -> None:
    """The reason prompt has to define distinctness or it is satisfiable by noise.

    A bare "reason" field invites "this is relevant" for every document, which
    passes the non-empty check and retains the whole batch. Enumerating the kinds
    of distinct contribution is what makes the model compare candidates against
    each other rather than against the query.
    """
    reason = (COMMIT_CONTEXT_TOOL["input_schema"]["properties"]["documents"]
              ["items"]["properties"]["reason"]["description"])
    assert "uniquely contributes" in reason
    for kind in ("evidence", "claim", "perspective", "counter-evidence"):
        assert kind in reason


# ---------------------------------------------------------------------------
# apply_commit — argument handling
# ---------------------------------------------------------------------------
def test_apply_commit_returns_the_decision_and_the_models_payload(
        ledger_with) -> None:
    """Two consumers, one call: the trace gets the decision, the model the payload.

    ``run_agent`` serializes ``payload`` into the tool result and puts
    ``decision.context``/``decision.documents`` on the trace step. Keeping them
    separate is what lets the payload stay small while the trace stays complete —
    the payload must never grow document text, and it is asserted key-by-key here
    for that reason.
    """
    ledger = ledger_with(("search-1", "alpha"))
    handled = apply_commit(ledger, {"documents": [
        {"docid": "b", "reason": "direct evidence"}]},
        max_documents=3, finishing=False)

    assert isinstance(handled, CommitHandlerResult)
    assert handled.decision.committed == ["b"]
    assert set(handled.payload) == {"committed", "rejected"}
    assert handled.payload["committed"] == ["b"]
    assert [r["docid"] for r in handled.payload["rejected"]] == ["a", "c"]


def test_apply_commit_rejects_a_non_list_documents_argument(
        ledger_with) -> None:
    """A malformed ``documents`` must raise before the ledger is touched.

    ``run_agent`` catches this and expires the batch cleanly. Letting a string
    through would have ``commit`` iterate its characters — every one a
    non-dict entry, silently filtered — so a garbled argument would read as an
    empty selection and reject the batch with no error reported to the model.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError, match="documents must be an array"):
        apply_commit(ledger, {"documents": "b"}, max_documents=3,
                     finishing=False)
    assert ledger.has_staged is True


def test_apply_commit_treats_a_missing_documents_key_as_reject_all(
        ledger_with) -> None:
    """An omitted ``documents`` resolves the batch instead of failing the turn.

    The schema marks it required, but models do omit required fields. Defaulting
    to ``[]`` makes that the cheap path (a reject-all, turn continues) rather
    than the expensive one (invalid commit, batch expired, same-turn searches
    refused).
    """
    ledger = ledger_with(("search-1", "alpha"))
    handled = apply_commit(ledger, {}, max_documents=3, finishing=False)
    assert handled.payload["committed"] == []
    assert len(handled.payload["rejected"]) == 3
    assert ledger.has_staged is False


def test_apply_commit_drops_non_dict_entries_before_validating(
        ledger_with) -> None:
    """Junk entries are filtered so one bad element does not cost the batch.

    Without the ``isinstance(item, dict)`` filter, ``commit``'s ``item.get`` would
    raise ``AttributeError`` on a bare string — reported to the model as an
    internal error and expiring a batch whose other selections were perfectly
    valid.
    """
    ledger = ledger_with(("search-1", "alpha"))
    handled = apply_commit(ledger, {"documents": [
        "not a dict",
        None,
        {"docid": "b", "reason": "real evidence"},
    ]}, max_documents=3, finishing=False)
    assert handled.payload["committed"] == ["b"]


def test_apply_commit_propagates_a_validation_error_unchanged(
        ledger_with) -> None:
    """The ledger's ``ValueError`` reaches the caller verbatim, not wrapped.

    ``run_agent`` formats it as ``f"{type(e).__name__}: {e}"`` into the tool
    result, so the model sees the ledger's own wording. Wrapping or re-raising it
    as another type would replace actionable feedback ("cannot commit documents
    outside the staged context: nope") with a generic handler message.
    """
    ledger = ledger_with(("search-1", "alpha"))
    with pytest.raises(ValueError, match="outside the staged context"):
        apply_commit(ledger, {"documents": [
            {"docid": "nope", "reason": "hallucinated"}]},
            max_documents=3, finishing=False)


def test_apply_commit_honours_the_per_step_maximum(ledger_with) -> None:
    """``max_documents`` is threaded through, not re-derived from a default.

    The handler is the only place the run's ``max_committed_per_step`` config
    reaches the ledger. A hardcoded default here would silently ignore the
    configured cap — and the system prompt would still advertise the configured
    number to the model.
    """
    ledger = ledger_with(("search-1", "alpha"))
    handled = apply_commit(ledger, {"documents": [
        {"docid": "a", "reason": "one"},
        {"docid": "b", "reason": "two"},
    ]}, max_documents=1, finishing=False)
    assert handled.payload["committed"] == ["a"]


# ---------------------------------------------------------------------------
# apply_commit — the finishing instruction
# ---------------------------------------------------------------------------
def test_finishing_appends_the_write_the_report_now_instruction(
        ledger_with) -> None:
    """When the budget is spent, the commit result is how the model is told.

    Retrieval is refused from this point on, so without an instruction the model
    would keep searching, keep being refused, and spend the finishing grace
    rounds discovering the state change. Attaching it to the commit result puts
    it in the message the model is already reading.
    """
    ledger = ledger_with(("search-1", "alpha"))
    handled = apply_commit(ledger, {"documents": [
        {"docid": "b", "reason": "evidence"}]},
        max_documents=3, finishing=True)

    assert set(handled.payload) == {"committed", "rejected", "instruction"}
    instruction = handled.payload["instruction"]
    # The report contract is restated because this may be the model's last turn.
    assert "write the final report now" in instruction
    assert "[id] citation markers" in instruction
    assert "only committed evidence" in instruction


def test_no_instruction_is_added_while_research_can_continue(
        ledger_with) -> None:
    """Mid-run commits stay silent, so the instruction keeps its urgency.

    Restating "write the report now" on every commit would train the model to
    ignore it, and would push it to wrap up while it still has budget to search —
    directly degrading the answer.
    """
    ledger = ledger_with(("search-1", "alpha"))
    handled = apply_commit(ledger, {"documents": []},
                           max_documents=3, finishing=False)
    assert "instruction" not in handled.payload


# ---------------------------------------------------------------------------
# expire_staged
# ---------------------------------------------------------------------------
def test_expire_staged_rejects_everything_with_the_given_reason(
        ledger_with) -> None:
    """Expiry is a reject-all with a caller-chosen per-document label.

    Every recovery path in ``run_agent`` funnels through here, and the reason it
    passes is stamped on each rejected docid. ``"not retained"`` is deliberately
    terse: the agent docstring records that sharing the long explanation turned a
    10-document batch into 600 words of identical text in the model's context.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = expire_staged(ledger, max_documents=3, reason="not retained")

    assert decision.committed == []
    assert [r["docid"] for r in decision.rejected] == ["a", "b", "c"]
    assert {r["reason"] for r in decision.rejected} == {"not retained"}
    assert ledger.has_staged is False


def test_expire_staged_compacts_every_pending_batch(ledger_with) -> None:
    """An expiry must reclaim all open batches, not just the newest.

    Parallel searches on one turn open several batches at once, and expiry is the
    path taken when the model fails to resolve them. Compacting only one would
    strand the others' full text in provider history permanently — the ledger
    clears ``pending`` regardless.
    """
    ledger = ledger_with(("q1", "alpha"), ("q2", "beta"))
    decision = expire_staged(ledger, max_documents=3, reason="not retained")

    assert set(decision.replacements) == {"q1", "q2"}
    for call_id in ("q1", "q2"):
        for entry in first_line_json(decision.replacements[call_id])["results"]:
            assert "text" not in entry
            assert entry["decision"].startswith(REJECTION_PREFIX)


def test_expire_staged_records_the_reason_on_each_tombstone(
        ledger_with) -> None:
    """The reason lands next to the marker, so a tombstone explains itself.

    The marker alone says "irrelevant"; the reason distinguishes "you passed on
    this" from "your batch lapsed before you decided". The second is a protocol
    mistake the model can correct, and only the reason tells it which happened.
    """
    ledger = ledger_with(("search-1", "alpha"))
    decision = expire_staged(ledger, max_documents=3,
                             reason="staged batch expired after invalid "
                                    "commit_context")
    entry = results_by_docid(decision.replacements["search-1"])["a"]
    assert entry["reason"] == ("staged batch expired after invalid "
                               "commit_context")


def test_expire_staged_on_an_empty_ledger_is_harmless() -> None:
    """Expiry must be idempotent — the loop can reach it with nothing staged.

    ``run_agent``'s recovery paths do not all re-check ``has_staged`` first, so
    raising here would convert a benign double-expiry into a failed run.
    """
    ledger = ContextLedger()
    decision = expire_staged(ledger, max_documents=3, reason="not retained")
    assert decision.rejected == []
    assert decision.replacements == {}


def test_expire_staged_leaves_previously_committed_documents_alone(
        ledger_with) -> None:
    """An expiry cannot cost the run evidence it already retained.

    Expiry runs on the failure paths, often right after a successful commit in
    an earlier round. ``committed_ids`` is the run's citable universe, so
    clearing or narrowing it here would silently strip references from the final
    report as a side effect of an unrelated protocol slip.
    """
    ledger = ledger_with(("q1", "alpha"))
    ledger.commit([{"docid": "a", "reason": "kept"}], max_documents=3)

    from aus_agent.tools import documents_from_search
    import json as _json
    from aus_agent_context.fakes import search_payload, staged_output

    ledger.stage("q2", "search", staged_output("beta"),
                 documents_from_search(_json.loads(search_payload("beta"))))
    expire_staged(ledger, max_documents=3, reason="not retained")

    assert ledger.committed_ids == {"a"}
