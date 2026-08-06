"""V2-local provider policy for preserving a topic across Mantle outages."""
from __future__ import annotations

import logging
from time import sleep
from typing import Callable

from aus_agent.agent import make_provider as make_base_provider
from aus_agent.providers.base import ModelTurn, Provider
from aus_agent.providers.openai import OpenAIProvider
from utils.env import env


OUTER_RETRIES = env("AUS_AGENT_V2_OUTER_RETRIES", 12)
OUTER_INITIAL_DELAY_S = env("AUS_AGENT_V2_OUTER_INITIAL_DELAY_S", 5.0)
OUTER_MAX_DELAY_S = env("AUS_AGENT_V2_OUTER_MAX_DELAY_S", 60.0)

log = logging.getLogger(__name__)


def retryable_mantle_transport_error(exc: Exception) -> bool:
    """Identify transient transport failures after the SDK exhausts retries."""
    status = getattr(exc, "status_code", None)
    if status in {408, 409, 429, 500, 502, 503, 504}:
        return True
    if status == 400 and "internal server error" in str(exc).lower():
        return True
    return type(exc).__name__ in {"APIConnectionError", "APITimeoutError"}


class ResilientOpenAIProvider(OpenAIProvider):
    """Retry one unchanged turn long enough to ride out a gateway incident.

    ``OpenAIProvider`` owns the conversation in memory and appends an assistant
    item only after a successful response. Retrying ``super().run_turn()``
    therefore sends the same request against the same state; it does not repeat
    a tool call or alter the research trajectory.
    """

    def __init__(
        self,
        model_id: str | None = None,
        *,
        max_tokens: int = 16_000,
        outer_retries: int = OUTER_RETRIES,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        super().__init__(model_id, max_tokens=max_tokens)
        self.outer_retries = outer_retries
        self._sleep = sleep_fn

    def run_turn(self) -> ModelTurn:
        """Preserve topic state while retrying only transient failures."""
        for attempt in range(self.outer_retries + 1):
            try:
                return super().run_turn()
            except Exception as exc:
                if (not retryable_mantle_transport_error(exc)
                        or attempt >= self.outer_retries):
                    raise
                delay = min(
                    OUTER_INITIAL_DELAY_S * (2 ** attempt),
                    OUTER_MAX_DELAY_S,
                )
                log.warning(
                    "Mantle transport remained unavailable after SDK retries; "
                    "preserving conversation and retrying unchanged turn in "
                    "%ss (%d/%d)",
                    delay,
                    attempt + 1,
                    self.outer_retries,
                )
                self._sleep(delay)
        raise AssertionError("retry loop must return or raise")


def make_provider(
    backend: str,
    model: str | None,
    region: str | None = None,
) -> Provider:
    """Keep resilience in v2 while delegating other backends to baseline."""
    if backend == "openai":
        return ResilientOpenAIProvider(model)
    return make_base_provider(backend, model, region=region)
