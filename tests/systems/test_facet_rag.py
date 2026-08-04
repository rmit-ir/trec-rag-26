"""End-to-end + unit coverage for ``src/systems/facet_rag``'s orchestrator/
analyzer architecture.

Two roles, two ``ScriptedProvider`` factories: ORCHESTRATOR (plans facets,
writes queries every loop iteration, drafts the final report) and ANALYZER
(judges retrieved passages per facet, reports coverage gaps, fact-checks the
draft). Each factory hands out a FRESH ``ScriptedProvider`` instance per call
— a ``Provider`` owns its own conversation, and ``run_one`` constructs many
of them (one per facet's orchestrator, one per facet's analyzer, plus plan/
draft/fact-check/format calls). Responders route by the prompt's unique
marker text (``FACET:``, ``COVERAGE GAP TO ADDRESS:``, ``EVIDENCE:``, etc.,
one per prompt template in ``prompts.py``) rather than by call order, which
stays correct under ``run_one``'s concurrent per-facet execution.

The orchestrator is one-shot per iteration, not native tool-calling: it
writes a query per mandatory engine (semantic/keyword/hybrid) as structured
JSON, and ``loop.py`` executes every one unconditionally — there is no
"declines to search" path to test anymore (see ``loop.py``'s module
docstring for why: gpt-oss-120b never batched more than one tool call per
turn regardless of prompt wording, checked against real runs).

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
from facet_rag.loop import Analysis, QueryPlan, parse_analysis, parse_query_plan, usage_token_stats
from facet_rag.pipeline import _sandwich_order
from facet_rag.planner import (
    DEFAULT_MAX_ITERATIONS,
    GLOBAL_ITERATION_CAP,
    Facet,
    build_plan_prompt,
    fallback_facets,
)

NARRATIVE = "How effective are influenza vaccines at preventing illness?"
QID = "mock_facet_001"
# All three mandatory engines enabled -- stub_search_tool stubs every entry in
# tools.search_tool._DISPATCH generically (including hybrid's own dense/sparse
# calls via utils.search), so hybrid is exercisable with zero extra fixture work.
ENGINES = ["semantic", "keyword", "hybrid"]
MANDATORY_ENGINES = ("semantic", "keyword", "hybrid")

_DOCID_RE = re.compile(r"\[docid=(\S+?)\]")
_EVIDENCE_DOCID_RE = re.compile(r"docid=(\S+)")
_ALLOWED_DOCIDS_RE = re.compile(r"ALLOWED DOCIDS:\s*(\[.*?\])", re.DOTALL)


# ---------------------------------------------------------------------------
# Scripted responders — route by each prompt's unique marker text
# ---------------------------------------------------------------------------
def _query_plan_text(*, suffix: str = "", boolean_engine: str | None = None,
                     boolean_query: str | None = None) -> str:
    """A valid orchestrator query-plan JSON: one distinct query per mandatory
    engine (semantic/keyword/hybrid), optionally plus a Boolean one."""
    return json.dumps({
        "queries": {e: f"{e} query{suffix}" for e in MANDATORY_ENGINES},
        "boolean_engine": boolean_engine, "boolean_query": boolean_query,
    })


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
        *, facets: list[dict[str, Any]]
        ) -> Callable[[str, int], dict[str, Any]]:
    """Plans, writes a fresh 3-engine query plan every loop iteration
    (including gap follow-ups -- there's no "decline to search" path
    anymore), drafts, and formats."""
    def _respond(pending: str, turn_index: int) -> dict[str, Any]:
        if "ALLOWED DOCIDS:" in pending:
            return model_turn(text=_format_text(pending))
        if "FACET:" in pending:
            return model_turn(text=_query_plan_text(suffix=f"_{turn_index}"))
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


def test_run_one_three_searches_per_facet_when_satisfied_first_round(
        pipeline_run: dict[str, Any]) -> None:
    """The analyzer reports satisfied on the first pass, so each facet's loop
    does exactly one round — but a round is the 3-engine mandatory minimum
    (semantic/keyword/hybrid), not a single search, so 2 facets means 6."""
    counts = pipeline_run["trajectory"]["tool_call_counts"]
    facets = len(pipeline_run["result"]["facets"])
    assert counts.get("search") == facets * len(MANDATORY_ENGINES) == 6


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
    assert kinds.count("tool_call") == 2 * len(MANDATORY_ENGINES)


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
            return model_turn(text=_query_plan_text(suffix=f"_{turn_index}"))
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


def test_loop_falls_back_to_facet_description_when_plan_unparseable(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """The orchestrator's per-iteration query plan is one-shot JSON, not
    native tool-calling, so there's no "declines to search" turn anymore —
    but its JSON can still fail to parse. A round must never be skipped: an
    unparseable plan falls back to searching the facet description on the
    run's first enabled engine."""
    def _orch(pending: str, turn_index: int) -> dict[str, Any]:
        return model_turn(text="I have no idea what to search for.")

    facet = Facet(name="effectiveness", description="How effective?",
                  max_iterations=5)
    orch = lambda: ScriptedProvider(_orch)  # noqa: E731
    analyzer = lambda: ScriptedProvider(  # noqa: E731
        make_analyzer_responder(satisfied=True))
    result = run_facet_loop(make_orchestrator=orch, make_analyzer=analyzer,
                            facet=facet, engines=ENGINES, max_chars=800)
    assert result.stop_reason == "analyzer_satisfied"
    assert result.iterations_used == 1
    assert len(result.evidence) == 1
    assert stub_search_tool["semantic"][0]["query"] == facet.description


def test_loop_gap_is_fed_back_to_the_orchestrator(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A coverage gap from the analyzer must reach the orchestrator's NEXT
    prompt verbatim — otherwise "search again to fill the gap" has no effect.

    Uses a single pre-built ``ScriptedProvider`` instance (rather than a
    factory) so its recorded ``user_messages`` can be inspected directly
    after the loop finishes — safe here because ``run_facet_loop`` only ever
    calls ``make_orchestrator`` once per facet. The stub returns identical
    docids regardless of query, so iteration 2 never sees anything NEW and
    the analyzer only runs once (iteration 1) -- the 2-iteration cap is what
    ends the loop, but the gap still has to reach iteration 2's prompt
    independently of whether that round finds anything.
    """
    facet = Facet(name="effectiveness", description="How effective?",
                  max_iterations=2)
    orchestrator = ScriptedProvider(
        make_orchestrator_responder(facets=ONE_FACET_PLAN))
    analyzer_factory = lambda: ScriptedProvider([  # noqa: E731
        model_turn(text=json.dumps({"relevant": [], "gap": "need strain-match data",
                                    "satisfied": False}))])
    result = run_facet_loop(make_orchestrator=lambda: orchestrator,
                            make_analyzer=analyzer_factory, facet=facet,
                            engines=ENGINES, max_chars=800)
    assert result.stop_reason == "max_iterations"
    assert result.iterations_used == 2
    assert "COVERAGE GAP TO ADDRESS: need strain-match data" in orchestrator.user_messages[1]


def test_loop_caps_iterations_at_ten_regardless_of_facet_value(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """The spec's hard ceiling: a facet claiming ``max_iterations=99`` must
    still stop at 10 — the planner's number is a request, not a grant."""
    facet = Facet(name="stubborn", description="Never satisfied", max_iterations=99)
    orch = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=ONE_FACET_PLAN))
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
    # Every iteration re-issues the mandatory-engine queries regardless of
    # gap content (there's no "decline" path), so iteration 2 searches again
    # -- the stub returns the SAME docids regardless of query, so nothing is
    # NEW and the facet's 2-iteration cap is what ends the loop.
    orch = lambda: ScriptedProvider(  # noqa: E731
        make_orchestrator_responder(facets=ONE_FACET_PLAN))
    analyzer = lambda: ScriptedProvider([  # noqa: E731
        model_turn(text=json.dumps({
            "relevant": [{"docid": CLIMBMIX_DOCIDS[0], "note": "supports it"}],
            "gap": None, "satisfied": False}))])
    result = run_facet_loop(make_orchestrator=orch, make_analyzer=analyzer,
                            facet=facet, engines=ENGINES, max_chars=800)
    # Iteration 1: search returns docids, analyzer keeps one, not satisfied.
    # Iteration 2: orchestrator searches again -> nothing NEW -> no second
    # analyzer call; the facet's 2-iteration cap is what ends the loop.
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
# loop.parse_query_plan
# ---------------------------------------------------------------------------
def test_parse_query_plan_valid_json() -> None:
    """The baseline contract: all three mandatory-engine queries plus a
    Boolean one, all kept as-is."""
    raw = json.dumps({
        "queries": {"semantic": "sem q", "keyword": "kw q", "hybrid": "hyb q"},
        "boolean_engine": "ssr", "boolean_query": '(^ a b)'})
    assert parse_query_plan(raw) == QueryPlan(
        queries={"semantic": "sem q", "keyword": "kw q", "hybrid": "hyb q"},
        boolean_engine="ssr", boolean_query="(^ a b)")


def test_parse_query_plan_drops_empty_or_missing_engine_queries() -> None:
    """A model that skips or blanks one engine's query must not crash the
    round — the loop just searches whichever engines it DID get a query for."""
    raw = json.dumps({"queries": {"semantic": "sem q", "keyword": "   "},
                      "boolean_engine": None, "boolean_query": None})
    plan = parse_query_plan(raw)
    assert plan.queries == {"semantic": "sem q"}


def test_parse_query_plan_rejects_unknown_boolean_engine() -> None:
    """``boolean_engine`` must be one of the actual Boolean engines — a
    hallucinated value (e.g. "semantic" again, or a typo) is dropped along
    with its query rather than routed to the wrong backend."""
    raw = json.dumps({"queries": {"semantic": "q"},
                      "boolean_engine": "semantic", "boolean_query": "q2"})
    plan = parse_query_plan(raw)
    assert plan.boolean_engine is None
    assert plan.boolean_query is None


def test_parse_query_plan_requires_both_boolean_fields_or_neither() -> None:
    """A ``boolean_engine`` with no matching query (or vice versa) is half a
    plan -- dropped entirely rather than searched with an empty string."""
    raw = json.dumps({"queries": {}, "boolean_engine": "ssr", "boolean_query": None})
    plan = parse_query_plan(raw)
    assert plan.boolean_engine is None
    assert plan.boolean_query is None


def test_parse_query_plan_malformed_yields_empty_plan() -> None:
    """Unparseable output yields an all-empty plan, letting the loop's own
    "never skip a round" fallback (search the facet description) take over."""
    assert parse_query_plan("not json at all") == QueryPlan(
        queries={}, boolean_engine=None, boolean_query=None)


def test_parse_query_plan_strips_fences() -> None:
    """Models wrap JSON in Markdown fences unprompted, so it must be tolerated."""
    raw = "```json\n" + json.dumps({"queries": {"semantic": "q"},
                                    "boolean_engine": None,
                                    "boolean_query": None}) + "\n```"
    assert parse_query_plan(raw).queries == {"semantic": "q"}


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
# pipeline._sandwich_order
# ---------------------------------------------------------------------------
def test_sandwich_order_puts_best_rank_first_and_second_best_last() -> None:
    """The lost-in-the-middle mitigation: strongest evidence (lowest rank) at
    both edges of the block, weakest in the middle -- not just sorted best-
    to-worst, which would bury the 2nd/3rd-best items past where models
    reliably attend."""
    evidence = [
        {"docid": "d3", "rank": 3}, {"docid": "d1", "rank": 1},
        {"docid": "d4", "rank": 4}, {"docid": "d2", "rank": 2},
    ]
    ordered = [e["docid"] for e in _sandwich_order(evidence)]
    assert ordered == ["d1", "d3", "d4", "d2"]


def test_sandwich_order_missing_rank_sorts_last() -> None:
    """A defensive fallback: an evidence item with no rank (shouldn't happen
    in practice) must not crash comparison against ranked items, and must not
    be treated as the best (rank 1) by accident."""
    evidence = [{"docid": "no_rank", "rank": None}, {"docid": "d1", "rank": 1}]
    ordered = [e["docid"] for e in _sandwich_order(evidence)]
    assert ordered[0] == "d1"


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
