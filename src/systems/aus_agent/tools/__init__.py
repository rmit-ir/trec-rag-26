"""AUS-specific tool definitions and local handlers."""

from .commit_context import (
    COMMIT_CONTEXT_TOOL,
    CommitHandlerResult,
    apply_commit,
    expire_staged,
)
from .search import (
    DEFAULT_BUDGET_TOKENS_PER_RESULT,
    SEARCH_TOOL_DEF,
    SearchExecution,
    build_search_tool_def,
    documents_from_search,
    execute_full_text_search,
    truncate_result_text,
)

__all__ = [
    "COMMIT_CONTEXT_TOOL",
    "CommitHandlerResult",
    "DEFAULT_BUDGET_TOKENS_PER_RESULT",
    "SEARCH_TOOL_DEF",
    "SearchExecution",
    "apply_commit",
    "build_search_tool_def",
    "documents_from_search",
    "execute_full_text_search",
    "expire_staged",
    "truncate_result_text",
]
