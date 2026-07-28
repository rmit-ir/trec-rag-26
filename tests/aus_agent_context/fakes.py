"""Local doubles and payload builders the shared ``tests/conftest.py`` lacks.

Fixtures live next door in this directory's ``conftest.py``; this module holds
the plain helpers they and the test modules share. Three things it exists for,
all of them assertions the migrated suite would otherwise have to weaken:

1. **Disjoint per-query document sets.** The shared ``stub_search_tool`` answers
   every query with the same four ClimbMix docids, but the staged/committed
   protocol is only observable when two searches on one turn stage *different*
   documents — "keep ``b`` from alpha and ``d`` from beta, compact the rest" is
   the whole behaviour under test. ``DOC_SETS`` maps ``alpha``/``beta``/``gamma``
   onto disjoint triples.

2. **A read-side view of the compacted bytes.** ``StrictScriptedProvider`` adds
   ``content_by_id`` so an assertion can read what a tool result *became* after
   compaction. It used to add the strictness too — the real
   ``BedrockProvider.compact_tool_results`` raises ``KeyError`` on an id that is
   not in history and ``agent.run_agent`` treats that as fatal, while the shared
   mock ignored it — but that now lives in ``ScriptedProvider`` itself, since a
   lenient mock hides the divergence for every suite, not just this one.

3. **Turn builders with explicit token usage.** ``conftest.model_turn`` defaults
   to 100-in/50-out; the migrated integration assertions are exact about
   cumulative token arithmetic, so ``turn()`` wraps it with per-turn usage.

Docids are single letters (``a``..``i``) deliberately: every migrated assertion
about commit ordering reads as a table of them. Realistic ``shard_*`` ids are
covered by the shared ``CLIMBMIX_DOCIDS`` fixtures, plus the chunk-id test in
``test_ledger_core.py`` that pins ``committed_full_ids``.
"""
from __future__ import annotations

import json
from typing import Any

from conftest import ScriptedProvider, model_turn, tool_call

# Three disjoint result sets, one per scripted query. The old suite's letters,
# kept verbatim so its expected commit/reject orderings migrate unchanged.
DOC_SETS: dict[str, tuple[str, ...]] = {
    "alpha": ("a", "b", "c"),
    "beta": ("d", "e", "f"),
    "gamma": ("g", "h", "i"),
}

# The staged text is asserted on both ways: present for a committed docid,
# absent everywhere in the strict trajectory and in every compacted tombstone.
_STAGED_TEXT = "full staged text for {docid}"

# The status line the agent appends to every tool result. The ledger must
# preserve it verbatim through compaction (it is the model's budget readout).
STATUS_LINE = "[context budget: 100 / 500,000 tokens (0.0%) · elapsed: 0m 1s]"


def staged_text(docid: str) -> str:
    return _STAGED_TEXT.format(docid=docid)


def search_payload(query: str, k: int = 10, *,
                   docids: tuple[str, ...] | None = None) -> str:
    """The JSON a ``search`` tool result carries, in ``run_search_tool``'s shape.

    Used by the ledger-level tests, which need a staged payload without running
    the agent loop at all.
    """
    ids = docids if docids is not None else DOC_SETS[query]
    return json.dumps({
        "query": query,
        "k": k,
        "results": [
            {
                "rank": rank,
                "id": docid,
                "docid": docid,
                "kind": "document",
                "score": 1 / rank,
                "text": staged_text(docid),
            }
            for rank, docid in enumerate(ids, 1)
        ],
    })


def staged_output(query: str) -> str:
    """A staged tool result exactly as the agent hands it to the ledger."""
    return search_payload(query) + "\n" + STATUS_LINE


def first_line_json(text: str) -> dict[str, Any]:
    """Parse a compacted tool result's payload, dropping the status line."""
    return json.loads(text.splitlines()[0])


def results_by_docid(compacted: str) -> dict[str, dict[str, Any]]:
    """A compacted result list keyed by docid, for per-document assertions."""
    payload = first_line_json(compacted)
    return {item["docid"]: item for item in payload["results"]}


# ---------------------------------------------------------------------------
# Turn scripting
# ---------------------------------------------------------------------------
def turn(*, text: str = "", calls: list[dict[str, Any]] | None = None,
         input_tokens: int = 100, output_tokens: int = 10) -> dict[str, Any]:
    """One scripted ``ModelTurn`` with explicit token usage.

    Delegates block assembly to the shared ``model_turn`` so a scripted turn
    stays structurally identical to a real provider's output; only the usage
    numbers are ours (the migrated token-arithmetic assertions are exact).
    """
    return model_turn(
        text=text or None,
        tool_calls=calls or [],
        usage={
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
        },
    )


def call(call_id: str, name: str, **arguments: Any) -> dict[str, Any]:
    """One scripted tool call with a caller-chosen id (asserted on by id)."""
    return tool_call(name, arguments, id=call_id)


class StrictScriptedProvider(ScriptedProvider):
    """``ScriptedProvider`` plus ``content_by_id`` for compaction assertions.

    The compaction strictness this class originally added now lives in the
    shared ``ScriptedProvider`` (`tests/conftest.py`), so only the read-side
    helper below is local. The name is kept because every module here imports
    it, and because the strictness is what these tests depend on.
    """

    @property
    def content_by_id(self) -> dict[str, str]:
        """Current content of every tool result, by tool-call id.

        The old ``FakeProvider`` kept this dict directly; here it is derived
        from the shared mock's history, which ``compact_tool_results`` rewrites
        in place — so reading it after a commit shows the compacted bytes.
        """
        return {
            message["tool_call_id"]: message["content"]
            for message in self.raw_messages
            if isinstance(message, dict) and message.get("role") == "tool"
        }
