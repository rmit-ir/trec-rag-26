"""The staged/committed protocol as ``run_agent`` actually drives it.

The ledger modules test ``ContextLedger`` in isolation. This one runs the real
loop against a scripted provider and asserts the parts of the protocol that only
exist once the two are wired together:

- compaction reaches the PROVIDER's history (the ledger only returns
  replacement strings — nothing shrinks until ``compact_tool_results`` is
  called with them, and a wrong call id is fatal, which is why the local
  ``StrictScriptedProvider`` is used here);
- the strict trajectory / rich trace split (staged text may appear in
  ``output.json``'s trace but never in ``trajectory.json``);
- the loop's recovery branches — expiry, invalid commit, commit ordering —
  measured in turns, since a turn is the unit of cost this design exists to
  save.

Scope note: ``tests/systems/test_aus_agent.py`` covers the loop's other
branches (report correction, backstops, failed searches, single-engine routing)
against the shared ``stub_search_tool``. What is here instead of there needs the
disjoint alpha/beta/gamma document sets — "keep ``b`` from the alpha batch and
``d`` from the beta batch, compact the rest" is not expressible when every query
returns the same four docids.
"""
from __future__ import annotations

import json
import re
from typing import Any

import pytest

from agent_harness_context.fakes import (
    StrictScriptedProvider,
    call,
    staged_text,
    turn,
)

from agent_harness.context import REJECTION_PREFIX

# Two searches, a split commit plus a third search, a final commit, then a
# report. Deliberately the shape the system prompt asks for (parallel
# complementary queries, commit alongside the next search) so the numbers below
# describe a well-behaved run rather than a contrived one.
RESEARCH_SCRIPT = [
    turn(text="Search two aspects.",
         calls=[call("s1", "search", query="alpha"),
                call("s2", "search", query="beta")],
         input_tokens=100),
    turn(text="Keep the strongest evidence and continue.",
         calls=[call("c1", "commit_context", documents=[
             {"docid": "b", "reason": "direct alpha evidence"},
             {"docid": "d", "reason": "direct beta evidence"}]),
                call("s3", "search", query="gamma")],
         input_tokens=200),
    turn(calls=[call("c2", "commit_context", documents=[
        {"docid": "g", "reason": "fills final gap"}])],
        input_tokens=300),
    turn(text="Research is complete.", input_tokens=400),
    turn(text="Supported finding. [b] [g]", input_tokens=500),
]


@pytest.fixture
def research_run(run_agent_capture) -> dict[str, Any]:
    """One five-turn run, shared by the assertions below.

    Turn 4 is a report with no citations while evidence IS committed, so it is
    refused once and rewritten — that is what makes the second user message in
    ``provider.user_messages`` a correction rather than a fresh task.
    """
    provider = StrictScriptedProvider(list(RESEARCH_SCRIPT))
    summary, captured = run_agent_capture(provider)
    trajectory = captured["trajectory"]
    return {"summary": summary, "captured": captured, "provider": provider,
            "trajectory": trajectory, "trace": trajectory.trace,
            "output": captured["output"]}


# ---------------------------------------------------------------------------
# What the run reports about its own context
# ---------------------------------------------------------------------------
def test_the_run_summary_counts_committed_and_rejected_documents(
        research_run: dict[str, Any]) -> None:
    """These two numbers are how a reviewer reads a run's retrieval discipline.

    Nine documents were staged across three searches and three were retained, so
    ``rejected`` is six. A dedup or expiry regression shows up here first: the
    counts are the only place the whole run's ledger activity is summarized, and
    they are what a sweep across topics aggregates.
    """
    summary = research_run["summary"]
    assert summary["status"] == "completed"
    assert summary["committed_documents"] == 3
    assert summary["rejected_documents"] == 6
    assert research_run["output"]["references"] == ["b", "g"]


def test_context_tokens_track_the_last_turn_not_the_sum(
        research_run: dict[str, Any]) -> None:
    """The stop condition is the CURRENT context size, not cumulative spend.

    The scripted turns report 100..500 input tokens, so the run's context size is
    the final turn's 500 while ``processed`` (billed prefill + output) sums to
    1,550. Summing the former would exhaust the budget after a few turns even
    though the conversation is being compacted back down — which is precisely
    what the staged/committed protocol is for.
    """
    summary = research_run["summary"]
    tokens = research_run["trace"]["summary"]["tokens"]
    assert summary["context_tokens"] == 500
    assert summary["peak_context_tokens"] == 500
    assert tokens["context_tokens"] == 500
    assert tokens["peak_context_tokens"] == 500
    assert tokens["context_budget_tokens"] == 10_000
    assert tokens["input"] == 1_500
    assert tokens["output"] == 50
    assert tokens["processed"] == 1_550


def test_cumulative_token_stats_accumulate_across_turns(
        research_run: dict[str, Any]) -> None:
    """Each step records the spend UP TO it, so a trace can be read as a cost curve.

    Step 0 sits after one 100/10 turn (110 processed); the first commit sits after
    two (110 + 210 = 320). Per-turn numbers alone could not answer "how much had
    this run spent by the time it made that decision", which is the question a
    reviewer asks of an expensive run.
    """
    steps = research_run["trace"]["steps"]
    assert steps[0]["stats"]["cumulative_tokens"]["processed"] == 110
    first_commit = next(s for s in steps if s.get("tool_call_id") == "c1")
    assert first_commit["stats"]["cumulative_tokens"]["processed"] == 320


def test_every_action_step_carries_the_live_budget_view(
        research_run: dict[str, Any]) -> None:
    """The budget view is per-step because the model paces itself off it.

    ``context_budget_tokens`` must be the run's configured budget on every step
    (not the 500k default), and the status line appended to each tool result must
    quote the same number — a mismatch would have the model self-pacing against a
    limit that is not the one being enforced.
    """
    for step in research_run["trace"]["steps"]:
        if step["type"] != "tool_call":
            continue
        assert {"context_tokens", "peak_context_tokens",
                "context_budget_tokens", "elapsed_ms"} <= set(step["stats"])
        assert step["stats"]["context_budget_tokens"] == 10_000
        if isinstance(step["output"], str):
            assert re.search(
                r"\n\[context budget: [\d,]+ / 10,000 tokens "
                r"\(\d+\.\d%\) · elapsed: \d+m \d+s\]$", step["output"])


def test_the_commit_result_the_model_reads_quotes_the_budget_too(
        research_run: dict[str, Any]) -> None:
    """A commit is a tool result like any other, so it carries the budget line.

    The commit turn is exactly when the model decides whether to search again, so
    the reading it gets there is the one that matters most. 200 of 10,000 is the
    usage of the turn just taken, not of the turn being answered.
    """
    assert re.search(
        r"\n\[context budget: 200 / 10,000 tokens \(2\.0%\) · "
        r"elapsed: \d+m \d+s\]$",
        research_run["provider"].content_by_id["c1"])


# ---------------------------------------------------------------------------
# Compaction reaches provider history
# ---------------------------------------------------------------------------
def test_the_provider_history_keeps_only_the_committed_text(
        research_run: dict[str, Any]) -> None:
    """This is the assertion the whole design exists to satisfy.

    ``ContextLedger`` only computes replacement strings; nothing shrinks until the
    loop calls ``compact_tool_results`` with them. Asserting on the ledger's
    return value would pass even if the loop dropped the call on the floor and
    every staged batch stayed in history for the rest of the run.
    """
    compacted = research_run["provider"].content_by_id["s1"]
    assert staged_text("b") in compacted
    assert staged_text("a") not in compacted
    assert f"{REJECTION_PREFIX} a" in compacted


def test_each_staged_batch_is_compacted_exactly_once(
        research_run: dict[str, Any]) -> None:
    """One compaction per batch is what makes Bedrock's rolling cache point safe.

    ``BedrockProvider`` marks everything settled the moment a compaction returns
    (see its module docstring) — rewriting a batch twice would edit bytes behind
    a cache checkpoint and re-bill the whole prefix as a cache write. The
    ``StrictScriptedProvider`` used here also raises on an unknown id, so a
    replacement aimed at the wrong batch fails rather than passing quietly.
    """
    compacted_ids = [sorted(batch) for batch in
                     research_run["provider"].compactions]
    assert compacted_ids == [["s1", "s2"], ["s3"]]


# ---------------------------------------------------------------------------
# The strict / rich artifact split
# ---------------------------------------------------------------------------
def test_the_strict_trajectory_carries_no_viewer_only_fields(
        research_run: dict[str, Any]) -> None:
    """``trajectory.json`` is the submitted artifact and its item keys are fixed.

    Every rich field the trace needs — timings, per-step token stats, the ledger
    decision, the retained documents — is viewer-only. Leaking one into the
    strict items would put a non-schema key in a submitted file, and the ledger's
    ``context``/``documents`` are the two most likely to leak because the loop
    builds them in the same call that records the step.
    """
    trajectory = research_run["trajectory"]
    forbidden = {"t_start", "t_end", "turn", "stats", "documents", "context",
                 "duration_ms", "tokens"}
    for item in trajectory["result"]:
        assert forbidden.isdisjoint(item)
    assert "raw_messages" not in research_run["trace"]


def test_the_trace_does_not_duplicate_the_staged_document_text(
        research_run: dict[str, Any]) -> None:
    """Document text is stored ONCE per run, and not in the rich trace.

    The strict item keeps the tool's own output verbatim (that is the record of
    what the model was shown), so the trace's search step uses the pruned
    ``trace_output`` instead — the same text twice would double a trace that is
    already ~1 MB and that the outputs viewer re-reads on every poll while the
    run is still in flight.
    """
    trace = research_run["trace"]
    assert "full staged text" not in json.dumps(trace["steps"])
    # ...and it IS present in the strict item, which is the deliberate half of
    # the split: the trajectory records the raw tool result the model saw.
    search_item = next(item for item in research_run["trajectory"]["result"]
                       if item.get("tool_name") == "search")
    assert staged_text("a") in search_item["output"]


def test_the_trace_search_step_records_decisions_without_text(
        research_run: dict[str, Any]) -> None:
    """The pruned search step still carries every identifying field.

    Pruning the text must not prune the audit trail: rank, id, docid and score
    are what let a reviewer match a committed document back to the query that
    found it. Text lives on the commit step's ``documents`` instead — attached
    only for what was actually retained.
    """
    search_step = next(step for step in research_run["trace"]["steps"]
                       if step.get("tool_name") == "search")
    assert "documents" not in search_step
    assert all("text" not in result
               for result in search_step["output"]["results"])
    assert all({"rank", "id", "docid", "score"} <= set(result)
               for result in search_step["output"]["results"])


def test_commit_steps_record_their_selection_on_the_trace(
        research_run: dict[str, Any]) -> None:
    """The trace has to say which documents each decision retained, in order.

    This is the run's evidence chain: a citation in the final report is only
    defensible if the trace shows where that docid was committed. Two commits
    here, and the split across them (``[b, d]`` then ``[g]``) is what proves the
    per-step decisions were recorded separately rather than as one final set.
    """
    commits = [step for step in research_run["trace"]["steps"]
               if step.get("tool_name") == "commit_context"]
    assert [c["context"]["committed"] for c in commits] == [["b", "d"], ["g"]]


def test_generation_spans_parent_every_tool_call_of_their_turn(
        research_run: dict[str, Any]) -> None:
    """The trace is a tree: an action must hang off the turn that requested it.

    The viewer draws the run from ``parent_id``, so an action parented to the
    wrong generation shows a decision being made in a turn where the model had
    different information — the exact thing a reader consults the trace to check.
    """
    trace = research_run["trace"]
    generations = {step["turn"]: step for step in trace["steps"]
                   if step["type"] == "generation"}
    assert len(generations) == 5
    assert generations[0]["input"] == {"kind": "initial",
                                       "ref": "trace.input"}
    assert generations[1]["input"]["kind"] == "tool_results"
    for step in trace["steps"]:
        if step["type"] != "tool_call" or "turn" not in step:
            continue
        assert step["parent_id"] == generations[step["turn"]]["id"]


def test_the_conversation_holds_the_task_and_one_correction(
        research_run: dict[str, Any]) -> None:
    """Every extra user message is a turn the run paid for.

    Turn 4's report cites nothing while evidence is committed, so it is refused —
    one correction message. The loop must never *also* inject a "now write the
    final report" prompt: the finishing instruction rides on the commit result
    instead, which costs no turn.
    """
    user_messages = research_run["provider"].user_messages
    assert len(user_messages) == 2
    assert "Research request:" in user_messages[0]
    assert "did not satisfy" in user_messages[1]
    assert "Now write the final" not in "\n".join(user_messages)


def test_the_system_prompt_and_tools_are_the_context_protocol_only(
        research_run: dict[str, Any]) -> None:
    """The model is given the protocol tools and no corpus name.

    Every tool that returns document text must route through the stage/commit
    protocol — that is what bounds context growth. ``get_documents`` qualifies
    (its results are staged exactly like a search batch); an unstaged fetch tool
    would not, and must never be added. Naming the corpus invites the model to
    answer from what it knows about ClimbMix rather than from retrieval.
    """
    provider = research_run["provider"]
    assert {tool["name"] for tool in provider.tools} == {
        "search", "get_documents", "commit_context"}
    assert "ClimbMix" not in provider.system_prompt


# ---------------------------------------------------------------------------
# Budget exhaustion
# ---------------------------------------------------------------------------
def test_the_budget_refuses_retrieval_but_still_honours_the_commit(
        run_agent_capture) -> None:
    """At the budget, bookkeeping is allowed and retrieval is not.

    Refusing the commit as well would strand a staged batch at the exact moment
    context is scarcest — its text would stay in history for the remaining
    report-writing turns. So the commit on the over-budget turn runs and the
    parallel search does not, which is visible as the gap between
    ``tool_call_counts`` (1) and ``tool_call_counts_all`` (2).
    """
    provider = StrictScriptedProvider([
        turn(text="Start.", calls=[call("s1", "search", query="alpha")],
             input_tokens=100),
        turn(text="Select and continue.",
             calls=[call("c1", "commit_context", documents=[
                 {"docid": "b", "reason": "evidence"}]),
                    call("s2", "search", query="beta")],
             input_tokens=160),
        turn(text="Budgeted finding. [b]", input_tokens=100),
    ])
    summary, captured = run_agent_capture(provider, context_token_budget=150)
    trajectory = captured["trajectory"]

    assert summary["status"] == "budget_exhausted"
    assert trajectory["tool_call_counts"]["search"] == 1
    assert trajectory["tool_call_counts_all"]["search"] == 2
    assert trajectory.trace["summary"]["stop_reason"] == (
        "generation_context_tokens")
    generations = [step for step in trajectory.trace["steps"]
                   if step["type"] == "generation"]
    assert generations[1]["stats"]["context_budget_exhausted"] is True
    # The staged batch was still compacted, so the report turns run lean.
    assert REJECTION_PREFIX in provider.content_by_id["s1"]


# ---------------------------------------------------------------------------
# Recovery branches
# ---------------------------------------------------------------------------
def test_an_expiry_explains_itself_once_not_per_document(
        run_agent_capture) -> None:
    """The long explanation goes in ``note``; the documents get two words.

    Regression with a measured cost: the explanation used to be stamped on every
    rejected docid, so a 10-document batch repeated one 60-word sentence ten
    times — 600 words of identical text added to the model's context on every
    expiry, and expiry is a common path.
    """
    provider = StrictScriptedProvider([
        turn(calls=[call("s1", "search", query="alpha")], input_tokens=100),
        # No commit_context on this turn, so the alpha batch expires.
        turn(calls=[call("s2", "search", query="beta")], input_tokens=100),
        turn(calls=[call("c1", "commit_context", documents=[
            {"docid": "d", "reason": "kept"}])], input_tokens=100),
        turn(text="Supported finding. [d]", input_tokens=100),
    ])
    summary, captured = run_agent_capture(provider)

    auto = next(step for step in captured["trajectory"].trace["steps"]
                if step.get("arguments", {}).get("automatic"))
    payload = json.loads(auto["output"].split("\n")[0])
    assert "explicit decision" in payload["note"]
    assert [r["reason"] for r in payload["rejected"]] == (
        ["not retained"] * len(payload["rejected"]))


def test_a_turn_without_a_commit_expires_the_batch_and_still_searches(
        run_agent_capture) -> None:
    """"Retain none" is a decision, so the turn's other actions must run.

    Treating a missing commit as a protocol breach cost a full turn at full
    context, and then a second one when the model dutifully committed against an
    already-expired batch. The expiry is recorded as a NON-failed
    ``commit_context`` so ``tool_call_counts`` does not report it as an error.
    """
    provider = StrictScriptedProvider([
        turn(text="Retrieve evidence.",
             calls=[call("s1", "search", query="alpha")], input_tokens=100),
        turn(text="None of those are useful; search something else.",
             calls=[call("s2", "search", query="beta")], input_tokens=100),
        turn(calls=[call("c1", "commit_context", documents=[
            {"docid": "d", "reason": "the one retained fact"}])],
            input_tokens=100),
        turn(text="Supported finding. [d]", input_tokens=100),
    ])
    summary, captured = run_agent_capture(provider)

    assert summary["status"] == "completed"
    assert summary["committed_documents"] == 1
    # a, b, c expired as a reject-all; e, f were staged by the beta search that
    # still ran, then not selected.
    assert summary["rejected_documents"] == 5
    assert captured["trajectory"]["tool_call_counts"]["search"] == 2
    assert REJECTION_PREFIX in provider.content_by_id["s1"]
    assert "refused" not in provider.content_by_id["s2"]
    auto = [step for step in captured["trajectory"].trace["steps"]
            if step.get("tool_name") == "commit_context"
            and step.get("arguments", {}).get("automatic")]
    assert len(auto) == 1
    assert auto[0]["failed"] is False
    assert "treated as an explicit decision" in auto[0]["output"]


def test_the_commits_position_within_the_turn_does_not_matter(
        run_agent_capture) -> None:
    """A commit listed after a search on the same turn is still honoured.

    The harness applies commits before retrieval regardless of the order the
    model emitted them, so the tool description's "first control action" is
    guidance rather than a gate. Enforcing it literally would refuse turns that
    work perfectly — and the ordering of tool-call blocks is not something a
    model controls reliably.
    """
    provider = StrictScriptedProvider([
        turn(calls=[call("s1", "search", query="alpha")], input_tokens=100),
        turn(calls=[call("s2", "search", query="beta"),
                    call("c1", "commit_context", documents=[
                        {"docid": "b", "reason": "direct evidence"}])],
             input_tokens=100),
        turn(calls=[call("c2", "commit_context", documents=[
            {"docid": "d", "reason": "second fact"}])], input_tokens=100),
        turn(text="Supported finding. [b] [d]", input_tokens=100),
    ])
    summary, captured = run_agent_capture(provider)

    assert summary["status"] == "completed"
    assert summary["committed_documents"] == 2
    assert captured["output"]["references"] == ["b", "d"]


def test_an_invalid_commit_expires_the_batch_rather_than_carrying_it(
        run_agent_capture) -> None:
    """A batch that survived a failed commit could never be resolved.

    The model already used its one turn on that batch, so carrying it forward
    would leave full text in history with no future turn allowed to decide on it.
    Expiring it costs the batch but bounds the context; the trace still records
    the three staged and three rejected docids so the loss is auditable.
    """
    provider = StrictScriptedProvider([
        turn(text="Retrieve evidence.",
             calls=[call("s1", "search", query="alpha")], input_tokens=100),
        turn(text="Invalid selection plus another action.",
             calls=[call("c1", "commit_context", documents=[
                 {"docid": "unknown", "reason": "not actually staged"}]),
                    call("s2", "search", query="beta")],
             input_tokens=100),
        turn(calls=[call("s3", "search", query="gamma")], input_tokens=100),
        turn(calls=[call("c2", "commit_context", documents=[
            {"docid": "g", "reason": "the one retained fact"}])],
            input_tokens=100),
        turn(text="Supported finding. [g]", input_tokens=100),
    ])
    summary, captured = run_agent_capture(provider)

    assert summary["status"] == "completed"
    assert summary["committed_documents"] == 1
    # a, b, c expired after the invalid commit; h, i were staged and unselected.
    assert summary["rejected_documents"] == 5
    assert REJECTION_PREFIX in provider.content_by_id["s1"]
    # The same-turn search is refused, and told why, so the model can retry it.
    assert "batch expired" in provider.content_by_id["s2"]
    commit_steps = [step for step in captured["trajectory"].trace["steps"]
                    if step.get("tool_name") == "commit_context"]
    assert commit_steps[0]["failed"] is True
    assert len(commit_steps[0]["context"]["staged"]) == 3
    assert len(commit_steps[0]["context"]["rejected"]) == 3


def test_a_report_is_accepted_while_a_staged_batch_is_still_open(
        run_agent_capture) -> None:
    """Deciding "I already have enough" must not cost a correction turn.

    The model searches once more, does not like what it sees, and writes the
    report instead of committing. The batch expires silently: refusing the report
    to demand a commit first would spend a full turn on bookkeeping for documents
    nobody wanted — the run's user message count is the assertion that proves it
    did not happen.
    """
    provider = StrictScriptedProvider([
        turn(text="Retrieve evidence.",
             calls=[call("s1", "search", query="alpha")], input_tokens=100),
        turn(calls=[call("c1", "commit_context", documents=[
            {"docid": "b", "reason": "direct evidence"}])], input_tokens=100),
        turn(calls=[call("s2", "search", query="gamma")], input_tokens=100),
        turn(text="Supported finding. [b]", input_tokens=100),
    ])
    summary, captured = run_agent_capture(provider)

    assert summary["status"] == "completed"
    assert captured["output"]["references"] == ["b"]
    assert REJECTION_PREFIX in provider.content_by_id["s2"]
    assert len(provider.user_messages) == 1


# ---------------------------------------------------------------------------
# get_documents stages like search — and records like search
# ---------------------------------------------------------------------------
def test_get_documents_records_parent_docids_not_unit_id_strings(
        run_agent_capture, monkeypatch: pytest.MonkeyPatch) -> None:
    """``returned`` must be hit DICTS here, exactly as the search branch builds.

    ``add_tool_call`` derives the strict ``returned_docids`` with
    ``hit["docid"]``, so a list of unit-id STRINGS makes it index a string with a
    string and raise ``TypeError: string indices must be integers`` — outside the
    branch's ``try``, so it kills the whole topic rather than degrading. That is
    what happened on the 119-topic test runs, and it went unnoticed because
    ``get_documents`` was invoked 0 times across the dev-30 runs: this is the
    first test that drives the branch at all.

    The two granularities are deliberately different and both are asserted: the
    strict trajectory carries PARENT docids (the organizer-facing contract, so a
    chunk hit reports the document it came from), while the rich trace's staged
    context keeps the ``<docid>_p<page>`` unit ids the ledger actually addresses.
    """
    from agent_harness import agent

    def fake_execute(arguments: dict[str, Any], **_: Any) -> tuple:
        ids = list(arguments.get("ids") or [])
        documents = [
            {"id": uid, "docid": uid.rsplit("_p", 1)[0], "kind": "chunk",
             "rank": rank, "score": None, "text": staged_text(uid),
             "metadata": {"source": "get_documents"}}
            for rank, uid in enumerate(ids, 1)]
        out = json.dumps({"ids": ids, "missing": [], "results": [
            {k: doc[k] for k in ("rank", "id", "docid", "kind", "text")}
            for doc in documents]})
        return out, documents, []

    monkeypatch.setattr(agent, "execute_get_documents", fake_execute)

    units = ["shard_1_2_p4", "shard_1_2_p5"]
    provider = StrictScriptedProvider([
        turn(text="Read the pages either side of the hit.",
             calls=[call("g1", "get_documents", ids=units)], input_tokens=100),
        turn(calls=[call("c1", "commit_context", documents=[
            {"docid": units[0], "reason": "the page that answers it"}])],
            input_tokens=100),
        turn(text=f"Supported finding. [{units[0]}]", input_tokens=100),
    ])
    summary, captured = run_agent_capture(provider)
    trajectory = captured["trajectory"]

    assert summary["status"] == "completed"
    item = next(i for i in trajectory["result"]
                if i.get("tool_name") == "get_documents")
    assert item["returned_docids"] == ["shard_1_2", "shard_1_2"]
    step = next(s for s in trajectory.trace["steps"]
                if s.get("tool_name") == "get_documents")
    assert step["failed"] is False
    assert step["context"]["staged"] == units
