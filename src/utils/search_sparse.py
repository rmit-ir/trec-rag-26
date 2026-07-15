"""Sparse retrieval client — Anserini/Lucene BM25 index-server.

Talks to index-server (``/api/search``) and returns hits normalized to
``{docid, score, rank, text}``.

Config (loaded from ``.env`` if python-dotenv is installed):

- ``SPARSE_SEARCH_URL``  base URL (default: http://127.0.0.1:8085)
- ``SEARCH_API_KEY``     reused if the sparse endpoint is behind Basic auth.
"""
from __future__ import annotations

import os
from typing import Any

from src.utils.search_types import SearchHit

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# Reuse the shared auth + POST helpers so both clients behave identically.
from src.utils.search_dense import auth_headers, post_json

DEFAULT_SPARSE_URL = "http://127.0.0.1:8085"


def search_sparse(query: str, k: int = 10, *, url: str | None = None,
                  timeout: float = 30.0) -> list["SearchHit"]:
    """Run BM25. Returns a list of ``SearchHit`` (see search.py)."""
    base = (url or os.environ.get("SPARSE_SEARCH_URL", DEFAULT_SPARSE_URL)).rstrip("/")
    body: dict[str, Any] = {"query": query, "hits": k}

    data = post_json(f"{base}/api/search", body, auth_headers(), timeout)
    hits: list[SearchHit] = []
    for i, h in enumerate(data.get("hits", {}).get("hits", []), start=1):
        source = h.get("_source") or {}
        hits.append({
            "docid": h["_id"],
            "score": float(h["_score"]),
            "rank": i,
            "text": source.get("contents"),
            "meta": {"source": "sparse", "_index": h.get("_index")},
        })
    return hits


if __name__ == "__main__":  # quick manual check
    import sys
    q = " ".join(sys.argv[1:]) or "influenza vaccination"
    for h in search_sparse(q, k=5):
        print(h["rank"], h["docid"], round(h["score"], 4),
              (h["text"] or "")[:80].replace("\n", " "))
