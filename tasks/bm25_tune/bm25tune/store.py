"""The judgment LOG (permanent audit record) and the judgment CACHE (PLAN §5.3).

Two structures with deliberately different guarantees, and the distinction is the
whole point of this module:

- The **log** (`JudgmentLog`) is append-only, per-process, and the **sole source
  of truth**. Every Bedrock attempt lands here — successes, throttles, parse
  failures, and the retry that fixed them — each with its `usage` and `cost`
  block, because *a call that returned garbage was still billed*. Summing
  `cost.usd` over the log (including `kind: "attempt_error"` rows) is the
  ground-truth spend the cost ledger reconciles against (PLAN §5.7). Records are
  never rewritten and never deleted; `--fresh` is structurally forbidden from
  touching this directory (`assert_fresh_allowed`).
- The **cache** (`JudgmentCache`) is a lookup structure that is *always*
  rebuildable from the log. Its on-disk snapshot (`cache/qrels-<pv>.jsonl`) is a
  pure accelerator: lose it, corrupt it, delete it, and `rebuild-cache` restores
  it from the log in seconds.

Three invariants this file exists to defend:

1. **The cache key is `(prompt_version, topic_id, chunk_id)` and nothing else.**
   `jkey()` is the only way a key is built. `run_id`/`stage` are *billing
   metadata* and are deliberately not key components — the entire reuse economy
   of PLAN §6.2 rests on a Stage-A judgment satisfying a Stage-B lookup. The dual
   invariant is just as load-bearing: a `umbrela-v1` grade must never satisfy a
   `facet-v1` lookup, or WP0's four-variant calibration silently poisons the
   sweep with labels made under a different rubric. Both are pinned in
   `tests/bm25_tune/test_store.py`.
2. **Crash safety in bounded time.** `flush()` per line plus `os.fsync()` every
   10 lines *or* every 5 seconds, whichever comes first (PLAN §5.8) — a pure
   line-count cadence leaves minutes of already-paid-for work exposed whenever
   the call rate is low. A crash therefore loses at most one truncated final
   line, which the reader tolerates and counts (`[LOG-TAIL]`); a malformed
   *interior* line is a hard error, because that is corruption rather than an
   interrupted write.
3. **No shared handles, no locks.** One segment file per writer process
   (`events-<UTCts>-<host>-<pid>.jsonl`), so concurrent writers are safe by
   construction rather than by locking.
"""
from __future__ import annotations

import json
import os
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .logging_setup import get_logger

log = get_logger("store")

# -- log segments ------------------------------------------------------------
SEGMENT_PREFIX = "events-"
SEGMENT_SUFFIX = ".jsonl"
#: PLAN §5.8's cadence. Both branches, whichever fires first.
FSYNC_EVERY_LINES = 10
FSYNC_EVERY_SECONDS = 5.0

# -- record kinds ------------------------------------------------------------
KIND_JUDGMENT = "judgment"
KIND_ATTEMPT_ERROR = "attempt_error"

# -- cache -------------------------------------------------------------------
KEY_SEP = "::"
CACHE_META_KIND = "cache_meta"
CACHE_BASENAME = "qrels-{prompt_version}.jsonl"


class LogCorruption(RuntimeError):
    """A log segment has a malformed line that is not an interrupted tail write.

    Fatal on purpose: the log is the source of truth for both the qrels and the
    money, so silently skipping a line we cannot parse would under-count spend
    and drop judgments we already paid for.
    """


class ProtectedPathError(RuntimeError):
    """`--fresh`/`--force` was pointed at an append-only audit artifact."""


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
def jkey(prompt_version: str, topic_id: str, chunk_id: str) -> str:
    """The judgment cache key: `"<prompt_version>::<topic_id>::<chunk_id>"`.

    **The only way keys are made** (PLAN §5.3). Centralized so the two facts that
    matter can be enforced in one place: `prompt_version` is always present (no
    cross-rubric poisoning), and `run_id`/`stage` never are (a Stage-A judgment
    is a Stage-B cache hit).

    Components are rejected if empty or if they contain the `::` separator —
    otherwise `("a::b", "c", "d")` and `("a", "b::c", "d")` would collide and one
    topic's grades would answer another's lookups.
    """
    parts = {"prompt_version": prompt_version, "topic_id": topic_id,
             "chunk_id": chunk_id}
    for name, value in parts.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"jkey {name} must be a non-empty string, "
                             f"got {value!r}")
        if KEY_SEP in value:
            raise ValueError(
                f"jkey {name}={value!r} contains {KEY_SEP!r}, which would make "
                "the key ambiguous (two different triples could produce the "
                "same string)")
    return KEY_SEP.join((prompt_version, topic_id, chunk_id))


def split_jkey(key: str) -> tuple[str, str, str]:
    """Inverse of `jkey`. Raises `ValueError` on anything not a 3-part key."""
    parts = key.split(KEY_SEP)
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"not a jkey: {key!r}")
    return parts[0], parts[1], parts[2]


def cache_snapshot_path(cache_dir: Path, prompt_version: str) -> Path:
    """`cache/qrels-<prompt_version>.jsonl` (PLAN §4.2)."""
    return Path(cache_dir) / CACHE_BASENAME.format(
        prompt_version=prompt_version)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    """`2026-07-30T12:00:00.123Z` — the record `ts` format (PLAN §5.3)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def utc_stamp() -> str:
    """`20260730T120000Z` — used in segment and `.superseded-` names."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _host_tag() -> str:
    """Short, filename-safe host tag. `platform.node()`, not a socket call."""
    node = (platform.node() or "unknown").split(".")[0]
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in node)
    return safe or "unknown"


def segment_name(*, stamp: str | None = None, host: str | None = None,
                 pid: int | None = None) -> str:
    """`events-<UTCts>-<host>-<pid>.jsonl` (PLAN §5.3).

    Per-*process* naming is what removes the need for a lock: two writers can
    never share a handle, so "safe under concurrent writers" is a property of the
    filenames rather than of correct locking discipline.
    """
    return (f"{SEGMENT_PREFIX}{stamp or utc_stamp()}-"
            f"{host or _host_tag()}-{pid if pid is not None else os.getpid()}"
            f"{SEGMENT_SUFFIX}")


def iter_segments(log_dir: Path) -> list[Path]:
    """Log segments in replay order (lexicographic == chronological by name).

    The name starts with a UTC stamp, so sorting by name orders by writer start
    time; the trailing pid breaks ties between processes that started in the same
    second. That ordering is the tie-break behind "latest successful grade wins"
    when two concurrent writers judged the same pair.
    """
    directory = Path(log_dir)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir()
                  if p.name.startswith(SEGMENT_PREFIX)
                  and p.name.endswith(SEGMENT_SUFFIX) and p.is_file())


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------
#: Field order of a log line. Fixed so a `git diff`/`head` of a segment is
#: readable and so two writers produce byte-comparable lines.
RECORD_FIELDS = (
    "kind", "jkey", "prompt_version", "topic_id", "chunk_id", "parent_docid",
    "narrative_sha256", "passage_text", "passage_sha256", "prompt_sha256",
    "raw_text", "raw_reasoning", "grade", "facet", "model_id", "region",
    "stop_reason", "usage", "cost", "run_id", "stage", "latency_ms", "attempt",
    "error", "ts",
)


def make_record(*, prompt_version: str, topic_id: str, chunk_id: str,
                parent_docid: str, narrative_sha256: str, passage_text: str,
                passage_sha256: str, prompt_sha256: str, model_id: str,
                region: str, run_id: str, stage: str, attempt: int,
                grade: int | None = None, facet: str | None = None,
                raw_text: str = "", raw_reasoning: str = "",
                stop_reason: str = "", usage: dict | None = None,
                cost: dict | None = None, latency_ms: int = 0,
                error: str | None = None,
                ts: str | None = None) -> dict:
    """Build one PLAN §5.3 log record.

    `kind` is derived, never passed: a record is a `judgment` exactly when it
    carries a grade and no error, and an `attempt_error` otherwise. Deriving it
    means a caller cannot log a "judgment" whose grade is null (which would let a
    parse failure enter the qrels) or an "attempt_error" that actually succeeded
    (which would hide a paid-for grade from the cache).

    `cost` is recorded on **every** record including failures, because the call
    was billed regardless (PLAN §5.3). Only attempts that never reached the model
    carry `usage: null, cost: null`.
    """
    ok = grade is not None and error is None
    record = {
        "kind": KIND_JUDGMENT if ok else KIND_ATTEMPT_ERROR,
        "jkey": jkey(prompt_version, topic_id, chunk_id),
        "prompt_version": prompt_version,
        "topic_id": topic_id,
        "chunk_id": chunk_id,
        "parent_docid": parent_docid,
        "narrative_sha256": narrative_sha256,
        "passage_text": passage_text,
        "passage_sha256": passage_sha256,
        "prompt_sha256": prompt_sha256,
        "raw_text": raw_text,
        "raw_reasoning": raw_reasoning,
        "grade": grade,
        "facet": facet,
        "model_id": model_id,
        "region": region,
        "stop_reason": stop_reason,
        "usage": usage,
        "cost": cost,
        "run_id": run_id,
        "stage": stage,
        "latency_ms": int(latency_ms),
        "attempt": int(attempt),
        "error": error,
        "ts": ts or utc_now_iso(),
    }
    return {name: record[name] for name in RECORD_FIELDS}


def is_success(record: dict) -> bool:
    """True for a record that carries a usable grade.

    The single definition of "this pair is done", used by the cache, the resume
    path, and the qrel writer, so those three can never disagree about whether a
    pair still needs (re-)judging — i.e. whether we are about to pay for it
    again.
    """
    return (record.get("kind") == KIND_JUDGMENT
            and record.get("error") is None
            and isinstance(record.get("grade"), int)
            and not isinstance(record.get("grade"), bool))


# ---------------------------------------------------------------------------
# Append-only log
# ---------------------------------------------------------------------------
class JudgmentLog:
    """One append-only segment, owned exclusively by this process.

    Written by the **single writer thread** of the judge driver (PLAN §5.4), so
    no locking: one mutator, one handle, one file. `append()` flushes every line
    so a crash cannot lose a line to Python-level buffering, and fsyncs on
    PLAN §5.8's 10-line/5-second cadence so a *machine* crash cannot lose more
    than a bounded amount of already-billed work.

    Use as a context manager, or call `close()` from the drain routine — either
    way the final fsync is unconditional.
    """

    def __init__(self, log_dir: Path, *,
                 fsync_every_lines: int = FSYNC_EVERY_LINES,
                 fsync_every_seconds: float = FSYNC_EVERY_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 name: str | None = None) -> None:
        self.log_dir = Path(log_dir)
        self.name = name or segment_name()
        self.path = self.log_dir / self.name
        self.fsync_every_lines = max(1, int(fsync_every_lines))
        self.fsync_every_seconds = float(fsync_every_seconds)
        self._clock = clock
        self._handle = None
        self._since_fsync = 0
        self._last_fsync = clock()
        self.lines_written = 0
        self.fsyncs = 0

    # -- lifecycle ----------------------------------------------------------
    def open(self) -> "JudgmentLog":
        """Create the segment (mode `"a"`) and its directory. Idempotent."""
        if self._handle is None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
            self._last_fsync = self._clock()
        return self

    def close(self) -> None:
        """Flush, fsync unconditionally, close. Safe to call twice."""
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        try:
            handle.flush()
            os.fsync(handle.fileno())
            self.fsyncs += 1
        finally:
            handle.close()
        self._since_fsync = 0

    def __enter__(self) -> "JudgmentLog":
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing ------------------------------------------------------------
    def append(self, record: dict) -> None:
        """Append one record as a single line, flush, and fsync if due.

        One `write` of one line: a partial line can only ever be the *last* line
        of the file, which is exactly the failure mode `read_segment` tolerates.
        """
        self.open()
        assert self._handle is not None
        line = json.dumps(record, ensure_ascii=False) + "\n"
        self._handle.write(line)
        self._handle.flush()
        self.lines_written += 1
        self._since_fsync += 1
        if self._since_fsync >= self.fsync_every_lines:
            self.fsync()
        else:
            self.maybe_fsync()

    def maybe_fsync(self) -> None:
        """Fsync if the 5-second branch of the cadence is due.

        Called by the writer thread when its queue read times out — which is why
        the time-based branch is free: the thread is already awake. Without it, a
        slow stretch (a few calls per minute) would leave minutes of paid-for
        judgments unsynced (PLAN §5.8).
        """
        if self._handle is None or self._since_fsync == 0:
            return
        if self._clock() - self._last_fsync >= self.fsync_every_seconds:
            self.fsync()

    def fsync(self) -> None:
        """Force the OS to persist what has been written."""
        if self._handle is None:
            return
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.fsyncs += 1
        self._since_fsync = 0
        self._last_fsync = self._clock()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
@dataclass
class SegmentRead:
    """One segment's parsed contents plus how far it was safely consumed.

    `lines_consumed` counts physical lines up to and including the last
    successfully parsed record — a truncated tail is deliberately *not* counted,
    so a later incremental replay re-reads (and re-tolerates) it rather than
    skipping past a line it never actually understood.
    """

    path: Path
    records: list[dict] = field(default_factory=list)
    lines_consumed: int = 0
    truncated_tail: bool = False


def iter_segment_records(path: Path, *, skip_lines: int = 0
                         ) -> Iterator[tuple[int, dict]]:
    """Stream `(physical_line_number, record)` from one segment.

    Streaming rather than returning a list because a segment embeds every
    passage's full text (PLAN §5.3 estimates 50–150 MB per run) — a cache rebuild
    must not need the log in memory.

    Tolerates **exactly one** truncated final line (an interrupted write, logged
    `[LOG-TAIL]`); a malformed interior line raises `LogCorruption` naming the
    file and line number.
    """
    path = Path(path)
    pending: tuple[int, str] | None = None
    with path.open(encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            if lineno <= skip_lines:
                continue
            line = raw.strip()
            if not line:
                continue
            if pending is not None:
                # A line we could not parse turned out to have a successor, so
                # it was not an interrupted tail write — it is corruption.
                bad_lineno, bad_line = pending
                raise LogCorruption(
                    f"{path}:{bad_lineno}: malformed interior line "
                    f"({bad_line[:120]!r}). The judgment log is the source of "
                    "truth for both the qrels and the spend, so this is not "
                    "skippable — inspect the segment.")
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                pending = (lineno, line)
                continue
            if not isinstance(record, dict):
                pending = (lineno, line)
                continue
            yield lineno, record
    if pending is not None:
        log.warning("[LOG-TAIL] %s:%d truncated final line tolerated (an "
                    "interrupted write; the record it describes will be "
                    "re-judged)", path, pending[0])


def read_segment(path: Path, *, skip_lines: int = 0) -> SegmentRead:
    """Eager `iter_segment_records` for tests and small segments.

    `truncated_tail` is derived by asking whether any non-blank content survives
    *past* the last record we parsed, rather than by counting lines — a record
    may not span more than one line today, but deriving the flag from "is there
    unconsumed content" keeps it honest if that ever changes.
    """
    out = SegmentRead(path=Path(path), lines_consumed=skip_lines)
    for lineno, record in iter_segment_records(path, skip_lines=skip_lines):
        out.records.append(record)
        out.lines_consumed = lineno
    out.truncated_tail = _has_content_after(Path(path), out.lines_consumed)
    return out


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
@dataclass
class CacheStats:
    """What a cache load did — reported in the `[CACHE]` log line.

    `snapshot_used` distinguishes the fast path from a full rescan, which matters
    operationally: a run that unexpectedly rescans is either a fresh clone or a
    corrupt snapshot, and the difference is minutes of startup on a 100k-line
    log.
    """

    segments: int = 0
    records: int = 0
    successes: int = 0
    updates: int = 0
    superseded: int = 0
    failures: int = 0
    truncated_tails: int = 0
    snapshot_used: bool = False
    snapshot_entries: int = 0


class JudgmentCache:
    """`jkey -> grade`, rebuilt from the log; the snapshot is only a cache.

    Semantics, each load-bearing somewhere:

    - **Latest successful grade wins.** Records are compared on their `ts`, with
      segment/line order as the tie-break, and only successes update an entry —
      so a re-judge that throttles or fails to parse can never *erase* a grade we
      already paid for.
    - **`prompt_version` isolation.** With `prompt_version` set, records under
      any other version are ignored outright. WP0 judges the same 280 pairs under
      four rubrics; without this, calibration labels would answer sweep lookups
      and the experiment would be scored against a label set that never existed.
    - **`run_id`/`stage` blindness.** They are not consulted at all, which is
      what makes a Stage-A judgment a Stage-B cache hit (PLAN §6.2's reuse
      economy).
    """

    def __init__(self, prompt_version: str | None = None) -> None:
        self.prompt_version = prompt_version
        self.grades: dict[str, int] = {}
        self._ts: dict[str, str] = {}
        #: jkeys whose most recent record is a failure and which have no
        #: successful record — i.e. pairs that were billed but produced no grade.
        self.failed: dict[str, str] = {}
        #: Physical lines already folded in, per segment name. The snapshot's
        #: high-water mark; see `load`.
        self.segment_lines: dict[str, int] = {}
        self.stats = CacheStats()

    # -- lookups ------------------------------------------------------------
    def get(self, key: str) -> int | None:
        """Grade for a `jkey`, or `None`. Never raises on an unknown key."""
        return self.grades.get(key)

    def get_grade(self, prompt_version: str, topic_id: str,
                  chunk_id: str) -> int | None:
        """`get(jkey(...))` — the call site that cannot mis-order the triple."""
        return self.grades.get(jkey(prompt_version, topic_id, chunk_id))

    def __contains__(self, key: object) -> bool:
        return key in self.grades

    def __len__(self) -> int:
        return len(self.grades)

    # -- ingestion ----------------------------------------------------------
    def ingest_record(self, record: dict) -> bool:
        """Fold one log record in; True if it changed a grade.

        Also called by the judge driver's writer thread for records it has just
        appended, so a pair that appears twice in one run's pool is a cache hit
        the second time rather than a second billed call.
        """
        self.stats.records += 1
        version = record.get("prompt_version")
        if self.prompt_version is not None and version != self.prompt_version:
            return False
        key = record.get("jkey")
        if not isinstance(key, str) or not key:
            return False
        if not is_success(record):
            self.stats.failures += 1
            if key not in self.grades:
                self.failed[key] = str(record.get("ts") or "")
            return False
        self.stats.successes += 1
        ts = str(record.get("ts") or "")
        previous = self._ts.get(key)
        if previous is not None and ts < previous:
            # An out-of-order record from a concurrent writer: keep the newer
            # grade. `>=` on equal timestamps means later segments win, which is
            # the documented tie-break.
            self.stats.superseded += 1
            return False
        if key in self.grades:
            self.stats.superseded += 1
        self.grades[key] = int(record["grade"])
        self._ts[key] = ts
        self.failed.pop(key, None)
        self.stats.updates += 1
        return True

    def note_appended(self, segment_name_: str, lines: int = 1) -> None:
        """Record that `lines` more lines exist in `segment_name_`.

        Keeps the snapshot's high-water mark honest for the segment *this*
        process is writing, so the next startup replays only what it has not
        already folded in.
        """
        self.segment_lines[segment_name_] = (
            self.segment_lines.get(segment_name_, 0) + lines)

    # -- loading ------------------------------------------------------------
    @classmethod
    def load(cls, log_dir: Path, *, prompt_version: str | None = None,
             snapshot_path: Path | None = None) -> "JudgmentCache":
        """Load from the snapshot (if usable) and replay only what is newer.

        **The log is the sole source of truth**: a missing, unreadable, or
        wrong-version snapshot costs a full rescan and nothing else.

        Deviation from PLAN §5.3's wording, deliberately: the plan says "replay
        only segments *newer than the snapshot's recorded high-water timestamp*".
        A timestamp on the segment *name* is the writer's **start** time, so a
        long-lived segment that was still being appended when the snapshot was
        taken would be skipped entirely on the next load — silently dropping
        every judgment it accumulated afterwards, and re-billing all of them. So
        the high-water mark is recorded **per segment, as a physical line
        count**, which is strictly more conservative (it can only cause re-read,
        never skip) and subsumes the timestamp rule. The snapshot still records
        `high_water_utc` for humans.
        """
        cache = cls(prompt_version=prompt_version)
        if snapshot_path is not None:
            cache._seed_from_snapshot(Path(snapshot_path))
        for segment in iter_segments(log_dir):
            skip = cache.segment_lines.get(segment.name, 0)
            cache.stats.segments += 1
            last_line = skip
            for lineno, record in iter_segment_records(segment,
                                                       skip_lines=skip):
                cache.ingest_record(record)
                last_line = lineno
            cache.segment_lines[segment.name] = last_line
            # A tolerated truncated tail shows up as unparsed physical content
            # past `last_line`; count it so `[CACHE]`/`[LOG-TAIL]` agree.
            if _has_content_after(segment, last_line):
                cache.stats.truncated_tails += 1
        return cache

    def _seed_from_snapshot(self, path: Path) -> None:
        """Populate from a snapshot, ignoring it on any doubt.

        Any problem — missing file, unparsable line, a meta line for a different
        `prompt_version` — resets to empty and falls back to a full log rescan.
        Refusing a suspect snapshot is free (seconds); trusting one is how a
        stale or mis-versioned label set enters the experiment.
        """
        if not path.is_file():
            return
        grades: dict[str, int] = {}
        timestamps: dict[str, str] = {}
        segments: dict[str, int] = {}
        try:
            with path.open(encoding="utf-8") as handle:
                meta = json.loads(handle.readline() or "{}")
                if meta.get("kind") != CACHE_META_KIND:
                    raise ValueError("missing cache_meta header")
                if (self.prompt_version is not None
                        and meta.get("prompt_version") != self.prompt_version):
                    raise ValueError(
                        f"snapshot is for prompt_version "
                        f"{meta.get('prompt_version')!r}, not "
                        f"{self.prompt_version!r}")
                raw_segments = meta.get("segments") or {}
                if not isinstance(raw_segments, dict):
                    raise ValueError("segments must be an object")
                segments = {str(k): int(v) for k, v in raw_segments.items()}
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    key = row["jkey"]
                    grades[key] = int(row["grade"])
                    timestamps[key] = str(row.get("ts") or "")
        except Exception as exc:  # noqa: BLE001 - any doubt => full rescan
            log.warning("[CACHE] ignoring snapshot %s (%s); rebuilding from "
                        "the log", path, exc)
            return
        self.grades = grades
        self._ts = timestamps
        self.segment_lines = segments
        self.stats.snapshot_used = True
        self.stats.snapshot_entries = len(grades)

    # -- snapshotting -------------------------------------------------------
    def snapshot(self, path: Path) -> Path:
        """Write the snapshot atomically (tmp + fsync + `os.replace`).

        Atomic because a half-written snapshot that a later startup happily read
        would answer lookups from a truncated label set — i.e. silently drop
        grades and re-bill for them. `os.replace` either publishes the whole file
        or leaves the previous one intact; there is no third outcome.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
        meta = {
            "kind": CACHE_META_KIND,
            "prompt_version": self.prompt_version,
            "created_utc": utc_now_iso(),
            "high_water_utc": max(self._ts.values(), default=""),
            "entries": len(self.grades),
            "segments": dict(sorted(self.segment_lines.items())),
        }
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(meta, sort_keys=True) + "\n")
            for key in sorted(self.grades):
                version, topic_id, chunk_id = split_jkey(key)
                handle.write(json.dumps({
                    "jkey": key,
                    "prompt_version": version,
                    "topic_id": topic_id,
                    "chunk_id": chunk_id,
                    "grade": self.grades[key],
                    "ts": self._ts.get(key, ""),
                }, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        return path

    def qrel_lines(self) -> Iterator[str]:
        """TREC 4-column qrel lines (`topic 0 chunk grade`) for publication.

        Parse failures are absent by construction: they never enter `grades`, so
        an unjudged pair is scored as gain 0 rather than as a fabricated grade
        (PLAN §5.5).
        """
        for key in sorted(self.grades):
            _, topic_id, chunk_id = split_jkey(key)
            yield f"{topic_id} 0 {chunk_id} {self.grades[key]}"


def _has_content_after(path: Path, lineno: int) -> bool:
    """True if `path` has a non-blank line after physical line `lineno`."""
    with Path(path).open(encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            if index > lineno and line.strip():
                return True
    return False


def rebuild_all(log_dir: Path) -> dict[str, JudgmentCache]:
    """Full rescan of every segment into one cache per `prompt_version`.

    What `python -m bm25tune rebuild-cache` runs. One streaming pass over the log
    (which may be hundreds of MB of embedded passage text) fanning out by prompt
    version, because the alternative — one pass per version — reads the whole log
    four times to answer the same question.
    """
    caches: dict[str, JudgmentCache] = {}
    for segment in iter_segments(log_dir):
        last_line = 0
        for lineno, record in iter_segment_records(segment):
            version = record.get("prompt_version")
            if not isinstance(version, str) or not version:
                continue
            cache = caches.get(version)
            if cache is None:
                cache = caches[version] = JudgmentCache(prompt_version=version)
                cache.stats.segments = 0
            cache.ingest_record(record)
            last_line = lineno
        # A version first seen in segment N gets no high-water mark for
        # segments 1..N-1, so a later incremental load re-reads them. That is
        # deliberate: re-reading is idempotent (latest-successful-wins), whereas
        # a fabricated high-water mark could skip records and re-bill them.
        for cache in caches.values():
            cache.segment_lines[segment.name] = last_line
            cache.stats.segments += 1
            if _has_content_after(segment, last_line):
                cache.stats.truncated_tails += 1
    return caches


# ---------------------------------------------------------------------------
# `--fresh` clobber protection (PLAN §5.8)
# ---------------------------------------------------------------------------
def assert_fresh_allowed(target: Path, *, log_dir: Path,
                         costs_dir: Path) -> None:
    """Refuse `--fresh` on the append-only audit artifacts.

    The judgment log and the cost ledger are the two things in this experiment
    that cannot be regenerated: the log *is* the raw judgments and the
    ground-truth spend, and the ledger is the budget's durable state. Every other
    artifact — run dirs, cache snapshots, score files — is derived and safe to
    supersede.

    Refuses if `target` is either protected directory, is inside one, or
    *contains* one (so `--fresh` on the data dir cannot take the log with it),
    and names `rebuild-cache` as the tool the caller probably wanted.
    """
    target = Path(target).resolve()
    for name, protected in (("judgments/log", Path(log_dir)),
                            ("costs", Path(costs_dir))):
        protected = protected.resolve()
        if target == protected or _is_relative(target, protected) \
                or _is_relative(protected, target):
            raise ProtectedPathError(
                f"refusing --fresh on {target}: it would destroy {name}/, which "
                "is an append-only audit record (raw judgments and the "
                "ground-truth spend; PLAN §5.3/§5.8). Derived artifacts can be "
                "superseded; these cannot be regenerated. To rebuild the cache "
                "snapshot from the log, use `python -m bm25tune rebuild-cache`.")


def _is_relative(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def rename_superseded(target: Path, *, log_dir: Path, costs_dir: Path,
                      stamp: str | None = None) -> Path | None:
    """Move `target` aside as `<name>.superseded-<UTCts>`; never delete.

    PLAN §5.8: `--fresh` **renames**. A rename is reversible by a human who
    realizes thirty seconds later that they wanted those judgments; `rm -rf` is
    not, and the artifacts in a run dir are downstream of hours of paid-for
    Bedrock calls.

    Returns the new path, or `None` if `target` did not exist. Raises
    `ProtectedPathError` via `assert_fresh_allowed` first.
    """
    target = Path(target)
    assert_fresh_allowed(target, log_dir=log_dir, costs_dir=costs_dir)
    if not target.exists():
        return None
    moved = target.with_name(f"{target.name}.superseded-{stamp or utc_stamp()}")
    suffix = 1
    while moved.exists():
        suffix += 1
        moved = target.with_name(
            f"{target.name}.superseded-{stamp or utc_stamp()}-{suffix}")
    os.replace(target, moved)
    log.info("[CACHE] superseded %s -> %s (renamed, not deleted)", target,
             moved)
    return moved


def write_lines(path: Path, lines: Iterable[str]) -> int:
    """Atomically write newline-terminated text (tmp + `os.replace`)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    count = 0
    with tmp.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line.rstrip("\n") + "\n")
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return count
