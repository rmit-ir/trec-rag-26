"""Shared one-shot LLM call helper, token-stat normalization, and defensive
JSON-fence stripping — used by every structured-JSON stage (planner, loop,
curator) so parsing tolerance and usage accounting stay consistent. Split out
from loop.py so curator.py can depend on it without a loop.py <-> curator.py
import cycle.
"""
from __future__ import annotations

import re
from typing import Any


def usage_token_stats(usage: dict[str, Any]) -> dict[str, int] | None:
    """Normalize provider usage into the trace token block (or None).

    Mirrors ``aus_agent.agent._usage_token_stats`` so token accounting is
    consistent across systems (Bedrock excludes cache reads from inputTokens;
    OpenAI's provider already subtracts them back out).
    """
    if not usage:
        return None
    uncached = int(usage.get("inputTokens", usage.get("input_tokens", 0)) or 0)
    output = int(usage.get("outputTokens", usage.get("output_tokens", 0)) or 0)
    cache_read = int(usage.get("cacheReadInputTokens",
                               usage.get("cache_read_input_tokens", 0)) or 0)
    cache_write = int(usage.get("cacheWriteInputTokens",
                                usage.get("cache_write_input_tokens", 0)) or 0)
    logical = uncached + cache_read + cache_write
    processed = uncached + cache_write
    return {"input": logical, "input_uncached": uncached, "output": output,
            "cache_read": cache_read, "cache_write": cache_write,
            "total": logical + output, "processed_input": processed,
            "processed": processed + output}


def one_shot(provider: Any, system_prompt: str, user_text: str) -> str:
    """Run one fresh, tool-less turn and return its text.

    The turn's usage is stashed on the provider as ``_last_usage`` so callers
    that want token stats can read it without changing the ``Provider``
    contract.
    """
    provider.start(system_prompt, [])
    provider.add_user_message(user_text)
    turn = provider.run_turn()
    provider._last_usage = turn.get("usage", {})  # type: ignore[attr-defined]
    return turn.get("text") or ""


def strip_fences(raw: str) -> str:
    """Drop ```json ... ``` fences a model may add despite instructions."""
    raw = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL)
    return fence.group(1).strip() if fence else raw
