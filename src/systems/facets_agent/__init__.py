"""facets_agent — minimal-prompt, facet_rag-inspired research agent (TREC RAG 2026).

Corpus-only RAG over ClimbMix, driven by a single continuous tool-calling
agent (the shared ``agent_harness.agent.run_agent`` harness, configured with
this package's own prompt/engines/hybrid-k instead of aus_agent's). Every citation
is a ClimbMix docid. Both run artifacts are written under
``data/outputs/facets_agent/`` via ``ragrun.save_run``.
"""
from .agent import DEFAULT_ENGINES, SYSTEM_NAME, run_agent

__all__ = ["DEFAULT_ENGINES", "SYSTEM_NAME", "run_agent"]
