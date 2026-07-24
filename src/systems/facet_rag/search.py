"""Facet execution — run one ClimbMix search per planned facet.

Thin adapter over the shared ``tools.search_tool`` backend: retrieval logic is
never duplicated here. Each facet is executed on its own engine; results are
de-duplicated by docid across facets (first facet to surface a docid keeps it),
and the surviving passages are what the synthesis stage cites.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from tools.search_tool import run_search_tool

from .planner import Facet

# Passage text handed to the synthesis LLM is bounded so a wide fan-out of
# facets cannot blow the context window. Generous — full passages are ~500-2000
# chars; this keeps the long ones without letting an outlier dominate.
DEFAULT_MAX_CHARS = 2000


@dataclass
class FacetResult:
    facet: Facet
    output: str                       # raw JSON tool output (for the trace)
    passages: list[dict[str, Any]]    # {docid, text, score, engine} kept
    failed: bool = False
    error: str | None = None


@dataclass
class Retrieval:
    per_facet: list[FacetResult] = field(default_factory=list)
    # Ordered, de-duplicated passages across all facets (docid -> passage).
    passages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def docids(self) -> list[str]:
        return [p["docid"] for p in self.passages]


def execute_facet(facet: Facet, *, max_chars: int = DEFAULT_MAX_CHARS
                  ) -> FacetResult:
    """Run one facet's query on its engine; return kept passages + raw output."""
    output = run_search_tool(
        query=facet.query, k=facet.k, max_chars=max_chars,
        search_engine=facet.engine)
    data = json.loads(output)
    if "error" in data:
        return FacetResult(facet=facet, output=output, passages=[],
                           failed=True, error=str(data["error"]))
    passages = [{
        "docid": str(r["docid"]),
        "text": r.get("text") or "",
        "score": r.get("score"),
        "engine": facet.engine,
        "facet": facet.name,
    } for r in data.get("results", [])]
    return FacetResult(facet=facet, output=output, passages=passages)


def execute_plan(facets: list[Facet], *, max_chars: int = DEFAULT_MAX_CHARS
                 ) -> Retrieval:
    """Execute every facet and merge results, de-duplicating by docid."""
    retrieval = Retrieval()
    seen: set[str] = set()
    for facet in facets:
        result = execute_facet(facet, max_chars=max_chars)
        retrieval.per_facet.append(result)
        for passage in result.passages:
            if passage["docid"] in seen:
                continue
            seen.add(passage["docid"])
            retrieval.passages.append(passage)
    return retrieval


def format_passages_for_synthesis(passages: list[dict[str, Any]]) -> str:
    """Render kept passages as a numbered, docid-labelled block for the LLM."""
    if not passages:
        return "(no passages retrieved)"
    blocks = []
    for i, p in enumerate(passages, 1):
        blocks.append(f"[{i}] docid={p['docid']}\n{p['text']}")
    return "\n\n".join(blocks)
