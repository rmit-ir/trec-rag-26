"""facets_agent's own ``commit_context`` tool definition.

Extends aus_agent's ``COMMIT_CONTEXT_TOOL`` with an optional ``release``
property: a facet's committed evidence should stay MINIMAL, so when a better
document is found for something already committed, the agent names the
superseded id here instead of leaving both in context forever. The handling
logic (``aus_agent.tools.commit_context.apply_commit`` ->
``aus_agent.context.ContextLedger.release_committed``) is shared and already
reads a ``release`` argument whenever a call carries one, regardless of which
tool definition advertised the field — this module only adds the schema that
tells the model the field exists and what it is for. aus_agent's own tool
definition is untouched, so this is purely additive to what THIS system's
model sees.
"""
from __future__ import annotations

from typing import Any

from aus_agent.tools.commit_context import COMMIT_CONTEXT_TOOL as _BASE_TOOL

_RELEASE_PROPERTY: dict[str, Any] = {
    "release": {
        "type": "array",
        "description": (
            "Previously committed ids to drop because a document you are "
            "committing in THIS SAME call supersedes them — same fact, more "
            "precise, better-sourced, or more complete. Each facet should "
            "end up with the minimal set of documents that actually cover "
            "it, not every document that was ever useful; when a better one "
            "arrives, release the one it replaces rather than keeping both. "
            "Only ids already committed may be listed here — never a "
            "currently staged id (list those in `documents` instead)."
        ),
        "items": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "An already-committed id, exactly as committed.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "What specifically supersedes it — name the newly "
                        "committed id and what it has that this one lacked."
                    ),
                },
            },
            "required": ["id", "reason"],
        },
    },
}

COMMIT_CONTEXT_TOOL: dict[str, Any] = {
    **_BASE_TOOL,
    "description": (
        _BASE_TOOL["description"] + " Optionally also pass `release`: ids "
        "already committed that a document committed in this same call now "
        "supersedes, so each facet's evidence stays the minimal set that "
        "covers it rather than accumulating every document that was ever "
        "useful."
    ),
    "input_schema": {
        **_BASE_TOOL["input_schema"],
        "properties": {
            **_BASE_TOOL["input_schema"]["properties"],
            **_RELEASE_PROPERTY,
        },
    },
}

__all__ = ["COMMIT_CONTEXT_TOOL"]
