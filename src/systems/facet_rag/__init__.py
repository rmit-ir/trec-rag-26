"""facet_rag — orchestrator/analyzer multi-facet RAG over ClimbMix (TREC RAG 2026).

    plan (orchestrator, 1 call)
      -> per-facet orchestrator/analyzer search-analyze-gap loops, run
         concurrently (loop.run_facet_loop), each up to 10 iterations
      -> joint draft (orchestrator) + fact-check (analyzer) synthesis
      -> strict TREC RAG artifacts

Two Bedrock models play fixed roles: the ORCHESTRATOR (default
``openai.gpt-oss-120b-1:0``) plans facets and drives the search tool; the
ANALYZER (default ``qwen.qwen3-next-80b-a3b``) judges retrieved passages
against each facet's need and reports coverage gaps. Both go through the
shared ``aus_agent.providers.bedrock.BedrockProvider``. Retrieval goes
through ``tools.search_tool`` (all four engines); the answer is shaped by
``ali_deepresearch.answer_format.format_answer`` and written via
``ragrun.save_run``. Every citation is a ClimbMix docid; no web search.

Public surface:

    from facet_rag import Facet, run_one, parse_facets, run_facet_loop
"""
from .loop import FacetLoopResult, LoopEvent, run_facet_loop
from .planner import Facet, build_plan_prompt, fallback_facets, parse_facets
from .pipeline import SYSTEM_NAME, run_one

__all__ = [
    "Facet",
    "build_plan_prompt",
    "fallback_facets",
    "parse_facets",
    "SYSTEM_NAME",
    "run_one",
    "FacetLoopResult",
    "LoopEvent",
    "run_facet_loop",
]
