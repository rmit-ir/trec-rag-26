"""Agent tool wrapper around hybrid retrieval.

Exposes a single ``search`` tool that an LLM agent can call to retrieve passages
from the ClimbMix corpus via dense (semantic) or sparse (BM25 keyword)
retrieval, returning compact JSON the model can cite. There is deliberately no
fused option: the caller is the fusion layer — cover an important facet by
querying both engines with queries styled for each.

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

from utils.search_dense import search_dense
from utils.search_sparse import search_sparse

SEARCH_ENGINES = ("semantic", "keyword")

# Anthropic / OpenAI-compatible tool definition.
SEARCH_TOOL: dict[str, Any] = {
    "name": "search",
    "description": (
        "Search the ClimbMix corpus for passages relevant to a query. "
        "search_engine selects dense (semantic, default) or exact-keyword "
        "BM25 (keyword) retrieval. Returns ranked passages with their docid "
        "and text; cite results by docid."
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
                    "Retrieval engine. semantic (dense embedding match): "
                    "conceptual, definitional, or broad-topic queries, "
                    "natural-question phrasing, and well-known product or "
                    "concept names; style the query as a natural phrase or "
                    "question. keyword (exact BM25 match): rare proper "
                    "names, surnames, IDs, codes, and verbatim technical "
                    "strings, where semantic may drift to a similar-"
                    "sounding topic; style the query as bare distinctive "
                    "terms without stopwords. The engines rank differently "
                    "— cover an important facet with both, one styled query "
                    "each; duplicate results are deduplicated downstream."
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

    ``search_engine`` picks the backend: ``semantic`` (default, dense only)
    or ``keyword`` (BM25 only). Each result is ``{rank, id, docid, kind,
    score, text}``; ``score`` is the engine's native score (inner-product /
    BM25), so scores are not comparable across engines.
    Text is truncated to ``max_chars``; pass ``None`` to preserve the
    complete text returned by the search backend. Errors are returned as
    ``{"error": "..."}`` rather than raised so the agent can react instead of
    crashing.
    """
    if search_engine not in SEARCH_ENGINES:
        return json.dumps({"error": (
            f"unknown search_engine: {search_engine!r} "
            f"(expected one of {list(SEARCH_ENGINES)})")})
    try:
        if search_engine == "semantic":
            hits = search_dense(query, k, **kwargs)
        else:
            hits = search_sparse(query, k, **kwargs)
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
            "score": round(h["score"], 6),
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
