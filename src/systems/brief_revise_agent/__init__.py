"""brief_revise_agent -- a fork of aus_agent, plus a pre-flight requirements
brief and one grounded review-and-revise pass (TREC RAG 2026).

Corpus-only RAG over ClimbMix, driven by the same shared
``agent_harness.agent.run_agent`` harness aus_agent uses, with the same
267-line tuned prompt, engine set, and budgets -- see ``PLAN.md`` for the
evidence this design is built on. Both run artifacts are written under
``data/outputs/brief_revise_agent/`` via ``ragrun.save_run``.
"""
from .agent import DEFAULT_ENGINES, SYSTEM_NAME, run_agent

__all__ = ["DEFAULT_ENGINES", "SYSTEM_NAME", "run_agent"]
