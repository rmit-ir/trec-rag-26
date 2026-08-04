"""Per-facet orchestrator/analyzer search loop.

Two models, two roles, driven from Python (neither model owns the stop
condition alone):

- The ORCHESTRATOR (e.g. gpt-oss-120b) gets a native Bedrock tool-use
  conversation with the shared ``search`` tool (``tools.search_tool``) and
  decides which engine(s) to query.
- The ANALYZER (e.g. Qwen) is a fresh one-shot call every iteration: it reads
  the newly retrieved passages against the facet's need, keeps what's
  relevant with a supporting note, and reports a coverage gap or
  ``satisfied``.

The loop stops on whichever comes first: the analyzer says ``satisfied``, the
orchestrator issues no search (nothing more to try), or the facet's
iteration budget (clamped to ``planner.GLOBAL_ITERATION_CAP``) runs out.

Trace events are buffered per facet (``FacetLoopResult.events``) rather than
written straight to a shared ``TrajectoryBuilder`` — facets run concurrently
in their own threads (see ``pipeline.py``), and the builder is not
thread-safe. The caller replays events into the builder sequentially once
every facet has finished.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from tools.search_tool import build_search_tool, run_search_tool

from .planner import Facet, GLOBAL_ITERATION_CAP
from .prompts import (
    ANALYZER_PROMPT,
    ORCHESTRATOR_GAP_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    ORCHESTRATOR_TASK_PROMPT,
)


def usage_token_stats(usage: dict[str, Any]) -> dict[str, int] | None:
    """Normalize provider usage into the trace token block (or None).

    Mirrors ``aus_agent.agent._usage_token_stats`` so token accounting is
    consistent across systems (Bedrock excludes cache reads from inputTokens;
    OpenAI's provider already subtracts them back out).
    """
    if not usage:
        return None
    uncached = int(usage.get("inputTokens", usage.get("input_tokens", 0)) or 0)
    output = int(usage.get("outputTokens", usage.get("output_tokens", 0)) or 0)
    cache_read = int(usage.get("cacheReadInputTokens",
                               usage.get("cache_read_input_tokens", 0)) or 0)
    cache_write = int(usage.get("cacheWriteInputTokens",
                                usage.get("cache_write_input_tokens", 0)) or 0)
    logical = uncached + cache_read + cache_write
    processed = uncached + cache_write
    return {"input": logical, "input_uncached": uncached, "output": output,
            "cache_read": cache_read, "cache_write": cache_write,
            "total": logical + output, "processed_input": processed,
            "processed": processed + output}


def one_shot(provider: Any, system_prompt: str, user_text: str) -> str:
    """Run one fresh, tool-less turn and return its text.

    The turn's usage is stashed on the provider as ``_last_usage`` so callers
    that want token stats can read it without changing the ``Provider``
    contract.
    """
    provider.start(system_prompt, [])
    provider.add_user_message(user_text)
    turn = provider.run_turn()
    provider._last_usage = turn.get("usage", {})  # type: ignore[attr-defined]
    return turn.get("text") or ""


@dataclass
class Analysis:
    relevant: list[dict[str, str]]   # [{"docid", "note"}]
    gap: str | None
    satisfied: bool


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL)
    return fence.group(1).strip() if fence else raw


def parse_analysis(raw: str, valid_docids: set[str]) -> Analysis:
    """Parse the analyzer JSON, dropping anything not in ``valid_docids``.

    Unparseable output is treated as "nothing kept, no gap, satisfied" so the
    loop stops rather than spinning on a facet whose analyzer keeps failing to
    answer in the expected shape.
    """
    try:
        payload = json.loads(_strip_fences(raw))
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
    """One replayable trace event — an orchestrator turn or an analysis call."""
    kind: str  # "oss_turn" | "qwen_analysis"
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
    evidence: list[dict[str, Any]]   # [{"docid", "note", "text"}], first-seen wins
    events: list[LoopEvent]
    iterations_used: int
    stop_reason: str  # "analyzer_satisfied" | "orchestrator_no_search" | "max_iterations"


def _render_passages(passages: list[dict[str, Any]]) -> str:
    if not passages:
        return "(no passages)"
    return "\n\n".join(f"[docid={p['docid']}]\n{p['text']}" for p in passages)


def _render_evidence(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(none yet)"
    return "\n".join(f"- [{e['docid']}] {e['note']}" for e in evidence)


def run_facet_loop(*, make_orchestrator: Any, make_analyzer: Any,
                   facet: Facet, engines: list[str], max_chars: int
                   ) -> FacetLoopResult:
    """Run one facet's orchestrator/analyzer search-analyze-gap loop.

    ``make_orchestrator``/``make_analyzer`` are zero-arg factories returning a
    fresh ``Provider`` each call — required because a ``Provider`` owns its
    own conversation state and facets run concurrently in their own threads.
    """
    from tools.search_tool import ENGINE_INFO, _query_guidance  # local: avoid
    # a hard import-time dependency on tools.search_tool internals elsewhere.

    orchestrator = make_orchestrator()
    analyzer = make_analyzer()
    tool_def = build_search_tool(engines)
    engine_blurbs = "\n".join(f"- {e}: {ENGINE_INFO[e]['blurb']}" for e in engines)
    orchestrator.start(
        ORCHESTRATOR_SYSTEM_PROMPT.format(
            engine_blurbs=engine_blurbs, query_guidance=_query_guidance(engines)),
        [tool_def])
    orchestrator.add_user_message(ORCHESTRATOR_TASK_PROMPT.format(
        facet_name=facet.name, facet_description=facet.description))

    cap = min(max(1, facet.max_iterations), GLOBAL_ITERATION_CAP)
    evidence: list[dict[str, Any]] = []
    seen_docids: set[str] = set()
    events: list[LoopEvent] = []
    stop_reason = "max_iterations"
    iterations_used = 0

    for _ in range(cap):
        iterations_used += 1
        turn = orchestrator.run_turn()
        tool_calls = turn.get("tool_calls") or []
        ev = LoopEvent(kind="oss_turn", oss_text=turn.get("text"),
                       oss_stats=usage_token_stats(turn.get("usage") or {}))
        events.append(ev)
        if not tool_calls:
            stop_reason = "orchestrator_no_search"
            break

        tool_results = []
        new_passages: list[dict[str, Any]] = []
        for call in tool_calls:
            args = call.get("arguments") or {}
            output = run_search_tool(
                query=str(args.get("query", "")),
                k=int(args.get("k", 10) or 10),
                max_chars=max_chars,
                search_engine=str(args.get("search_engine") or engines[0]))
            data = json.loads(output)
            failed = "error" in data
            results = [] if failed else data.get("results", [])
            ev.tool_calls.append({
                "arguments": args, "output": output,
                "returned_docids": [str(r["docid"]) for r in results],
                "failed": failed,
            })
            tool_results.append({"id": call["id"], "content": output,
                                 "is_error": failed})
            for r in results:
                docid = str(r["docid"])
                if docid in seen_docids:
                    continue
                seen_docids.add(docid)
                new_passages.append({"docid": docid, "text": r.get("text") or ""})
        orchestrator.add_tool_results(tool_results)

        if not new_passages:
            gap = ("The last search returned no new passages. Try a "
                  "different engine or reformulate the query.")
            events.append(LoopEvent(kind="qwen_analysis", satisfied=False,
                                    gap=gap, relevant_count=0))
            orchestrator.add_user_message(
                ORCHESTRATOR_GAP_PROMPT.format(gap=gap))
            continue

        analysis_prompt = ANALYZER_PROMPT.format(
            facet_name=facet.name, facet_description=facet.description,
            evidence_so_far=_render_evidence(evidence),
            passages=_render_passages(new_passages))
        raw = one_shot(analyzer, "", analysis_prompt)
        qstats = usage_token_stats(getattr(analyzer, "_last_usage", {}))
        analysis = parse_analysis(
            raw, valid_docids={p["docid"] for p in new_passages})
        events.append(LoopEvent(
            kind="qwen_analysis", qwen_stats=qstats,
            gap=analysis.gap, satisfied=analysis.satisfied,
            relevant_count=len(analysis.relevant)))

        text_by_docid = {p["docid"]: p["text"] for p in new_passages}
        for item in analysis.relevant:
            evidence.append({"docid": item["docid"], "note": item["note"],
                            "text": text_by_docid.get(item["docid"], "")})

        if analysis.satisfied:
            stop_reason = "analyzer_satisfied"
            break
        orchestrator.add_user_message(ORCHESTRATOR_GAP_PROMPT.format(
            gap=analysis.gap or "more evidence needed"))

    return FacetLoopResult(facet=facet, evidence=evidence, events=events,
                           iterations_used=iterations_used,
                           stop_reason=stop_reason)
