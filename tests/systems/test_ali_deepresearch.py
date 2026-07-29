"""End-to-end + unit coverage for ``src/systems/ali_deepresearch``.

Hermetic pytest port of ``src/systems/ali_deepresearch/test_mock.py``. The
original drove the REAL ClimbMix ``search`` **and** ``get_document`` backends,
so it needed credentials; here both are stubbed:

- ``stub_search_tool`` (root conftest) replaces ``tools.search_tool``'s engine
  dispatch — ``ClimbMixTools.search``'s own cross-step dedup, snippet
  formatting, and meta assembly all stay under test;
- ``stub_fetch_doc`` (systems conftest) replaces the *separate* urllib client
  ``ClimbMixTools.get_document`` reaches through.

The scripted LLM still reads the real docid back out of the ``<tool_response>``
it was handed, exactly as the original did — that is what proves the round trip
(docid formatted into the response text -> parsed by the model -> accepted by
``get_document`` -> cited in the answer) rather than a hard-coded constant.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn

from ragrun import build_rag_output, save_run, validate_rag_output

from ali_deepresearch import ClimbMixTools, ReactAgent, SYSTEM_PROMPT
from ali_deepresearch.answer_format import (
    MAX_CITATIONS,
    format_answer,
)
from ali_deepresearch.react_agent import AgentResult
from ali_deepresearch.run import (
    build_metadata,
    candidate_docids,
    steps_to_trajectory,
)
from ali_deepresearch.tools import dispatch

QUERY = "How effective are influenza vaccines at preventing illness?"
QID = "mock_flu_001"

_DOCID_RE = re.compile(r"DocID:(\S+)")
_DOC_HEADER_RE = re.compile(r"Document (\S+):")


# ---------------------------------------------------------------------------
# Scripted ChatLLM (the three-round think -> search -> get_document -> answer)
# ---------------------------------------------------------------------------
class ScriptedLLM:
    """A ``ChatLLM`` that reacts to the real tool responses in the history.

    ``turns`` is a list of callables ``(last_tool_response) -> str``; the last
    one repeats forever, which is what lets the budget tests script "a model
    that never answers" without an unbounded list.
    """

    def __init__(self, turns: list[Callable[[str], str]]) -> None:
        self._turns = turns
        self.calls = 0
        self.seen_stops: list[list[str] | None] = []

    @staticmethod
    def _last_tool_response(messages: list[dict[str, str]]) -> str:
        for m in reversed(messages):
            if m["role"] == "user" and "<tool_response>" in m["content"]:
                return m["content"]
        return ""

    def complete(self, messages: list[dict[str, str]], *,
                 stop: list[str] | None = None,
                 max_tokens: int | None = None) -> str:
        self.seen_stops.append(stop)
        index = min(self.calls, len(self._turns) - 1)
        self.calls += 1
        return self._turns[index](self._last_tool_response(messages))


def _turn_search(_resp: str) -> str:
    return ("<think>The user asks about influenza vaccine effectiveness. I "
            "will search the corpus.</think>\n"
            "<tool_call>\n"
            '{"name": "search", "arguments": {"query": '
            '"influenza vaccine effectiveness"}}\n'
            "</tool_call>")


def _turn_get_document(resp: str) -> str:
    """Open the top hit — docid lifted out of the real ``<tool_response>``."""
    match = _DOCID_RE.search(resp)
    docid = match.group(1) if match else "shard_00000_0"
    return ("<think>The top result looks relevant. I will open it to read the "
            "full text.</think>\n"
            "<tool_call>\n"
            f'{{"name": "get_document", "arguments": {{"docid": "{docid}"}}}}\n'
            "</tool_call>")


def _turn_answer(resp: str) -> str:
    # Assert-by-construction that get_document's response really was seen.
    assert _DOC_HEADER_RE.search(resp), f"no document in history: {resp[:80]!r}"
    return ("<think>I now have enough to answer.</think>\n"
            "<answer>\n"
            "Influenza vaccines reduce the risk of laboratory-confirmed "
            "influenza illness among vaccinated individuals. Vaccine "
            "effectiveness varies by season and by the match between the "
            "vaccine and circulating strains.\n"
            "</answer>")


SCRIPT_THREE_ROUNDS = [_turn_search, _turn_get_document, _turn_answer]


def build_agent(script: list[Callable[[str], str]], *, k: int = 5,
                max_rounds: int = 6) -> tuple[ReactAgent, ScriptedLLM]:
    llm = ScriptedLLM(script)
    agent = ReactAgent(llm, SYSTEM_PROMPT + str(date.today()),
                       toolbox=ClimbMixTools(), k=k, max_rounds=max_rounds)
    return agent, llm


def assemble(result: AgentResult, *, run_id: str = "ali_deepresearch.mock",
             llm: Any | None = None) -> dict[str, Any]:
    """Run the REAL artifact assembly helpers from ``run.py`` over a result."""
    trajectory = steps_to_trajectory(
        result, build_metadata(result.query, "mock/tongyi-deepresearch", 5))
    references, answer = format_answer(
        result.answer_text or "", candidate_docids(result), llm=llm)
    output = build_rag_output(
        narrative_id=result.query_id, narrative=result.query, run_id=run_id,
        run_desc="mock end-to-end test", references=references, answer=answer)
    paths = save_run("ali_deepresearch", result.query, trajectory=trajectory,
                     output=output)
    return {"trajectory": trajectory, "output": output, "paths": paths,
            "references": references, "answer": answer}


@pytest.fixture
def react_run(stub_search_tool: dict[str, list[dict[str, Any]]],
              stub_fetch_doc: dict[str, list[str]]) -> dict[str, Any]:
    """One full hermetic three-round ReAct run + artifact assembly."""
    agent, llm = build_agent(SCRIPT_THREE_ROUNDS)
    result = agent.run(QUERY, query_id=QID)
    assembled = assemble(result)
    return {"result": result, "llm": llm, "calls": stub_search_tool,
            "fetches": stub_fetch_doc, **assembled}


# ---------------------------------------------------------------------------
# Full ReAct run (ported test_mock.py assertions)
# ---------------------------------------------------------------------------
def test_react_run_completes(react_run: dict[str, Any]) -> None:
    """A compliant model finishes in 3 rounds — one LLM call per round, no more.

    ``rounds`` is what the ``calls_left`` budget is spent from, so an off-by-one
    here means every real run silently gets one more (or one fewer) research
    step than configured.
    """
    result = react_run["result"]
    assert result.status == "completed"
    assert result.rounds == 3
    assert react_run["llm"].calls == 3


def test_react_run_writes_both_artifacts_without_violations(
        react_run: dict[str, Any]) -> None:
    """A submission-ready ReAct run leaves no ``output.violations.json`` behind.

    ``save_run`` writes that third file only when the output breaks the track
    schema, so its absence is the machine-checkable claim that this artifact
    could be exported as-is — asserted here for the ReAct loop, whose answer is
    assembled incrementally across rounds rather than in one synthesis step.
    """
    paths = react_run["paths"]
    assert paths["trajectory"].exists()
    assert paths["output"].exists()
    assert "violations" not in paths
    assert validate_rag_output(react_run["output"]) == []


def test_react_run_tool_call_counts(react_run: dict[str, Any]) -> None:
    """Both ClimbMix tools were reached, each exactly once.

    ``search`` and ``get_document`` hit different backends (the search REST API
    vs. ``utils.fetch_doc``); a run that never opens a document is a
    snippet-only run, which is a materially weaker system than the paper's.
    """
    assert react_run["trajectory"]["tool_call_counts"] == {
        "search": 1, "get_document": 1}


def test_react_run_retrieved_docids_and_references_non_empty(
        react_run: dict[str, Any]) -> None:
    """The two fields a grounded run cannot be empty in.

    No ``retrieved_docids`` means retrieval never landed; no ``references``
    means nothing was cited — either way the topic contributes nothing to the
    submission even though the run "succeeded".
    """
    assert react_run["trajectory"]["retrieved_docids"]
    assert react_run["references"]


def test_react_run_interleaved_item_kinds(react_run: dict[str, Any]) -> None:
    """Every ReAct round contributes ``reasoning`` then ``tool_call``.

    The organizers read this sequence as the agent's decision trail, so a
    dropped ``<think>`` block (or a tool call recorded without its reasoning)
    turns an auditable trajectory into a bare list of queries.
    """
    kinds = [item["type"] for item in react_run["trajectory"]["result"]]
    assert kinds == ["reasoning", "tool_call", "reasoning", "tool_call",
                     "reasoning", "output_text"]


def test_react_run_trajectory_top_level_schema(
        react_run: dict[str, Any]) -> None:
    """Exactly the reference sample's key set — no more, no less."""
    assert set(react_run["trajectory"]) == {
        "metadata", "query_id", "tool_call_counts", "tool_call_counts_all",
        "status", "retrieved_docids", "result", "raw_messages",
    }
    assert react_run["trajectory"]["raw_messages"]


def test_react_run_search_item_carries_sample_extras(
        react_run: dict[str, Any]) -> None:
    """The strict search item mirrors the reference trajectory's extra fields."""
    item = next(i for i in react_run["trajectory"]["result"]
                if i["type"] == "tool_call" and i["tool_name"] == "search")
    assert "returned" in item
    assert "original_query" in item
    assert "k" in item
    assert item["k"] == 5
    assert item["previous_queries_before_search"] == []
    assert item["found_docids_before_search"] == []


def test_react_run_every_reference_is_cited(react_run: dict[str, Any]) -> None:
    """An uncited reference is a spec violation that fails silently.

    The run still completes and the prose still reads fine; only the track
    validator notices. ``format_answer`` re-indexes references down to the ones
    actually cited precisely to keep this true.
    """
    cited = {c for s in react_run["answer"] for c in s["citations"]}
    assert cited == set(range(len(react_run["references"])))


def test_react_run_opened_document_is_cited_first(
        react_run: dict[str, Any]) -> None:
    """``candidate_docids`` puts documents the model actually READ ahead of the
    ones it only saw in a snippet — the reference list order must reflect it."""
    opened = react_run["fetches"]["docids"]
    assert len(opened) == 1
    assert react_run["references"][0] == opened[0]


def test_react_run_search_routed_with_the_scripted_query(
        react_run: dict[str, Any]) -> None:
    """``ClimbMixTools.search`` goes through the default (semantic) engine and
    passes the model's query and k straight through."""
    calls = react_run["calls"]
    assert list(calls) == ["semantic"]
    assert calls["semantic"] == [
        {"query": "influenza vaccine effectiveness", "k": 5}]


def test_react_loop_uses_the_upstream_stop_sequence(
        react_run: dict[str, Any]) -> None:
    """The ``STOP`` tokens must reach the model on every research turn.

    They are what cuts generation at the end of a ``<tool_call>`` so the model
    cannot continue past it and hallucinate its own ``<tool_response>``. Losing
    them does not break the loop — it silently degrades grounding.
    """
    from ali_deepresearch import STOP

    assert react_run["llm"].seen_stops == [STOP, STOP, STOP]


# ---------------------------------------------------------------------------
# Strict trajectory vs. rich trace (the timing invariants)
# ---------------------------------------------------------------------------
def test_trajectory_omits_viewer_only_fields(react_run: dict[str, Any]) -> None:
    """The strict/rich split: timings and stats belong to the trace, not here.

    The trajectory is the organizer-facing artifact and is checked against a
    reference sample, so extra keys are a submission-format risk. This is the
    half that must stay lean.
    """
    trajectory = react_run["trajectory"]
    viewer_only = {"t_start", "t_end", "turn", "stats", "context", "documents"}
    assert all(not (viewer_only & item.keys())
               for item in trajectory["result"])
    assert "started_at" not in trajectory
    assert "ended_at" not in trajectory


def test_output_trace_has_ordered_run_bounds(react_run: dict[str, Any]) -> None:
    """The run's own span is the timeline's scale in the outputs viewer.

    Missing or inverted bounds make every step bar in that run unrenderable,
    and they are also how run durations get compared across systems.
    """
    trace = react_run["output"]["trace"]
    assert isinstance(trace["started_at"], str)
    assert isinstance(trace["ended_at"], str)
    assert trace["started_at"] <= trace["ended_at"]


def test_output_trace_steps_are_fully_timed(react_run: dict[str, Any]) -> None:
    """The trace is rich-only (viewer input); an untimed step renders as nothing.

    A step missing ``t_start``/``t_end`` draws as a zero-width bar, and a
    missing ``turn`` breaks the per-round grouping the viewer uses to show which
    actions belonged to the same model turn.
    """
    steps = react_run["output"]["trace"]["steps"]
    assert steps
    for step in steps:
        assert isinstance(step.get("t_start"), str)
        assert isinstance(step.get("t_end"), str)
        assert isinstance(step.get("turn"), int)
        assert step["t_start"] <= step["t_end"]


def test_output_trace_steps_are_sequential(react_run: dict[str, Any]) -> None:
    """The ReAct loop is strictly sequential — no overlapping spans, so
    ``t_start`` never goes backwards (unlike aus_agent's parallel tool calls)."""
    starts = [s["t_start"] for s in react_run["output"]["trace"]["steps"]]
    assert all(a <= b for a, b in zip(starts, starts[1:]))


def test_output_trace_turn_indices(react_run: dict[str, Any]) -> None:
    """Each of the 3 LLM rounds produced a reasoning + an action step."""
    turns = [s["turn"] for s in react_run["output"]["trace"]["steps"]]
    assert turns == [0, 0, 1, 1, 2, 2]


def test_output_trace_steps_lie_within_run_bounds(
        react_run: dict[str, Any]) -> None:
    """Steps must nest inside the run span, not straddle it.

    A step outside the bounds stretches the viewer's axis so every other bar
    collapses — the usual cause being a stamp taken before the run clock
    started or after it was read.
    """
    trace = react_run["output"]["trace"]
    steps = trace["steps"]
    assert trace["started_at"] <= steps[0]["t_start"]
    assert steps[-1]["t_end"] <= trace["ended_at"]


# ---------------------------------------------------------------------------
# ReAct loop control
# ---------------------------------------------------------------------------
def test_loop_terminates_at_the_call_budget(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A model that never emits ``<answer>`` must stop at ``max_rounds``.

    The guard is ``while calls_left > 0`` with ``calls_left`` decremented once
    per round, so the cap is exact — this is the anti-infinite-loop property.
    """
    agent, llm = build_agent([_turn_search], max_rounds=4)
    result = agent.run(QUERY, query_id=QID)
    assert result.status == "max_rounds"
    assert result.rounds == 4
    assert llm.calls == 4
    assert result.answer_text is None
    assert len(stub_search_tool["semantic"]) == 4


def test_budget_exhaustion_still_yields_saveable_artifacts(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """No ``<answer>`` means no draft, so the heuristic supplies a placeholder
    sentence — the run is still schema-valid rather than unwritable."""
    agent, _ = build_agent([_turn_search], max_rounds=2)
    assembled = assemble(agent.run(QUERY, query_id=QID))
    assert assembled["trajectory"]["status"] == "max_rounds"
    assert assembled["answer"][0]["text"] == "No answer was produced."
    assert validate_rag_output(assembled["output"]) == []


def test_malformed_tool_call_payload_is_reported_not_fatal(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """Invalid JSON from the model is expected traffic, not an exception.

    The tool-call payload is free-form model output, so a parse failure must
    come back as tool feedback the model can correct from. Raising would lose
    the whole topic to one bad brace, and the raw text is kept in ``arguments``
    so the trajectory still shows what it tried.
    """
    def _garbage(_resp: str) -> str:
        return "<think>thinking</think>\n<tool_call>\n{not json\n</tool_call>"

    agent, _ = build_agent([_garbage, _turn_answer_uncited()], max_rounds=4)
    result = agent.run(QUERY, query_id=QID)
    step = result.steps[1]
    assert step["kind"] == "tool_call"
    assert step["name"] == "unknown"
    assert step["failed"] is True
    assert step["arguments"] == {"raw": "{not json"}
    assert "not a valid JSON" in step["output"]
    # The loop recovered and finished on the next round.
    assert result.status == "completed"


def test_single_quoted_tool_call_payload_is_repaired(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """``_parse_tool_call`` retries with ``'`` -> ``"`` before giving up."""
    def _single_quotes(_resp: str) -> str:
        return ("<think>thinking</think>\n<tool_call>\n"
                "{'name': 'search', 'arguments': {'query': 'flu vaccine'}}\n"
                "</tool_call>")

    agent, _ = build_agent([_single_quotes], max_rounds=1)
    result = agent.run(QUERY, query_id=QID)
    assert result.steps[1]["name"] == "search"
    assert result.steps[1]["failed"] is False
    assert stub_search_tool["semantic"][0]["query"] == "flu vaccine"


def test_unknown_tool_name_is_reported_not_fatal(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A hallucinated tool (the model's training had web browsing) must not crash.

    It also must not be counted as work done: ``tool_call_counts`` stays clean
    while ``tool_call_counts_all`` keeps the attempt, which is how a run's real
    protocol-error rate stays visible in the artifact.
    """
    def _unknown(_resp: str) -> str:
        return ("<think>thinking</think>\n<tool_call>\n"
                '{"name": "browse_web", "arguments": {"url": "http://x"}}\n'
                "</tool_call>")

    agent, _ = build_agent([_unknown], max_rounds=1)
    result = agent.run(QUERY, query_id=QID)
    step = result.steps[1]
    assert step["name"] == "browse_web"
    assert step["failed"] is True
    assert "not found" in step["output"]
    # The failed call is excluded from the OK counts but kept in the _all view.
    trajectory = steps_to_trajectory(
        result, build_metadata(QUERY, "mock", 5))
    assert trajectory["tool_call_counts"] == {}
    assert trajectory["tool_call_counts_all"] == {"browse_web": 1}


def test_hallucinated_tool_response_is_truncated(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """Upstream behaviour: anything the model writes past a ``<tool_response>``
    it authored itself is cut, so it cannot fake evidence."""
    def _fakes_response(_resp: str) -> str:
        return ("<think>thinking</think>\n"
                "<tool_response>\nDocID:shard_99999_1\nfabricated\n"
                "</tool_response>\n<answer>bogus</answer>")

    agent, _ = build_agent([_fakes_response, _turn_answer_uncited()],
                           max_rounds=3)
    result = agent.run(QUERY, query_id=QID)
    assistant = [m for m in result.messages if m["role"] == "assistant"][0]
    assert "<tool_response>" not in assistant["content"]
    assert "fabricated" not in assistant["content"]
    # The faked answer was cut too, so the run had to continue a round.
    assert result.rounds == 2


def test_untagged_leading_prose_becomes_reasoning(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """``_extract_think`` falls back to the prose before the first tag when the
    model forgets ``<think>``."""
    def _untagged(_resp: str) -> str:
        return ("I should look this up in the corpus.\n"
                "<tool_call>\n"
                '{"name": "search", "arguments": {"query": "flu"}}\n'
                "</tool_call>")

    agent, _ = build_agent([_untagged], max_rounds=1)
    result = agent.run(QUERY, query_id=QID)
    assert result.steps[0]["kind"] == "reasoning"
    assert result.steps[0]["text"] == "I should look this up in the corpus."


def test_answer_wins_over_a_same_turn_tool_call(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """``if toolcall_m and not answer_m`` — an ``<answer>`` in the same message
    suppresses the tool call, so the run cannot both act and finish."""
    def _both(_resp: str) -> str:
        return ("<think>thinking</think>\n<tool_call>\n"
                '{"name": "search", "arguments": {"query": "flu"}}\n'
                "</tool_call>\n<answer>Final answer here.</answer>")

    agent, _ = build_agent([_both], max_rounds=3)
    result = agent.run(QUERY, query_id=QID)
    assert result.status == "completed"
    assert [s["kind"] for s in result.steps] == ["reasoning", "answer"]
    assert "semantic" not in stub_search_tool


def test_context_guard_forces_a_final_answer(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """Over the char-limit guard the loop spends ONE extra turn demanding an
    answer and finishes as ``budget_exhausted`` — it does not keep researching.
    """
    agent, llm = build_agent([_turn_search, _turn_answer_uncited()],
                             max_rounds=6)
    agent.context_char_limit = 1   # any real history exceeds this
    result = agent.run(QUERY, query_id=QID)
    assert result.status == "budget_exhausted"
    assert result.rounds == 1
    assert llm.calls == 2
    assert result.answer_text == "A short final answer."
    # The forced-answer turn is unconstrained by the stop sequence.
    assert result.messages[-2]["content"].startswith(
        "You have now reached the maximum context length")
    assert llm.seen_stops[-1] is None


def _turn_answer_uncited() -> Callable[[str], str]:
    def _answer(_resp: str) -> str:
        return "<think>done</think>\n<answer>A short final answer.</answer>"
    return _answer


# ---------------------------------------------------------------------------
# ClimbMixTools behaviour reached through the loop
# ---------------------------------------------------------------------------
def test_search_dedups_across_steps(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """The stub returns the same ids every time, so a second identical search
    must surface NO new results and list them all as already-seen."""
    toolbox = ClimbMixTools()
    first, first_meta = toolbox.search("flu vaccine", k=3)
    second, second_meta = toolbox.search("flu vaccine again", k=3)
    assert first_meta["returned_docids"] == list(CLIMBMIX_DOCIDS[:3])
    assert second_meta["returned_docids"] == []
    assert second_meta["hidden"] == list(CLIMBMIX_DOCIDS[:3])
    assert second_meta["previous_queries_before_search"] == ["flu vaccine"]
    assert "## Already-seen" in second
    assert "found 0 results" in second


def test_search_error_envelope_is_surfaced_as_tool_text(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A backend outage must reach the model as text, not as a traceback.

    The ReAct loop has no retry of its own: if ``dispatch`` propagated, one
    flaky search would lose the topic. Handing the error to the model lets it
    reword the query or fall back to what it already has.
    """
    from tools import search_tool

    def _boom(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        raise RuntimeError("backend down")

    monkeypatch.setitem(search_tool._DISPATCH, "semantic", _boom)
    text, meta, failed = dispatch(ClimbMixTools(), "search",
                                  {"query": "flu"}, k=3)
    assert failed is True
    assert meta["failed"] is True
    assert "backend down" in text


@pytest.mark.parametrize("name,args,fragment", [
    ("search", {}, "missing 'query'"),
    ("get_document", {}, "missing 'docid'"),
    ("visit", {"url": "x"}, "not found"),
])
def test_dispatch_rejects_bad_calls_without_raising(
        name: str, args: dict[str, Any], fragment: str,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """Every malformed call shape returns actionable text instead of raising.

    A missing required argument and an unavailable tool (``visit`` exists in the
    upstream Tongyi toolset but not in ours) are both routine model errors; the
    message has to name the problem so the next round can fix it.
    """
    text, meta, failed = dispatch(ClimbMixTools(), name, args, k=3)
    assert failed is True
    assert fragment in text


def test_get_document_failure_is_surfaced_not_raised(
        stub_fetch_doc: dict[str, list[str]]) -> None:
    """A 404 from the doc endpoint is a normal outcome of a hallucinated docid.

    The fetch client is separate from search, so this is its own failure path —
    and it must degrade to tool text, since the model routinely asks for ids it
    half-remembered from a snippet.
    """
    text, meta = ClimbMixTools().get_document("missing_doc_1")
    assert meta["failed"] is True
    assert "Error retrieving document missing_doc_1" in text


def test_candidate_docids_skips_failed_get_document(
        stub_search_tool: dict[str, list[dict[str, Any]]],
        stub_fetch_doc: dict[str, list[str]]) -> None:
    """A get_document that 404s must not put its docid in the allow-list — the
    model never read that text, so nothing may be cited to it."""
    def _open_missing(resp: str) -> str:
        return ("<think>opening</think>\n<tool_call>\n"
                '{"name": "get_document", "arguments": '
                '{"docid": "missing_doc_1"}}\n</tool_call>')

    agent, _ = build_agent([_turn_search, _open_missing,
                            _turn_answer_uncited()], max_rounds=4)
    result = agent.run(QUERY, query_id=QID)
    candidates = candidate_docids(result)
    assert "missing_doc_1" not in candidates
    assert candidates == list(CLIMBMIX_DOCIDS[:4])


# ---------------------------------------------------------------------------
# answer_format.format_answer — both paths
# ---------------------------------------------------------------------------
def test_format_answer_offline_heuristic_is_deterministic() -> None:
    """The no-LLM path must produce a valid, reproducible answer on its own.

    It is the fallback every other formatting failure lands on, so it has to
    satisfy the track rules unaided: sentence split, every reference cited
    (round-robin), at most 3 citations each. Determinism matters because two
    runs of the same draft must not differ in the submission.
    """
    draft = "First claim here. Second claim here. Third claim here."
    docids = ["d1", "d2", "d3", "d4"]
    refs, answer = format_answer(draft, docids, llm=None)
    assert refs == docids
    assert [s["text"] for s in answer] == [
        "First claim here.", "Second claim here.", "Third claim here."]
    # Round-robin: every reference cited, at most MAX_CITATIONS per sentence.
    cited = {c for s in answer for c in s["citations"]}
    assert cited == set(range(len(refs)))
    assert all(len(s["citations"]) <= MAX_CITATIONS for s in answer)
    # Deterministic: the same input yields byte-identical output.
    assert format_answer(draft, docids, llm=None) == (refs, answer)


def test_format_answer_offline_dedups_candidate_docids() -> None:
    """A docid seen twice (searched, then opened) must appear once in references.

    ``candidate_docids`` concatenates two sources, so duplicates are normal
    input. A repeated reference is a duplicated citation index in the
    submission, and the second copy would end up uncited.
    """
    refs, _ = format_answer("One sentence.", ["d1", "d2", "d1"], llm=None)
    assert refs == ["d1", "d2"]


def test_format_answer_offline_strips_markdown() -> None:
    """Answer sentences are scored as plain text, so Markdown is noise.

    Fenced blocks are dropped entirely (no citable claim) and headings/emphasis
    are unwrapped in place — a leaked ``**`` or a code block would be graded as
    part of the sentence by the nugget judge.
    """
    draft = ("## Heading\n"
             "- A **bold** claim with `code`.\n"
             "```\nfenced block\n```\n"
             "Another claim.")
    _, answer = format_answer(draft, ["d1"], llm=None)
    texts = [s["text"] for s in answer]
    assert "fenced block" not in " ".join(texts)
    assert "**" not in " ".join(texts)
    assert texts[0].startswith("Heading A bold claim with code.")


def test_format_answer_offline_trims_to_the_word_budget() -> None:
    """An over-length answer is rejected outright by the track validator.

    The ReAct model has no word budget in its prompt (unlike aus_agent's report
    contract), so the formatter is the only thing standing between a rambling
    draft and an invalid submission.
    """
    from ali_deepresearch.answer_format import MAX_WORDS

    sentence = " ".join(["word"] * 100) + "."
    refs, answer = format_answer(" ".join([sentence] * 20), ["d1"], llm=None)
    assert sum(len(s["text"].split()) for s in answer) <= MAX_WORDS


def test_format_answer_offline_handles_an_empty_draft() -> None:
    """A run that never answered still has to produce a valid output object.

    ``answer`` must be a non-empty list with every reference cited, so the
    placeholder sentence (cited to the first candidate) is what keeps a
    budget-exhausted run writable instead of crashing the batch.
    """
    refs, answer = format_answer("", ["d1"], llm=None)
    assert answer == [{"text": "No answer was produced.", "citations": [0]}]
    assert refs == ["d1"]


class _FormatterLLM:
    """A ``ChatLLM`` returning a canned formatter response (records prompts)."""

    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply
        self.prompts: list[str] = []

    def complete(self, messages: list[dict[str, str]], *,
                 stop: list[str] | None = None,
                 max_tokens: int | None = None) -> str:
        self.prompts.append(messages[-1]["content"])
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def test_format_answer_llm_path_uses_the_model_sentences() -> None:
    """The formatter model decides sentence-level attribution, not the order.

    References are numbered by FIRST CITATION, so index 0 is whatever the answer
    cites first — not the top-ranked candidate. The allow-list must also go into
    the prompt verbatim, since that is the only thing telling the model which
    ids exist.
    """
    llm = _FormatterLLM(json.dumps({"sentences": [
        {"text": "Vaccines reduce confirmed illness.", "citations": ["d2"]},
        {"text": "Effectiveness varies by season.", "citations": ["d1"]},
    ]}))
    refs, answer = format_answer("draft prose", ["d1", "d2"], llm=llm)
    # References are in FIRST-CITED order, not candidate order.
    assert refs == ["d2", "d1"]
    assert answer == [
        {"text": "Vaccines reduce confirmed illness.", "citations": [0]},
        {"text": "Effectiveness varies by season.", "citations": [1]},
    ]
    # The allow-list is handed to the model verbatim as JSON.
    assert '["d1", "d2"]' in llm.prompts[0]


def test_format_answer_llm_citations_are_constrained_to_the_allow_list() -> None:
    """CORRECTNESS-CRITICAL: a hallucinated docid must never reach references.

    The formatter model is free to invent ids; ``_from_llm_json`` filters every
    citation against the candidate allow-list before indexing it, so an invented
    id is dropped and the sentence simply loses that citation.
    """
    llm = _FormatterLLM(json.dumps({"sentences": [
        {"text": "Grounded claim.", "citations": ["d1"]},
        {"text": "Invented claim.", "citations": ["shard_HALLUCINATED_1"]},
    ]}))
    refs, answer = format_answer("draft", ["d1", "d2"], llm=llm)
    assert refs == ["d1"]
    assert "shard_HALLUCINATED_1" not in refs
    assert answer[1]["citations"] == []


def test_format_answer_llm_all_citations_hallucinated_falls_back() -> None:
    """When NOTHING survives the allow-list filter the LLM result is unusable
    (``parsed[0]`` is empty), so the deterministic heuristic takes over — which
    is what keeps every reference cited."""
    llm = _FormatterLLM(json.dumps({"sentences": [
        {"text": "Invented claim.", "citations": ["nope"]}]}))
    refs, answer = format_answer("Draft sentence one. Draft sentence two.",
                                 ["d1"], llm=llm)
    assert refs == ["d1"]
    assert answer[0]["text"] == "Draft sentence one."
    assert answer[0]["citations"] == [0]


def test_format_answer_llm_caps_citations_per_sentence() -> None:
    """Over-citing is a hard validator failure, so the extras are dropped here.

    The subtle part is what happens to the 4th docid: it must not be registered
    as a reference at all, or the output would carry a reference nothing cites —
    trading one violation for another.
    """
    llm = _FormatterLLM(json.dumps({"sentences": [
        {"text": "Everything at once.",
         "citations": ["d1", "d2", "d3", "d4"]}]}))
    refs, answer = format_answer("draft", ["d1", "d2", "d3", "d4"], llm=llm)
    assert len(answer[0]["citations"]) == MAX_CITATIONS
    # References are re-indexed down to the ones still cited, so validation
    # (every reference cited) still passes.
    assert refs == ["d1", "d2", "d3"]
    assert answer[0]["citations"] == [0, 1, 2]


@pytest.mark.parametrize("reply", [
    "no json here at all",
    '{"sentences": []}',
    '{"sentences": "not a list"}',
    '{"nope": 1}',
    '{"sentences": [{"text": "   ", "citations": ["d1"]}]}',
    "{broken json",
])
def test_format_answer_llm_garbage_falls_back_to_heuristic(reply: str) -> None:
    """Formatting is a second LLM call, so every malformed reply shape is traffic.

    Each case here is a different way the JSON contract can be broken (no JSON,
    empty list, wrong type, wrong key, blank text, truncated). All must degrade
    to the deterministic heuristic — the run's retrieval work is already done and
    must not be thrown away over a formatting hiccup.
    """
    llm = _FormatterLLM(reply)
    refs, answer = format_answer("Draft one. Draft two.", ["d1"], llm=llm)
    assert refs == ["d1"]
    assert [s["text"] for s in answer] == ["Draft one.", "Draft two."]


def test_format_answer_llm_exception_falls_back_to_heuristic() -> None:
    """A provider outage must degrade to a valid answer, not lose the run.

    The formatting call happens after all retrieval; letting a 503 propagate
    would discard a completed research trajectory at the last step.
    """
    llm = _FormatterLLM(RuntimeError("endpoint 503"))
    refs, answer = format_answer("Draft one.", ["d1"], llm=llm)
    assert refs == ["d1"]
    assert answer[0]["text"] == "Draft one."


def test_format_answer_llm_skipped_for_an_empty_draft() -> None:
    """``if llm is not None and answer_text`` — no draft, no formatting call."""
    llm = _FormatterLLM('{"sentences": [{"text": "x", "citations": ["d1"]}]}')
    refs, answer = format_answer("", ["d1"], llm=llm)
    assert llm.prompts == []
    assert answer[0]["text"] == "No answer was produced."


def test_format_answer_llm_path_via_scripted_provider() -> None:
    """The real production wiring for facet_rag / o3_deep_research: a turn-based
    ``Provider`` adapted to the ChatLLM shape by ``facet_rag`` and driven here by
    the shared ``ScriptedProvider``."""
    from facet_rag.pipeline import _ProviderLLM

    provider = ScriptedProvider([model_turn(text=json.dumps({"sentences": [
        {"text": "Provider-formatted sentence.", "citations": ["d1"]}]}))])
    refs, answer = format_answer("draft prose", ["d1", "d2"],
                                 llm=_ProviderLLM(provider))
    assert refs == ["d1"]
    assert answer == [{"text": "Provider-formatted sentence.",
                       "citations": [0]}]
    assert provider.turn_index == 1
    assert "ALLOWED DOCIDS:" in provider.user_messages[0]


def test_full_run_with_llm_formatting(
        stub_search_tool: dict[str, list[dict[str, Any]]],
        stub_fetch_doc: dict[str, list[str]]) -> None:
    """End-to-end with the LLM formatter instead of the offline heuristic; the
    formatter cites the docid the agent actually opened."""
    agent, _ = build_agent(SCRIPT_THREE_ROUNDS)
    result = agent.run(QUERY, query_id=QID)
    opened = stub_fetch_doc["docids"][0]
    llm = _FormatterLLM(json.dumps({"sentences": [
        {"text": "Vaccines reduce confirmed influenza illness.",
         "citations": [opened]}]}))
    assembled = assemble(result, llm=llm)
    assert assembled["references"] == [opened]
    assert validate_rag_output(assembled["output"]) == []
    assert "violations" not in assembled["paths"]


# ---------------------------------------------------------------------------
# Live (deselected by default)
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_react_run_live_against_real_backends() -> None:
    """The original ``test_mock.py``: scripted LLM, REAL search + get_document.

    Needs ``SEARCH_API_KEY`` / ``PYSERINI_API_TOKEN``.
    """
    agent, _ = build_agent(SCRIPT_THREE_ROUNDS)
    result = agent.run(QUERY, query_id="live_flu_001")
    assert result.status == "completed"
    assembled = assemble(result, run_id="ali_deepresearch.live")
    assert assembled["trajectory"]["tool_call_counts"] == {
        "search": 1, "get_document": 1}
    assert assembled["trajectory"]["retrieved_docids"]
    assert assembled["references"]
    assert validate_rag_output(assembled["output"]) == []
