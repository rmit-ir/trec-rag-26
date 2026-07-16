"""Minimal per-provider contract — NOT a message-translation layer.

Each provider owns its native message history internally (Bedrock Converse
dicts, OpenAI Responses items, ...). The harness only ever drives four calls
and consumes normalized plain-dict events; it never touches provider-native
message formats.

Normalized shapes:

    tool_call   = {"id": str, "name": str, "arguments": dict}
    tool_result = {"id": str, "content": str, "is_error": bool}
    ModelTurn   = {
        "blocks":           [...],        # in content order, each one of:
                                          #   {"type": "reasoning", "text": str}
                                          #   {"type": "tool_call", "call": tool_call}
                                          #   {"type": "text", "text": str}
        "reasoning_blocks": [str],        # convenience view of blocks
        "tool_calls":       [tool_call],  # convenience view of blocks
        "text":             str | None,   # concatenated text blocks
        "stop_reason":      str,          # provider-native stop reason
        "usage":            dict,         # provider-native token usage
        "raw":              Any,          # full provider response
    }

Tool definitions handed to ``start()`` are Anthropic-style dicts
(``name`` / ``description`` / ``input_schema``); each provider converts to its
native tool schema internally.

Adding a backend (Azure OpenAI, OpenAI Responses, ...): subclass ``Provider``,
implement the four methods + ``raw_messages``, and register it in
``agent.make_provider``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

ModelTurn = dict[str, Any]  # documented above


class Provider(ABC):
    """One conversation with one model; owns its native message history."""

    model_id: str

    @abstractmethod
    def start(self, system_prompt: str, tools: list[dict[str, Any]]) -> None:
        """Begin a fresh conversation with a system prompt and tool defs."""

    @abstractmethod
    def add_user_message(self, text: str) -> None:
        """Append a user turn."""

    @abstractmethod
    def run_turn(self) -> ModelTurn:
        """Run one model turn; append the assistant message (verbatim, with
        any reasoning blocks intact) to the internal history and return the
        normalized events."""

    @abstractmethod
    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        """Answer ALL pending tool calls from the last turn, in order.
        ``results`` items: ``{"id", "content", "is_error"}``."""

    @property
    @abstractmethod
    def raw_messages(self) -> list[Any]:
        """JSON-serializable provider-native message history (for the
        trajectory's ``raw_messages``)."""
