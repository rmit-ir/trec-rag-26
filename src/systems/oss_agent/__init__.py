"""oss_agent -- open-weight-only fork of brief_revise_agent (TREC RAG 2026).

Corpus-only RAG over ClimbMix, driven by the same shared
``agent_harness.agent.run_agent`` harness aus_agent/brief_revise_agent use.
Every model role (main writer, brief analyst, reviewer, blind scout) is
restricted to a Bedrock open-weight model id -- no OpenAI ``gpt-5.6-*``
model, no proprietary Bedrock model (e.g. ``anthropic.*``), anywhere in the
pipeline. See ``agent.py``'s module docstring and ``README.md`` for the
taxonomy-informed design rationale. Run artifacts are written under
``data/outputs/oss_agent/`` via ``ragrun.save_run``.
"""
from .agent import ALLOWED_MODELS, DEFAULT_ENGINES, DEFAULT_MODEL, SYSTEM_NAME, run_agent

__all__ = [
    "ALLOWED_MODELS", "DEFAULT_ENGINES", "DEFAULT_MODEL", "SYSTEM_NAME",
    "run_agent",
]
