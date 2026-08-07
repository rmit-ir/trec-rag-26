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
import re
from typing import Any

try:  # creds from the repo root .env
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from utils.env import env

from .base import ModelTurn, Provider

DEFAULT_MODEL_ID = "gpt-5.6-luna"
# Mirror of bedrock.py's guard: a turn with no text and no tool calls is
# unusable (the loop would stall), so ask again rather than append it.
EMPTY_RESPONSE_RETRIES = 3

# Per-attempt HTTP timeouts. The read bound is the one that matters: a hung
# socket is invisible until it expires, so `timeout=600.0` (the old single
# scalar) stalled a run for ten minutes before the retry that fixed it in under
# a second.
#
# It is MODEL-DEPENDENT and therefore not a constant to tune once. Measured on
# `gpt-5.6-luna` over 447 turns (2026-08-05 prompt-variant runs): p50 5.4s,
# p90 15.6s, p99 25.2s, longest legitimate turn ~26s. A larger generator
# (`gpt-5.6-sol`) or `reasoning.mode=pro` raises all of those, so the default
# below is deliberately sized for the SLOWER model rather than the measured
# one — the two failure modes are not symmetric:
#
#   too high -> one hung socket stalls the run for the timeout's duration;
#   too low  -> legitimate generations are cancelled mid-flight, and since each
#               retry re-sends the entire accumulated conversation, a too-tight
#               bound burns tokens and can never converge on the long turns it
#               keeps killing.
#
# The second is far worse, so the default keeps ~12x headroom over luna's p99
# (room for a ~10x slower model) while still halving the old stall. Tune per
# model with AUS_AGENT_READ_TIMEOUT_S rather than editing this; re-measure with
#
#   grep -ho "turn [0-9]* took [0-9.]*s" <run log> | grep -o "[0-9.]*s$"
#
# and set it to roughly 5x the observed p99. NB: a turn-duration distribution
# gathered under an existing timeout cannot show anything above that timeout,
# so read the p99 of the SUCCESSFUL turns and ignore the pile-up at the ceiling.
CONNECT_TIMEOUT_S = env("AUS_AGENT_CONNECT_TIMEOUT_S", 15.0)
READ_TIMEOUT_S = env("AUS_AGENT_READ_TIMEOUT_S", 300.0)
WRITE_TIMEOUT_S = env("AUS_AGENT_WRITE_TIMEOUT_S", 60.0)  # body = whole convo
POOL_TIMEOUT_S = env("AUS_AGENT_POOL_TIMEOUT_S", 15.0)
MAX_RETRIES = env("AUS_AGENT_MAX_RETRIES", 5)


def _region_from_base_url(url: str) -> str:
    """AWS region out of an endpoint host, or ``"unknown"`` if it has none.

    ``https://bedrock-mantle.us-east-1.api.aws/openai/v1`` -> ``us-east-1``.
    Returning a sentinel rather than raising keeps a non-AWS endpoint working;
    it simply has no rate table and reports tokens without dollars.
    """
    match = re.search(r"\.([a-z]{2}-[a-z]+-\d)\.", url or "")
    return match.group(1) if match else "unknown"


class OpenAIProvider(Provider):
    def __init__(self, model_id: str | None = None, *,
                 max_tokens: int = 16000, region: str | None = None,
                 reasoning_effort: str | None = None,
                 reasoning_mode: str | None = None) -> None:
        self.model_id = (model_id
                         or os.environ.get("OPENAI_MODEL_ID", DEFAULT_MODEL_ID))
        # Cost lookup keys on (model_id, region). The OpenAI-compatible client
        # carries no region of its own, so derive it from the endpoint host
        # (``bedrock-mantle.us-east-1.api.aws``); without this every call is
        # reported unpriced even when a rate table exists.
        self.region = (region
                       or os.environ.get("OPENAI_REGION")
                       or _region_from_base_url(
                           os.environ.get("OPENAI_BASE_URL", "")))
        self.max_tokens = max_tokens
        # Both default to None => the key is omitted => the API's own defaults
        # (effort=medium, mode=standard) apply, exactly as before. They are
        # INDEPENDENT parameters, not one scale: mode picks the reasoning
        # system, effort picks how much of it to spend.
        self.reasoning_effort = (reasoning_effort
                                 or os.environ.get("OPENAI_REASONING_EFFORT"))
        self.reasoning_mode = (reasoning_mode
                               or os.environ.get("OPENAI_REASONING_MODE"))
        self._client: Any = None  # built lazily so tests need no API key
        self._system = ""
        self._tools: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []

    def _ensure_client(self) -> Any:
        if self._client is None:
            import httpx
            from openai import OpenAI

            # Split rather than one scalar: a stalled *read* is the failure we
            # actually see, and it needs a much tighter bound than the write of
            # a request body that grows to the whole accumulated conversation.
            self._client = OpenAI(
                timeout=httpx.Timeout(
                    READ_TIMEOUT_S,
                    connect=CONNECT_TIMEOUT_S,
                    write=WRITE_TIMEOUT_S,
                    pool=POOL_TIMEOUT_S,
                ),
                max_retries=MAX_RETRIES,
            )
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

    def _reasoning(self) -> dict[str, Any]:
        """The `reasoning` block, omitting keys that were never configured.

        Sending ``effort=None`` is not the same as omitting it, and an
        unsupported key is a 400 rather than a silent ignore -- so only
        explicitly-set values are included.
        """
        block: dict[str, Any] = {"summary": "auto"}
        if self.reasoning_effort:
            block["effort"] = self.reasoning_effort
        if self.reasoning_mode:
            block["mode"] = self.reasoning_mode
        return block

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
                reasoning=self._reasoning(),
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
            out_details = getattr(resp.usage, "output_tokens_details", None)
            usage = {
                # input_tokens includes cached tokens on OpenAI; report the
                # uncached remainder so the harness's uncached+cache_read sum
                # equals true context size, matching the Bedrock convention.
                "input_tokens": int(resp.usage.input_tokens or 0) - cached,
                "cache_read_input_tokens": cached,
                "output_tokens": int(resp.usage.output_tokens or 0),
                # Reasoning tokens are BILLED as output but produce no visible
                # text, so a run can spend most of its output budget on thinking
                # and look cheap by word count. Without this figure a
                # reasoning-effort experiment yields a quality delta with no
                # cost denominator -- which is why no such experiment has ever
                # been run here. Included in output_tokens, not additional to it.
                "reasoning_tokens": int(
                    getattr(out_details, "reasoning_tokens", 0) or 0),
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
