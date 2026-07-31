"""The Bedrock Converse judge and the `judge-pool` driver (PLAN §5.4, §5.8).

This module is where the experiment spends money, so every design choice below
exists to make that spend visible, bounded, and never paid for twice.

**The single writer thread is the load-bearing invariant.** Converse calls run on
a `ThreadPoolExecutor`; each finished attempt is pushed onto a `queue.Queue`; and
**one dedicated writer thread** is the sole consumer. That one thread, and only
that thread:

1. appends to the append-only judgment log (so no locking, no shared handle, and
   the log's line order is a real serialization of what happened);
2. calls `CostMeter.add(...)` (so the running dollar total has exactly one
   mutator — no lock, no torn float, PLAN §5.7);
3. calls `BudgetGuard.check()` (so the ceiling is evaluated against a total that
   cannot be mid-update).

Log integrity, meter correctness, and budget enforcement therefore all rest on
that thread staying single. **Do not parallelize it, and do not touch the meter
or the log from a worker.**

**There is no unmetered path to the model.** `judge-pool` refuses to start if
`pricing.py` cannot be imported (PLAN §9: metering must be integrated *before* a
single real Converse call), and every attempt — success, throttle, parse failure,
truncation — is logged with its `usage` and `cost` blocks, because a call that
returned garbage was still billed.

**Model-call gotchas that cost real debugging time** (PLAN §1, all `[measured]`):

- Bare model id `openai.gpt-oss-20b-1:0`. The `au.*`/`us.*` inference-profile
  prefixes raise `ValidationException` for this model.
- `maxTokens=1024`, not 512: output up to 648 tokens was observed, and truncation
  lands *before* the `text` block.
- gpt-oss-20b emits a `reasoningContent` block **before** `text`, so
  `content[0]["text"]` raises `KeyError` on a perfectly good response.
  `parse_grade` iterates.
- There is **no `ExpiredTokenException` attribute on the client**, so credential
  expiry is caught as `ClientError` and dispatched on
  `response["Error"]["Code"]`. Transport timeouts come from
  `botocore.exceptions`, not from the client's `exceptions` namespace.

`boto3` is imported **only inside `BedrockJudge._client()`** — that is what keeps
`tests/bm25_tune/` hermetic with no dependency group (PLAN §4.1/§7.3), and why
`classify_error` inspects exception attributes rather than exception classes.
"""
from __future__ import annotations

import os
import queue
import random
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from . import store
from .logging_setup import Heartbeat, HeartbeatStats, get_logger
from .prompts import FACET_RE, GRADE_RE, PromptSpec, get_prompt

log = get_logger("judge")

# -- model call defaults (PLAN §1/§5.4) --------------------------------------
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_ATTEMPTS = 8
#: botocore's default HTTP connection pool is 10; a pool with more worker
#: threads than that logs "Connection pool is full, discarding connection" and
#: churns TCP/TLS setup on every discarded connection (harmless, but noisy and
#: slightly wasteful). The driver passes its `concurrency` so the pool matches
#: the number of in-flight Converse calls. Falls back to boto3's default of 10.
DEFAULT_MAX_POOL_CONNECTIONS = 10

# -- retry policy ------------------------------------------------------------
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 30.0

#: Appended verbatim on the one parse-failure retry (PLAN §5.4).
PARSE_RETRY_INSTRUCTION = "Reply with exactly one line: ##final score: <0-3>"

#: PLAN §5.4: >1 % parse failures aborts the run.
PARSE_FAIL_ABORT_RATIO = 0.01
#: ...but only once enough calls exist for a ratio to mean anything. The plan
#: does not name a floor; without one the very first call failing reads as 100 %
#: and would abort a healthy run on a single flake. 100 calls is ~$0.016 at the
#: measured rate — cheap enough to be worth spending to avoid a false abort, and
#: small enough that a genuine prompt/model regression still trips in seconds.
PARSE_FAIL_MIN_CALLS = 100

#: Typical projected total spend for the whole plan (PLAN §6.2b: $7.75 typical,
#: $13.53 worst case). Used ONLY to phrase the budget-trip message as a share of
#: whatever the live cap is, so lowering the cap cannot leave a stale percentage
#: behind in the message an operator reads when the run stops.
PLAN_EXPECTED_SPEND_USD = 8.0

# -- error classes (defensive strings, matched case-sensitively) --------------
THROTTLE_CODES = frozenset({
    "ThrottlingException", "TooManyRequestsException", "Throttling",
    "RequestLimitExceeded", "ProvisionedThroughputExceededException",
    "SlowDown", "LimitExceededException", "ServiceQuotaExceededException",
})
#: PLAN §5.4 + the brief: dispatch on `response['Error']['Code']`, because the
#: client object has no `ExpiredTokenException` attribute to catch.
EXPIRED_CODES = frozenset({
    "ExpiredTokenException", "ExpiredToken", "InvalidClientTokenId",
    "UnrecognizedClientException",
})
#: Transport-level failures. These come from `botocore.exceptions`, never from
#: `client.exceptions`, so they are matched by class *name* — no boto3 import.
TIMEOUT_EXC_NAMES = frozenset({
    "ReadTimeoutError", "ConnectTimeoutError", "ConnectionClosedError",
    "EndpointConnectionError", "ConnectionError", "IncompleteReadError",
})
RETRYABLE_SERVER_CODES = frozenset({
    "ServiceUnavailableException", "InternalServerException",
    "ModelTimeoutException", "ModelNotReadyException",
})

ERROR_THROTTLE = "throttle"
ERROR_EXPIRED = "expired_token"
ERROR_TIMEOUT = "timeout"
ERROR_SERVER = "server_error"
ERROR_PARSE = "parse_failure"
ERROR_OTHER = "other"
RETRYABLE_ERRORS = frozenset({ERROR_THROTTLE, ERROR_TIMEOUT, ERROR_SERVER})

# -- drain triggers (PLAN §5.8's table) --------------------------------------
TRIGGER_COMPLETE = "complete"
TRIGGER_CRED = "cred_expiry"
TRIGGER_BUDGET = "budget"
TRIGGER_SIGINT = "sigint"
TRIGGER_SIGTERM = "sigterm"
TRIGGER_PARSE_FAIL = "parse_fail"
TRIGGER_WRITER_ERROR = "writer_error"

#: trigger -> (log prefix, exit code). The exit codes are `cli.py`'s constants,
#: duplicated as literals here only so this module stays importable on its own;
#: `test_judge.py` pins them against `cli.py`.
#:
#: `parse_fail` and `writer_error` map to the generic `1` because PLAN §5.7's
#: table reserves 3/4/5/6/130/143 for the conditions it names and gives no code
#: to either — "unexpected" is the honest classification, and both print a
#: diagnosis rather than relying on the code alone.
TRIGGER_EXITS: dict[str, tuple[str, int]] = {
    TRIGGER_COMPLETE: ("[SUMMARY]", 0),
    TRIGGER_CRED: ("[CRED]", 3),
    TRIGGER_BUDGET: ("[BUDGET]", 5),
    TRIGGER_SIGINT: ("[SIGNAL]", 130),
    TRIGGER_SIGTERM: ("[SIGNAL]", 143),
    TRIGGER_PARSE_FAIL: ("[PARSE-FAIL]", 1),
    TRIGGER_WRITER_ERROR: ("[JUDGE]", 1),
}

DRAIN_TIMEOUT_S = 60.0
#: How long the writer waits on an empty queue before checking the fsync clock.
WRITER_POLL_S = 0.5


class CredentialsExpired(RuntimeError):
    """The SSO session token expired mid-run (PLAN §5.4/R3).

    Raised out of a worker and up to the driver, which drains and exits 3. Not
    retried in-process: env-var credentials cannot self-heal inside a running
    process, and a polling loop would burn hours of wall clock while the operator
    is not watching. Resume is free — every completed judgment is already in the
    cache, so re-running the same command judges only what is left.
    """


class ParseFailureRateExceeded(RuntimeError):
    """More than 1 % of calls produced no parsable grade (PLAN §5.4).

    A rate this high is a prompt or model regression, not noise, and continuing
    would spend hours producing a label set with holes in it.
    """


class PricingUnavailable(RuntimeError):
    """`pricing.py` (WP3b) is not importable, so nothing may call Bedrock.

    PLAN §9 is explicit: metering is integrated **before** `judge-pool` makes a
    single real call — there must be no unmetered path to the model. Refusing to
    start is the only correct behaviour; the alternative (judge now, account
    later) is exactly how a spend ceiling becomes an aspiration.
    """


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_grade(content_blocks: Sequence[dict]
                ) -> tuple[int | None, str, str, str | None]:
    """`(grade, text, reasoning, facet)` from a Converse `content` list.

    **Iterates** the blocks and concatenates every `text` value and every
    `reasoningContent.reasoningText.text`. gpt-oss-20b puts its reasoning block
    *first*, so the idiomatic `content[0]["text"]` raises `KeyError` on a
    perfectly good response — the single most expensive mistake available here,
    because it looks like a model failure rather than a parsing bug.

    The grade is the **last** `##final score: <0-3>` match in the text blocks:
    the model sometimes restates the format line before committing, and the last
    statement is the answer. `##facet:` is captured when present (only
    `facet-name-v1` asks for one) and is metadata — never required, and its
    absence never fails a judgment.
    """
    texts: list[str] = []
    reasonings: list[str] = []
    for block in content_blocks or []:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            texts.append(text)
        reasoning = block.get("reasoningContent")
        if isinstance(reasoning, dict):
            inner = reasoning.get("reasoningText")
            if isinstance(inner, dict) and isinstance(inner.get("text"), str):
                reasonings.append(inner["text"])
            elif isinstance(reasoning.get("text"), str):
                reasonings.append(reasoning["text"])
    joined = "\n".join(texts)
    matches = list(GRADE_RE.finditer(joined))
    grade = int(matches[-1].group(1)) if matches else None
    facet_match = FACET_RE.search(joined)
    facet = facet_match.group(1).strip() if facet_match else None
    return grade, joined, "\n".join(reasonings), facet


def response_content(response: dict) -> list[dict]:
    """`output.message.content`, defensively — `[]` rather than a `KeyError`.

    A malformed envelope must degrade to `parse_failure` (which is logged, costed,
    and retried once) instead of killing the writer thread and taking every
    already-billed in-flight judgment with it.
    """
    output = response.get("output") if isinstance(response, dict) else None
    message = output.get("message") if isinstance(output, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return list(content) if isinstance(content, list) else []


def response_usage(response: dict) -> dict | None:
    """The `usage` block, normalized to `{inputTokens, outputTokens}`.

    Kept even when Bedrock returns extra keys, and returned as `None` when
    absent: `None` means "this call was not billed", which is a materially
    different claim from "billed 0 tokens" and must not be conflated in the
    ledger (PLAN §5.3).
    """
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    out = {"inputTokens": int(usage.get("inputTokens") or 0),
           "outputTokens": int(usage.get("outputTokens") or 0)}
    if usage.get("totalTokens") is not None:
        out["totalTokens"] = int(usage["totalTokens"])
    return out


def classify_error(exc: Exception) -> str:
    """`"throttle" | "expired_token" | "timeout" | "server_error" | "other"`.

    Reads **exception attributes**, never exception classes, so it needs no boto3
    import and is therefore testable with a plain object carrying
    `response["Error"]["Code"]` (PLAN §5.4/§7.3). That is not just a testing
    convenience: `ClientError` subclasses are generated at runtime from the
    service model, so catching them by name is unreliable anyway, and the client
    has **no `ExpiredTokenException` attribute at all**.

    Extends the plan's three-way return with `timeout` and `server_error`. Both
    are retryable-but-not-throttling: folding them into `"other"` would abandon a
    pair on a transient socket hiccup, and folding them into `"throttle"` would
    inflate the throttle counter the operator uses to decide whether to lower
    concurrency.
    """
    name = type(exc).__name__
    if name in TIMEOUT_EXC_NAMES:
        return ERROR_TIMEOUT
    response = getattr(exc, "response", None)
    code = ""
    status = 0
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            code = str(error.get("Code") or "")
        metadata = response.get("ResponseMetadata")
        if isinstance(metadata, dict):
            try:
                status = int(metadata.get("HTTPStatusCode") or 0)
            except (TypeError, ValueError):
                status = 0
    if code in EXPIRED_CODES or name in EXPIRED_CODES:
        return ERROR_EXPIRED
    if code in THROTTLE_CODES or name in THROTTLE_CODES or status == 429:
        return ERROR_THROTTLE
    if code in RETRYABLE_SERVER_CODES or name in RETRYABLE_SERVER_CODES:
        return ERROR_SERVER
    if status in (500, 502, 503, 504):
        return ERROR_SERVER
    return ERROR_OTHER


def backoff_delay(attempt: int, *, base: float = BACKOFF_BASE_S,
                  cap: float = BACKOFF_CAP_S,
                  rng: random.Random | None = None) -> float:
    """Exponential backoff with **full jitter**: `uniform(0, min(cap, base·2^(n-1)))`.

    Full jitter rather than a fixed exponential delay because 16 workers that
    throttle together would otherwise retry in lockstep and re-throttle forever;
    jitter spreads them. `attempt` is 1-based, so the first retry waits within
    [0, 1 s] and the sequence saturates at the 30 s cap.
    """
    exponential = min(cap, base * (2 ** max(0, attempt - 1)))
    return (rng or random).uniform(0.0, exponential)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class AttemptResult:
    """One Converse call — billed whether or not it produced a grade.

    Exists because PLAN §5.3 requires **every attempt** in the log: a throttle,
    the parse failure after it, and the retry that finally worked are three
    records with three cost blocks. Summing only the successes would under-report
    the experiment's real spend.
    """

    attempt: int
    prompt: str
    grade: int | None = None
    raw_text: str = ""
    raw_reasoning: str = ""
    facet: str | None = None
    stop_reason: str = ""
    usage: dict | None = None
    latency_ms: int = 0
    error: str | None = None

    @property
    def billed(self) -> bool:
        """True when the call reached the model, so `usage`/`cost` are real."""
        return self.usage is not None


@dataclass
class JudgeResult:
    """The outcome of judging one pair, plus the full attempt history.

    `grade is None` is a legitimate, non-fatal outcome (`error="parse_failure"`):
    such pairs are excluded from the qrels and counted in the manifest rather
    than crashing the run (PLAN §5.4). `history` is what the writer thread turns
    into log records — one per attempt.
    """

    grade: int | None
    raw_text: str
    raw_reasoning: str
    facet: str | None
    stop_reason: str
    usage: dict | None
    latency_ms: int
    attempts: int
    error: str | None
    history: list[AttemptResult] = field(default_factory=list)

    @classmethod
    def from_history(cls, history: Sequence[AttemptResult]) -> "JudgeResult":
        """Build from the attempt list, taking the final attempt as the outcome."""
        final = history[-1]
        return cls(grade=final.grade, raw_text=final.raw_text,
                   raw_reasoning=final.raw_reasoning, facet=final.facet,
                   stop_reason=final.stop_reason, usage=final.usage,
                   latency_ms=sum(a.latency_ms for a in history),
                   attempts=len(history), error=final.error,
                   history=list(history))


# ---------------------------------------------------------------------------
# The judge
# ---------------------------------------------------------------------------
class BedrockJudge:
    """One Converse-calling judge, shared across worker threads.

    boto3 clients are thread-safe **for calls** (not for construction), so one
    client serves the whole pool; `_client()` builds it lazily under a lock and is
    the only place `boto3` is imported.

    `converse` may be injected, which is how the whole offline suite exercises
    parsing, retries, backoff, and credential handling with no boto3 and no
    network (PLAN §7.3).
    """

    def __init__(self, model_id: str, region: str, *,
                 max_tokens: int = DEFAULT_MAX_TOKENS,
                 temperature: float = DEFAULT_TEMPERATURE,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 max_pool_connections: int = DEFAULT_MAX_POOL_CONNECTIONS,
                 converse: Callable[..., dict] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 rng: random.Random | None = None) -> None:
        if model_id.startswith(("au.", "us.", "eu.", "apac.")):
            # PLAN §1 [measured]: the inference-profile prefixes raise
            # ValidationException for this model. Failing here beats failing on
            # call 1 of 13,000 after a 10-minute pool build.
            raise ValueError(
                f"model_id {model_id!r} carries an inference-profile prefix; "
                "gpt-oss-20b needs the BARE id (openai.gpt-oss-20b-1:0) or "
                "Bedrock raises ValidationException")
        self.model_id = model_id
        self.region = region
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.max_attempts = max(1, int(max_attempts))
        self.max_pool_connections = max(1, int(max_pool_connections))
        self._injected_converse = converse
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.Random()
        self._client_obj: object | None = None
        self._client_lock = threading.Lock()
        self._client_generation = 0
        #: Counters the driver folds into the heartbeat and the manifest.
        self.throttles = 0
        self.timeouts = 0
        self.parse_retries = 0

    # -- transport ----------------------------------------------------------
    def _client(self):
        """The `bedrock-runtime` client. **The only `boto3` import in the module.**"""
        with self._client_lock:
            if self._client_obj is None:
                import boto3  # noqa: PLC0415 - deliberately function-local
                from botocore.config import \
                    Config  # noqa: PLC0415 - function-local, with boto3

                # Size the HTTP pool to the worker count so a pool wider than
                # botocore's default 10 does not discard (and re-establish)
                # connections on every extra in-flight Converse call.
                self._client_obj = boto3.client(
                    "bedrock-runtime", region_name=self.region,
                    config=Config(max_pool_connections=self.max_pool_connections))
                self._client_generation += 1
            return self._client_obj

    def _recreate_client(self) -> None:
        """Drop the cached client so the next call re-resolves credentials.

        Covers the one refreshable case: a profile or credential *file* that the
        operator refreshed while the job ran. Env-var credentials cannot be
        refreshed inside a live process, which is why a failed recreate escalates
        to `CredentialsExpired` and exit-and-resume rather than a polling loop.
        """
        with self._client_lock:
            self._client_obj = None

    def _converse(self, prompt: str) -> dict:
        """One Converse call with PLAN §5.4's exact inference config."""
        if self._injected_converse is not None:
            call = self._injected_converse
        else:
            call = self._client().converse
        return call(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": self.max_tokens,
                             "temperature": self.temperature},
        )

    # -- one judgment -------------------------------------------------------
    def judge(self, prompt: str) -> JudgeResult:
        """Judge one rendered prompt, retrying per PLAN §5.4.

        Retry policy, and why each branch exists:

        - **throttle / timeout / 5xx** — backoff with full jitter, up to
          `max_attempts`. Every attempt is recorded (and costed if it reached the
          model).
        - **credential expiry** — one client recreate, then `CredentialsExpired`
          up to the driver, which drains and exits 3.
        - **parse failure** — exactly one retry with
          `PARSE_RETRY_INSTRUCTION` appended; after that, `grade=None` with
          `error="parse_failure"` is *returned normally*. A pair we cannot parse
          must not crash a multi-hour job over the 12,999 pairs that are fine.
        - **anything else** — recorded and returned as `error="other"`, again
          without crashing the run.
        """
        history: list[AttemptResult] = []
        current_prompt = prompt
        parse_retry_used = False
        cred_retry_used = False
        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            started = self._clock()
            try:
                response = self._converse(current_prompt)
            except Exception as exc:  # noqa: BLE001 - classified below
                kind = classify_error(exc)
                elapsed_ms = int((self._clock() - started) * 1000)
                history.append(AttemptResult(attempt=attempt,
                                             prompt=current_prompt,
                                             latency_ms=elapsed_ms,
                                             error=kind))
                if kind == ERROR_EXPIRED:
                    if not cred_retry_used:
                        cred_retry_used = True
                        log.warning("[CRED] %s on attempt %d — recreating the "
                                    "client once in case a profile/credential "
                                    "file was refreshed", type(exc).__name__,
                                    attempt)
                        self._recreate_client()
                        continue
                    raise CredentialsExpired(str(exc)) from exc
                if kind in RETRYABLE_ERRORS and attempt < self.max_attempts:
                    if kind == ERROR_THROTTLE:
                        self.throttles += 1
                    elif kind == ERROR_TIMEOUT:
                        self.timeouts += 1
                    delay = backoff_delay(attempt, rng=self._rng)
                    log.warning("[THROTTLE] attempt=%d kind=%s sleep=%.1fs",
                                attempt, kind, delay)
                    self._sleep(delay)
                    continue
                log.warning("[JUDGE] attempt=%d failed (%s: %s)", attempt,
                            type(exc).__name__, exc)
                return JudgeResult.from_history(history)

            elapsed_ms = int((self._clock() - started) * 1000)
            grade, text, reasoning, facet = parse_grade(
                response_content(response))
            stop_reason = str(response.get("stopReason") or "")
            result = AttemptResult(
                attempt=attempt, prompt=current_prompt, grade=grade,
                raw_text=text, raw_reasoning=reasoning, facet=facet,
                stop_reason=stop_reason, usage=response_usage(response),
                latency_ms=elapsed_ms)
            if grade is None:
                # The maxTokens trap: an empty `text` block with
                # `stopReason == "max_tokens"` means the model spent its whole
                # budget in `reasoningContent` and never emitted the score line.
                # It is a parse failure, not an empty answer, and it is BILLED.
                result.error = ERROR_PARSE
                history.append(result)
                if stop_reason == "max_tokens":
                    log.warning("[PARSE-FAIL] attempt=%d truncated at "
                                "max_tokens (%d) before the text block; "
                                "reasoning=%d chars", attempt, self.max_tokens,
                                len(reasoning))
                else:
                    log.warning("[PARSE-FAIL] attempt=%d unparsable text=%r",
                                attempt, text[:200])
                if not parse_retry_used and attempt < self.max_attempts:
                    parse_retry_used = True
                    self.parse_retries += 1
                    current_prompt = f"{prompt}\n{PARSE_RETRY_INSTRUCTION}"
                    continue
                return JudgeResult.from_history(history)
            history.append(result)
            return JudgeResult.from_history(history)

        # Attempts exhausted: the last recorded attempt carries the reason.
        return JudgeResult.from_history(history)


# ---------------------------------------------------------------------------
# Pool pairs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class JudgePair:
    """One (topic, chunk) pair to judge, with everything the prompt needs.

    Deliberately self-contained: the driver never reaches back into the index or
    the labeled file, so `judge-pool` (WP3) is testable and reviewable without
    `searcher.py` (WP2) or a JVM. `narrative` and `keyword` are both carried
    because `PromptSpec.query_slot` — not the driver — decides which one fills
    `{q}`; getting that backwards would mislabel a whole prompt version's cache.
    """

    topic_id: str
    chunk_id: str
    narrative: str
    keyword: str
    passage_text: str

    @property
    def parent_docid(self) -> str:
        from .extract import parent_docid

        return parent_docid(self.chunk_id)


def pending_pairs(pairs: Sequence[JudgePair], cache: "store.JudgmentCache",
                  prompt_version: str) -> tuple[list[JudgePair], int]:
    """`(uncached_pairs, cache_hits)` under `prompt_version`.

    Module-level so the **pre-flight estimate and the judging loop count the same
    calls**. The pre-flight (PLAN §5.7 layer 1) runs on the main thread before any
    worker exists and must estimate the calls that will actually be *made*, not
    the size of the pool — a resumed run whose pool is 95 % cached would otherwise
    be refused on an estimate 20× its real cost.
    """
    pending: list[JudgePair] = []
    hits = 0
    for pair in pairs:
        key = store.jkey(prompt_version, pair.topic_id, pair.chunk_id)
        if cache.get(key) is not None:
            hits += 1
        else:
            pending.append(pair)
    return pending, hits


def sample_pairs(pairs: Sequence[JudgePair], n: int, *,
                 seed: int = 13) -> list[JudgePair]:
    """`--pilot N`: N pairs spread **evenly across topics** (PLAN §5.7).

    Not the first N. The pool is built in topic order, so a head slice would
    cover ~2 % of the topics and bias the measured token means toward whichever
    narratives sort first — and those means are the basis every later pre-flight
    projection uses. Round-robin over shuffled per-topic queues instead, so the
    cost basis is representative of the pool it is extrapolated to.
    """
    if n >= len(pairs):
        return list(pairs)
    by_topic: dict[str, list[JudgePair]] = {}
    for pair in pairs:
        by_topic.setdefault(pair.topic_id, []).append(pair)
    rng = random.Random(seed)
    queues: dict[str, list[JudgePair]] = {}
    for topic_id in sorted(by_topic):
        bucket = sorted(by_topic[topic_id], key=lambda p: p.chunk_id)
        rng.shuffle(bucket)
        queues[topic_id] = bucket
    picked: list[JudgePair] = []
    topic_ids = sorted(queues)
    while len(picked) < n:
        drew = False
        for topic_id in topic_ids:
            if len(picked) >= n:
                break
            bucket = queues[topic_id]
            if bucket:
                picked.append(bucket.pop())
                drew = True
        if not drew:
            break
    picked.sort(key=lambda p: (p.topic_id, p.chunk_id))
    return picked


# ---------------------------------------------------------------------------
# Pricing (WP3b) — imported lazily, never bypassed
# ---------------------------------------------------------------------------
def load_pricing():
    """Import `pricing` (WP3b) or raise `PricingUnavailable`.

    Lazy so this module and its tests do not depend on WP3b's landing order, and
    **never optional**: `judge-pool` calls this before it builds a client, so a
    missing metering layer stops the run instead of producing unaccounted spend
    (PLAN §9). There is deliberately no `--no-metering` escape hatch.
    """
    try:
        from . import pricing  # noqa: PLC0415 - deliberately function-local
    except ImportError as exc:
        raise PricingUnavailable(
            "bm25tune.pricing is not importable, so there is no metered path "
            f"to Bedrock ({exc}). judge-pool refuses to run un-metered: the "
            "operator-set ceiling and the report's cost analysis both read "
            "from the meter (PLAN §5.7/§9). Land WP3b (pricing.py) "
            "first.") from exc
    missing = [name for name in ("load_rates", "call_cost", "CostMeter",
                                 "BudgetGuard", "BudgetExceeded",
                                 "build_cost_report", "write_cost_artifacts")
               if not hasattr(pricing, name)]
    if missing:
        raise PricingUnavailable(
            f"bm25tune.pricing is missing {', '.join(missing)} — the PLAN §5.7 "
            "interface is incomplete, so spend could not be recorded or "
            "capped. judge-pool refuses to run.")
    return pricing


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------
@dataclass
class PoolStats:
    """Everything the `[SUMMARY]`/manifest lines report about a judge run."""

    total: int = 0
    cache_hits: int = 0
    judged: int = 0
    graded: int = 0
    parse_failures: int = 0
    other_errors: int = 0
    throttles: int = 0
    cred_expiries: int = 0
    records: int = 0
    billed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    spent_usd: float = 0.0
    trigger: str = TRIGGER_COMPLETE
    exit_code: int = 0

    def to_json(self) -> dict[str, object]:
        return {
            "total": self.total, "cache_hits": self.cache_hits,
            "judged": self.judged, "graded": self.graded,
            "parse_failures": self.parse_failures,
            "other_errors": self.other_errors, "throttles": self.throttles,
            "cred_expiries": self.cred_expiries, "records": self.records,
            "billed_calls": self.billed_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "spent_usd": round(self.spent_usd, 8),
            "trigger": self.trigger, "exit_code": self.exit_code,
        }


class JudgePoolDriver:
    """Judges a pooled pair list: thread pool in, one writer thread out.

    Lives here rather than in `cli.py` because the concurrency model, the log,
    the meter, and the drain are one mechanism — PLAN §5.4 and §5.8 describe the
    same thread. `cli.py` only builds the inputs and maps the returned exit code.

    **One drain routine, four triggers** (PLAN §5.8): credential expiry (3),
    `BudgetExceeded` (5), SIGINT (130), SIGTERM (143), plus the normal
    completion path — which runs the *same* `drain_and_checkpoint` code, so the
    shutdown sequence is exercised on every single run rather than only in the
    rare conditions where it matters. A shutdown path that only fires on failure
    is the code that rots.
    """

    def __init__(self, *, judge: BedrockJudge, spec: PromptSpec,
                 log_store: store.JudgmentLog, cache: store.JudgmentCache,
                 meter, guard, rates, pricing_mod,
                 run_id: str, stage: str, concurrency: int = 16,
                 snapshot_path: Path | None = None,
                 run_dir: Path | None = None,
                 heartbeat_interval: float = 60.0,
                 drain_timeout: float = DRAIN_TIMEOUT_S,
                 fsync_every_lines: int = store.FSYNC_EVERY_LINES,
                 fsync_every_seconds: float = store.FSYNC_EVERY_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.judge = judge
        self.spec = spec
        self.log_store = log_store
        self.cache = cache
        self.meter = meter
        self.guard = guard
        self.rates = rates
        self.pricing = pricing_mod
        self.run_id = run_id
        self.stage = stage
        self.concurrency = max(1, int(concurrency))
        self.snapshot_path = snapshot_path
        self.run_dir = run_dir
        self.heartbeat_interval = heartbeat_interval
        self.drain_timeout = drain_timeout
        self.checkpoint_every_lines = max(1, int(fsync_every_lines))
        self.checkpoint_every_seconds = float(fsync_every_seconds)
        self._clock = clock

        self.stats = PoolStats()
        self.hb_stats = HeartbeatStats(cap_usd=getattr(guard, "cap_usd", 0.0))
        #: Every attempt's `usage` block, in completion order — the input to
        #: WP3b's `pilot_basis`. Appended by the writer thread only, read by the
        #: main thread after the join, so it needs no lock. Kept in memory rather
        #: than re-scanned out of the log afterwards because `--pilot N`'s whole
        #: purpose is to report *this* invocation's measured token means, and a
        #: log scan would also pick up every earlier run's calls.
        self.usages: list[dict | None] = []
        #: Set by a signal handler, by the writer on `BudgetExceeded`, or by a
        #: worker's `CredentialsExpired`. The feeder checks it before every
        #: submit, so no new work starts once it is set.
        self.stop_requested = threading.Event()
        self.trigger: str | None = None
        self._queue: "queue.Queue[dict | None]" = queue.Queue()
        self._writer: threading.Thread | None = None
        self._writer_error: BaseException | None = None
        self._draining = False
        self._since_checkpoint = 0
        self._last_checkpoint = clock()
        self._prev_handlers: dict[int, object] = {}

    # -- signals ------------------------------------------------------------
    def install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers that only set a flag.

        **No I/O in the handler** (PLAN §5.8): a handler that tried to write the
        log or the ledger could re-enter a half-updated buffer and corrupt the
        very audit record the drain exists to preserve. So the handler sets the
        flag, and the main thread does the work.

        No-op off the main thread (a test, or a library embedding), where
        `signal.signal` raises.
        """
        def _handler(signum: int, _frame: object) -> None:
            if self._draining:
                # A second signal must not trap the operator behind a hung
                # Converse call. Immediate, no I/O, exit code already known.
                os._exit(TRIGGER_EXITS[self._trigger_for(signum)][1])
            self.trigger = self._trigger_for(signum)
            self.stop_requested.set()

        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                self._prev_handlers[signum] = signal.signal(signum, _handler)
            except (ValueError, OSError):  # not the main thread
                log.debug("[SIGNAL] could not install handler for %s", signum)

    def restore_signal_handlers(self) -> None:
        """Put the previous handlers back (so a test/CLI reuse is clean)."""
        for signum, previous in self._prev_handlers.items():
            try:
                signal.signal(signum, previous)  # type: ignore[arg-type]
            except (ValueError, OSError, TypeError):
                pass
        self._prev_handlers.clear()

    @staticmethod
    def _trigger_for(signum: int) -> str:
        return TRIGGER_SIGINT if signum == signal.SIGINT else TRIGGER_SIGTERM

    def request_stop(self, trigger: str) -> None:
        """Ask for a drain with `trigger`; the first request wins.

        First-wins because the trigger determines the exit code, and the *cause*
        is the first thing that went wrong — a budget stop that then hits a
        credential expiry while draining is still a budget stop.
        """
        if self.trigger is None:
            self.trigger = trigger
        self.stop_requested.set()

    # -- the writer thread --------------------------------------------------
    def _writer_loop(self) -> None:
        """Sole consumer of the record queue. See the module docstring.

        This thread is the *only* mutator of the log, the cache, the cost meter
        and the stats — which is precisely why no locks appear anywhere in this
        module's hot path. The 10-line/5-second cadence (PLAN §5.8) is applied to
        both the log fsync and the meter checkpoint together, so the ledger can
        never drift from the log by more than one window.
        """
        try:
            while True:
                try:
                    record = self._queue.get(timeout=WRITER_POLL_S)
                except queue.Empty:
                    # Awake anyway: this is why the time-based fsync branch is
                    # free (PLAN §5.8).
                    self.log_store.maybe_fsync()
                    self._maybe_checkpoint()
                    continue
                if record is None:
                    self._queue.task_done()
                    break
                try:
                    self._consume(record)
                finally:
                    self._queue.task_done()
        except BaseException as exc:  # noqa: BLE001 - reported to the driver
            # The writer dying silently would be the worst failure available
            # here: workers would keep calling (and billing) Bedrock while
            # nothing reached the log. So record it and demand a drain.
            self._writer_error = exc
            log.exception("[JUDGE] writer thread failed — draining. Every "
                          "record still queued is already-billed work that "
                          "will be lost; the pairs are re-judgable but re-paid.")
            self.request_stop(TRIGGER_WRITER_ERROR)

    def _consume(self, record: dict) -> None:
        """Persist one record, meter it, and check the budget. In that order.

        Order matters and is asserted by PLAN §5.7's reconciliation semantics:
        the **log is written first**, so after a crash the log can only be *ahead*
        of the ledger — a gap that self-heals on the next load. The reverse
        (ledger ahead of log) is unreachable by a crash and is therefore reported
        as an integrity error rather than papered over.
        """
        self.log_store.append(record)
        self.cache.note_appended(self.log_store.name)
        self.cache.ingest_record(record)
        self.stats.records += 1
        usage = record.get("usage")
        cost = record.get("cost")
        self.usages.append(usage)
        if usage:
            self.stats.billed_calls += 1
            self.stats.input_tokens += int(usage.get("inputTokens") or 0)
            self.stats.output_tokens += int(usage.get("outputTokens") or 0)
        self.meter.add(cost, usage, run_id=self.run_id, stage=self.stage)
        self.stats.spent_usd = float(self.meter.spent_usd())
        self.hb_stats.spent_usd = self.stats.spent_usd
        self._since_checkpoint += 1
        if self._since_checkpoint >= self.checkpoint_every_lines:
            self._checkpoint()
        else:
            self._maybe_checkpoint()
        try:
            self.guard.check()
        except self.pricing.BudgetExceeded as exc:
            # Raised on the writer thread, so it cannot propagate to the main
            # thread by itself (PLAN §5.7 layer 2). Flag it and keep consuming:
            # every queued record is already-billed work we want on disk.
            log.error("[BUDGET] %s", exc)
            self.request_stop(TRIGGER_BUDGET)
        self._check_parse_failures()

    def _maybe_checkpoint(self) -> None:
        if self._since_checkpoint == 0:
            return
        if self._clock() - self._last_checkpoint >= self.checkpoint_every_seconds:
            self._checkpoint()

    def _checkpoint(self) -> None:
        self.meter.checkpoint()
        self._since_checkpoint = 0
        self._last_checkpoint = self._clock()

    def _check_parse_failures(self) -> None:
        """Abort once >1 % of billed calls produced no grade (PLAN §5.4)."""
        if self.stats.billed_calls < PARSE_FAIL_MIN_CALLS:
            return
        ratio = self.stats.parse_failures / self.stats.billed_calls
        if ratio > PARSE_FAIL_ABORT_RATIO and self.trigger is None:
            log.error("[PARSE-FAIL] %d/%d billed calls (%.2f%%) produced no "
                      "parsable grade, over the %.0f%% abort threshold — this "
                      "is a prompt/model regression, not noise. Draining.",
                      self.stats.parse_failures, self.stats.billed_calls,
                      100.0 * ratio, 100.0 * PARSE_FAIL_ABORT_RATIO)
            self.request_stop(TRIGGER_PARSE_FAIL)

    # -- the work -----------------------------------------------------------
    def _judge_one(self, pair: JudgePair) -> tuple[JudgePair, JudgeResult]:
        """Worker body: render, call, return. Touches no shared state.

        Workers never write the log, the cache, or the meter — the writer thread
        does. That is the whole basis for this module being lock-free.
        """
        prompt = self.spec.render_pair(narrative=pair.narrative,
                                       keyword=pair.keyword,
                                       passage=pair.passage_text)
        return pair, self.judge.judge(prompt)

    def _records_for(self, pair: JudgePair,
                     result: JudgeResult) -> Iterator[dict]:
        """One log record per attempt, each with its own cost block.

        Costs are computed here from the attempt's own `usage` via WP3b's
        `call_cost` — never by hand, and never re-derived later from a running
        total (PLAN §5.3). An attempt that never reached the model carries
        `usage: null, cost: null`, which the ledger distinguishes from a
        zero-cost call.
        """
        from .extract import sha256_text

        narrative_sha = sha256_text(pair.narrative)
        passage_sha = sha256_text(pair.passage_text)
        for attempt in result.history:
            cost = (self.pricing.call_cost(attempt.usage, self.rates)
                    if attempt.usage else None)
            yield store.make_record(
                prompt_version=self.spec.version_id,
                topic_id=pair.topic_id, chunk_id=pair.chunk_id,
                parent_docid=pair.parent_docid,
                narrative_sha256=narrative_sha,
                passage_text=pair.passage_text, passage_sha256=passage_sha,
                prompt_sha256=sha256_text(attempt.prompt),
                model_id=self.judge.model_id, region=self.judge.region,
                run_id=self.run_id, stage=self.stage, attempt=attempt.attempt,
                grade=attempt.grade, facet=attempt.facet,
                raw_text=attempt.raw_text, raw_reasoning=attempt.raw_reasoning,
                stop_reason=attempt.stop_reason, usage=attempt.usage,
                cost=cost, latency_ms=attempt.latency_ms,
                error=attempt.error)

    def run(self, pairs: Sequence[JudgePair]) -> int:
        """Judge every uncached pair; return the exit code the drain chose.

        Returns rather than exits so `cli.py` owns process termination and a test
        can assert the code without `pytest.raises(SystemExit)`.
        """
        pending = self._filter_cached(pairs)
        self.stats.total = len(pairs)
        self.hb_stats.total = len(pairs)
        self.hb_stats.cache_hits = self.stats.cache_hits
        log.info("[CACHE] %d/%d pooled pairs already judged under %s "
                 "(hit rate %.1f%%); %d to judge",
                 self.stats.cache_hits, len(pairs), self.spec.version_id,
                 100.0 * self.stats.cache_hits / max(len(pairs), 1),
                 len(pending))
        if not pending:
            log.info("[JUDGE] nothing to do — every pooled pair is cached")
            return self.drain_and_checkpoint(TRIGGER_COMPLETE)

        self.log_store.open()
        self._writer = threading.Thread(target=self._writer_loop,
                                        name="bm25tune-writer", daemon=True)
        self._writer.start()
        heartbeat = Heartbeat(self.hb_stats, interval=self.heartbeat_interval,
                              logger=get_logger("heartbeat"))
        heartbeat.start()
        # NOT a `with` block, deliberately. `ThreadPoolExecutor.__exit__` calls
        # `shutdown(wait=True)`, which blocks until every running call returns —
        # so a `with` here would make the drain's 60 s bound (PLAN §5.8)
        # cosmetic: by the time the `finally` ran, we would already have waited
        # indefinitely on the exact hung call the bound exists to escape.
        pool = ThreadPoolExecutor(max_workers=self.concurrency,
                                  thread_name_prefix="bm25tune-judge")
        futures: set[Future] = set()
        try:
            feeder = iter(pending)
            # Bounded in-flight window: submitting all 13,000 futures up front
            # would make `stop_requested` cosmetic (the pool's own queue would
            # already hold every remaining call).
            for pair in _take(feeder, self.concurrency * 2):
                futures.add(pool.submit(self._judge_one, pair))
            while futures:
                done, futures = _wait_first(futures)
                for future in done:
                    try:
                        pair, result = future.result()
                    except CredentialsExpired as exc:
                        self.stats.cred_expiries += 1
                        log.error("[CRED] %s", exc)
                        self.request_stop(TRIGGER_CRED)
                        continue
                    self._handle_result(pair, result)
                if self.stop_requested.is_set():
                    break
                for pair in _take(feeder, len(done)):
                    futures.add(pool.submit(self._judge_one, pair))
        finally:
            heartbeat.stop()
            # Cancel what has not started (nothing billed yet), then let the
            # drain bound the wait on what has.
            pool.shutdown(wait=False, cancel_futures=True)
            code = self.drain_and_checkpoint(self.trigger or TRIGGER_COMPLETE,
                                             in_flight=futures)
        return code

    def _filter_cached(self, pairs: Sequence[JudgePair]) -> list[JudgePair]:
        """Drop pairs already graded under this prompt version.

        The cache consult is the entire resume story (PLAN §5.6): after a crash,
        a credential expiry, a budget stop, or a signalled drain, "re-run the
        same command" is correct precisely because this filter removes everything
        already paid for.
        """
        pending, hits = pending_pairs(pairs, self.cache, self.spec.version_id)
        self.stats.cache_hits += hits
        return pending

    def _handle_result(self, pair: JudgePair, result: JudgeResult) -> None:
        """Queue every attempt's record and update the counters."""
        for record in self._records_for(pair, result):
            self._queue.put(record)
        self.stats.judged += 1
        self.hb_stats.judged = self.stats.judged + self.stats.cache_hits
        if result.grade is not None:
            self.stats.graded += 1
        elif result.error == ERROR_PARSE:
            self.stats.parse_failures += 1
            self.hb_stats.parse_fails = self.stats.parse_failures
        else:
            self.stats.other_errors += 1
        self.stats.throttles = self.judge.throttles
        self.hb_stats.throttles = self.stats.throttles

    # -- the ONE drain routine (PLAN §5.8) ----------------------------------
    def drain_and_checkpoint(self, trigger: str, *,
                             in_flight: Iterable[Future] = ()) -> int:
        """Stop feeding, finish what is billed, persist everything, return a code.

        **The single shutdown path for all four triggers** plus normal
        completion (PLAN §5.8). The sequence, in order, with the reason each step
        is where it is:

        1. set `stop_requested` — the feeder submits no more work;
        2. await in-flight futures, bounded by `drain_timeout` (60 s), then
           abandon them. We *wait* rather than cancel because those calls are
           **already billed**: discarding them would waste money and force a
           re-judge;
        3. drain the queue and join the writer, then flush + `fsync` the log
           unconditionally — the audit record is the one artifact that cannot be
           regenerated;
        4. snapshot the cache (atomic; a pure accelerator, but a stale one costs
           minutes on the next start);
        5. checkpoint the meter and write the run's cost files, so the ledger
           cannot lag the log by more than this drain;
        6. log the trigger line with the resume instruction;
        7. return the trigger's exit code.

        Idempotent: a second call is a no-op returning the same code, so the
        normal-completion path and a concurrent signal cannot double-drain.
        """
        if self._draining:
            return TRIGGER_EXITS.get(trigger, ("[SUMMARY]", 0))[1]
        self._draining = True
        self.stop_requested.set()
        prefix, code = TRIGGER_EXITS.get(trigger, ("[SUMMARY]", 1))
        self.stats.trigger = trigger
        self.stats.exit_code = code

        # (2) in-flight futures: already billed, so wait for their results.
        in_flight = list(in_flight)
        pending = [f for f in in_flight if not f.done()]
        if pending:
            log.info("[SIGNAL] draining %d in-flight call(s) (already billed) "
                     "with a %.0fs bound", len(pending), self.drain_timeout)
        deadline = self._clock() + self.drain_timeout
        for future in in_flight:
            if future.cancelled():
                continue  # never started, so never billed
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            try:
                pair, result = future.result(timeout=remaining)
            except CredentialsExpired:
                self.stats.cred_expiries += 1
                continue
            except TimeoutError:
                break
            except Exception:  # noqa: BLE001 - a lost call, not a lost log
                log.exception("[JUDGE] in-flight call failed during drain")
                continue
            self._handle_result(pair, result)
        abandoned = sum(1 for f in in_flight
                        if not f.done() and not f.cancelled())
        if abandoned:
            log.warning("[SIGNAL] abandoning %d call(s) still in flight after "
                        "%.0fs — their judgments are lost but their cost is "
                        "recorded only if the record reached the queue",
                        abandoned, self.drain_timeout)

        # (3) writer: drain the queue, then join and fsync unconditionally.
        # `self._writer is None` means nothing was ever judged (all cached), so
        # there is no queue to drain — but the log still gets its final fsync.
        if self._writer is not None and self._writer.is_alive():
            self._queue.put(None)
            self._writer.join(timeout=self.drain_timeout)
            if self._writer.is_alive():
                log.error("[SIGNAL] writer thread did not finish within %.0fs; "
                          "%d record(s) may be unwritten",
                          self.drain_timeout, self._queue.qsize())
        self.log_store.close()

        # (3b) A trigger the writer raised while we were draining must not be
        # lost to the code we already chose. The budget check runs on the writer
        # thread, so on a short run (or a queue that lagged the feeder) the trip
        # can land *after* the main thread entered the drain — and reporting exit
        # 0 for a run that breached the cap is the one wrong answer here. Only
        # ever escalates: a real trigger is never overwritten by a later one.
        late = self.trigger
        if late is not None and late != trigger and code == 0:
            log.warning("[SIGNAL] %s was raised while draining — reporting it "
                        "rather than success", late)
            trigger = late
            prefix, code = TRIGGER_EXITS.get(late, ("[SUMMARY]", 1))
            self.stats.trigger = trigger
            self.stats.exit_code = code

        # (4) cache snapshot.
        if self.snapshot_path is not None:
            try:
                self.cache.snapshot(self.snapshot_path)
                log.info("[CACHE] snapshot %s (%d entries)",
                         self.snapshot_path, len(self.cache))
            except OSError:
                log.exception("[CACHE] snapshot failed (the log remains the "
                              "source of truth; run rebuild-cache)")

        # (5) meter checkpoint + this run's cost files.
        try:
            self.meter.checkpoint()
        except Exception:  # noqa: BLE001 - never mask the original trigger
            log.exception("[COST] meter checkpoint failed")
        self.stats.spent_usd = float(self.meter.spent_usd())
        self._write_run_costs()

        # (6) the trigger line.
        self._log_trigger(prefix, trigger)
        if self._writer_error is not None and code == 0:
            # A dead writer means records were lost even though the run
            # otherwise "completed". Never report success for that.
            log.error("[JUDGE] the writer thread died (%s) — exiting non-zero "
                      "even though the pool finished",
                      type(self._writer_error).__name__)
            code = 1
            self.stats.exit_code = code
        log.info("[SUMMARY] %s", self.stats.to_json())
        return code

    def _log_trigger(self, prefix: str, trigger: str) -> None:
        """The trigger-specific line, each naming the operator's next action."""
        unjudged = max(self.stats.total - self.stats.cache_hits
                       - self.stats.judged, 0)
        if trigger == TRIGGER_CRED:
            log.error("%s session token expired — refresh SSO creds and re-run "
                      "the same command; resume is automatic (%d pairs "
                      "unjudged, %d judgments safe on disk)", prefix, unjudged,
                      self.stats.graded)
        elif trigger == TRIGGER_BUDGET:
            cap = float(getattr(self.guard, "cap_usd", 0.0))
            # The share is DERIVED from the live cap, never a literal: the cap is
            # user-set (it moved $200 -> $50 on 2026-07-31) and a stale hardcoded
            # percentage in the one message an operator reads at 3am is exactly
            # the kind of quiet wrongness that gets the cap raised for no reason.
            share = (f"~{100.0 * PLAN_EXPECTED_SPEND_USD / cap:.0f}%% of it"
                     if cap > 0 else "far below it")
            log.error("%s HARD STOP — spent=$%.4f of cap=$%.2f; %d pairs "
                      "unjudged; a trip at this cap is prima facie a BUG "
                      "(expected total spend is ~$%.0f, " + share +
                      ", PLAN §6.2b) — diagnose before raising "
                      "BM25_TUNE_BUDGET_USD, then re-run the same command to "
                      "resume", prefix, self.stats.spent_usd, cap, unjudged,
                      PLAN_EXPECTED_SPEND_USD)
        elif trigger in (TRIGGER_SIGINT, TRIGGER_SIGTERM):
            log.error("%s %s — drained %d in-flight, checkpointed, resume with "
                      "the same command (%d pairs unjudged)", prefix,
                      "SIGINT" if trigger == TRIGGER_SIGINT else "SIGTERM",
                      self.stats.judged, unjudged)
        elif trigger == TRIGGER_PARSE_FAIL:
            log.error("%s aborted: %d/%d billed calls unparsable — inspect the "
                      "raw_text values in the log segment before re-running",
                      prefix, self.stats.parse_failures,
                      self.stats.billed_calls)
        else:
            log.info("%s judged %d pairs (%d graded, %d cache hits, %d parse "
                     "failures) spent=$%.4f", prefix, self.stats.judged,
                     self.stats.graded, self.stats.cache_hits,
                     self.stats.parse_failures, self.stats.spent_usd)

    def _write_run_costs(self) -> None:
        """Write `runs/<run_id>/costs.{json,md}` via WP3b's own writers.

        Delegated, never reimplemented. The cost files are the source material
        for the report's cost section (PLAN §5.7/§7.4), and a second
        implementation of the same arithmetic here is exactly the R12 failure
        mode — a published figure that disagrees with the ledger.

        A failure here is logged and swallowed on purpose: the drain must not
        lose its trigger (and its exit code) to a reporting problem, and nothing
        is actually lost — the log and `costs/ledger.jsonl` hold everything
        `cost-report --run-id <id>` needs to regenerate these files later.
        """
        if self.run_dir is None:
            return
        try:
            report = self.pricing.build_cost_report(
                self.log_store.log_dir, self.meter,
                cap_usd=getattr(self.guard, "cap_usd", 0.0),
                run_id=self.run_id, cache_hits=self.stats.cache_hits,
                rates=self.rates)
            json_path, md_path = self.pricing.write_cost_artifacts(
                Path(self.run_dir), report)
            log.info("[COST] wrote %s and %s", json_path, md_path)
        except Exception:  # noqa: BLE001 - never mask the drain's trigger
            log.exception(
                "[COST] failed to write this run's cost files. Spend is still "
                "fully recorded in the judgment log and costs/ledger.jsonl; "
                "regenerate with `python -m bm25tune cost-report --run-id %s`",
                self.run_id)


def _take(iterator: Iterator[JudgePair], n: int) -> list[JudgePair]:
    """Up to `n` items from `iterator` (the bounded submit window)."""
    out: list[JudgePair] = []
    for _ in range(max(0, n)):
        try:
            out.append(next(iterator))
        except StopIteration:
            break
    return out


def _wait_first(futures: set[Future]) -> tuple[list[Future], set[Future]]:
    """Block until at least one future completes; return `(done, still_pending)`.

    A thin wrapper over `concurrent.futures.wait(FIRST_COMPLETED)` so `run()`
    reads as a loop over completions and the bounded-window logic stays in one
    place.
    """
    from concurrent.futures import FIRST_COMPLETED, wait

    done, pending = wait(futures, return_when=FIRST_COMPLETED)
    return list(done), set(pending)
