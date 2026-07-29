"""facet_rag pipeline — plan -> execute -> synthesize -> artifacts.

Three deterministic stages, driven by the pluggable ``aus_agent.providers``
backends (Bedrock / OpenAI) behind the shared ``Provider`` contract:

1. PLAN       one LLM turn: narrative -> facets JSON (planner.parse_facets).
2. EXECUTE    no LLM: one ClimbMix search per facet (search.execute_plan).
3. SYNTHESIZE one LLM turn: retrieved passages -> grounded prose.

The prose is then mapped to the strict TREC RAG sentence/citation shape by the
shared ``ali_deepresearch.answer_format.format_answer`` (LLM stage reused from
this system's synthesis provider, deterministic heuristic fallback), and both
run artifacts are written via ``ragrun.save_run``. Every LLM turn is a fresh,
tool-less conversation, so the provider's turn API is used single-shot.
"""
from __future__ import annotations

from typing import Any

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run

from ali_deepresearch.answer_format import format_answer

from .planner import (
    Facet,
    build_plan_prompt,
    fallback_facets,
    parse_facets,
)
from .prompts import SYNTHESIZE_PROMPT
from .search import Retrieval, execute_plan, format_passages_for_synthesis

SYSTEM_NAME = "facet_rag"


def _usage_token_stats(usage: dict[str, Any]) -> dict[str, int] | None:
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


class _ProviderLLM:
    """Adapt a turn-based ``Provider`` to the ``format_answer`` ChatLLM shape.

    ``format_answer`` calls ``llm.complete(messages, stop=, max_tokens=)`` and
    expects a plain string. Each call is a self-contained, tool-less turn.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self.last_usage: dict[str, Any] = {}

    def complete(self, messages: list[dict[str, str]], *,
                 stop: list[str] | None = None,
                 max_tokens: int | None = None) -> str:
        # messages is a single user turn from format_answer.
        system = ""
        user_parts: list[str] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_parts.append(m["content"])
        text = one_shot(self._provider, system, "\n\n".join(user_parts))
        self.last_usage = getattr(self._provider, "_last_usage", {})
        return text


def one_shot(provider: Any, system_prompt: str, user_text: str
             ) -> tuple[str, dict[str, Any]] | str:
    """Run one fresh, tool-less turn and return its text (+ usage on provider).

    Returns just the text; the turn's usage is stashed on the provider as
    ``_last_usage`` so callers that want token stats can read it without
    changing the ``Provider`` contract.
    """
    provider.start(system_prompt, [])
    provider.add_user_message(user_text)
    turn = provider.run_turn()
    provider._last_usage = turn.get("usage", {})  # type: ignore[attr-defined]
    return turn.get("text") or ""


def run_one(provider: Any, *, qid: str, narrative: str, engines: list[str],
            default_engine: str, run_id: str, run_desc: str,
            model_id: str, backend: str, max_chars: int,
            min_facets: int, max_facets: int,
            format_llm: bool = True) -> dict[str, Any]:
    """Execute the full plan->execute->synthesize pipeline for one narrative."""
    started_at = now_iso()
    meta = {
        "model": model_id,
        "backend": backend,
        "engines": engines,
        "run_id": run_id,
        "query_source": narrative,
        "strategy": "plan-then-execute (multi-facet)",
    }
    tb = TrajectoryBuilder(qid, narrative, metadata=meta)

    # -- stage 1: plan ------------------------------------------------------
    t0 = now_iso()
    plan_prompt = build_plan_prompt(narrative, engines,
                                    min_facets=min_facets, max_facets=max_facets)
    plan_raw = one_shot(provider, "", plan_prompt)
    t1 = now_iso()
    plan_stats = _usage_token_stats(getattr(provider, "_last_usage", {}))
    tb.add_reasoning(f"Plan:\n{plan_raw}", t_start=t0, t_end=t1, turn=0,
                     stats={"tokens": plan_stats} if plan_stats else None)

    facets = parse_facets(plan_raw, engines, default_engine=default_engine)
    if not facets:
        facets = fallback_facets(narrative, default_engine=default_engine)

    # -- stage 2: execute (one search per facet) ----------------------------
    retrieval = execute_plan(facets, max_chars=max_chars)
    for i, fr in enumerate(retrieval.per_facet):
        ts, te = now_iso(), now_iso()
        tb.add_tool_call(
            "search",
            {"query": fr.facet.query, "search_engine": fr.facet.engine,
             "k": fr.facet.k},
            fr.output,
            returned_docids=[p["docid"] for p in fr.passages],
            failed=fr.failed, t_start=ts, t_end=te, turn=1,
            facet=fr.facet.name)

    # -- stage 3: synthesize ------------------------------------------------
    t2 = now_iso()
    synth_prompt = SYNTHESIZE_PROMPT.format(
        narrative=narrative,
        passages=format_passages_for_synthesis(retrieval.passages))
    draft = one_shot(provider, "", synth_prompt)
    t3 = now_iso()
    synth_stats = _usage_token_stats(getattr(provider, "_last_usage", {}))
    tb.add_model_step(output="synthesis", input="(passages)",
                      t_start=t2, t_end=t3, turn=2,
                      stats={"tokens": synth_stats} if synth_stats else None)

    # -- artifacts: strict sentence/citation shape --------------------------
    llm = _ProviderLLM(provider) if format_llm else None
    references, answer = format_answer(draft, retrieval.docids, llm=llm)
    tb.add_output_text(draft, t_start=t3, t_end=now_iso(), turn=2)

    ended_at = now_iso()
    status = "completed" if references else "no_references"
    trajectory = tb.finalize(status=status, started_at=started_at,
                             ended_at=ended_at)
    output = build_rag_output(
        narrative_id=qid, narrative=narrative, run_id=run_id,
        run_desc=run_desc, references=references, answer=answer)

    paths = save_run(SYSTEM_NAME, narrative, trajectory=trajectory,
                     output=output)
    return {"paths": paths, "facets": facets, "retrieval": retrieval,
            "references": references, "status": status}
