"""``commit_release`` factor (factorial taxonomy S12): an isolated
``commit_context`` schema variant that adds ONLY the ``release`` property
on top of the shared ``agent_harness`` default -- no ``coverage``/
``ready_to_report`` ledger (that's facets_agent's own bundled addition,
a different factor; importing facets_agent's ``COMMIT_CONTEXT_TOOL``
wholesale would conflate the two). The harness's own
``agent_harness.tools.commit_context.apply_commit`` already handles a
``release`` argument whenever the call carries one, regardless of which
tool schema advertised it -- this module only needs to advertise the
field, not implement its handling.
"""
from __future__ import annotations

from typing import Any

from agent_harness.tools.commit_context import COMMIT_CONTEXT_TOOL as _BASE

_RELEASE_PROPERTY: dict[str, Any] = {
    "release": {
        "type": "array",
        "description": (
            "Previously committed ids to drop because a document you are "
            "committing in THIS SAME call supersedes them -- same fact, "
            "more precise, better-sourced, or more complete. Only ids "
            "already committed may be listed here."
        ),
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string",
                      "description": "An already-committed id, exactly as committed."},
                "reason": {"type": "string",
                          "description": "What supersedes it."},
            },
            "required": ["id", "reason"],
        },
    },
}

COMMIT_CONTEXT_TOOL_WITH_RELEASE: dict[str, Any] = {
    **_BASE,
    "description": _BASE["description"] + (
        " Optionally also pass `release`: ids already committed that a "
        "document committed in this same call now supersedes."
    ),
    "input_schema": {
        **_BASE["input_schema"],
        "properties": {
            **_BASE["input_schema"]["properties"],
            **_RELEASE_PROPERTY,
        },
    },
}
