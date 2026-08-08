"""AUS full-text adapter over the shared search-tool backend."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tools.search_tool import (SEARCH_ENGINES, build_search_tool,
                               run_search_tool)

DEFAULT_BUDGET_TOKENS_PER_RESULT = 4096
CHARS_PER_TOKEN_BUDGET = 5

# The per-result staging budget is an AUS-specific control layered on top of the
# shared search tool; the query/engine guidance itself comes from
# ``build_search_tool`` so it always matches the enabled engines.
_BUDGET_PROP = {
    "budget_tokens_per_result": {
        "type": "integer",
        "minimum": 1,
        "description": (
            "Maximum approximate tokens staged per result. Text is bounded at "
            "tokens × 5 characters and cut at the final line break before that "
            "boundary. Default 4096."
        ),
        "default": DEFAULT_BUDGET_TOKENS_PER_RESULT,
    },
}


def build_search_tool_def(engines: list[str] | tuple[str, ...] | None = None
                          ) -> dict[str, Any]:
    """AUS ``search`` tool for exactly ``engines`` (see ``build_search_tool``).

    Adds the AUS-only ``budget_tokens_per_result`` control and the staging note
    to the engine-aware base tool. ``search_engine`` is always required — every
    query must be written for the backend it is sent to, so the model names
    that backend even when only one is enabled.
    """
    base = build_search_tool(engines)
    return {
        **base,
        "description": (
            base["description"] + " Each result is bounded independently "
            "before it is staged; extra queries are cheap — cover an important "
            "facet with more than one query."
        ),
        "input_schema": {
            **base["input_schema"],
            "properties": {**base["input_schema"]["properties"], **_BUDGET_PROP},
        },
    }


# Default definition (semantic + keyword) for back-compat with existing imports.
SEARCH_TOOL_DEF = build_search_tool_def(["semantic", "keyword"])

# The position claim this used to make ("exactly the first action") is not what
# the loop enforces — commits are applied before the turn's searches whatever
# order the model emitted them in (tests/agent_harness_context: "the commit's
# position within the turn does not matter"). Stating a rule the harness does
# not enforce trains the model against a phantom constraint, so the text now
# matches the behaviour: the turn is what matters, not the slot.
CONTEXT_PROTOCOL = (
    "STAGED FOR THE IMMEDIATELY FOLLOWING TURN ONLY: call commit_context on "
    "that turn, in any position among its actions. Select only sparse "
    "non-duplicate documents whose full text should persist, with a reason "
    "naming each document's distinct evidence. Every unselected occurrence "
    "will be compacted before the next turn."
)


@dataclass
class SearchExecution:
    output: str
    trace_output: dict[str, Any]
    returned: list[dict[str, Any]] | None
    failed: bool
    documents: list[dict[str, Any]]


def documents_from_search(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "id": str(result.get("id", result["docid"])),
        "docid": str(result["docid"]),
        "kind": result.get("kind", "document"),
        "rank": result.get("rank"),
        "score": result.get("score"),
        "text": result.get("text"),
        "metadata": {
            "query": data.get("query"),
            "truncated": result.get("truncated", False),
            "original_chars": result.get("original_chars"),
            "returned_chars": result.get("returned_chars"),
            "budget_tokens_per_result":
                data.get("budget_tokens_per_result"),
        },
    } for result in data.get("results", [])]


def truncate_result_text(text: str, *, budget_tokens: int) -> tuple[str, bool]:
    """Bound one result at tokens×5 chars, preferring a line boundary."""
    if budget_tokens <= 0:
        raise ValueError("budget_tokens_per_result must be positive")
    boundary = budget_tokens * CHARS_PER_TOKEN_BUDGET
    if len(text) <= boundary:
        return text, False
    prefix = text[:boundary]
    line_break = prefix.rfind("\n")
    if line_break > 0:
        prefix = prefix[:line_break]
    return prefix, True


def execute_full_text_search(
    arguments: dict[str, Any],
    *,
    default_k: int,
    seen_docids: set[str],
    engines: list[str] | tuple[str, ...] | None = None,
) -> SearchExecution:
    """Retrieve full hits, then independently bound each staged result.

    ``search_engine`` is required on every call: the tool schema marks it
    required and an omitted engine comes back as an error envelope rather than
    silently routing to a default, so a trajectory never contains a search
    whose backend was chosen by the harness. ``engines`` is the run's enabled
    set, named in that error so the model can retry immediately.
    """
    query = str(arguments.get("query", ""))
    search_engine = str(arguments.get("search_engine") or "")
    if not search_engine:
        allowed = list(engines) if engines else list(SEARCH_ENGINES)
        message = ("search_engine is required on every search call: name one "
                   f"of {allowed} explicitly and write the query for it")
        return SearchExecution(
            json.dumps({"error": message}), {"error": message}, None, True, [])
    budget_tokens = int(arguments.get(
        "budget_tokens_per_result",
        DEFAULT_BUDGET_TOKENS_PER_RESULT,
    ))
    if budget_tokens <= 0:
        return SearchExecution(
            json.dumps({
                "error": "budget_tokens_per_result must be positive"
            }),
            {"error": "budget_tokens_per_result must be positive"},
            None,
            True,
            [],
        )
    output = run_search_tool(
        query=query,
        k=int(arguments.get("k", default_k)),
        max_chars=None,
        search_engine=search_engine,
    )
    data = json.loads(output)
    if "error" in data:
        return SearchExecution(output, data, None, True, [])

    for result in data.get("results", []):
        original = str(result.get("text") or "")
        bounded, truncated = truncate_result_text(
            original, budget_tokens=budget_tokens)
        result["text"] = bounded
        result["truncated"] = truncated
        result["original_chars"] = len(original)
        result["returned_chars"] = len(bounded)
    data["budget_tokens_per_result"] = budget_tokens
    data["context_protocol"] = CONTEXT_PROTOCOL
    output = json.dumps(data, ensure_ascii=False)
    trace_output = {
        **data,
        "results": [{
            key: result[key]
            for key in (
                "rank", "id", "docid", "kind", "score", "truncated",
                "original_chars", "returned_chars",
            )
            if key in result
        } for result in data["results"]],
    }
    returned = [{
        "docid": result["docid"],
        "score": result["score"],
    } for result in data["results"]]
    seen_docids.update(hit["docid"] for hit in returned)
    return SearchExecution(
        output=output,
        trace_output=trace_output,
        returned=returned,
        failed=False,
        documents=documents_from_search(data),
    )
