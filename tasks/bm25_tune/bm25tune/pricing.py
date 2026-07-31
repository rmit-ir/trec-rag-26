"""Cost recording and the hard US$200 ceiling (PLAN §5.7).

Two user requirements land in this one module, deliberately: *"this entire
process should not cost more than $200"* and *"ensure that the costs are
recorded and stored — we will need the cost analysis for the scientific
report."* They are one module because **the ceiling is enforced from exactly the
numbers the report is written from**. If they were computed twice, one of the two
would eventually be wrong, and the interesting failure (a mis-scaled rate) would
disable the ceiling *and* misreport the paper at the same time.

Four layers, in dependency order:

1. **`Rates` / `load_rates`** — the rate table is *frozen data*, not a constant
   in code: `prices/bedrock-gpt-oss-20b-aps2-2026-07-30.json` is the verbatim
   AWS Pricing API extract, committed. An unknown `(model, region, tier)`
   raises `UnknownRate`; there is no default and no guess, because a wrong rate
   corrupts both the ceiling and the report (PLAN R12). The loader also asserts
   the file's own `unit` field still reads `"1K tokens"` — the per-token /
   per-1K units slip is a 1000× error, and it is the single most damaging silent
   bug this file can have.
2. **`call_cost`** — the `cost` block of the judgment-log record (PLAN §5.3),
   or `None` when the call never reached the model (`usage is None`).
3. **`CostMeter`** — cumulative, durable, reconcilable spend across the *whole*
   experiment (calibration + Stage A + Stage B + continuity), because the cap is
   experiment-wide, not per-run. State lives in `costs/totals.json`; every
   checkpoint also appends to `costs/ledger.jsonl`. It maintains token counts as
   well as dollars, so every pre-flight after WP0 estimates from **measured**
   means instead of the priors.
4. **`BudgetGuard`** — pre-flight refusal (exit 4) and the per-record continuous
   check (exit 5), whose reserve is `concurrency × max_observed_cost_per_call`
   floored at the measured worst-case prior. It tracks *observed* cost, so a
   prompt-length blow-up trips it within seconds rather than at the end.

**THREAD-SAFETY IS BY CONSTRUCTION, NOT BY LOCKING. `CostMeter.add()`,
`CostMeter.checkpoint()` and `BudgetGuard.check()` are called ONLY from the
single writer thread** (PLAN §5.4: workers hand finished records to a
`queue.Queue`; one dedicated writer thread is the sole consumer). One mutating
thread means no lock and no torn float. If a future change moves `add()` into
the worker callbacks "for speed", the counters silently start losing increments
and the ceiling stops being a ceiling — spend would be *under*-reported, which
is the direction that costs real money. Either keep the single-writer contract
or add a lock in the same commit; do not do the first half.

**ORDER OF OPERATIONS MATTERS (crash semantics).** The judgment log is
authoritative because it is written first, per call. The writer thread must:

    block = call_cost(usage, rates)     # pure
    log.append(record_with(block))      # flush (+ fsync on cadence)
    meter.add(block, usage, run_id=..., stage=...)   # then, and only then
    guard.check()

That ordering is why the ledger can only ever *lag* the log, which is
recoverable (`reconcile()` heals it). The reverse — ledger ahead of log — cannot
arise from a crash and is reported as an integrity error. This module therefore
deliberately does **not** offer a "record and meter in one call" convenience: it
would put the meter first and turn a bounded, self-healing gap into an
unexplainable one.

Pure stdlib, and no `boto3` anywhere — the rate file is data. `refresh-prices`
(in `cli.py`) is the only place boto3 appears, lazily, inside the subcommand
body. That is what makes everything here hermetically testable (PLAN §7.3).
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

from .logging_setup import get_logger

log = get_logger("pricing")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
#: The committed rate table this experiment prices against. Pinned rather than
#: "newest file wins" on purpose: `refresh-prices` writes a NEW dated file, and
#: a run must not silently re-price itself against rates fetched after it
#: started. Adopting a newer table is an explicit act (pass `table_id=`), so a
#: mid-experiment price change is visible in the manifest instead of retroactive.
RATE_TABLE_ID = "bedrock-gpt-oss-20b-aps2-2026-07-30"

#: Where committed rate tables live. Under the package (code, not data) because
#: they are small, must ship with the wheel, and are part of the audit trail.
PRICES_DIR = Path(__file__).resolve().parent / "prices"

#: The AWS Pricing API's own unit string for every entry in the committed file.
#: Asserted on load: if a future table switches to per-token pricing, every
#: figure below would be 1000× off and the ceiling would never trip.
EXPECTED_UNIT = "1K tokens"

PRICING_TIERS = ("standard", "batch", "flex", "priority")

LEDGER_BASENAME = "ledger.jsonl"
TOTALS_BASENAME = "totals.json"
TOTALS_VERSION = 1

#: Recorded `cost` blocks are rounded to 8 decimal places — enough that a single
#: call's cost is exact to a hundredth of a microdollar (PLAN §5.3's example
#: block is reproduced exactly), and the accumulated rounding error over the
#: whole plan's ~49k calls is ~1e-4 US$, far inside the $0.001 reconciliation
#: tolerance.
COST_DP = 8

#: Reconciliation tolerance between the ledger and the judgment log (PLAN §5.7).
RECONCILE_TOLERANCE_USD = 0.001

#: **[measured]** worst-case per-call cost (1040 in / 648 out at standard
#: ap-southeast-2 rates, PLAN §6.2b). Floors `BudgetGuard`'s reserve so a
#: cold meter still reserves something for the in-flight calls.
WORST_CASE_CALL_USD_PRIOR = 0.000275

#: **[measured]** typical token counts (PLAN §5.7 layer 1). Used by `preflight`
#: only while the meter is empty; once WP0 has run, the measured means from
#: `totals.json` replace them and the `[BUDGET]` line says `basis=measured`.
PRIOR_MEAN_INPUT_TOKENS = 900
PRIOR_MEAN_OUTPUT_TOKENS = 300

#: Checkpoint cadence — the same 10-record / 5-second rule as the log's fsync
#: (PLAN §5.3/§5.8), so the ledger can never lag the log by more than one
#: window.
CHECKPOINT_EVERY_RECORDS = 10
CHECKPOINT_EVERY_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class PricingError(RuntimeError):
    """A rate table is missing, malformed, or priced in an unexpected unit."""


class UnknownRate(PricingError):
    """No committed rate for the requested (model, region, tier).

    A separate type because the correct response is specific: fetch the rate
    (`refresh-prices`) or fix the env var — never fall back to a guessed number.
    A guessed rate would silently corrupt the report's cost section *and*
    mis-scale the ceiling (PLAN R12).
    """


class LedgerIntegrityError(PricingError):
    """The cost ledger claims more spend than the judgment log can account for.

    A crash can only leave the ledger *behind* the log (the log is written
    first), so the reverse means a doctored ledger or a lost log segment — an
    integrity problem to investigate, not something to auto-heal.
    """


class BudgetError(RuntimeError):
    """Base for the two budget stops, so a caller can catch either."""


class BudgetRefused(BudgetError):
    """Pre-flight says the stage cannot fit under the cap → CLI exit 4."""


class BudgetExceeded(BudgetError):
    """Mid-run: `spent + reserve >= cap` → drain, then CLI exit 5."""


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rates:
    """US$ per 1 000 tokens for one (model, region, tier), plus its provenance.

    `table_id` travels with the numbers into every judgment record, the manifest
    and `costs.json`, so any published figure can be traced back to the exact
    committed price file it came from.
    """

    input_per_1k: float
    output_per_1k: float
    tier: str
    table_id: str

    def call_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Un-rounded cost of one call. The single place the arithmetic lives."""
        return (input_tokens / 1000.0 * self.input_per_1k
                + output_tokens / 1000.0 * self.output_per_1k)


def rate_table_path(table_id: str = RATE_TABLE_ID,
                    prices_dir: Path | None = None) -> Path:
    """Path of a committed rate table by its id."""
    return (prices_dir or PRICES_DIR) / f"{table_id}.json"


def available_tables(prices_dir: Path | None = None) -> list[str]:
    """Every committed rate-table id, oldest-name first (ids are date-suffixed)."""
    directory = prices_dir or PRICES_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def load_rate_table(table_id: str = RATE_TABLE_ID,
                    prices_dir: Path | None = None) -> dict:
    """Load and lightly validate one committed rate table (raw JSON)."""
    path = rate_table_path(table_id, prices_dir)
    if not path.is_file():
        raise UnknownRate(
            f"no committed rate table {table_id!r} at {path}. Available: "
            f"{available_tables(prices_dir) or '(none)'}. Fetch one with "
            "`python -m bm25tune refresh-prices` — never hardcode a rate.")
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PricingError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(table, dict) or "rates" not in table:
        raise PricingError(f"{path} has no 'rates' object")
    return table


def load_rates(model_id: str, region: str, tier: str = "standard", *,
               table_id: str = RATE_TABLE_ID,
               prices_dir: Path | None = None) -> Rates:
    """Rates for one (model, region, tier), or `UnknownRate`.

    Matching is deliberately strict — exact `model_id` and `region` against the
    table's own fields, exact tier suffix on the `usagetype` key. The bare model
    id is the only one that works on Bedrock anyway (PLAN §1: `us.*`/`au.*`
    profile prefixes raise ValidationException), so "close enough" matching
    would only ever paper over a real mistake.
    """
    tier = (tier or "").strip().lower()
    if tier not in PRICING_TIERS:
        raise UnknownRate(
            f"tier {tier!r} is not one of {'|'.join(PRICING_TIERS)}")
    table = load_rate_table(table_id, prices_dir)

    if table.get("model_id") != model_id:
        raise UnknownRate(
            f"rate table {table_id!r} prices model "
            f"{table.get('model_id')!r}, not {model_id!r}; refusing to guess a "
            "rate (a wrong rate corrupts the cost report and the $ ceiling)")
    if table.get("region") != region:
        raise UnknownRate(
            f"rate table {table_id!r} is for region {table.get('region')!r}, "
            f"not {region!r}; refusing to guess a rate")

    rates = table["rates"]
    entries: dict[str, dict] = {}
    for kind in ("input", "output"):
        suffix = f"-{kind}-tokens-{tier}"
        matches = [k for k in rates if k.endswith(suffix)]
        if len(matches) != 1:
            raise UnknownRate(
                f"rate table {table_id!r} has {len(matches)} entries ending "
                f"{suffix!r} (expected exactly 1) for "
                f"model={model_id} region={region} tier={tier}")
        entries[kind] = rates[matches[0]]

    for kind, entry in entries.items():
        unit = entry.get("unit")
        if unit != EXPECTED_UNIT:
            raise PricingError(
                f"{kind} rate in {table_id!r} is priced per {unit!r}, not "
                f"{EXPECTED_UNIT!r}. Every figure in pricing.py assumes per-1K "
                "tokens; a per-token table would misreport cost by 1000x and "
                "disable the budget ceiling (PLAN R12). Fix the loader "
                "explicitly rather than the assertion.")
        if entry.get("usd_per_unit") in (None, ""):
            raise PricingError(
                f"{kind} rate in {table_id!r} has no usd_per_unit")

    try:
        return Rates(
            input_per_1k=float(entries["input"]["usd_per_unit"]),
            output_per_1k=float(entries["output"]["usd_per_unit"]),
            tier=tier,
            table_id=str(table.get("rate_table_id") or table_id),
        )
    except (TypeError, ValueError) as exc:
        raise PricingError(
            f"non-numeric usd_per_unit in rate table {table_id!r}") from exc


def warn_if_nonstandard_tier(tier: str, logger=None) -> str | None:
    """Warn loudly when accounting uses a tier the Converse path never bills.

    PLAN §4.1: the Converse API always bills at standard, so accounting at
    `batch`/`flex` *under-records* real spend — the direction that quietly costs
    money. Returns the warning line (or None) so a caller can also surface it in
    `costs.md` rather than only in a log nobody re-reads.
    """
    if tier == "standard":
        return None
    line = (f"[COST] tier != standard (tier={tier}) — metered figures will not "
            "match the AWS bill; the Converse path always bills at standard")
    (logger or log).warning("%s", line)
    return line


# ---------------------------------------------------------------------------
# Per-call cost
# ---------------------------------------------------------------------------
def call_cost(usage: dict | None, rates: Rates) -> dict | None:
    """The `cost` block of a judgment-log record (PLAN §5.3), or `None`.

    `None` in ⇒ `None` out: a record whose call never reached the model (a
    throttle before send, a rejected credential) carries `usage: null` and must
    carry `cost: null` too. Anything that *did* reach the model was billed even
    if it returned an unparseable grade or hit `max_tokens`, so this is called
    for failures and retries as well — summing `cost.usd` over the whole log,
    `attempt_error` rows included, is the ground-truth spend.

    Pure: no meter, no I/O. That keeps the writer thread's ordering honest —
    the log line is written before the meter is touched (see the module
    docstring).
    """
    if usage is None:
        return None
    input_tokens = _as_tokens(usage.get("inputTokens"))
    output_tokens = _as_tokens(usage.get("outputTokens"))
    input_usd = round(input_tokens / 1000.0 * rates.input_per_1k, COST_DP)
    output_usd = round(output_tokens / 1000.0 * rates.output_per_1k, COST_DP)
    return {
        "usd": round(input_usd + output_usd, COST_DP),
        "input_usd": input_usd,
        "output_usd": output_usd,
        "tier": rates.tier,
        "rate_table_id": rates.table_id,
    }


def _as_tokens(value: object) -> int:
    """Coerce a `usage` token count, treating junk as 0 rather than crashing.

    A malformed usage block must not take down a multi-hour job; it must
    under-report by one call and be visible in the log. `usage: null` is handled
    a level up (it means "never billed"), so this only sees present-but-odd.
    """
    if value is None:
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        log.warning("[COST] non-numeric token count %r treated as 0", value)
        return 0


# ---------------------------------------------------------------------------
# Meter state
# ---------------------------------------------------------------------------
@dataclass
class MeterState:
    """The durable budget state — `costs/totals.json`'s contents.

    Token counts sit next to the dollars because they are the *pre-flight
    basis*: once WP0 has run, `mean_input_tokens` / `mean_output_tokens` are
    measured facts and every later estimate stops guessing (PLAN §5.7 layer 1).
    """

    spent_usd: float = 0.0
    #: Billed calls (a `usage` block was present). The denominator for means.
    calls: int = 0
    #: Every `add()`, including `usage: null` rows that cost nothing.
    records: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: Largest single-call cost ever observed — `BudgetGuard`'s reserve basis.
    max_call_usd: float = 0.0
    by_stage: dict[str, float] = field(default_factory=dict)
    calls_by_stage: dict[str, int] = field(default_factory=dict)
    by_run: dict[str, float] = field(default_factory=dict)
    checkpoints: int = 0
    heals: int = 0
    updated_utc: str = ""

    # -- derived ------------------------------------------------------------
    @property
    def basis(self) -> str:
        """`"measured"` once any call has been billed, else `"prior"`."""
        return "measured" if self.calls > 0 else "prior"

    @property
    def mean_input_tokens(self) -> float:
        return (self.input_tokens / self.calls if self.calls
                else float(PRIOR_MEAN_INPUT_TOKENS))

    @property
    def mean_output_tokens(self) -> float:
        return (self.output_tokens / self.calls if self.calls
                else float(PRIOR_MEAN_OUTPUT_TOKENS))

    @property
    def mean_call_usd(self) -> float:
        return self.spent_usd / self.calls if self.calls else 0.0

    def to_json(self) -> dict:
        return {
            "version": TOTALS_VERSION,
            "spent_usd": round(self.spent_usd, 10),
            "calls": self.calls,
            "records": self.records,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "max_call_usd": round(self.max_call_usd, 10),
            "mean_input_tokens": round(self.mean_input_tokens, 3),
            "mean_output_tokens": round(self.mean_output_tokens, 3),
            "basis": self.basis,
            "by_stage": {k: round(v, 10) for k, v in sorted(
                self.by_stage.items())},
            "calls_by_stage": dict(sorted(self.calls_by_stage.items())),
            "by_run": {k: round(v, 10) for k, v in sorted(self.by_run.items())},
            "checkpoints": self.checkpoints,
            "heals": self.heals,
            "updated_utc": self.updated_utc,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "MeterState":
        return cls(
            spent_usd=float(payload.get("spent_usd", 0.0)),
            calls=int(payload.get("calls", 0)),
            records=int(payload.get("records", payload.get("calls", 0))),
            input_tokens=int(payload.get("input_tokens", 0)),
            output_tokens=int(payload.get("output_tokens", 0)),
            max_call_usd=float(payload.get("max_call_usd", 0.0)),
            by_stage={str(k): float(v)
                      for k, v in (payload.get("by_stage") or {}).items()},
            calls_by_stage={str(k): int(v) for k, v in (
                payload.get("calls_by_stage") or {}).items()},
            by_run={str(k): float(v)
                    for k, v in (payload.get("by_run") or {}).items()},
            checkpoints=int(payload.get("checkpoints", 0)),
            heals=int(payload.get("heals", 0)),
            updated_utc=str(payload.get("updated_utc", "")),
        )


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write_json(path: Path, payload: dict) -> None:
    """tmp-file + `os.replace` so `totals.json` is never a half-written file.

    The budget state is read on every startup; a truncated `totals.json` after a
    crash would either lose the accounting or refuse to parse mid-run. `replace`
    is atomic within a filesystem, and the fsync makes the *content* durable
    before the rename publishes it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _append_jsonl(path: Path, record: dict) -> None:
    """Append one fsync'd line to an append-only ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_ledger(path: Path) -> list[dict]:
    """Parse `ledger.jsonl`, tolerating one truncated final line.

    A crash mid-append leaves at most a partial last line; refusing to read the
    whole ledger because of it would throw away the accounting we are trying to
    recover. A malformed *interior* line is a real corruption and raises.
    """
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                log.warning("[COST] ignoring truncated final ledger line in %s",
                            path)
                continue
            raise PricingError(
                f"{path}:{index + 1} is malformed JSON (interior line) — the "
                "ledger is corrupt; rebuild it from the judgment log")
    return out


def replay_ledger(path: Path) -> MeterState:
    """Rebuild `MeterState` from the ledger — the crash-recovery path.

    Each checkpoint line carries the *absolute* cumulative state, so the replay
    is "adopt the last complete snapshot" rather than a sum of deltas that a
    single lost line would silently shift. `costs/totals.json` is therefore
    always reconstructible, which is the third level of derivability PLAN §4.2
    asks for (log → ledger → totals).
    """
    state = MeterState()
    for record in read_ledger(path):
        if record.get("kind") not in {"checkpoint", "heal"}:
            continue
        state = MeterState.from_json(record)
    return state


# ---------------------------------------------------------------------------
# CostMeter
# ---------------------------------------------------------------------------
class CostMeter:
    """Cumulative spend across the whole experiment. Durable and reconcilable.

    **Single-writer by contract** — see the module docstring. `add()`,
    `maybe_checkpoint()` and `checkpoint()` are called only from the judge
    loop's one writer thread; `load()`/`reconcile()`/`preflight` run on the main
    thread before any worker exists.
    """

    def __init__(self, costs_dir: Path, state: MeterState | None = None,
                 *, clock=time.monotonic) -> None:
        self.costs_dir = Path(costs_dir)
        self.state = state or MeterState()
        self._clock = clock
        self._since_checkpoint = 0
        self._last_checkpoint_at = clock()
        #: Set on the first `add()` of this process, so a checkpoint line names
        #: the run that produced it even when the meter was loaded cold.
        self._last_run_id = ""
        self._last_stage = ""

    # -- paths --------------------------------------------------------------
    @property
    def ledger_path(self) -> Path:
        return self.costs_dir / LEDGER_BASENAME

    @property
    def totals_path(self) -> Path:
        return self.costs_dir / TOTALS_BASENAME

    # -- construction -------------------------------------------------------
    @classmethod
    def load(cls, costs_dir: Path, *, clock=time.monotonic) -> "CostMeter":
        """`totals.json`, else replay `ledger.jsonl`, else a zeroed meter.

        The fallback chain is the point: the cap spans the whole experiment, so
        losing the budget state would silently reset the ceiling. A corrupt
        `totals.json` is *not* fatal — it is a cache of the ledger, and saying
        so here is what makes the ledger's append-only-ness worth having.
        """
        costs_dir = Path(costs_dir)
        totals = costs_dir / TOTALS_BASENAME
        state: MeterState | None = None
        if totals.is_file():
            try:
                state = MeterState.from_json(
                    json.loads(totals.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError, ValueError):
                log.warning("[COST] %s is unreadable; replaying %s instead",
                            totals, LEDGER_BASENAME)
                state = None
        if state is None:
            state = replay_ledger(costs_dir / LEDGER_BASENAME)
        return cls(costs_dir, state, clock=clock)

    # -- accounting ---------------------------------------------------------
    def add(self, cost: dict | None, usage: dict | None, *,
            run_id: str, stage: str) -> None:
        """Record one completed call. **Writer thread only.**

        Call this *after* the record has been written to the judgment log, so
        the ledger can only lag (recoverable) and never lead (an integrity
        error). `cost=None, usage=None` — a call that never reached the model —
        is counted as a record and costs nothing; it must not crash the meter,
        because the throttle-before-send path is exactly where a crash would be
        least welcome.
        """
        self.state.records += 1
        self._since_checkpoint += 1
        self._last_run_id = run_id
        self._last_stage = stage
        if usage is not None:
            self.state.calls += 1
            self.state.input_tokens += _as_tokens(usage.get("inputTokens"))
            self.state.output_tokens += _as_tokens(usage.get("outputTokens"))
            self.state.calls_by_stage[stage] = (
                self.state.calls_by_stage.get(stage, 0) + 1)
        if cost is not None:
            usd = float(cost.get("usd") or 0.0)
            self.state.spent_usd += usd
            self.state.by_stage[stage] = self.state.by_stage.get(stage, 0.0) + usd
            self.state.by_run[run_id] = self.state.by_run.get(run_id, 0.0) + usd
            self.state.max_call_usd = max(self.state.max_call_usd, usd)
        # Checkpoint on cadence here rather than relying on the caller to
        # remember: the crash-window guarantee is a property of the meter, not
        # of whoever wired it up this month.
        self.maybe_checkpoint()

    def spent_usd(self) -> float:
        """Experiment-wide spend, in US$."""
        return self.state.spent_usd

    def spent_by_stage(self) -> dict[str, float]:
        return dict(self.state.by_stage)

    def spent_by_run(self) -> dict[str, float]:
        return dict(self.state.by_run)

    @property
    def max_call_usd(self) -> float:
        return self.state.max_call_usd

    # -- durability ---------------------------------------------------------
    def maybe_checkpoint(self) -> bool:
        """Checkpoint if 10 records or 5 seconds have passed. Writer thread only."""
        if (self._since_checkpoint >= CHECKPOINT_EVERY_RECORDS
                or (self._since_checkpoint
                    and self._clock() - self._last_checkpoint_at
                    >= CHECKPOINT_EVERY_SECONDS)):
            self.checkpoint()
            return True
        return False

    def checkpoint(self, *, kind: str = "checkpoint",
                   extra: dict | None = None) -> dict:
        """Append a ledger line and atomically rewrite `totals.json`.

        Runs on the writer thread's 10-record/5-second cadence and
        unconditionally in the drain (PLAN §5.8), so ledger and log can never
        drift by more than one cadence window.
        """
        self.state.checkpoints += 1
        self.state.updated_utc = _utc_now()
        payload = self.state.to_json()
        record = dict(payload)
        record["kind"] = kind
        record["ts"] = self.state.updated_utc
        record["run_id"] = self._last_run_id
        record["stage"] = self._last_stage
        if extra:
            record.update(extra)
        _append_jsonl(self.ledger_path, record)
        _atomic_write_json(self.totals_path, payload)
        self._since_checkpoint = 0
        self._last_checkpoint_at = self._clock()
        return record

    # -- reconciliation -----------------------------------------------------
    def reconcile(self, log_dir: Path, *,
                  heal: bool = True) -> tuple[float, float]:
        """Compare the ledger against the judgment log. Startup-only.

        Returns `(ledger_total, log_total)`. The **judgment log is
        authoritative** — it is written first, per call — so a log total ahead
        of the ledger is the ordinary crash artifact: the meter adopts the log
        total and appends a `{"kind": "heal"}` ledger line (`heal=False` inspects
        without mutating, which is what `cost-report` wants).

        The reverse cannot arise from a crash and raises
        `LedgerIntegrityError`: it means a doctored ledger or a lost log
        segment, and silently trusting either would let real spend go
        unaccounted.
        """
        ledger_total = self.spent_usd()
        log_total = judgment_log_total_usd(log_dir)
        delta = log_total - ledger_total
        if delta > RECONCILE_TOLERANCE_USD:
            if heal:
                log.warning(
                    "[COST] ledger lagged the judgment log by $%.6f "
                    "(crash window); adopting the log total $%.6f",
                    delta, log_total)
                self.state.spent_usd = log_total
                self.state.heals += 1
                self.checkpoint(kind="heal", extra={
                    "healed_from_usd": round(ledger_total, 10),
                    "healed_to_usd": round(log_total, 10),
                    "log_dir": str(log_dir),
                })
            else:
                log.warning("[COST] ledger lags the judgment log by $%.6f",
                            delta)
        elif -delta > RECONCILE_TOLERANCE_USD:
            raise LedgerIntegrityError(
                f"cost ledger total ${ledger_total:.6f} exceeds the judgment "
                f"log total ${log_total:.6f} by ${-delta:.6f}. A crash can only "
                "leave the ledger BEHIND the log (the log is written first), so "
                "this means a doctored ledger or a lost/moved log segment. "
                f"Investigate {log_dir} before spending anything else.")
        return ledger_total, log_total

    def reconciliation_report(self, log_dir: Path) -> dict:
        """Non-raising reconciliation summary for `costs.md`/`costs.json`.

        `cost-report` must be able to *print* an integrity problem rather than
        die on it — a report that refuses to render is the least useful possible
        response to "the numbers disagree".
        """
        ledger_total = self.spent_usd()
        log_total = judgment_log_total_usd(log_dir)
        delta = round(ledger_total - log_total, 10)
        if abs(delta) <= RECONCILE_TOLERANCE_USD:
            status = "ok"
        elif delta < 0:
            status = "ledger_lagging"
        else:
            status = "integrity_error"
        return {
            "ledger_total_usd": round(ledger_total, 10),
            "judgment_log_total_usd": round(log_total, 10),
            "delta_usd": delta,
            "tolerance_usd": RECONCILE_TOLERANCE_USD,
            "status": status,
        }


# ---------------------------------------------------------------------------
# Judgment-log scanning (read-only)
# ---------------------------------------------------------------------------
#: `store.py` (WP3) owns writing the judgment log. `pricing.py` only ever
#: *reads* it, and does so with its own tolerant scanner rather than importing
#: `store`: the cost report must work on a log written by an older version of
#: the harness, must survive a truncated tail from a crash, and must stay
#: importable in the hermetic test env with no other module present. Both sides
#: agree on one thing only — the §5.3 line format — which is the narrowest
#: possible coupling.
LOG_SEGMENT_GLOB = "events-*.jsonl"


def iter_log_records(log_dir: Path) -> Iterator[dict]:
    """Yield every record in every log segment, tolerating a truncated tail.

    Crash-safety mirror of `store.JudgmentLog`'s reader (PLAN §5.3): a malformed
    *final* line in a segment is counted and skipped; a malformed interior line
    raises, because that is corruption rather than an interrupted write.
    """
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return
    for segment in sorted(log_dir.glob(LOG_SEGMENT_GLOB)):
        lines = segment.read_text(encoding="utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if index == len(lines) - 1:
                    log.warning("[LOG-TAIL] %s: ignoring truncated final line",
                                segment)
                    continue
                raise PricingError(
                    f"{segment}:{index + 1} is malformed JSON (interior line) "
                    "— the judgment log is the audit record; investigate "
                    "rather than deleting it")


def judgment_log_total_usd(log_dir: Path) -> float:
    """Ground-truth spend: sum `cost.usd` over EVERY record in the log.

    Includes `attempt_error` rows on purpose — a call that returned an empty
    text at `stopReason=max_tokens`, or an unparseable grade, was still billed.
    Excluding them would under-report the bill, which is the error direction
    that costs money.
    """
    total = 0.0
    for record in iter_log_records(log_dir):
        cost = record.get("cost")
        if isinstance(cost, dict):
            total += float(cost.get("usd") or 0.0)
    return total


# ---------------------------------------------------------------------------
# BudgetGuard
# ---------------------------------------------------------------------------
class BudgetGuard:
    """The US$200 ceiling: pre-flight refusal (exit 4) + per-call stop (exit 5).

    The reserve is `concurrency × max_observed_cost_per_call`, floored at the
    **[measured]** worst-case prior — *not* a fixed fraction of the cap. At the
    moment `check()` can trip, at most `concurrency` calls are in flight and
    each can bill at most about the worst call seen so far, so the reserve
    provably covers the overshoot the drain will still record. At concurrency 16
    that is ~$0.005; an earlier draft's "2 % of the cap" was ~900× larger and
    was not tied to what is actually in flight.

    Because the reserve tracks *observed* per-call cost, a prompt-length blow-up
    both raises the reserve and accelerates spend — so it trips within seconds
    instead of at the end (PLAN R11).

    **`check()` takes no arguments and runs on the writer thread, once per
    completed record.** There is no "batch" in the judging loop.
    """

    def __init__(self, meter: CostMeter, cap_usd: float, concurrency: int,
                 *, rates: Rates | None = None) -> None:
        if cap_usd <= 0:
            raise ValueError(f"cap_usd must be positive, got {cap_usd!r}")
        self.meter = meter
        self.cap_usd = float(cap_usd)
        self.concurrency = max(int(concurrency), 1)
        self.rates = rates

    # -- reserve ------------------------------------------------------------
    def worst_call_usd(self) -> float:
        return max(self.meter.max_call_usd, WORST_CASE_CALL_USD_PRIOR)

    def reserve_usd(self) -> float:
        """US$ held back for the calls that are in flight right now."""
        return self.concurrency * self.worst_call_usd()

    def remaining_usd(self) -> float:
        return self.cap_usd - self.meter.spent_usd()

    # -- layer 1: pre-flight ------------------------------------------------
    def preflight(self, est_calls: int, est_in: int | None = None,
                  est_out: int | None = None, *, stage: str = "?") -> dict:
        """Estimate a stage's spend and refuse to start if it cannot fit.

        `est_in`/`est_out` are *mean tokens per call*. Left as `None` they come
        from `costs/totals.json` — so once WP0 has run, every later pre-flight
        uses **measured** means and the `[BUDGET]` line says `basis=measured`
        instead of `basis=prior`. That is the whole reason the meter tracks
        tokens as well as dollars.

        Raises `BudgetRefused` (CLI exit 4) *before* anything is spent, naming
        the shortfall and the env var to raise. Returns the estimate dict, which
        goes into `costs.json` and the manifest's `preflight_estimate_usd` —
        whose ratio to `actual_usd` is itself a reportable number (PLAN §7.2).
        """
        if self.rates is None:
            raise PricingError(
                "BudgetGuard needs rates to run a pre-flight; construct it "
                "with BudgetGuard(meter, cap, concurrency, rates=load_rates(…))")
        state = self.meter.state
        if est_in is None and est_out is None:
            basis = state.basis
            mean_in = state.mean_input_tokens
            mean_out = state.mean_output_tokens
        else:
            basis = "explicit"
            mean_in = float(est_in if est_in is not None
                            else state.mean_input_tokens)
            mean_out = float(est_out if est_out is not None
                             else state.mean_output_tokens)
        est_calls = max(int(est_calls), 0)
        per_call = self.rates.call_usd(mean_in, mean_out)
        est_usd = est_calls * per_call
        spent = self.meter.spent_usd()
        ok = spent + est_usd <= self.cap_usd
        estimate = {
            "stage": stage,
            "est_calls": est_calls,
            "basis": basis,
            "mean_input_tokens": round(mean_in, 2),
            "mean_output_tokens": round(mean_out, 2),
            "est_usd_per_call": round(per_call, 10),
            "est_usd": round(est_usd, COST_DP),
            "spent_usd": round(spent, COST_DP),
            "cap_usd": self.cap_usd,
            "remaining_usd": round(self.cap_usd - spent, COST_DP),
            "reserve_usd": round(self.reserve_usd(), COST_DP),
            "rate_table_id": self.rates.table_id,
            "tier": self.rates.tier,
            "ok": ok,
        }
        estimate["line"] = format_budget_line(estimate)
        (log.info if ok else log.error)("%s", estimate["line"])
        if not ok:
            shortfall = spent + est_usd - self.cap_usd
            raise BudgetRefused(
                f"[BUDGET] stage={stage} REFUSED — estimated ${est_usd:.4f} on "
                f"top of ${spent:.4f} already spent would exceed the "
                f"${self.cap_usd:.2f} cap by ${shortfall:.4f}. Nothing has been "
                "spent. Expected total spend for the whole plan is ~$8-14 "
                "(PLAN §6.2b), so a refusal here is prima facie a BUG "
                "(runaway prompt length, a cache-key miss storm, a retry loop) "
                "— diagnose it and escalate to the user before raising "
                "BM25_TUNE_BUDGET_USD.")
        return estimate

    # -- layer 2: continuous ------------------------------------------------
    def check(self) -> None:
        """Raise `BudgetExceeded` when `spent + reserve >= cap`.

        One float compare, run per completed record on the writer thread —
        computationally free, and placed where every result already flows
        through a single thread. The caller catches this, sets `stop_requested`
        with trigger `budget`, and keeps draining the queue: in-flight calls are
        already billed, so discarding them would waste money *and* lose
        judgments (PLAN §5.7 layer 3).
        """
        spent = self.meter.spent_usd()
        reserve = self.reserve_usd()
        if spent + reserve >= self.cap_usd:
            raise BudgetExceeded(
                f"[BUDGET] spent=${spent:.6f} + reserve=${reserve:.6f} "
                f"(concurrency {self.concurrency} x worst observed call "
                f"${self.worst_call_usd():.8f}) >= cap=${self.cap_usd:.2f}")

    # -- reporting ----------------------------------------------------------
    def status(self) -> dict:
        """Spent / cap / remaining / reserve — what `budget` prints."""
        spent = self.meter.spent_usd()
        state = self.meter.state
        return {
            "cap_usd": self.cap_usd,
            "spent_usd": round(spent, COST_DP),
            "remaining_usd": round(self.cap_usd - spent, COST_DP),
            "reserve_usd": round(self.reserve_usd(), COST_DP),
            "concurrency": self.concurrency,
            "calls": state.calls,
            "records": state.records,
            "max_call_usd": round(state.max_call_usd, 8),
            "mean_call_usd": round(state.mean_call_usd, 8),
            "basis": state.basis,
            "mean_input_tokens": round(state.mean_input_tokens, 1),
            "mean_output_tokens": round(state.mean_output_tokens, 1),
            "by_stage": {k: round(v, COST_DP) for k, v in
                         sorted(state.by_stage.items())},
            "updated_utc": state.updated_utc,
        }


def format_budget_line(estimate: dict) -> str:
    """The `[BUDGET]` pre-flight line (PLAN §5.7 layer 1's exact shape)."""
    return (f"[BUDGET] stage={estimate['stage']} "
            f"est_calls={estimate['est_calls']} basis={estimate['basis']} "
            f"est_usd=${estimate['est_usd']:.4f} "
            f"spent=${estimate['spent_usd']:.4f} "
            f"cap=${estimate['cap_usd']:.2f} "
            f"remaining=${estimate['remaining_usd']:.4f} "
            f"→ {'OK' if estimate['ok'] else 'REFUSED'}")


# ---------------------------------------------------------------------------
# Pilot cost basis (PLAN §5.7 "pilot-then-calibrate")
# ---------------------------------------------------------------------------
def pilot_basis(usages: Sequence[dict | None], rates: Rates, *,
                pool_size: int, meter: CostMeter, cap_usd: float) -> dict:
    """Measured cost basis from a `--pilot N` run, extrapolated to the pool.

    The pilot exists so the *measured* per-call cost recalibrates the projection
    before the multi-hour spend is authorized, and its judgments are cached — so
    it costs nothing extra, being N of the calls the full run would make anyway.
    Returned as data (not just a log line) so WP7/WP8 can paste the exact
    numbers into chat, which is what the plan requires before a launch.
    """
    billed = [u for u in usages if u is not None]
    in_tokens = [_as_tokens(u.get("inputTokens")) for u in billed]
    out_tokens = [_as_tokens(u.get("outputTokens")) for u in billed]
    mean_in = statistics.fmean(in_tokens) if in_tokens else 0.0
    mean_out = statistics.fmean(out_tokens) if out_tokens else 0.0
    per_call = rates.call_usd(mean_in, mean_out)
    spent = meter.spent_usd()
    return {
        "pilot_calls": len(usages),
        "pilot_billed_calls": len(billed),
        "mean_input_tokens": round(mean_in, 1),
        "mean_output_tokens": round(mean_out, 1),
        "usd_per_call": round(per_call, 10),
        "pool_size": pool_size,
        "projected_pool_usd": round(pool_size * per_call, 4),
        "spent_usd": round(spent, COST_DP),
        "cap_usd": round(cap_usd, 2),
        "remaining_after_projection_usd": round(
            cap_usd - spent - max(pool_size - len(usages), 0) * per_call, 4),
        "rate_table_id": rates.table_id,
        "tier": rates.tier,
    }


def format_pilot_basis(basis: dict) -> str:
    """One `[COST]` line summarizing a pilot's measured basis."""
    return (f"[COST] pilot={basis['pilot_calls']} calls "
            f"mean_in={basis['mean_input_tokens']} "
            f"mean_out={basis['mean_output_tokens']} "
            f"usd_per_call=${basis['usd_per_call']:.8f} "
            f"pool={basis['pool_size']} "
            f"proj=${basis['projected_pool_usd']:.4f} "
            f"spent=${basis['spent_usd']:.4f} "
            f"cap=${basis['cap_usd']:.2f} "
            f"remaining_after=${basis['remaining_after_projection_usd']:.4f} "
            f"table={basis['rate_table_id']} tier={basis['tier']}")


# ---------------------------------------------------------------------------
# Cost report
# ---------------------------------------------------------------------------
def _percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile — deterministic, stdlib-only, no interpolation.

    Interpolating (numpy's default) would make the reported p95 depend on a
    convention nobody states in the paper; nearest-rank is "an actual observed
    call", which is what a cost table should quote.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])


def _token_stats(values: Sequence[int]) -> dict:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0,
                "max": 0, "total": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "p95": round(_percentile([float(v) for v in values], 95.0), 2),
        "min": min(values),
        "max": max(values),
        "total": sum(values),
    }


def build_cost_report(log_dir: Path, meter: CostMeter, *,
                      cap_usd: float,
                      run_id: str | None = None,
                      cache_hits: int = 0,
                      rates: Rates | None = None,
                      manifest: dict | None = None) -> dict:
    """Every §5.7 reporting bullet, computed from the judgment log.

    Scoped to one `run_id` when given, plus an always-present experiment-wide
    roll-up — the cap is experiment-wide, so a per-run report alone could never
    answer "how much of the $200 is left".

    Deliberate choices worth knowing when reading the output:

    - **`usd_per_judged_pair`'s denominator is the count of unique `jkey`s**, so
      a pair judged under two prompt versions counts twice and the denominator
      matches what was actually billed (PLAN §5.7).
    - **`usd_saved_by_cache` is an estimate and is labeled one** everywhere it
      appears: the avoided calls' true token counts are unknowable, so it is
      `cache_hits × observed mean cost per call`.
    - **Wasted-spend categories overlap** (a truncation is usually also a parse
      failure), so `total_usd` is the de-duplicated union, not their sum.
    """
    records = list(iter_log_records(log_dir))
    scoped = [r for r in records
              if run_id is None or r.get("run_id") == run_id]

    def _summarize(rows: list[dict]) -> dict:
        by_stage: dict[str, dict] = {}
        by_prompt: dict[str, dict] = {}
        in_tokens: list[int] = []
        out_tokens: list[int] = []
        call_usd: list[float] = []
        total = 0.0
        billed = 0
        jkeys: set[str] = set()
        graded_jkeys: set[str] = set()
        errors: dict[str, int] = {}
        wasted_ids: dict[str, set[int]] = {
            "retries": set(), "parse_failures": set(), "truncations": set()}
        wasted_usd: dict[str, float] = {
            "retries": 0.0, "parse_failures": 0.0, "truncations": 0.0}
        wasted_union: dict[int, float] = {}

        for index, row in enumerate(rows):
            cost = row.get("cost")
            usd = float(cost.get("usd") or 0.0) if isinstance(cost, dict) else 0.0
            usage = row.get("usage")
            stage = str(row.get("stage") or "?")
            pver = str(row.get("prompt_version") or "?")
            total += usd
            if isinstance(usage, dict):
                billed += 1
                in_tokens.append(_as_tokens(usage.get("inputTokens")))
                out_tokens.append(_as_tokens(usage.get("outputTokens")))
                call_usd.append(usd)
            for bucket, key in ((by_stage, stage), (by_prompt, pver)):
                slot = bucket.setdefault(key, {"calls": 0, "billed_calls": 0,
                                               "usd": 0.0, "input_tokens": 0,
                                               "output_tokens": 0})
                slot["calls"] += 1
                slot["usd"] += usd
                if isinstance(usage, dict):
                    slot["billed_calls"] += 1
                    slot["input_tokens"] += _as_tokens(usage.get("inputTokens"))
                    slot["output_tokens"] += _as_tokens(
                        usage.get("outputTokens"))
            jkey = row.get("jkey")
            if jkey:
                jkeys.add(str(jkey))
                if row.get("grade") is not None:
                    graded_jkeys.add(str(jkey))
            err = row.get("error")
            if err:
                errors[str(err)] = errors.get(str(err), 0) + 1
            # Billed-but-wasted spend. Categories overlap; the union is what the
            # report headlines so nothing is double-counted.
            if usd:
                if int(row.get("attempt") or 1) > 1:
                    wasted_ids["retries"].add(index)
                    wasted_usd["retries"] += usd
                if err == "parse_failure" or (row.get("grade") is None
                                              and row.get("kind")
                                              == "attempt_error"):
                    wasted_ids["parse_failures"].add(index)
                    wasted_usd["parse_failures"] += usd
                if row.get("stop_reason") == "max_tokens":
                    wasted_ids["truncations"].add(index)
                    wasted_usd["truncations"] += usd
                for ids in wasted_ids.values():
                    if index in ids:
                        wasted_union[index] = usd
                        break

        for bucket in (by_stage, by_prompt):
            for slot in bucket.values():
                slot["usd"] = round(slot["usd"], 8)

        judged_pairs = len(graded_jkeys) or len(jkeys)
        mean_call = (total / billed) if billed else 0.0
        return {
            "records": len(rows),
            "billed_calls": billed,
            "total_usd": round(total, 8),
            "usd_by_stage": {k: v["usd"] for k, v in sorted(by_stage.items())},
            "by_stage": {k: by_stage[k] for k in sorted(by_stage)},
            "by_prompt_version": {k: by_prompt[k] for k in sorted(by_prompt)},
            "input_tokens": _token_stats(in_tokens),
            "output_tokens": _token_stats(out_tokens),
            "usd_per_call": {
                "mean": round(mean_call, 10),
                "median": round(statistics.median(call_usd), 10)
                if call_usd else 0.0,
                "p95": round(_percentile(call_usd, 95.0), 10)
                if call_usd else 0.0,
                "max": round(max(call_usd), 10) if call_usd else 0.0,
            },
            "unique_jkeys": len(jkeys),
            "judged_pairs": judged_pairs,
            "usd_per_judged_pair": round(total / judged_pairs, 10)
            if judged_pairs else 0.0,
            "usd_per_1000_judgments": round(mean_call * 1000.0, 6),
            "errors": dict(sorted(errors.items())),
            "wasted_usd": {
                **{k: round(v, 8) for k, v in wasted_usd.items()},
                "calls": {k: len(v) for k, v in wasted_ids.items()},
                "total_usd": round(sum(wasted_union.values()), 8),
                "note": ("categories overlap (a truncation is usually also a "
                         "parse failure); total_usd is the de-duplicated union"),
            },
            "cache": {
                "hits": cache_hits,
                "usd_saved_by_cache_estimate": round(cache_hits * mean_call, 8),
                "note": ("ESTIMATE — cache hits x observed mean cost per call; "
                         "the avoided calls' true token counts are unknowable"),
            },
        }

    spent = meter.spent_usd()
    report: dict = {
        "kind": "bm25tune-cost-report",
        "generated_utc": _utc_now(),
        "run_id": run_id,
        "log_dir": str(log_dir),
        "rate_table_id": (rates.table_id if rates else
                          (manifest or {}).get("cost", {}).get(
                              "rate_table_id", RATE_TABLE_ID)),
        "tier": rates.tier if rates else None,
        "budget": {
            "cap_usd": round(cap_usd, 2),
            "spent_usd": round(spent, COST_DP),
            "remaining_usd": round(cap_usd - spent, COST_DP),
            "share_of_cap": round(spent / cap_usd, 10) if cap_usd else None,
        },
        "meter": meter.state.to_json(),
        "experiment": _summarize(records),
        "reconciliation": meter.reconciliation_report(log_dir),
    }
    if run_id is not None:
        report["run"] = _summarize(scoped)
        derived: dict[str, float | None] = {}
        manifest = manifest or {}
        queries = manifest.get("query_count")
        grid = manifest.get("grid")
        run_usd = report["run"]["total_usd"]
        derived["usd_per_query"] = (round(run_usd / queries, 10)
                                    if isinstance(queries, int) and queries
                                    else None)
        derived["usd_per_grid_cell"] = (round(run_usd / len(grid), 10)
                                        if isinstance(grid, (list, tuple))
                                        and grid else None)
        report["run"]["per_unit"] = derived
    if rates is not None:
        warning = warn_if_nonstandard_tier(rates.tier)
        if warning:
            report["warnings"] = [warning]
    return report


def render_cost_report_md(report: dict) -> str:
    """`costs.md` — the human-readable half, written for the paper's cost section.

    Kept next to `build_cost_report` so a new figure cannot land in the JSON and
    be quietly missing from the document a human actually reads; the estimate
    labels and the reconciliation verdict are spelled out in prose here because
    that is where they will be copied from.
    """
    lines: list[str] = []
    budget = report["budget"]
    lines.append("# BM25 tuning — cost report")
    lines.append("")
    lines.append(f"Generated {report['generated_utc']} · rate table "
                 f"`{report['rate_table_id']}`"
                 + (f" · tier `{report['tier']}`" if report.get("tier") else ""))
    if report.get("run_id"):
        lines.append(f"Run: `{report['run_id']}`")
    lines.append("")
    for warning in report.get("warnings", []):
        lines.append(f"> **WARNING** {warning}")
        lines.append("")

    lines.append("## Budget")
    lines.append("")
    lines.append("| field | US$ |")
    lines.append("|---|---|")
    lines.append(f"| cap | {budget['cap_usd']:.2f} |")
    lines.append(f"| spent (whole experiment) | {budget['spent_usd']:.4f} |")
    lines.append(f"| remaining | {budget['remaining_usd']:.4f} |")
    share = budget.get("share_of_cap")
    if share is not None:
        lines.append(f"| share of cap used | {100.0 * share:.3f} % |")
    lines.append("")

    def _section(title: str, block: dict) -> None:
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"- records: **{block['records']}** "
                     f"(billed calls: {block['billed_calls']})")
        lines.append(f"- total: **US$ {block['total_usd']:.6f}**")
        lines.append(f"- US$/call: mean {block['usd_per_call']['mean']:.8f}, "
                     f"median {block['usd_per_call']['median']:.8f}, "
                     f"p95 {block['usd_per_call']['p95']:.8f}, "
                     f"max {block['usd_per_call']['max']:.8f}")
        lines.append(f"- US$ per 1000 judgments: "
                     f"{block['usd_per_1000_judgments']:.4f}")
        lines.append(f"- judged pairs (unique `jkey`, prompt-version "
                     f"qualified): **{block['judged_pairs']}** → "
                     f"US$/judged pair {block['usd_per_judged_pair']:.8f}")
        per_unit = block.get("per_unit") or {}
        if per_unit.get("usd_per_query") is not None:
            lines.append(f"- US$/query: {per_unit['usd_per_query']:.8f}")
        if per_unit.get("usd_per_grid_cell") is not None:
            lines.append(f"- US$/grid cell: {per_unit['usd_per_grid_cell']:.8f}")
        lines.append("")
        lines.append("### Spend by stage")
        lines.append("")
        lines.append("| stage | records | billed calls | US$ |")
        lines.append("|---|---|---|---|")
        for stage, slot in block["by_stage"].items():
            lines.append(f"| {stage} | {slot['calls']} | "
                         f"{slot['billed_calls']} | {slot['usd']:.6f} |")
        lines.append("")
        lines.append("### Spend by prompt version")
        lines.append("")
        lines.append("| prompt_version | records | billed calls | US$ |")
        lines.append("|---|---|---|---|")
        for pver, slot in block["by_prompt_version"].items():
            lines.append(f"| {pver} | {slot['calls']} | "
                         f"{slot['billed_calls']} | {slot['usd']:.6f} |")
        lines.append("")
        lines.append("### Tokens per call")
        lines.append("")
        lines.append("| | n | mean | median | p95 | min | max | total |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for label, key in (("input", "input_tokens"),
                           ("output", "output_tokens")):
            stats = block[key]
            lines.append(f"| {label} | {stats['n']} | {stats['mean']} | "
                         f"{stats['median']} | {stats['p95']} | {stats['min']} "
                         f"| {stats['max']} | {stats['total']} |")
        lines.append("")
        cache = block["cache"]
        lines.append("### Cache payoff (ESTIMATE)")
        lines.append("")
        lines.append(f"- cache hits: **{cache['hits']}**")
        lines.append(f"- US$ saved by the cache: "
                     f"**~{cache['usd_saved_by_cache_estimate']:.6f}** "
                     f"— *{cache['note']}*")
        lines.append("")
        wasted = block["wasted_usd"]
        lines.append("### Billed but wasted")
        lines.append("")
        lines.append("| category | calls | US$ |")
        lines.append("|---|---|---|")
        for key in ("retries", "parse_failures", "truncations"):
            lines.append(f"| {key} | {wasted['calls'][key]} | "
                         f"{wasted[key]:.6f} |")
        lines.append(f"| **union (de-duplicated)** | — | "
                     f"**{wasted['total_usd']:.6f}** |")
        lines.append("")
        lines.append(f"*{wasted['note']}.*")
        lines.append("")
        if block["errors"]:
            lines.append("Errors recorded: "
                         + ", ".join(f"`{k}`={v}" for k, v in
                                     block["errors"].items()))
            lines.append("")

    if report.get("run") is not None:
        _section(f"This run (`{report['run_id']}`)", report["run"])
    _section("Whole experiment", report["experiment"])

    rec = report["reconciliation"]
    lines.append("## Reconciliation (ledger vs judgment log)")
    lines.append("")
    lines.append(f"- ledger total: US$ {rec['ledger_total_usd']:.6f}")
    lines.append(f"- judgment-log total: US$ "
                 f"{rec['judgment_log_total_usd']:.6f}")
    lines.append(f"- delta: US$ {rec['delta_usd']:.6f} "
                 f"(tolerance ±{rec['tolerance_usd']})")
    verdict = {
        "ok": "**OK** — ledger and log agree within tolerance.",
        "ledger_lagging": ("**LEDGER LAGGING** — expected after a crash inside "
                           "a checkpoint window; the judgment log is "
                           "authoritative and `judge-pool` startup self-heals "
                           "the ledger."),
        "integrity_error": ("**INTEGRITY ERROR** — the ledger claims more spend "
                            "than the log can account for. A crash cannot "
                            "produce this (the log is written first): suspect a "
                            "doctored ledger or a lost log segment. "
                            "Investigate before spending anything else."),
    }[rec["status"]]
    lines.append(f"- verdict: {verdict}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Every figure above is priced from the committed rate table "
                 f"`{report['rate_table_id']}` "
                 "(`tasks/bm25_tune/bm25tune/prices/`), which is the verbatim "
                 "AWS Pricing API extract — so the cost analysis is "
                 "reproducible without a live API call.")
    lines.append("")
    return "\n".join(lines)


def write_cost_artifacts(out_dir: Path, report: dict) -> tuple[Path, Path]:
    """Write `costs.json` + `costs.md` into `out_dir`; return both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "costs.json"
    md_path = out_dir / "costs.md"
    _atomic_write_json(json_path, report)
    md_path.write_text(render_cost_report_md(report), encoding="utf-8")
    return json_path, md_path


def manifest_cost_fields(report: dict, *, cap_usd: float,
                         spent_before_usd: float,
                         preflight_estimate_usd: float | None = None,
                         tripped: bool = False) -> dict:
    """The manifest's `cost` and `budget` blocks (PLAN §7.2).

    Built here rather than in whatever module happens to write the manifest, so
    the report and the manifest can never disagree about the same run's spend —
    they are two renderings of one dict. `preflight_estimate_usd` sits next to
    `actual_usd` deliberately: their ratio is the estimator's accuracy, which is
    itself a reportable number and what makes the *next* experiment's budgeting
    trustworthy.
    """
    scope = report.get("run") or report["experiment"]
    spent_after = report["budget"]["spent_usd"]
    return {
        "cost": {
            "rate_table_id": report["rate_table_id"],
            "tier": report.get("tier"),
            "preflight_estimate_usd": preflight_estimate_usd,
            "actual_usd": scope["total_usd"],
            "usd_by_stage": scope["usd_by_stage"],
            "usd_per_judged_pair": scope["usd_per_judged_pair"],
            "judged_pairs": scope["judged_pairs"],
            "cache_hits": scope["cache"]["hits"],
            "usd_saved_by_cache": scope["cache"]["usd_saved_by_cache_estimate"],
            "usd_saved_by_cache_is_estimate": True,
            "wasted_usd": {
                "retries": scope["wasted_usd"]["retries"],
                "parse_failures": scope["wasted_usd"]["parse_failures"],
                "truncations": scope["wasted_usd"]["truncations"],
                "total": scope["wasted_usd"]["total_usd"],
            },
            "input_tokens": scope["input_tokens"]["total"],
            "output_tokens": scope["output_tokens"]["total"],
        },
        "budget": {
            "cap_usd": round(cap_usd, 2),
            "spent_before_usd": round(spent_before_usd, COST_DP),
            "spent_after_usd": spent_after,
            "remaining_usd": round(cap_usd - spent_after, COST_DP),
            "tripped": bool(tripped),
        },
    }
