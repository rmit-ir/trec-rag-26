"""V2 search adapter that stages local page context automatically.

The base agent almost never chose ``get_documents`` even though retrieval hits
are page-sized units. V2 removes that decision: for the highest-ranked hits it
fetches the immediately preceding and following pages and returns them in the
same staged batch. The model still decides which individual pages to commit.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agent_harness.tools import get_documents as base_documents
from agent_harness.tools import search as base_search


DEFAULT_ADJACENT_HITS = 5
_PAGE_ID_RE = re.compile(r"^(?P<parent>.+)_p(?P<page>[1-9]\d*)$")


def build_search_tool_def(
    engines: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Describe the automatic page expansion without adding another knob."""
    tool = base_search.build_search_tool_def(engines)
    return {
        **tool,
        "description": (
            tool["description"]
            + " For the highest-ranked paginated hits, the harness also "
              "returns the immediately adjacent pages in the same staged "
              "batch; inspect and commit only the pages that contribute."
        ),
    }


# Concrete default exported for architecture inspection. Runtime calls still
# build from the run's selected engine list, so this constant is descriptive,
# not a hidden restriction on configurable retrieval.
SEARCH_TOOL_DEF = build_search_tool_def(["semantic", "keyword"])


def adjacent_page_ids(
    unit_ids: list[str], *, max_seed_hits: int = DEFAULT_ADJACENT_HITS,
) -> list[str]:
    """Return stable, deduplicated ±1 page ids absent from the hit list."""
    present = set(unit_ids)
    adjacent: list[str] = []
    seeds = 0
    for unit_id in unit_ids:
        match = _PAGE_ID_RE.match(unit_id)
        if match is None:
            continue
        seeds += 1
        if seeds > max_seed_hits:
            break
        parent = match.group("parent")
        page = int(match.group("page"))
        candidates = []
        if page > 1:
            candidates.append(f"{parent}_p{page - 1}")
        candidates.append(f"{parent}_p{page + 1}")
        for candidate in candidates:
            if (candidate not in present and candidate not in adjacent):
                adjacent.append(candidate)
    return adjacent


def execute_full_text_search(
    arguments: dict[str, Any],
    *,
    default_k: int,
    seen_docids: set[str],
    engines: list[str] | tuple[str, ...] | None = None,
) -> base_search.SearchExecution:
    """Run base retrieval, then merge adjacent pages into its staged batch."""
    execution = base_search.execute_full_text_search(
        arguments,
        default_k=default_k,
        seen_docids=seen_docids,
        engines=engines,
    )
    if execution.failed or not execution.documents:
        return execution

    requirement_ids = [
        str(value).strip()
        for value in arguments.get("for_requirements", [])
        if str(value).strip()
    ]
    if requirement_ids:
        routed_data = json.loads(execution.output)
        routed_data["for_requirements"] = requirement_ids
        for document in execution.documents:
            document.setdefault("metadata", {})[
                "for_requirements"] = list(requirement_ids)
        execution = base_search.SearchExecution(
            output=json.dumps(routed_data, ensure_ascii=False),
            trace_output={
                **execution.trace_output,
                "for_requirements": requirement_ids,
            },
            returned=execution.returned,
            failed=False,
            documents=execution.documents,
        )

    unit_ids = [str(document["id"]) for document in execution.documents]
    requested = adjacent_page_ids(unit_ids)
    if not requested:
        return execution
    _out, adjacent_documents, missing = base_documents.execute_get_documents(
        {"ids": requested})
    if not adjacent_documents and not missing:
        return execution

    data = json.loads(execution.output)
    existing_results = data.get("results", [])
    next_rank = len(existing_results) + 1
    adjacent_results: list[dict[str, Any]] = []
    for offset, document in enumerate(adjacent_documents):
        adjacent_results.append({
            "rank": next_rank + offset,
            "id": document["id"],
            "docid": document["docid"],
            "kind": document["kind"],
            "score": None,
            "text": document["text"],
            "adjacent": True,
        })
        document.setdefault("metadata", {}).update({
            "source": "automatic_adjacent_page",
            "query": data.get("query"),
            "for_requirements": list(requirement_ids),
        })
    data["results"] = existing_results + adjacent_results
    data["automatic_adjacent_pages"] = {
        "requested": requested,
        "returned": [document["id"] for document in adjacent_documents],
        "missing": missing,
        "seed_hits": min(DEFAULT_ADJACENT_HITS, len(unit_ids)),
    }
    data["context_protocol"] = base_search.CONTEXT_PROTOCOL
    output = json.dumps(data, ensure_ascii=False)
    trace_output = {
        **execution.trace_output,
        "automatic_adjacent_pages": data["automatic_adjacent_pages"],
        "results": execution.trace_output.get("results", []) + [{
            "rank": result["rank"],
            "id": result["id"],
            "docid": result["docid"],
            "kind": result["kind"],
            "score": None,
            "adjacent": True,
        } for result in adjacent_results],
    }
    return base_search.SearchExecution(
        output=output,
        trace_output=trace_output,
        returned=execution.returned,
        failed=False,
        documents=execution.documents + adjacent_documents,
    )
