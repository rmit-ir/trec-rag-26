"""AUS-specific tool definitions and local handlers."""

from .commit_context import (
    COMMIT_CONTEXT_TOOL,
    CommitHandlerResult,
    apply_commit,
    expire_staged,
)
from .get_documents import (
    GET_DOCUMENTS_TOOL,
    execute_get_documents,
)
from .judge import (
    DEFAULT_JUDGE_BACKEND,
    DEFAULT_JUDGE_MODEL,
    JUDGE_RELEVANCE_TOOL,
    execute_judge_relevance,
    judge_documents,
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
from .snippet import (
    DEFAULT_SNIPPET_BACKEND,
    DEFAULT_SNIPPET_MAX_CHARS,
    DEFAULT_SNIPPET_MODEL,
    generate_snippets,
)

__all__ = [
    "COMMIT_CONTEXT_TOOL",
    "CommitHandlerResult",
    "DEFAULT_BUDGET_TOKENS_PER_RESULT",
    "DEFAULT_JUDGE_BACKEND",
    "DEFAULT_JUDGE_MODEL",
    "DEFAULT_SNIPPET_BACKEND",
    "DEFAULT_SNIPPET_MAX_CHARS",
    "DEFAULT_SNIPPET_MODEL",
    "GET_DOCUMENTS_TOOL",
    "JUDGE_RELEVANCE_TOOL",
    "SEARCH_TOOL_DEF",
    "SearchExecution",
    "apply_commit",
    "build_search_tool_def",
    "documents_from_search",
    "execute_full_text_search",
    "execute_get_documents",
    "execute_judge_relevance",
    "expire_staged",
    "generate_snippets",
    "judge_documents",
    "truncate_result_text",
]
