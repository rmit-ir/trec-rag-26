"""Agent tool wrapper around hybrid retrieval.

Exposes a single ``search`` tool that an LLM agent can call to retrieve passages
from the ClimbMix corpus. It runs dense + sparse retrieval and RRF-fuses them
(see ``src.utils.search``), returning compact JSON the model can cite.

Usage as a tool:
    from src.tools.search_tool import SEARCH_TOOL, run_search_tool
    # SEARCH_TOOL -> Anthropic-style tool definition (name/description/input_schema)
    # run_search_tool(**tool_input) -> JSON string to hand back as the tool result

Usage as a CLI:
    python src/tools/search_tool.py "influenza vaccination" --k 5 --prf rm3
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# Allow running as a script (`python src/tools/search_tool.py ...`) from the repo
# root by putting the repo root (which contains the `src` package) on sys.path
# before importing it. Harmless when imported as `src.tools.search_tool`.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.utils.search import search

# Anthropic / OpenAI-compatible tool definition.
SEARCH_TOOL: dict[str, Any] = {
    "name": "search",
    "description": (
        "Search the ClimbMix corpus for passages relevant to a query. Combines "
        "dense (semantic) and sparse (BM25) retrieval with reciprocal-rank "
        "fusion. Returns ranked passages with their docid and text; cite results "
        "by docid."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "k": {
                "type": "integer",
                "description": "Number of fused passages to return (default 10).",
                "default": 10,
            },
        },
        "required": ["query"],
    },
}


def run_search_tool(query: str, k: int = 10, max_chars: int = 500,
                    **kwargs: Any) -> str:
    """Execute the tool and return a JSON string of results (for a tool result).

    Each result: ``{rank, docid, rrf_score, text}`` with text truncated to
    ``max_chars``. Errors are returned as ``{"error": "..."}`` rather than raised
    so the agent can react instead of crashing.
    """
    try:
        hits = search(query, k=k, **kwargs)
    except Exception as e:  # surface as tool output, not an exception
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

    results = []
    for h in hits:
        text = h.get("text") or ""
        results.append({
            "rank": h["rank"],
            "docid": h["docid"],
            "rrf_score": round(h["score"], 6),
            "text": text[:max_chars],
        })
    return json.dumps({"query": query, "k": k, "results": results},
                      ensure_ascii=False)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Hybrid search tool")
    ap.add_argument("query", nargs="+")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--max-chars", type=int, default=300)
    args = ap.parse_args()

    out = run_search_tool(" ".join(args.query), k=args.k,
                          max_chars=args.max_chars)
    print(json.dumps(json.loads(out), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
