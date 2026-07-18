"""AUS full-text adapter over the shared search-tool backend."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tools.search_tool import SEARCH_TOOL, run_search_tool

DEFAULT_BUDGET_TOKENS_PER_RESULT = 4096
CHARS_PER_TOKEN_BUDGET = 5

SEARCH_TOOL_DEF = {
    **SEARCH_TOOL,
    "description": (
        "Search the available evidence corpus. Results contain ranked document "
        "IDs and document text; inspect that text directly and cite by docid. "
        "Each result is bounded independently before it is staged. Match "
        "query style to engine: exact names and rare strings favor keyword; "
        "concepts and questions favor semantic. The engines rank differently, "
        "and extra queries are cheap — cover an important facet with both "
        "engines, one styled query each."
    ),
    "input_schema": {
        **SEARCH_TOOL["input_schema"],
        # Engine choice is deliberately required here: without a fused
        # fallback, every query must be styled for the engine it targets.
        "required": ["query", "search_engine"],
        "properties": {
            **SEARCH_TOOL["input_schema"]["properties"],
            "query": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "One information need as a short, specific phrase: a few "
                    "distinctive content words (names, technical terms, the "
                    "core concept) or a natural question phrased like a "
                    "webpage title or FAQ. Include at least one rare or "
                    "specific term — never a single common word — and attach "
                    "one disambiguating qualifier to any proper name. Omit "
                    "audience, format, and task words from the request and "
                    "query a single facet at a time. For numeric or "
                    "statistical facts, query the topic and entity, not the "
                    "number."
                ),
            },
            "budget_tokens_per_result": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Maximum approximate tokens staged per result. Text is "
                    "bounded at tokens × 5 characters and cut at the final "
                    "line break before that boundary. Default 4096."
                ),
                "default": DEFAULT_BUDGET_TOKENS_PER_RESULT,
            },
        },
    },
}

CONTEXT_PROTOCOL = (
    "STAGED FOR THE IMMEDIATELY FOLLOWING TURN ONLY: commit_context must be "
    "exactly the first action on that turn. Select only sparse non-duplicate "
    "documents whose full text should persist, with a reason naming each "
    "document's distinct evidence. Every unselected occurrence will be "
    "compacted before the next turn."
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
) -> SearchExecution:
    """Retrieve full hits, then independently bound each staged result."""
    query = str(arguments.get("query", ""))
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
    # Forward search_engine only when the model supplied it, so the backend's
    # default (semantic) stays the single source of truth.
    engine_kwargs: dict[str, Any] = {}
    if "search_engine" in arguments:
        engine_kwargs["search_engine"] = str(arguments["search_engine"])
    output = run_search_tool(
        query=query,
        k=int(arguments.get("k", default_k)),
        max_chars=None,
        **engine_kwargs,
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
