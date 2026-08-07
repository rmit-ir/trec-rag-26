"""V2 transport resilience must not mutate baseline or retry bad requests."""
from __future__ import annotations

from typing import Any

import pytest

from agent_harness.providers.openai import OpenAIProvider
from systems.aus_agent_v2.provider import (
    OUTER_INITIAL_DELAY_S,
    ResilientOpenAIProvider,
    retryable_mantle_transport_error,
)


def http_error(status: int, message: str = "gateway") -> RuntimeError:
    """Build the small exception surface the retry classifier consumes."""
    error = RuntimeError(message)
    error.status_code = status  # type: ignore[attr-defined]
    return error


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504])
def test_retryable_mantle_statuses_cover_observed_outages(status: int) -> None:
    """The live incident alternated 502, 503, and 504 within one model turn."""
    assert retryable_mantle_transport_error(http_error(status)) is True


def test_validation_errors_are_not_retried() -> None:
    """A malformed model option cannot become valid by waiting for Mantle."""
    assert retryable_mantle_transport_error(
        http_error(400, "unsupported reasoning effort")
    ) is False
    assert retryable_mantle_transport_error(
        http_error(400, "Internal server error")
    ) is True


def test_resilient_provider_retries_the_unchanged_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovered request must continue the topic instead of losing research."""
    expected: dict[str, Any] = {
        "blocks": [],
        "reasoning_blocks": [],
        "tool_calls": [],
        "text": "OK",
        "stop_reason": "completed",
        "usage": {},
        "raw": {},
    }
    outcomes: list[Exception | dict[str, Any]] = [http_error(503), expected]

    def scripted_turn(_self: OpenAIProvider) -> dict[str, Any]:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(OpenAIProvider, "run_turn", scripted_turn)
    sleeps: list[float] = []
    provider = ResilientOpenAIProvider(
        "test-model", outer_retries=2, sleep_fn=sleeps.append
    )

    assert provider.run_turn() is expected
    assert sleeps == [OUTER_INITIAL_DELAY_S]
    assert outcomes == []


def test_resilient_provider_fails_fast_on_non_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outer resilience must not hide a prompt or request-contract defect."""
    error = http_error(400, "invalid tools schema")

    def invalid_turn(_self: OpenAIProvider) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(OpenAIProvider, "run_turn", invalid_turn)
    sleeps: list[float] = []
    provider = ResilientOpenAIProvider(
        "test-model", outer_retries=2, sleep_fn=sleeps.append
    )

    with pytest.raises(RuntimeError, match="invalid tools schema"):
        provider.run_turn()
    assert sleeps == []
