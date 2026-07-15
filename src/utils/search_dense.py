"""Dense retrieval client — Jina-v5 DiskANN search endpoint.

Talks to the dense search service (``/search``) and returns hits normalized to
``{docid, score, rank, text}`` so the fusion layer can treat dense and sparse
results uniformly.

Config comes from the environment (loaded from a ``.env`` if python-dotenv is
installed):

- ``DENSE_SEARCH_URL``  base URL (default: the hosted Jina-v5 nano endpoint)
- ``SEARCH_API_KEY``    single API key for the search services. Either a ready
                        HTTP Basic token, or ``user:pass`` (auto base64-encoded).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Any

from src.utils.search_types import SearchHit

try:  # optional; env still works without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEFAULT_DENSE_URL = "https://index-climbmix-jina-v5-nano.dsync.net"


def auth_headers() -> dict[str, str]:
    """Authorization header from the single SEARCH_API_KEY env var, or {}."""
    key = os.environ.get("SEARCH_API_KEY")
    if not key:
        return {}
    # Accept either a raw "user:pass" (base64-encode it) or a pre-encoded token.
    token = base64.b64encode(key.encode()).decode() if ":" in key else key
    return {"Authorization": f"Basic {token}"}


def post_json(url: str, body: dict[str, Any], headers: dict[str, str],
              timeout: float) -> dict[str, Any]:
    payload = json.dumps(body).encode()
    # A non-default User-Agent is required: the endpoint's proxy 403s the stock
    # "Python-urllib/x.y" UA.
    hdrs = {"Content-Type": "application/json",
            "User-Agent": "trec-rag-search/1.0", **headers}
    req = urllib.request.Request(url, data=payload, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def search_dense(query: str, k: int = 10, *, with_text: bool = True,
                 complexity: int | None = None, beam_width: int | None = None,
                 url: str | None = None, timeout: float = 30.0) -> list["SearchHit"]:
    """Run dense retrieval. Returns a list of ``SearchHit`` (see search.py)."""
    base = (url or os.environ.get("DENSE_SEARCH_URL", DEFAULT_DENSE_URL)).rstrip("/")
    body: dict[str, Any] = {"query": query, "k": k, "with_text": with_text}
    if complexity is not None:
        body["complexity"] = complexity
    if beam_width is not None:
        body["beam_width"] = beam_width

    data = post_json(f"{base}/search", body, auth_headers(), timeout)
    hits: list[SearchHit] = []
    for i, h in enumerate(data.get("hits", []), start=1):
        hits.append({
            "docid": h["docid"],
            "score": float(h["score"]),
            "rank": h.get("rank", i),
            "text": h.get("text"),
            "meta": {"source": "dense"},
        })
    return hits


if __name__ == "__main__":  # quick manual check
    import sys
    q = " ".join(sys.argv[1:]) or "influenza vaccination"
    for h in search_dense(q, k=5):
        print(h["rank"], h["docid"], round(h["score"], 4),
              (h["text"] or "")[:80].replace("\n", " "))
