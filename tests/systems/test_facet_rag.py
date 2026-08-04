"""End-to-end + unit coverage for ``src/systems/facet_rag``'s orchestrator/
analyzer architecture.

Two roles, two ``ScriptedProvider`` factories: ORCHESTRATOR (plans facets,
drives the search tool, drafts the final report) and ANALYZER (judges
retrieved passages per facet, reports coverage gaps, fact-checks the draft).
Each factory hands out a FRESH ``ScriptedProvider`` instance per call — a
``Provider`` owns its own conversation, and ``run_one`` constructs many of
them (one per facet's orchestrator, one per facet's analyzer, plus plan/
draft/fact-check/format calls). Responders route by the prompt's unique
marker text (``FACET:``, ``Coverage gap reported``, ``EVIDENCE:``, etc., one
per prompt template in ``prompts.py``) rather than by call order, which stays
correct under ``run_one``'s concurrent per-facet execution.

Loop-mechanics tests (stop conditions, gap feedback, evidence dedup within a
facet) call ``run_facet_loop`` directly instead of going through the full
pipeline — that keeps them single-threaded and deterministic, since
``run_one`` runs facets concurrently and only aggregate properties (not
per-instance call order) are safe to assert there.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn

from ragrun import validate_rag_output

from facet_rag import parse_facets, run_facet_loop, run_one
from facet_rag.loop import Analysis, parse_analysis, usage_token_stats
from facet_rag.planner import (
    DEFAULT_MAX_ITERATIONS,
    GLOBAL_ITERATION_CAP,
    Facet,
    build_plan_prompt,
    fallback_facets,
)

NARRATIVE = "How effective are influenza vaccines at preventing illness?"
QID = "mock_facet_001"
ENGINES = ["semantic", "keyword"]

_DOCID_RE = re.compile(r"\[docid=(\S+?)\]")
_EVIDENCE_DOCID_RE = re.compile(r"docid=(\S+)")
_ALLOWED_DOCIDS_RE = re.compile(r"ALLOWED DOCIDS:\s*(\[.*?\])", re.DOTALL)


# ---------------------------------------------------------------------------
# Scripted responders — route by each prompt's unique marker text
# ---------------------------------------------------------------------------
def _search_call(*, call_id: str, query: str = "q", engine: str = "semantic",
                 k: int = 5) -> list[dict[str, Any]]:
    return [{"id": call_id, "name": "search",
             "arguments": {"query": query, "search_engine": engine, "k": k}}]


def _format_text(pending: str) -> str:
    match = _ALLOWED_DOCIDS_RE.search(pending)
    docids = json.loads(match.group(1)) if match else []
    cites = docids[:1]
    return json.dumps({"sentences": [
        {"text": "Influenza vaccines reduce illness risk.", "citations": cites},
        {"text": "Effectiveness varies by season.", "citations": cites},
    ]})


def _cited_text(pending: str) -> str:
    docids = _EVIDENCE_DOCID_RE.findall(pending)
    cite = f"[{docids[0]}]" if docids else ""
    return f"Vaccines reduce illness risk {cite}. Effectiveness varies by season {cite}."


def make_orchestrator_responder(
        *, facets: list[dict[str, Any]], stop_on_gap: bool = True
        ) -> Callable[[str, int], dict[str, Any]]:
    """Plans, searches once per facet turn, drafts, and formats.

    ``stop_on_gap=False`` makes it search again on a coverage-gap follow-up
    instead of ending the loop, for tests that need more than one iteration.
    """
    def _respond(pending: str, turn_index: int) -> dict[str, Any]:
        if "ALLOWED DOCIDS:" in pending:
            return model_turn(text=_format_text(pending))
        if "Coverage gap reported" in pending:
            if stop_on_gap:
                return model_turn(text="No further search would help.")
            return model_turn(tool_calls=_search_call(
                call_id=f"call_gap_{turn_index}", query="follow-up query"))
        if "FACET:" in pending:
            return model_turn(tool_calls=_search_call(call_id=f"call_{turn_index}"))
        if "EVIDENCE:" in pending:
            return model_turn(text=_cited_text(pending))
        if "RESEARCH NARRATIVE:" in pending:
            return model_turn(text=json.dumps({"facets": facets}))
        raise AssertionError(
            f"unrecognised orchestrator prompt at turn {turn_index}: {pending[:150]!r}")
    return _respond


def make_analyzer_responder(
        *, satisfied: bool = True, gap: str = "need more detail on strain match"
        ) -> Callable[[str, int], dict[str, Any]]:
    def _respond(pending: str, turn_index: int) -> dict[str, Any]:
        if "DRAFT:" in pending:
            return model_turn(text=_cited_text(pending))
        if "NEWLY RETRIEVED PASSAGES:" in pending:
            docids = _DOCID_RE.findall(pending)
            relevant = [{"docid": d, "note": "supports the facet"} for d in docids[:1]]
            return model_turn(text=json.dumps({
                "relevant": relevant,
                "gap": None if satisfied else gap,
                "satisfied": satisfied,
            }))
        raise AssertionError(
            f"unrecognised analyzer prompt at turn {turn_index}: {pending[:150]!r}")
    return _respond


ONE_FACET_PLAN = [{"name": "effectiveness",
                   "description": "How effective are flu vaccines at "
                                  "preventing illness?", "max_iterations": 3}]
TWO_FACET_PLAN = [
    {"name": "effectiveness", "description": "How effective are flu vaccines?",
     "max_iterations": 2},
    {"name": "strain match", "description": "How well do vaccines match "
                                            "circulating strains?",
     "max_iterations": 2},
]


@pytest.fixture
def pipeline_run(stub_search_tool: dict[str, list[dict[str, Any]]],
                 read_artifacts: Callable[..., dict[str, Any]]
                 ) -> dict[str, Any]:
    """One full hermetic ``run_one`` — two facets, both satisfied in 1 round.

    Returned as a fixture because several assertions below are all about the
    same single run; re-running it per test would only slow the suite down.
    """
    orch_factory = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=TWO_FACET_PLAN))
    analyzer_factory = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=True))
    result = run_one(
        orch_factory, analyzer_factory, qid=QID, narrative=NARRATIVE,
        engines=ENGINES, run_id="facet_rag.mock", run_desc="mock end-to-end",
        orchestrator_model_id="mock-orchestrator", analyzer_model_id="mock-analyzer",
        max_chars=800, min_facets=2, max_facets=2, format_llm=True)
    artifacts = read_artifacts(result["paths"])
    return {"result": result, "calls": stub_search_tool,
            "trajectory": artifacts["trajectory"], "output": artifacts["output"],
            "violations": artifacts["violations"]}


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
def test_run_one_completes_and_writes_both_artifacts(
        pipeline_run: dict[str, Any]) -> None:
    """A submission-ready run leaves no ``output.violations.json`` behind."""
    result, paths = pipeline_run["result"], pipeline_run["result"]["paths"]
    assert result["status"] == "completed"
    assert paths["trajectory"].exists()
    assert paths["output"].exists()
    assert "violations" not in paths
    assert pipeline_run["violations"] == []


def test_run_one_output_passes_track_validation(
        pipeline_run: dict[str, Any]) -> None:
    """Validate the artifact as re-read from disk, not just in memory."""
    assert validate_rag_output(pipeline_run["output"]) == []


def test_run_one_plans_both_facets(pipeline_run: dict[str, Any]) -> None:
    """The plan the orchestrator returned is the plan that got looped, in order.

    Multi-facet coverage is the entire premise of this system: if the planned
    facets were silently merged or reordered, the run would degrade to a
    single search loop while still looking successful.
    """
    facets = pipeline_run["result"]["facets"]
    assert [f.name for f in facets] == [TWO_FACET_PLAN[0]["name"],
                                        TWO_FACET_PLAN[1]["name"]]
    assert [f.max_iterations for f in facets] == [2, 2]


def test_run_one_one_search_per_facet_when_satisfied_first_round(
        pipeline_run: dict[str, Any]) -> None:
    """The analyzer reports satisfied on the first pass, so each facet's loop
    does exactly one search — no wasted follow-up rounds."""
    counts = pipeline_run["trajectory"]["tool_call_counts"]
    assert counts.get("search") == len(pipeline_run["result"]["facets"]) == 2


def test_run_one_evidence_merged_and_deduped_across_facets(
        pipeline_run: dict[str, Any]) -> None:
    """Both facets search the same stubbed corpus (same docids come back), so
    the merged evidence must dedupe by docid rather than double-count it.

    This is the multi-facet analogue of the old plan-then-execute dedup: now
    it happens on ANALYST-VETTED evidence, not on raw retrieved passages.
    """
    evidence = pipeline_run["result"]["evidence"]
    docids = [e["docid"] for e in evidence]
    assert len(docids) == len(set(docids))
    # Each facet's analyzer kept exactly its first docid; both facets see the
    # same stubbed corpus, so without dedup this would be 2 with duplicates.
    assert len(evidence) == 1
    assert evidence[0]["facet"] == TWO_FACET_PLAN[0]["name"]  # first facet wins


def test_run_one_retrieved_docids_and_references_non_empty(
        pipeline_run: dict[str, Any]) -> None:
    """The two fields a grounded run cannot be empty in."""
    assert pipeline_run["trajectory"]["retrieved_docids"]
    assert pipeline_run["result"]["references"]


def test_run_one_every_reference_is_cited(pipeline_run: dict[str, Any]) -> None:
    """An uncited reference is a spec violation that fails silently."""
    output = pipeline_run["output"]
    cited = {c for s in output["answer"] for c in s["citations"]}
    assert cited == set(range(len(output["references"])))


def test_run_one_trace_lives_only_in_output(
        pipeline_run: dict[str, Any]) -> None:
    """The rich trace is an internal artifact: output.json only, never the
    organizer-facing trajectory."""
    trace = pipeline_run["output"].get("trace", {})
    assert isinstance(trace.get("steps"), list)
    assert len(trace["steps"]) >= 4  # plan + 2 oss_turn + 2 qwen_analysis + draft/check
    assert "trace" not in pipeline_run["trajectory"]


def test_run_one_strict_result_starts_with_plan_reasoning(
        pipeline_run: dict[str, Any]) -> None:
    """The plan is the only ``add_reasoning`` call; every facet turn and the
    draft/fact-check pass are rich-only ``generation`` spans (not in strict
    result), matching the old synthesis stage's rich-only treatment."""
    kinds = [item["type"] for item in pipeline_run["trajectory"]["result"]]
    assert kinds[0] == "reasoning"
    assert kinds.count("reasoning") == 1
    assert kinds[-1] == "output_text"
    assert kinds.count("tool_call") == 2


def test_run_one_tool_call_items_name_their_facet(
        pipeline_run: dict[str, Any]) -> None:
    """Each recorded search must say WHICH facet it served.

    Without the ``facet`` annotation the trajectory is an unattributed list
    of queries, and per-facet effectiveness cannot be reconstructed later.
    """
    items = [i for i in pipeline_run["trajectory"]["result"]
             if i["type"] == "tool_call"]
    assert {i["facet"] for i in items} == {TWO_FACET_PLAN[0]["name"],
                                           TWO_FACET_PLAN[1]["name"]}


def test_unparseable_plan_falls_back_in_the_pipeline(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A garbage plan must still retrieve something (via ``fallback_facets``)."""
    def _orch(pending: str, turn_index: int) -> dict[str, Any]:
        if "ALLOWED DOCIDS:" in pending:
            return model_turn(text=_format_text(pending))
        if "FACET:" in pending:
            return model_turn(tool_calls=_search_call(call_id=f"c{turn_index}"))
        if "EVIDENCE:" in pending:
            return model_turn(text=_cited_text(pending))
        return model_turn(text="I could not produce a plan, sorry.")

    orch_factory = lambda: ScriptedProvider(_orch)  # noqa: E731
    analyzer_factory = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=True))
    result = run_one(
        orch_factory, analyzer_factory, qid=QID, narrative=NARRATIVE,
        engines=ENGINES, run_id="facet_rag.mock", run_desc="fallback plan",
        orchestrator_model_id="mock-orchestrator", analyzer_model_id="mock-analyzer",
        max_chars=800, min_facets=2, max_facets=4, format_llm=True)
    assert [f.name for f in result["facets"]] == ["whole narrative"]
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# loop.run_facet_loop — direct, single-threaded (no ThreadPoolExecutor)
# ---------------------------------------------------------------------------
def test_loop_stops_when_analyzer_is_satisfied(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """The common case: one search, the analyzer accepts it, loop ends early —
    well under the facet's iteration budget."""
    facet = Facet(name="effectiveness", description="How effective?",
                  max_iterations=5)
    orch = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=ONE_FACET_PLAN))
    analyzer = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=True))
    result = run_facet_loop(make_orchestrator=orch, make_analyzer=analyzer,
                            facet=facet, engines=ENGINES, max_chars=800)
    assert result.stop_reason == "analyzer_satisfied"
    assert result.iterations_used == 1
    assert len(result.evidence) == 1


def test_loop_stops_when_orchestrator_issues_no_search() -> None:
    """If the orchestrator declines to search at all (no tool call on its
    first turn), the loop must not spin — there is nothing to analyze."""
    def _orch(pending: str, turn_index: int) -> dict[str, Any]:
        return model_turn(text="Nothing to search for.")

    facet = Facet(name="effectiveness", description="How effective?",
                  max_iterations=5)
    orch = lambda: ScriptedProvider(_orch)  # noqa: E731
    analyzer = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=True))
    result = run_facet_loop(make_orchestrator=orch, make_analyzer=analyzer,
                            facet=facet, engines=ENGINES, max_chars=800)
    assert result.stop_reason == "orchestrator_no_search"
    assert result.iterations_used == 1
    assert result.evidence == []


def test_loop_gap_is_fed_back_to_the_orchestrator(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A coverage gap from the analyzer must reach the orchestrator's NEXT
    turn verbatim — otherwise "search again to fill the gap" has no effect."""
    facet = Facet(name="effectiveness", description="How effective?",
                  max_iterations=5)
    orch_factory = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=ONE_FACET_PLAN, stop_on_gap=True))
    analyzer_factory = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=False, gap="need strain-match data"))
    result = run_facet_loop(make_orchestrator=orch_factory,
                            make_analyzer=analyzer_factory, facet=facet,
                            engines=ENGINES, max_chars=800)
    # Iteration 1: search + gap reported (not satisfied). Iteration 2: the
    # orchestrator responder ends the loop once it sees the gap (stop_on_gap).
    assert result.stop_reason == "orchestrator_no_search"
    assert result.iterations_used == 2


def test_loop_caps_iterations_at_ten_regardless_of_facet_value(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """The spec's hard ceiling: a facet claiming ``max_iterations=99`` must
    still stop at 10 — the planner's number is a request, not a grant."""
    facet = Facet(name="stubborn", description="Never satisfied", max_iterations=99)
    orch = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=ONE_FACET_PLAN, stop_on_gap=False))
    analyzer = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=False, gap="still missing something"))
    result = run_facet_loop(make_orchestrator=orch, make_analyzer=analyzer,
                            facet=facet, engines=ENGINES, max_chars=800)
    assert result.iterations_used == GLOBAL_ITERATION_CAP
    assert result.stop_reason == "max_iterations"


def test_loop_no_new_passages_skips_analysis_and_keeps_going(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A repeat search (same docids the loop already saw) has nothing new to
    analyze, so the loop feeds a gap straight back WITHOUT calling the
    analyzer — verified via the analyzer's own single-turn queue: if the loop
    called it a second time here, ``ScriptedProvider`` would raise on the
    exhausted queue instead of the run completing cleanly."""
    facet = Facet(name="effectiveness", description="How effective?",
                  max_iterations=2)
    # stop_on_gap=False: the orchestrator searches again on EVERY gap prompt
    # (from the analyzer on iteration 1, from the loop's own "no new
    # passages" note on iteration 2) rather than ending the loop itself, so
    # the cap is what stops it.
    orch = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=ONE_FACET_PLAN, stop_on_gap=False))
    analyzer = lambda: ScriptedProvider([  # noqa: E731
        model_turn(text=json.dumps({
            "relevant": [{"docid": CLIMBMIX_DOCIDS[0], "note": "supports it"}],
            "gap": None, "satisfied": False}))])
    result = run_facet_loop(make_orchestrator=orch, make_analyzer=analyzer,
                            facet=facet, engines=ENGINES, max_chars=800)
    # Iteration 1: search returns docids, analyzer keeps one, not satisfied.
    # Iteration 2: orchestrator searches again (stub returns the SAME docids
    # regardless of query -> nothing NEW), so no second analyzer call; the
    # facet's 2-iteration cap is what ends the loop.
    assert result.stop_reason == "max_iterations"
    assert result.iterations_used == 2
    assert len(result.evidence) == 1


# ---------------------------------------------------------------------------
# loop.parse_analysis
# ---------------------------------------------------------------------------
def test_parse_analysis_valid_json() -> None:
    """The baseline contract: a well-formed analysis becomes exactly that
    ``Analysis`` — every tolerance test below is a deviation from this shape."""
    raw = json.dumps({"relevant": [{"docid": "d1", "note": "supports X"}],
                      "gap": "need Y", "satisfied": False})
    assert parse_analysis(raw, valid_docids={"d1"}) == Analysis(
        relevant=[{"docid": "d1", "note": "supports X"}],
        gap="need Y", satisfied=False)


def test_parse_analysis_drops_docids_outside_the_allow_list() -> None:
    """The analyzer only ever sees ``valid_docids``, but a hallucinated or
    stale docid must not be accepted into evidence."""
    raw = json.dumps({"relevant": [{"docid": "d1", "note": "ok"},
                                   {"docid": "hallucinated", "note": "bad"}],
                      "gap": None, "satisfied": True})
    result = parse_analysis(raw, valid_docids={"d1"})
    assert result.relevant == [{"docid": "d1", "note": "ok"}]


def test_parse_analysis_null_gap_becomes_none() -> None:
    """A JSON ``null`` gap (the satisfied case) must not become the string
    ``"None"`` or an empty-but-truthy value."""
    raw = json.dumps({"relevant": [], "gap": None, "satisfied": True})
    assert parse_analysis(raw, valid_docids=set()).gap is None


def test_parse_analysis_malformed_stops_the_loop_rather_than_spin() -> None:
    """Unparseable analyzer output is treated as satisfied=True (not a retry
    loop) so a facet whose analyzer keeps failing doesn't burn its whole
    iteration budget on a stage that will never produce evidence."""
    result = parse_analysis("not json at all", valid_docids={"d1"})
    assert result == Analysis(relevant=[], gap=None, satisfied=True)


def test_parse_analysis_strips_fences() -> None:
    """Models wrap JSON in Markdown fences unprompted, so it must be tolerated."""
    raw = "```json\n" + json.dumps({"relevant": [], "gap": None,
                                    "satisfied": True}) + "\n```"
    assert parse_analysis(raw, valid_docids=set()).satisfied is True


# ---------------------------------------------------------------------------
# planner.parse_facets / fallback_facets / build_plan_prompt
# ---------------------------------------------------------------------------
def _plan(facets: list[dict[str, Any]]) -> str:
    return json.dumps({"facets": facets})


def test_parse_facets_valid_json() -> None:
    """The baseline contract for facet parsing."""
    facets = parse_facets(_plan(ONE_FACET_PLAN))
    assert facets == [Facet(name="effectiveness",
                            description=ONE_FACET_PLAN[0]["description"],
                            max_iterations=3)]


def test_parse_facets_clamps_max_iterations() -> None:
    """The spec's hard ceiling applies at parse time too, not just in the
    loop — a facet must not even report a >10 budget in the artifact."""
    facets = parse_facets(_plan([{"description": "d", "max_iterations": 99}]))
    assert facets[0].max_iterations == GLOBAL_ITERATION_CAP
    facets = parse_facets(_plan([{"description": "d", "max_iterations": 0}]))
    assert facets[0].max_iterations == 1


def test_parse_facets_defaults_max_iterations_when_missing_or_unparseable() -> None:
    """A model that omits or mangles ``max_iterations`` still gets a usable
    facet rather than losing it."""
    facets = parse_facets(_plan([{"description": "d"},
                                 {"description": "d2", "max_iterations": "nope"}]))
    assert [f.max_iterations for f in facets] == [DEFAULT_MAX_ITERATIONS] * 2


def test_parse_facets_skips_rows_without_a_description() -> None:
    """Rows with no description (or that are not objects) are dropped, not
    fatal — ``description`` is the only thing the orchestrator's loop needs."""
    facets = parse_facets(_plan([{"name": "empty"}, "a bare string",
                                 {"description": "usable"}]))
    assert [f.description for f in facets] == ["usable"]


def test_parse_facets_names_default_to_the_description_head() -> None:
    """A nameless facet still needs a label, because it is stamped on every
    trajectory tool_call item."""
    long_desc = "a" * 60
    facets = parse_facets(_plan([{"description": long_desc}]))
    assert facets[0].name == long_desc[:40]


@pytest.mark.parametrize("raw", [
    "not json at all", "{", "[]", '{"facets": "not a list"}',
    '{"nope": []}', "",
])
def test_parse_facets_malformed_yields_empty_list(raw: str) -> None:
    """Malformed plan JSON returns ``[]``, letting ``fallback_facets`` take
    over instead of the run dying."""
    assert parse_facets(raw) == []


def test_fallback_facets_gets_the_full_iteration_budget() -> None:
    """The safety net covers the WHOLE narrative as the only facet, so it
    gets the full 10-iteration budget rather than the default 4 — it has no
    sibling facets to share the run's search cost with."""
    facets = fallback_facets(f"  {NARRATIVE}  ")
    assert facets == [Facet(name="whole narrative", description=NARRATIVE,
                            max_iterations=GLOBAL_ITERATION_CAP)]


def test_build_plan_prompt_renders_facet_count_bounds_and_narrative() -> None:
    """The prompt is the only place the facet-count band is explained to the
    orchestrator."""
    prompt = build_plan_prompt(NARRATIVE, min_facets=2, max_facets=4)
    assert "2-4 facets" in prompt
    assert NARRATIVE in prompt


# ---------------------------------------------------------------------------
# loop.usage_token_stats
# ---------------------------------------------------------------------------
def test_usage_token_stats_returns_none_for_empty_usage() -> None:
    """No token block at all when a provider reports nothing."""
    assert usage_token_stats({}) is None


@pytest.mark.parametrize("usage", [
    {"inputTokens": 100, "outputTokens": 50,
     "cacheReadInputTokens": 900, "cacheWriteInputTokens": 0},
    {"input_tokens": 100, "output_tokens": 50,
     "cache_read_input_tokens": 900, "cache_write_input_tokens": 0},
])
def test_usage_token_stats_normalizes_both_key_shapes(
        usage: dict[str, Any]) -> None:
    """Bedrock camelCase and OpenAI snake_case must reduce to identical numbers."""
    assert usage_token_stats(usage) == {
        "input": 1000, "input_uncached": 100, "output": 50,
        "cache_read": 900, "cache_write": 0, "total": 1050,
        "processed_input": 100, "processed": 150,
    }


# ---------------------------------------------------------------------------
# Live (deselected by default): the same pipeline over the REAL search backend.
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_run_one_live_against_real_search() -> None:
    """Scripted LLMs, REAL ClimbMix search — keeps the retrieval path
    exercisable without model credentials. Needs ``SEARCH_API_KEY`` /
    ``PYSERINI_API_TOKEN`` for the hosted engines."""
    orch_factory = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=ONE_FACET_PLAN))
    analyzer_factory = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=True))
    result = run_one(
        orch_factory, analyzer_factory, qid="live_facet_001", narrative=NARRATIVE,
        engines=ENGINES, run_id="facet_rag.live", run_desc="live end-to-end",
        orchestrator_model_id="mock-orchestrator", analyzer_model_id="mock-analyzer",
        max_chars=800, min_facets=1, max_facets=1, format_llm=True)
    assert result["status"] == "completed"
    assert result["references"]
    output = json.loads(result["paths"]["output"].read_text())
    assert validate_rag_output(output) == []
