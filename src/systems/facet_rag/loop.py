"""Per-facet orchestrator/analyzer/curator search loop.

Three models/roles, driven from Python (no single one owns the stop
condition alone):

- The ORCHESTRATOR (e.g. gpt-oss-120b) is a fresh one-shot call every
  iteration: it writes one query per mandatory engine (semantic/keyword/
  hybrid) plus an optional Boolean-engine query, as structured JSON
  (``ORCHESTRATOR_QUERY_PROMPT``). NOT native tool-calling: gpt-oss-120b via
  Bedrock Converse never batched more than one ``search`` tool call per turn
  regardless of how directively the system prompt asked for it (checked
  empirically against real runs), so the code executes every query in the
  parsed plan unconditionally instead of trusting the model's tool-call
  choices.
- The ANALYZER (e.g. Qwen) is also a fresh one-shot call every iteration: it
  reads the newly retrieved passages against the facet's need, keeps what's
  relevant with a supporting note, and reports a coverage gap or
  ``satisfied``.
- The CURATOR (``curator.py``, same model as the analyzer) runs whenever the
  evidence pool changed: it ranks the facet's FULL accumulated evidence
  (every round so far, not just the newest) by relevance AND diversity,
  sinking near-duplicates below whichever higher-ranked item already covers
  the same point. It is the loop's authoritative coverage gate — a facet
  only stops once the curator agrees its top-N ranked, de-duplicated items
  adequately cover the facet, not just when the analyzer likes the latest
  round. Its top-N becomes the facet's actual contribution to synthesis
  (``FacetLoopResult.evidence``), not the analyzer's raw, unfiltered keeps —
  see ``curator.py`` for why the analyzer alone under-filters.

The loop stops on whichever comes first: the curator says ``covered``, or
the facet's iteration budget (clamped to ``planner.GLOBAL_ITERATION_CAP``)
runs out. There is no "orchestrator declines to search" stop path — every
iteration mandates at least the enabled mandatory-engine queries, with a
description-only fallback if the orchestrator's JSON is unusable, so a round
is never skipped.

Trace events are buffered per facet (``FacetLoopResult.events``) rather than
written straight to a shared ``TrajectoryBuilder`` — facets run concurrently
in their own threads (see ``pipeline.py``), and the builder is not
thread-safe. The caller replays events into the builder sequentially once
every facet has finished.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from tools.search_tool import run_search_tool

from .curator import curate
from .llm import one_shot, strip_fences, usage_token_stats
from .planner import Facet, GLOBAL_ITERATION_CAP
from .prompts import ANALYZER_PROMPT, ORCHESTRATOR_QUERY_PROMPT

__all__ = [
    "Analysis", "FacetLoopResult", "LoopEvent", "QueryPlan",
    "one_shot", "usage_token_stats",  # re-exported: pipeline.py imports these from here
    "parse_analysis", "parse_query_plan", "run_facet_loop",
]

# The three engines every iteration must query (whichever of these the run
# actually enables) -- the rest (ssr/lucene_bool) are the orchestrator's
# optional Boolean-precision add-on. See prompts.ORCHESTRATOR_QUERY_PROMPT.
MANDATORY_ENGINES = ("semantic", "keyword", "hybrid")
BOOLEAN_ENGINES = ("ssr", "lucene_bool")
DEFAULT_K = 10


@dataclass
class QueryPlan:
    queries: dict[str, str]          # engine -> query, only non-empty ones
    boolean_engine: str | None
    boolean_query: str | None


def parse_query_plan(raw: str) -> QueryPlan:
    """Parse the orchestrator's per-iteration query JSON.

    Unparseable/empty output yields an all-empty plan; the caller falls back
    to searching the facet description on the run's first enabled engine so
    an iteration is never wasted.
    """
    try:
        payload = json.loads(strip_fences(raw))
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return QueryPlan(queries={}, boolean_engine=None, boolean_query=None)

    queries: dict[str, str] = {}
    raw_queries = payload.get("queries")
    if isinstance(raw_queries, dict):
        for engine in MANDATORY_ENGINES:
            q = raw_queries.get(engine)
            if isinstance(q, str) and q.strip():
                queries[engine] = q.strip()

    boolean_engine = payload.get("boolean_engine")
    boolean_engine = boolean_engine if boolean_engine in BOOLEAN_ENGINES else None
    boolean_query = payload.get("boolean_query")
    boolean_query = (boolean_query.strip()
                     if isinstance(boolean_query, str) and boolean_query.strip()
                     else None)
    if not (boolean_engine and boolean_query):  # need both or neither
        boolean_engine = boolean_query = None
    return QueryPlan(queries=queries, boolean_engine=boolean_engine,
                     boolean_query=boolean_query)


@dataclass
class Analysis:
    relevant: list[dict[str, str]]   # [{"docid", "note"}]
    gap: str | None
    satisfied: bool


def parse_analysis(raw: str, valid_docids: set[str]) -> Analysis:
    """Parse the analyzer JSON, dropping anything not in ``valid_docids``.

    Unparseable output is treated as "nothing kept, no gap, satisfied" so the
    loop stops rather than spinning on a facet whose analyzer keeps failing to
    answer in the expected shape.
    """
    try:
        payload = json.loads(strip_fences(raw))
    except json.JSONDecodeError:
        return Analysis(relevant=[], gap=None, satisfied=True)
    if not isinstance(payload, dict):
        return Analysis(relevant=[], gap=None, satisfied=True)

    relevant = []
    for row in payload.get("relevant") or []:
        if not isinstance(row, dict):
            continue
        docid = str(row.get("docid", "")).strip()
        if docid not in valid_docids:
            continue
        note = str(row.get("note", "")).strip()
        relevant.append({"docid": docid, "note": note})

    gap = payload.get("gap")
    gap = str(gap).strip() if isinstance(gap, str) and gap.strip() else None
    satisfied = bool(payload.get("satisfied", False))
    return Analysis(relevant=relevant, gap=gap, satisfied=satisfied)


@dataclass
class LoopEvent:
    """One replayable trace event — an orchestrator round, an analysis call,
    or a curator ranking pass."""
    kind: str  # "oss_turn" | "qwen_analysis" | "curator"
    oss_text: str | None = None
    oss_stats: dict[str, int] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    qwen_stats: dict[str, int] | None = None
    gap: str | None = None
    satisfied: bool = False
    relevant_count: int = 0


@dataclass
class FacetLoopResult:
    facet: Facet
    evidence: list[dict[str, Any]]   # curator's top-N: [{"docid","note","text","rank"}]
    events: list[LoopEvent]
    iterations_used: int
    stop_reason: str  # "curator_covered" | "max_iterations"


def _render_passages(passages: list[dict[str, Any]]) -> str:
    if not passages:
        return "(no passages)"
    return "\n\n".join(f"[docid={p['docid']}]\n{p['text']}" for p in passages)


def _render_evidence(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(none yet)"
    return "\n".join(f"- [{e['docid']}] {e['note']}" for e in evidence)


def run_facet_loop(*, make_orchestrator: Any, make_analyzer: Any,
                   narrative: str, facet: Facet, engines: list[str],
                   max_chars: int) -> FacetLoopResult:
    """Run one facet's orchestrator/analyzer/curator search-analyze-gap loop.

    ``make_orchestrator``/``make_analyzer`` are zero-arg factories returning a
    fresh ``Provider`` each call — required because a ``Provider`` owns its
    own conversation state and facets run concurrently in their own threads.
    The curator reuses ``make_analyzer`` for its own, separate provider
    instance (same model, independent conversation).
    """
    from tools.search_tool import ENGINE_INFO  # local: avoid a hard
    # import-time dependency on tools.search_tool internals elsewhere.

    orchestrator = make_orchestrator()
    analyzer = make_analyzer()
    curator_provider = make_analyzer()

    mandatory = [e for e in MANDATORY_ENGINES if e in engines]
    boolean_available = [e for e in BOOLEAN_ENGINES if e in engines]
    boolean_blurbs = ("\n".join(f"- {e}: {ENGINE_INFO[e]['blurb']}"
                                for e in boolean_available)
                      if boolean_available
                      else "(no Boolean engine is enabled for this run)")

    def blurb(engine: str) -> str:
        return ENGINE_INFO[engine]["blurb"] if engine in ENGINE_INFO else engine

    cap = min(max(1, facet.max_iterations), GLOBAL_ITERATION_CAP)
    evidence: list[dict[str, Any]] = []
    curated_top: list[dict[str, Any]] = []
    seen_docids: set[str] = set()
    events: list[LoopEvent] = []
    stop_reason = "max_iterations"
    iterations_used = 0
    gap: str | None = None
    tried_queries: list[str] = []

    for _ in range(cap):
        iterations_used += 1
        context_block = ""
        if gap:
            tried = "; ".join(tried_queries[-6:]) or "(none)"
            context_block = (f"\nCOVERAGE GAP TO ADDRESS: {gap}\n"
                             f"QUERIES ALREADY TRIED (write different ones): "
                             f"{tried}\n")
        prompt = ORCHESTRATOR_QUERY_PROMPT.format(
            facet_name=facet.name, facet_description=facet.description,
            context_block=context_block, semantic_blurb=blurb("semantic"),
            keyword_blurb=blurb("keyword"), hybrid_blurb=blurb("hybrid"),
            boolean_blurbs=boolean_blurbs)
        raw = one_shot(orchestrator, "", prompt)
        oss_stats = usage_token_stats(getattr(orchestrator, "_last_usage", {}))
        plan = parse_query_plan(raw)

        calls = [(engine, plan.queries[engine]) for engine in mandatory
                if engine in plan.queries]
        if plan.boolean_engine and plan.boolean_engine in engines:
            calls.append((plan.boolean_engine, plan.boolean_query))
        if not calls:
            # Totally unparseable/empty plan -- never skip a round.
            calls = [(engines[0], facet.description)]

        ev = LoopEvent(kind="oss_turn", oss_text=raw, oss_stats=oss_stats)
        events.append(ev)

        new_passages: list[dict[str, Any]] = []
        for engine, query in calls:
            output = run_search_tool(query=query, k=DEFAULT_K,
                                     max_chars=max_chars, search_engine=engine)
            data = json.loads(output)
            failed = "error" in data
            results = [] if failed else data.get("results", [])
            ev.tool_calls.append({
                "arguments": {"query": query, "search_engine": engine,
                             "k": DEFAULT_K},
                "output": output,
                "returned_docids": [str(r["docid"]) for r in results],
                "failed": failed,
            })
            tried_queries.append(query)
            for r in results:
                docid = str(r["docid"])
                if docid in seen_docids:
                    continue
                seen_docids.add(docid)
                new_passages.append({"docid": docid, "text": r.get("text") or "",
                                     "rank": r.get("rank")})

        if not new_passages:
            gap = ("The last round of searches returned no new passages. "
                  "Write different, more specific queries.")
            events.append(LoopEvent(kind="qwen_analysis", satisfied=False,
                                    gap=gap, relevant_count=0))
            continue

        analysis_prompt = ANALYZER_PROMPT.format(
            facet_name=facet.name, facet_description=facet.description,
            evidence_so_far=_render_evidence(evidence),
            passages=_render_passages(new_passages))
        raw2 = one_shot(analyzer, "", analysis_prompt)
        qstats = usage_token_stats(getattr(analyzer, "_last_usage", {}))
        analysis = parse_analysis(
            raw2, valid_docids={p["docid"] for p in new_passages})
        events.append(LoopEvent(
            kind="qwen_analysis", qwen_stats=qstats,
            gap=analysis.gap, satisfied=analysis.satisfied,
            relevant_count=len(analysis.relevant)))

        passage_by_docid = {p["docid"]: p for p in new_passages}
        for item in analysis.relevant:
            passage = passage_by_docid.get(item["docid"], {})
            evidence.append({"docid": item["docid"], "note": item["note"],
                            "text": passage.get("text", "")})

        # Curator: rank the FULL accumulated pool (not just this round) by
        # relevance + diversity, sinking near-duplicates. Its top-N is what
        # ultimately reaches synthesis, and its `covered` verdict -- not the
        # analyzer's per-round `satisfied` -- is what stops the loop.
        curation, curator_stats = curate(curator_provider, narrative=narrative,
                                         facet=facet, evidence=evidence)
        events.append(LoopEvent(
            kind="curator", qwen_stats=curator_stats, gap=curation.gap,
            satisfied=curation.covered, relevant_count=len(curation.top)))
        curated_top = [{"docid": item.docid, "note": item.note,
                        "text": item.text, "rank": rank}
                       for rank, item in enumerate(curation.top, 1)]

        if curation.covered:
            stop_reason = "curator_covered"
            break
        gap = curation.gap or analysis.gap or "more evidence needed"

    return FacetLoopResult(facet=facet, evidence=curated_top, events=events,
                           iterations_used=iterations_used,
                           stop_reason=stop_reason)
