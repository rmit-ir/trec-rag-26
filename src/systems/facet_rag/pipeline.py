"""facet_rag pipeline — plan -> per-facet orchestrator/analyzer loops ->
joint draft + fact-check -> artifacts.

1. PLAN        one orchestrator turn: narrative -> facets (planner.parse_facets).
2. FACET LOOPS one orchestrator/analyzer loop per facet, run concurrently
               (loop.run_facet_loop) — each facet accumulates its own
               analyst-vetted evidence.
3. SYNTHESIZE  orchestrator drafts the cited report from all facets' merged
               evidence; the analyzer fact-checks/patches it in a second pass.

The final prose is then mapped to the strict TREC RAG sentence/citation shape
by ``ali_deepresearch.answer_format.format_answer``, and both run artifacts
are written via ``ragrun.save_run``.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run

from ali_deepresearch.answer_format import format_answer

from .loop import FacetLoopResult, one_shot, run_facet_loop, usage_token_stats
from .planner import build_plan_prompt, fallback_facets, parse_facets
from .prompts import FACT_CHECK_PROMPT, SYNTH_DRAFT_PROMPT

SYSTEM_NAME = "facet_rag"

# Re-exported for callers/tests that want the token-normalization helper
# under its historical name.
_usage_token_stats = usage_token_stats


class _ProviderLLM:
    """Adapt a turn-based ``Provider`` to the ``format_answer`` ChatLLM shape.

    ``format_answer`` calls ``llm.complete(messages, stop=, max_tokens=)`` and
    expects a plain string. Each call is a self-contained, tool-less turn.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def complete(self, messages: list[dict[str, str]], *,
                 stop: list[str] | None = None,
                 max_tokens: int | None = None) -> str:
        system = ""
        user_parts: list[str] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_parts.append(m["content"])
        return one_shot(self._provider, system, "\n\n".join(user_parts))


def _sandwich_order(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder evidence so the strongest items sit at both edges, weakest in
    the middle -- the standard mitigation for "lost in the middle" (models
    under-weight the center of a long context).

    Ranked by each item's own ``rank`` (1-indexed position within the search
    call that surfaced it) ascending -- best first. ``rank`` is comparable
    within one engine's result list but NOT calibrated across engines (a
    dense cosine score and a BM25 score are different scales); using rank
    instead of raw score sidesteps that, at the cost of only ordering within
    each search's own confidence, not truly cross-engine. Items with no rank
    (shouldn't happen; defensive) sort last.
    """
    ranked = sorted(
        evidence,
        key=lambda e: e.get("rank") if e.get("rank") is not None else float("inf"))
    ordered: list[Any] = [None] * len(ranked)
    lo, hi = 0, len(ranked) - 1
    for i, item in enumerate(ranked):
        if i % 2 == 0:
            ordered[lo] = item
            lo += 1
        else:
            ordered[hi] = item
            hi -= 1
    return ordered


def _render_evidence_block(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(no evidence retrieved)"
    blocks = []
    for i, e in enumerate(_sandwich_order(evidence), 1):
        blocks.append(f"[{i}] docid={e['docid']} facet={e['facet']}\n"
                      f"note: {e['note']}\n{e['text']}")
    return "\n\n".join(blocks)


def _merge_evidence(facet_results: list[FacetLoopResult]
                    ) -> list[dict[str, Any]]:
    """Dedup evidence by docid across facets — first facet to surface it wins."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fr in facet_results:
        for item in fr.evidence:
            if item["docid"] in seen:
                continue
            seen.add(item["docid"])
            merged.append({**item, "facet": fr.facet.name})
    return merged


def _replay_events(tb: TrajectoryBuilder, facet_results: list[FacetLoopResult],
                   turn_start: int) -> int:
    """Write every facet's buffered loop events into ``tb``, in facet order.

    Facets run concurrently in their own threads (``TrajectoryBuilder`` is not
    thread-safe), so nothing touches ``tb`` until every facet has finished.
    Returns the next free turn number.
    """
    turn = turn_start
    for fr in facet_results:
        for ev in fr.events:
            if ev.kind == "oss_turn":
                tb.add_model_step(
                    output=ev.oss_text or "", input=fr.facet.description,
                    turn=turn,
                    stats={"tokens": ev.oss_stats} if ev.oss_stats else None)
                for tc in ev.tool_calls:
                    tb.add_tool_call(
                        "search", tc["arguments"], tc["output"],
                        returned_docids=tc["returned_docids"],
                        failed=tc["failed"], turn=turn, facet=fr.facet.name)
            else:  # "qwen_analysis"
                tb.add_model_step(
                    output=(f"satisfied={ev.satisfied} gap={ev.gap!r} "
                           f"kept={ev.relevant_count}"),
                    input=fr.facet.description, turn=turn,
                    stats={"tokens": ev.qwen_stats} if ev.qwen_stats else None)
            turn += 1
    return turn


def run_one(make_orchestrator: Callable[[], Any],
           make_analyzer: Callable[[], Any], *, qid: str, narrative: str,
           engines: list[str], run_id: str, run_desc: str,
           orchestrator_model_id: str, analyzer_model_id: str,
           max_chars: int, min_facets: int, max_facets: int,
           format_llm: bool = True) -> dict[str, Any]:
    """Execute the full plan -> facet loops -> synthesize pipeline."""
    started_at = now_iso()
    meta = {
        "models": {"orchestrator": orchestrator_model_id,
                   "analyzer": analyzer_model_id},
        "engines": engines,
        "run_id": run_id,
        "query_source": narrative,
        "strategy": "orchestrator/analyzer facet loops",
    }
    tb = TrajectoryBuilder(qid, narrative, metadata=meta)

    # -- stage 1: plan --------------------------------------------------------
    t0 = now_iso()
    orchestrator = make_orchestrator()
    plan_raw = one_shot(orchestrator, "", build_plan_prompt(
        narrative, min_facets=min_facets, max_facets=max_facets))
    t1 = now_iso()
    plan_stats = usage_token_stats(getattr(orchestrator, "_last_usage", {}))
    tb.add_reasoning(f"Plan:\n{plan_raw}", t_start=t0, t_end=t1, turn=0,
                     stats={"tokens": plan_stats} if plan_stats else None)

    facets = parse_facets(plan_raw)
    if not facets:
        facets = fallback_facets(narrative)

    # -- stage 2: per-facet orchestrator/analyzer loops, run concurrently -----
    with ThreadPoolExecutor(max_workers=max(1, len(facets))) as pool:
        facet_results = list(pool.map(
            lambda facet: run_facet_loop(
                make_orchestrator=make_orchestrator, make_analyzer=make_analyzer,
                facet=facet, engines=engines, max_chars=max_chars),
            facets))
    next_turn = _replay_events(tb, facet_results, turn_start=1)

    evidence = _merge_evidence(facet_results)
    docids = [e["docid"] for e in evidence]

    # -- stage 3: joint draft + fact-check synthesis ---------------------------
    t2 = now_iso()
    evidence_block = _render_evidence_block(evidence)
    draft_provider = make_orchestrator()
    draft = one_shot(draft_provider, "", SYNTH_DRAFT_PROMPT.format(
        narrative=narrative, evidence=evidence_block))
    draft_stats = usage_token_stats(getattr(draft_provider, "_last_usage", {}))
    tb.add_model_step(output="draft", input="(evidence)", t_start=t2,
                      t_end=now_iso(), turn=next_turn,
                      stats={"tokens": draft_stats} if draft_stats else None)
    next_turn += 1

    t3 = now_iso()
    check_provider = make_analyzer()
    checked = one_shot(check_provider, "", FACT_CHECK_PROMPT.format(
        narrative=narrative, draft=draft, evidence=evidence_block))
    check_stats = usage_token_stats(getattr(check_provider, "_last_usage", {}))
    tb.add_model_step(output="fact_check", input="(draft, evidence)",
                      t_start=t3, t_end=now_iso(), turn=next_turn,
                      stats={"tokens": check_stats} if check_stats else None)
    final_text = checked.strip() or draft

    # -- artifacts: strict sentence/citation shape ----------------------------
    llm = _ProviderLLM(make_orchestrator()) if format_llm else None
    references, answer = format_answer(final_text, docids, llm=llm)
    tb.add_output_text(final_text, t_start=t3, t_end=now_iso(), turn=next_turn)

    ended_at = now_iso()
    status = "completed" if references else "no_references"
    trajectory = tb.finalize(status=status, started_at=started_at,
                             ended_at=ended_at)
    output = build_rag_output(
        narrative_id=qid, narrative=narrative, run_id=run_id,
        run_desc=run_desc, references=references, answer=answer)

    paths = save_run(SYSTEM_NAME, narrative, trajectory=trajectory,
                     output=output)
    return {"paths": paths, "facets": facets, "facet_results": facet_results,
            "evidence": evidence, "references": references, "status": status}
