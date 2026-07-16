"""ragrun — shared run-output layer for TREC RAG 2026 agent systems.

Every RAG agent run produces exactly two JSON artifacts, saved under
``data/outputs/<system-name>/``:

- ``<ts>.<slug>.trajectory.json`` — full agent trace (reasoning, tool calls,
  retrieved docids, raw provider messages), format modeled on
  ``data/sample-files/run_InfoSeekQA_*.json``.
- ``<ts>.<slug>.output.json``     — one TREC RAG 2026 output object
  (``metadata`` / ``references`` / ``answer`` with sentence-level citations),
  per the track's ``rag-task.md``.

Retrieval MUST go through the ClimbMix search utils (``utils.search*`` /
``tools.search_tool``); all cited ids are ClimbMix docids. Agents never use
web search.
"""
from ragrun.trajectory import TrajectoryBuilder, now_iso
from ragrun.outputs import (
    build_rag_output,
    validate_rag_output,
    save_run,
    run_timestamp,
    query_slug,
)

__all__ = [
    "TrajectoryBuilder",
    "now_iso",
    "build_rag_output",
    "validate_rag_output",
    "save_run",
    "run_timestamp",
    "query_slug",
]
