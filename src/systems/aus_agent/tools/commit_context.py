"""Definition and focused handler for the local commit_context control."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..context import CommitDecision, ContextLedger

COMMIT_CONTEXT_TOOL: dict[str, Any] = {
    "name": "commit_context",
    "description": (
        "Select the small subset of documents from the MOST RECENT staged "
        "search batch whose full text should persist. This MUST be the first "
        "control action on the immediately following model turn. Every staged "
        "occurrence not listed is compacted before the next turn. Do not select "
        "a docid that is already committed, or a semantically redundant "
        "document supporting the same claim, unless it adds materially "
        "different evidence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "documents": {
                "type": "array",
                "description": (
                    "Evidence-worthy staged documents to retain. An empty "
                    "array explicitly rejects the whole staged batch."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "docid": {"type": "string"},
                        "reason": {
                            "type": "string",
                            "description": (
                                "The distinct evidence, claim, perspective, "
                                "date, name, counterevidence, or coverage area "
                                "this document uniquely contributes."
                            ),
                        },
                    },
                    "required": ["docid", "reason"],
                },
            },
        },
        "required": ["documents"],
    },
}


@dataclass
class CommitHandlerResult:
    decision: CommitDecision
    payload: dict[str, Any]


def apply_commit(
    ledger: ContextLedger,
    arguments: dict[str, Any],
    *,
    max_documents: int,
    finishing: bool,
) -> CommitHandlerResult:
    raw_documents = arguments.get("documents", [])
    if not isinstance(raw_documents, list):
        raise ValueError("documents must be an array")
    selected = [item for item in raw_documents if isinstance(item, dict)]
    decision = ledger.commit(selected, max_documents=max_documents)
    payload: dict[str, Any] = {
        "committed": decision.committed,
        "rejected": decision.rejected,
    }
    if finishing:
        payload["instruction"] = (
            "Research budget is exhausted; emit the final JSON using the "
            "schema already defined in the system prompt and only committed "
            "evidence."
        )
    return CommitHandlerResult(decision=decision, payload=payload)


def expire_staged(
    ledger: ContextLedger,
    *,
    max_documents: int,
    reason: str,
) -> CommitDecision:
    return ledger.commit(
        [],
        max_documents=max_documents,
        unselected_reason=reason,
    )
