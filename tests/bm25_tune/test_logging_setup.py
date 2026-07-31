"""What the logging layer defends: the operator's only view of a live run.

`judge-pool` runs for hours, spends real money, and is unattended apart from a
`tail -f`. Three things therefore have to hold, and none of them is checked by any
other test:

1. **The `[HEARTBEAT]` projection must be arithmetically right.** It is the number
   an operator uses to decide whether to let a job keep running or kill it (PLAN
   §5.7/R11). A projection that ignores cache hits over-states the remaining cost
   by whatever the hit rate is — on a resumed run that is most of the pool, so the
   line would scream "$180 projected" on a job that will spend $2, and the honest
   response to that is to kill a healthy run.
2. **The heartbeat must never take the run down.** It exists to report on
   long-running work; a division by zero in the first seconds (nothing judged
   yet), or an exception in the reporting thread, must not remove the run's only
   progress signal.
3. **The grep prefixes must not drift.** `README.md` and the worklogs tell readers
   to `grep '\\[JUDGE\\]'`; the strings are an interface, and a rename silently
   breaks every instruction written against them.

`setup_logging` is covered for idempotence because it is called per invocation and
tests call it repeatedly in one process — duplicate handlers would double every
line in `sweep.log`, which is the artifact a worklog later attaches verbatim.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from bm25tune import cli, extract
from bm25tune.logging_setup import (HEARTBEAT_INTERVAL_S, LOG_PREFIXES,
                                    Heartbeat, HeartbeatStats, format_heartbeat,
                                    get_logger, make_formatter, setup_logging)


# ---------------------------------------------------------------------------
# The heartbeat line
# ---------------------------------------------------------------------------
def test_projection_bills_only_the_calls_that_cost_money() -> None:
    """The cost projection must divide by billed calls, not by judged calls.

    This is the whole point of the field. Here 900 of 1000 judged pairs were cache
    hits, so $1.00 bought 100 real calls; the 4000 uncached pairs remaining project
    to $40. Dividing by `judged` instead would report $4 and hide a 10x overrun —
    and the symmetric error on a *resumed* run over-states cost and gets a healthy
    job killed.
    """
    line = format_heartbeat(HeartbeatStats(
        total=5000, judged=1000, cache_hits=900, spent_usd=1.00,
        cap_usd=200.0, elapsed_s=100.0))
    assert "spent=$1.00" in line
    assert "proj=$41.00" in line  # (5000 - 900) uncached x $0.01/call


def test_heartbeat_survives_a_cold_start() -> None:
    """Zero elapsed time, zero judged, and zero total must not raise.

    The first heartbeat can fire before anything has completed — and on the
    heartbeat's own daemon thread, where a `ZeroDivisionError` costs the run its
    only progress signal for the next several hours.
    """
    line = format_heartbeat(HeartbeatStats())
    assert "judged 0/0 (-)" in line
    assert "rate=-" in line
    assert "eta=-" in line
    assert "proj=$0.00" in line


def test_heartbeat_line_carries_every_field_the_plan_names() -> None:
    """All of PLAN §5.6's fields are present, so the line is self-sufficient.

    An operator diagnoses from this one line: a climbing `throttles` means back
    off concurrency, a climbing `parse_fails` means the prompt or parser is wrong
    and the spend is buying nothing. Dropping a field turns a diagnosable run into
    one that needs a code read.
    """
    line = format_heartbeat(HeartbeatStats(
        total=200, judged=50, cache_hits=10, throttles=3, parse_fails=1,
        spent_usd=0.5, cap_usd=200.0, elapsed_s=25.0))
    for field in ("judged", "rate=", "cache_hits=10", "throttles=3",
                  "parse_fails=1", "spent=$", "proj=$", "cap=$", "eta="):
        assert field in line, f"missing {field!r} in {line!r}"
    assert line.startswith("[HEARTBEAT] ")
    assert "\n" not in line, "a multi-line heartbeat breaks line-oriented greps"


def test_eta_uses_the_observed_rate() -> None:
    """ETA must be derived from measured throughput, not assumed.

    50 done in 100 s is 0.5/s, so the remaining 150 take 300 s = 5m. This is the
    number that decides whether a run is left overnight; an ETA computed from a
    hardcoded rate would be confidently wrong exactly when throttling makes it
    matter.
    """
    line = format_heartbeat(HeartbeatStats(total=200, judged=50,
                                          elapsed_s=100.0))
    assert "rate=0.50/s" in line
    assert "eta=5m" in line


def test_completed_work_reports_no_eta_rather_than_zero() -> None:
    """A finished pool prints `eta=-`, not `eta=0m`.

    `0m` reads as "about to finish" — indistinguishable from a stalled run with
    one item left. The distinction matters at exactly the moment someone is
    deciding whether to intervene.
    """
    line = format_heartbeat(HeartbeatStats(total=100, judged=100,
                                          elapsed_s=50.0))
    assert "eta=-" in line
    assert "(100.0%)" in line


# ---------------------------------------------------------------------------
# The heartbeat thread
# ---------------------------------------------------------------------------
def test_heartbeat_thread_emits_and_is_joined_on_exit(
        caplog: pytest.LogCaptureFixture) -> None:
    """The context manager runs the thread and joins it on the way out.

    An orphaned heartbeat keeps logging after the drain routine has written the
    final `[SUMMARY]` (PLAN §5.8), so the tail of `sweep.log` misreports where the
    run ended — and that file is the evidence a worklog cites.
    """
    stats = HeartbeatStats(total=10, judged=5, elapsed_s=1.0)
    before = threading.active_count()
    with caplog.at_level(logging.INFO):
        with Heartbeat(stats, interval=0.01) as hb:
            for _ in range(200):
                if "[HEARTBEAT]" in caplog.text:
                    break
                threading.Event().wait(0.01)
    assert "[HEARTBEAT]" in caplog.text
    assert hb._thread is None
    assert threading.active_count() == before


def test_heartbeat_reads_live_stats_through_a_callable() -> None:
    """Progress must be read at emit time, not captured at construction.

    The judge loop's counters live on the writer thread and are replaced, not
    mutated, in some code paths; binding a stale object would freeze the reported
    progress at zero while the run proceeded normally — the most confusing
    possible failure, since the job looks hung but is fine.
    """
    box = {"stats": HeartbeatStats(total=10, judged=1)}
    hb = Heartbeat(lambda: box["stats"], interval=1000.0, clock=lambda: 0.0)
    assert "judged 1/10" in format_heartbeat(hb.snapshot())
    box["stats"] = HeartbeatStats(total=10, judged=9)
    assert "judged 9/10" in format_heartbeat(hb.snapshot())


def test_stop_final_emits_one_last_line(
        caplog: pytest.LogCaptureFixture) -> None:
    """`stop(final=True)` records the terminal counters.

    The drain path needs the last heartbeat to be the true end state — without it
    the log's final progress line is up to a minute stale, and a resumed run's
    reconciliation starts from the wrong number.
    """
    hb = Heartbeat(HeartbeatStats(total=4, judged=4, spent_usd=2.5),
                   interval=1000.0)
    with caplog.at_level(logging.INFO):
        hb.stop(final=True)
    assert "judged 4/4 (100.0%)" in caplog.text
    assert "spent=$2.50" in caplog.text


def test_starting_twice_is_refused() -> None:
    """A double `start()` must raise rather than leak a second thread.

    Two heartbeats interleave contradictory progress lines from independently
    initialized clocks, so the log shows two different ETAs for one run and
    neither is trustworthy.
    """
    hb = Heartbeat(HeartbeatStats(), interval=1000.0)
    hb.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            hb.start()
    finally:
        hb.stop()


def test_snapshot_measures_elapsed_from_start_not_from_construction() -> None:
    """`start()` resets the clock, so `rate` reflects the working period.

    A `Heartbeat` is built during setup — index open and warm-up take minutes
    (PLAN §5.2) — and if that time counted, the reported rate and every ETA
    derived from it would be depressed for the whole run.
    """
    now = [0.0]
    hb = Heartbeat(HeartbeatStats(total=10, judged=5),
                   interval=1000.0, clock=lambda: now[0])
    now[0] = 500.0          # 500 s of setup before the loop begins
    hb.start()
    try:
        now[0] = 510.0      # 10 s of actual judging
        assert hb.snapshot().elapsed_s == 10.0
    finally:
        hb.stop()


def test_default_interval_is_a_minute() -> None:
    """The 60 s cadence is the plan's, and is a real trade-off.

    Too slow and a runaway spends unnoticed; too fast and hours of log are
    unreadable noise. PLAN §5.6 fixes 60 s, and the README tells operators what to
    expect to see and how often.
    """
    assert HEARTBEAT_INTERVAL_S == 60.0


# ---------------------------------------------------------------------------
# Sinks and the grep contract
# ---------------------------------------------------------------------------
def test_setup_logging_is_idempotent(tmp_path: Path,
                                     caplog: pytest.LogCaptureFixture) -> None:
    """Repeated calls must not duplicate handlers.

    `main()` calls this once per invocation, and a subcommand may re-point the
    file sink after it learns its run dir. Accumulated handlers double every line
    in `sweep.log`, which corrupts both the operator's reading and any later
    line-counting over the artifact.
    """
    logfile = tmp_path / "a.log"
    for _ in range(3):
        setup_logging(logfile)
    get_logger("t").info("[JUDGE] once")
    logging.shutdown()
    assert logfile.read_text().count("[JUDGE] once") == 1


def test_both_sinks_receive_the_same_text(tmp_path: Path) -> None:
    """Console and file share one formatter, so the artifact matches what was watched.

    PLAN §5.6 requires the attached `sweep.log` to be the stream the operator saw.
    Divergent formatters would make a worklog's quoted line unfindable in the file
    it supposedly came from.
    """
    logfile = tmp_path / "b.log"
    setup_logging(logfile)
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "_bm25tune", False)]
    assert len(ours) == 2
    formats = {h.formatter._fmt for h in ours}  # type: ignore[union-attr]
    assert len(formats) == 1


def test_timestamps_are_utc_and_iso8601(tmp_path: Path) -> None:
    """Log times must be UTC with a `Z`, for correlation with AWS records.

    Cost reconciliation compares the log against Bedrock/Cost Explorer
    timestamps, which are UTC. A local-time log makes that a manual timezone
    exercise on every dispute about what a run spent.
    """
    formatter = make_formatter()
    record = logging.LogRecord("bm25tune", logging.INFO, __file__, 1,
                              "[COST] x", None, None)
    stamped = formatter.format(record)
    assert "T" in stamped.split()[0]
    assert stamped.split()[0].endswith("Z")
    assert formatter.converter is __import__("time").gmtime


def test_log_prefixes_are_the_documented_grep_contract() -> None:
    """The 19 prefixes are fixed strings the README tells operators to grep.

    Renaming one breaks written instructions and any saved grep/alert over a run
    log, with no compile-time signal. PLAN §5.6 enumerates them; this pins the set
    and its uniqueness. (`[CALIB]`/`[GATE]` were added with WP6's `calibrate`.)
    """
    assert len(LOG_PREFIXES) == len(set(LOG_PREFIXES)) == 19
    for prefix in LOG_PREFIXES:
        assert prefix.startswith("[") and prefix.endswith("]")
        assert prefix == prefix.upper()
    assert {"[JUDGE]", "[BUDGET]", "[COST]", "[HEARTBEAT]", "[SIGNAL]",
            "[SUMMARY]"} <= set(LOG_PREFIXES)


def test_live_wp1_code_only_logs_documented_prefixes() -> None:
    """Every prefix emitted by WP1's code is in `LOG_PREFIXES`.

    The contract is only worth having if the code obeys it. Checked by scanning
    the sources rather than by review, since the drift here is a new `[STAGE]` or
    `[INFO]` added in passing by whoever writes the next work package.
    """
    import re

    pattern = re.compile(r'"\s*(\[[A-Z][A-Z-]*\])')
    for module in (cli, extract):
        source = Path(module.__file__).read_text()
        for found in pattern.findall(source):
            assert found in LOG_PREFIXES, (
                f"{Path(module.__file__).name} logs {found}, which is not in "
                "LOG_PREFIXES — add it there (and to the README) or reuse an "
                "existing prefix")


def test_get_logger_keeps_everything_under_one_namespace() -> None:
    """All loggers live under `bm25tune.`, so one level change affects the run.

    `--verbose` sets a level on the package logger; a module that named itself
    outside the namespace would ignore it, and would also escape any handler the
    harness installs.
    """
    assert get_logger("judge").name == "bm25tune.judge"
    assert get_logger("bm25tune.judge").name == "bm25tune.judge"
    assert get_logger().name == "bm25tune"
