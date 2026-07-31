"""Logging configuration and the progress heartbeat (PLAN §5.6).

Two jobs, both aimed at a multi-hour `judge-pool` run that a human watches over
`tail -f`:

1. **Greppable, timestamped, dual-sink logging.** One format everywhere —
   `%(asctime)s %(levelname)s %(name)s %(message)s` with UTC ISO-8601
   timestamps — written to the console *and* to the run's `sweep.log`, so the
   file an operator later attaches to a worklog is byte-identical to what they
   watched. Every interesting event carries one of the stable prefixes in
   `LOG_PREFIXES`; those strings are the harness's grep contract and must not
   drift, because the README and the worklog tell readers to search for them.
2. **A heartbeat thread that makes spend visible in real time.** Without it,
   cost is only known at the end — which is exactly when it is too late to
   notice a runaway (PLAN §5.7/R11). `format_heartbeat` is a pure function so
   the projection arithmetic is testable without threads or a clock.

The formatting helpers are pure and the thread is a thin wrapper around them,
deliberately: a shutdown path or a progress line that only exists inside a
thread is the code that rots.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

#: The harness's grep contract (PLAN §5.6). Every operational event is prefixed
#: with one of these; `README.md` documents them as the way to read a run log.
LOG_PREFIXES = (
    "[LOAD]", "[WARMUP]", "[SEARCH]", "[POOL]", "[CACHE]", "[JUDGE]",
    "[THROTTLE]", "[CRED]", "[PARSE-FAIL]", "[PREFIX-MISS]", "[LOG-TAIL]",
    "[NDCG]", "[HEARTBEAT]", "[BUDGET]", "[COST]", "[SIGNAL]", "[SUMMARY]",
    # WP6 calibration (`calibrate`): the driver stage and the gate verdict.
    "[CALIB]", "[GATE]",
)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
HEARTBEAT_INTERVAL_S = 60.0


class _UTCFormatter(logging.Formatter):
    """`logging.Formatter` pinned to UTC with an ISO-8601 `…T…Z` timestamp.

    Runs are launched from whatever shell happens to be around and compared
    against Bedrock/AWS timestamps, which are UTC; a local-time log would make
    that correlation a manual exercise.

    `formatTime` is overridden rather than configured via `default_msec_format`:
    the base implementation only consults that attribute when `datefmt` is None,
    so with an explicit `datefmt` (which we need for the `T` separator) the
    milliseconds and the `Z` are silently dropped — leaving a log that *is* UTC
    but does not say so, which is the failure this class exists to prevent.
    """

    converter = time.gmtime

    def formatTime(self, record: logging.LogRecord,
                   datefmt: str | None = None) -> str:
        stamp = time.strftime(datefmt or DATE_FORMAT,
                              self.converter(record.created))
        return f"{stamp}.{int(record.msecs):03d}Z"


def make_formatter() -> logging.Formatter:
    """The single formatter both sinks share."""
    return _UTCFormatter(LOG_FORMAT, DATE_FORMAT)


def setup_logging(logfile: Path | None = None, *,
                  level: int = logging.INFO) -> logging.Logger:
    """Configure the root logger for one CLI invocation.

    Idempotent: the handlers this function installed are removed and replaced,
    so a re-entrant call (a test, or a subcommand that learns its run dir late
    and re-points the file sink) cannot double every line.

    `logfile`'s parent is created if needed. Returns the `bm25tune` logger, the
    one callers should use.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_bm25tune", False):
            root.removeHandler(handler)
            handler.close()

    formatter = make_formatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._bm25tune = True  # type: ignore[attr-defined]
    root.addHandler(console)

    if logfile is not None:
        logfile = Path(logfile)
        logfile.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(logfile, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._bm25tune = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    root.setLevel(level)
    return logging.getLogger("bm25tune")


def get_logger(name: str = "bm25tune") -> logging.Logger:
    """Child logger under the `bm25tune` namespace."""
    return logging.getLogger(name if name.startswith("bm25tune")
                             else f"bm25tune.{name}")


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
@dataclass
class HeartbeatStats:
    """A snapshot of judge-loop progress, as of one instant.

    Mutated in place by the writer thread (the single mutator, per PLAN §5.7)
    and read by the heartbeat thread. Fields are plain ints/floats, so a torn
    read yields a slightly stale number in a log line — acceptable, and the
    reason no lock is taken on the hot path.

    `spent_usd`/`cap_usd` are here rather than in `pricing.py` because the whole
    point of PLAN §5.6 is that cost is a *heartbeat* field: an operator watching
    `tail -f` sees dollars accrue, not just a call count.
    """

    total: int = 0
    judged: int = 0
    cache_hits: int = 0
    throttles: int = 0
    parse_fails: int = 0
    spent_usd: float = 0.0
    cap_usd: float = 0.0
    elapsed_s: float = 0.0


def format_heartbeat(stats: HeartbeatStats) -> str:
    """Render one `[HEARTBEAT]` line (PLAN §5.6's exact field set).

    Pure, so the projection arithmetic — the number that decides whether an
    operator lets a multi-hour job continue — is pinned by a unit test rather
    than only ever seen in production. Degenerate inputs (nothing judged yet,
    no total known) print `-` instead of dividing by zero, because a heartbeat
    that crashes the thread it runs on takes the run's only progress signal
    with it.
    """
    total = max(stats.total, 0)
    judged = max(stats.judged, 0)
    pct = f"{100.0 * judged / total:.1f}%" if total else "-"
    rate = judged / stats.elapsed_s if stats.elapsed_s > 0 and judged else 0.0
    rate_s = f"{rate:.2f}/s" if rate else "-"
    remaining = max(total - judged, 0)
    eta = f"{remaining / rate / 60.0:.0f}m" if rate and remaining else "-"
    # Projection = observed cost per completed call, extrapolated to the whole
    # pool. Calls served from cache cost nothing, so the denominator is the
    # number actually billed (`judged - cache_hits`), floored at 1.
    billed = max(judged - stats.cache_hits, 1)
    proj = stats.spent_usd / billed * max(total - stats.cache_hits, 0)
    return (f"[HEARTBEAT] judged {judged}/{total} ({pct}) rate={rate_s} "
            f"cache_hits={stats.cache_hits} throttles={stats.throttles} "
            f"parse_fails={stats.parse_fails} "
            f"spent=${stats.spent_usd:.2f} proj=${proj:.2f} "
            f"cap=${stats.cap_usd:.2f} eta={eta}")


class Heartbeat:
    """Daemon thread logging `format_heartbeat(...)` every `interval` seconds.

    Use as a context manager so the thread is always joined — an orphaned
    heartbeat would keep logging after the drain routine (PLAN §5.8) has already
    written the final `[SUMMARY]`, making the tail of a log lie about where the
    run ended.

    The thread waits on an `Event` rather than sleeping, so `stop()` returns
    promptly instead of up to a minute later.
    """

    def __init__(self, stats: HeartbeatStats | Callable[[], HeartbeatStats],
                 *, interval: float = HEARTBEAT_INTERVAL_S,
                 logger: logging.Logger | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._stats = stats
        self._interval = interval
        self._log = logger or get_logger("heartbeat")
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = clock()

    def snapshot(self) -> HeartbeatStats:
        """Current stats with `elapsed_s` filled in from the clock."""
        stats = self._stats() if callable(self._stats) else self._stats
        stats.elapsed_s = self._clock() - self._t0
        return stats

    def emit_once(self) -> str:
        """Log one heartbeat line now and return it (used by the drain path)."""
        line = format_heartbeat(self.snapshot())
        self._log.info(line)
        return line

    def start(self) -> "Heartbeat":
        if self._thread is not None:
            raise RuntimeError("Heartbeat already started")
        self._t0 = self._clock()
        self._thread = threading.Thread(target=self._run, name="bm25tune-hb",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self, *, final: bool = False) -> None:
        """Signal the thread and join it; optionally emit one last line."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=self._interval + 5.0)
        if final:
            self.emit_once()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.emit_once()
            except Exception:  # pragma: no cover - never kill the run
                self._log.exception("[HEARTBEAT] failed to render progress")

    def __enter__(self) -> "Heartbeat":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
