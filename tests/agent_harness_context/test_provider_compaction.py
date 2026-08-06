"""``BedrockProvider``'s half of the compaction protocol: settling and cache points.

The ledger computes replacement text; the provider is what actually rewrites
history — and on Bedrock that rewrite interacts with prompt caching, where a
mistake costs money rather than correctness. Two coupled invariants:

- **Settling.** ``compact_tool_results`` rewrites the one staged batch and then
  declares every message currently in history final (``_settled_count``). It is
  the ONLY thing that advances that counter, because it is the only moment the
  code can prove no earlier message will change again.
- **One rolling cache point, at the settled boundary.** Bedrock charges a cache
  *write* for a prefix it has not seen and a cheap *read* for one it has. A
  checkpoint placed over bytes that are about to be compacted turns every
  following turn's read into a write; two checkpoints left behind spend one of
  the four Claude allows and fragment the prefix.

Also here: the contentless-response retry, which is a history-integrity
behaviour like the above — a contentless assistant message is legal to receive
and illegal to send back, so keeping one poisons the NEXT request.

These tests build the provider with ``object.__new__`` and set the handful of
attributes each method reads, so no boto3 client is constructed and nothing can
reach the network. ``boto3`` itself is still imported (the module imports it at
top level), hence the ``importorskip``: it lives in the ``aus-agent`` dep group,
which CI installs.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("boto3", reason="boto3 is in the aus-agent dep group")

from agent_harness.context import REJECTION_PREFIX
from agent_harness.providers.bedrock import EMPTY_RESPONSE_RETRIES, BedrockProvider


def make_provider(*, caching: bool = True) -> BedrockProvider:
    """A ``BedrockProvider`` with no boto3 client and an empty history.

    ``object.__new__`` skips ``__init__`` (which would build a real client), so
    only the attributes the methods under test read are set. Nothing here can
    make a network call even if credentials happen to be present.
    """
    provider = object.__new__(BedrockProvider)
    provider.caching = caching
    provider._messages = []
    provider._settled_count = 0
    return provider


def staged(call_id: str) -> dict[str, Any]:
    """A user message carrying one tool result — what a staged batch looks like."""
    return {
        "role": "user",
        "content": [{"toolResult": {
            "toolUseId": call_id,
            "content": [{"text": f"full staged payload {call_id}"}],
            "status": "success",
        }}],
    }


def signed_assistant() -> dict[str, Any]:
    """An assistant message with a signed reasoning block.

    Signed ``reasoningContent`` must be replayed byte-for-byte or Bedrock rejects
    the turn, which is why nothing is ever appended to an assistant message —
    including a cache point.
    """
    return {
        "role": "assistant",
        "content": [{"reasoningContent": {
            "reasoningText": {"text": "", "signature": "signed"}}}],
    }


def cache_point_indices(provider: BedrockProvider) -> list[int]:
    """Indices of every message currently carrying a cache point."""
    return [index for index, message in enumerate(provider._messages)
            if any("cachePoint" in block for block in message["content"])]


# ---------------------------------------------------------------------------
# Rewriting tool results
# ---------------------------------------------------------------------------
def test_compaction_rewrites_the_tool_result_and_nothing_else() -> None:
    """Only ``toolResult`` blocks may be touched; assistant messages are frozen.

    An assistant message's signed reasoning is replayed verbatim or the API
    rejects the request, so the compaction pass has to walk past them. The
    identity assertion is the point — an implementation that rebuilt the list
    would produce an equal-looking message whose signature no longer matches.
    """
    provider = make_provider()
    assistant = signed_assistant()
    provider._messages = [assistant, staged("s1")]
    replacement = json.dumps({"decision": f"{REJECTION_PREFIX} a"})

    provider.compact_tool_results({"s1": replacement})

    assert provider._messages[0] is assistant
    assert (provider._messages[1]["content"][0]["toolResult"]["content"]
            == [{"text": replacement}])


def test_compaction_settles_every_message_then_in_history() -> None:
    """Settling is all-or-nothing at the moment compaction returns.

    The commit that triggered the compaction cleared the ledger's ``pending``
    list, so nothing earlier can ever be rewritten again — which is exactly the
    condition a cache checkpoint needs. Settling fewer messages would leave the
    checkpoint further back than it could be (paying to re-read bytes that are
    already final); settling more would put it over volatile bytes.
    """
    provider = make_provider()
    provider._messages = [
        {"role": "user", "content": [{"text": "task"}]},
        signed_assistant(),
        staged("s1"),
        signed_assistant(),
    ]
    assert provider._settled_count == 0

    provider.compact_tool_results({"s1": "compacted"})

    assert provider._settled_count == 4


def test_a_failed_compaction_settles_nothing() -> None:
    """An unknown id must raise BEFORE the boundary moves.

    ``run_agent`` treats this as fatal, and rightly: it means the harness tried
    to compact a batch that is not in history, so its idea of what the model can
    see has diverged from the provider's. Advancing ``_settled_count`` on the way
    out would then anchor a cache point using that wrong view.
    """
    provider = make_provider()
    provider._messages = [staged("s1")]

    with pytest.raises(KeyError, match="tool results not found"):
        provider.compact_tool_results({"missing": "x"})

    assert provider._settled_count == 0


def test_the_compaction_error_names_the_missing_ids() -> None:
    """The message has to identify which batch went missing.

    This surfaces as a failed run, so the id is the only handle a developer has
    on which search's tool result the ledger and the provider disagree about.
    """
    provider = make_provider()
    provider._messages = [staged("s1")]

    with pytest.raises(KeyError) as excinfo:
        provider.compact_tool_results({"s1": "ok", "s9": "x", "s8": "y"})

    assert "s8, s9" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The rolling cache point
# ---------------------------------------------------------------------------
def test_the_rolling_cache_point_lands_on_the_last_settled_user_message() -> None:
    """The checkpoint must sit at the settled boundary, not at the end.

    Two ways to get this wrong, both asserted against here: anchoring on the
    trailing assistant message (nothing may be appended to a signed one), or
    anchoring on the freshly staged batch (whose bytes are about to be rewritten,
    so the entry the write pays for is invalidated by the very next turn).
    """
    provider = make_provider()
    provider._messages = [
        {"role": "user", "content": [{"text": "task"}]},
        signed_assistant(),
        staged("s1"),
        signed_assistant(),
    ]
    provider.compact_tool_results({"s1": "compacted"})
    provider._messages.append(staged("s2"))  # fresh, still volatile

    provider._place_rolling_cache_point()

    assert cache_point_indices(provider) == [2]
    assert (provider._messages[2]["content"][-1]
            == {"cachePoint": {"type": "default"}})


def test_the_rolling_cache_point_moves_and_never_duplicates() -> None:
    """Exactly one checkpoint survives each move, and it advances.

    A leftover checkpoint is a silent cost regression twice over: Claude allows
    four, so a stale one is a slot the run cannot use later, and Bedrock matches
    the longest prefix ending at a checkpoint — several of them fragment the
    prefix into segments that each pay their own write.
    """
    provider = make_provider()
    provider._messages = [
        {"role": "user", "content": [{"text": "task"}]},
        signed_assistant(),
        staged("s1"),
        signed_assistant(),
    ]
    provider.compact_tool_results({"s1": "compacted"})
    provider._place_rolling_cache_point()
    assert cache_point_indices(provider) == [2]

    provider._messages.append(staged("s2"))
    provider._messages.append(signed_assistant())
    provider.compact_tool_results({"s2": "compacted"})
    provider._place_rolling_cache_point()

    assert cache_point_indices(provider) == [4]


def test_no_cache_point_is_placed_before_the_first_compaction() -> None:
    """Nothing is settled yet on turn one, so there is nothing worth caching.

    The initial user message is about to be followed by a staged batch that will
    be rewritten; a checkpoint there would pay a cache write for a prefix the
    next turn invalidates. Waiting costs one uncached turn and saves every
    subsequent one.
    """
    provider = make_provider()
    provider._messages = [{"role": "user", "content": [{"text": "task"}]}]

    provider._place_rolling_cache_point()

    assert provider._messages[0]["content"] == [{"text": "task"}]


def test_caching_disabled_places_no_cache_points_at_all() -> None:
    """``caching=False`` has to be a true off switch, not a smaller window.

    It is the control used to measure what caching is actually buying, and to
    work around a model that rejects cache points. A stray checkpoint would make
    the comparison meaningless — and cache-point blocks are billed content.
    """
    provider = make_provider(caching=False)
    provider._messages = [staged("s1")]

    provider.compact_tool_results({"s1": "compacted"})
    provider._place_rolling_cache_point()

    assert cache_point_indices(provider) == []


def test_a_settled_history_of_only_assistant_messages_gets_no_point() -> None:
    """With no settled *user* message there is nowhere legal to anchor.

    The loop walks back looking for one and must simply place nothing rather than
    fall through to an assistant message — appending to a signed reasoning block
    is a hard provider error, so this is a crash-avoidance guarantee, not an
    optimisation.
    """
    provider = make_provider()
    provider._messages = [signed_assistant(), signed_assistant()]
    provider._settled_count = 2

    provider._place_rolling_cache_point()

    assert cache_point_indices(provider) == []


# ---------------------------------------------------------------------------
# Contentless responses
# ---------------------------------------------------------------------------
class FakeConverseClient:
    """A stand-in for the boto3 ``bedrock-runtime`` client's ``converse``.

    Records each request so the retry count is observable, and replays queued
    replies. Purely local — the provider never builds a real client in these
    tests, so no credentials and no socket are involved.
    """

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]


def runnable(provider: BedrockProvider,
             client: FakeConverseClient) -> BedrockProvider:
    """Fill in the attributes ``run_turn`` reads, then attach the fake client."""
    provider.model_id = "m"
    provider.max_tokens = 16
    provider.thinking = False
    provider._system = []
    provider._tool_config = None
    provider._client = client
    return provider


def test_a_contentless_response_is_re_asked_and_never_appended() -> None:
    """A contentless assistant message must not enter history.

    It is legal to receive and illegal to send back, so appending one kills the
    NEXT request with "The content field in the Message object at messages.N is
    empty" — the run dies a turn after the turn that caused it, which is why the
    symptom was hard to attribute. Re-asking is side-effect-free precisely
    because nothing has been appended yet.
    """
    client = FakeConverseClient([
        {"output": {"message": {"role": "assistant", "content": []}}},
        {"output": {"message": {"role": "assistant",
                                "content": [{"text": "hello"}]}},
         "stopReason": "end_turn", "usage": {}},
    ])
    provider = runnable(make_provider(), client)

    turn = provider.run_turn()

    assert len(client.calls) == 2
    assert turn["text"] == "hello"
    assert len(provider._messages) == 1
    assert provider._messages[0]["content"] == [{"text": "hello"}]


def test_a_persistently_contentless_response_raises_after_the_retries() -> None:
    """The retry budget is bounded, and exhausting it fails loudly.

    Observed roughly once in ten dev topics, so retrying is worth it — but
    looping forever on a model that has stopped producing content would burn the
    token budget silently. ``run_agent`` catches the ``RuntimeError`` and still
    saves the run's partial artifacts.
    """
    client = FakeConverseClient([
        {"output": {"message": {"role": "assistant", "content": []}},
         "stopReason": "end_turn"},
    ])
    provider = runnable(make_provider(), client)

    with pytest.raises(RuntimeError, match="no content"):
        provider.run_turn()

    assert len(client.calls) == EMPTY_RESPONSE_RETRIES
    assert provider._messages == []
