"""SSR Boolean retrieval client — Cottontail Shortest-Substring Ranking.

Talks to the ``tasks/ssr_search`` HTTP service (``serve.py``, default
``:8099``) which wraps the Cottontail ``ssr-server`` over the full-corpus Hazel
burrows. Queries are **GCL Boolean** expressions (not natural language); see
``src/tools/search_tool.py`` for the operator/tactics guidance handed to the
agent. Returns hits normalized to the shared ``SearchHit`` shape.

Config (loaded from ``.env`` if python-dotenv is installed):

- ``SSR_SEARCH_URL``  base URL of the SSR service (default ``http://127.0.0.1:8099``)

The service is local, so no auth is sent. SSR ranks by shortest matching
substring and does not expose a numeric score, so we synthesize a
rank-descending score (``1/rank``) purely so downstream ordering is stable;
scores are not comparable across engines (already documented in the tool).
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

# Reuse the shared POST helper (no auth headers for the local service).
from utils.search_dense import post_json

DEFAULT_SSR_URL = "http://127.0.0.1:8099"


def search_ssr(query: str, k: int = 10, *, url: str | None = None,
               timeout: float = 60.0) -> list["SearchHit"]:
    """Run an SSR/GCL Boolean query. Returns a list of ``SearchHit``.

    ``query`` is a GCL expression, e.g. ``(^ uranium enrichment russia)``.
    """
    base = (url or os.environ.get("SSR_SEARCH_URL", DEFAULT_SSR_URL)).rstrip("/")
    body: dict[str, Any] = {"query": query, "k": k}

    data = post_json(f"{base}/search", body, {}, timeout)
    hits: list[SearchHit] = []
    for i, h in enumerate(data.get("results", []), start=1):
        rank = int(h.get("rank", i))
        hits.append(make_hit(
            h["docno"],
            score=round(1.0 / rank, 6),
            rank=rank,
            text=h.get("snippet"),
            meta={"source": "ssr", "burrow": h.get("burrow")},
        ))
    return hits


if __name__ == "__main__":  # quick manual check
    import sys
    q = " ".join(sys.argv[1:]) or "(^ influenza vaccine)"
    for h in search_ssr(q, k=5):
        print(h["rank"], h["docid"], round(h["score"], 4),
              (h["text"] or "")[:80].replace("\n", " "))
