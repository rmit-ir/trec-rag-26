"""Agent tool wrapper around hybrid retrieval.

Exposes a single ``search`` tool that an LLM agent can call to retrieve passages
from the ClimbMix corpus. It runs dense + sparse retrieval and RRF-fuses them
(see ``utils.search``), returning compact JSON the model can cite.

Usage as a tool:
    from tools.search_tool import SEARCH_TOOL, run_search_tool
    # SEARCH_TOOL -> Anthropic-style tool definition (name/description/input_schema)
    # run_search_tool(**tool_input) -> JSON string to hand back as the tool result

Usage as a CLI:
    python src/tools/search_tool.py "influenza vaccination" --k 5
"""
from __future__ import annotations

import json
from typing import Any

from utils.search import search
from utils.search_dense import search_dense
from utils.search_sparse import search_sparse

SEARCH_ENGINES = ("semantic", "keyword", "fusion")

# Anthropic / OpenAI-compatible tool definition.
SEARCH_TOOL: dict[str, Any] = {
    "name": "search",
    "description": (
        "Search the ClimbMix corpus for passages relevant to a query. "
        "search_engine selects dense (semantic, default), sparse (BM25), or "
        "reciprocal-rank fusion of both. Returns ranked passages with their "
        "docid and text; cite results by docid."
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
            "search_engine": {
                "type": "string",
                "enum": list(SEARCH_ENGINES),
                "default": "semantic",
                "description": (
                    "Retrieval engine. semantic (default, dense embedding "
                    "match): concepts, definitions, paraphrase, ambiguous "
                    "common words, natural-question phrasing. keyword "
                    "(exact BM25 match): exact names, codes, and rare "
                    "technical strings — supply the full distinctive term, "
                    "never a bare ambiguous name. fusion (reciprocal-rank "
                    "fusion of both): most robust choice, strongest on "
                    "compact distinctive-term queries; prefer it when a "
                    "query mixes a proper name with conceptual words."
                ),
            },
        },
        "required": ["query"],
    },
}


def run_search_tool(query: str, k: int = 10, max_chars: int | None = 500,
                    search_engine: str = "semantic",
                    **kwargs: Any) -> str:
    """Execute the tool and return a JSON string of results (for a tool result).

    ``search_engine`` picks the backend: ``semantic`` (default, dense only),
    ``keyword`` (BM25 only), or ``fusion`` (dense+sparse RRF). Each result is ``{rank, id, docid, kind, rrf_score, text}``; the
    ``rrf_score`` key name is kept stable for downstream consumers and holds
    the RRF score for fusion, or the engine's native score (inner-product /
    BM25) for a single engine. Text is truncated to ``max_chars``; pass
    ``None`` to preserve the complete text returned by the search backend.
    Errors are returned as ``{"error": "..."}`` rather than raised so the agent
    can react instead of crashing.
    """
    if search_engine not in SEARCH_ENGINES:
        return json.dumps({"error": (
            f"unknown search_engine: {search_engine!r} "
            f"(expected one of {list(SEARCH_ENGINES)})")})
    try:
        if search_engine == "semantic":
            hits = search_dense(query, k, **kwargs)
        elif search_engine == "keyword":
            hits = search_sparse(query, k, **kwargs)
        else:
            hits = search(query, k=k, **kwargs)
    except Exception as e:  # surface as tool output, not an exception
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

    results = []
    for h in hits:
        text = h.get("text") or ""
        results.append({
            "rank": h["rank"],
            "id": h["id"],
            "docid": h["docid"],
            "kind": h["kind"],
            "rrf_score": round(h["score"], 6),
            "text": text if max_chars is None else text[:max_chars],
        })
    return json.dumps({"query": query, "k": k, "results": results},
                      ensure_ascii=False)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Hybrid search tool")
    ap.add_argument("query", nargs="+")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--max-chars", type=int, default=300)
    ap.add_argument("--engine", choices=SEARCH_ENGINES,
                    default="semantic")
    args = ap.parse_args()

    out = run_search_tool(" ".join(args.query), k=args.k,
                          max_chars=args.max_chars,
                          search_engine=args.engine)
    print(json.dumps(json.loads(out), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
