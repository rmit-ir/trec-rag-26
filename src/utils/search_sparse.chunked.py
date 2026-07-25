"""DRAFT — NOT APPLIED. Proposed post-cutover shape for search_sparse.

This file is a design artifact for tasks/bm25_index/CHUNKED-REINDEX-DESIGN.md.
It is NOT imported anywhere and must NOT replace the live src/utils/search_sparse.py
until the sparse index-server has been relaunched against the CHUNKED index
(data/built-indexes/climbmix-bm25-chunked/). Ordering: index built -> server
relaunched -> this becomes search_sparse.py.

What changes vs the live client:
- Docstring: results are now CHUNK-keyed (id = chunk id `<docid>_p<page>`, parent
  docid derivable via chunk_id.rsplit("_p",1)[0]) with CHUNK-segment text — not
  whole documents. This mirrors search_dense.
- meta now records granularity so the fusion layer can see the retrieval unit
  without re-deriving it.

What does NOT change:
- The parsing (`_id` -> id, `_source.contents` -> text) is identical; make_hit +
  classify_id already auto-derive kind="chunk" and the parent docid from the
  `_p<page>` suffix. The correctness of the migration comes from the SERVER
  returning chunk ids, not from this file.
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

from utils.search_dense import auth_headers, post_json

DEFAULT_SPARSE_URL = "https://index-climbmix-bm25.dsync.net"


def search_sparse(query: str, k: int = 10, *, url: str | None = None,
                  timeout: float = 30.0) -> list["SearchHit"]:
    """Run BM25 over the CHUNKED index. Returns a list of ``SearchHit``.

    Post-cutover the index-server is keyed by chunk id (``<docid>_p<page>``) and
    stores chunk-segment text, so each hit's ``id`` is a chunk id, ``kind`` is
    ``"chunk"``, ``docid`` is the parent doc, and ``text`` is the chunk segment —
    the same shape as ``search_dense``, so fusion/citation/dedup line up 1:1
    across engines.
    """
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
            # granularity is explicit now so downstream code needn't re-derive it
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
