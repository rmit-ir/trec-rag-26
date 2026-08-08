"""Agent tool wrapper around the ClimbMix retrieval backends.

Exposes a single ``search`` tool that an LLM agent can call to retrieve passages
from the ClimbMix corpus. Five engines are available, and a run can enable any
subset (see ``build_search_tool``) so each method's effectiveness can be tested
in isolation:

- ``semantic``     dense embedding match (Jina-v5 DiskANN)          — natural language
- ``keyword``      hosted BM25 bag-of-words OR (index-server)        — natural language
- ``hybrid``       dense+sparse fused with RRF (``utils.search.search``) — natural language
- ``ssr``          Cottontail Shortest-Substring Ranking, GCL Boolean — Boolean syntax
- ``lucene_bool``  full Lucene query-parser over the BM25 index       — Lucene syntax

``search_engine`` is required on every call for every build, single-engine
included — no schema default is advertised, so the backend that answered a
query is always the one the model named.

``hybrid`` is ``utils.search.search`` (dense+sparse RRF fusion) made
model-selectable like any other engine; a caller that owns its OWN composition
still runs it through ``run_search_backend`` directly instead of registering it
here.

Usage as a tool:
    from tools.search_tool import SEARCH_TOOL, build_search_tool, run_search_tool
    # SEARCH_TOOL           -> default (semantic+keyword) tool definition
    # build_search_tool([...]) -> tool definition restricted to the given engines
    # run_search_tool(**tool_input) -> JSON string to hand back as the tool result
    # run_search_backend(q, backend, engine=...) -> same envelope for a
    #   caller-owned composition not registered as a selectable engine

Usage as a CLI:
    python src/tools/search_tool.py "influenza vaccination" --k 5 --engine semantic
    python src/tools/search_tool.py "(^ influenza vaccine)" --engine ssr
"""
from __future__ import annotations

import json
from typing import Any, Callable

from utils.search import search as search_hybrid
from utils.search_dense import search_dense
from utils.search_lucene_bool import search_lucene_bool
from utils.search_sparse import search_sparse
from utils.search_ssr import search_ssr
from utils.search_types import SearchHit

# All engines, in a stable order. ``kind`` selects the query-writing guidance
# handed to the model; ``blurb`` is the one-line "when to use" for the tool
# description. The dispatch below maps each name to its backend client.
ENGINE_INFO: dict[str, dict[str, str]] = {
    "semantic": {
        "kind": "nl",
        "blurb": ("semantic (dense embedding match): conceptual, definitional, "
                  "or broad-topic needs and natural-question phrasing"),
    },
    "keyword": {
        "kind": "nl",
        "blurb": ("keyword (hosted BM25, bag-of-words OR — operators are "
                  "ignored): rare proper names, IDs, and verbatim strings; "
                  "any query term may match, none is required"),
    },
    "hybrid": {
        "kind": "nl",
        "blurb": ("hybrid (dense+sparse fused with Reciprocal Rank Fusion): "
                  "the safe general-purpose default — combines semantic's "
                  "conceptual recall with keyword's exact-term precision, at "
                  "roughly 2x the cost of a single-engine call"),
    },
    "ssr": {
        "kind": "gcl",
        "blurb": ("ssr (Cottontail Shortest-Substring Ranking, GCL Boolean): "
                  "precise co-occurrence and phrases with REQUIRED terms; a "
                  "required-but-absent term returns an empty set (a truthful "
                  "zero) instead of a wrong near-match"),
    },
    "lucene_bool": {
        "kind": "lucene",
        "blurb": ("lucene_bool (full Lucene query-parser over the BM25 index): "
                  "Boolean AND/OR, required (+) / excluded (-) terms, phrases, "
                  "and proximity — BM25-ranked"),
    },
}
SEARCH_ENGINES = tuple(ENGINE_INFO)

# ---------------------------------------------------------------------------
# Query-writing guidance, selected by the enabled engines' ``kind``.
# ---------------------------------------------------------------------------
_NL_GUIDANCE = (
    "Write the query as a short, specific phrase: a few distinctive content "
    "words (names, technical terms, the core concept) or a natural question "
    "phrased like a webpage title or FAQ. Include at least one rare or specific "
    "term — never a single common word — and attach one disambiguating "
    "qualifier to any proper name. Omit audience, format, and task words, and "
    "query a single facet at a time. For semantic, phrase naturally; for "
    "keyword, use bare distinctive terms without stopwords."
)

# Baked from measured SSR probes AND a 10-topic agentic sweep on the full corpus
# (see the ssr_search worklog + data/outputs/engine-comparison). The arity cap
# and the drop-on-zero rule are the sweep's key corrections: agents that stacked
# 5-7 required terms hit empty sets on 7/10 topics (11 zeros/19 searches on one).
_GCL_GUIDANCE = (
    "Write a GCL Boolean query, NOT natural language. Operators: "
    "`(^ a b ...)` = AND (ALL terms must co-occur in one document); "
    "`(+ a b ...)` = OR (any); `\"a b\"` = exact phrase (adjacent, in order); "
    "`(<< (^ a b) (# k))` = a AND b within k tokens (proximity, k~15-60); "
    "`(>> A B)` / `(<< A B)` = A contains / is-contained-in B. Terms are "
    "Porter-stemmed and case-insensitive — use ONE form (reactor matches "
    "reactors; russia matches Russia). RULES that maximise SSR: "
    "(1) Keep ANDs SHORT: at most 3 required terms. More terms do NOT add "
    "precision — they shrink the match set and usually return ZERO. Lead with "
    "the single rarest / most-distinctive term (a proper name, technical term, "
    "or term-of-art). "
    "(2) On an empty result, DROP the weakest (most common) term and retry — "
    "NEVER add another required term (adding only shrinks it further). If a "
    "2-3 term AND is still empty, the terms genuinely don't co-occur: switch a "
    "term or move on; do not keep piling on qualifiers. "
    "(3) One `(^ ...)` per facet — decompose a multi-part need into several "
    "short queries rather than one long AND. "
    "(4) Disambiguate a polysemous word by AND-ing ONE context term: "
    "`(^ \"de minimis\" tariff)` not bare `\"de minimis\"`; "
    "`(^ smr \"nuclear reactor\")` not bare `smr`. "
    "(5) Quote multiword names/terms-of-art, but pair a phrase with a term (a "
    "bare phrase pulls patents/boilerplate). "
    "(6) To widen WITHOUT lengthening the AND, put an OR inside it — keep one "
    "anchor required and widen the other facet: "
    "`(^ uranium (+ enrichment conversion fabrication))`. "
    "SSR is a precision/co-occurrence instrument: use it to pin exact entities, "
    "confirm co-mention, or get a truthful zero — not to bag-of-AND a broad "
    "topic (widen with the `keyword`/`semantic` engines for open-ended recall)."
)

_LUCENE_GUIDANCE = (
    "Write a Lucene query-parser query. The default operator is OR, so REQUIRE "
    "terms with `+`: `+uranium +enrichment +russia` (all three required). "
    "Operators: `+term` required, `-term` excluded, `\"exact phrase\"`, "
    "`\"a b\"~N` = a and b within N tokens (proximity), `term*` prefix "
    "wildcard, `( )` grouping, and `AND`/`OR`/`NOT`. The field is the document "
    "body by default. Terms are English-analysed (Porter-stemmed, lowercased) "
    "— one form suffices. TACTICS: require 2-4 distinctive terms with `+`; "
    "quote multiword names; disambiguate a polysemous term by REQUIRING a "
    "context term (`+\"de minimis\" +tariff`); use `\"a b\"~N` when two terms "
    "must be near each other."
)

_GUIDANCE_BY_KIND = {"nl": _NL_GUIDANCE, "gcl": _GCL_GUIDANCE,
                     "lucene": _LUCENE_GUIDANCE}


def _query_guidance(engines: list[str]) -> str:
    """Query-writing guidance covering exactly the enabled engines' kinds."""
    kinds: list[str] = []
    for e in engines:
        kind = ENGINE_INFO[e]["kind"]
        if kind not in kinds:
            kinds.append(kind)
    if len(kinds) == 1:
        return _GUIDANCE_BY_KIND[kinds[0]]
    # Mixed kinds: the query language depends on search_engine — spell out each.
    label = {"nl": "for semantic/keyword", "gcl": "for ssr",
             "lucene": "for lucene_bool"}
    return " ".join(f"[{label[k]}] {_GUIDANCE_BY_KIND[k]}" for k in kinds)


def build_search_tool(engines: list[str] | tuple[str, ...] | None = None
                      ) -> dict[str, Any]:
    """Build a ``search`` tool definition enabling exactly ``engines``.

    The ``search_engine`` enum, the "when to use" description, and the
    query-writing guidance are all derived from the enabled set, so a
    single-engine run yields a tool cleanly specialised to that engine (used to
    test each method's effectiveness in isolation). ``search_engine`` is
    ALWAYS required — including on a single-engine build — so every search in
    a trajectory records the backend it was written for, and no call can be
    routed by an implicit default.
    """
    engines = list(engines) if engines else ["semantic", "keyword"]
    unknown = [e for e in engines if e not in ENGINE_INFO]
    if unknown:
        raise ValueError(f"unknown engine(s): {unknown} "
                         f"(known: {list(ENGINE_INFO)})")
    blurbs = " | ".join(ENGINE_INFO[e]["blurb"] for e in engines)
    multi = len(engines) > 1
    engine_prop = {
        "type": "string",
        "enum": engines,
        "description": ("Retrieval engine — REQUIRED on every call, name it "
                        "explicitly. " + blurbs
                        + (". The engines rank differently — cover an important "
                           "facet with more than one." if multi else ".")),
    }
    props: dict[str, Any] = {
        "query": {"type": "string", "description": _query_guidance(engines)},
        "k": {"type": "integer", "default": 10,
              "description": "Number of passages to return (default 10)."},
        "search_engine": engine_prop,
    }
    required = ["query", "search_engine"]
    desc = ("Search the ClimbMix corpus for passages relevant to a query. "
            "Returns ranked passages, each with its `id` (a page/chunk id like "
            "`shard_x_p2` when paginated) and text; commit and cite by that `id` "
            "exactly as returned. search_engine selects: " + blurbs + ".")
    return {"name": "search", "description": desc,
            "input_schema": {"type": "object", "properties": props,
                             "required": required}}


# Default definition (semantic + keyword) for back-compat with existing imports.
SEARCH_TOOL: dict[str, Any] = build_search_tool(["semantic", "keyword"])

_DISPATCH = {
    "semantic": lambda q, k, **kw: search_dense(q, k, **kw),
    "keyword": lambda q, k, **kw: search_sparse(q, k, **kw),
    "hybrid": lambda q, k, **kw: search_hybrid(q, k, **kw),
    "ssr": lambda q, k, **kw: search_ssr(q, k, **kw),
    "lucene_bool": lambda q, k, **kw: search_lucene_bool(q, k, **kw),
}


def run_search_backend(
    query: str,
    backend: Callable[..., list[SearchHit]],
    *,
    engine: str,
    k: int = 10,
    max_chars: int | None = 500,
    **kwargs: Any,
) -> str:
    """Run one selected backend through the standard agent-tool envelope.

    Callers that own a retrieval composition, such as dense+sparse RRF, pass
    that shared composition here without adding it to the model-selectable
    ``ENGINE_INFO``/``_DISPATCH`` table. This keeps serialization, truncation,
    and agent-visible error handling identical to the single-engine tool path.
    """
    try:
        hits = backend(query, k=k, **kwargs)
    except Exception as exc:  # surface as tool output, not an exception
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    results = []
    for hit in hits:
        result_text = hit.get("text") or ""
        results.append({
            "rank": hit["rank"],
            "id": hit["id"],
            "docid": hit["docid"],
            "kind": hit["kind"],
            "score": round(hit["score"], 6),
            "text": (result_text if max_chars is None
                     else result_text[:max_chars]),
        })
    return json.dumps({"query": query, "k": k, "engine": engine,
                       "results": results}, ensure_ascii=False)


def run_search_tool(query: str, k: int = 10, max_chars: int | None = 500,
                    search_engine: str = "semantic",
                    **kwargs: Any) -> str:
    """Execute the tool and return a JSON string of results (for a tool result).

    ``search_engine`` picks the backend (see ``ENGINE_INFO``). Each result is
    ``{rank, id, docid, kind, score, text}``; ``score`` is the engine's native
    score (inner-product / BM25 / rank-synthetic for SSR), so scores are not
    comparable across engines. Text is truncated to ``max_chars`` (pass ``None``
    to keep the full text). Errors are returned as ``{"error": "..."}`` rather
    than raised so the agent can react instead of crashing.
    """
    if search_engine not in _DISPATCH:
        return json.dumps({"error": (
            f"unknown search_engine: {search_engine!r} "
            f"(expected one of {list(_DISPATCH)})")})
    return run_search_backend(
        query,
        _DISPATCH[search_engine],
        engine=search_engine,
        k=k,
        max_chars=max_chars,
        **kwargs,
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="ClimbMix search tool")
    ap.add_argument("query", nargs="+")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--max-chars", type=int, default=300)
    ap.add_argument("--engine", choices=SEARCH_ENGINES, default="semantic")
    args = ap.parse_args()

    out = run_search_tool(" ".join(args.query), k=args.k,
                          max_chars=args.max_chars,
                          search_engine=args.engine)
    print(json.dumps(json.loads(out), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
