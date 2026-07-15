"""Shared types for the search layer.

Kept in its own module (no imports from the client/fusion modules) so every
retrieval backend and the fusion layer can share ``SearchHit`` without an import
cycle.
"""
from __future__ import annotations

from typing import Any, TypedDict


class SearchHit(TypedDict):
    """One normalized retrieval result, uniform across all backends
    (``search_dense``, ``search_sparse``, ``search_pyserini``, and the fused
    results from ``search``).

    - ``docid``  external document id (e.g. ``shard_00042_1337``)
    - ``score``  backend score (BM25 / inner-product / RRF for fused results)
    - ``rank``   1-based rank within that backend's result list
    - ``text``   document text if the backend returned it, else ``None``
    - ``meta``   untyped backend-specific extras (source name, raw fields,
                 per-source RRF breakdown, hosted-index name, ...)
    """
    docid: str
    score: float
    rank: int
    text: str | None
    meta: dict[str, Any]
