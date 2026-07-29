"""facet_rag — plan-then-execute multi-facet RAG over ClimbMix (TREC RAG 2026).

A three-stage, corpus-only pipeline:

    plan (1 LLM call) -> execute (one ClimbMix search per facet) -> synthesize
    (1 LLM call) -> strict TREC RAG artifacts

Backends are pluggable via the shared ``aus_agent.providers`` (Bedrock /
OpenAI); retrieval goes through ``tools.search_tool`` (all four engines); the
answer is shaped by ``ali_deepresearch.answer_format.format_answer`` and written
via ``ragrun.save_run``. Every citation is a ClimbMix docid; no web search.

Public surface:

    from facet_rag import Facet, run_one, execute_plan, parse_facets
"""
from .planner import Facet, build_plan_prompt, fallback_facets, parse_facets
from .pipeline import SYSTEM_NAME, run_one
from .search import Retrieval, execute_plan, execute_facet

__all__ = [
    "Facet",
    "build_plan_prompt",
    "fallback_facets",
    "parse_facets",
    "SYSTEM_NAME",
    "run_one",
    "Retrieval",
    "execute_plan",
    "execute_facet",
]
