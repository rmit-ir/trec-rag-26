"""What `bm25tune/pricing.py` defends, and why every case here is load-bearing.

This module is the only thing standing between the experiment and two hard user
requirements: **spend must not exceed the exported ceiling** (US$50 as approved
on 2026-07-31; `BM25_TUNE_BUDGET_USD`, no default), and **every cost must be recorded
for the scientific report**. Both are enforced from the same numbers, so a single
arithmetic slip breaks the paper *and* the ceiling at once.

The three failure modes these tests exist to catch:

1. **A units slip (per-token vs per-1K).** The committed AWS extract prices per
   1 000 tokens. Reading it as per-token would report the paper's cost figure
   1000× too low *and* make the ceiling unreachable — the guard would never
   trip, which is precisely the runaway case (PLAN R11/R12) it was built for. So
   the first test pins a **hand-computed** dollar figure against the real
   committed file, not a fixture.
2. **A silent rate default.** An unknown (model, region, tier) must raise, never
   fall back. A guessed rate is indistinguishable from a correct one in the
   output, so it would corrupt the report undetectably.
3. **A guard that measures the prior instead of reality.** The reserve and the
   spend both have to track *observed* per-call cost; if either froze at the
   measured prior, a prompt-length blow-up would only be caught at the end,
   after the money was gone.

Plus the durability chain (log → ledger → totals) that PLAN §4.2 asks for, and
its asymmetry: a ledger *behind* the log is the ordinary crash artifact and
self-heals; a ledger *ahead* of the log cannot arise from a crash and is an
integrity error.

All hermetic — the rate table is committed data and nothing here reaches AWS.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from bm25tune import pricing
from bm25tune.pricing import (RATE_TABLE_ID, BudgetExceeded, BudgetGuard,
                              BudgetRefused, CostMeter, LedgerIntegrityError,
                              Rates, UnknownRate, call_cost, load_rates)

MODEL = "openai.gpt-oss-20b-1:0"
REGION = "ap-southeast-2"

# Hand-copied from the committed rate file, NOT read from it — the point of the
# first test is to compare two independently-sourced numbers.
INPUT_PER_1K = 0.0000721
OUTPUT_PER_1K = 0.000309


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _usage(inp: int, out: int) -> dict:
    return {"inputTokens": inp, "outputTokens": out}


def _standard_rates() -> Rates:
    return load_rates(MODEL, REGION, "standard")


def _log_segment(log_dir: Path, records: list[dict],
                 name: str = "events-20260730T120000-host-1.jsonl") -> Path:
    """Write a judgment-log segment in the PLAN §5.3 line format.

    `pricing.py` reads the log with its own tolerant scanner rather than
    importing `store` (WP3 owns writing it), so these tests must speak the wire
    format directly — which is exactly the coupling that needs pinning.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def _judgment(jkey: str, usd: float, *, run_id: str = "r1", stage: str = "A",
              **extra) -> dict:
    return {
        "kind": "judgment", "jkey": jkey, "prompt_version": "facet-v1",
        "grade": 2, "run_id": run_id, "stage": stage,
        "usage": _usage(900, 300),
        "cost": {"usd": usd, "input_usd": usd / 2, "output_usd": usd / 2,
                 "tier": "standard", "rate_table_id": RATE_TABLE_ID},
        "attempt": 1, "error": None, "stop_reason": "end_turn",
        **extra,
    }


# ---------------------------------------------------------------------------
# Rates and call_cost
# ---------------------------------------------------------------------------
def test_call_cost_matches_a_hand_computed_figure_from_the_committed_table() -> None:
    """The 1000× bug detector: pins dollars for known token counts.

    Arithmetic done by hand from the rates as printed in the committed file's
    `description` strings ($0.0000721 and $0.000309 per 1K tokens):

        934 input  -> 0.934 * 0.0000721 = 0.0000673414 -> 0.00006734 (8 dp)
        212 output -> 0.212 * 0.000309  = 0.0000655080 -> 0.00006551 (8 dp)
        total                                          = 0.00013285

    Those are exactly PLAN §5.3's example `cost` block, so this test also pins
    that the block the log stores is the one the plan documents. If a refactor
    ever reads `usd_per_unit` as per-token, this figure moves by three orders of
    magnitude — which would simultaneously misreport the paper's cost section and
    make `BudgetGuard` unable to reach the cap at all.
    """
    rates = _standard_rates()
    assert rates.input_per_1k == pytest.approx(INPUT_PER_1K, rel=0, abs=1e-12)
    assert rates.output_per_1k == pytest.approx(OUTPUT_PER_1K, rel=0, abs=1e-12)
    assert rates.table_id == RATE_TABLE_ID
    assert rates.tier == "standard"

    block = call_cost(_usage(934, 212), rates)
    assert block == {
        "usd": 0.00013285,
        "input_usd": 0.00006734,
        "output_usd": 0.00006551,
        "tier": "standard",
        "rate_table_id": RATE_TABLE_ID,
    }


def test_typical_and_worst_case_per_call_costs_reproduce_the_plan_table() -> None:
    """Re-derives PLAN §6.2b's headline figures so a rate edit fails here first.

    The whole "the cap has multiple-x headroom, so a trip is a BUG not a scope
    problem" argument (PLAN §0/§6.2b) rests on these three numbers. If a future
    rate table makes the plan's economics wrong, the executors need to know
    before they internalize the wrong posture — not after a `[BUDGET]` trip they
    then dismiss as expected.
    """
    rates = _standard_rates()
    typical = rates.call_usd(900, 300)
    worst = rates.call_usd(1040, 648)
    assert round(typical, 6) == 0.000158, typical
    assert round(worst, 6) == 0.000275, worst
    assert round(49_170 * typical, 2) == 7.75
    assert round(49_170 * worst, 2) == 13.53
    # $50 (the cap since 2026-07-31) buys ~182k worst-case calls — 3.7x the
    # entire plan. Still a circuit breaker rather than a scope limiter, which is
    # the posture the executors are told to hold; if a rate change ever made this
    # ratio approach 1x, that posture would be wrong and this assertion is where
    # it surfaces.
    assert 180_000 < 50.0 / worst < 184_000
    assert 3.5 < (50.0 / worst) / 49_170 < 3.9
    # The measured worst-case prior that floors the guard's reserve must be the
    # worst case rounded up to 6 dp, not something looser.
    assert pricing.WORST_CASE_CALL_USD_PRIOR == round(worst, 6) == 0.000275


@pytest.mark.parametrize("tier,inp,out", [
    ("standard", 0.0000721, 0.000309),
    ("batch", 0.00003605, 0.0001545),
    ("flex", 0.00003605, 0.0001545),
    ("priority", 0.000126175, 0.00054075),
])
def test_every_committed_tier_loads_with_the_rate_the_plan_records(
        tier: str, inp: float, out: float) -> None:
    """All four tiers resolve, so `BM25_TUNE_PRICING_TIER` can never mis-price.

    The tier is an env var an operator can set; if a tier key were missing the
    failure would be `UnknownRate` at judge start (loud, fine) — but if tier
    parsing matched loosely it could resolve to the *wrong* tier's rate, which
    is silent. Pinning all eight numbers makes that impossible.
    """
    rates = load_rates(MODEL, REGION, tier)
    assert rates.input_per_1k == pytest.approx(inp, rel=0, abs=1e-12)
    assert rates.output_per_1k == pytest.approx(out, rel=0, abs=1e-12)
    assert rates.tier == tier


@pytest.mark.parametrize("model,region,tier", [
    ("anthropic.claude-3-5-sonnet-20240620-v1:0", REGION, "standard"),
    ("us.openai.gpt-oss-20b-1:0", REGION, "standard"),   # the profile-prefixed id
    (MODEL, "us-east-1", "standard"),
    (MODEL, REGION, "provisioned"),
])
def test_load_rates_refuses_an_unknown_model_region_or_tier(
        model: str, region: str, tier: str) -> None:
    """No silent default — a guessed rate is invisible in the output.

    The `us.*` case is the realistic one: PLAN §1 records that profile-prefixed
    ids raise ValidationException on Bedrock, so a caller who passes one has a
    real bug, and quietly pricing it at the bare id's rate would hide it. Every
    other case would corrupt the report by an unknown factor while looking
    perfectly plausible (PLAN R12).
    """
    with pytest.raises(UnknownRate):
        load_rates(model, region, tier)


def test_load_rates_rejects_a_table_priced_per_token_rather_than_per_1k(
        tmp_path: Path) -> None:
    """The units assertion, exercised: a per-token table must not load silently.

    This is the R12 scenario as an actual file. Without the check, every figure
    would be 1000× too small: `spent` would crawl, the ceiling would never trip,
    and the paper would report a cost that is off by three orders of magnitude —
    and nothing in the output would look wrong.
    """
    table = json.loads(pricing.rate_table_path().read_text())
    for entry in table["rates"].values():
        entry["unit"] = "tokens"
    (tmp_path / f"{RATE_TABLE_ID}.json").write_text(json.dumps(table))
    with pytest.raises(pricing.PricingError, match="1000x"):
        load_rates(MODEL, REGION, "standard", prices_dir=tmp_path)


def test_usage_null_costs_nothing_and_does_not_crash_the_meter(
        tmp_path: Path) -> None:
    """A call that never reached the model is free — and must stay meterable.

    `usage: null` marks a throttle-before-send or a rejected credential (PLAN
    §5.3). It must produce `cost: null` (charging for it would inflate the
    report) and must not except inside `add()` — the credential-expiry path is
    the *worst* place for the meter to die, because the drain that follows is
    what saves the already-billed work.
    """
    rates = _standard_rates()
    assert call_cost(None, rates) is None

    meter = CostMeter(tmp_path)
    meter.add(None, None, run_id="r1", stage="A")
    assert meter.spent_usd() == 0.0
    assert meter.state.records == 1
    assert meter.state.calls == 0        # not a billed call
    assert meter.state.basis == "prior"  # so the pre-flight keeps the priors
    assert meter.state.max_call_usd == 0.0


def test_a_malformed_token_count_is_treated_as_zero_rather_than_crashing(
        tmp_path: Path) -> None:
    """One weird usage block must cost the run a data point, not the run.

    A multi-hour job that dies on `{"inputTokens": null}` loses every in-flight
    judgment (all already billed). Under-counting one call by a fraction of a
    cent is strictly cheaper, and it is visible in the log as a `[COST]` warning.
    """
    rates = _standard_rates()
    block = call_cost({"inputTokens": None, "outputTokens": "abc"}, rates)
    assert block is not None and block["usd"] == 0.0

    meter = CostMeter(tmp_path)
    meter.add(block, {"inputTokens": None, "outputTokens": "abc"},
              run_id="r1", stage="A")
    assert meter.state.calls == 1
    assert meter.state.input_tokens == 0


# ---------------------------------------------------------------------------
# CostMeter durability
# ---------------------------------------------------------------------------
def test_meter_round_trips_load_add_checkpoint_reload(tmp_path: Path) -> None:
    """The cap spans the whole experiment, so spend MUST survive a restart.

    Calibration, Stage A, Stage B and the continuity pass are separate
    invocations with different `run_id`s. If the meter reset on each one, the
    "$50 for the entire process" requirement would silently become "$50 per
    invocation" — the ceiling would still be *there* and would still never be
    reached, which is the worst kind of broken: untestable in production.
    """
    rates = _standard_rates()
    meter = CostMeter.load(tmp_path)
    assert meter.spent_usd() == 0.0

    for _ in range(4):
        usage = _usage(900, 300)
        meter.add(call_cost(usage, rates), usage, run_id="r-calib", stage="calib")
    usage = _usage(1040, 648)
    meter.add(call_cost(usage, rates), usage, run_id="r-A", stage="A")
    meter.checkpoint()

    reloaded = CostMeter.load(tmp_path)
    assert reloaded.spent_usd() == pytest.approx(meter.spent_usd(), abs=1e-12)
    assert reloaded.state.calls == 5
    assert reloaded.state.input_tokens == 4 * 900 + 1040
    assert reloaded.state.output_tokens == 4 * 300 + 648
    assert set(reloaded.spent_by_stage()) == {"calib", "A"}
    assert set(reloaded.spent_by_run()) == {"r-calib", "r-A"}
    # The worst observed call is the 1040/648 one — the guard's reserve basis.
    # It carries the *recorded* (8-dp) figure, i.e. the one the log shows, not a
    # re-derived exact value: the reserve must be justifiable from the artifacts.
    assert reloaded.state.max_call_usd == call_cost(_usage(1040, 648),
                                                    rates)["usd"]
    assert reloaded.state.max_call_usd == pytest.approx(
        rates.call_usd(1040, 648), abs=1e-8)


def test_reloaded_meter_reports_measured_means_so_preflight_stops_guessing(
        tmp_path: Path) -> None:
    """WP0's measured token counts must replace the priors for every later stage.

    PLAN §5.7 layer 1 promises `basis=measured` after calibration. If the means
    stayed at the 900/300 priors, the Stage-B estimate would be wrong in an
    unknown direction and `preflight_estimate_usd / actual_usd` — a reportable
    number in the manifest — would measure nothing.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    for tokens in ((800, 100), (1000, 500)):
        usage = _usage(*tokens)
        meter.add(call_cost(usage, rates), usage, run_id="r", stage="calib")
    meter.checkpoint()

    state = CostMeter.load(tmp_path).state
    assert state.basis == "measured"
    assert state.mean_input_tokens == pytest.approx(900.0)
    assert state.mean_output_tokens == pytest.approx(300.0)
    assert state.mean_call_usd == pytest.approx(meter.spent_usd() / 2)


def test_ledger_replay_reproduces_totals_json_exactly(tmp_path: Path) -> None:
    """`totals.json` is a cache of the ledger — losing it must not lose the cap.

    PLAN §4.2 wants three levels of derivability (log → ledger → totals). This
    pins the middle link: deleting `totals.json` and replaying the append-only
    ledger yields the same spend, calls and per-stage split. Checkpoint lines
    carry *absolute* state precisely so one lost line cannot shift the replay.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    for index in range(25):
        usage = _usage(900 + index, 300)
        meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    meter.checkpoint()
    totals = json.loads(meter.totals_path.read_text())

    replayed = pricing.replay_ledger(meter.ledger_path)
    assert replayed.to_json() == totals

    meter.totals_path.unlink()
    assert CostMeter.load(tmp_path).spent_usd() == pytest.approx(
        meter.spent_usd(), abs=1e-12)


def test_a_corrupt_totals_file_falls_back_to_the_ledger(tmp_path: Path) -> None:
    """A half-written `totals.json` must not be fatal, nor reset the budget.

    `totals.json` is rewritten atomically, but a full disk or an out-of-band
    edit can still leave junk. Treating that as "spend = 0" would silently hand
    the experiment a fresh cap; refusing to start would block a resume. Falling
    back to the append-only ledger is the only answer that loses nothing.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    usage = _usage(900, 300)
    meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    meter.checkpoint()
    expected = meter.spent_usd()

    meter.totals_path.write_text("{not json")
    assert CostMeter.load(tmp_path).spent_usd() == pytest.approx(expected)


def test_a_truncated_final_ledger_line_is_tolerated_but_an_interior_one_is_not(
        tmp_path: Path) -> None:
    """Crash-during-append is recoverable; corruption in the middle is not.

    A machine crash can only ever truncate the *last* line. Tolerating that
    keeps a resume working. Tolerating a malformed *interior* line would mean
    silently reading a mangled ledger as authoritative — so it raises, naming
    the judgment log as the rebuild source.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    usage = _usage(900, 300)
    meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    meter.checkpoint()
    good = meter.ledger_path.read_text()

    meter.ledger_path.write_text(good + '{"kind": "checkpo')
    assert pricing.replay_ledger(meter.ledger_path).calls == 1

    meter.ledger_path.write_text('{"kind": "checkpo\n' + good)
    with pytest.raises(pricing.PricingError, match="interior line"):
        pricing.replay_ledger(meter.ledger_path)


def test_checkpoint_cadence_matches_the_log_fsync_window(tmp_path: Path) -> None:
    """Bounding the crash window is what makes the lagging ledger self-heal safe.

    PLAN §5.3/§5.8 fix the cadence at 10 records **or** 5 seconds, whichever
    first, so ledger and log can never drift by more than one window. The
    time-based branch is the one that matters at a low call rate — a pure
    line-count rule would leave minutes of already-billed work exposed — so it
    is driven here with a fake clock rather than left to a real one.
    """
    rates = _standard_rates()
    now = [0.0]
    meter = CostMeter(tmp_path, clock=lambda: now[0])
    usage = _usage(900, 300)

    for _ in range(9):
        meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    assert meter.state.checkpoints == 0, "checkpointed before 10 records"
    meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    assert meter.state.checkpoints == 1, "10th record did not checkpoint"

    meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    assert meter.state.checkpoints == 1
    now[0] += pricing.CHECKPOINT_EVERY_SECONDS
    meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    assert meter.state.checkpoints == 2, "the 5-second branch never fired"


def test_add_and_check_are_documented_as_single_writer_thread_only() -> None:
    """Pins the invariant a future 'optimization' is most likely to break.

    `CostMeter` takes no lock: safety comes from PLAN §5.4's design, where the
    one writer thread is the sole consumer of the results queue. Moving `add()`
    into the worker callbacks would silently lose increments — spend would be
    *under*-reported, the direction that costs real money — and nothing would
    fail visibly. Since there is no runtime assertion that could catch it
    cheaply, the contract is pinned as prose, in the three docstrings a future
    editor reads before touching this.
    """
    assert "writer thread" in (pricing.__doc__ or "").lower()
    for func in (CostMeter.add, CostMeter.checkpoint, BudgetGuard.check):
        assert "writer thread" in (func.__doc__ or "").lower(), func.__name__


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------
def test_a_log_ahead_of_the_ledger_self_heals_on_reconcile(
        tmp_path: Path) -> None:
    """The ordinary crash artifact: bounded, expected, and must not block a resume.

    The judgment log is written first, per call, so a crash inside a checkpoint
    window always leaves the ledger behind. `reconcile` adopts the log total and
    records a `heal` line — the ledger stays append-only (nothing is rewritten)
    and the budget state comes back to truth, so the resume prices correctly
    instead of granting itself the un-checkpointed spend all over again.
    """
    log_dir = tmp_path / "log"
    costs = tmp_path / "costs"
    _log_segment(log_dir, [_judgment(f"k{i}", 0.001) for i in range(10)])

    meter = CostMeter.load(costs)
    ledger_total, log_total = meter.reconcile(log_dir)
    assert ledger_total == 0.0
    assert log_total == pytest.approx(0.01)
    assert meter.spent_usd() == pytest.approx(0.01)
    assert meter.state.heals == 1

    kinds = [r["kind"] for r in pricing.read_ledger(meter.ledger_path)]
    assert kinds == ["heal"]
    # And it is durable: the healed total is what the next process loads.
    assert CostMeter.load(costs).spent_usd() == pytest.approx(0.01)


def test_a_ledger_ahead_of_the_log_is_an_integrity_error(tmp_path: Path) -> None:
    """This direction cannot come from a crash, so auto-healing it would be wrong.

    A ledger claiming more spend than the log can account for means a doctored
    ledger or a lost/moved log segment. Both invalidate the audit trail the
    report is written from; quietly adopting either number would let real spend
    go unexplained. The message therefore names the log dir to investigate.
    """
    log_dir = tmp_path / "log"
    costs = tmp_path / "costs"
    _log_segment(log_dir, [_judgment("k0", 0.001)])
    rates = _standard_rates()
    meter = CostMeter(costs)
    for _ in range(50):
        usage = _usage(900, 300)
        meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    meter.checkpoint()

    with pytest.raises(LedgerIntegrityError, match="doctored ledger"):
        meter.reconcile(log_dir)


def test_reconciliation_within_tolerance_is_ok_and_never_heals(
        tmp_path: Path) -> None:
    """Rounding must not masquerade as a crash — or trip the integrity alarm.

    Per-call costs are rounded to 8 dp when recorded, so ledger and log agree to
    ~1e-4 US$ over the whole plan. Without the ±$0.001 tolerance every run would
    log a spurious heal (noise that trains operators to ignore the line) or a
    spurious integrity error (which halts a legitimate run).
    """
    log_dir = tmp_path / "log"
    costs = tmp_path / "costs"
    rates = _standard_rates()
    usages = [_usage(900 + i, 300 + i) for i in range(5)]
    records = []
    meter = CostMeter(costs)
    for index, usage in enumerate(usages):
        block = call_cost(usage, rates)
        records.append({**_judgment(f"k{index}", block["usd"]),
                        "usage": usage, "cost": block})
        meter.add(block, usage, run_id="r", stage="A")
    meter.checkpoint()
    _log_segment(log_dir, records)

    before = meter.spent_usd()
    ledger_total, log_total = meter.reconcile(log_dir)
    assert ledger_total == pytest.approx(log_total, abs=1e-12)
    assert meter.state.heals == 0
    assert meter.spent_usd() == before
    assert meter.reconciliation_report(log_dir)["status"] == "ok"


def test_the_log_total_includes_billed_failures_and_retries(
        tmp_path: Path) -> None:
    """Ground truth is what AWS billed, not what produced a usable grade.

    A call that returned an empty text at `stopReason=max_tokens`, or an
    unparseable grade, was billed. Summing only `kind: "judgment"` rows would
    under-report the bill — so the reconciliation would then flag the *correct*
    ledger as ahead of the log, i.e. the integrity alarm would fire on healthy
    runs and the real signal would be lost.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [
        _judgment("k0", 0.001),
        {**_judgment("k0", 0.002), "kind": "attempt_error", "grade": None,
         "error": "parse_failure", "attempt": 1},
        {**_judgment("k1", 0.003), "kind": "attempt_error", "grade": None,
         "error": "throttle", "usage": None, "cost": None},
    ])
    assert pricing.judgment_log_total_usd(log_dir) == pytest.approx(0.003)


def test_a_truncated_final_log_line_does_not_break_the_cost_total(
        tmp_path: Path) -> None:
    """A crash mid-write must not make the whole cost report unreadable.

    PLAN §5.3 promises at most one truncated final line per segment. If the cost
    scanner raised on it, `cost-report` would be unusable after exactly the
    event it is most needed for, and the operator's only recourse would be to
    hand-edit the audit record.
    """
    log_dir = tmp_path / "log"
    path = _log_segment(log_dir, [_judgment("k0", 0.001)])
    path.write_text(path.read_text() + '{"kind": "judgment", "cos')
    assert pricing.judgment_log_total_usd(log_dir) == pytest.approx(0.001)


def test_two_writer_segments_are_summed(tmp_path: Path) -> None:
    """Per-process segments mean spend is spread across files after any resume.

    PLAN §5.3 gives every writer process its own segment (no shared handles, no
    locking). A cost scanner that only read the newest one would under-report
    every resumed run — and resuming is the *normal* path after a cred expiry or
    a budget stop.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [_judgment("k0", 0.001)],
                 name="events-20260730T120000-hostA-1.jsonl")
    _log_segment(log_dir, [_judgment("k1", 0.002)],
                 name="events-20260730T130000-hostA-2.jsonl")
    assert pricing.judgment_log_total_usd(log_dir) == pytest.approx(0.003)


# ---------------------------------------------------------------------------
# BudgetGuard — layer 1 (pre-flight)
# ---------------------------------------------------------------------------
def test_preflight_refuses_before_spending_when_the_estimate_exceeds_the_cap(
        tmp_path: Path) -> None:
    """Exit-4 semantics: refuse *first*, so a bad plan costs nothing at all.

    This is the only layer that can prevent spend rather than curtail it. The
    message must name the shortfall and point at the env var, and must say a
    refusal is prima facie a bug (expected total is ~$8-14 against a $50 cap,
    PLAN §6.2b) — otherwise the reflex becomes "raise the cap", which is exactly
    what R11 forbids.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    guard = BudgetGuard(meter, cap_usd=1.0, concurrency=16, rates=rates)

    ok = guard.preflight(1_000, stage="A")
    assert ok["ok"] is True
    assert ok["basis"] == "prior"
    assert ok["est_usd"] == pytest.approx(1_000 * rates.call_usd(900, 300),
                                          rel=1e-6)
    assert "[BUDGET] stage=A" in ok["line"] and "→ OK" in ok["line"]

    with pytest.raises(BudgetRefused) as excinfo:
        guard.preflight(10_000_000, stage="A")
    message = str(excinfo.value)
    assert "REFUSED" in message
    assert "BM25_TUNE_BUDGET_USD" in message
    assert "BUG" in message
    assert "Nothing has been spent" in message
    # And nothing was: the refusal is pure arithmetic.
    assert meter.spent_usd() == 0.0
    assert not meter.ledger_path.exists()


def test_preflight_uses_measured_means_once_the_meter_has_data(
        tmp_path: Path) -> None:
    """After WP0, the estimate must stop being a guess (PLAN §5.7 layer 1).

    A blow-up in prompt length shows up in the *measured* means, so a pre-flight
    that kept using the 900/300 priors would happily authorize a stage that the
    per-call guard then aborts hours in. Measured means make the cheap check the
    one that catches it.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    usage = _usage(9_000, 3_000)   # 10x the prior — a prompt blow-up
    meter.add(call_cost(usage, rates), usage, run_id="r", stage="calib")

    guard = BudgetGuard(meter, cap_usd=50.0, concurrency=16, rates=rates)
    estimate = guard.preflight(1_000, stage="A")
    assert estimate["basis"] == "measured"
    assert estimate["mean_input_tokens"] == pytest.approx(9_000.0)
    assert estimate["est_usd"] == pytest.approx(
        1_000 * rates.call_usd(9_000, 3_000), rel=1e-6)
    assert "basis=measured" in estimate["line"]


def test_preflight_honours_explicit_token_estimates_over_the_meter(
        tmp_path: Path) -> None:
    """The caller must be able to price a hypothetical (a finer grid, a re-prompt).

    PLAN §6.2b invites the user to spend the headroom on options that change the
    token profile. Explicit means are labeled `basis=explicit` so a `[BUDGET]`
    line always says where its numbers came from — an estimate whose provenance
    is ambiguous is not auditable.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    usage = _usage(900, 300)
    meter.add(call_cost(usage, rates), usage, run_id="r", stage="calib")
    guard = BudgetGuard(meter, cap_usd=50.0, concurrency=16, rates=rates)

    estimate = guard.preflight(100, 2_000, 600, stage="B")
    assert estimate["basis"] == "explicit"
    assert estimate["est_usd"] == pytest.approx(100 * rates.call_usd(2_000, 600),
                                                rel=1e-9)


def test_preflight_without_rates_is_a_programming_error_not_a_free_pass(
        tmp_path: Path) -> None:
    """A guard built without rates must refuse to estimate, not estimate $0.

    Returning "$0, fits fine" would turn a wiring mistake into an unmetered
    launch — the one thing PLAN §9 says must never exist.
    """
    guard = BudgetGuard(CostMeter(tmp_path), cap_usd=50.0, concurrency=16)
    with pytest.raises(pricing.PricingError, match="rates"):
        guard.preflight(100, stage="A")


# ---------------------------------------------------------------------------
# BudgetGuard — layer 2 (continuous)
# ---------------------------------------------------------------------------
def test_check_takes_no_arguments_and_trips_on_observed_spend(
        tmp_path: Path) -> None:
    """The per-record stop: `spent + reserve >= cap`, evaluated on real spend.

    `check()` deliberately takes no arguments — there is no "batch" in the judge
    loop (PLAN §5.7 layer 2), it runs once per completed record on the writer
    thread. Feeding real costs through the meter (rather than asserting on a
    hand-set `spent_usd`) is what pins that the two halves are wired to each
    other and not to two different notions of spend.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    guard = BudgetGuard(meter, cap_usd=0.01, concurrency=4, rates=rates)
    guard.check()   # a cold meter is never over budget

    usage = _usage(900, 300)
    with pytest.raises(BudgetExceeded) as excinfo:
        for _ in range(500):
            meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
            guard.check()
    message = str(excinfo.value)
    assert "[BUDGET]" in message and "reserve=" in message
    # It tripped early, not after blowing far past the cap: spend at the moment
    # of the raise is still under the cap, with the reserve covering the rest.
    assert meter.spent_usd() < guard.cap_usd
    assert meter.spent_usd() + guard.reserve_usd() >= guard.cap_usd


def test_check_tracks_observed_cost_drift_not_the_prior(tmp_path: Path) -> None:
    """R11's runaway: inflated tokens must trip the guard within a few calls.

    Fed usage blocks 100× the prior, the guard must trip because *both* halves
    respond to reality — spend accrues 100× faster, and the reserve rises with
    `max_observed_cost_per_call`. If either were frozen at the measured prior,
    a prompt-length blow-up would only be caught at the end, after the money
    was gone. The comparison against a same-cap guard fed prior-sized calls is
    the actual assertion: the drifting run must stop far sooner.
    """
    rates = _standard_rates()
    cap = 0.05
    fat = _usage(90_000, 30_000)      # ~100x the typical call
    lean = _usage(900, 300)

    def _calls_until_stop(usage: dict) -> int:
        meter = CostMeter(tmp_path / f"c{usage['inputTokens']}")
        guard = BudgetGuard(meter, cap_usd=cap, concurrency=16, rates=rates)
        for count in range(1, 5_000):
            meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
            try:
                guard.check()
            except BudgetExceeded:
                return count
        return -1

    fat_calls = _calls_until_stop(fat)
    lean_calls = _calls_until_stop(lean)
    assert 0 < fat_calls <= 5, fat_calls          # trips within seconds
    assert lean_calls > 100 * fat_calls, (lean_calls, fat_calls)

    # And the reserve itself grew with the observed maximum, rather than
    # remaining the concurrency x prior floor.
    meter = CostMeter(tmp_path / "reserve")
    guard = BudgetGuard(meter, cap_usd=50.0, concurrency=16, rates=rates)
    floor = guard.reserve_usd()
    assert floor == pytest.approx(16 * pricing.WORST_CASE_CALL_USD_PRIOR)
    meter.add(call_cost(fat, rates), fat, run_id="r", stage="A")
    assert guard.reserve_usd() == pytest.approx(
        16 * call_cost(fat, rates)["usd"])
    assert guard.reserve_usd() > 50 * floor


def test_the_reserve_is_concurrency_times_worst_call_not_a_fraction_of_the_cap(
        tmp_path: Path) -> None:
    """Pins the sizing an earlier design got ~900x wrong.

    A fixed 2 % of a $50 cap is $1 — a large fraction of the plan's expected spend
    — and it is not tied to what is actually in flight. The correct reserve is
    `concurrency x max_observed_cost_per_call`, floored at the measured
    worst-case prior: at concurrency 16 that is ~$0.0044, which provably covers
    the overshoot the drain will still record while taking no meaningful bite
    out of the cap.
    """
    meter = CostMeter(tmp_path)
    guard = BudgetGuard(meter, cap_usd=50.0, concurrency=16)
    assert guard.reserve_usd() == pytest.approx(0.0044, abs=1e-4)
    assert guard.reserve_usd() < 0.0001 * guard.cap_usd
    assert BudgetGuard(meter, 50.0, 32).reserve_usd() == pytest.approx(
        2 * guard.reserve_usd())


def test_a_nonpositive_cap_is_rejected_at_construction(tmp_path: Path) -> None:
    """`BM25_TUNE_BUDGET_USD=0` must be a config error, not a silent no-op run.

    With cap 0 every `check()` would trip immediately, which reads in the log
    exactly like a runaway — sending the operator hunting a bug in the judge.
    """
    for cap in (0.0, -1.0):
        with pytest.raises(ValueError, match="cap_usd"):
            BudgetGuard(CostMeter(tmp_path), cap_usd=cap, concurrency=16)


def test_nonstandard_tier_warns_that_metered_spend_will_not_match_the_bill(
        caplog: pytest.LogCaptureFixture) -> None:
    """Accounting at batch/flex rates under-reports real spend by ~2x.

    The Converse path always bills at standard (PLAN §4.1), so a `batch` tier
    only changes the *accounting* — in the direction that hides money. The
    warning is returned as well as logged so `costs.md` can carry it, since a
    figure copied into a paper outlives the log it came from.
    """
    assert pricing.warn_if_nonstandard_tier("standard") is None
    line = pricing.warn_if_nonstandard_tier("batch")
    assert line is not None
    assert "[COST]" in line and "will not match the AWS bill" in line


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def test_cost_report_splits_by_stage_and_prompt_version(tmp_path: Path) -> None:
    """The report must attribute spend, not just total it.

    PLAN §5.7 requires per-stage and per-prompt-version splits because the paper
    needs to say what calibration cost versus the sweep, and what the
    `umbrela-v1` continuity pass cost on top. `run_id`/`stage` are billing
    metadata that deliberately never enter the cache key (§5.3), so this split is
    the *only* place that attribution exists.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [
        {**_judgment("a", 0.001, stage="calib"), "prompt_version": "facet-v1"},
        {**_judgment("b", 0.002, stage="calib"),
         "prompt_version": "umbrela-v1"},
        {**_judgment("c", 0.004, stage="A"), "prompt_version": "facet-v1"},
    ])
    meter = CostMeter(tmp_path / "costs")
    report = pricing.build_cost_report(log_dir, meter, cap_usd=50.0,
                                       rates=_standard_rates())
    exp = report["experiment"]
    assert exp["usd_by_stage"] == {"A": 0.004, "calib": 0.003}
    assert exp["by_prompt_version"]["facet-v1"]["usd"] == pytest.approx(0.005)
    assert exp["by_prompt_version"]["umbrela-v1"]["usd"] == pytest.approx(0.002)
    assert report["rate_table_id"] == RATE_TABLE_ID
    assert report["tier"] == "standard"


def test_usd_per_judged_pair_counts_unique_jkeys_so_re_prompts_count_twice(
        tmp_path: Path) -> None:
    """The denominator must match what was billed, not what was learned.

    PLAN §5.7 defines a judged pair as a unique `jkey` — prompt-version
    qualified — so the same (topic, chunk) judged under two prompts counts twice.
    Deduping to (topic, chunk) would divide by a smaller number and overstate the
    cost per pair; deduping over retries would understate it. Retries share a
    `jkey`, so they must not inflate the count either.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [
        _judgment("facet-v1::t1::c1", 0.001),
        # same pair, second prompt version -> a distinct jkey, billed again
        {**_judgment("umbrela-v1::t1::c1", 0.001),
         "prompt_version": "umbrela-v1"},
        # a retry of the first: same jkey, extra spend, NOT an extra pair
        {**_judgment("facet-v1::t1::c1", 0.002), "attempt": 2},
    ])
    exp = pricing.build_cost_report(
        log_dir, CostMeter(tmp_path / "costs"), cap_usd=50.0)["experiment"]
    assert exp["judged_pairs"] == 2
    assert exp["total_usd"] == pytest.approx(0.004)
    assert exp["usd_per_judged_pair"] == pytest.approx(0.002)


def test_cache_savings_are_labeled_an_estimate_everywhere_they_appear(
        tmp_path: Path) -> None:
    """A number the paper will quote must not look measured when it is inferred.

    The avoided calls' token counts are unknowable, so US$-saved-by-cache is
    `cache_hits x observed mean cost per call`. If the JSON or the markdown
    presented it bare, it would be cited as a measurement — so the label travels
    with the value in both renderings and in the manifest block.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [_judgment("a", 0.002), _judgment("b", 0.004)])
    report = pricing.build_cost_report(
        log_dir, CostMeter(tmp_path / "costs"), cap_usd=50.0, cache_hits=1_000,
        rates=_standard_rates())
    cache = report["experiment"]["cache"]
    assert cache["usd_saved_by_cache_estimate"] == pytest.approx(1_000 * 0.003)
    assert "ESTIMATE" in cache["note"]

    md = pricing.render_cost_report_md(report)
    assert "ESTIMATE" in md
    assert "US$ saved by the cache" in md

    fields = pricing.manifest_cost_fields(report, cap_usd=50.0,
                                          spent_before_usd=0.0)
    assert fields["cost"]["usd_saved_by_cache_is_estimate"] is True


def test_wasted_spend_is_categorised_and_de_duplicated(tmp_path: Path) -> None:
    """"How much did we pay for nothing" is a report figure, so it must not double-count.

    A truncation is usually *also* a parse failure, so summing the categories
    would overstate waste — and waste is the number that tells the next
    experiment whether `maxTokens=1024` and the retry policy were right. Hence
    per-category figures plus an explicit de-duplicated union.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [
        _judgment("ok", 0.001),
        {**_judgment("trunc", 0.002), "kind": "attempt_error", "grade": None,
         "error": "parse_failure", "stop_reason": "max_tokens"},
        {**_judgment("retry", 0.004), "attempt": 2},
    ])
    wasted = pricing.build_cost_report(
        log_dir, CostMeter(tmp_path / "costs"),
        cap_usd=50.0)["experiment"]["wasted_usd"]
    assert wasted["parse_failures"] == pytest.approx(0.002)
    assert wasted["truncations"] == pytest.approx(0.002)
    assert wasted["retries"] == pytest.approx(0.004)
    # 0.002 counted once despite being in two categories.
    assert wasted["total_usd"] == pytest.approx(0.006)
    assert "overlap" in wasted["note"]


def test_token_percentiles_are_nearest_rank_observed_values(
        tmp_path: Path) -> None:
    """A quoted p95 should be a call that happened, not an interpolation.

    PLAN §5.7 wants mean/median/p95 tokens per call. Nearest-rank keeps every
    published percentile equal to an actually-observed token count, so the
    figure is reproducible from the log without knowing which interpolation
    convention the reporter used.
    """
    log_dir = tmp_path / "log"
    rates = _standard_rates()
    records = []
    for index in range(20):
        usage = _usage(100 * (index + 1), 50)
        records.append({**_judgment(f"k{index}", 0.0), "usage": usage,
                        "cost": call_cost(usage, rates)})
    _log_segment(log_dir, records)
    stats = pricing.build_cost_report(
        log_dir, CostMeter(tmp_path / "costs"),
        cap_usd=50.0)["experiment"]["input_tokens"]
    assert stats["n"] == 20
    assert stats["min"] == 100 and stats["max"] == 2000
    assert stats["median"] == pytest.approx(1050.0)
    assert stats["p95"] == 1900.0   # the 19th of 20 sorted values


def test_cost_report_scoped_to_a_run_keeps_the_experiment_roll_up(
        tmp_path: Path) -> None:
    """A per-run report alone could never answer "how much of the cap is left".

    The cap is experiment-wide, so `--run-id` must *add* a breakdown rather than
    narrow the report. This also pins the per-query / per-grid-cell figures,
    which come from the run manifest — data the cost module has no other way to
    know.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [
        _judgment("a", 0.001, run_id="run-A", stage="A"),
        _judgment("b", 0.002, run_id="run-B", stage="B"),
    ])
    meter = CostMeter(tmp_path / "costs")
    report = pricing.build_cost_report(
        log_dir, meter, cap_usd=50.0, run_id="run-A",
        manifest={"query_count": 238, "grid": [[0.9, 0.4], [1.2, 0.75]]},
        rates=_standard_rates())
    assert report["run"]["total_usd"] == pytest.approx(0.001)
    assert report["experiment"]["total_usd"] == pytest.approx(0.003)
    assert report["run"]["per_unit"]["usd_per_query"] == pytest.approx(
        0.001 / 238, rel=1e-4)
    assert report["run"]["per_unit"]["usd_per_grid_cell"] == pytest.approx(
        0.0005)


def test_cost_report_md_states_the_reconciliation_verdict_in_prose(
        tmp_path: Path) -> None:
    """`costs.md` is read by a human deciding whether to trust the figures.

    A bare delta means nothing to a reader; the verdict has to say whether a
    mismatch is the benign crash artifact or an integrity problem, because the
    two demand opposite responses (resume vs. stop and investigate).
    """
    log_dir = tmp_path / "log"
    # Well beyond the +-$0.001 rounding tolerance, so this is a real lag.
    _log_segment(log_dir, [_judgment("a", 0.05)])
    meter = CostMeter(tmp_path / "costs")   # ledger at $0 -> lagging
    report = pricing.build_cost_report(log_dir, meter, cap_usd=50.0,
                                       rates=_standard_rates())
    assert report["reconciliation"]["status"] == "ledger_lagging"
    md = pricing.render_cost_report_md(report)
    assert "LEDGER LAGGING" in md
    assert "self-heal" in md
    assert RATE_TABLE_ID in md


def test_write_cost_artifacts_emits_both_files(tmp_path: Path) -> None:
    """Both `costs.json` and `costs.md` must appear, since both get published.

    PLAN §7.4 commits the pair into `evaluation-results/`; a run that produced
    only the JSON would silently drop the reviewable half of the cost trail.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [_judgment("a", 0.001)])
    report = pricing.build_cost_report(
        log_dir, CostMeter(tmp_path / "costs"), cap_usd=50.0,
        rates=_standard_rates())
    json_path, md_path = pricing.write_cost_artifacts(tmp_path / "out", report)
    assert json.loads(json_path.read_text())["rate_table_id"] == RATE_TABLE_ID
    assert md_path.read_text().startswith("# BM25 tuning — cost report")


def test_manifest_cost_fields_cover_every_plan_7_2_key(tmp_path: Path) -> None:
    """The manifest is what the report is written from without reading code.

    PLAN §7.2 fixes the field list; a missing key means the paper's cost section
    has to be reconstructed by hand from logs. `preflight_estimate_usd` beside
    `actual_usd` is deliberate — their ratio is the estimator's accuracy, itself
    a reportable number.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [_judgment("a", 0.001, run_id="run-A")])
    report = pricing.build_cost_report(
        log_dir, CostMeter(tmp_path / "costs"), cap_usd=50.0, run_id="run-A",
        cache_hits=7, rates=_standard_rates())
    fields = pricing.manifest_cost_fields(
        report, cap_usd=50.0, spent_before_usd=0.0,
        preflight_estimate_usd=0.0012, tripped=False)
    assert set(fields["cost"]) >= {
        "rate_table_id", "tier", "preflight_estimate_usd", "actual_usd",
        "usd_by_stage", "usd_per_judged_pair", "cache_hits",
        "usd_saved_by_cache", "wasted_usd", "input_tokens", "output_tokens"}
    assert set(fields["budget"]) == {
        "cap_usd", "spent_before_usd", "spent_after_usd", "remaining_usd",
        "tripped"}
    assert fields["cost"]["preflight_estimate_usd"] == 0.0012
    assert fields["cost"]["cache_hits"] == 7


def test_pilot_basis_extrapolates_measured_tokens_to_the_whole_pool(
        tmp_path: Path) -> None:
    """The number a human must read before authorizing a multi-hour job.

    PLAN §5.7 requires `--pilot N` to stop and print a *measured* basis, and
    WP7/WP8 require that line pasted into chat before the full run launches. So
    it is returned as data, not only logged: a projection that exists solely in
    a log line cannot be quoted, checked, or diffed against the actual.
    """
    rates = _standard_rates()
    meter = CostMeter(tmp_path)
    usages = [_usage(1_000, 400), _usage(800, 200)]
    for usage in usages:
        meter.add(call_cost(usage, rates), usage, run_id="r", stage="A")
    basis = pricing.pilot_basis(usages, rates, pool_size=10_000, meter=meter,
                               cap_usd=50.0)
    assert basis["mean_input_tokens"] == 900.0
    assert basis["mean_output_tokens"] == 300.0
    assert basis["usd_per_call"] == pytest.approx(rates.call_usd(900, 300))
    assert basis["projected_pool_usd"] == pytest.approx(
        10_000 * rates.call_usd(900, 300), rel=1e-6)
    line = pricing.format_pilot_basis(basis)
    assert "[COST] pilot=2" in line and "proj=$" in line and "cap=$50.00" in line


def test_pricing_imports_no_boto3_or_numpy_in_a_fresh_interpreter() -> None:
    """`pricing.py` must stay stdlib-only, or this whole suite acquires a dep group.

    Enforced in a subprocess because the full suite already imports boto3 for
    `tests/systems/test_aus_agent.py`, so an in-process check would pass or fail
    on test ordering. If a rate ever has to be fetched, it goes in the
    `refresh-prices` subcommand body — the one lazy boto3 import (PLAN §4.1).
    """
    import subprocess
    import sys

    task_root = Path(__file__).resolve().parents[2] / "tasks" / "bm25_tune"
    probe = (
        f"import sys;"
        f"sys.path.insert(0, {str(task_root)!r});"
        f"import bm25tune.pricing;"
        f"bad=[m for m in ('boto3','botocore','numpy','scipy','pyserini','torch')"
        f" if m in sys.modules];"
        f"print(','.join(bad))"
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                          text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", (
        f"{proc.stdout.strip()} imported by pricing.py; the rate table is data "
        "— move any fetch into the refresh-prices subcommand body")


# ---------------------------------------------------------------------------
# CLI wiring (the three WP3b subcommands)
# ---------------------------------------------------------------------------
def test_budget_subcommand_prints_the_state_and_makes_no_api_call(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """PLAN §9's standing rule requires this before every Bedrock launch.

    It must therefore be free and safe: no network (the root `no_network`
    fixture would fail this test if it reached out), no credentials, exit 0 even
    on a completely cold data dir — otherwise agents would learn to skip it.
    """
    from bm25tune.cli import main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", "50.0")
    rates = _standard_rates()
    meter = CostMeter(tmp_path / "costs")
    usage = _usage(900, 300)
    meter.add(call_cost(usage, rates), usage, run_id="r", stage="calib")
    meter.checkpoint()

    with caplog.at_level("INFO"):
        assert main(["budget"]) == 0
    text = caplog.text
    assert "[BUDGET] spent=$0.0002 cap=$50.00 remaining=$49.9998" in text
    assert "basis=measured" in text
    assert RATE_TABLE_ID in text


def test_the_spend_ceiling_has_no_default_and_must_be_exported(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A cap nobody set this run is a cap nobody re-confirmed.

    The user's requirement (2026-07-31) is that the ceiling be *passed in*, not
    inherited: an unattended multi-hour job must be bounded by a live decision,
    and money is the one thing the harness cannot undo after the fact. So
    `budget` — the command PLAN §9 makes mandatory before any launch — refuses
    with exit 1 rather than assuming the approved figure, and the message quotes
    the export so the operator does not have to find it in the plan. Commands
    that cannot spend are unaffected, which is what keeps the refusal from being
    ignored as noise.
    """
    from bm25tune.cli import main
    from bm25tune.config import APPROVED_BUDGET_USD

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BM25_TUNE_BUDGET_USD", raising=False)
    with caplog.at_level("ERROR"):
        assert main(["budget"]) == 1
    assert "BM25_TUNE_BUDGET_USD is not set" in caplog.text
    assert f"export BM25_TUNE_BUDGET_USD={APPROVED_BUDGET_USD}" in caplog.text

    # Nonpositive is refused here too, naming the variable rather than a
    # constructor argument: with cap 0 every check trips at once, which reads in
    # the log exactly like a runaway judge.
    caplog.clear()
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", "0")
    with caplog.at_level("ERROR"):
        assert main(["budget"]) == 1
    assert "must be positive" in caplog.text


def test_cost_report_subcommand_writes_both_artifacts_and_reconciles(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """End-to-end for the subcommand WP9 runs to produce the paper's cost section.

    Also pins that an integrity error is *reported* rather than raised: a report
    that refuses to render is the least useful possible response to "the numbers
    disagree", and the operator needs the figures in order to investigate.
    """
    from bm25tune.cli import main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", "50.0")
    log_dir = tmp_path / "judgments" / "log"
    _log_segment(log_dir, [_judgment("a", 0.001, run_id="run-A")])
    run_dir = tmp_path / "runs" / "run-A"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps(
        {"query_count": 238, "cache": {"hits": 5}}))

    with caplog.at_level("INFO"):
        assert main(["cost-report", "--run-id", "run-A"]) == 0
    assert (run_dir / "costs.json").is_file()
    assert (run_dir / "costs.md").is_file()
    assert "reconciliation:" in caplog.text
    payload = json.loads((run_dir / "costs.json").read_text())
    assert payload["run"]["cache"]["hits"] == 5   # taken from the manifest

    # A ledger ahead of the log: reported (exit 1), not raised.
    doctored = CostMeter(tmp_path / "costs")
    doctored.state.spent_usd = 5.0
    doctored.checkpoint()
    caplog.clear()
    with caplog.at_level("INFO"):
        assert main(["cost-report"]) == 1
    assert "integrity_error" in caplog.text


def test_refresh_prices_refuses_to_overwrite_a_committed_table(
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Published cost figures cite a rate table by id, so it is immutable.

    `refresh-prices` writes a NEW dated file; overwriting today's would
    retroactively re-price an already-published run. The refusal happens
    *before* the boto3 client is built, so this test needs no credentials and
    makes no call — which is also why WP3b's own spend is exactly $0.
    """
    from bm25tune.cli import main

    with caplog.at_level("INFO"):
        assert main(["refresh-prices", "--date", "2026-07-30"]) == 1
    assert "refusing to overwrite" in caplog.text
    assert "already exists" in caplog.text


def test_budget_refusal_maps_to_exit_4_and_a_mid_run_stop_to_exit_5(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exit codes are the contract a launching agent branches on.

    PLAN §5.7 makes 4 ("never started, nothing spent") and 5 ("stopped part-way,
    partial results are scoreable, resume is free") distinct precisely so the
    launcher does not have to parse logs. WP3's `judge-pool` raises these; this
    pins that `main`'s handler already maps them, so the mapping cannot be
    forgotten when that lands.
    """
    from bm25tune import cli

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(tmp_path))
    for exc, expected in ((pricing.BudgetRefused("nope"),
                           cli.EXIT_BUDGET_PREFLIGHT),
                          (pricing.BudgetExceeded("stop"),
                           cli.EXIT_BUDGET_STOP),
                          (pricing.LedgerIntegrityError("bad"),
                           cli.EXIT_ERROR)):
        monkeypatch.setattr(cli, "cmd_budget",
                            lambda args, exc=exc: (_ for _ in ()).throw(exc))
        # Rebuild the parser so the patched callable is the registered one.
        assert cli.main(["budget"]) == expected


def test_call_cost_rounding_keeps_the_ledger_inside_reconcile_tolerance(
        tmp_path: Path) -> None:
    """8-dp rounding must not accumulate past the ±$0.001 reconciliation window.

    Recorded costs are rounded so the log is readable and PLAN §5.3's example
    block reproduces exactly. Over the plan's ~49k calls that rounding must stay
    an order of magnitude below the tolerance — otherwise the integrity alarm
    would eventually fire on a perfectly healthy run, and an alarm that cries
    wolf is worse than none.
    """
    rates = _standard_rates()
    exact = 0.0
    recorded = 0.0
    for index in range(50_000):
        usage = _usage(760 + index % 281, 58 + index % 591)
        exact += rates.call_usd(usage["inputTokens"], usage["outputTokens"])
        recorded += call_cost(usage, rates)["usd"]
    drift = abs(exact - recorded)
    assert drift < pricing.RECONCILE_TOLERANCE_USD / 10, drift
    assert math.isfinite(recorded)


def test_reported_dollar_figures_keep_per_call_resolution(tmp_path: Path) -> None:
    """A 6-dp `budget` block would quantise money coarser than one call costs.

    Every persisted dollar figure is the audit trail behind the report's cost
    analysis, and at this experiment's scale a single call is ~$0.00016 — so
    rounding a total to 6 dp discards a *whole call's* worth of precision and
    makes `spent_usd` disagree with the 8-dp `cost` blocks it is the sum of.
    Reporting must never be lossier than recording: every money field here is
    rounded to `COST_DP`, not to a hand-written literal.
    """
    log_dir = tmp_path / "log"
    _log_segment(log_dir, [_judgment("a", 0.00010197)])
    meter = CostMeter(tmp_path / "costs")
    meter.add(_judgment("a", 0.00010197)["cost"], _usage(900, 300),
              run_id="r1", stage="A")

    report = pricing.build_cost_report(log_dir, meter, cap_usd=50.0,
                                       rates=_standard_rates())
    # The exact 8-dp figure survives; a 6-dp round would give 0.000102.
    assert report["budget"]["spent_usd"] == pytest.approx(0.00010197, abs=1e-10)
    assert report["budget"]["spent_usd"] != pytest.approx(0.000102, abs=1e-12)

    guard = BudgetGuard(meter, 50.0, 16, rates=_standard_rates())
    assert guard.status()["spent_usd"] == pytest.approx(0.00010197, abs=1e-10)
    assert guard.status()["by_stage"]["A"] == pytest.approx(0.00010197,
                                                            abs=1e-10)

    fields = pricing.manifest_cost_fields(
        report, cap_usd=50.0, spent_before_usd=0.0,
        preflight_estimate_usd=0.0002, tripped=False)
    assert fields["budget"]["spent_after_usd"] == pytest.approx(0.00010197,
                                                                abs=1e-10)
