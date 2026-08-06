"""Definition and focused handler for the local commit_context control."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..context import CommitDecision, ContextLedger

COMMIT_CONTEXT_TOOL: dict[str, Any] = {
    "name": "commit_context",
    "description": (
        "Select the small subset of results from the MOST RECENT staged batch "
        "(search or get_documents) whose full text should persist. Call it on "
        "the immediately following model turn, in any position among that "
        "turn's actions. Every staged occurrence not listed is compacted "
        "before the next turn. Pass each result's `id` EXACTLY as it was "
        "returned (a chunk id like `shard_00042_1337_p3` when the backend is "
        "paginated — do not strip the `_p<page>` suffix). Distinct pages of "
        "one document are distinct units: commit each page you actually need. "
        "Never select an id already committed. "
        "ADJUDICATE, DO NOT DE-DUPLICATE. A batch routinely holds several "
        "results bearing on one claim, especially when a lead was searched on "
        "more than one engine — that is the batch working as intended, not "
        "redundancy to discard. Compare them and keep the complementary ones "
        "where each carries evidence the others do not, or the single best one "
        "where they genuinely say the same thing. Better means: states the "
        "concrete figure, date, or named finding rather than describing it "
        "categorically; gives the worked example rather than the "
        "generalisation; is the primary or better-sourced account rather than "
        "a report of it; and, between two results making the same point, says "
        "it more precisely. A result is rejected because another one beat it "
        "on those grounds, never because it looked similar."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "documents": {
                "type": "array",
                "description": (
                    "Evidence-worthy staged results to retain. An empty "
                    "array explicitly rejects the whole staged batch."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": (
                                "The result's id exactly as returned (chunk id "
                                "with any `_p<page>` suffix); never edited."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": (
                                "The distinct evidence, claim, perspective, "
                                "date, name, counter-evidence, or coverage area "
                                "this result uniquely contributes. Where it was "
                                "kept over a competing result in the same "
                                "batch, name the specific thing it has that "
                                "the other did not — the figure, the example, "
                                "the primary account, the sharper statement."
                            ),
                        },
                        "facts": {
                            "type": "array",
                            "description": (
                                "The specific, checkable things this document "
                                "STATES, extracted now while its full text is "
                                "in front of you. One entry per fact. Copy the "
                                "value as the document gives it — do not round, "
                                "summarise, or convert. This is what you will "
                                "write from later: by the time you draft the "
                                "report the document may be many turns back, "
                                "and a fact you did not record here is one you "
                                "will paraphrase away. Extract only what the "
                                "document actually says; never infer a value it "
                                "does not state. Omit entirely for a document "
                                "kept for its argument or perspective rather "
                                "than for any specific it contains."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "claim": {
                                        "type": "string",
                                        "description": (
                                            "What the document asserts, in one "
                                            "short clause."
                                        ),
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": (
                                            "A VERBATIM SPAN COPIED FROM THE "
                                            "DOCUMENT — a figure, date, rate, "
                                            "amount, threshold, proper name, or "
                                            "a short quoted clause. Copy the "
                                            "characters, do not describe them: "
                                            "'22,700 to 25,000', '34%', "
                                            "'the EU AI Act', 'Hebb, 1949', "
                                            "'median 4.2 months'. If you find "
                                            "yourself writing a summary such as "
                                            "'time is a limiting factor' or "
                                            "'several techniques are used', "
                                            "there is no value here — leave the "
                                            "fact out entirely rather than "
                                            "filling this field with prose. A "
                                            "fact with no verbatim span is not "
                                            "a fact worth recording."
                                        ),
                                    },
                                    "scope": {
                                        "type": "string",
                                        "description": (
                                            "The condition the value holds "
                                            "under — who, where, when, measured "
                                            "how. Omit only if the document "
                                            "states none."
                                        ),
                                    },
                                    "source": {
                                        "type": "string",
                                        "description": (
                                            "Who the document attributes it to, "
                                            "if anyone — the study, author, "
                                            "institution, dataset, or law. Most "
                                            "documents in this corpus name no "
                                            "source at all — omitting this is "
                                            "the normal case and costs nothing. "
                                            "Never invent one."
                                        ),
                                    },
                                },
                                "required": ["claim", "value"],
                            },
                        },
                    },
                    "required": ["id", "reason"],
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
            "Research budget is exhausted; write the final report now (plain "
            "prose, one sentence per line, [id] citation markers citing the "
            "exact committed ids) using only committed evidence."
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
