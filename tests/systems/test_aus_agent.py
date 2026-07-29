"""End-to-end coverage for the ``src/systems/aus_agent`` AGENT LOOP.

Scope note: ``ContextLedger`` has its own unit suite (``tests/aus_agent_context``);
this file exercises ``agent.run_agent`` — the ``while True`` loop, its protocol
branches, and the artifacts it writes — plus the pure helpers the loop's
correctness rests on (``_parse_final_prose``, ``_map_citations``,
``_usage_token_stats``).

Two things make the loop testable offline:

- ``ScriptedProvider`` (root conftest) implements the full ``Provider``
  contract, so ``make_provider`` is monkeypatched to hand it back and no SDK,
  key, or socket is involved;
- ``stub_search_tool`` replaces only the engine dispatch, so the AUS search
  adapter (per-result truncation, staging, ``seen_docids``) stays under test.

The loop has no bounded round list — it runs until the model produces an
acceptable final report or a backstop fires — so several tests here exist purely
to prove **termination**: a scripted model that never satisfies the report
contract must stop, not hang. Those are the ones worth reading first.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn, tool_call

from aus_agent import agent as agent_mod
from aus_agent.agent import (
    FINISHING_ROUNDS_GRACE,
    MAX_REPORT_WORDS,
    MAX_UNCITED_REFUSALS,
    _collapse_to_docs,
    _map_citations,
    _parse_final_prose,
    _usage_token_stats,
    make_provider,
    run_agent,
)

QID = "mock_aus_001"
QUERY = "How effective is congestion pricing at reducing traffic?"
D = CLIMBMIX_DOCIDS


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch,
          stub_search_tool: dict[str, list[dict[str, Any]]]
          ) -> Callable[..., dict[str, Any]]:
    """Run ``run_agent`` against a scripted provider; return everything written.

    Every test in this module goes through here, so the provider substitution
    (``make_provider`` -> ``ScriptedProvider``) happens in exactly one place and
    a test body is just its script plus its assertions.
    """
    def _drive(script: list[dict[str, Any]] |
               Callable[[str, int], dict[str, Any]], *,
               query_id: str = QID, query: str = QUERY,
               **kwargs: Any) -> dict[str, Any]:
        provider = ScriptedProvider(script)
        monkeypatch.setattr(agent_mod, "make_provider",
                            lambda backend, model: provider)
        kwargs.setdefault("k", 2)
        kwargs.setdefault("safety_max_rounds", 20)
        summary = run_agent(query_id, query, **kwargs)
        trajectory = json.loads(summary["paths"]["trajectory"].read_text())
        output = json.loads(summary["paths"]["output"].read_text())
        return {"summary": summary, "provider": provider,
                "trajectory": trajectory, "output": output,
                "trace": output["trace"], "calls": stub_search_tool}
    return _drive


# The canonical three-turn run: search, commit two documents, cited report.
HAPPY_SCRIPT = [
    model_turn(reasoning=["I need evidence on both revenue and equity."],
               tool_calls=[tool_call(
                   "search",
                   {"query": "congestion pricing revenue",
                    "search_engine": "semantic"}, id="s1")]),
    model_turn(text="Two of those are worth keeping.",
               tool_calls=[tool_call("commit_context", {"documents": [
                   {"docid": D[0], "reason": "revenue allocation"},
                   {"docid": D[1], "reason": "who pays"}]}, id="c1")]),
    model_turn(text=(f"Toll revenue funds the capital plan [{D[0]}].\n"
                     f"Peak-period drivers earn more than transit riders "
                     f"[{D[1]}].")),
]


@pytest.fixture
def happy_run(drive: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    """One completed search -> commit -> report run, shared by the asserts below."""
    return drive(list(HAPPY_SCRIPT))


# ---------------------------------------------------------------------------
# Happy path: the loop, the protocol, the artifacts
# ---------------------------------------------------------------------------
def test_happy_run_completes_in_exactly_the_scripted_turns(
        happy_run: dict[str, Any]) -> None:
    """Three provider turns must be enough for a compliant model.

    ``ScriptedProvider`` raises when over-consumed, so a regression that adds a
    bookkeeping round (the failure mode the commit protocol has been tuned
    against twice — see the no-op/expire comments in ``agent.py``) surfaces here
    as an exhausted script rather than as a quietly costlier run.
    """
    assert happy_run["summary"]["status"] == "completed"
    assert happy_run["provider"].turn_index == 3
    assert happy_run["provider"].remaining == 0


def test_happy_run_writes_both_artifacts_and_no_violations_file(
        happy_run: dict[str, Any]) -> None:
    """A submission-ready run leaves no ``output.violations.json`` behind.

    ``save_run`` only writes that file when the output breaks the track schema,
    so its absence is the machine-checkable claim that this run could be
    exported as-is.
    """
    paths = happy_run["summary"]["paths"]
    assert paths["trajectory"].exists()
    assert paths["output"].exists()
    assert "violations" not in paths


def test_happy_run_output_passes_track_validation(
        happy_run: dict[str, Any]) -> None:
    """Belt-and-braces on the above: validate the artifact as re-read from disk.

    ``save_run`` validates the in-memory object; this proves the JSON round trip
    did not change anything the validator cares about.
    """
    from ragrun import validate_rag_output

    assert validate_rag_output(happy_run["output"]) == []


def test_happy_run_strict_item_kinds(happy_run: dict[str, Any]) -> None:
    """The organizer-facing trajectory is an interleaved reasoning/action log.

    Reasoning appears as its own item and the second turn's *narration* (text
    emitted alongside tool calls) is folded in as reasoning too — the
    ``narration_as_reasoning`` path. A regression that dropped narration would
    silently lose the model's stated rationale for each commit.
    """
    kinds = [item["type"] for item in happy_run["trajectory"]["result"]]
    assert kinds == ["reasoning", "tool_call", "reasoning", "tool_call",
                     "output_text"]


def test_happy_run_tool_call_counts(happy_run: dict[str, Any]) -> None:
    """``commit_context`` is counted as a tool call like retrieval is.

    It is a local control, not a backend call, but the trajectory must still
    show it: it is the only record of which evidence the agent chose to retain.
    """
    assert happy_run["trajectory"]["tool_call_counts"] == {
        "search": 1, "commit_context": 1}
    assert happy_run["trajectory"]["tool_call_counts_all"] == {
        "search": 1, "commit_context": 1}


def test_happy_run_retrieved_docids_cover_the_whole_batch(
        happy_run: dict[str, Any]) -> None:
    """``retrieved_docids`` is everything SEEN, not everything kept.

    The distinction matters for the trajectory's audit story: two documents were
    committed, but the run must own having read all four — that is what makes
    "rejected" a decision rather than an omission.
    """
    assert set(happy_run["trajectory"]["retrieved_docids"]) == set(D[:2])
    assert happy_run["summary"]["committed_documents"] == 2


def test_happy_run_references_are_the_committed_cited_docids(
        happy_run: dict[str, Any]) -> None:
    """Citations may only name evidence the agent explicitly retained.

    This is the system's central correctness claim (module docstring: "Every
    citation must identify evidence returned by the available retrieval tools
    and explicitly retained by the agent"), and it is enforced twice — in
    ``_parse_final_prose`` against the committed set, then again in
    ``_map_citations``.
    """
    assert happy_run["output"]["references"] == [D[0], D[1]]
    assert happy_run["output"]["answer"] == [
        {"text": "Toll revenue funds the capital plan.", "citations": [0]},
        {"text": "Peak-period drivers earn more than transit riders.",
         "citations": [1]},
    ]


def test_happy_run_every_reference_is_cited(happy_run: dict[str, Any]) -> None:
    """An uncited reference is a spec violation, and it fails silently.

    The run still completes and the answer still reads fine; only the validator
    notices. Asserting it per-system is cheaper than finding it at export time.
    """
    references = happy_run["output"]["references"]
    cited = {c for s in happy_run["output"]["answer"] for c in s["citations"]}
    assert cited == set(range(len(references)))


def test_happy_run_citation_markers_are_stripped_from_the_answer(
        happy_run: dict[str, Any]) -> None:
    """The organizer schema carries citations as indices, never as inline text.

    A leaked ``[docid]`` marker would be scored as part of the sentence by the
    nugget/answer judges.
    """
    assert all("[" not in s["text"] for s in happy_run["output"]["answer"])


def test_happy_run_search_is_routed_with_the_model_engine_and_k(
        happy_run: dict[str, Any]) -> None:
    """The model's ``search_engine`` selection reaches the dispatch table.

    With two engines enabled, styling a query for the wrong backend wastes the
    call — so engine routing is behaviour, not plumbing.
    """
    assert happy_run["calls"] == {
        "semantic": [{"query": "congestion pricing revenue", "k": 2}]}


def test_happy_run_provider_conversation_shape(
        happy_run: dict[str, Any]) -> None:
    """One continuous conversation: no corrective user message was needed.

    A compliant run sends exactly the initial task prompt; every extra user
    message is a refused turn. Tool results are answered in one batch per turn,
    which is what the provider APIs require (an unanswered ``tool_use`` is a
    hard provider error).
    """
    provider = happy_run["provider"]
    assert len(provider.user_messages) == 1
    assert QUERY in provider.user_messages[0]
    assert [t["name"] for t in provider.tools] == [
        "search", "get_documents", "commit_context"]
    assert [[r["id"] for r in batch] for batch in provider.tool_results] == [
        ["s1"], ["c1"]]
    assert all(not r["is_error"] for batch in provider.tool_results
               for r in batch)


def test_happy_run_commit_compacts_the_staged_batch_in_provider_history(
        happy_run: dict[str, Any]) -> None:
    """Compaction is what keeps the context bounded, and it must be observable.

    ``commit_context`` rewrites the search result already in provider history so
    rejected documents shrink to markers. If this silently stopped happening the
    run would still complete — just at several times the token cost, which is
    the whole point of the system.
    """
    assert [sorted(c) for c in happy_run["provider"].compactions] == [["s1"]]
    compacted = happy_run["provider"].compactions[0]["s1"]
    assert D[0] in compacted           # committed: full text retained
    assert "passage" not in compacted or D[1] not in compacted


def test_happy_run_trace_records_the_full_input_contract(
        happy_run: dict[str, Any]) -> None:
    """The rich trace must be self-contained enough to explain a run later.

    Without the system prompt and tool definitions captured, a trace cannot be
    reproduced or diffed against a later prompt revision.
    """
    trace_input = happy_run["trace"]["input"]
    assert set(trace_input) == {"system_prompt", "user_message", "tools"}
    assert "commit_context" in trace_input["system_prompt"]
    assert [t["name"] for t in trace_input["tools"]] == [
        "search", "get_documents", "commit_context"]


def test_happy_run_trace_summary_carries_the_context_ledger(
        happy_run: dict[str, Any]) -> None:
    """Committed vs. rejected is the run's evidence-selection audit trail."""
    summary = happy_run["trace"]["summary"]
    assert summary["context"] == {"committed": sorted(D[:2]), "rejected": []}
    assert summary["report_repairs"] == []


def test_happy_run_trace_config_is_recorded(happy_run: dict[str, Any]) -> None:
    """Budgets are per-run knobs, so a trace is uninterpretable without them.

    "Stopped at 20 rounds" means nothing unless the cap is in the artifact.
    """
    assert happy_run["trace"]["config"] == {
        "context_token_budget": 500_000,
        "safety_max_rounds": 20,
        "max_committed_per_step": 10,
    }


def test_happy_run_trace_tokens_include_the_budget_view(
        happy_run: dict[str, Any]) -> None:
    """Context size — not a round limit — is what stops research in this system.

    So the token accounting is a first-class result, not diagnostics: the
    scripted turns declare 100 input tokens each, which must show up as the
    current/peak context rather than being summed.
    """
    tokens = happy_run["trace"]["summary"]["tokens"]
    assert tokens["context_tokens"] == 100
    assert tokens["peak_context_tokens"] == 100
    assert tokens["context_budget_tokens"] == 500_000
    assert tokens["processed"] == 450          # 3 turns × (100 in + 50 out)


def test_happy_run_trace_steps_are_generation_and_action_spans(
        happy_run: dict[str, Any]) -> None:
    """Every model turn gets a ``generation`` span even with no visible text.

    Providers may return signature-only reasoning; without an unconditional span
    the viewer timeline would show an unexplained gap between a tool result and
    the next action.
    """
    steps = [(s["type"], s["turn"]) for s in happy_run["trace"]["steps"]]
    assert steps == [("generation", 0), ("tool_call", 0),
                     ("generation", 1), ("tool_call", 1),
                     ("generation", 2)]


def test_happy_run_trace_steps_are_fully_timed(
        happy_run: dict[str, Any]) -> None:
    """The trace is the viewer's only input; an untimed step renders as nothing.

    Bounds must also nest inside the run's own bounds, or the timeline scale is
    wrong for every other step.
    """
    trace = happy_run["trace"]
    for step in trace["steps"]:
        assert isinstance(step["t_start"], str)
        assert isinstance(step["t_end"], str)
        assert step["t_start"] <= step["t_end"]
        assert trace["started_at"] <= step["t_start"]
        assert step["t_end"] <= trace["ended_at"]


def test_happy_run_strict_trajectory_omits_viewer_only_fields(
        happy_run: dict[str, Any]) -> None:
    """The strict/rich split: organizers get the trajectory, we keep the trace.

    Extra keys on a strict item are a submission-format risk, so the split is
    asserted rather than assumed.
    """
    viewer_only = {"t_start", "t_end", "turn", "stats", "context", "documents"}
    for item in happy_run["trajectory"]["result"]:
        assert not (viewer_only & item.keys())
    assert "trace" not in happy_run["trajectory"]
    assert "trace" in happy_run["output"]


def test_happy_run_summary_return_value(happy_run: dict[str, Any]) -> None:
    """``run_agent``'s return value is what the batch runner logs and reports.

    It is also what ``run.py`` prints per topic, so the fields are effectively
    an API — a rename here shows up as a broken batch summary.
    """
    summary = happy_run["summary"]
    assert summary["n_references"] == 2
    assert summary["n_sentences"] == 2
    assert summary["words"] == 13
    assert summary["committed_documents"] == 2
    assert summary["rejected_documents"] == 0
    assert summary["context_tokens"] == 100
    assert summary["peak_context_tokens"] == 100
    assert summary["processed_tokens"] == 450


def test_metadata_records_backend_engines_and_run_id(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Run metadata must identify the configuration that produced the artifact.

    Two runs of this system differ mainly by model/engine choice; without these
    fields the outputs are indistinguishable after the fact.
    """
    result = drive(list(HAPPY_SCRIPT), run_id="aus-agent-probe",
                   engines=["semantic"])
    metadata = result["trajectory"]["metadata"]
    assert metadata["run_id"] == "aus-agent-probe"
    assert metadata["engines"] == ["semantic"]
    assert metadata["k"] == 2
    assert metadata["temperature"] is None
    assert metadata["model"] == ScriptedProvider.model_id


def test_single_engine_run_pins_searches_to_that_engine(
        drive: Callable[..., dict[str, Any]]) -> None:
    """With one engine enabled the model may omit ``search_engine``.

    The adapter must then use the RUN's engine, not the shared tool's built-in
    ``semantic`` default — otherwise an SSR-only or keyword-only experiment
    silently measures the wrong backend.
    """
    script = [
        model_turn(tool_calls=[tool_call(
            "search", {"query": "congestion pricing"}, id="s1")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"Toll revenue funds the capital plan [{D[0]}]."),
    ]
    result = drive(script, engines=["keyword"])
    assert list(result["calls"]) == ["keyword"]
    assert result["summary"]["status"] == "completed"


def test_chunk_ids_are_reported_doc_level_but_kept_in_full_in_the_trace(
        drive: Callable[..., dict[str, Any]],
        fake_hits: Callable[..., list[dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The track wants doc-level ids; reviewers want the page that supported it.

    Retrieval units may be chunks (``<docid>_p<n>``). ``references`` must carry
    the parent docid (a chunk id is not a valid corpus docid for the organizers)
    while ``trace.output.references_full`` keeps the precise unit.
    """
    from tools import search_tool

    chunk_ids = tuple(f"{d}_p{i + 1}" for i, d in enumerate(D))

    def _chunked(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        return fake_hits(min(k, len(chunk_ids)), ids=chunk_ids)

    monkeypatch.setattr(search_tool, "_DISPATCH",
                        {e: _chunked for e in search_tool._DISPATCH})
    # Commit and cite the chunk-native unit id; the doc-level collapse is the
    # submission-format step at the end of the run, not the model's job.
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "q", "search_engine": "semantic"}, id="s1")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"id": f"{D[0]}_p1", "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"A cited claim [{D[0]}_p1]."),
    ])
    assert result["output"]["references"] == [D[0]]
    assert result["trace"]["output"]["references_full"] == [f"{D[0]}_p1"]


def test_partial_output_is_published_before_the_first_model_turn(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A live run must be visible in the outputs viewer while it is still going.

    The partial is written with ``trace.status == "running"``, which is also the
    gate that keeps it out of ``--skip-existing`` and the submission exporter —
    an unfinished run must never look finished.
    """
    seen: dict[int, list[tuple[str, str]]] = {}

    def _responder(pending: str, turn_index: int) -> dict[str, Any]:
        from ragrun.outputs import data_dir

        out_dir = data_dir() / "outputs" / "aus_agent"
        files = sorted(out_dir.glob("*.json")) if out_dir.exists() else []
        seen[turn_index] = [
            (path.name.split(".")[-2],
             json.loads(path.read_text()).get("trace", {}).get("status"))
            for path in files]
        return HAPPY_SCRIPT[turn_index]

    result = drive(_responder)
    # Before turn 0 the output already exists and is marked running; the
    # trajectory is deliberately NOT written incrementally (too large).
    assert seen[0] == [("output", "running")]
    assert result["trace"]["status"] == "completed"


# ---------------------------------------------------------------------------
# Protocol branches
# ---------------------------------------------------------------------------
def test_no_commit_context_expires_the_batch_but_keeps_the_turn(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A turn with no ``commit_context`` means "retain none", not "protocol error".

    Treating it as a breach used to cost a full turn at full context size, twice
    over (see the ``expire_staged_context`` comment). The following turn's
    searches must still run, and the auto-expiry must be recorded as a NON-failed
    ``commit_context`` so ``tool_call_counts`` does not misreport it as an error.
    """
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic"}, id="s1")]),
        model_turn(tool_calls=[tool_call(
            "search", {"query": "b", "search_engine": "keyword"}, id="s2")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"A cited claim [{D[0]}]."),
    ])
    assert result["summary"]["status"] == "completed"
    # 2 searches + 1 auto-expiry + 1 real commit, none of them failed.
    assert result["trajectory"]["tool_call_counts"] == {
        "search": 2, "commit_context": 2}
    assert result["trajectory"]["tool_call_counts_all"] == {
        "search": 2, "commit_context": 2}
    assert list(result["calls"]) == ["semantic", "keyword"]
    expiry = [i for i in result["trajectory"]["result"]
              if i["type"] == "tool_call"
              and i["tool_name"] == "commit_context"][0]
    assert json.loads(expiry["arguments"])["automatic"] is True


def test_two_commit_context_calls_are_ambiguous_and_lose_the_turn(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Several commits cannot be resolved, so the batch expires and the turn is
    refused.

    This is the one commit shape that still costs a turn, deliberately: there is
    no single selection to honour, and guessing would retain evidence the model
    did not choose. The refusal must come back as ``is_error`` tool results so
    the model sees why.
    """
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic"}, id="s1")]),
        model_turn(tool_calls=[
            tool_call("commit_context", {"documents": [
                {"docid": D[0], "reason": "revenue"}]}, id="c1"),
            tool_call("commit_context", {"documents": []}, id="c2")]),
        # Nothing is committed, so a cited report is impossible; the loop
        # bounces uncited prose MAX_UNCITED_REFUSALS times and then accepts it.
        model_turn(text="An honest evidence-gap statement."),
        model_turn(text="An honest evidence-gap statement."),
        model_turn(text="An honest evidence-gap statement."),
    ])
    assert result["summary"]["status"] == "completed"
    assert result["summary"]["committed_documents"] == 0
    # The successful search is the only non-failed call; all three
    # commit_context records (auto-expiry + the two refused calls) are failures.
    assert result["trajectory"]["tool_call_counts"] == {"search": 1}
    assert result["trajectory"]["tool_call_counts_all"] == {
        "search": 1, "commit_context": 3}
    refused = result["provider"].tool_results[-1]
    assert all(r["is_error"] for r in refused)
    assert "commit_context calls" in refused[0]["content"]


def test_commit_context_with_nothing_staged_is_a_no_op_not_a_failure(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A stray commit must not cost the turn's searches.

    The pathological loop this prevents: model searches without committing ->
    batch expires -> model dutifully commits next turn -> nothing is staged ->
    that turn's searches are refused too. Two turns burned on bookkeeping.
    """
    result = drive([
        model_turn(tool_calls=[
            tool_call("commit_context", {"documents": []}, id="c0"),
            tool_call("search", {"query": "a", "search_engine": "semantic"},
                      id="s1")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"A cited claim [{D[0]}]."),
    ])
    assert result["summary"]["status"] == "completed"
    assert result["summary"]["committed_documents"] == 1
    # The no-op is recorded as a successful call and answered, and the search on
    # the same turn ran.
    assert result["trajectory"]["tool_call_counts"] == {
        "search": 1, "commit_context": 2}
    noop = json.loads([i for i in result["trajectory"]["result"]
                       if i["type"] == "tool_call"
                       and i["tool_name"] == "commit_context"][0]["output"]
                      .split("\n[context budget")[0])
    assert noop["committed"] == [] and noop["rejected"] == []


def test_invalid_commit_expires_the_batch_and_refuses_same_turn_actions(
        drive: Callable[..., dict[str, Any]]) -> None:
    """An out-of-batch docid is a hallucinated selection and must not commit.

    ``ContextLedger.commit`` raises; the loop rolls the ledger back, compacts
    the batch anyway (it cannot be reselected), and refuses the turn's other
    actions so the next turn starts from a clean context. The parallel search on
    that turn is counted in ``_all`` but not as a success.
    """
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic"}, id="s1")]),
        model_turn(tool_calls=[
            tool_call("commit_context", {"documents": [
                {"docid": "shard_NOT_STAGED", "reason": "x"}]}, id="c1"),
            tool_call("search", {"query": "b", "search_engine": "semantic"},
                      id="s2")]),
        model_turn(text="Honest evidence-gap statement."),
        model_turn(text="Honest evidence-gap statement."),
        model_turn(text="Honest evidence-gap statement."),
    ])
    assert result["summary"]["committed_documents"] == 0
    assert result["trajectory"]["tool_call_counts"] == {"search": 1}
    assert result["trajectory"]["tool_call_counts_all"] == {
        "search": 2, "commit_context": 1}
    commit_item = [i for i in result["trajectory"]["result"]
                   if i["type"] == "tool_call"
                   and i["tool_name"] == "commit_context"][0]
    assert "outside the staged context" in commit_item["output"]


def test_commit_without_a_reason_is_rejected(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The per-document reason is the point of the commit protocol.

    Without it the ledger is a list of ids with no argument for keeping any of
    them, so a reasonless selection is refused rather than silently accepted.
    """
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic"}, id="s1")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0]}]}, id="c1")]),
        model_turn(text="Honest evidence-gap statement."),
        model_turn(text="Honest evidence-gap statement."),
        model_turn(text="Honest evidence-gap statement."),
    ])
    assert result["summary"]["committed_documents"] == 0
    commit_item = [i for i in result["trajectory"]["result"]
                   if i["type"] == "tool_call"
                   and i["tool_name"] == "commit_context"][0]
    assert "distinct evidence reason" in commit_item["output"]


def test_parallel_searches_share_one_staged_batch(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Two searches on one turn stage ONE batch, resolved by ONE commit.

    Both call ids must be compacted together — if only the committed document's
    own search were rewritten, the duplicate copy in the sibling search would
    stay in context and the token saving would evaporate.
    """
    result = drive([
        model_turn(tool_calls=[
            tool_call("search", {"query": "a", "search_engine": "semantic"},
                      id="s1"),
            tool_call("search", {"query": "b", "search_engine": "keyword"},
                      id="s2")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"A cited claim [{D[0]}]."),
    ])
    assert result["summary"]["status"] == "completed"
    assert result["trajectory"]["tool_call_counts"] == {
        "search": 2, "commit_context": 1}
    assert [sorted(c) for c in result["provider"].compactions] == [["s1", "s2"]]
    assert result["summary"]["committed_documents"] == 1
    # The duplicate occurrence of the committed docid is rejected, not kept.
    assert result["summary"]["rejected_documents"] >= 1


def test_a_failed_search_does_not_stop_the_run(
        drive: Callable[..., dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
        fake_hits: Callable[..., list[dict[str, Any]]]) -> None:
    """Backend errors are tool feedback, not exceptions.

    One flaky engine call must degrade to an error envelope the model can react
    to; raising would lose an entire topic's work. The failure is excluded from
    ``tool_call_counts`` but kept in ``tool_call_counts_all``, which is how a
    run's real error rate stays visible.
    """
    from tools import search_tool

    def _flaky(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        if query == "boom":
            raise RuntimeError("engine exploded")
        return fake_hits(min(k, len(D)))

    monkeypatch.setattr(search_tool, "_DISPATCH",
                        {e: _flaky for e in search_tool._DISPATCH})
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "boom", "search_engine": "semantic"},
            id="s1")]),
        model_turn(tool_calls=[tool_call(
            "search", {"query": "ok", "search_engine": "semantic"}, id="s2")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"A cited claim [{D[0]}]."),
    ])
    assert result["summary"]["status"] == "completed"
    assert result["trajectory"]["tool_call_counts"] == {
        "search": 1, "commit_context": 1}
    assert result["trajectory"]["tool_call_counts_all"]["search"] == 2
    failed_item = [i for i in result["trajectory"]["result"]
                   if i["type"] == "tool_call"
                   and "boom" in i["arguments"]][0]
    assert "engine exploded" in failed_item["output"]


def test_an_invalid_budget_argument_fails_only_that_call(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A bad ``budget_tokens_per_result`` must not reach the backend at all.

    Validated in the adapter, returned as an error envelope — a zero/negative
    budget would otherwise truncate every result to nothing.
    """
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic",
                       "budget_tokens_per_result": 0}, id="s1")]),
        model_turn(tool_calls=[tool_call(
            "search", {"query": "b", "search_engine": "semantic"}, id="s2")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"A cited claim [{D[0]}]."),
    ])
    assert result["calls"]["semantic"] == [{"query": "b", "k": 2}]
    assert result["summary"]["status"] == "completed"


def test_per_result_truncation_bounds_staged_text(
        drive: Callable[..., dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Each result is bounded independently before it is staged.

    This is the mechanism that makes "extra queries are cheap" true: without it
    one long document could blow the whole context budget in a single call.
    """
    from tools import search_tool
    from utils.search_types import make_hit

    long_text = "paragraph line\n" * 500

    def _long(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        return [make_hit(D[0], score=1.0, rank=1, text=long_text)]

    monkeypatch.setattr(search_tool, "_DISPATCH",
                        {e: _long for e in search_tool._DISPATCH})
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic",
                       "budget_tokens_per_result": 10}, id="s1")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=f"A cited claim [{D[0]}]."),
    ])
    staged = json.loads(result["trajectory"]["result"][0]["output"]
                        .split("\n[context budget")[0])
    assert staged["results"][0]["truncated"] is True
    assert staged["results"][0]["returned_chars"] <= 10 * 5
    assert staged["results"][0]["original_chars"] == len(long_text)


def test_context_budget_exhaustion_refuses_retrieval_and_finishes(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Reaching the token budget must convert the run to report-writing.

    Context size, not a round limit, is this system's stop condition — so the
    budget hit has to (a) refuse further retrieval, (b) still honour the pending
    commit (bookkeeping, not retrieval), and (c) mark the run
    ``budget_exhausted``, which is the status the exporter accepts alongside
    ``completed``.
    """
    # The budget is checked against the usage of the turn just taken, so the
    # first turn must be under budget for its search to run at all.
    light = {"inputTokens": 100, "outputTokens": 10,
             "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0}
    heavy = {"inputTokens": 5_000, "outputTokens": 10,
             "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0}
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic"}, id="s1")],
            usage=light),
        model_turn(tool_calls=[
            tool_call("commit_context", {"documents": [
                {"docid": D[0], "reason": "revenue"}]}, id="c1"),
            tool_call("search", {"query": "more", "search_engine": "semantic"},
                      id="s2")], usage=heavy),
        model_turn(text=f"A cited claim [{D[0]}].", usage=heavy),
    ], context_token_budget=1_000)
    assert result["summary"]["status"] == "budget_exhausted"
    assert result["trace"]["summary"]["stop_reason"] == (
        "generation_context_tokens")
    # The second search was refused; the commit on the same turn still ran.
    assert result["calls"]["semantic"] == [{"query": "a", "k": 2}]
    assert result["trajectory"]["tool_call_counts_all"]["search"] == 2
    refused = [i for i in result["trajectory"]["result"]
               if i["type"] == "tool_call" and "more" in i["arguments"]][0]
    assert "research budget" in refused["output"]


def test_budget_status_is_appended_to_every_tool_result(
        happy_run: dict[str, Any]) -> None:
    """The model can only self-pace if it is told how much budget is left.

    The status line rides on every tool result rather than in a separate
    message, so it costs no turn and cannot be missed.
    """
    for batch in happy_run["provider"].tool_results:
        for result in batch:
            assert "[context budget:" in result["content"]
            assert "elapsed:" in result["content"]


def test_a_rejected_report_gets_one_correction_turn_then_succeeds(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A non-compliant report must be bounced with actionable reasons.

    Each bounce costs a full turn at full context, which is why the parser
    repairs whatever it can; what it cannot repair (here: citing nothing) comes
    back as an explicit correction message in the same conversation.
    """
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic"}, id="s1")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text="A claim with no citation at all."),
        model_turn(text=f"A claim, now cited [{D[0]}]."),
    ])
    assert result["summary"]["status"] == "completed"
    feedback = result["provider"].user_messages[-1]
    assert "did not satisfy the final-" in feedback
    assert "no sentence carries a citation" in feedback


def test_repairs_are_recorded_rather_than_bounced(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Silent leniency would be unauditable, so every repair is written down.

    Markdown and a stray uncommitted citation are fixed in place (saving a
    correction turn); ``trace.summary.report_repairs`` is what keeps that
    honest.
    """
    result = drive([
        model_turn(tool_calls=[tool_call(
            "search", {"query": "a", "search_engine": "semantic"}, id="s1")]),
        model_turn(tool_calls=[tool_call("commit_context", {"documents": [
            {"docid": D[0], "reason": "revenue"}]}, id="c1")]),
        model_turn(text=("## Findings\n"
                         f"- A **bold** claim [{D[0]}].\n"
                         "A second claim [shard_NEVER_COMMITTED].\n")),
    ])
    assert result["summary"]["status"] == "completed"
    repairs = result["trace"]["summary"]["report_repairs"]
    assert any("heading" in r for r in repairs)
    assert any("list/quote" in r for r in repairs)
    assert any("emphasis" in r for r in repairs)
    assert any("uncommitted docids shard_NEVER_COMMITTED" in r
               for r in repairs)
    assert result["output"]["references"] == [D[0]]
    assert [s["text"] for s in result["output"]["answer"]] == [
        "A bold claim.", "A second claim."]


def test_uncited_report_is_accepted_after_the_refusal_limit(
        drive: Callable[..., dict[str, Any]]) -> None:
    """When the corpus has nothing, an honest evidence-gap answer beats failing.

    The loop refuses an uncited report ``MAX_UNCITED_REFUSALS`` times to push
    the model toward evidence, then accepts it — the alternative is spinning to
    the backstop and losing the topic outright.
    """
    script = [model_turn(text="Nothing in the corpus addresses this.")] * (
        MAX_UNCITED_REFUSALS + 1)
    result = drive(script)
    assert result["summary"]["status"] == "completed"
    assert result["provider"].turn_index == MAX_UNCITED_REFUSALS + 1
    assert result["output"]["references"] == []
    assert result["output"]["answer"] == [
        {"text": "Nothing in the corpus addresses this.", "citations": []}]


# ---------------------------------------------------------------------------
# Termination (the loop has no bounded round list — these prove it stops)
# ---------------------------------------------------------------------------
def test_an_unfixable_report_terminates_at_the_safety_backstop(
        drive: Callable[..., dict[str, Any]]) -> None:
    """A model that can never satisfy the contract must STOP, not hang.

    Over-length is the rejection the parser deliberately will not repair
    (truncating would cut the conclusion), so a model that only ever writes
    1100 words is the pathological case. Current behaviour: the correction path
    raises ``RuntimeError`` at ``safety_max_rounds``, the outer handler turns it
    into ``status == "failed"``, and the sentinel answer names the reason.
    NOTE: the run is still saved, but its answer is a "Run failed:" sentence, so
    ``failed`` runs must be filtered before export (they are: the exporter gates
    on completed/budget_exhausted).
    """
    long_report = " ".join(["word"] * (MAX_REPORT_WORDS + 76)) + "."
    result = drive(lambda pending, i: model_turn(text=long_report),
                   safety_max_rounds=3)
    assert result["summary"]["status"] == "failed"
    assert result["provider"].turn_index == 3
    assert result["output"]["answer"][0]["text"].startswith(
        "Run failed: RuntimeError: runaway-loop safety backstop")
    assert result["trace"]["status"] == "failed"


def test_a_no_progress_turn_terminates_at_the_hard_round_cap(
        drive: Callable[..., dict[str, Any]]) -> None:
    """The one guard every path passes through, including the no-op paths.

    A turn consisting only of a neutralised ``commit_context`` (nothing staged)
    executes no tools and reaches none of the per-branch
    ``rounds >= safety_max_rounds`` checks — so without the unconditional
    ``hard_round_cap`` the ``while True`` loop would spin forever. Terminating
    at ``safety_max_rounds + FINISHING_ROUNDS_GRACE`` is exactly that backstop
    firing.
    """
    result = drive(
        lambda pending, i: model_turn(tool_calls=[
            tool_call("commit_context", {"documents": []}, id=f"noop{i}")]),
        safety_max_rounds=3)
    assert result["summary"]["status"] == "failed"
    assert result["provider"].turn_index == 3 + FINISHING_ROUNDS_GRACE
    assert "runaway-loop safety backstop reached: 13 rounds" in (
        result["output"]["answer"][0]["text"])


def test_a_failed_run_still_writes_saveable_artifacts(
        drive: Callable[..., dict[str, Any]]) -> None:
    """Even a crashed run must leave a schema-valid artifact pair.

    The sentinel answer has no citations and there are no references, which is
    valid (nothing is uncited), so the batch runner never has to special-case
    writing a failure.
    """
    from ragrun import validate_rag_output

    result = drive(lambda pending, i: model_turn(text=""),
                   safety_max_rounds=2)
    assert result["summary"]["status"] == "failed"
    assert validate_rag_output(result["output"]) == []
    assert "violations" not in result["summary"]["paths"]


def test_an_empty_provider_turn_is_a_rejected_report_not_a_stall(
        drive: Callable[..., dict[str, Any]]) -> None:
    """No text and no tool calls means the model produced nothing usable.

    The loop must treat it as a rejected final report (and say "response is
    empty") rather than looping silently — a turn that neither acts nor answers
    is otherwise indistinguishable from progress.
    """
    result = drive([model_turn(text=""),
                    model_turn(text="Honest evidence-gap statement."),
                    model_turn(text="Honest evidence-gap statement."),
                    model_turn(text="Honest evidence-gap statement.")])
    assert result["summary"]["status"] == "completed"
    assert "response is empty" in result["provider"].user_messages[1]


def test_a_non_positive_context_budget_is_rejected_up_front() -> None:
    """The budget divides in ``_budget_status_line`` and gates the whole loop.

    Failing fast beats a run that reports 0% forever or divides by zero.
    """
    with pytest.raises(ValueError, match="context_token_budget must be"):
        run_agent(QID, QUERY, context_token_budget=0)


# ---------------------------------------------------------------------------
# _parse_final_prose (the report contract)
# ---------------------------------------------------------------------------
COMMITTED = {"d1", "d2", "d3", "d4"}


@pytest.mark.parametrize("text,expected_texts,expected_citations", [
    # One sentence per line is the contract's happy path.
    ("Claim one [d1].\nClaim two [d2].",
     ["Claim one.", "Claim two."], [["d1"], ["d2"]]),
    # Multiple docids in one marker, and separate markers, both parse.
    ("Claim [d1, d2] and more [d3].", ["Claim and more."], [["d1", "d2", "d3"]]),
    # A citation-only line folds upward: models routinely put markers on the
    # next line, and bouncing that would cost a full correction turn.
    ("A claim here.\n[d1, d2]", ["A claim here."], [["d1", "d2"]]),
])
def test_parse_final_prose_accepts_the_contract_shapes(
        text: str, expected_texts: list[str],
        expected_citations: list[list[str]]) -> None:
    """These are the shapes a compliant model actually emits.

    Each is accepted without a correction turn — at ~100k context per turn, the
    difference between repairing and bouncing is most of the run's cost.
    """
    sentences, errors, _ = _parse_final_prose(text, COMMITTED)
    assert errors == []
    assert sentences is not None
    assert [s["text"] for s in sentences] == expected_texts
    assert [s["citations"] for s in sentences] == expected_citations


def test_parse_final_prose_keeps_bracketed_mathematics() -> None:
    """A citation marker holds docid-shaped tokens ONLY.

    Regression guard with a real cause: a model wrote the DPO objective as
    ``log[π_r(y|x)/π_ref(y|x)]`` and an earlier any-content pattern deleted the
    ratio from the mathematics as though it were a citation.
    """
    sentences, errors, _ = _parse_final_prose(
        "The ratio log[a/b] is bounded [d1].", COMMITTED)
    assert errors == []
    assert sentences == [
        {"text": "The ratio log[a/b] is bounded.", "citations": ["d1"]}]


@pytest.mark.parametrize("text,error_fragment", [
    ("", "response is empty"),
    ("   \n\t\n", "response is empty"),
    ("[d1]", "the report contains no sentences"),
    # Fence lines are dropped, so a fence-only response has no prose left. (The
    # fence's CONTENTS are kept as prose — the parser has no notion of a code
    # block, only of the fence lines themselves.)
    ("```\n```", "the report contains no sentences"),
])
def test_parse_final_prose_rejects_unusable_reports(
        text: str, error_fragment: str) -> None:
    """These cannot be repaired on the model's behalf, so they cost a turn.

    Guessing a report out of nothing would fabricate the run's conclusion.
    """
    sentences, errors, _ = _parse_final_prose(text, COMMITTED)
    assert sentences is None
    assert any(error_fragment in e for e in errors)


def test_parse_final_prose_rejects_an_over_length_report() -> None:
    """Truncating an over-length report would cut its conclusion.

    So the model re-prioritizes instead — the one rejection that is a
    deliberate refusal to repair.
    """
    text = " ".join(["word"] * (MAX_REPORT_WORDS + 1)) + " [d1]."
    sentences, errors, _ = _parse_final_prose(text, COMMITTED)
    assert sentences is None
    assert any("hard maximum" in e for e in errors)


def test_parse_final_prose_rejects_uncited_prose_differently_by_state() -> None:
    """The refusal must tell the model what to DO, and that differs.

    With evidence committed the fix is "add markers"; with nothing committed the
    fix is "go and search" — every claim would otherwise be unsupported prior
    knowledge, which the contract forbids outright.
    """
    _, with_evidence, _ = _parse_final_prose("Uncited claim.", COMMITTED)
    _, without_evidence, _ = _parse_final_prose("Uncited claim.", set())
    assert any("no sentence carries a citation" in e for e in with_evidence)
    assert any("no evidence has been committed" in e for e in without_evidence)


def test_parse_final_prose_allow_uncited_is_the_escape_hatch() -> None:
    """``allow_uncited`` is what turns a doomed run into an honest answer.

    Set when the budget is exhausted or after ``MAX_UNCITED_REFUSALS``; without
    it those runs would loop to the backstop and be lost entirely.
    """
    sentences, errors, _ = _parse_final_prose(
        "Nothing in the corpus addresses this.", set(), allow_uncited=True)
    assert errors == []
    assert sentences == [
        {"text": "Nothing in the corpus addresses this.", "citations": []}]


@pytest.mark.parametrize("text,repair_fragment,expected", [
    ("# Heading\nA claim [d1].", "dropped a Markdown heading", "A claim."),
    ("- A claim [d1].", "unwrapped a Markdown list/quote marker", "A claim."),
    ("> A claim [d1].", "unwrapped a Markdown list/quote marker", "A claim."),
    ("**A** claim [d1].", "unwrapped Markdown emphasis", "A claim."),
    ("A `code` claim [d1].", "unwrapped Markdown emphasis", "A code claim."),
])
def test_parse_final_prose_repairs_markdown_in_place(
        text: str, repair_fragment: str, expected: str) -> None:
    """Markdown carries no citable claim, and bouncing it wastes a turn.

    The contract asks for plain prose; models reach for Markdown anyway, so the
    parser unwraps rather than argues.
    """
    sentences, errors, repairs = _parse_final_prose(text, COMMITTED)
    assert errors == []
    assert sentences is not None
    assert sentences[-1]["text"] == expected
    assert any(repair_fragment in r for r in repairs)


def test_parse_final_prose_drops_uncommitted_citations() -> None:
    """A citation to evidence that was never retained cannot be honoured.

    Dropping it (and recording the drop) keeps the sentence — with its other,
    valid support — instead of failing the whole report over one bad id.
    """
    sentences, errors, repairs = _parse_final_prose(
        "Claim [d1] with a hallucinated id [shard_NEVER].", COMMITTED)
    assert errors == []
    assert sentences is not None
    assert sentences[0]["citations"] == ["d1"]
    assert any("dropped uncommitted docids shard_NEVER" in r for r in repairs)


def test_parse_final_prose_caps_citations_at_three() -> None:
    """The track schema allows at most 3 citations per sentence.

    Over-citing is a validator failure, so the extras are dropped here rather
    than bounced — and the drop is recorded.
    """
    sentences, errors, repairs = _parse_final_prose(
        "Claim [d1, d2, d3, d4].", COMMITTED)
    assert errors == []
    assert sentences is not None
    assert sentences[0]["citations"] == ["d1", "d2", "d3"]
    assert any("beyond the first 3" in r for r in repairs)


# ---------------------------------------------------------------------------
# _map_citations
# ---------------------------------------------------------------------------
def test_map_citations_orders_references_by_first_citation() -> None:
    """Reference indices are positional in the submitted JSON.

    First-cited order makes them stable and reviewable; any other order would
    still validate, which is precisely why it needs a test.
    """
    references, answer = _map_citations([
        {"text": "First.", "citations": ["d3"]},
        {"text": "Second.", "citations": ["d1", "d3"]},
    ], COMMITTED)
    assert references == ["d3", "d1"]
    assert answer == [{"text": "First.", "citations": [0]},
                      {"text": "Second.", "citations": [1, 0]}]


def test_map_citations_caps_before_registering_a_reference() -> None:
    """Order of operations matters: cap first, then register.

    Registering a 4th docid and *then* dropping its index would leave a
    reference nothing cites — the exact "references never cited" violation the
    track validator flags.
    """
    references, answer = _map_citations(
        [{"text": "Claim.", "citations": ["d1", "d2", "d3", "d4"]}], COMMITTED)
    assert references == ["d1", "d2", "d3"]
    assert answer[0]["citations"] == [0, 1, 2]


def test_map_citations_drops_never_retrieved_docids() -> None:
    """Second line of defence behind ``_parse_final_prose``'s own filter.

    ``_map_citations`` is what the artifact is actually built from, so it
    re-checks rather than trusting the caller.
    """
    references, answer = _map_citations(
        [{"text": "Claim.", "citations": ["zz", "d2"]}], COMMITTED)
    assert references == ["d2"]
    assert answer[0]["citations"] == [0]


# ---------------------------------------------------------------------------
# _collapse_to_docs (the chunk -> parent-doc submission transform)
# ---------------------------------------------------------------------------
def test_collapse_to_docs_maps_chunk_pages_onto_one_parent_reference() -> None:
    """references must be ClimbMix docids — a chunk id is not a valid one.

    ``rag-task.md``: "Use the ClimbMix docid as the cited evidence identifier in
    final RAG references" and "If a system chunks documents internally, keep
    final references tied to ClimbMix document IDs". Two pages of one document
    therefore collapse to a single reference, and the sentence's citation
    indices are remapped onto the collapsed list — deduped, so citing both pages
    of one doc cites it once.
    """
    references, answer = _collapse_to_docs(
        ["doc_a_p1", "doc_a_p7", "doc_b_p2"],
        [{"text": "Both pages of A.", "citations": [0, 1]},
         {"text": "A and B.", "citations": [0, 2]}])
    assert references == ["doc_a", "doc_b"]
    assert answer == [{"text": "Both pages of A.", "citations": [0]},
                      {"text": "A and B.", "citations": [0, 1]}]


def test_collapse_to_docs_caps_a_sentence_at_three_citations() -> None:
    """The track's hard per-sentence limit, enforced at the submission boundary.

    ``rag-task.md``: "Cite no more than three references per sentence." This is
    the LAST transform before the artifact is written, and it has its own cap
    independent of ``_map_citations`` — collapsing can only ever shrink a
    citation list, but a sentence citing four DISTINCT parent docs must still be
    truncated to three or ``validate_rag_output`` rejects the run.
    """
    references, answer = _collapse_to_docs(
        ["d1_p1", "d2_p1", "d3_p1", "d4_p1", "d5_p1"],
        [{"text": "Overcited.", "citations": [0, 1, 2, 3, 4]}])
    assert references == ["d1", "d2", "d3", "d4", "d5"]
    assert answer[0]["citations"] == [0, 1, 2]
    assert len(answer[0]["citations"]) <= 3


def test_collapse_to_docs_counts_the_cap_in_parent_docs_not_chunks() -> None:
    """Four chunks of two documents is two citations, not a capped four.

    The cap applies to the collapsed reference list, so pages of the same parent
    must not consume cap slots — otherwise a well-sourced sentence reading four
    pages of two documents would lose a genuine second source.
    """
    _, answer = _collapse_to_docs(
        ["a_p1", "a_p2", "a_p3", "b_p1"],
        [{"text": "Four pages, two docs.", "citations": [0, 1, 2, 3]}])
    assert answer[0]["citations"] == [0, 1]


def test_collapse_to_docs_leaves_an_unpaginated_docid_untouched() -> None:
    """Doc-level engines must pass through unchanged.

    Only a trailing ``_p<n>`` is stripped; a docid whose own name contains
    digits and underscores (every ClimbMix id does) must survive intact.
    """
    references, answer = _collapse_to_docs(
        ["shard_00459_61697"], [{"text": "Claim.", "citations": [0]}])
    assert references == ["shard_00459_61697"]
    assert answer[0]["citations"] == [0]


def test_collapse_to_docs_drops_an_out_of_range_citation_index() -> None:
    """An index past the reference list must vanish, not become a bad citation.

    ``validate_rag_output`` rejects any citation index outside ``references``,
    so this is the difference between a dropped citation and an invalid run.
    """
    references, answer = _collapse_to_docs(
        ["a_p1"], [{"text": "Claim.", "citations": [0, 9]}])
    assert references == ["a"]
    assert answer[0]["citations"] == [0]


# ---------------------------------------------------------------------------
# _usage_token_stats (cross-backend token arithmetic)
# ---------------------------------------------------------------------------
def test_usage_token_stats_of_an_empty_dict_is_zeroed() -> None:
    """A provider that reports no usage must not break the loop.

    ``context_tokens`` is read from this on every turn and compared against the
    budget, so ``None`` here would raise mid-run. (Contrast
    ``facet_rag.pipeline._usage_token_stats``, which deliberately returns
    ``None`` for ``{}`` — it only annotates metadata.)
    """
    assert _usage_token_stats({}) == {
        "input": 0, "input_uncached": 0, "output": 0, "cache_read": 0,
        "cache_write": 0, "total": 0, "processed_input": 0, "processed": 0}


@pytest.mark.parametrize("usage", [
    # Bedrock camelCase.
    {"inputTokens": 1000, "outputTokens": 200,
     "cacheReadInputTokens": 4000, "cacheWriteInputTokens": 500},
    # OpenAI snake_case (providers/openai.py normalizes cached tokens OUT of
    # input_tokens precisely so this arithmetic matches Bedrock's).
    {"input_tokens": 1000, "output_tokens": 200,
     "cache_read_input_tokens": 4000, "cache_write_input_tokens": 500},
])
def test_usage_token_stats_normalizes_both_backends(
        usage: dict[str, Any]) -> None:
    """The two SDKs disagree on names AND on what ``input`` includes.

    Both must reduce to the same numbers, because the run's stop condition is a
    comparison against the LOGICAL context size (uncached + cache reads +
    cache writes) while cost tracking needs the PROCESSED size (which excludes
    cache reads). Conflating them would either stop research early or bill a
    cache hit as a fresh prefill.
    """
    assert _usage_token_stats(usage) == {
        "input": 5500,            # logical context the model actually saw
        "input_uncached": 1000,
        "output": 200,
        "cache_read": 4000,
        "cache_write": 500,
        "total": 5700,
        "processed_input": 1500,  # billed prefill: uncached + cache writes
        "processed": 1700,
    }


def test_usage_token_stats_tolerates_null_counts() -> None:
    """Providers occasionally send explicit nulls instead of omitting a field.

    ``int(None)`` would raise on a turn that is otherwise fine.
    """
    assert _usage_token_stats(
        {"inputTokens": None, "outputTokens": 7})["output"] == 7


# ---------------------------------------------------------------------------
# make_provider
# ---------------------------------------------------------------------------
def test_make_provider_openai_builds_no_client_until_used() -> None:
    """Constructing a provider must not need a key or a socket.

    The lazy client is what lets the whole harness be tested offline (and what
    lets ``run.py`` fail on a bad ``--backend`` before spending anything).
    """
    provider = make_provider("openai", "gpt-5.6-luna")
    assert type(provider).__name__ == "OpenAIProvider"
    assert provider.model_id == "gpt-5.6-luna"
    assert provider._client is None


def test_make_provider_bedrock_selects_the_bedrock_backend() -> None:
    """Same contract for the default backend, if boto3 is installed.

    Skipped rather than failed when it is not: ``boto3`` lives in the
    ``aus-agent`` dep group, not ``dev``, so the hermetic suite must stay green
    without it. NOTE (current behaviour): ``BedrockProvider.__init__`` builds
    its boto3 client eagerly, unlike OpenAI's lazy one — it does not call out,
    but it does resolve the credential chain at construction time.
    """
    pytest.importorskip("boto3", reason="boto3 is in the aus-agent dep group")
    provider = make_provider("bedrock", "au.anthropic.claude-sonnet-5")
    assert type(provider).__name__ == "BedrockProvider"
    assert provider.model_id == "au.anthropic.claude-sonnet-5"


def test_make_provider_rejects_an_unknown_backend() -> None:
    """A typo'd ``--backend`` must fail loudly before any spend.

    The message names the available options because this is a CLI-facing error.
    """
    with pytest.raises(ValueError, match=r"unknown backend: 'vertex'"):
        make_provider("vertex", None)


# ---------------------------------------------------------------------------
# Live (deselected by default)
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_run_agent_live_end_to_end() -> None:
    """The real loop against a real model and real retrieval.

    Deselected by default (needs AWS Bedrock creds + ``SEARCH_API_KEY``). It is
    kept runnable because the offline tests script the model's side of the
    protocol: only a live run proves a real model can actually follow it.
    Small budgets keep it to a couple of rounds.
    """
    from ragrun import validate_rag_output

    summary = run_agent(
        "live_aus_001",
        "How is congestion pricing revenue in New York being spent?",
        k=3, safety_max_rounds=6, context_token_budget=60_000,
        run_id="aus-agent-live-test",
        run_desc="live smoke test from tests/systems/test_aus_agent.py")
    assert summary["status"] in ("completed", "budget_exhausted")
    output = json.loads(summary["paths"]["output"].read_text())
    assert validate_rag_output(output) == []
    assert output["references"]
