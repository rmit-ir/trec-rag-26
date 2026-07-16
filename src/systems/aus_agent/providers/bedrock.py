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


class BedrockProvider(Provider):
    def __init__(self, model_id: str | None = None, *, region: str | None = None,
                 max_tokens: int = 16000, thinking: bool = True) -> None:
        self.model_id = (model_id
                         or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID))
        self.max_tokens = max_tokens
        self.thinking = thinking
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region or os.environ.get("BEDROCK_REGION", DEFAULT_REGION),
            config=Config(read_timeout=600, connect_timeout=30,
                          retries={"max_attempts": 5, "mode": "adaptive"}),
        )
        self._system: list[dict[str, Any]] = []
        self._tool_config: dict[str, Any] | None = None
        self._messages: list[dict[str, Any]] = []

    # -- Provider contract ---------------------------------------------------

    def start(self, system_prompt: str, tools: list[dict[str, Any]]) -> None:
        self._system = [{"text": system_prompt}]
        self._tool_config = {
            "tools": [
                {"toolSpec": {"name": t["name"],
                              "description": t["description"],
                              "inputSchema": {"json": t["input_schema"]}}}
                for t in tools
            ]
        } if tools else None
        self._messages = []

    def add_user_message(self, text: str) -> None:
        self._messages.append({"role": "user", "content": [{"text": text}]})

    def run_turn(self) -> ModelTurn:
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

        resp = self._client.converse(**kwargs)
        msg = resp["output"]["message"]
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

    @property
    def raw_messages(self) -> list[Any]:
        return self._messages
