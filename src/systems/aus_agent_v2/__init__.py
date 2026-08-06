"""AUS v2 — coverage-planned, evidence-patched RAG for TREC RAG 2026.

Corpus-only RAG over ClimbMix: retrieval goes through ``tools.search_tool`` /
``utils.fetch_doc`` and every citation is a ClimbMix docid. Both run artifacts
are written under ``data/outputs/aus_agent_v2/`` via ``ragrun.save_run``.
"""
from .pipeline import SYSTEM_NAME, run_one

__all__ = ["SYSTEM_NAME", "run_one"]
