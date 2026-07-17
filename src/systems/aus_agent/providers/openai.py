"""OpenAI backend — Responses API, stateless (``store=False``).

- Credentials come from the environment (root ``.env`` via python-dotenv:
  ``OPENAI_API_KEY``).
- Default model: ``OPENAI_MODEL_ID`` env or ``DEFAULT_MODEL_ID`` below.

Statelessness is the load-bearing choice: the harness compacts old tool
results (``compact_tool_results``), which requires owning the message history
ourselves rather than chaining ``previous_response_id`` server-side state.
Every request therefore sends the full ``input`` item list, and the model's
output items — including ``reasoning`` items — are appended back to that list
verbatim for replay.

Reasoning models return their chain-of-thought as encrypted ``reasoning``
items when ``include=["reasoning.encrypted_content"]`` is requested (required
with ``store=False``, or multi-turn tool use loses the reasoning state and
quality drops). Like Bedrock's signed ``reasoningContent``, these are replayed
byte-for-byte and never rewritten; ``reasoning_blocks`` in the normalized turn
carries only the human-readable summary, which is often empty.

Prompt caching is automatic on OpenAI (prefixes over ~1024 tokens) — no cache
points to manage. ``usage.input_tokens`` INCLUDES cached tokens (unlike
Bedrock, which excludes cache reads), so the normalized usage dict subtracts
``cached_tokens`` back out to keep ``agent._usage_token_stats`` arithmetic
correct across backends.
"""
from __future__ import annotations

import json
import os
from typing import Any

try:  # creds from the repo root .env
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .base import ModelTurn, Provider

DEFAULT_MODEL_ID = "gpt-5.6-terra"
# Mirror of bedrock.py's guard: a turn with no text and no tool calls is
# unusable (the loop would stall), so ask again rather than append it.
EMPTY_RESPONSE_RETRIES = 3


class OpenAIProvider(Provider):
    def __init__(self, model_id: str | None = None, *,
                 max_tokens: int = 16000) -> None:
        self.model_id = (model_id
                         or os.environ.get("OPENAI_MODEL_ID", DEFAULT_MODEL_ID))
        self.max_tokens = max_tokens
        self._client: Any = None  # built lazily so tests need no API key
        self._system = ""
        self._tools: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(timeout=600.0, max_retries=5)
        return self._client

    # -- Provider contract ---------------------------------------------------

    def start(self, system_prompt: str, tools: list[dict[str, Any]]) -> None:
        self._system = system_prompt
        self._tools = [
            {"type": "function",
             "name": t["name"],
             "description": t["description"],
             "parameters": t["input_schema"]}
            for t in tools
        ]
        self._items = []

    def add_user_message(self, text: str) -> None:
        self._items.append({"role": "user", "content": text})

    def run_turn(self) -> ModelTurn:
        client = self._ensure_client()
        for attempt in range(EMPTY_RESPONSE_RETRIES):
            resp = client.responses.create(
                model=self.model_id,
                instructions=self._system,
                input=self._items,
                tools=self._tools or None,
                max_output_tokens=self.max_tokens,
                store=False,
                include=["reasoning.encrypted_content"],
            )
            blocks: list[dict[str, Any]] = []
            reasoning_blocks: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            text_parts: list[str] = []
            for item in resp.output:
                kind = getattr(item, "type", None)
                if kind == "reasoning":
                    rtext = "\n".join(
                        s.text for s in (item.summary or []) if s.text)
                    reasoning_blocks.append(rtext)
                    blocks.append({"type": "reasoning", "text": rtext})
                elif kind == "function_call":
                    try:
                        arguments = json.loads(item.arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    call = {"id": item.call_id, "name": item.name,
                            "arguments": arguments}
                    tool_calls.append(call)
                    blocks.append({"type": "tool_call", "call": call})
                elif kind == "message":
                    for content in item.content:
                        if getattr(content, "type", None) == "output_text":
                            text_parts.append(content.text)
                            blocks.append({"type": "text",
                                           "text": content.text})
            if tool_calls or text_parts:
                break
        else:
            raise RuntimeError(
                f"OpenAI returned a response with no text and no tool calls "
                f"{EMPTY_RESPONSE_RETRIES} times in a row "
                f"(status={getattr(resp, 'status', None)!r})")

        # Append output items VERBATIM (encrypted reasoning included) — they
        # must be replayed unmodified for reasoning + tool use across turns.
        self._items.extend(
            item.model_dump(exclude_none=True) for item in resp.output)

        usage = {}
        if resp.usage is not None:
            details = getattr(resp.usage, "input_tokens_details", None)
            cached = int(getattr(details, "cached_tokens", 0) or 0)
            usage = {
                # input_tokens includes cached tokens on OpenAI; report the
                # uncached remainder so the harness's uncached+cache_read sum
                # equals true context size, matching the Bedrock convention.
                "input_tokens": int(resp.usage.input_tokens or 0) - cached,
                "cache_read_input_tokens": cached,
                "output_tokens": int(resp.usage.output_tokens or 0),
            }

        return {
            "blocks": blocks,
            "reasoning_blocks": reasoning_blocks,
            "tool_calls": tool_calls,
            "text": "\n".join(text_parts) if text_parts else None,
            "stop_reason": getattr(resp, "status", "") or "",
            "usage": usage,
            "raw": resp.model_dump(exclude_none=True),
        }

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        for r in results:
            self._items.append({
                "type": "function_call_output",
                "call_id": r["id"],
                "output": r["content"],
            })

    def compact_tool_results(self, replacements: dict[str, str]) -> None:
        """Rewrite earlier function_call_output items; never touch reasoning."""
        remaining = dict(replacements)
        for item in self._items:
            if item.get("type") != "function_call_output":
                continue
            call_id = item.get("call_id")
            if call_id not in remaining:
                continue
            item["output"] = remaining.pop(call_id)
        if remaining:
            missing = ", ".join(sorted(remaining))
            raise KeyError(f"tool results not found for compaction: {missing}")

    @property
    def raw_messages(self) -> list[Any]:
        return self._items
