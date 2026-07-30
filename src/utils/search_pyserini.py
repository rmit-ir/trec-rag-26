"""Pyserini hosted BM25 client — Castorini/UWaterloo API.

Talks to the hosted Pyserini search API (``/v1/<index>/search``) over GET with a
Bearer token, and returns hits normalized to the shared ``SearchHit`` type.

Response shape (per the API):
    {"api": "v1", "index": "climbmix-400b", "query": {"text": ...},
     "candidates": [{"docid": ..., "score": ..., "rank": ..., "doc": <text>}, ...]}

Config (loaded from ``.env`` if python-dotenv is installed):

- ``PYSERINI_SEARCH_URL``  full search URL
                           (default: hosted climbmix-400b endpoint)
- ``PYSERINI_API_TOKEN``   Bearer token for the API.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from utils.fetch_doc import _doc_text
from utils.http_retry import urlopen_with_backoff
from utils.search_types import SearchHit, make_hit

try:  # optional; env still works without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEFAULT_PYSERINI_URL = "http://api.castorini.uwaterloo.ca/v1/climbmix-400b/search"


def _get_json(url: str, params: dict[str, Any], token: str | None,
              timeout: float) -> dict[str, Any]:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "trec-rag-search/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(full, headers=headers, method="GET")
    with urlopen_with_backoff(req, timeout=timeout) as r:
        return json.load(r)


def search_pyserini(query: str, k: int = 10, *, url: str | None = None,
                    token: str | None = None,
                    timeout: float = 30.0) -> list[SearchHit]:
    """Run hosted Pyserini BM25. Returns a list of ``SearchHit`` (see search.py)."""
    endpoint = url or os.environ.get("PYSERINI_SEARCH_URL", DEFAULT_PYSERINI_URL)
    tok = token or os.environ.get("PYSERINI_API_TOKEN")

    data = _get_json(endpoint, {"query": query, "hits": k}, tok, timeout)
    index = data.get("index")
    api = data.get("api")

    hits: list[SearchHit] = []
    for i, c in enumerate(data.get("candidates", []), start=1):
        # The spec: "If `doc` is an object, extract its text-bearing field such
        # as `text` or `contents`; if it is a string, use the string directly."
        # A missing `doc` (the docids-only response mode) must stay None rather
        # than become "" — that None is what tells the fusion layer to borrow
        # text from another source.
        doc = c.get("doc")
        hits.append(make_hit(
            c["docid"],
            score=float(c["score"]),
            rank=c.get("rank", i),
            text=None if doc is None else _doc_text(doc),
            meta={"source": "pyserini", "index": index, "api": api},
        ))
    return hits


if __name__ == "__main__":  # quick manual check
    import sys
    q = " ".join(sys.argv[1:]) or "ping"
    for h in search_pyserini(q, k=5):
        print(h["rank"], h["docid"], round(h["score"], 4),
              (h["text"] or "")[:80].replace("\n", " "))
