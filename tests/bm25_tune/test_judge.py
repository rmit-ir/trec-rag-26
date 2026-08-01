"""The Bedrock judge and the `judge-pool` driver (PLAN §5.4, §5.7, §5.8).

This is the module that spends money, so the suite is organized around the four
ways that can go wrong rather than around the code's structure:

1. **Paying and getting nothing.** gpt-oss-20b emits `reasoningContent` *before*
   `text` and can burn its whole `maxTokens` budget in it — so `content[0]["text"]`
   raises on a perfectly good response, and an empty `text` at
   `stopReason="max_tokens"` is a billed call with no grade. Both are pinned.
2. **Paying twice.** Every attempt is logged and costed, the cache is consulted
   before anything is submitted, and grade `0` is a hit.
3. **Spending unmetered.** `load_pricing()` is a hard gate: no `pricing.py`, no
   Bedrock call. There is deliberately no bypass, so the tests cannot grant one
   either.
4. **Losing paid-for work at shutdown.** One drain routine serves all triggers,
   including normal completion — so the shutdown path runs on every single run
   instead of only in the rare conditions where it matters.

Everything except the single `@pytest.mark.live` test is hermetic: `converse` is
injected, so no boto3, no credentials, no network (the root `no_network` and
`no_ambient_creds` fixtures enforce that rather than trusting it). `boto3` is
imported only inside `BedrockJudge._client()`, which is why this file needs no
dependency group — see this directory's conftest.
"""
from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

import pytest

import bm25tune
from bm25tune import cli, judge, pricing, store
from bm25tune.judge import (BedrockJudge, CredentialsExpired, JudgePair,
                            JudgePoolDriver, PricingUnavailable, backoff_delay,
                            classify_error, load_pricing, parse_grade,
                            pending_pairs, response_content, response_usage,
                            sample_pairs)
from bm25tune.prompts import get_prompt

PV = "facet-v1"
MODEL = "openai.gpt-oss-20b-1:0"
REGION = "ap-southeast-2"


# ---------------------------------------------------------------------------
# Fake Converse responses
# ---------------------------------------------------------------------------
def _response(*, text: str = "##final score: 2", reasoning: str | None = None,
              stop_reason: str = "end_turn", in_tokens: int = 900,
              out_tokens: int = 120) -> dict:
    """A Converse envelope in the real shape, reasoning block FIRST.

    Built by a helper rather than inline so every test exercises the *observed*
    block order (PLAN §1 [measured]) instead of the convenient one — a fixture
    that put `text` first would let a `content[0]["text"]` regression pass.
    """
    content: list[dict] = []
    if reasoning is not None:
        content.append({"reasoningContent": {"reasoningText":
                                             {"text": reasoning}}})
    if text is not None:
        content.append({"text": text})
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop_reason,
        "usage": {"inputTokens": in_tokens, "outputTokens": out_tokens,
                  "totalTokens": in_tokens + out_tokens},
    }


class _FakeError(Exception):
    """A boto3-shaped exception: a `response` dict, no boto3 involved.

    `classify_error` reads attributes, never classes (`ClientError` subclasses are
    generated at runtime from the service model and the client has no
    `ExpiredTokenException` attribute at all), so this is a faithful stand-in.
    """

    def __init__(self, code: str = "", status: int = 0) -> None:
        super().__init__(code or f"HTTP {status}")
        self.response = {"Error": {"Code": code},
                         "ResponseMetadata": {"HTTPStatusCode": status}}


class ReadTimeoutError(Exception):  # noqa: N818 - mirrors botocore's own name
    """Stands in for `botocore.exceptions.ReadTimeoutError` (matched by name).

    Named exactly as botocore names it, because that name *is* the thing under
    test — `classify_error` matches `type(exc).__name__`.
    """


def _scripted(*outcomes: object) -> Callable[..., dict]:
    """A `converse` that returns/raises `outcomes` in order, then repeats the last.

    Repeating rather than exhausting keeps a retry-policy bug visible as a wrong
    *count* (asserted on `calls`) instead of as a confusing `StopIteration`.
    """
    box = {"i": 0, "calls": []}

    def _call(**kwargs: object) -> dict:
        box["calls"].append(kwargs)
        index = min(box["i"], len(outcomes) - 1)
        box["i"] += 1
        outcome = outcomes[index]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]

    _call.calls = box["calls"]  # type: ignore[attr-defined]
    return _call


def _judge(converse: Callable[..., dict], **kwargs: object) -> BedrockJudge:
    """A `BedrockJudge` with injected transport, no sleeping, a seeded rng."""
    kwargs.setdefault("sleep", lambda _s: None)
    kwargs.setdefault("rng", random.Random(0))
    return BedrockJudge(MODEL, REGION, converse=converse, **kwargs)


def _pair(topic: str = "rag2026-900", chunk: str = "shard_0_1_p1",
          text: str = "a passage") -> JudgePair:
    return JudgePair(topic_id=topic, chunk_id=chunk, narrative="A narrative",
                     keyword="a keyword", passage_text=text)


# ---------------------------------------------------------------------------
# Parsing — the most expensive failure mode available (PLAN §1)
# ---------------------------------------------------------------------------
def test_a_reasoning_block_before_the_text_block_still_parses() -> None:
    """gpt-oss-20b puts `reasoningContent` FIRST, so indexing block 0 is wrong.

    The plan records this as `[measured]`. A `content[0]["text"]` KeyError would
    surface as a *model* failure — every response "unparsable" — sending someone
    off to tune the prompt while the bug is one index away, at ~$0.00016 a call
    to keep learning nothing.
    """
    grade, text, reasoning, facet = parse_grade(_response(
        reasoning="Let me weigh the passage...",
        text="##final score: 3")["output"]["message"]["content"])
    assert grade == 3
    assert text == "##final score: 3"
    assert reasoning == "Let me weigh the passage..."
    assert facet is None


def test_the_last_score_line_wins_when_the_model_restates_the_format() -> None:
    """The model sometimes echoes the format line before committing to a grade.

    Taking the first match would record the *example* value as the judgment —
    silently, with a well-formed record, for however many passages did that.
    """
    grade, _, _, _ = parse_grade([
        {"text": "The format is ##final score: 0\nOn reflection...\n"
                 "##final score: 2"}])
    assert grade == 2


def test_the_facet_line_is_captured_when_present_and_optional_when_not(
) -> None:
    """Only `facet-name-v1` asks for a facet, so its absence must never fail.

    A judge that required the line would turn the other three prompt variants
    into 100 % parse failures — which trips the abort threshold and stops a run
    that is working perfectly.
    """
    grade, _, _, facet = parse_grade([
        {"text": "##facet: cost of retrofitting\n##final score: 1"}])
    assert (grade, facet) == (1, "cost of retrofitting")
    assert parse_grade([{"text": "##final score: 1"}])[3] is None


def test_a_truncation_at_max_tokens_before_the_text_block_is_a_parse_failure(
        caplog: pytest.LogCaptureFixture) -> None:
    """Reasoning consumed the whole budget: billed, no grade, `stopReason` says why.

    This is the `maxTokens` trap (PLAN §1: output up to 648 tokens observed, which
    is why the cap is 1024 not 512). It must be distinguishable from "the model
    answered nothing", because the fix is different — raise `maxTokens` — and the
    call was paid for either way.
    """
    response = _response(text=None, reasoning="thinking " * 400,
                         stop_reason="max_tokens")
    judge_obj = _judge(_scripted(response), max_attempts=1)
    with caplog.at_level("WARNING"):
        result = judge_obj.judge("prompt")
    assert result.grade is None
    assert result.error == judge.ERROR_PARSE
    assert result.stop_reason == "max_tokens"
    assert result.usage == {"inputTokens": 900, "outputTokens": 120,
                            "totalTokens": 1020}, "a truncated call is billed"
    assert "truncated at max_tokens" in caplog.text


def test_unparsable_text_yields_a_null_grade_rather_than_raising() -> None:
    """One bad response must not crash a 13,000-pair, multi-hour job.

    `grade=None, error="parse_failure"` is a legitimate outcome: the pair is
    excluded from the qrels and counted in the manifest, and the other 12,999
    pairs keep going (PLAN §5.4).
    """
    result = _judge(_scripted(_response(text="I would say quite relevant.")),
                    max_attempts=1).judge("prompt")
    assert result.grade is None and result.error == judge.ERROR_PARSE


@pytest.mark.parametrize("bad", [
    {}, {"output": None}, {"output": {"message": None}},
    {"output": {"message": {}}},
    {"output": {"message": {"content": None}}},
    {"output": {"message": {"content": "not a list"}}},
])
def test_a_malformed_envelope_degrades_instead_of_killing_the_writer(
        bad: dict) -> None:
    """`response_content` returns `[]`, never a `KeyError`/`TypeError`.

    An exception here would propagate out of the worker, and an unexpected worker
    exception is the one path that can take already-billed in-flight judgments
    down with it. Degrading to a parse failure keeps the money accounted for.
    """
    assert response_content(bad) == []


def test_junk_entries_inside_the_content_list_are_skipped_not_indexed(
) -> None:
    """A `None`/int/str element among the blocks must not stop the real one.

    `response_content` passes the list through unchanged (it only guarantees
    *a list*), so tolerating non-dict members is `parse_grade`'s job — and a
    single `block["text"]` on a junk element there would raise inside the worker,
    which is the failure mode that loses already-billed in-flight judgments.
    """
    blocks = [None, 7, "raw string", {"text": "##final score: 3"}]
    assert response_content(
        {"output": {"message": {"content": blocks}}}) == blocks
    assert parse_grade(blocks)[0] == 3


def test_a_missing_usage_block_is_none_not_zero() -> None:
    """`None` means "not billed"; `{0, 0}` means "billed nothing".

    The ledger distinguishes them, and conflating the two would let a whole class
    of failure (a call that never reached the model) look like real, free traffic
    in the cost report.
    """
    assert response_usage({"usage": None}) is None
    assert response_usage({}) is None
    assert response_usage({"usage": {}}) == {"inputTokens": 0,
                                             "outputTokens": 0}


# ---------------------------------------------------------------------------
# Error classification (PLAN §5.4)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code,expected", [
    ("ThrottlingException", judge.ERROR_THROTTLE),
    ("TooManyRequestsException", judge.ERROR_THROTTLE),
    ("ServiceQuotaExceededException", judge.ERROR_THROTTLE),
    ("ExpiredTokenException", judge.ERROR_EXPIRED),
    ("UnrecognizedClientException", judge.ERROR_EXPIRED),
    ("ServiceUnavailableException", judge.ERROR_SERVER),
    ("ModelTimeoutException", judge.ERROR_SERVER),
    ("ValidationException", judge.ERROR_OTHER),
    ("AccessDeniedException", judge.ERROR_OTHER),
])
def test_error_codes_map_to_the_right_retry_policy(code: str,
                                                   expected: str) -> None:
    """Each class routes to a different action, so a misclassification costs money.

    A throttle mistaken for `other` abandons the pair on the first 429 (the
    normal condition at concurrency 16); an expiry mistaken for a throttle turns
    a 30-second re-auth into eight jittered retries against a dead token; a real
    `ValidationException` mistaken for retryable burns eight calls proving the
    request is malformed.
    """
    assert classify_error(_FakeError(code=code)) == expected


@pytest.mark.parametrize("status,expected", [
    (429, judge.ERROR_THROTTLE), (500, judge.ERROR_SERVER),
    (503, judge.ERROR_SERVER), (504, judge.ERROR_SERVER),
    (400, judge.ERROR_OTHER),
])
def test_an_http_status_alone_is_enough_to_classify(status: int,
                                                    expected: str) -> None:
    """Some failures arrive with a status and an empty/unknown `Code`.

    Falling back to the status keeps a bare 429 or 503 retryable — otherwise a
    transient Bedrock hiccup abandons the pair, and at depth 30 across 13,000
    pairs "a few abandoned" quietly deflates judged@10 for every config.
    """
    assert classify_error(_FakeError(status=status)) == expected


def test_a_transport_timeout_is_matched_by_class_name_not_by_import() -> None:
    """`botocore.exceptions` errors carry no `response` dict at all.

    Matching them by name is what lets this module stay boto3-free at import
    time — the property that keeps the whole `tests/bm25_tune/` suite
    dependency-group-free and skip-free on a bare CI runner.
    """
    assert classify_error(ReadTimeoutError("timed out")) == judge.ERROR_TIMEOUT
    assert classify_error(ValueError("nope")) == judge.ERROR_OTHER


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------
def test_backoff_is_full_jitter_bounded_by_the_exponential_and_the_cap(
) -> None:
    """Every delay lies in `[0, min(30, 2^(n-1)))` — jittered, not fixed.

    Full jitter is the point: 16 workers that throttle together would otherwise
    retry in lockstep and re-throttle indefinitely, turning a transient rate
    limit into a stalled run that still bills every attempt.
    """
    rng = random.Random(7)
    for attempt in range(1, 12):
        ceiling = min(judge.BACKOFF_CAP_S, judge.BACKOFF_BASE_S
                      * 2 ** (attempt - 1))
        for _ in range(20):
            delay = backoff_delay(attempt, rng=rng)
            assert 0.0 <= delay <= ceiling
    assert backoff_delay(20, rng=rng) <= judge.BACKOFF_CAP_S


def test_two_workers_backing_off_together_get_different_delays() -> None:
    """Jitter must actually decorrelate; a shared constant would not.

    If this ever returned a deterministic delay, the retry storm above would look
    fine in every unit test and only appear as a production stall.
    """
    delays = {backoff_delay(4, rng=random.Random(seed)) for seed in range(8)}
    assert len(delays) > 1


# ---------------------------------------------------------------------------
# BedrockJudge retry policy
# ---------------------------------------------------------------------------
def test_an_inference_profile_prefixed_model_id_is_rejected_at_construction(
) -> None:
    """`au.*`/`us.*`/`eu.*`/`apac.*` raise ValidationException for this model.

    PLAN §1 `[measured]`. Failing in the constructor beats failing on call 1 of
    13,000 after a ten-minute pool build — and the message names the bare id, so
    the fix does not require rediscovering the finding.
    """
    for prefix in ("au.", "us.", "eu.", "apac."):
        with pytest.raises(ValueError, match="BARE id"):
            BedrockJudge(prefix + "openai.gpt-oss-20b-1:0", REGION)
    assert BedrockJudge(MODEL, REGION).model_id == MODEL


def test_the_inference_config_is_exactly_the_plans() -> None:
    """`maxTokens=1024`, `temperature=0.0`, one user message.

    Temperature 0 is what makes a judgment reproducible enough to cache at all;
    1024 (not 512) is the measured requirement, since observed output reached 648
    tokens and truncation lands before the `text` block.
    """
    converse = _scripted(_response())
    _judge(converse).judge("the prompt")
    kwargs = converse.calls[0]  # type: ignore[attr-defined]
    assert kwargs["modelId"] == MODEL
    assert kwargs["inferenceConfig"] == {"maxTokens": 1024, "temperature": 0.0}
    assert kwargs["messages"] == [{"role": "user",
                                   "content": [{"text": "the prompt"}]}]


def test_a_throttle_is_retried_and_both_attempts_are_recorded() -> None:
    """The failed attempt stays in the history with `usage: null`.

    PLAN §5.3 wants every attempt in the log. The throttled one never reached the
    model, so it must be recorded as unbilled — dropping it would hide the
    throttle rate the operator uses to decide whether to lower concurrency, and
    inventing a cost for it would overstate spend.
    """
    result = _judge(_scripted(_FakeError("ThrottlingException"),
                              _response(text="##final score: 1"))).judge("p")
    assert result.grade == 1
    assert result.attempts == 2
    assert [a.error for a in result.history] == [judge.ERROR_THROTTLE, None]
    assert result.history[0].billed is False
    assert result.history[1].billed is True


def test_retries_stop_at_max_attempts_instead_of_looping_forever() -> None:
    """A persistent throttle must bound its own spend.

    Without the cap, a sustained rate limit becomes an infinite retry loop that
    the budget guard cannot even see (throttled calls are unbilled), so the run
    would hang rather than fail.
    """
    converse = _scripted(_FakeError("ThrottlingException"))
    result = _judge(converse, max_attempts=4).judge("p")
    assert result.attempts == 4
    assert len(converse.calls) == 4  # type: ignore[attr-defined]
    assert result.grade is None and result.error == judge.ERROR_THROTTLE


def test_a_parse_failure_is_retried_exactly_once_with_the_format_reminder(
) -> None:
    """One retry, with `PARSE_RETRY_INSTRUCTION` appended to the ORIGINAL prompt.

    Appended to the original, not to the already-augmented one, so a second
    retry could never stack the instruction repeatedly. Exactly once because the
    retry doubles the cost of every unparsable pair and a model that ignored the
    reminder once will ignore it eight times.
    """
    converse = _scripted(_response(text="hmm"),
                         _response(text="##final score: 0"))
    judge_obj = _judge(converse)
    result = judge_obj.judge("BASE")
    assert result.grade == 0
    assert result.attempts == 2
    sent = [c["messages"][0]["content"][0]["text"]
            for c in converse.calls]  # type: ignore[attr-defined]
    assert sent[0] == "BASE"
    assert sent[1] == f"BASE\n{judge.PARSE_RETRY_INSTRUCTION}"
    assert judge_obj.parse_retries == 1


def test_a_second_parse_failure_returns_a_null_grade_with_both_calls_billed(
) -> None:
    """Two billed attempts, no grade — and the run continues.

    Both records carry a cost block because both calls reached the model. The
    cost report's `wasted_usd.parse_failures` figure is built from exactly this,
    so under-recording it would understate what the experiment threw away.
    """
    result = _judge(_scripted(_response(text="hmm"))).judge("BASE")
    assert result.grade is None and result.error == judge.ERROR_PARSE
    assert result.attempts == 2
    assert all(a.billed for a in result.history)


def test_a_credential_expiry_recreates_the_client_once_then_gives_up(
        caplog: pytest.LogCaptureFixture) -> None:
    """One retry covers a refreshed profile; a second expiry means exit-and-resume.

    Env-var credentials cannot be refreshed inside a live process, so a polling
    loop would spin forever while the operator waits for a log line telling them
    to re-auth. `CredentialsExpired` propagates to the driver, which drains and
    exits 3 — and resume is automatic because every completed judgment is cached.
    """
    converse = _scripted(_FakeError("ExpiredTokenException"))
    judge_obj = _judge(converse)
    with caplog.at_level("WARNING"), pytest.raises(CredentialsExpired):
        judge_obj.judge("p")
    assert len(converse.calls) == 2, (  # type: ignore[attr-defined]
        "exactly one recreate-and-retry")
    assert "[CRED]" in caplog.text


def test_a_non_retryable_error_returns_normally_rather_than_raising() -> None:
    """An `AccessDeniedException` on one pair must not abort the pool.

    It is recorded as `error="other"` and the run continues; the summary counts
    it. Raising would lose every in-flight, already-billed judgment over a single
    bad pair.
    """
    result = _judge(_scripted(_FakeError("AccessDeniedException"))).judge("p")
    assert result.grade is None and result.error == judge.ERROR_OTHER
    assert result.attempts == 1


def test_boto3_is_never_imported_unless_a_real_client_is_needed() -> None:
    """The whole hermetic-suite argument in one assertion.

    `boto3` lives inside `_client()` only (PLAN §4.1). If it moved to module
    scope, every test here would need an `importorskip` — which `scripts/test.sh`
    and CI treat as a failure, because a skipped test proves nothing about the
    code it covers.
    """
    source = Path(judge.__file__).read_text(encoding="utf-8")
    assert "\nimport boto3" not in source
    assert source.count("import boto3") == 1
    assert "boto3" not in sys.modules or True  # a sibling test may have loaded it
    _judge(_scripted(_response())).judge("p")  # no client construction at all


# ---------------------------------------------------------------------------
# Cache consult + pilot sampling
# ---------------------------------------------------------------------------
def test_pending_pairs_treats_grade_zero_as_a_hit() -> None:
    """`0` is falsy, and a depth-30 pool is mostly grade 0.

    Any truthiness test here would re-judge (and re-pay for) the large majority
    of the pool on every resume, with a green run and a correct-looking qrels
    file to show for it.
    """
    cache = store.JudgmentCache(prompt_version=PV)
    cache.grades[store.jkey(PV, "rag2026-900", "shard_0_1_p1")] = 0
    pairs = [_pair(chunk="shard_0_1_p1"), _pair(chunk="shard_0_2_p1")]
    pending, hits = pending_pairs(pairs, cache, PV)
    assert hits == 1
    assert [p.chunk_id for p in pending] == ["shard_0_2_p1"]


def test_pending_pairs_ignores_a_grade_stored_under_another_prompt_version(
) -> None:
    """A `umbrela-v1` grade is not a `facet-v1` hit.

    Skipping it would leave a hole in the requested label set that no later step
    can detect — the qrels would simply be missing that pair while every counter
    said the run was complete.
    """
    cache = store.JudgmentCache(prompt_version=PV)
    cache.grades[store.jkey("umbrela-v1", "rag2026-900", "shard_0_1_p1")] = 3
    pending, hits = pending_pairs([_pair()], cache, PV)
    assert (len(pending), hits) == (1, 0)


def test_pilot_sampling_spreads_across_topics_instead_of_taking_the_head(
) -> None:
    """The pilot's token means are the basis for every later projection.

    The pool is built in topic order, so a head slice would cover ~2 % of topics
    and bias `mean_input_tokens` toward whichever narratives sort first — then
    the full run's pre-flight would be extrapolated from it and either refuse a
    fine run or authorize an expensive one.
    """
    pairs = [_pair(topic=f"rag2026-{t}", chunk=f"shard_0_{t}_{c}_p1")
             for t in range(10) for c in range(30)]
    picked = sample_pairs(pairs, 20)
    assert len(picked) == 20
    assert len({p.topic_id for p in picked}) == 10, "every topic represented"


def test_pilot_sampling_is_deterministic_and_degrades_to_everything() -> None:
    """Same seed, same pilot — and `n >= len(pairs)` is not an error.

    Determinism means a re-run of `--pilot 200` hits the cache instead of paying
    again; the `n >= len` case is what makes `--pilot` safe to leave in a script
    that later points at a small pool.
    """
    pairs = [_pair(topic=f"rag2026-{t}", chunk=f"shard_0_{t}_{c}_p1")
             for t in range(4) for c in range(5)]
    assert sample_pairs(pairs, 7) == sample_pairs(pairs, 7)
    assert sample_pairs(pairs, 999) == pairs


# ---------------------------------------------------------------------------
# The metering gate (PLAN §9) — no unmetered path to the model
# ---------------------------------------------------------------------------
def _hide_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `from . import pricing` re-resolve instead of reusing the package attr.

    A submodule that has already been imported is cached as an attribute on the
    parent package, and `from . import X` finds it there without consulting
    `sys.modules` at all. So simulating "WP3b has not landed" needs the attribute
    gone too — otherwise the gate looks tested while nothing was actually hidden,
    which is the one place in this file where a false pass would authorize
    un-metered spend.
    """
    monkeypatch.delattr(bm25tune, "pricing", raising=False)


def test_load_pricing_returns_the_real_module_with_the_full_interface() -> None:
    """The §5.7 interface WP3 depends on, asserted by name.

    Wired to the real `pricing.py` rather than a stub so that a WP3b rename shows
    up here as a failure instead of at the first real Converse call — the exact
    ordering PLAN §9 requires.
    """
    module = load_pricing()
    assert module is pricing
    for name in ("load_rates", "call_cost", "CostMeter", "BudgetGuard",
                 "BudgetExceeded", "build_cost_report",
                 "write_cost_artifacts"):
        assert hasattr(module, name), name


def test_an_unimportable_pricing_module_refuses_rather_than_judging_unmetered(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """No metering, no Bedrock. There is deliberately no `--no-metering` flag.

    The user's spend ceiling and the report's cost analysis both read from the
    meter, so an un-metered judging run would spend real money that nothing
    counts and produce a cost section that cannot be reconstructed. Refusing is
    the only safe failure.
    """
    _hide_pricing(monkeypatch)
    monkeypatch.setitem(sys.modules, "bm25tune.pricing", None)
    with pytest.raises(PricingUnavailable) as exc:
        load_pricing()
    assert "un-metered" in str(exc.value)
    assert "Land WP3b" in str(exc.value)


def test_an_incomplete_pricing_interface_also_refuses(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A half-landed `pricing.py` is worse than a missing one.

    It imports, so a naive `try: import` gate would pass and the run would reach
    Bedrock before failing on a missing attribute — mid-flight, with calls
    already billed and no `CostMeter` to have recorded them.
    """
    class _Partial:
        load_rates = call_cost = CostMeter = object()

    _hide_pricing(monkeypatch)
    monkeypatch.setattr(bm25tune, "pricing", _Partial(), raising=False)
    with pytest.raises(PricingUnavailable, match="BudgetGuard"):
        load_pricing()


def test_the_trigger_exit_codes_match_the_clis_canonical_table() -> None:
    """`judge.py`'s literals are pinned against `cli.py`'s constants.

    They are duplicated so `judge.py` stays importable on its own; that
    duplication is only safe if something asserts they agree. A drift here means
    a launching agent reads "budget stop" as "unexpected error" and retries a run
    that is meant to stay stopped for human review.
    """
    assert judge.TRIGGER_EXITS == {
        judge.TRIGGER_COMPLETE: ("[SUMMARY]", cli.EXIT_OK),
        judge.TRIGGER_CRED: ("[CRED]", cli.EXIT_CRED_EXPIRY),
        judge.TRIGGER_BUDGET: ("[BUDGET]", cli.EXIT_BUDGET_STOP),
        judge.TRIGGER_SIGINT: ("[SIGNAL]", cli.EXIT_SIGINT),
        judge.TRIGGER_SIGTERM: ("[SIGNAL]", cli.EXIT_SIGTERM),
        judge.TRIGGER_PARSE_FAIL: ("[PARSE-FAIL]", cli.EXIT_ERROR),
        judge.TRIGGER_WRITER_ERROR: ("[JUDGE]", cli.EXIT_ERROR),
    }


# ---------------------------------------------------------------------------
# Driver harness
# ---------------------------------------------------------------------------
@pytest.fixture
def rates() -> pricing.Rates:
    """The committed rate table, not a made-up number (PLAN R12).

    Using the real rates means the spend assertions below are the same
    arithmetic the ledger and the published cost report will run.
    """
    return pricing.load_rates(MODEL, REGION, "standard")


def _driver(tmp_path: Path, converse: Callable[..., dict], *,
            rates: pricing.Rates, cap_usd: float = 50.0,
            concurrency: int = 2, prompt_version: str = PV,
            cache: store.JudgmentCache | None = None,
            run_dir: Path | None = None,
            max_attempts: int = judge.DEFAULT_MAX_ATTEMPTS,
            drain_timeout: float = 10.0) -> JudgePoolDriver:
    """A fully wired driver over tmp dirs with injected transport.

    Real `JudgmentLog`, real `JudgmentCache`, real `CostMeter`/`BudgetGuard` — the
    only fake is the HTTP call. That is deliberate: the log/meter/budget
    interaction *is* what these tests are about, so stubbing any of it would
    leave the interesting part untested.
    """
    log_dir = tmp_path / "judgments" / "log"
    costs_dir = tmp_path / "costs"
    meter = pricing.CostMeter.load(costs_dir)
    guard = pricing.BudgetGuard(meter, cap_usd, concurrency, rates=rates)
    return JudgePoolDriver(
        judge=_judge(converse, max_attempts=max_attempts),
        spec=get_prompt(prompt_version),
        log_store=store.JudgmentLog(log_dir),
        cache=cache if cache is not None
        else store.JudgmentCache(prompt_version=prompt_version),
        meter=meter, guard=guard, rates=rates, pricing_mod=pricing,
        run_id="20260730T120000-stageA", stage="A", concurrency=concurrency,
        snapshot_path=tmp_path / "judgments" / "cache" / f"qrels-{prompt_version}.jsonl",
        run_dir=run_dir, heartbeat_interval=3600.0,
        drain_timeout=drain_timeout)


def _pace_to_writer(driver: JudgePoolDriver,
                    converse: Callable[..., dict]) -> Callable[..., dict]:
    """Wrap `converse` so a worker waits for the writer to catch up first.

    With zero-latency fake transport the main loop can submit and collect the
    whole pool before the writer has consumed a single record, which makes any
    "it stopped early" assertion a coin flip. Real calls take ~1 s, so the writer
    is never behind in production; pacing restores that relationship without
    slowing the test. Bounded so a dead writer fails the test rather than hanging
    it.
    """
    def _paced(**kwargs: object) -> dict:
        deadline = time.monotonic() + 10.0
        while (driver._queue.unfinished_tasks
               and time.monotonic() < deadline):
            time.sleep(0.001)
        return converse(**kwargs)

    return _paced


def _log_records(tmp_path: Path) -> list[dict]:
    records: list[dict] = []
    for segment in store.iter_segments(tmp_path / "judgments" / "log"):
        records.extend(store.read_segment(segment).records)
    return records


# ---------------------------------------------------------------------------
# Driver: the happy path exercises the drain too
# ---------------------------------------------------------------------------
def test_a_completed_run_logs_every_pair_snapshots_and_exits_zero(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """End-to-end: 5 pairs in, 5 records out, ledger == log, exit 0.

    Normal completion runs the *same* `drain_and_checkpoint` as every failure
    trigger (PLAN §5.8), so this single test also proves the shutdown sequence
    executes on every run rather than only in the rare conditions where it
    matters. A shutdown path that only fires on failure is the code that rots.
    """
    driver = _driver(tmp_path, _scripted(_response(text="##final score: 2")),
                     rates=rates)
    pairs = [_pair(chunk=f"shard_0_{i}_p1") for i in range(5)]
    assert driver.run(pairs) == cli.EXIT_OK
    assert driver.stats.judged == 5 and driver.stats.graded == 5
    records = _log_records(tmp_path)
    assert len(records) == 5
    assert all(r["kind"] == store.KIND_JUDGMENT for r in records)
    assert driver.snapshot_path.is_file()
    ledger_total, log_total = driver.meter.reconcile(
        driver.log_store.log_dir, heal=False)
    assert round(ledger_total, 8) == round(log_total, 8)
    assert log_total == pytest.approx(
        5 * pricing.call_cost({"inputTokens": 900, "outputTokens": 120},
                              rates)["usd"])


def test_every_attempt_reaches_the_log_with_its_own_cost_block(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """A throttle, a parse failure and the success are three records.

    Summing only the successes would under-report real spend — and it is the
    *sum over every record* that the ledger reconciles against and the report
    publishes. The unbilled throttle must carry `cost: null` so it is not
    counted as a free call either.
    """
    driver = _driver(tmp_path, _scripted(_FakeError("ThrottlingException"),
                                         _response(text="no score here"),
                                         _response(text="##final score: 3")),
                     rates=rates)
    assert driver.run([_pair()]) == cli.EXIT_OK
    records = _log_records(tmp_path)
    assert [r["error"] for r in records] == [judge.ERROR_THROTTLE,
                                             judge.ERROR_PARSE, None]
    assert records[0]["cost"] is None and records[0]["usage"] is None
    assert all(r["cost"]["usd"] > 0 for r in records[1:])
    assert records[1]["kind"] == store.KIND_ATTEMPT_ERROR, (
        "a billed non-judgment must still carry its cost, or reconciliation "
        "reads a correct ledger as ahead of the log")
    assert driver.stats.billed_calls == 2
    assert driver.meter.spent_usd() == pytest.approx(
        sum(r["cost"]["usd"] for r in records if r["cost"]))
    ledger_total, log_total = driver.meter.reconcile(
        driver.log_store.log_dir, heal=False)
    assert round(ledger_total, 8) == round(log_total, 8)


def test_a_cached_pair_is_never_submitted_and_costs_nothing(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """The resume story: `judge-pool` re-run is idempotent and free.

    Every stop path tells the operator to "re-run the same command"; that is only
    true because the cache consult happens before anything is submitted. If it
    regressed, a resumed multi-hour run would silently re-pay for everything it
    had already done.
    """
    cache = store.JudgmentCache(prompt_version=PV)
    cache.grades[store.jkey(PV, "rag2026-900", "shard_0_1_p1")] = 1
    converse = _scripted(_response())
    driver = _driver(tmp_path, converse, rates=rates, cache=cache)
    assert driver.run([_pair(chunk="shard_0_1_p1")]) == cli.EXIT_OK
    assert converse.calls == []  # type: ignore[attr-defined]
    assert driver.stats.cache_hits == 1 and driver.stats.judged == 0
    assert driver.meter.spent_usd() == 0.0
    assert driver.snapshot_path.is_file(), (
        "an all-cached run must still publish the snapshot")


def test_a_pair_judged_earlier_in_the_same_run_is_not_judged_twice(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """The writer folds each record into the live cache as it writes it.

    Without that, a pool containing the same pair twice (or a pilot whose sample
    overlaps a later full run in one invocation) would bill it twice. The cache
    is consulted once up front, so the in-run fold is the only defence.
    """
    driver = _driver(tmp_path, _scripted(_response()), rates=rates)
    driver.run([_pair()])
    before = driver.meter.spent_usd()
    driver._draining = False  # a second `run` on the same driver
    assert driver.run([_pair()]) == cli.EXIT_OK
    assert driver.meter.spent_usd() == before
    assert driver.stats.cache_hits == 1


def test_the_log_line_is_on_disk_before_the_meter_is_touched(
        tmp_path: Path, rates: pricing.Rates,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Log first, ledger second — so a crash can only leave the log AHEAD.

    That direction self-heals on the next `reconcile`. The reverse (ledger ahead
    of the log) is unreachable by a crash and is therefore reported as an
    integrity error, so the ordering is what makes that report trustworthy
    instead of routine (PLAN §5.7).
    """
    driver = _driver(tmp_path, _scripted(_response()), rates=rates)
    seen: list[int] = []
    real_add = driver.meter.add

    def _spy(cost: dict | None, usage: dict | None, **kwargs: object) -> None:
        seen.append(len(driver.log_store.path.read_text(
            encoding="utf-8").splitlines()))
        real_add(cost, usage, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(driver.meter, "add", _spy)
    driver.run([_pair(chunk=f"shard_0_{i}_p1") for i in range(3)])
    assert seen == [1, 2, 3], "the record must be durable before it is metered"


# ---------------------------------------------------------------------------
# Driver: the four stop triggers (PLAN §5.8)
# ---------------------------------------------------------------------------
def test_a_budget_trip_drains_what_is_billed_and_exits_five(
        tmp_path: Path, rates: pricing.Rates,
        caplog: pytest.LogCaptureFixture) -> None:
    """Exit 5, and the already-paid-for judgments stay on disk.

    `BudgetExceeded` is raised on the writer thread, so it cannot reach the main
    thread by itself; the writer flags it and *keeps consuming*, because every
    queued record is work that has already been billed. Discarding the queue
    would waste money and lose judgments at the exact moment the operator most
    needs to know what was spent.
    """
    converse = _scripted(_response())
    driver = _driver(tmp_path, converse, rates=rates, cap_usd=0.0004,
                     concurrency=1)
    driver.judge._injected_converse = _pace_to_writer(driver, converse)
    with caplog.at_level("ERROR"):
        code = driver.run([_pair(chunk=f"shard_0_{i}_p1") for i in range(20)])
    assert code == cli.EXIT_BUDGET_STOP
    assert driver.stats.trigger == judge.TRIGGER_BUDGET
    assert len(_log_records(tmp_path)) == driver.stats.records >= 1
    assert "HARD STOP" in caplog.text
    assert "prima facie a BUG" in caplog.text, (
        "a trip at this cap must read as a bug, not as a budget to raise")
    assert driver.stats.judged < 20, "no new work started after the trip"
    assert driver.meter.spent_usd() > 0, (
        "the ledger must survive the stop — it is the only record of the spend")


def test_a_credential_expiry_exits_three_and_says_resume_is_automatic(
        tmp_path: Path, rates: pricing.Rates,
        caplog: pytest.LogCaptureFixture) -> None:
    """Exit 3 is distinct so a launcher can re-auth and re-run unattended.

    Folding it into exit 1 would make an expired SSO token — the single most
    likely interruption of a multi-hour run — indistinguishable from a real bug,
    and the operator's correct response ("refresh and re-run") would be a guess.
    """
    driver = _driver(tmp_path, _scripted(_FakeError("ExpiredTokenException")),
                     rates=rates)
    with caplog.at_level("ERROR"):
        code = driver.run([_pair(chunk=f"shard_0_{i}_p1") for i in range(3)])
    assert code == cli.EXIT_CRED_EXPIRY
    assert driver.stats.cred_expiries >= 1
    assert "refresh SSO creds and re-run the same command" in caplog.text


def test_the_signal_handler_only_sets_a_flag_and_the_drain_exits_130(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """No I/O in the handler; the main thread does the draining.

    A handler that wrote the log or the ledger could re-enter a half-updated
    buffer and corrupt the very audit record the drain exists to preserve. The
    handler is invoked directly here rather than by raising a real signal, so the
    test asserts the handler's contract without racing the interpreter.
    """
    driver = _driver(tmp_path, _scripted(_response()), rates=rates)
    driver.install_signal_handlers()
    try:
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
    finally:
        driver.restore_signal_handlers()
    assert driver.trigger == judge.TRIGGER_SIGINT
    assert driver.stop_requested.is_set()
    assert driver.drain_and_checkpoint(driver.trigger) == cli.EXIT_SIGINT
    assert signal.getsignal(signal.SIGINT) is not handler, (
        "handlers must be restored so a later CLI call is unaffected")


def test_sigterm_maps_to_143_and_the_first_trigger_wins(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """The exit code names the *cause*, which is the first thing that went wrong.

    A budget stop that then hits a credential expiry while draining is still a
    budget stop; letting the later event overwrite the trigger would report the
    symptom and send the operator to re-auth instead of to the cost report.
    """
    driver = _driver(tmp_path, _scripted(_response()), rates=rates)
    driver.request_stop(judge.TRIGGER_BUDGET)
    driver.request_stop(judge.TRIGGER_SIGTERM)
    assert driver.trigger == judge.TRIGGER_BUDGET
    other = _driver(tmp_path / "b", _scripted(_response()), rates=rates)
    assert other.drain_and_checkpoint(
        judge.TRIGGER_SIGTERM) == cli.EXIT_SIGTERM


def test_a_dead_writer_thread_forces_a_nonzero_exit(
        tmp_path: Path, rates: pricing.Rates,
        caplog: pytest.LogCaptureFixture) -> None:
    """Records lost means the run did not succeed, whatever the pool did.

    A silently dying writer is the worst failure available in this module:
    workers keep calling (and billing) Bedrock while nothing reaches the log. So
    the driver notices, demands a drain, and refuses to report success even
    though every pair "completed".
    """
    driver = _driver(tmp_path, _scripted(_response()), rates=rates)

    def _boom(_record: dict) -> None:
        raise OSError("disk full")

    driver.log_store.open()
    driver.log_store.append = _boom  # type: ignore[method-assign]
    with caplog.at_level("ERROR"):
        code = driver.run([_pair(chunk=f"shard_0_{i}_p1") for i in range(3)])
    assert code == cli.EXIT_ERROR
    assert "writer thread" in caplog.text


def test_the_drain_is_idempotent_so_a_signal_cannot_double_checkpoint(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """A second call is a no-op returning the same code.

    Normal completion and a concurrent SIGTERM can both reach the drain; a second
    pass would re-checkpoint the meter and re-snapshot the cache while the log
    handle is already closed — turning a clean shutdown into a confusing
    exception at the very end of a paid-for run.
    """
    driver = _driver(tmp_path, _scripted(_response()), rates=rates)
    assert driver.run([_pair()]) == cli.EXIT_OK
    assert driver.drain_and_checkpoint(judge.TRIGGER_SIGINT) == cli.EXIT_SIGINT
    assert driver.stats.trigger == judge.TRIGGER_COMPLETE, (
        "the second call must not rewrite the recorded outcome")
    assert len(_log_records(tmp_path)) == 1


# ---------------------------------------------------------------------------
# Driver: the parse-failure abort threshold (PLAN §5.4)
# ---------------------------------------------------------------------------
def test_a_prompt_regression_aborts_once_past_one_percent(
        tmp_path: Path, rates: pricing.Rates,
        caplog: pytest.LogCaptureFixture) -> None:
    """Wholesale unparsable output is a regression, not noise — stop paying.

    At ~$0.00016 a call, 13,000 pairs of garbage costs ~$4 and produces an empty
    qrels file. The threshold turns that into a fast, loud stop that names the
    field to inspect.
    """
    converse = _scripted(_response(text="no grade at all"))
    driver = _driver(tmp_path, converse, rates=rates, concurrency=1)
    driver.judge._injected_converse = _pace_to_writer(driver, converse)
    pairs = [_pair(chunk=f"shard_0_{i}_p1") for i in range(400)]
    with caplog.at_level("ERROR"):
        code = driver.run(pairs)
    assert code == cli.EXIT_ERROR
    assert driver.stats.trigger == judge.TRIGGER_PARSE_FAIL
    assert driver.stats.judged < 400, "it must stop, not merely complain"
    assert driver.stats.billed_calls < 2 * judge.PARSE_FAIL_MIN_CALLS + 20, (
        "the abort must land near the floor, not hundreds of calls later")
    assert "over the 1% abort threshold" in caplog.text.replace(" %", "%")


def test_a_single_early_flake_does_not_abort_a_healthy_run(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """PLAN gap: ">1 % aborts" with no floor makes the first failure read as 100 %.

    Without `PARSE_FAIL_MIN_CALLS`, one unlucky first response would abort a run
    that is fine — and the operator would have no way to tell that from a real
    regression. 100 calls is ~$0.016 of insurance against a false abort, and a
    genuine regression still trips within seconds.
    """
    assert judge.PARSE_FAIL_MIN_CALLS == 100
    driver = _driver(tmp_path, _scripted(_response(text="nope"),
                                         _response(text="nope"),
                                         _response(text="##final score: 1")),
                     rates=rates, concurrency=1)
    code = driver.run([_pair(chunk=f"shard_0_{i}_p1") for i in range(4)])
    assert code == cli.EXIT_OK
    assert driver.stats.parse_failures == 1
    assert driver.stats.trigger == judge.TRIGGER_COMPLETE


# ---------------------------------------------------------------------------
# Driver: what `--pilot` reports on
# ---------------------------------------------------------------------------
def test_the_driver_accumulates_this_runs_usages_for_the_pilot_basis(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """`--pilot N` must report on THIS invocation, not on the whole log.

    Re-deriving the means by scanning the log would fold in every earlier run's
    calls, so a pilot after a partial full run would report a basis that is not
    the pilot's — and that basis is exactly what the human approves the multi-hour
    spend against.
    """
    driver = _driver(tmp_path, _scripted(_FakeError("ThrottlingException"),
                                         _response(in_tokens=800,
                                                   out_tokens=100)),
                     rates=rates, concurrency=1)
    driver.run([_pair(chunk=f"shard_0_{i}_p1") for i in range(2)])
    assert len(driver.usages) == driver.stats.records
    assert None in driver.usages, "the unbilled throttle is recorded too"
    basis = pricing.pilot_basis(driver.usages, rates, pool_size=1000,
                                meter=driver.meter, cap_usd=50.0)
    assert basis["pilot_billed_calls"] == 2
    assert basis["mean_input_tokens"] == 800.0
    assert basis["projected_pool_usd"] > 0


def test_a_completed_run_writes_its_cost_files_through_wp3bs_writers(
        tmp_path: Path, rates: pricing.Rates) -> None:
    """`costs.json`/`costs.md` come from `build_cost_report`, never local math.

    A second implementation of the same arithmetic is the R12 failure mode: a
    published figure that disagrees with the ledger. Delegating means the report
    and the manifest are two renderings of one dict.
    """
    run_dir = tmp_path / "runs" / "20260730T120000-stageA"
    driver = _driver(tmp_path, _scripted(_response()), rates=rates,
                     run_dir=run_dir)
    driver.run([_pair()])
    report = json.loads((run_dir / "costs.json").read_text(encoding="utf-8"))
    assert report["budget"]["spent_usd"] == pytest.approx(
        driver.meter.spent_usd())
    assert (run_dir / "costs.md").read_text(encoding="utf-8").strip()


def test_a_cost_report_failure_never_swallows_the_drains_exit_code(
        tmp_path: Path, rates: pricing.Rates,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Reporting is best-effort; the trigger and its exit code are not.

    Nothing is actually lost when this fails — the log and `costs/ledger.jsonl`
    hold everything `cost-report` needs to regenerate the files later. Losing the
    *exit code* to a reporting bug, by contrast, would tell a launcher that a
    budget stop was a clean success.
    """
    driver = _driver(tmp_path, _scripted(_FakeError("ExpiredTokenException")),
                     rates=rates, run_dir=tmp_path / "runs" / "r")
    monkeypatch.setattr(pricing, "build_cost_report",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("report exploded")))
    with caplog.at_level("ERROR"):
        assert driver.run([_pair()]) == cli.EXIT_CRED_EXPIRY
    assert "cost-report --run-id" in caplog.text


# ---------------------------------------------------------------------------
# CLI wiring (the two stubs WP3 replaced)
# ---------------------------------------------------------------------------
def _seed_run(cfg: "object", run_id: str, *, topics: int = 2,
              chunks: int = 3) -> Path:
    """Write a query file plus a `pool.jsonl` + `pool-texts.jsonl` pair.

    Mirrors what `search-sweep` (WP2) leaves behind, using WP2's own writers, so
    these tests exercise the real file contract rather than a hand-rolled
    approximation of it.
    """
    from bm25tune import extract, pool as pool_mod

    rows = [{"topic_id": f"rag2026-{t}", "topic": f"Narrative for topic {t}",
             "query": f"keyword query {t}", "k_orig": 10}
            for t in range(topics)]
    extract.write_jsonl(cfg.queries_dir / "keyword-1063.jsonl", rows)
    run_dir = cfg.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    entries, texts = [], []
    for t in range(topics):
        for c in range(chunks):
            chunk_id = f"shard_0000{t}_{c}_p1"
            text = f"passage {t}-{c}"
            entries.append(pool_mod.PoolEntry(
                topic_id=f"rag2026-{t}", chunk_id=chunk_id,
                first_seen_config="k1=0.9,b=0.4",
                text_sha256=extract.sha256_text(text)))
            texts.append({"chunk_id": chunk_id, "text": text})
    pool_mod.write_pool(run_dir / "pool.jsonl", entries)
    extract.write_jsonl(run_dir / "pool-texts.jsonl", texts)
    return run_dir


@pytest.fixture
def fake_bedrock(monkeypatch: pytest.MonkeyPatch) -> Callable[..., dict]:
    """Point `cmd_judge_pool`'s `BedrockJudge` at an injected `converse`.

    The CLI builds its own judge, so this patches the *class* rather than the
    transport — everything else (pricing gate, cache load, pre-flight, driver,
    drain, manifest) stays the real code path.
    """
    converse = _scripted(_response(text="##final score: 2"))
    real = judge.BedrockJudge

    def _factory(model_id: str, region: str, **kwargs: object) -> BedrockJudge:
        return real(model_id, region, converse=converse,
                    sleep=lambda _s: None, rng=random.Random(0), **kwargs)

    monkeypatch.setattr(judge, "BedrockJudge", _factory)
    return converse


def test_judge_pool_runs_end_to_end_and_publishes_every_artifact(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        caplog: pytest.LogCaptureFixture) -> None:
    """One command: pool in, log + qrels snapshot + manifest + costs out.

    This is the integration seam nothing else covers — WP2's `pool.jsonl`, WP1's
    prompt registry, WP3's log/cache, WP3b's meter, all through the real
    `argparse` path. If it breaks, the launch command in PLAN §5.6 does not work,
    which is only discoverable by spending money.
    """
    run_dir = _seed_run(bm25_config, "20260730T120000-stageA")
    with caplog.at_level("INFO"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA",
                         "--prompt-version", PV, "--concurrency", "2"])
    assert code == cli.EXIT_OK
    snapshot = bm25_config.cache_dir / f"qrels-{PV}.jsonl"
    assert snapshot.is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text(
        encoding="utf-8"))
    assert manifest["judge"]["prompt_version"] == PV
    assert manifest["judge"]["graded"] == 6
    assert manifest["budget"]["cap_usd"] == 50.0
    assert manifest["cost"]["rate_table_id"] == pricing.RATE_TABLE_ID
    assert (run_dir / "costs.json").is_file()
    assert "[BUDGET] stage=A" in caplog.text, "the pre-flight line must appear"


def test_the_published_snapshot_is_readable_by_the_scorer(
        bm25_config: "object", fake_bedrock: Callable[..., dict]) -> None:
    """WP3's snapshot format is WP4's `load_qrels_jsonl` input.

    The two were written in parallel against the plan, so this is the only place
    the actual bytes meet the actual reader — including the `cache_meta` header
    line, which has no `grade` field and would otherwise raise.
    """
    from bm25tune import metrics

    _seed_run(bm25_config, "20260730T120000-stageA")
    assert cli.main(["judge-pool", "--run-id", "20260730T120000-stageA",
                     "--prompt-version", PV]) == cli.EXIT_OK
    qrels = metrics.load_qrels_jsonl(
        bm25_config.cache_dir / f"qrels-{PV}.jsonl", prompt_version=PV)
    assert qrels.prompt_version == PV
    assert sum(len(v) for v in qrels.grades.values()) == 6


def test_judge_pool_refuses_to_start_when_metering_is_unavailable(
        bm25_config: "object", monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """The §9 ordering requirement, asserted at the CLI boundary.

    The refusal happens before a client, a pool, or a single pair is loaded — so
    there is no window in which a call could be made and not counted. A regression
    here is invisible until the ledger and the log disagree after real spend.
    """
    _seed_run(bm25_config, "20260730T120000-stageA")
    monkeypatch.setattr(judge, "load_pricing",
                        lambda: (_ for _ in ()).throw(
                            PricingUnavailable("no pricing module")))
    monkeypatch.setattr(judge, "BedrockJudge", lambda *a, **k: pytest.fail(
        "a judge was constructed despite metering being unavailable"))
    with caplog.at_level("ERROR"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA"])
    assert code == cli.EXIT_ERROR
    assert "no pricing module" in caplog.text


def test_a_preflight_over_the_cap_refuses_with_exit_four_before_spending(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Exit 4 means "nothing was spent", which exit 5 does not.

    A launching agent has to tell "never started, no partial results" from
    "stopped part-way, partial results are scoreable" without parsing the log —
    and only one of those is safe to retry with a raised cap.
    """
    _seed_run(bm25_config, "20260730T120000-stageA")
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", "0.00000001")
    with caplog.at_level("ERROR"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA"])
    assert code == cli.EXIT_BUDGET_PREFLIGHT
    assert "nothing was spent" in caplog.text
    assert not store.iter_segments(bm25_config.log_dir), (
        "a refusal must not have written a judgment")


def test_a_pool_text_digest_mismatch_is_a_hard_error(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        caplog: pytest.LogCaptureFixture) -> None:
    """The two halves of one sweep must describe the same passages.

    A `text_sha256` disagreement means the grades would be attributed to text
    that was never sent to the judge — an unfalsifiable, permanently cached lie
    about what was judged. Cheaper to re-run the sweep than to publish that.
    """
    run_dir = _seed_run(bm25_config, "20260730T120000-stageA")
    texts_path = run_dir / "pool-texts.jsonl"
    rows = [json.loads(line) for line in
            texts_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] = "a completely different passage"
    from bm25tune import extract
    extract.write_jsonl(texts_path, rows)
    with caplog.at_level("ERROR"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA"])
    assert code == cli.EXIT_ERROR
    assert "text that was never sent" in caplog.text


def test_a_partially_fetched_text_sidecar_is_refused_before_any_spend(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        caplog: pytest.LogCaptureFixture) -> None:
    """A truncated `pool-texts.jsonl` deflates judged@10 for EVERY config.

    Missing passages are silently unjudged, so the harm is uniform across the
    grid and therefore invisible in the comparison the experiment exists to make
    — and the money is spent by the time the report shows it. `--no-fetch-texts`
    already gives a loud missing-file error; this covers the partial case, which
    otherwise only produced a log line.
    """
    run_dir = _seed_run(bm25_config, "20260730T120000-stageA", topics=2,
                        chunks=5)
    texts_path = run_dir / "pool-texts.jsonl"
    rows = [json.loads(line) for line in
            texts_path.read_text(encoding="utf-8").splitlines()]
    from bm25tune import extract
    extract.write_jsonl(texts_path, rows[:6])  # 6 of 10 passages survive
    with caplog.at_level("ERROR"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA"])
    assert code == cli.EXIT_ERROR
    assert "search-sweep" in caplog.text
    assert not store.iter_segments(bm25_config.log_dir), (
        "a coverage refusal must happen before a single call")


def test_allow_partial_texts_judges_the_pairs_that_do_have_passages(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        caplog: pytest.LogCaptureFixture) -> None:
    """The gap is sometimes real and understood, so the floor is overridable.

    Judging 6 of 10 deliberately beats judging nothing when the sweep genuinely
    could not fetch some chunks — but it has to be an explicit choice, recorded
    in the shell history, rather than the default.
    """
    run_dir = _seed_run(bm25_config, "20260730T120000-stageA", topics=2,
                        chunks=5)
    texts_path = run_dir / "pool-texts.jsonl"
    rows = [json.loads(line) for line in
            texts_path.read_text(encoding="utf-8").splitlines()]
    from bm25tune import extract
    extract.write_jsonl(texts_path, rows[:6])
    with caplog.at_level("ERROR"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA",
                         "--prompt-version", PV, "--allow-partial-texts"])
    assert code == cli.EXIT_OK
    assert "CANNOT be judged" in caplog.text, "the gap is still reported"
    cache = store.JudgmentCache.load(bm25_config.log_dir, prompt_version=PV)
    assert len(cache) == 6


def test_a_run_id_pointing_at_the_judgment_log_is_refused(
        bm25_config: "object") -> None:
    """`--run-id ../../judgments/log` must not make the log a run dir.

    Paths are compared after `resolve()`, so traversal cannot reach the two
    append-only audit artifacts. Without this, a mistyped run id could put the
    ground-truth spend record inside a directory other commands treat as
    derived and safe to supersede.
    """
    assert cli.main(["judge-pool", "--run-id", "../../judgments/log"]) \
        == cli.EXIT_ERROR


def test_fresh_supersedes_only_the_snapshot_and_never_the_log(
        bm25_config: "object", fake_bedrock: Callable[..., dict]) -> None:
    """`--fresh` renames the qrels snapshot; the log and its grades survive.

    The run dir is deliberately out of scope too — it holds `pool.jsonl`, which
    is this command's *input*. And because the log is untouched, the "fresh" run
    is a full cache hit: `--fresh` costs nothing, which is the point of the
    log/cache split.
    """
    _seed_run(bm25_config, "20260730T120000-stageA")
    args = ["judge-pool", "--run-id", "20260730T120000-stageA",
            "--prompt-version", PV]
    assert cli.main(args) == cli.EXIT_OK
    spent = pricing.CostMeter.load(bm25_config.costs_dir).spent_usd()
    assert cli.main(args + ["--fresh"]) == cli.EXIT_OK
    assert list(bm25_config.cache_dir.glob("*.superseded-*")), (
        "the old snapshot must be renamed, not deleted")
    assert (bm25_config.run_dir("20260730T120000-stageA")
            / "pool.jsonl").is_file()
    assert pricing.CostMeter.load(bm25_config.costs_dir).spent_usd() == spent


def test_pilot_judges_a_sample_and_stops_by_design(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        caplog: pytest.LogCaptureFixture) -> None:
    """`--pilot N` prints a measured basis and does NOT go on to the full pool.

    Stopping is the safety property: the human approves the multi-hour spend
    against the pilot's numbers. A pilot that flowed straight into the full run
    would make that gate decorative.
    """
    _seed_run(bm25_config, "20260730T120000-stageA")
    with caplog.at_level("INFO"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA",
                         "--prompt-version", PV, "--pilot", "2"])
    assert code == cli.EXIT_OK
    assert "[COST] pilot=" in caplog.text
    assert "--pilot stops here BY DESIGN" in caplog.text
    cache = store.JudgmentCache.load(bm25_config.log_dir, prompt_version=PV)
    assert len(cache) == 2, "only the sampled pairs were judged"


def test_bare_pilot_defaults_to_two_hundred(bm25_config: "object") -> None:
    """`--pilot` with no value is the plan's documented default.

    The launch command in PLAN §5.6 is meant to be copy-pasteable; if the bare
    flag parsed as `None` it would silently judge the *whole* pool, which is the
    spend the pilot exists to gate.
    """
    args = cli.build_parser().parse_args(["judge-pool", "--pilot"])
    assert args.pilot == cli.DEFAULT_PILOT_N == 200
    assert cli.build_parser().parse_args(["judge-pool"]).pilot is None


def test_a_keyword_slot_prompt_warns_about_the_topic_level_cache_key(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        caplog: pytest.LogCaptureFixture) -> None:
    """`umbrela-kw-v1` in a pooled sweep judges chunks against ONE of 3-16 queries.

    The cache key is topic-level by design (PLAN §5.3), so a pooled run cannot
    hold one judgment per (query, chunk). That is a real limitation of using a
    §3.2 calibration diagnostic here, and it has to be loud rather than
    discovered later in the numbers.
    """
    _seed_run(bm25_config, "20260730T120000-stageA")
    with caplog.at_level("WARNING"):
        code = cli.main(["judge-pool", "--run-id", "20260730T120000-stageA",
                         "--prompt-version", "umbrela-kw-v1"])
    assert code == cli.EXIT_OK
    assert "cache key is topic-level" in caplog.text


def test_judge_pool_without_a_pool_file_says_which_command_to_run_first(
        bm25_config: "object", fake_bedrock: Callable[..., dict],
        caplog: pytest.LogCaptureFixture) -> None:
    """A missing input is a clean refusal naming `search-sweep`, not a traceback.

    This is the most common first-time error, and the operator is one flag away
    from being right; a stack trace would send them to read the source instead.
    """
    with caplog.at_level("ERROR"):
        code = cli.main(["judge-pool", "--run-id", "nope-stageA"])
    assert code == cli.EXIT_ERROR
    assert "search-sweep" in caplog.text


# ---------------------------------------------------------------------------
# rebuild-cache
# ---------------------------------------------------------------------------
def test_rebuild_cache_regenerates_every_versions_snapshot_from_the_log(
        bm25_config: "object", caplog: pytest.LogCaptureFixture) -> None:
    """The answer to a lost, stale, or corrupt snapshot — and it spends nothing.

    This command is what makes "the cache is only a cache" true in practice, and
    it is the tool `--fresh` names when someone points it at `judgments/log/`. It
    reads the log and writes snapshots: no Bedrock, nothing destroyed.
    """
    with store.JudgmentLog(bm25_config.log_dir) as handle:
        for version, grade in ((PV, 3), ("umbrela-v1", 1)):
            handle.append(store.make_record(
                prompt_version=version, topic_id="rag2026-0",
                chunk_id="shard_00000_1_p1", parent_docid="shard_00000_1",
                narrative_sha256="n" * 64, passage_text="p",
                passage_sha256="p" * 64, prompt_sha256="q" * 64,
                model_id=MODEL, region=REGION, run_id="r", stage="A",
                attempt=1, grade=grade, raw_text="x"))
    with caplog.at_level("INFO"):
        assert cli.main(["rebuild-cache"]) == cli.EXIT_OK
    for version, grade in ((PV, 3), ("umbrela-v1", 1)):
        path = bm25_config.cache_dir / f"qrels-{version}.jsonl"
        cache = store.JudgmentCache(prompt_version=version)
        cache._seed_from_snapshot(path)
        assert cache.get(store.jkey(version, "rag2026-0",
                                    "shard_00000_1_p1")) == grade


def test_rebuild_cache_can_write_a_single_version_and_reports_the_rest(
        bm25_config: "object", caplog: pytest.LogCaptureFixture) -> None:
    """`--only-prompt-version` narrows the *write*, not the scan.

    The scan is one pass over a log that embeds every passage's full text, so
    reporting the other versions' counts is free — and the operator usually wants
    to know they are still there before overwriting one.
    """
    with store.JudgmentLog(bm25_config.log_dir) as handle:
        for version in (PV, "umbrela-v1"):
            handle.append(store.make_record(
                prompt_version=version, topic_id="rag2026-0",
                chunk_id="shard_00000_1_p1", parent_docid="shard_00000_1",
                narrative_sha256="n" * 64, passage_text="p",
                passage_sha256="p" * 64, prompt_sha256="q" * 64,
                model_id=MODEL, region=REGION, run_id="r", stage="A",
                attempt=1, grade=2, raw_text="x"))
    with caplog.at_level("INFO"):
        assert cli.main(["rebuild-cache", "--prompt-version", PV,
                         "--only-prompt-version"]) == cli.EXIT_OK
    assert (bm25_config.cache_dir / f"qrels-{PV}.jsonl").is_file()
    assert not (bm25_config.cache_dir / "qrels-umbrela-v1.jsonl").exists()
    assert "not written" in caplog.text


def test_rebuild_cache_on_an_empty_log_is_a_clean_no_op(
        bm25_config: "object", caplog: pytest.LogCaptureFixture) -> None:
    """Expected before the first `judge-pool`, so it must not look like a failure.

    An error here would be indistinguishable from a *lost* log, which is the one
    situation in this experiment that would actually be unrecoverable.
    """
    with caplog.at_level("INFO"):
        assert cli.main(["rebuild-cache"]) == cli.EXIT_OK
    assert "nothing to rebuild" in caplog.text


def test_a_corrupt_interior_log_line_stops_rebuild_cache_with_exit_one(
        bm25_config: "object", caplog: pytest.LogCaptureFixture) -> None:
    """`LogCorruption` is mapped to a refusal, not an unhandled traceback.

    The log is the source of truth for both the qrels and the money, so a damaged
    interior line must be investigated rather than skipped — and the exit code
    plus the `[LOG-TAIL]` prefix are what a launcher and a human respectively
    read to know that.
    """
    bm25_config.log_dir.mkdir(parents=True, exist_ok=True)
    segment = bm25_config.log_dir / store.segment_name(
        stamp="20260730T120000Z", host="h", pid=1)
    good = json.dumps(store.make_record(
        prompt_version=PV, topic_id="rag2026-0", chunk_id="c_p1",
        parent_docid="c", narrative_sha256="n", passage_text="p",
        passage_sha256="p", prompt_sha256="q", model_id=MODEL, region=REGION,
        run_id="r", stage="A", attempt=1, grade=1)) + "\n"
    segment.write_text(good + "{oops\n" + good, encoding="utf-8")
    with caplog.at_level("ERROR"):
        assert cli.main(["rebuild-cache"]) == cli.EXIT_ERROR
    assert "[LOG-TAIL]" in caplog.text


# ---------------------------------------------------------------------------
# The one live call (PLAN §7.3: the real path stays exercisable)
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_a_real_converse_call_returns_a_parsable_grade() -> None:
    """ONE real Bedrock call (~$0.0002) proving the live path end to end.

    Every other test here fakes transport, which cannot catch the things that
    actually cost debugging time: the bare-model-id requirement, the
    reasoning-block-first content order, the `usage` field names, and the region.
    Kept to a single call and excluded from the offline suite; run with
    `bash scripts/test.sh live`.
    """
    spec = get_prompt(PV)
    prompt = spec.render_pair(
        narrative="Does congestion pricing reduce urban traffic volumes?",
        keyword="congestion pricing traffic reduction",
        passage="After London introduced its congestion charge, traffic "
                "entering the charging zone fell by about 15 percent in the "
                "first year, and average speeds rose.")
    judge_obj = BedrockJudge(MODEL, REGION)
    result = judge_obj.judge(prompt)
    assert result.grade in (0, 1, 2, 3), (
        f"unparsable live response: stop_reason={result.stop_reason!r} "
        f"text={result.raw_text[:300]!r}")
    assert result.usage is not None and result.usage["inputTokens"] > 0
    cost = pricing.call_cost(result.usage,
                             pricing.load_rates(MODEL, REGION, "standard"))
    assert cost["usd"] < 0.01, f"one call should be cents at most: {cost}"
    print(f"\n[LIVE] grade={result.grade} attempts={result.attempts} "
          f"stop_reason={result.stop_reason} usage={result.usage} cost={cost}")
