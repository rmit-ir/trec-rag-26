"""Agent tool: Boolean (GCL) retrieval over the Cottontail SSR engine.

This is the paper's stack (*Boolean Queries Are All You Need?*, arXiv 2607.11362):
a Cottontail annotative index ranked by Shortest-Substring Ranking (SSR), driven
by a **GCL Boolean query language**. Unlike the OR-only BM25 ``search`` tool,
this executes true Boolean structure — AND / OR / phrase / proximity /
containment — so a required-but-absent term yields *zero* hits (a truthful
empty set) instead of drifting to a confidently-wrong near-match.

It talks HTTP to the ``tasks/ssr_search`` service (``serve.py``). Start that
first, e.g.:

    SSR_BURROWS=data/built-indexes/ssr-shard00000/json.burrow \\
      tasks/ssr_search/env/bin/uvicorn serve:app --port 8099   # from tasks/ssr_search

Config (env / .env):
    SSR_SEARCH_URL   base URL of the ssr-search service (default 127.0.0.1:8099)

Usage as a tool:
    from tools.search_boolean_tool import SEARCH_BOOLEAN_TOOL, run_search_boolean_tool
Usage as a CLI:
    python src/tools/search_boolean_tool.py '(+ influenza vaccine)' --k 5
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from utils.http_retry import urlopen_with_backoff

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEFAULT_SSR_URL = "http://127.0.0.1:8099"

_GCL_GUIDE = (
    "Query language is GCL (Cottontail). Operators: "
    "`(^ a b ...)` = AND (ALL terms must co-occur in one document body); "
    "`(+ a b ...)` = OR (any); "
    "`\"a b\"` = exact phrase (= `(... a b)`, adjacent and in order); "
    "`(>> A B)` = A that CONTAINS B; `(<< A B)` = A CONTAINED IN B; "
    "`(# k)` = the set of width-k windows, so proximity 'a AND b within k "
    "tokens' is `(<< (^ a b) (# k))`. Terms are Porter-stemmed, case-insensitive. "
    "RULES (measured on the full corpus): keep ANDs to AT MOST 3 required terms "
    "led by the rarest one — more terms shrink the set and usually return ZERO, "
    "not better precision; on an empty result DROP the weakest term and retry, "
    "NEVER add another; disambiguate a polysemous word by AND-ing one context "
    "term (`(^ \"de minimis\" tariff)`); quote multiword names but pair a phrase "
    "with a term; widen a facet with OR INSIDE the AND rather than lengthening "
    "it, e.g. `(^ uranium (+ enrichment conversion fabrication))`. This is a "
    "precision/co-occurrence tool — not for broad-topic recall."
)

SEARCH_BOOLEAN_TOOL: dict[str, Any] = {
    "name": "search_boolean",
    "description": (
        "Boolean keyword search over the ClimbMix corpus using the SSR engine. "
        "Use this instead of the OR-only `search` keyword engine when you need "
        "PRECISE co-occurrence: rare proper names/IDs that must appear TOGETHER, "
        "an entity constrained by an attribute, or verbatim phrases. Because it "
        "enforces Boolean structure, a required term that is absent returns an "
        "empty result set (a truthful zero) rather than a wrong near-match — use "
        "that to disambiguate surname collisions and to confirm non-existence. "
        "Require co-occurrence with `(^ ...)`; widen with `(+ ...)`. "
        + _GCL_GUIDE +
        " Results are ranked by shortest matching substring (tight matches win); "
        "each carries a docno and a match-centered snippet. Cite by docno."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A GCL Boolean query. Prefer `(^ ...)` to require "
                    "co-occurrence and `\"...\"` for phrases. Example: "
                    "`(^ (+ rmit \"information retrieval\") sanderson)`."
                ),
            },
            "k": {
                "type": "integer",
                "description": "Number of ranked results to return (default 10).",
                "default": 10,
            },
        },
        "required": ["query"],
    },
}


def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urlopen_with_backoff(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_search_boolean_tool(query: str, k: int = 10, max_chars: int | None = 500,
                            *, url: str | None = None, timeout: float = 60.0,
                            **kwargs: Any) -> str:
    """Execute the Boolean tool; return a JSON string for a tool result.

    Each result is ``{rank, docid, snippet}`` (snippet truncated to
    ``max_chars``; pass ``None`` to keep the full match-centered window).
    Errors return ``{"error": "..."}`` rather than raising.
    """
    base = (url or os.environ.get("SSR_SEARCH_URL", DEFAULT_SSR_URL)).rstrip("/")
    try:
        data = _post(f"{base}/search", {"query": query, "k": k}, timeout)
    except Exception as e:  # noqa: BLE001  — surface as tool output
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

    results = []
    for h in data.get("results", []):
        snip = h.get("snippet") or ""
        results.append({
            "rank": h["rank"],
            "docid": h["docno"],
            "snippet": snip if max_chars is None else snip[:max_chars],
        })
    return json.dumps({"query": query, "k": k, "results": results},
                      ensure_ascii=False)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Boolean (GCL/SSR) search tool")
    ap.add_argument("query", nargs="+")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--max-chars", type=int, default=400)
    ap.add_argument("--url", default=None)
    args = ap.parse_args()
    out = run_search_boolean_tool(" ".join(args.query), k=args.k,
                                  max_chars=args.max_chars, url=args.url)
    print(json.dumps(json.loads(out), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
