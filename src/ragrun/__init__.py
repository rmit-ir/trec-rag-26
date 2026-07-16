"""ragrun — shared run-output layer for TREC RAG 2026 agent systems.

Every RAG agent run produces exactly two JSON artifacts, saved under
``data/outputs/<system-name>/``:

- ``<ts>.<slug>.trajectory.json`` — strict retrieval-analysis/training
  projection modeled on ``data/sample-files/run_InfoSeekQA_*.json``.
- ``<ts>.<slug>.output.json`` — organizer-facing answer fields plus an
  internal top-level ``trace`` containing timings, tokens, documents, and
  context decisions. The submission exporter strips ``trace``.

Retrieval MUST go through the ClimbMix search utils (``utils.search*`` /
``tools.search_tool``); all cited ids are ClimbMix docids. Agents never use
web search.
"""
from ragrun.trajectory import TrajectoryBuilder, now_iso
from ragrun.outputs import (
    build_rag_output,
    submission_output,
    validate_rag_output,
    save_run,
    run_timestamp,
    query_slug,
)

__all__ = [
    "TrajectoryBuilder",
    "now_iso",
    "build_rag_output",
    "submission_output",
    "validate_rag_output",
    "save_run",
    "run_timestamp",
    "query_slug",
]
