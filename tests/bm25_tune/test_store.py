"""The judgment log and cache: what protects paid-for work (PLAN §5.3, §5.8).

This module defends the two artifacts the experiment cannot regenerate — the
append-only judgment log (the raw grades *and* the ground-truth spend) and the
cost ledger it reconciles against — plus the one it can (the cache snapshot).
Everything here is fragile in the same specific way: a failure is silent. A
mis-keyed cache does not crash, it re-bills; a skipped log segment does not
crash, it drops grades; a half-written snapshot does not crash, it answers
lookups from a truncated label set.

Four properties carry the money:

1. `jkey` includes `prompt_version` and excludes `run_id`/`stage`. The first
   stops a `umbrela-v1` grade satisfying a `facet-v1` lookup (a label set that
   never existed); the second is the entire Stage-A → Stage-B reuse economy
   (PLAN §6.2).
2. A crash loses at most a truncated final line, which is *tolerated*; a
   malformed interior line is fatal, because that is corruption rather than an
   interrupted write.
3. Rebuilding from the log always reproduces the incremental state — the
   snapshot is only an accelerator and is allowed to be wrong.
4. `--fresh` can never reach `judgments/log/` or `costs/`, and renames rather
   than deletes everything else.

All hermetic: `store.py` is stdlib-only at import, so nothing here needs boto3,
a JVM, credentials, or a network (see this directory's conftest).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bm25tune import store
from bm25tune.store import (CACHE_META_KIND, JudgmentCache, JudgmentLog,
                            LogCorruption, ProtectedPathError,
                            assert_fresh_allowed, cache_snapshot_path,
                            iter_segments, jkey, make_record, read_segment,
                            rebuild_all, rename_superseded, split_jkey)

PV = "facet-v1"
OTHER_PV = "umbrela-v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _record(*, topic_id: str = "rag2026-900", chunk_id: str = "shard_0_1_p1",
            grade: int | None = 2, prompt_version: str = PV,
            ts: str = "2026-07-30T12:00:00.000Z", run_id: str = "runA",
            stage: str = "A", error: str | None = None, attempt: int = 1,
            usd: float | None = 0.0001, in_tokens: int = 900,
            out_tokens: int = 120) -> dict:
    """One §5.3 log record with everything defaulted to a plausible success.

    A helper rather than a fixture so each test can vary exactly the one field
    it is about, and so the 25-field record shape is constructed by
    `make_record` (the real code path) instead of hand-written dicts that could
    drift from it.
    """
    usage = (None if usd is None
             else {"inputTokens": in_tokens, "outputTokens": out_tokens})
    cost = None if usd is None else {"usd": usd, "tier": "standard"}
    return make_record(
        prompt_version=prompt_version, topic_id=topic_id, chunk_id=chunk_id,
        parent_docid=chunk_id.rsplit("_p", 1)[0],
        narrative_sha256="n" * 64, passage_text="a passage",
        passage_sha256="p" * 64, prompt_sha256="q" * 64,
        model_id="openai.gpt-oss-20b-1:0", region="ap-southeast-2",
        run_id=run_id, stage=stage, attempt=attempt, grade=grade,
        raw_text=f"##final score: {grade}", usage=usage, cost=cost,
        error=error, ts=ts)


def _write_segment(log_dir: Path, name: str, records: list[dict], *,
                   truncate_last: bool = False) -> Path:
    """Write a log segment by hand, optionally with a torn final line.

    Bypasses `JudgmentLog` on purpose: the point is to reproduce what a *crashed*
    writer leaves behind, which the writer itself will never produce.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    lines = [json.dumps(r, ensure_ascii=False) + "\n" for r in records]
    text = "".join(lines)
    if truncate_last and lines:
        text = "".join(lines[:-1]) + lines[-1][:len(lines[-1]) // 2]
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Keys — the cache's whole correctness argument (PLAN §5.3)
# ---------------------------------------------------------------------------
def test_jkey_is_prompt_version_qualified_so_rubrics_cannot_cross_contaminate(
) -> None:
    """Two rubrics judging the same pair must produce two different keys.

    WP0 judges the same 280 pairs under four prompt variants. If `prompt_version`
    were not in the key, the last variant judged would answer every lookup and
    the sweep would be scored against a blend of rubrics — a well-formed qrel for
    a label set that never existed, and undetectable after the fact.
    """
    assert jkey(PV, "t1", "c1") != jkey(OTHER_PV, "t1", "c1")
    assert split_jkey(jkey(PV, "t1", "c1")) == (PV, "t1", "c1")


def test_jkey_ignores_run_id_and_stage_so_stage_a_judgments_serve_stage_b(
) -> None:
    """`run_id`/`stage` are billing metadata, never key components.

    This is PLAN §6.2's reuse economy stated as a test: Stage B re-judging what
    Stage A already paid for would roughly double the experiment's bill. The
    record carries both fields; the key must not.
    """
    stage_a = _record(run_id="runA", stage="A")
    stage_b = _record(run_id="runB", stage="B")
    assert stage_a["run_id"] != stage_b["run_id"]
    assert stage_a["stage"] != stage_b["stage"]
    assert stage_a["jkey"] == stage_b["jkey"]


@pytest.mark.parametrize("parts", [
    ("", "t1", "c1"), (PV, "", "c1"), (PV, "t1", ""),
    ("pv::x", "t1", "c1"), (PV, "t1::x", "c1"), (PV, "t1", "c1::x"),
])
def test_jkey_rejects_empty_or_separator_bearing_components(
        parts: tuple[str, str, str]) -> None:
    """A component containing `::` would make two different triples collide.

    `("a::b", "c", "d")` and `("a", "b::c", "d")` join to the same string, so one
    topic's grades would answer another's lookups. Cheap to reject, impossible to
    detect later.
    """
    with pytest.raises(ValueError):
        jkey(*parts)


def test_make_record_derives_kind_so_a_null_grade_cannot_enter_the_qrels(
) -> None:
    """`kind` is derived from (grade, error), never accepted from the caller.

    A caller that could pass `kind="judgment"` alongside `grade=None` would put a
    parse failure into the qrels as a real label; one that could pass
    `kind="attempt_error"` on a success would hide a grade we already paid for.
    """
    ok = _record(grade=3)
    failed = _record(grade=None, error="parse_failure")
    assert ok["kind"] == store.KIND_JUDGMENT and store.is_success(ok)
    assert failed["kind"] == store.KIND_ATTEMPT_ERROR
    assert not store.is_success(failed)
    assert list(ok) == list(store.RECORD_FIELDS), "field order must be fixed"


def test_a_failed_attempt_still_carries_its_cost_block() -> None:
    """A call that returned garbage was still billed (PLAN §5.3).

    Summing `cost.usd` over successes only would under-report real spend, and the
    ledger reconciles against exactly this sum — so an uncosted failure row makes
    the ceiling itself wrong, not merely the report.
    """
    failed = _record(grade=None, error="parse_failure", usd=0.00021)
    assert failed["cost"] == {"usd": 0.00021, "tier": "standard"}
    assert failed["usage"]["inputTokens"] == 900


def test_an_attempt_that_never_reached_the_model_has_null_usage_and_cost(
) -> None:
    """`usage: null` means "not billed", which is not "billed zero tokens".

    The ledger distinguishes the two (a throttle before send vs. a zero-token
    call), and conflating them would let a retry storm look free.
    """
    never_sent = _record(grade=None, error="throttle", usd=None)
    assert never_sent["usage"] is None and never_sent["cost"] is None


# ---------------------------------------------------------------------------
# Append + replay round trip
# ---------------------------------------------------------------------------
def test_appended_records_replay_into_the_same_grades(tmp_path: Path) -> None:
    """Write through `JudgmentLog`, read back with `JudgmentCache.load`.

    The round trip is the resume story: after any crash, "re-run the same
    command" is only correct because everything already paid for comes back out
    of the log.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record(chunk_id="shard_0_1_p1", grade=3))
        handle.append(_record(chunk_id="shard_0_2_p1", grade=0))
        handle.append(_record(chunk_id="shard_0_3_p1", grade=None,
                              error="parse_failure"))
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_1_p1")) == 3
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_2_p1")) == 0
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_3_p1")) is None
    assert len(cache) == 2, "a parse failure must not enter the label set"
    assert cache.stats.failures == 1


def test_grade_zero_is_a_cache_hit_not_a_miss(tmp_path: Path) -> None:
    """`grade == 0` is a real judgment, and `0` is falsy in Python.

    The single most likely re-billing bug in this module: any `if cache.get(k):`
    would re-judge every non-relevant pair in the pool — and grade 0 is a large
    share of a depth-30 pool, so it would be a substantial, invisible overspend.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record(grade=0))
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    key = jkey(PV, "rag2026-900", "shard_0_1_p1")
    assert cache.get(key) == 0
    assert key in cache


def test_the_log_is_flushed_per_line_so_a_reader_sees_it_before_close(
        tmp_path: Path) -> None:
    """Every `append` flushes, so a crash cannot lose a line to Python buffering.

    Without the per-line flush, a `tail -f` of a live run would show nothing and
    an abrupt kill would lose up to a 8 kB buffer of already-billed judgments.
    """
    log_dir = tmp_path / "log"
    handle = JudgmentLog(log_dir).open()
    try:
        handle.append(_record())
        assert handle.path.read_text(encoding="utf-8").count("\n") == 1
    finally:
        handle.close()


def test_fsync_fires_on_the_line_count_branch_and_on_close(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10 lines triggers one fsync; `close()` always adds a final one.

    PLAN §5.8 fixes the cadence, and both branches matter for a different
    failure: the count bound caps loss under load, the unconditional close fsync
    is what makes a clean drain actually durable.
    """
    synced: list[int] = []
    monkeypatch.setattr(store.os, "fsync", lambda fd: synced.append(fd))
    handle = JudgmentLog(tmp_path / "log", fsync_every_lines=10,
                         fsync_every_seconds=10_000.0, clock=lambda: 0.0)
    handle.open()
    for i in range(9):
        handle.append(_record(chunk_id=f"shard_0_{i}_p1"))
    assert synced == [], "no fsync before the 10th line"
    handle.append(_record(chunk_id="shard_0_9_p1"))
    assert len(synced) == 1
    handle.close()
    assert len(synced) == 2, "close must fsync unconditionally"


def test_maybe_fsync_covers_the_five_second_branch_when_the_queue_is_idle(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow call rate must not leave paid-for work unsynced for minutes.

    A pure line-count cadence (an earlier draft's "every 25 lines") is the exact
    failure PLAN §5.8 rejects: at a few calls per minute it exposes minutes of
    already-billed judgments to a machine crash. The writer thread is already
    awake on its queue timeout, so this branch is free.
    """
    synced: list[int] = []
    monkeypatch.setattr(store.os, "fsync", lambda fd: synced.append(fd))
    now = [0.0]
    handle = JudgmentLog(tmp_path / "log", fsync_every_lines=1000,
                         fsync_every_seconds=5.0, clock=lambda: now[0])
    handle.open()
    handle.append(_record())
    assert synced == []
    handle.maybe_fsync()
    assert synced == [], "not yet 5 seconds"
    now[0] = 5.1
    handle.maybe_fsync()
    assert len(synced) == 1
    handle.maybe_fsync()
    assert len(synced) == 1, "nothing new written, so nothing to sync"


def test_two_writer_processes_get_distinct_segments_that_merge_on_load(
        tmp_path: Path) -> None:
    """Per-process segment names are what remove the need for a lock.

    `events-<ts>-<host>-<pid>.jsonl` means two concurrent writers can never share
    a handle, so "safe under concurrent writers" is a property of the filenames
    rather than of correct locking discipline — and both segments must still fold
    into one cache.
    """
    log_dir = tmp_path / "log"
    first = JudgmentLog(log_dir, name=store.segment_name(
        stamp="20260730T120000Z", host="hostA", pid=111))
    second = JudgmentLog(log_dir, name=store.segment_name(
        stamp="20260730T120000Z", host="hostA", pid=222))
    with first, second:
        first.append(_record(chunk_id="shard_0_1_p1", grade=3))
        second.append(_record(chunk_id="shard_0_2_p1", grade=1))
    assert len(iter_segments(log_dir)) == 2
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert len(cache) == 2


# ---------------------------------------------------------------------------
# Corruption tolerance (PLAN §5.3/§5.8)
# ---------------------------------------------------------------------------
def test_a_truncated_final_line_is_tolerated_and_the_rest_survives(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """An interrupted write must cost one re-judgment, not the whole log.

    This is the ordinary machine-crash artifact: the process died between
    `write` and the newline. Refusing to read such a segment would strand every
    judgment before it, all of which are already paid for.
    """
    log_dir = tmp_path / "log"
    _write_segment(log_dir, store.segment_name(stamp="20260730T120000Z",
                                               host="h", pid=1),
                   [_record(chunk_id="shard_0_1_p1", grade=3),
                    _record(chunk_id="shard_0_2_p1", grade=1),
                    _record(chunk_id="shard_0_3_p1", grade=2)],
                   truncate_last=True)
    with caplog.at_level("WARNING"):
        cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert len(cache) == 2
    assert cache.stats.truncated_tails == 1
    assert "[LOG-TAIL]" in caplog.text


def test_a_malformed_interior_line_is_fatal(tmp_path: Path) -> None:
    """Corruption in the middle of a segment is not an interrupted write.

    A line with content *after* it was fully written and then damaged, which
    means the log — the source of truth for both the qrels and the money — is not
    what it claims. Skipping it would silently under-count spend and drop
    judgments; the honest response is to stop and name the line.
    """
    log_dir = tmp_path / "log"
    path = log_dir / store.segment_name(stamp="20260730T120000Z", host="h",
                                        pid=1)
    log_dir.mkdir(parents=True)
    good = json.dumps(_record(chunk_id="shard_0_1_p1")) + "\n"
    path.write_text(good + '{"kind": "judgm\n' + good, encoding="utf-8")
    with pytest.raises(LogCorruption) as exc:
        read_segment(path)
    assert ":2:" in str(exc.value), "the failure must name the line"


def test_a_blank_line_is_not_corruption(tmp_path: Path) -> None:
    """Empty lines are skipped rather than raising.

    A stray newline (an editor, a `cat` of two segments) is not evidence of a
    damaged record, and treating it as fatal would make the log needlessly
    brittle for zero safety gain.
    """
    log_dir = tmp_path / "log"
    path = log_dir / store.segment_name(stamp="20260730T120000Z", host="h",
                                        pid=1)
    log_dir.mkdir(parents=True)
    line = json.dumps(_record()) + "\n"
    path.write_text(line + "\n" + line, encoding="utf-8")
    assert len(read_segment(path).records) == 2


# ---------------------------------------------------------------------------
# Latest-successful-wins
# ---------------------------------------------------------------------------
def test_a_later_rejudge_supersedes_an_earlier_grade(tmp_path: Path) -> None:
    """Re-judging the same pair keeps the newest successful grade.

    Ordering is by record `ts` with segment order as the tie-break, so a
    deliberate re-judgment (a prompt fix inside the same version, a manual
    correction) actually takes effect instead of being ignored.
    """
    log_dir = tmp_path / "log"
    _write_segment(log_dir, store.segment_name(stamp="20260730T120000Z",
                                               host="h", pid=1),
                   [_record(grade=1, ts="2026-07-30T12:00:00.000Z"),
                    _record(grade=3, ts="2026-07-30T13:00:00.000Z")])
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_1_p1")) == 3
    assert cache.stats.superseded == 1


def test_an_out_of_order_record_cannot_overwrite_a_newer_grade(
        tmp_path: Path) -> None:
    """Two concurrent writers may interleave; the newer `ts` still wins.

    Segment order alone would let a slow writer's older judgment clobber a newer
    one purely because its file sorts later, silently changing a published label.
    """
    log_dir = tmp_path / "log"
    _write_segment(log_dir, store.segment_name(stamp="20260730T120000Z",
                                               host="h", pid=1),
                   [_record(grade=3, ts="2026-07-30T13:00:00.000Z")])
    _write_segment(log_dir, store.segment_name(stamp="20260730T120100Z",
                                               host="h", pid=2),
                   [_record(grade=1, ts="2026-07-30T12:00:00.000Z")])
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_1_p1")) == 3


def test_a_later_failure_cannot_erase_a_grade_already_paid_for(
        tmp_path: Path) -> None:
    """Only successes update an entry.

    A re-judge that throttles or fails to parse must leave the existing grade
    alone — otherwise a transient failure during any later run would delete a
    label we paid for and quietly shrink the qrels.
    """
    log_dir = tmp_path / "log"
    _write_segment(log_dir, store.segment_name(stamp="20260730T120000Z",
                                               host="h", pid=1),
                   [_record(grade=2, ts="2026-07-30T12:00:00.000Z"),
                    _record(grade=None, error="parse_failure",
                            ts="2026-07-30T14:00:00.000Z")])
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_1_p1")) == 2


def test_a_cache_scoped_to_one_version_ignores_the_others_records(
        tmp_path: Path) -> None:
    """Prompt-version isolation, enforced at ingest rather than at lookup.

    A cache that stored every version and filtered on read would leak through any
    call site that used a raw key — so records for another rubric are dropped
    outright, and `len(cache)` is the count for *this* label set.
    """
    log_dir = tmp_path / "log"
    _write_segment(log_dir, store.segment_name(stamp="20260730T120000Z",
                                               host="h", pid=1),
                   [_record(prompt_version=PV, grade=3),
                    _record(prompt_version=OTHER_PV, grade=0)])
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert len(cache) == 1
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_1_p1")) == 3
    assert cache.get(jkey(OTHER_PV, "rag2026-900", "shard_0_1_p1")) is None


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------
def test_the_snapshot_round_trips_and_leaves_no_temp_file(
        tmp_path: Path) -> None:
    """tmp + `os.replace`: either the whole file publishes or the old one stays.

    A half-written snapshot that a later startup happily read would answer
    lookups from a truncated label set — dropping grades and re-billing them.
    `os.replace` has no third outcome, and no `.tmp` may survive to be mistaken
    for a snapshot.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record(chunk_id="shard_0_1_p1", grade=3))
        handle.append(_record(chunk_id="shard_0_2_p1", grade=0))
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    path = cache.snapshot(cache_snapshot_path(tmp_path / "cache", PV))
    assert path.name == "qrels-facet-v1.jsonl"
    assert not list(path.parent.glob("*.tmp*"))
    reloaded = JudgmentCache.load(log_dir, prompt_version=PV,
                                 snapshot_path=path)
    assert reloaded.grades == cache.grades
    assert reloaded.stats.snapshot_used


def test_the_snapshot_header_records_the_prompt_version_and_segment_marks(
        tmp_path: Path) -> None:
    """The meta line is what makes the fast path safe to take.

    `prompt_version` lets a load refuse someone else's snapshot, and the
    per-segment line counts are the high-water mark that decides what gets
    replayed. Both are load-bearing enough to pin their presence.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record())
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    path = cache.snapshot(tmp_path / "cache" / "snap.jsonl")
    meta = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert meta["kind"] == CACHE_META_KIND
    assert meta["prompt_version"] == PV
    assert meta["entries"] == 1
    assert sum(meta["segments"].values()) == 1


def test_a_snapshot_for_another_prompt_version_is_refused_and_rescanned(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A mis-versioned snapshot must cost a rescan, never a wrong label set.

    Trusting it is how `umbrela-v1` grades end up answering `facet-v1` lookups —
    the exact poisoning the key design exists to prevent. Refusing costs seconds.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record(prompt_version=PV, grade=3))
    wrong = JudgmentCache.load(log_dir, prompt_version=None)
    wrong.prompt_version = OTHER_PV
    path = wrong.snapshot(tmp_path / "cache" / "snap.jsonl")
    with caplog.at_level("WARNING"):
        cache = JudgmentCache.load(log_dir, prompt_version=PV,
                                   snapshot_path=path)
    assert not cache.stats.snapshot_used
    assert "[CACHE] ignoring snapshot" in caplog.text
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_1_p1")) == 3


def test_a_corrupt_snapshot_falls_back_to_the_log(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The log is the sole source of truth, so a bad snapshot is survivable.

    If a damaged accelerator could stop a run, the "cache is only a cache" claim
    would be false — and the operator's recovery would be manual file surgery
    instead of doing nothing at all.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record(grade=2))
    snap = tmp_path / "cache" / "snap.jsonl"
    snap.parent.mkdir(parents=True)
    snap.write_text("this is not json\n", encoding="utf-8")
    with caplog.at_level("WARNING"):
        cache = JudgmentCache.load(log_dir, prompt_version=PV,
                                   snapshot_path=snap)
    assert cache.get(jkey(PV, "rag2026-900", "shard_0_1_p1")) == 2
    assert not cache.stats.snapshot_used


def test_a_snapshot_does_not_hide_records_appended_after_it_was_taken(
        tmp_path: Path) -> None:
    """The high-water mark is per-segment LINES, not the segment's name stamp.

    PLAN §5.3's wording ("replay only segments newer than the snapshot") is a
    trap: a segment's name carries the writer's *start* time, so the segment that
    was still growing when the snapshot was taken would be skipped forever —
    silently dropping every judgment appended afterwards and re-billing all of
    them. This is the regression test for that deviation.
    """
    log_dir = tmp_path / "log"
    name = store.segment_name(stamp="20260730T120000Z", host="h", pid=1)
    handle = JudgmentLog(log_dir, name=name).open()
    handle.append(_record(chunk_id="shard_0_1_p1", grade=3))
    handle.fsync()
    mid_run = JudgmentCache.load(log_dir, prompt_version=PV)
    snap = mid_run.snapshot(tmp_path / "cache" / "snap.jsonl")
    # ...the same segment keeps growing after the snapshot.
    handle.append(_record(chunk_id="shard_0_2_p1", grade=1))
    handle.close()

    resumed = JudgmentCache.load(log_dir, prompt_version=PV,
                                 snapshot_path=snap)
    assert resumed.stats.snapshot_used
    assert resumed.get(jkey(PV, "rag2026-900", "shard_0_2_p1")) == 1, (
        "the post-snapshot append was skipped — it would be re-judged and "
        "re-billed")


def test_note_appended_keeps_a_live_writers_high_water_mark_honest(
        tmp_path: Path) -> None:
    """The driver's writer thread folds records in as it writes them.

    Without `note_appended`, the snapshot taken at drain time would claim zero
    lines for the segment this process just wrote, and the next startup would
    replay all of them. Correct but wasteful on a 100k-line log — and the same
    accounting is what makes the *incremental* replay above safe.
    """
    log_dir = tmp_path / "log"
    name = store.segment_name(stamp="20260730T120000Z", host="h", pid=1)
    handle = JudgmentLog(log_dir, name=name).open()
    cache = JudgmentCache(prompt_version=PV)
    for i in range(3):
        record = _record(chunk_id=f"shard_0_{i}_p1", grade=i)
        handle.append(record)
        cache.note_appended(handle.name)
        cache.ingest_record(record)
    handle.close()
    assert cache.segment_lines[name] == 3
    snap = cache.snapshot(tmp_path / "cache" / "snap.jsonl")
    reloaded = JudgmentCache.load(log_dir, prompt_version=PV,
                                  snapshot_path=snap)
    assert reloaded.stats.records == 0, "nothing should need replaying"
    assert len(reloaded) == 3


def test_qrel_lines_are_trec_four_column_and_omit_parse_failures(
        tmp_path: Path) -> None:
    """The published qrels form (PLAN §5.5/§7.4).

    An unjudged pair must be *absent*, so `score` counts it as a judged@10
    shortfall rather than scoring it as a fabricated gain-0 relevance judgment.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record(chunk_id="shard_0_1_p1", grade=3))
        handle.append(_record(chunk_id="shard_0_2_p1", grade=None,
                              error="parse_failure"))
    cache = JudgmentCache.load(log_dir, prompt_version=PV)
    assert list(cache.qrel_lines()) == ["rag2026-900 0 shard_0_1_p1 3"]


# ---------------------------------------------------------------------------
# rebuild-cache
# ---------------------------------------------------------------------------
def test_rebuild_all_reproduces_the_incremental_state_per_version(
        tmp_path: Path) -> None:
    """A full rescan must equal what the incremental path built.

    This is the property that lets the snapshot be "only a cache": if the two
    could disagree, `rebuild-cache` would be a way to *change* the label set
    rather than to restore it, and no published qrel would be reproducible.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        handle.append(_record(prompt_version=PV, chunk_id="shard_0_1_p1",
                              grade=3))
        handle.append(_record(prompt_version=PV, chunk_id="shard_0_2_p1",
                              grade=0))
        handle.append(_record(prompt_version=OTHER_PV,
                              chunk_id="shard_0_1_p1", grade=1))
    rebuilt = rebuild_all(log_dir)
    assert set(rebuilt) == {PV, OTHER_PV}
    for version, cache in rebuilt.items():
        incremental = JudgmentCache.load(log_dir, prompt_version=version)
        assert cache.grades == incremental.grades, version


def test_rebuild_all_reads_the_log_once_for_every_version(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One streaming pass, fanned out by prompt version.

    The log embeds every passage's full text (PLAN §5.3 estimates 50-150 MB per
    run), so a pass per version would read hundreds of MB four times to answer
    the same question — and `rebuild-cache` is exactly what an operator reaches
    for when they are already in a hurry.
    """
    log_dir = tmp_path / "log"
    with JudgmentLog(log_dir) as handle:
        for version in (PV, OTHER_PV):
            handle.append(_record(prompt_version=version, grade=2))
    opens: list[Path] = []
    real_iter = store.iter_segment_records

    def _counting(path: Path, **kwargs: object):
        opens.append(Path(path))
        return real_iter(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "iter_segment_records", _counting)
    caches = rebuild_all(log_dir)
    assert set(caches) == {PV, OTHER_PV}
    assert len(opens) == 1, f"read the log {len(opens)} times, not once"


# ---------------------------------------------------------------------------
# `--fresh` clobber protection (PLAN §5.8)
# ---------------------------------------------------------------------------
def test_fresh_is_refused_on_the_log_dir_the_ledger_and_their_parents(
        tmp_path: Path) -> None:
    """The two append-only audit records are structurally unreachable by `--fresh`.

    They are the only artifacts here that cannot be regenerated: the log *is* the
    raw judgments and the ground-truth spend, and the ledger is the budget's
    durable state. A `--fresh` that could rename either would destroy hours of
    paid-for work and make the cost reconciliation unfalsifiable — so a *parent*
    directory is refused too, since renaming it takes the protected dirs along.
    """
    log_dir = tmp_path / "judgments" / "log"
    costs_dir = tmp_path / "costs"
    for target in (log_dir, costs_dir, log_dir / "events-x.jsonl",
                   tmp_path / "judgments", tmp_path):
        with pytest.raises(ProtectedPathError) as exc:
            assert_fresh_allowed(target, log_dir=log_dir, costs_dir=costs_dir)
        assert "rebuild-cache" in str(exc.value), (
            "the refusal must name the tool the caller actually wanted")


def test_fresh_is_allowed_on_derived_artifacts_and_renames_rather_than_deletes(
        tmp_path: Path) -> None:
    """A superseded snapshot is moved aside, never removed (PLAN §5.8).

    A rename is reversible by a human who realizes thirty seconds later that they
    wanted those judgments; `rm -rf` is not, and everything in a run dir is
    downstream of hours of paid-for Bedrock calls.
    """
    log_dir = tmp_path / "judgments" / "log"
    costs_dir = tmp_path / "costs"
    log_dir.mkdir(parents=True)
    costs_dir.mkdir()
    snapshot = tmp_path / "judgments" / "cache" / "qrels-facet-v1.jsonl"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("grades\n", encoding="utf-8")
    moved = rename_superseded(snapshot, log_dir=log_dir, costs_dir=costs_dir,
                              stamp="20260730T120000Z")
    assert moved is not None and moved.is_file()
    assert moved.name == "qrels-facet-v1.jsonl.superseded-20260730T120000Z"
    assert not snapshot.exists()
    assert moved.read_text(encoding="utf-8") == "grades\n"


def test_rename_superseded_on_a_missing_target_is_a_no_op(
        tmp_path: Path) -> None:
    """`--fresh` on a first run must not fail just because nothing exists yet.

    The flag is most often typed on a re-run, but a scripted launch may pass it
    unconditionally; erroring there would block a run for no safety reason.
    """
    log_dir = tmp_path / "judgments" / "log"
    costs_dir = tmp_path / "costs"
    assert rename_superseded(tmp_path / "cache" / "nope.jsonl",
                             log_dir=log_dir, costs_dir=costs_dir) is None


def test_a_second_supersede_in_the_same_second_does_not_overwrite_the_first(
        tmp_path: Path) -> None:
    """Two `--fresh` runs within one second must not lose the earlier archive.

    The stamp has second resolution, so the naive name collides — and the
    collision would silently destroy the very artifact the rename exists to
    preserve.
    """
    log_dir = tmp_path / "judgments" / "log"
    costs_dir = tmp_path / "costs"
    target = tmp_path / "cache" / "snap.jsonl"
    target.parent.mkdir(parents=True)
    first_paths = []
    for body in ("one\n", "two\n"):
        target.write_text(body, encoding="utf-8")
        first_paths.append(rename_superseded(
            target, log_dir=log_dir, costs_dir=costs_dir,
            stamp="20260730T120000Z"))
    assert first_paths[0] != first_paths[1]
    assert first_paths[0].read_text(encoding="utf-8") == "one\n"
    assert first_paths[1].read_text(encoding="utf-8") == "two\n"


def test_write_lines_is_atomic_and_leaves_no_temp_behind(
        tmp_path: Path) -> None:
    """The published qrels file is written whole or not at all.

    `qrels-<pv>.txt` is committed to the repo (PLAN §7.4) and read by `score`; a
    truncated one would score every config against a partial label set while
    looking perfectly well-formed.
    """
    path = tmp_path / "out" / "qrels.txt"
    count = store.write_lines(path, ["t 0 c 3", "t 0 d 1"])
    assert count == 2
    assert path.read_text(encoding="utf-8") == "t 0 c 3\nt 0 d 1\n"
    assert [p.name for p in path.parent.iterdir()] == ["qrels.txt"]


# ---------------------------------------------------------------------------
# Misc invariants
# ---------------------------------------------------------------------------
def test_segments_sort_chronologically_by_name(tmp_path: Path) -> None:
    """Lexicographic name order == replay order, and pid breaks the tie.

    Replay order is the tie-break behind "latest successful grade wins" when two
    concurrent writers judged the same pair, so it has to be a property of the
    filenames rather than of filesystem `iterdir` order (which is arbitrary).
    """
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    names = [store.segment_name(stamp="20260730T120100Z", host="h", pid=2),
             store.segment_name(stamp="20260730T120000Z", host="h", pid=9),
             store.segment_name(stamp="20260730T120000Z", host="h", pid=1)]
    for name in names:
        (log_dir / name).write_text("", encoding="utf-8")
    (log_dir / "not-a-segment.jsonl").write_text("", encoding="utf-8")
    (log_dir / "qrels-facet-v1.jsonl").write_text("", encoding="utf-8")
    assert [p.name for p in iter_segments(log_dir)] == [names[2], names[1],
                                                        names[0]]


def test_iter_segments_on_a_missing_dir_is_empty_not_an_error(
        tmp_path: Path) -> None:
    """A first run has no log dir yet, and that is not a failure.

    `judge-pool` consults the cache before it creates anything, so this path is
    hit on every fresh clone.
    """
    assert iter_segments(tmp_path / "never-created") == []


def test_the_record_timestamp_is_utc_with_millis_and_a_z_suffix() -> None:
    """`ts` is compared as a *string* to order re-judgments.

    A fixed-width, zero-padded UTC format is what makes lexicographic comparison
    equal chronological comparison; a local-time or variable-width stamp would
    silently mis-order supersessions and could resurrect an old grade.
    """
    ts = store.utc_now_iso()
    assert len(ts) == len("2026-07-30T12:00:00.000Z")
    assert ts.endswith("Z") and ts[10] == "T" and ts[-5] == "."


def test_the_host_tag_is_filename_safe_so_segment_names_stay_greppable(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A dotted or slashed hostname must not leak into the segment filename.

    `platform.node()` on a cluster commonly returns `host.domain.example`; used
    raw, the segment's apparent extension becomes `.example-1234.jsonl` and a
    `/`-bearing node name would escape the log dir entirely. `_host_tag` is also
    deliberately `platform.node()` rather than a socket call, so that naming a
    segment can never block on DNS inside the writer thread.
    """
    monkeypatch.setattr(store.platform, "node",
                        lambda: "node1.cluster.example")
    assert store._host_tag() == "node1"
    monkeypatch.setattr(store.platform, "node", lambda: "we/ird host")
    assert store._host_tag() == "we-ird-host"
    name = store.segment_name(stamp="20260730T120000Z", pid=4242)
    assert name == "events-20260730T120000Z-we-ird-host-4242.jsonl"
    assert os.sep not in name
