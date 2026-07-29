"""Sparse retrieval client — Anserini/Lucene BM25 index-server.

Talks to index-server (``/api/search``). The server is keyed by chunk id
(``<docid>_p<page>``) over the CHUNKED index and stores chunk-segment text, so
each hit's ``id`` is a chunk id, ``kind`` is ``"chunk"``, ``docid`` is the
parent doc (``id`` minus the ``_p<page>`` suffix), and ``text`` is the chunk
segment — the same shape as ``search_dense``, so fusion/citation/dedup line up
1:1 across engines. ``make_hit``/``classify_id`` derive kind + parent docid
from the id; the chunk-awareness comes from the SERVER returning chunk ids.

Config (loaded from ``.env`` if python-dotenv is installed):

- ``SPARSE_SEARCH_URL``  base URL (default: the hosted index-server endpoint)
- ``SEARCH_API_KEY``     reused if the sparse endpoint is behind Basic auth.
"""
from __future__ import annotations

import os
from typing import Any

from utils.search_types import SearchHit, make_hit

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# Reuse the shared auth + POST helpers so both clients behave identically.
from utils.search_dense import auth_headers, post_json

DEFAULT_SPARSE_URL = "https://index-climbmix-bm25.dsync.net"


def search_sparse(query: str, k: int = 10, *, url: str | None = None,
                  timeout: float = 30.0) -> list["SearchHit"]:
    """Run BM25 over the chunked index. Returns a list of ``SearchHit``
    (chunk-keyed: ``id`` = chunk id, ``kind`` = ``"chunk"``, ``text`` = the
    chunk segment); see search.py."""
    base = (url or os.environ.get("SPARSE_SEARCH_URL", DEFAULT_SPARSE_URL)).rstrip("/")
    body: dict[str, Any] = {"query": query, "hits": k}

    data = post_json(f"{base}/api/search", body, auth_headers(), timeout)
    hits: list[SearchHit] = []
    for i, h in enumerate(data.get("hits", {}).get("hits", []), start=1):
        source = h.get("_source") or {}
        hits.append(make_hit(
            h["_id"],
            score=float(h["_score"]),
            rank=i,
            text=source.get("contents"),
            # granularity is explicit so downstream code needn't re-derive it
            meta={"source": "sparse", "granularity": "chunk",
                  "_index": h.get("_index")},
        ))
    return hits


if __name__ == "__main__":  # quick manual check
    import sys
    q = " ".join(sys.argv[1:]) or "influenza vaccination"
    for h in search_sparse(q, k=5):
        print(h["rank"], h["id"], h["docid"], round(h["score"], 4),
              (h["text"] or "")[:80].replace("\n", " "))
