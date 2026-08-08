"""Bounded retry/backoff for the shared ClimbMix HTTP endpoints.

The ``pyserini-rest-api`` skill (v0.3.0, "Request Pacing and Rate Limits") makes
this mandatory, not optional: the API is shared infrastructure, so a client must
back off on ``429`` rather than retry harder, and must never tight-loop on a
failing request. Its other rules — at most one in-flight request per worker, a
fixed modest worker pool — we already satisfy by construction (every client here
is a synchronous ``urlopen``; the pools in ``utils.search`` and ``agent_harness``
cap at 2 and 8 against an allowance of about a dozen).

Every hosted call in ``src/`` routes through this, so the policy lives in one
place instead of five slightly-different retry loops:

- ``utils.search_dense.post_json`` — dense, and via it sparse + SSR
- ``utils.search_pyserini._get_json``
- ``utils.fetch_doc.fetch_doc``
- ``tools.search_boolean_tool._post``
- ``agent_harness.tools.get_documents._fetch_one``

What is retried, and what deliberately is not:

- ``429`` and ``5xx`` — transient by definition. ``Retry-After`` wins when the
  server sends one (both the delay-seconds and HTTP-date forms), else exponential
  backoff.
- socket timeouts and connection-level ``URLError`` — a dropped connection to a
  service we do not control.
- **Not** any other ``4xx``. A ``401`` is a missing token and a ``404`` is a
  missing docid; retrying either just wastes the endpoint's capacity and delays
  the real error. They raise on the first attempt.

After ``max_retries`` retries the last error is re-raised, so a genuine outage
still fails loudly instead of being smoothed into an empty result.
"""
from __future__ import annotations

import email.utils
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

# Exponential backoff base and ceiling, per the skill's "for example 1s, 2s, 4s,
# capped at 60s".
BASE_DELAY = 1.0
MAX_DELAY = 60.0
MAX_RETRIES = 4

# 429 is the rate-limit signal the skill names; anything 5xx is a server-side
# transient. Both are worth waiting out; no other status is.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 507, 509})

# Indirection so a test can neutralize the waiting without monkeypatching
# `time.sleep` process-wide, and without threading a `sleep=` argument through
# five clients that have no business exposing one. Patch
# ``utils.http_retry._sleep``.
_sleep = time.sleep


def parse_retry_after(value: str | None, *, now: datetime | None = None
                      ) -> float | None:
    """Seconds to wait per a ``Retry-After`` header, or ``None`` if unusable.

    The header has two documented forms and real services send both: a
    delay-seconds integer (``Retry-After: 30``) and an HTTP-date
    (``Retry-After: Wed, 21 Oct 2026 07:28:00 GMT``). Honouring only the integer
    form — the easy half — would silently fall through to our own backoff exactly
    when a server has told us precisely how long it needs.

    A date already in the past yields ``0.0`` (retry now, do not wait); an
    unparseable value yields ``None`` so the caller falls back to exponential
    backoff rather than treating a malformed header as "wait zero".
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:  # an HTTP-date without a zone is UTC by spec
        when = when.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return max(0.0, (when - reference).total_seconds())


def _backoff_delay(attempt: int) -> float:
    """Exponential delay for a zero-based retry index, capped at ``MAX_DELAY``."""
    return min(MAX_DELAY, BASE_DELAY * (2 ** attempt))


def urlopen_with_backoff(req: urllib.request.Request | str, *,
                         timeout: float = 30.0,
                         max_retries: int = MAX_RETRIES,
                         sleep: Callable[[float], None] | None = None,
                         opener: Callable[..., Any] | None = None) -> Any:
    """``urlopen`` with bounded backoff on ``429``/``5xx``/timeouts.

    Returns the response object, which the caller must close (every call site
    here already uses a ``with`` block). Re-raises the final error once retries
    are exhausted.

    ``sleep`` and ``opener`` are injected so tests can assert the delay schedule
    without actually waiting — a real-sleep test suite for a 1/2/4/8s schedule
    would add 15 seconds to a 10-second run.
    """
    # Both callables are resolved per call rather than defaulted in the
    # signature: a default argument binds at import time, so it would bypass a
    # test (or tests/dummy_api/conftest.py) monkeypatching
    # `urllib.request.urlopen` — or `_sleep`, which the client call sites reach
    # only through this module-level name.
    open_url = opener or urllib.request.urlopen
    wait = sleep or _sleep
    last_error: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return open_url(req, timeout=timeout)
        except urllib.error.HTTPError as err:
            if err.code not in RETRY_STATUSES:
                raise
            last_error = err
            retry_after = parse_retry_after(err.headers.get("Retry-After")
                                            if err.headers else None)
            delay = retry_after if retry_after is not None else _backoff_delay(attempt)
        except (urllib.error.URLError, socket.timeout, TimeoutError) as err:
            # URLError covers DNS failure and connection refused/reset. Note
            # HTTPError subclasses URLError, so this must stay the later branch.
            last_error = err
            delay = _backoff_delay(attempt)

        if attempt >= max_retries:
            break
        wait(min(MAX_DELAY, delay))

    assert last_error is not None  # only reachable after an except branch
    raise last_error
