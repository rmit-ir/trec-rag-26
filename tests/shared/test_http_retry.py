"""Unit-test the retry/backoff policy the ``pyserini-rest-api`` skill mandates.

The Pyserini API is shared infrastructure the whole track hits, so "back off on
429" is a rule we are *told* to follow, not a robustness nicety — the failure
mode of getting it wrong is our client hammering an endpoint everyone depends
on, or (just as bad) retrying a ``401``/``404`` forever and burning the
allowance on a request that can never succeed.

This file covers the decision logic in isolation with a fake opener; the
companion loopback tests in ``tests/dummy_api/test_rate_limit.py`` prove the
real clients get the behaviour over an actual socket. Every sleep is captured
rather than performed — a genuine 1/2/4/8s schedule would triple the runtime of
the whole suite.
"""
from __future__ import annotations

import socket
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from utils.http_retry import (
    BASE_DELAY,
    MAX_DELAY,
    MAX_RETRIES,
    parse_retry_after,
    urlopen_with_backoff,
)


def _http_error(code: int, retry_after: str | None = None
                ) -> urllib.error.HTTPError:
    """An ``HTTPError`` shaped like the ones ``urlopen`` actually raises."""
    import email.message

    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x/", code, "boom", headers, None)


class _Opener:
    """Fake ``urlopen`` replaying a script of exceptions then a sentinel."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls = 0

    def __call__(self, req: Any, timeout: float | None = None) -> Any:
        self.calls += 1
        item = self.script.pop(0) if self.script else "OK"
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def slept() -> list[float]:
    """Collect the delays the retry loop asks for, without waiting them out."""
    return []


# ---------------------------------------------------------------------------
# parse_retry_after — both documented header forms
# ---------------------------------------------------------------------------
def test_retry_after_accepts_delay_seconds() -> None:
    """The integer form is the common one; a float must also survive."""
    assert parse_retry_after("30") == 30.0
    assert parse_retry_after("  2.5  ") == 2.5


def test_retry_after_accepts_an_http_date() -> None:
    """The date form is the half that is easy to forget.

    Dropping it would mean falling back to our own guessed backoff at exactly
    the moment the server told us precisely how long it needs — the worst time
    to guess.
    """
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    later = now + timedelta(seconds=45)
    header = later.strftime("%a, %d %b %Y %H:%M:%S GMT")

    assert parse_retry_after(header, now=now) == pytest.approx(45.0, abs=1.0)


def test_retry_after_in_the_past_means_retry_now() -> None:
    """A stale date must clamp to 0.0, never a negative sleep.

    ``time.sleep`` on a negative number raises, so an unclamped subtraction
    would turn a helpful header into a crash inside the retry loop.
    """
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    past = (now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")

    assert parse_retry_after(past, now=now) == 0.0


@pytest.mark.parametrize("value", [None, "", "   ", "soon", "tomorrow-ish"])
def test_unusable_retry_after_falls_back_to_none(value: str | None) -> None:
    """An absent or malformed header yields ``None``, not ``0.0``.

    The distinction matters: ``None`` means "use exponential backoff", whereas
    ``0.0`` would mean "retry immediately" — i.e. a garbled header would turn
    into a tight loop against a rate-limited endpoint.
    """
    assert parse_retry_after(value) is None


def test_retry_after_date_without_a_zone_is_read_as_utc() -> None:
    """A zoneless HTTP-date is UTC by spec, not local time.

    Treating it as local would skew the wait by the machine's UTC offset — up to
    half a day, and differently in CI than on a laptop.
    """
    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Thu, 30 Jul 2026 12:00:10", now=now) \
        == pytest.approx(10.0, abs=1.0)


# ---------------------------------------------------------------------------
# Which failures are retried
# ---------------------------------------------------------------------------
def test_429_is_retried_and_the_eventual_success_is_returned(slept) -> None:
    """The headline rule: a rate-limited call must recover, not fail the run.

    A search that dies on the first 429 loses the whole narrative's retrieval,
    so this is the behaviour the submission depends on.
    """
    opener = _Opener(_http_error(429), _http_error(429))

    result = urlopen_with_backoff("http://x/", opener=opener,
                                  sleep=slept.append)

    assert result == "OK"
    assert opener.calls == 3
    assert slept == [BASE_DELAY, BASE_DELAY * 2]


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_5xx_is_retried(code: int, slept) -> None:
    """Server-side transients get the same treatment as a 429."""
    opener = _Opener(_http_error(code))

    assert urlopen_with_backoff("http://x/", opener=opener,
                               sleep=slept.append) == "OK"
    assert opener.calls == 2


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_other_4xx_raises_immediately(code: int, slept) -> None:
    """A 401 is a missing token and a 404 a missing docid — neither improves.

    Retrying them would waste the shared endpoint's allowance and delay the real
    error by the full backoff schedule, so they must surface on attempt one.
    """
    opener = _Opener(_http_error(code))

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urlopen_with_backoff("http://x/", opener=opener, sleep=slept.append)

    assert excinfo.value.code == code
    assert opener.calls == 1
    assert slept == [], "a non-retryable status must not sleep"


@pytest.mark.parametrize("err", [
    pytest.param(urllib.error.URLError("connection refused"), id="urlerror"),
    pytest.param(socket.timeout("timed out"), id="socket-timeout"),
    pytest.param(TimeoutError("timed out"), id="builtin-timeout"),
])
def test_connection_level_failures_are_retried(err: BaseException, slept) -> None:
    """A dropped connection to a service we do not control is transient."""
    opener = _Opener(err)

    assert urlopen_with_backoff("http://x/", opener=opener,
                               sleep=slept.append) == "OK"
    assert opener.calls == 2


def test_http_error_is_matched_before_url_error(slept) -> None:
    """``HTTPError`` subclasses ``URLError``, so branch order is load-bearing.

    If the ``URLError`` branch came first it would swallow every ``HTTPError``,
    and a ``404`` would be retried four times as though it were a network drop.
    """
    opener = _Opener(_http_error(404))

    with pytest.raises(urllib.error.HTTPError):
        urlopen_with_backoff("http://x/", opener=opener, sleep=slept.append)

    assert slept == []


# ---------------------------------------------------------------------------
# The schedule, and its bounds
# ---------------------------------------------------------------------------
def test_retry_after_overrides_our_exponential_guess(slept) -> None:
    """When the server states a wait, honour it instead of our own schedule."""
    opener = _Opener(_http_error(429, retry_after="7"))

    urlopen_with_backoff("http://x/", opener=opener, sleep=slept.append)

    assert slept == [7.0]


def test_a_huge_retry_after_is_capped(slept) -> None:
    """A server asking for an hour must not stall the run for an hour.

    Better to give up after ``MAX_DELAY`` and let the caller fail loudly than to
    have a batch job appear hung.
    """
    opener = _Opener(_http_error(429, retry_after="3600"))

    urlopen_with_backoff("http://x/", opener=opener, sleep=slept.append)

    assert slept == [MAX_DELAY]


def test_backoff_is_exponential_and_bounded(slept) -> None:
    """Delays double, and attempts stop at ``MAX_RETRIES``.

    The bound is what keeps a genuine outage from becoming an unbounded loop
    against the shared API.
    """
    opener = _Opener(*[_http_error(503) for _ in range(MAX_RETRIES + 1)])

    with pytest.raises(urllib.error.HTTPError):
        urlopen_with_backoff("http://x/", opener=opener, sleep=slept.append)

    assert opener.calls == MAX_RETRIES + 1
    assert slept == [1.0, 2.0, 4.0, 8.0][:MAX_RETRIES]
    # The last attempt must not be followed by a pointless sleep.
    assert len(slept) == MAX_RETRIES


def test_exhausted_retries_reraise_the_last_error(slept) -> None:
    """An outage must fail loudly, not be smoothed into an empty result.

    A swallowed failure here would show up as a narrative with no retrieval —
    silently scoring zero instead of alerting us.
    """
    opener = _Opener(*[_http_error(503) for _ in range(MAX_RETRIES + 1)])

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urlopen_with_backoff("http://x/", opener=opener, sleep=slept.append)

    assert excinfo.value.code == 503


def test_max_retries_zero_makes_a_single_attempt(slept) -> None:
    """``max_retries=0`` means "try once" — used by health checks.

    The skill requires the health endpoint be probed one-shot rather than
    retried, so off-by-one here would violate it.
    """
    opener = _Opener(_http_error(429))

    with pytest.raises(urllib.error.HTTPError):
        urlopen_with_backoff("http://x/", opener=opener, max_retries=0,
                             sleep=slept.append)

    assert opener.calls == 1
    assert slept == []


def test_a_first_attempt_success_never_sleeps(slept) -> None:
    """The happy path must add zero latency — this runs on every search."""
    opener = _Opener()

    assert urlopen_with_backoff("http://x/", opener=opener,
                               sleep=slept.append) == "OK"
    assert opener.calls == 1
    assert slept == []


def test_timeout_is_forwarded_to_the_opener() -> None:
    """The caller's timeout must survive the wrapper.

    ``fetch_doc`` and the search clients pass their own; dropping it would
    silently fall back to urllib's (no timeout at all), so a hung endpoint would
    hang the run forever.
    """
    seen: list[float | None] = []

    def opener(req: Any, timeout: float | None = None) -> str:
        seen.append(timeout)
        return "OK"

    urlopen_with_backoff("http://x/", timeout=12.5, opener=opener)

    assert seen == [12.5]
