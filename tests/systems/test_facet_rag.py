"""End-to-end + unit coverage for ``src/systems/facet_rag``.

This module is the hermetic pytest port of the ad-hoc
``src/systems/facet_rag/test_mock.py`` script. Two things changed in the port,
both deliberate:

1. **Retrieval is stubbed.** The original drove the REAL ClimbMix search
   backend, so it could only pass on a machine with credentials and silently
   downgraded to "SKIPPED" without them. Here ``stub_search_tool`` replaces the
   engine dispatch table, which keeps ``run_search_tool``'s serialization,
   truncation, and error-envelope logic under test while removing the network.
   The live path is preserved as a single ``@pytest.mark.live`` test.
2. **Stage routing is explicit.** The original mock guessed the pipeline stage
   from a fragile ``"SEARCH FACETS" in text or ("facets" in text.lower() and
   ...)`` condition. The three prompts each carry a unique marker
   (``RETRIEVED PASSAGES:`` / ``ALLOWED DOCIDS:``), so the responder here keys
   off those instead — a prompt-wording change now fails loudly rather than
   routing a synthesis turn into the planner branch.

Everything else — the invariants the original checked one ``check()`` at a time
— is asserted below, one test per property.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS, ScriptedProvider, model_turn

from ragrun import validate_rag_output

from facet_rag import execute_facet, execute_plan, parse_facets
from facet_rag.pipeline import _usage_token_stats, run_one
from facet_rag.planner import (
    DEFAULT_K,
    MAX_K,
    MIN_K,
    Facet,
    build_plan_prompt,
    fallback_facets,
)
from facet_rag.search import format_passages_for_synthesis

NARRATIVE = "How effective are influenza vaccines at preventing illness?"
QID = "mock_facet_001"
ENGINES = ["semantic", "keyword"]

# The two facets the scripted planner emits. Pinned to *different* engines so
# the routing assertion has something to prove.
FACET_A = {"name": "effectiveness", "engine": "semantic",
           "query": "influenza vaccine effectiveness", "k": 5}
FACET_B = {"name": "strain match", "engine": "keyword",
           "query": "influenza vaccine strain match season", "k": 5}

_PASSAGE_DOCID_RE = re.compile(r"docid=(\S+)")
_ALLOWED_DOCIDS_RE = re.compile(r"ALLOWED DOCIDS:\s*(\[.*?\])", re.DOTALL)


# ---------------------------------------------------------------------------
# Scripted provider (responder mode: one branch per pipeline stage)
# ---------------------------------------------------------------------------
def _plan_text(facets: list[dict[str, Any]] | None = None) -> str:
    return json.dumps({"facets": facets if facets is not None
                       else [FACET_A, FACET_B]})


def _synthesize_text(pending: str) -> str:
    """Grounded prose citing a docid lifted out of the synthesis prompt.

    Reading the docid back out of the prompt (rather than hard-coding one) is
    what makes the citation guaranteed-valid: the pipeline only accepts
    citations that are in the retrieved allow-list, so the mock has to cite
    whatever retrieval actually returned.
    """
    docids = _PASSAGE_DOCID_RE.findall(pending)
    cite = f"[{docids[0]}]" if docids else ""
    return ("Influenza vaccines reduce the risk of laboratory-confirmed "
            f"influenza illness among vaccinated people {cite}. "
            "Vaccine effectiveness varies by season and by how well the "
            f"vaccine matches circulating strains {cite}.")


def _format_text(pending: str) -> str:
    """Strict ``{"sentences": [...]}`` JSON citing the first allowed docid."""
    match = _ALLOWED_DOCIDS_RE.search(pending)
    docids = json.loads(match.group(1)) if match else []
    cites = docids[:1]
    return json.dumps({"sentences": [
        {"text": "Influenza vaccines reduce the risk of confirmed influenza "
                 "illness.", "citations": cites},
        {"text": "Effectiveness varies by season and strain match.",
         "citations": cites},
    ]})


def make_responder(facets: list[dict[str, Any]] | None = None
                   ) -> Callable[[str, int], dict[str, Any]]:
    """Build a ``ScriptedProvider`` responder that answers all three stages."""
    def _respond(pending: str, turn_index: int) -> dict[str, Any]:
        if "ALLOWED DOCIDS:" in pending:
            return model_turn(text=_format_text(pending))
        if "RETRIEVED PASSAGES:" in pending:
            return model_turn(text=_synthesize_text(pending))
        assert "RESEARCH NARRATIVE:" in pending, (
            f"unrecognised stage prompt at turn {turn_index}: {pending[:120]!r}")
        return model_turn(text=_plan_text(facets))
    return _respond


@pytest.fixture
def pipeline_run(stub_search_tool: dict[str, list[dict[str, Any]]],
                 read_artifacts: Callable[..., dict[str, Any]]
                 ) -> dict[str, Any]:
    """One full hermetic ``run_one`` — the port of ``test_mock.py::main``.

    Returned as a fixture because a dozen assertions below are all about the
    same single run; re-running it per test would only slow the suite down.
    """
    provider = ScriptedProvider(make_responder())
    result = run_one(
        provider, qid=QID, narrative=NARRATIVE,
        engines=ENGINES, default_engine="semantic",
        run_id="facet_rag.mock", run_desc="mock end-to-end test",
        model_id=provider.model_id, backend="mock", max_chars=800,
        min_facets=2, max_facets=4, format_llm=True)
    artifacts = read_artifacts(result["paths"])
    return {"result": result, "provider": provider, "calls": stub_search_tool,
            "trajectory": artifacts["trajectory"], "output": artifacts["output"],
            "violations": artifacts["violations"]}


# ---------------------------------------------------------------------------
# Full pipeline (ported test_mock.py assertions)
# ---------------------------------------------------------------------------
def test_run_one_completes_and_writes_both_artifacts(
        pipeline_run: dict[str, Any]) -> None:
    """A submission-ready run leaves no ``output.violations.json`` behind.

    ``save_run`` writes that third file only when the output breaks the track
    schema, so its absence is the machine-checkable claim that this artifact
    could be exported as-is.
    """
    result, paths = pipeline_run["result"], pipeline_run["result"]["paths"]
    assert result["status"] == "completed"
    assert paths["trajectory"].exists()
    assert paths["output"].exists()
    # save_run only returns a "violations" key when it wrote a violations file.
    assert "violations" not in paths
    assert pipeline_run["violations"] == []


def test_run_one_output_passes_track_validation(
        pipeline_run: dict[str, Any]) -> None:
    """Validate the artifact as re-read from disk, not just in memory.

    ``save_run`` validates the object it was handed; this proves the JSON round
    trip did not change anything the track validator cares about.
    """
    assert validate_rag_output(pipeline_run["output"]) == []


def test_run_one_plans_both_facets(pipeline_run: dict[str, Any]) -> None:
    """The plan the model returned is the plan that got executed, in order.

    Multi-facet coverage is the entire premise of this system: if the planner's
    facets were silently merged or reordered, the run would degrade to ordinary
    single-query RAG while still looking successful.
    """
    facets = pipeline_run["result"]["facets"]
    assert [f.name for f in facets] == [FACET_A["name"], FACET_B["name"]]
    assert [f.engine for f in facets] == [FACET_A["engine"], FACET_B["engine"]]


def test_run_one_one_search_per_facet(pipeline_run: dict[str, Any]) -> None:
    """Retrieval cost is exactly one search per planned facet — no fan-out.

    This is the pipeline's cost model (facet count is the only knob that buys
    more retrieval); a stray extra call per facet doubles the run's backend load
    invisibly.
    """
    counts = pipeline_run["trajectory"]["tool_call_counts"]
    assert counts.get("search") == len(pipeline_run["result"]["facets"]) == 2


def test_run_one_retrieved_docids_and_references_non_empty(
        pipeline_run: dict[str, Any]) -> None:
    """The two fields a grounded run cannot be empty in.

    No ``retrieved_docids`` means retrieval never landed; no ``references``
    means nothing was cited — either way the topic contributes nothing to the
    submission even though the run reports ``completed``.
    """
    assert pipeline_run["trajectory"]["retrieved_docids"]
    assert pipeline_run["result"]["references"]


def test_run_one_strict_item_kind_sequence(pipeline_run: dict[str, Any]) -> None:
    """plan reasoning -> one tool_call per facet -> the synthesis output_text.

    The synthesis LLM turn itself is a rich-only ``generation`` span, so it
    deliberately does NOT appear here.
    """
    kinds = [item["type"] for item in pipeline_run["trajectory"]["result"]]
    assert kinds == ["reasoning", "tool_call", "tool_call", "output_text"]


def test_run_one_tool_call_items_name_facet_and_engine(
        pipeline_run: dict[str, Any]) -> None:
    """Each recorded search must say WHICH facet it served and on which engine.

    Without the ``facet`` annotation the trajectory is an unattributed list of
    queries, and per-facet effectiveness — the thing this system exists to
    measure — cannot be reconstructed from the artifact afterwards.
    """
    items = [i for i in pipeline_run["trajectory"]["result"]
             if i["type"] == "tool_call"]
    assert [i["facet"] for i in items] == [FACET_A["name"], FACET_B["name"]]
    engines = [json.loads(i["arguments"])["search_engine"] for i in items]
    assert engines == [FACET_A["engine"], FACET_B["engine"]]
    assert all(e in ENGINES for e in engines)


def test_run_one_every_reference_is_cited(pipeline_run: dict[str, Any]) -> None:
    """An uncited reference is a spec violation that fails silently.

    The run still completes and the answer still reads fine; only the track
    validator flags it. Multi-facet retrieval makes it especially easy to hit —
    facet B's documents are in the candidate pool whether or not the synthesis
    cited any of them.
    """
    output = pipeline_run["output"]
    cited = {c for s in output["answer"] for c in s["citations"]}
    assert cited == set(range(len(output["references"])))


def test_run_one_trace_lives_only_in_output(
        pipeline_run: dict[str, Any]) -> None:
    """The rich trace is an internal artifact: output.json only, never the
    organizer-facing trajectory."""
    trace = pipeline_run["output"].get("trace", {})
    assert isinstance(trace.get("steps"), list)
    # reasoning + 2 tool_calls + generation + output_text
    assert len(trace["steps"]) >= 4
    assert "trace" not in pipeline_run["trajectory"]


def test_run_one_provider_is_driven_single_shot(
        pipeline_run: dict[str, Any]) -> None:
    """Three tool-less turns (plan, synthesize, format) and no tool results.

    ``facet_rag`` never hands tool results back to the provider — retrieval is
    a pipeline stage, not a model action. The original mock encoded this by
    raising from ``add_tool_results``; asserting the recording is empty says the
    same thing without an exception path.
    """
    provider = pipeline_run["provider"]
    assert provider.turn_index == 3
    assert provider.tool_results == []
    assert provider.tools == []


# ---------------------------------------------------------------------------
# Engine routing
# ---------------------------------------------------------------------------
def test_engine_routing_follows_the_plan(pipeline_run: dict[str, Any]) -> None:
    """A plan pinning facet A to ``semantic`` and B to ``keyword`` must reach
    exactly those two engines, with exactly those queries."""
    calls = pipeline_run["calls"]
    assert set(calls) == {"semantic", "keyword"}
    assert [c["query"] for c in calls["semantic"]] == [FACET_A["query"]]
    assert [c["query"] for c in calls["keyword"]] == [FACET_B["query"]]
    assert calls["semantic"][0]["k"] == FACET_A["k"]


@pytest.mark.parametrize("engine", ["semantic", "keyword"])
def test_single_engine_plan_touches_only_that_engine(
        engine: str, stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """Routing must be driven by the plan, not by a hard-coded default.

    Parametrized over both engines so a regression that pins everything to
    ``semantic`` (the shared tool's own default) cannot pass by coincidence —
    that bug would make every keyword/SSR comparison measure the wrong backend.
    """
    facets = [{**FACET_A, "engine": engine}]
    provider = ScriptedProvider(make_responder(facets))
    run_one(provider, qid=QID, narrative=NARRATIVE, engines=ENGINES,
            default_engine="semantic", run_id="facet_rag.mock",
            run_desc="single-engine routing", model_id=provider.model_id,
            backend="mock", max_chars=800, min_facets=1, max_facets=1,
            format_llm=True)
    assert set(stub_search_tool) == {engine}


# ---------------------------------------------------------------------------
# planner.parse_facets
# ---------------------------------------------------------------------------
def _plan(facets: list[dict[str, Any]]) -> str:
    return json.dumps({"facets": facets})


def test_parse_facets_valid_json() -> None:
    """The baseline contract: a well-formed plan becomes exactly those Facets.

    Everything else in this group is a deviation from this shape, so if this one
    is wrong the tolerance tests below prove nothing.
    """
    facets = parse_facets(_plan([FACET_A, FACET_B]), ENGINES,
                          default_engine="semantic")
    assert facets == [
        Facet(name="effectiveness", engine="semantic",
              query=FACET_A["query"], k=5),
        Facet(name="strain match", engine="keyword", query=FACET_B["query"],
              k=5),
    ]


@pytest.mark.parametrize("wrapper", [
    "```json\n{body}\n```",       # fenced with a language tag
    "```\n{body}\n```",           # bare fence
    "  \n{body}\n  ",             # stray whitespace
])
def test_parse_facets_strips_fences(wrapper: str) -> None:
    """Models wrap JSON in Markdown fences unprompted, so it must be tolerated.

    Each wrapper is a shape seen in practice. Failing any of them costs the run
    its whole plan — the pipeline falls back to a single whole-narrative facet,
    losing the multi-facet coverage this system is for.
    """
    raw = wrapper.format(body=_plan([FACET_A]))
    facets = parse_facets(raw, ENGINES, default_engine="semantic")
    assert [f.query for f in facets] == [FACET_A["query"]]


def test_parse_facets_rejects_json_embedded_in_prose() -> None:
    """CURRENT BEHAVIOUR (documented, not endorsed): only *fenced* or bare JSON
    parses. ``_strip_fences`` is a full-string fence match, and there is no
    "first {...} block" extraction like ``answer_format._from_llm_json`` has, so
    a model that prefixes "Here you go:" yields no facets — and the pipeline
    then falls back to a single whole-narrative facet.

    Asserted so a future change to add prose tolerance is a deliberate, visible
    change rather than an accident.
    """
    raw = f"Here you go:\n{_plan([FACET_A])}\nHope that helps!"
    assert parse_facets(raw, ENGINES, default_engine="semantic") == []


def test_parse_facets_coerces_disabled_engine_to_default() -> None:
    """A facet naming an engine this run did not enable must still run.

    The planner model knows about engines from its prompt but can name one that
    is switched off (``ssr`` here). Coercing to the run's default keeps the facet
    instead of dropping it — and it keeps a single-engine ablation honest, since
    a stray ``semantic`` request cannot leak into a keyword-only run.
    """
    facets = parse_facets(_plan([{**FACET_A, "engine": "ssr"}]),
                          ENGINES, default_engine="keyword")
    assert [f.engine for f in facets] == ["keyword"]


@pytest.mark.parametrize("raw", [
    "not json at all",
    "{",
    "[]",                                    # a list, not the {facets: []} obj
    '{"facets": "not a list"}',
    '{"nope": []}',
    "",
])
def test_parse_facets_malformed_yields_empty_list(raw: str) -> None:
    """The plan comes from an LLM, so malformed JSON is expected traffic.

    Returning ``[]`` (rather than raising) is precisely what lets
    ``fallback_facets`` take over instead of the run dying — each case here is a
    different way the plan can be wrong: not JSON, truncated, right JSON but the
    wrong container, wrong value type, wrong key, nothing at all.
    """
    assert parse_facets(raw, ENGINES, default_engine="semantic") == []


def test_parse_facets_skips_unusable_rows() -> None:
    """Rows with no query (or that are not objects) are dropped, not fatal."""
    facets = parse_facets(_plan([
        {"name": "empty", "engine": "semantic", "query": "   "},
        "a bare string",                                    # type: ignore[list-item]
        {"name": "good", "engine": "semantic", "query": "usable query"},
    ]), ENGINES, default_engine="semantic")
    assert [f.query for f in facets] == ["usable query"]


@pytest.mark.parametrize("given,expected", [
    (999, MAX_K),          # above the ceiling
    (0, MIN_K),            # below the floor
    (-5, MIN_K),
    (7, 7),                # inside the band, untouched
    ("nope", DEFAULT_K),   # unparseable -> the default
    (None, DEFAULT_K),
])
def test_parse_facets_clamps_k(given: Any, expected: int) -> None:
    """``k`` is model-chosen, so it must be bounded before it reaches a backend.

    An unclamped ``k`` is the one plan field that can hurt the *service*: a
    hallucinated ``k=999`` would ask the hosted index for a thousand passages
    per facet, and ``k=0`` would retrieve nothing while still looking like a
    successful search.
    """
    facets = parse_facets(_plan([{"query": "q", "k": given}]), ENGINES,
                          default_engine="semantic")
    assert [f.k for f in facets] == [expected]


def test_parse_facets_names_default_to_the_query_head() -> None:
    """A nameless facet still needs a label, because the label is in the artifact.

    ``facet`` is stamped on every trajectory tool_call item; an empty name would
    make those records unattributable. The 40-char cap keeps a whole narrative
    from becoming the "name".
    """
    long_query = "a" * 60
    facets = parse_facets(_plan([{"query": long_query}]), ENGINES,
                          default_engine="semantic")
    assert facets[0].name == long_query[:40]


def test_parse_facets_does_not_clamp_facet_count() -> None:
    """FINDING: ``min_facets``/``max_facets`` are *prompt* parameters only.

    ``build_plan_prompt`` renders them into the instructions, but
    ``parse_facets`` has no count clamp — a model that returns 9 facets when
    asked for 2-4 gets 9 searches. Asserted as current behaviour; reported so
    the caller can decide whether a clamp belongs in the parser.
    """
    rows = [{"query": f"query {i}", "engine": "semantic"} for i in range(9)]
    assert len(parse_facets(_plan(rows), ENGINES,
                            default_engine="semantic")) == 9


def test_fallback_facets_covers_the_whole_narrative() -> None:
    """The safety net must degrade to plain RAG, not to no retrieval.

    Whenever planning fails this is the entire plan, so it has to query the FULL
    narrative (trimmed) on the run's own engine — a fallback that retrieved
    nothing would turn a planning hiccup into an ungrounded answer.
    """
    facets = fallback_facets(f"  {NARRATIVE}  ", default_engine="keyword")
    assert facets == [Facet(name="whole narrative", engine="keyword",
                            query=NARRATIVE, k=DEFAULT_K)]


def test_unparseable_plan_falls_back_in_the_pipeline(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A garbage plan must still retrieve something (via ``fallback_facets``)."""
    def _respond(pending: str, turn_index: int) -> dict[str, Any]:
        if "ALLOWED DOCIDS:" in pending:
            return model_turn(text=_format_text(pending))
        if "RETRIEVED PASSAGES:" in pending:
            return model_turn(text=_synthesize_text(pending))
        return model_turn(text="I could not produce a plan, sorry.")

    provider = ScriptedProvider(_respond)
    result = run_one(provider, qid=QID, narrative=NARRATIVE, engines=ENGINES,
                     default_engine="keyword", run_id="facet_rag.mock",
                     run_desc="fallback plan", model_id=provider.model_id,
                     backend="mock", max_chars=800, min_facets=2, max_facets=4,
                     format_llm=True)
    assert [f.name for f in result["facets"]] == ["whole narrative"]
    # The fallback facet is pinned to default_engine and queries the narrative.
    assert list(stub_search_tool) == ["keyword"]
    assert stub_search_tool["keyword"][0]["query"] == NARRATIVE
    assert result["status"] == "completed"


def test_build_plan_prompt_renders_engine_blurbs_and_bounds() -> None:
    """The prompt is the only place engine choice is explained to the planner.

    Two failure modes it guards: a disabled engine that is still advertised (the
    model plans facets that then get silently coerced), and blurbs drifting from
    ``tools.search_tool.ENGINE_INFO`` — which is the single source of truth, so
    the model's idea of "keyword" must come from there and not a copy.
    """
    prompt = build_plan_prompt(NARRATIVE, ENGINES, min_facets=2, max_facets=4)
    assert "2-4 facets" in prompt
    assert NARRATIVE in prompt
    # Blurbs come from tools.search_tool.ENGINE_INFO (single source of truth).
    assert "- semantic: semantic (dense embedding match)" in prompt
    assert "- keyword: keyword (hosted BM25" in prompt
    # A disabled engine must not be advertised.
    assert "- ssr:" not in prompt


# ---------------------------------------------------------------------------
# search.execute_plan / execute_facet
# ---------------------------------------------------------------------------
def test_execute_plan_dedups_by_docid_first_facet_wins(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """The stub returns the same docid list to every engine, so a narrow first
    facet followed by a wider second one exercises both halves of the dedup:
    overlapping ids keep the FIRST facet's provenance, new ids are appended."""
    first = Facet(name="narrow", engine="semantic", query="q1", k=2)
    second = Facet(name="wide", engine="keyword", query="q2", k=4)
    retrieval = execute_plan([first, second])

    assert retrieval.docids == list(CLIMBMIX_DOCIDS[:4])
    provenance = [p["facet"] for p in retrieval.passages]
    assert provenance == ["narrow", "narrow", "wide", "wide"]
    # Per-facet results keep their own unfiltered view (2 and 4 passages).
    assert [len(fr.passages) for fr in retrieval.per_facet] == [2, 4]
    assert all(not fr.failed for fr in retrieval.per_facet)


def test_execute_facet_records_unknown_engine_as_failure(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """``run_search_tool`` returns an ``{"error": ...}`` envelope rather than
    raising, and ``execute_facet`` turns that into ``failed=True``."""
    result = execute_facet(Facet(name="bad", engine="nonexistent", query="q"))
    assert result.failed is True
    assert result.passages == []
    assert "unknown search_engine" in (result.error or "")
    assert json.loads(result.output)["error"] == result.error


def test_execute_plan_continues_past_a_failing_facet(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """A backend exception on one facet is recorded, not propagated — the other
    facets still run and their passages still reach synthesis."""
    from tools import search_tool

    def _boom(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        raise RuntimeError("index unavailable")

    monkeypatch.setitem(search_tool._DISPATCH, "keyword", _boom)

    good = Facet(name="good", engine="semantic", query="q1", k=2)
    bad = Facet(name="bad", engine="keyword", query="q2", k=2)
    retrieval = execute_plan([bad, good])   # failing facet FIRST

    assert [fr.failed for fr in retrieval.per_facet] == [True, False]
    assert retrieval.per_facet[0].error == "RuntimeError: index unavailable"
    assert retrieval.docids == list(CLIMBMIX_DOCIDS[:2])


def test_failed_facet_marks_the_trajectory_item(
        monkeypatch: pytest.MonkeyPatch,
        stub_search_tool: dict[str, list[dict[str, Any]]],
        read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """End-to-end: one dead engine must not abort the run, and the failed call
    is excluded from ``tool_call_counts`` while still counted in ``_all``."""
    from tools import search_tool

    def _boom(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        raise RuntimeError("index unavailable")

    monkeypatch.setitem(search_tool._DISPATCH, "keyword", _boom)

    provider = ScriptedProvider(make_responder())
    result = run_one(provider, qid=QID, narrative=NARRATIVE, engines=ENGINES,
                     default_engine="semantic", run_id="facet_rag.mock",
                     run_desc="one dead engine", model_id=provider.model_id,
                     backend="mock", max_chars=800, min_facets=2, max_facets=4,
                     format_llm=True)
    trajectory = read_artifacts(result["paths"])["trajectory"]
    assert result["status"] == "completed"
    assert trajectory["tool_call_counts"] == {"search": 1}
    assert trajectory["tool_call_counts_all"] == {"search": 2}
    assert trajectory["retrieved_docids"]


def test_execute_facet_passes_max_chars_through(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """``max_chars`` truncates in ``run_search_tool``, so the passage text the
    synthesis stage sees is bounded."""
    long_facet = Facet(name="f", engine="semantic", query="q", k=1)
    result = execute_facet(long_facet, max_chars=10)
    assert len(result.passages[0]["text"]) <= 10


# ---------------------------------------------------------------------------
# search.format_passages_for_synthesis
# ---------------------------------------------------------------------------
def test_format_passages_for_synthesis_empty() -> None:
    """Zero passages must render as an explicit marker, not an empty prompt.

    Every facet can fail (dead engine, empty result set); handing the synthesis
    model a blank evidence section invites it to answer from prior knowledge,
    which is exactly the ungrounded output the track penalises.
    """
    assert format_passages_for_synthesis([]) == "(no passages retrieved)"


def test_format_passages_for_synthesis_numbered_docid_blocks() -> None:
    """The rendered block is the model's ONLY source of citable docids.

    The synthesis prompt asks for ``docid=`` citations, so this format and the
    regex that reads them back are two halves of one contract — a spacing change
    here silently strands every citation.
    """
    passages = [{"docid": "shard_1_1", "text": "first"},
                {"docid": "shard_2_2", "text": "second"}]
    rendered = format_passages_for_synthesis(passages)
    assert rendered == ("[1] docid=shard_1_1\nfirst\n\n"
                        "[2] docid=shard_2_2\nsecond")
    # The synthesis prompt's docid regex must be able to find every docid.
    assert _PASSAGE_DOCID_RE.findall(rendered) == ["shard_1_1", "shard_2_2"]


# ---------------------------------------------------------------------------
# pipeline._usage_token_stats
# ---------------------------------------------------------------------------
def test_usage_token_stats_returns_none_for_empty_usage() -> None:
    """facet_rag skips the token block entirely when a provider reports nothing
    (unlike ``aus_agent._usage_token_stats``, which returns a zeroed dict)."""
    assert _usage_token_stats({}) is None


@pytest.mark.parametrize("usage", [
    {"inputTokens": 100, "outputTokens": 50,
     "cacheReadInputTokens": 900, "cacheWriteInputTokens": 0},
    {"input_tokens": 100, "output_tokens": 50,
     "cache_read_input_tokens": 900, "cache_write_input_tokens": 0},
])
def test_usage_token_stats_normalizes_both_key_shapes(
        usage: dict[str, Any]) -> None:
    """Bedrock camelCase and OpenAI snake_case must reduce to identical numbers.

    Run cost is compared across backends from this block, and the two SDKs
    disagree on more than spelling: ``input`` here is the LOGICAL context
    (uncached + cache reads), while ``processed`` is the billed prefill that
    excludes cache reads. Conflating them would report a cache hit as a fresh
    900-token prefill.
    """
    assert _usage_token_stats(usage) == {
        "input": 1000, "input_uncached": 100, "output": 50,
        "cache_read": 900, "cache_write": 0, "total": 1050,
        "processed_input": 100, "processed": 150,
    }


# ---------------------------------------------------------------------------
# Live (deselected by default): the same pipeline over the REAL search backend.
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_run_one_live_against_real_search() -> None:
    """The original ``test_mock.py`` shape: scripted LLM, REAL ClimbMix search.

    Keeps the retrieval path exercisable without model credentials. Needs
    ``SEARCH_API_KEY`` / ``PYSERINI_API_TOKEN`` for the hosted engines.
    """
    provider = ScriptedProvider(make_responder())
    result = run_one(
        provider, qid="live_facet_001", narrative=NARRATIVE, engines=ENGINES,
        default_engine="semantic", run_id="facet_rag.live",
        run_desc="live end-to-end test", model_id=provider.model_id,
        backend="mock", max_chars=800, min_facets=2, max_facets=4,
        format_llm=True)

    failures = [fr.error for fr in result["retrieval"].per_facet if fr.failed]
    assert not failures, f"live search failed: {failures}"
    assert result["status"] == "completed"
    assert result["references"]
    output = json.loads(result["paths"]["output"].read_text())
    assert validate_rag_output(output) == []
