"""Bedrock backend — boto3 ``bedrock-runtime`` Converse API.

- Region defaults to ``ap-southeast-2`` (override: ``BEDROCK_REGION``).
- Credentials come from the environment (root ``.env`` via python-dotenv:
  ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN``).
- Default model: ``BEDROCK_MODEL_ID`` env or ``au.anthropic.claude-sonnet-5``.
  Verified working under this role: au.anthropic.claude-sonnet-5,
  au.anthropic.claude-opus-4-8, au.anthropic.claude-haiku-4-5-20251001-v1:0,
  au.anthropic.claude-sonnet-4-6, au.anthropic.claude-opus-4-7,
  au.anthropic.claude-opus-4-6-v1. (global.*/us.* profiles are AccessDenied.)

Extended thinking: enabled via ``additionalModelRequestFields =
{"thinking": {"type": "adaptive"}}`` — the current setting for Claude 4.6+
models (``budget_tokens`` is rejected on Sonnet 5 / Opus 4.7+). Reasoning
arrives as ``reasoningContent`` content blocks, interleaved with ``toolUse``
blocks in the same assistant message. CRITICAL: those blocks (text +
signature) are passed back UNMODIFIED on subsequent turns — we append the
whole ``output.message`` verbatim to the history and never rewrite it.

Prompt caching: Claude on Bedrock has NO automatic caching (unlike Nova) —
every cached prefix needs an explicit ``{"cachePoint": {"type": "default"}}``
block. Bedrock chains the sections ``tools`` -> ``system`` -> ``messages`` and
evaluates the per-checkpoint token minimum against their cumulative total, so
stable content must precede volatile content. Two checkpoints (of the 4 Claude
allows) are placed:

1. a static one at the end of ``system`` — tools + system never change; and
2. a rolling one at the end of the last *settled* user message.

"Settled" is the key invariant: ``compact_tool_results`` only ever rewrites the
single staged batch held in the ledger's ``pending`` list, and the commit that
triggers it clears ``pending``, so each tool result is compacted exactly once.
By the time compaction returns, every message then in history is final — hence
``_settled_count = len(self._messages)`` right there. The freshly staged batch
appended afterwards sits *after* the breakpoint: it is about to be rewritten,
so caching it would buy an entry that the next turn invalidates anyway.

Anthropic models on Bedrock support simplified cache management — one
checkpoint at the end of the static content, and the service looks back ~20
content blocks to find the longest matching prefix — so a single rolling
checkpoint is enough; there is no need to keep a window of older breakpoints.

Note: with caching on, ``usage.inputTokens`` counts only NON-cached input.
The true context size is ``inputTokens + cacheReadInputTokens +
cacheWriteInputTokens`` (see ``agent._usage_token_stats``).
"""
from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.config import Config

try:  # creds/config from the repo root .env
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .base import ModelTurn, Provider

DEFAULT_MODEL_ID = "au.anthropic.claude-sonnet-5"
DEFAULT_REGION = "ap-southeast-2"
# How many times to re-ask when Converse returns a contentless assistant
# message. Observed once in ten dev topics, and it kills the run on the turn
# after it lands, so it is worth retrying rather than propagating.
EMPTY_RESPONSE_RETRIES = 3


def cache_point() -> dict[str, Any]:
    """A fresh Bedrock cache checkpoint marker (default 5-minute TTL)."""
    return {"cachePoint": {"type": "default"}}


class BedrockProvider(Provider):
    def __init__(self, model_id: str | None = None, *, region: str | None = None,
                 max_tokens: int = 16000, thinking: bool = True,
                 caching: bool = True) -> None:
        self.model_id = (model_id
                         or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID))
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.caching = caching
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region or os.environ.get("BEDROCK_REGION", DEFAULT_REGION),
            config=Config(read_timeout=600, connect_timeout=30,
                          retries={"max_attempts": 5, "mode": "adaptive"}),
        )
        self._system: list[dict[str, Any]] = []
        self._tool_config: dict[str, Any] | None = None
        self._messages: list[dict[str, Any]] = []
        # Count of leading messages that can never be rewritten again. Advanced
        # only by compact_tool_results; see the module docstring.
        self._settled_count = 0

    # -- Provider contract ---------------------------------------------------

    def start(self, system_prompt: str, tools: list[dict[str, Any]]) -> None:
        self._system = [{"text": system_prompt}]
        if self.caching:
            # Static checkpoint: Bedrock chains tools -> system -> messages, so
            # this one entry covers every byte that never changes in this run.
            self._system.append(cache_point())
        self._tool_config = {
            "tools": [
                {"toolSpec": {"name": t["name"],
                              "description": t["description"],
                              "inputSchema": {"json": t["input_schema"]}}}
                for t in tools
            ]
        } if tools else None
        self._messages = []
        self._settled_count = 0

    def add_user_message(self, text: str) -> None:
        self._messages.append({"role": "user", "content": [{"text": text}]})

    def _place_rolling_cache_point(self) -> None:
        """Move the single rolling checkpoint to the settled boundary.

        Anchored on the last settled *user* message: assistant messages carry
        signed ``reasoningContent`` and are replayed byte-for-byte, so nothing
        is ever appended to them. The cost is that the trailing assistant turn
        stays uncached for one more round, which the next checkpoint absorbs.
        """
        if not self.caching:
            return
        for message in self._messages:
            content = message.get("content")
            if isinstance(content, list) and any(
                    "cachePoint" in block for block in content):
                message["content"] = [
                    block for block in content if "cachePoint" not in block]
        for index in range(self._settled_count - 1, -1, -1):
            message = self._messages[index]
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, list):
                message["content"] = [*content, cache_point()]
            return

    def run_turn(self) -> ModelTurn:
        self._place_rolling_cache_point()
        kwargs: dict[str, Any] = {
            "modelId": self.model_id,
            "system": self._system,
            "messages": self._messages,
            "inferenceConfig": {"maxTokens": self.max_tokens},
        }
        if self._tool_config:
            kwargs["toolConfig"] = self._tool_config
        if self.thinking:
            kwargs["additionalModelRequestFields"] = {
                "thinking": {"type": "adaptive"}}

        # Converse occasionally answers with an assistant message carrying no
        # content blocks at all. Appending one poisons the history: the message
        # is legal to receive but illegal to send back, so the NEXT request
        # dies with "The content field in the Message object at messages.N is
        # empty" and the run fails a turn after the turn that caused it. It is
        # also unusable — no text, no tool calls, nothing to act on. Ask again
        # rather than keep it; the retry is free of side effects because
        # nothing has been appended yet.
        for attempt in range(EMPTY_RESPONSE_RETRIES):
            resp = self._client.converse(**kwargs)
            msg = resp["output"]["message"]
            if msg.get("content"):
                break
        else:
            raise RuntimeError(
                f"Bedrock returned an assistant message with no content "
                f"{EMPTY_RESPONSE_RETRIES} times in a row "
                f"(stopReason={resp.get('stopReason')!r})")
        # Append VERBATIM — reasoningContent blocks (incl. signatures) must be
        # replayed unmodified for thinking + tool use to work across turns.
        self._messages.append(msg)

        blocks: list[dict[str, Any]] = []
        reasoning_blocks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for block in msg.get("content", []):
            if "reasoningContent" in block:
                rtext = (block["reasoningContent"]
                         .get("reasoningText", {}).get("text", ""))
                reasoning_blocks.append(rtext)
                blocks.append({"type": "reasoning", "text": rtext})
            elif "toolUse" in block:
                tu = block["toolUse"]
                call = {"id": tu["toolUseId"], "name": tu["name"],
                        "arguments": tu.get("input") or {}}
                tool_calls.append(call)
                blocks.append({"type": "tool_call", "call": call})
            elif "text" in block:
                text_parts.append(block["text"])
                blocks.append({"type": "text", "text": block["text"]})

        return {
            "blocks": blocks,
            "reasoning_blocks": reasoning_blocks,
            "tool_calls": tool_calls,
            "text": "\n".join(text_parts) if text_parts else None,
            "stop_reason": resp.get("stopReason", ""),
            "usage": resp.get("usage", {}),
            "raw": resp,
        }

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        content = [
            {"toolResult": {
                "toolUseId": r["id"],
                "content": [{"text": r["content"]}],
                "status": "error" if r.get("is_error") else "success",
            }}
            for r in results
        ]
        self._messages.append({"role": "user", "content": content})

    def compact_tool_results(self, replacements: dict[str, str]) -> None:
        """Compact earlier toolResult texts without touching signed messages."""
        remaining = dict(replacements)
        for message in self._messages:
            if message.get("role") != "user":
                continue
            for block in message.get("content", []):
                result = block.get("toolResult")
                if not isinstance(result, dict):
                    continue
                tool_use_id = result.get("toolUseId")
                if tool_use_id not in remaining:
                    continue
                result["content"] = [{"text": remaining.pop(tool_use_id)}]
        if remaining:
            missing = ", ".join(sorted(remaining))
            raise KeyError(f"tool results not found for compaction: {missing}")
        # Compaction only ever rewrites the one staged batch, and the commit
        # that triggered it cleared the ledger's pending list — so every
        # message now in history has reached its final bytes.
        self._settled_count = len(self._messages)

    @property
    def raw_messages(self) -> list[Any]:
        return self._messages
