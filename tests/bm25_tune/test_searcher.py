"""What `searcher.py` defends: one searcher, one config at a time, no JVM in CI.

`ChunkSearcher` is the only code in the harness that touches a 921-million-chunk
Lucene index living read-only under another user's home. None of that can be
exercised in the offline suite, so what *is* pinned here is everything around the
JVM call — and each of these has a silent failure mode:

- **The lazy `pyserini` import.** If it ever moves to module scope, this whole
  test directory needs an `importorskip`, and the tests it gates become silent
  skips that prove nothing (PLAN §4.1/§7.3). Pinned in a subprocess, because an
  in-process `sys.modules` check would report whatever an earlier test imported.
- **`set_bm25` mid-batch.** `set_config` racing a `batch_search` would score part
  of a batch under the wrong config, producing a run file that is well-formed and
  wrong, with nothing downstream able to detect it (PLAN R9). The rule is
  enforced, so it is tested.
- **`doc(id).contents()` vs `.raw()`.** `.raw()` is None on this index
  (**[measured]**), so a `.raw()`-based implementation would hand the judge empty
  passages — graded 0 across the board, sweep still producing a plausible score
  matrix.
- **The `num_docs` assertion.** A moved or re-chunked index would silently make
  every cached judgment refer to text that is no longer there.
- **Warmup.** Without it the first grid cell's 9.4 s cold start reads as a
  regression in a log an operator is watching for exactly that.

The seam is `_import_lucene_searcher()`: `FakeLuceneSearcher` below implements the
four pyserini methods the harness calls (`batch_search`, `set_bm25`, `doc`,
`close`) and — importantly — **shifts its rankings when `set_bm25` changes**, so
the grid and pooling logic is exercised against configs that genuinely reorder
results, the way the real index does (**[measured]** top-10 overlap falls to
0.72).

The last section drives `cli.cmd_search_sweep` through that same fake, because the
sweep's contract is not "it searches" but **"re-running the same command finishes
the job and changes nothing else"** — and the two bugs that surfaced during a live
plumbing check were both in the resumed path, not the searching one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bm25tune import searcher as searcher_mod
from bm25tune.extract import QueryRec
from bm25tune.searcher import (BASELINE_CONFIG, EXPECTED_NUM_DOCS,
                               ChunkSearcher, SearcherError, config_key,
                               format_param, parse_configs, run_file_name,
                               stage_a_grid)


# ---------------------------------------------------------------------------
# The fake pyserini surface
# ---------------------------------------------------------------------------
class FakeHit:
    """A pyserini `JScoredDoc` stand-in: just `docid` and `score`."""

    def __init__(self, docid: str, score: float) -> None:
        self.docid = docid
        self.score = score


class FakeDoc:
    """A pyserini `Document` stand-in whose `raw()` is None, as measured.

    `raw()` returning None is not incidental colour — it is the measured
    behaviour of this index, and the reason `fetch_texts` must use `contents()`.
    A fake that returned text from both would let a `.raw()` regression pass.
    """

    def __init__(self, contents: str | None) -> None:
        self._contents = contents

    def contents(self) -> str | None:
        return self._contents

    def raw(self) -> None:
        return None


class FakeLuceneSearcher:
    """Scriptable stand-in for `LuceneSearcher` whose ranking depends on config.

    `batch_search` returns, for each query, the chunk ids of its scripted
    ranking **rotated by a config-dependent offset**, so two configs produce
    different orders over a shared candidate set — the measured behaviour that
    gives the sweep something to find. It also records every call and every
    `set_bm25`, so a test can assert the *sequence* of config changes rather than
    just the final state.
    """

    def __init__(self, index_dir: str, *, num_docs: int = EXPECTED_NUM_DOCS,
                 rankings: dict[str, list[str]] | None = None,
                 texts: dict[str, str] | None = None) -> None:
        self.index_dir = index_dir
        self.num_docs = num_docs
        self._rankings = rankings or {}
        self._texts = texts or {}
        self.bm25: tuple[float, float] | None = None
        self.calls: list[tuple[tuple[float, float] | None, list[str]]] = []
        self.events: list[str] = []
        self.closed = False
        #: Set by a test to have `batch_search` re-enter `set_config`, which is
        #: the race the enforcement in `set_config` exists to prevent.
        self.on_search = None

    def set_bm25(self, k1: float, b: float) -> None:
        self.bm25 = (k1, b)
        self.events.append(f"set_bm25({k1},{b})")

    def batch_search(self, queries, qids, k=10, threads=1):
        self.events.append(f"batch_search({len(qids)},k={k},t={threads})")
        self.calls.append((self.bm25, list(qids)))
        if self.on_search is not None:
            self.on_search()
        # Rotation offset from the config, so distinct (k1, b) give distinct
        # orders over the same candidates.
        shift = 0 if self.bm25 is None else int(round(self.bm25[0] * 10
                                                     + self.bm25[1] * 100))
        out = {}
        for qid in qids:
            ranked = list(self._rankings.get(qid, []))
            if ranked:
                offset = shift % len(ranked)
                ranked = ranked[offset:] + ranked[:offset]
            out[qid] = [FakeHit(cid, float(len(ranked) - i))
                        for i, cid in enumerate(ranked[:k])]
        return out

    def doc(self, docid: str):
        self.events.append(f"doc({docid})")
        if docid not in self._texts:
            return None
        return FakeDoc(self._texts[docid])

    def close(self) -> None:
        self.closed = True


def make_searcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
                  num_docs: int = EXPECTED_NUM_DOCS,
                  rankings: dict[str, list[str]] | None = None,
                  texts: dict[str, str] | None = None,
                  expected_num_docs: int | None = EXPECTED_NUM_DOCS,
                  batch_size: int = 64) -> tuple[ChunkSearcher, list]:
    """A `ChunkSearcher` over a real (empty) dir with the fake class injected.

    A real directory, because `_open`'s fail-fast branch checks `is_dir()` before
    it ever reaches pyserini — a `tmp_path` keeps that check exercised rather
    than bypassed. Returns the searcher and a list that collects every fake
    instance it constructs, so a test can assert only *one* was ever opened.
    """
    index_dir = tmp_path / "index"
    index_dir.mkdir(exist_ok=True)
    built: list[FakeLuceneSearcher] = []

    def factory(path: str) -> FakeLuceneSearcher:
        fake = FakeLuceneSearcher(path, num_docs=num_docs, rankings=rankings,
                                  texts=texts)
        built.append(fake)
        return fake

    chunk_searcher = ChunkSearcher(index_dir, threads=4,
                                   batch_size=batch_size,
                                   expected_num_docs=expected_num_docs)
    monkeypatch.setattr(chunk_searcher, "_import_lucene_searcher",
                        lambda: factory)
    return chunk_searcher, built


def q(topic: str, text: str) -> QueryRec:
    return QueryRec.make(topic, f"narrative for {topic}", text, 30)


# ---------------------------------------------------------------------------
# Import discipline
# ---------------------------------------------------------------------------
def test_importing_searcher_does_not_import_pyserini() -> None:
    """`import bm25tune.searcher` must not pull in pyserini or the JVM.

    The constraint the whole hermetic suite rests on: if this breaks, these tests
    need a dep group and an `importorskip`, and a skipped test is a green run that
    proved nothing (PLAN §4.1/§7.3). Checked in a subprocess because the full
    suite imports heavy modules for other tests, so an in-process `sys.modules`
    check would pass or fail on test ordering.
    """
    task_root = Path(__file__).resolve().parents[2] / "tasks" / "bm25_tune"
    probe = (
        "import sys;"
        f"sys.path.insert(0, {str(task_root)!r});"
        "import bm25tune.searcher, bm25tune.pool;"
        "print(','.join(m for m in ('pyserini','jnius','torch','numpy')"
        " if m in sys.modules))")
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", (
        f"{proc.stdout.strip()} imported at module scope; the import belongs "
        "inside ChunkSearcher._import_lucene_searcher()")


def test_constructing_a_searcher_opens_nothing(tmp_path: Path) -> None:
    """`__init__` must not touch the JVM, the filesystem, or a 1.5 TB mmap.

    Construction has to be free so a subcommand that ends up not searching (a
    fully-resumed sweep, a config error caught later) never pays the 9.4 s cold
    start — and so this test file can construct one with a nonexistent path.
    """
    chunk_searcher = ChunkSearcher(tmp_path / "does-not-exist")
    assert chunk_searcher.num_docs is None
    assert chunk_searcher.config is None
    assert chunk_searcher.warmup_seconds == 0.0


# ---------------------------------------------------------------------------
# Opening: fail-fast and the identity assertion
# ---------------------------------------------------------------------------
def test_a_missing_index_dir_names_the_env_var_not_a_jvm_trace(
        tmp_path: Path) -> None:
    """An unreadable index fails before pyserini is even imported.

    The index is ~1.5 TB under another user's home (PLAN R7), so "not mounted" and
    "no read permission" are routine, and the JVM's failure mode for either is
    opaque. Failing first also means the message is right on a machine with no
    pyserini installed at all — which is where this test runs.
    """
    chunk_searcher = ChunkSearcher(tmp_path / "not-there")
    with pytest.raises(SearcherError, match="BM25_TUNE_INDEX_DIR"):
        chunk_searcher.warmup()


def test_a_wrong_num_docs_aborts_and_says_do_not_update_the_expectation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A different chunk count means a different corpus — stop, don't adapt.

    This is the guard against the worst silent failure in the experiment: a
    re-chunked or re-built index at the same path would keep every chunk id
    *shaped* the same while the text behind it changed, so cached judgments would
    be applied to passages nobody judged and the score matrix would still look
    fine (PLAN R7).
    """
    chunk_searcher, _ = make_searcher(tmp_path, monkeypatch,
                                      num_docs=921_892_635)
    with pytest.raises(SearcherError) as excinfo:
        chunk_searcher.warmup()
    assert "921892635" in str(excinfo.value)
    assert str(EXPECTED_NUM_DOCS) in str(excinfo.value)
    assert "STOP" in str(excinfo.value)


def test_expected_num_docs_matches_the_measured_index() -> None:
    """The asserted chunk count is the measured one, recorded in the manifest.

    A drifted constant would either disable the identity check (if it matched
    nothing) or reject the real index outright. It is also written into every run
    manifest, so it is part of the published provenance.
    """
    assert EXPECTED_NUM_DOCS == 921_892_634


def test_one_searcher_is_opened_for_the_whole_sweep(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every config reuses one `LuceneSearcher`; opening per config is the bug.

    Opening the index costs JVM startup plus mmap faulting, so a per-config open
    would multiply the sweep's cold cost by 26 — and would defeat the page-cache
    warming that makes configs 2..26 fast (**[measured]** 1.3–1.6 s vs 9.4 s).
    """
    chunk_searcher, built = make_searcher(
        tmp_path, monkeypatch, rankings={q("t1", "alpha").qkey: ["c1", "c2"]})
    queries = [q("t1", "alpha")]
    for k1, b in [(0.5, 0.2), (0.9, 0.4), (1.6, 0.8)]:
        chunk_searcher.set_config(k1, b)
        chunk_searcher.run_config(queries, k=2)
    assert len(built) == 1


def test_a_config_set_before_open_is_applied_on_open(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`set_config` before the first search must not be silently lost.

    `set_config` is deliberately JVM-free so it can be called during setup, which
    means the deferred value has to be applied when the index opens. If it were
    dropped, the first grid cell would be scored under pyserini's default and the
    run file would carry a config label it was never scored under.
    """
    chunk_searcher, built = make_searcher(tmp_path, monkeypatch)
    chunk_searcher.set_config(1.6, 0.8)
    chunk_searcher.warmup()
    assert built[0].bm25 == (1.6, 0.8)


# ---------------------------------------------------------------------------
# The sequential-config rule (PLAN R9)
# ---------------------------------------------------------------------------
def test_set_config_refuses_while_a_batch_search_is_in_flight(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The one concurrency rule, enforced rather than documented (PLAN R9).

    `set_bm25` swaps a mutable `Similarity` on the shared Java searcher, so a
    flip during a batch scores some of that batch under the old config and some
    under the new one. The resulting run file is perfectly well-formed and wrong,
    and no downstream check could tell — which is why this raises instead of
    trusting a comment.
    """
    chunk_searcher, built = make_searcher(
        tmp_path, monkeypatch, rankings={q("t1", "alpha").qkey: ["c1"]})
    chunk_searcher.set_config(0.9, 0.4)
    chunk_searcher.warmup()
    raised: list[Exception] = []

    def reenter() -> None:
        try:
            chunk_searcher.set_config(1.2, 0.75)
        except RuntimeError as exc:
            raised.append(exc)

    built[0].on_search = reenter
    chunk_searcher.run_config([q("t1", "alpha")], k=1)
    assert raised and "in flight" in str(raised[0])
    # The config that was actually used is unchanged.
    assert chunk_searcher.config == (0.9, 0.4)


def test_the_in_flight_flag_clears_after_a_search_so_the_next_config_applies(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must not latch — the sweep flips configs 26 times in a row.

    A flag set on entry and never cleared (or cleared only on success) would make
    the second grid cell raise, turning the safety check into a sweep-stopper. So
    it is cleared in a `finally`, and this pins that a search *failure* does not
    wedge the searcher either.
    """
    chunk_searcher, built = make_searcher(
        tmp_path, monkeypatch, rankings={q("t1", "alpha").qkey: ["c1"]})
    chunk_searcher.set_config(0.9, 0.4)
    chunk_searcher.run_config([q("t1", "alpha")], k=1)
    chunk_searcher.set_config(1.2, 0.75)
    assert built[0].bm25 == (1.2, 0.75)

    def boom() -> None:
        raise RuntimeError("JVM exploded")

    built[0].on_search = boom
    with pytest.raises(RuntimeError, match="JVM exploded"):
        chunk_searcher.run_config([q("t1", "alpha")], k=1)
    chunk_searcher.set_config(0.5, 0.2)  # must not raise
    assert built[0].bm25 == (0.5, 0.2)


def test_run_config_without_a_config_refuses(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Searching before `set_config` would mislabel the run file.

    pyserini defaults to k1=0.9/b=0.4, so the ranking would be *valid* — just
    attributed to whatever cell the caller thought it had selected. Silently
    producing the baseline's numbers under another cell's filename is the kind of
    error that survives all the way into a published score matrix.
    """
    chunk_searcher, _ = make_searcher(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="before set_config"):
        chunk_searcher.run_config([q("t1", "alpha")], k=1)


# ---------------------------------------------------------------------------
# Warmup
# ---------------------------------------------------------------------------
def test_warmup_runs_a_throwaway_batch_once_and_is_logged(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """The 9.4 s cold start is paid before timing, and labelled `[WARMUP]`.

    Two failures this prevents. Without warmup, the first cell's wall time is ~7x
    the rest and reads as a regression in the log an operator is watching. Without
    idempotence, a resumed sweep pays the throwaway batch again on every call.
    """
    import logging

    chunk_searcher, built = make_searcher(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO):
        first = chunk_searcher.warmup()
        second = chunk_searcher.warmup()
    assert second == first
    searches = [e for e in built[0].events if e.startswith("batch_search")]
    assert len(searches) == 1
    assert "[WARMUP]" in caplog.text
    assert "9.4s measured" in caplog.text


def test_warmup_does_not_disturb_the_selected_config(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Warmup must not reset the scoring function it warms.

    A warmup that called `set_bm25` itself (to "be deterministic", say) would
    silently override the cell the sweep just selected — and because the
    throwaway queries are discarded, the only visible symptom would be a run file
    scored under the wrong config.
    """
    chunk_searcher, built = make_searcher(tmp_path, monkeypatch)
    chunk_searcher.set_config(*BASELINE_CONFIG)
    chunk_searcher.warmup()
    assert chunk_searcher.config == BASELINE_CONFIG
    assert built[0].bm25 == BASELINE_CONFIG


# ---------------------------------------------------------------------------
# run_config
# ---------------------------------------------------------------------------
def test_run_config_returns_chunk_ids_and_scores_keyed_by_qkey(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The return shape is what the run-file writer and the pool both consume.

    `qkey -> [(chunk_id, score)]` with pyserini's `docid`/`score` already
    unwrapped: everything downstream is stdlib-only and must never see a Java
    object, which is what lets `pool.py` and `metrics.py` be tested with no JVM.
    """
    alpha, beta = q("t1", "alpha"), q("t1", "beta")
    chunk_searcher, _ = make_searcher(
        tmp_path, monkeypatch,
        rankings={alpha.qkey: ["c1", "c2", "c3"], beta.qkey: ["c9"]})
    chunk_searcher.set_config(*BASELINE_CONFIG)
    out = chunk_searcher.run_config([alpha, beta], k=3)
    assert set(out) == {alpha.qkey, beta.qkey}
    assert all(isinstance(cid, str) and isinstance(score, float)
               for cid, score in out[alpha.qkey])
    assert len(out[alpha.qkey]) == 3
    assert out[beta.qkey] == [("c9", 1.0)]


def test_run_config_batches_so_progress_is_visible(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Queries go out in batches, each logged — that is the progress signal.

    A single `batch_search` over 1063 queries is one opaque 80-second call; the
    batch size *is* the heartbeat granularity for the search stage (PLAN §5.2).
    A regression to one big call would leave an operator with no way to tell a
    slow sweep from a hung one.
    """
    import logging

    queries = [q("t1", f"query {i}") for i in range(10)]
    chunk_searcher, built = make_searcher(
        tmp_path, monkeypatch, batch_size=4,
        rankings={rec.qkey: ["c1"] for rec in queries})
    chunk_searcher.set_config(0.7, 0.35)
    with caplog.at_level(logging.INFO):
        out = chunk_searcher.run_config(queries, k=1)
    assert len(out) == 10
    batch_sizes = [len(qids) for _cfg, qids in built[0].calls
                   if not qids[0].startswith("warmup")]
    assert batch_sizes == [4, 4, 2]
    assert "[SEARCH] k1=0.7 b=0.35 done 10q" in caplog.text


def test_every_query_of_a_batch_is_scored_under_one_config(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Batching must not interleave configs — that is the R9 failure mode.

    The fake records the live `(k1, b)` at each `batch_search`, so this asserts
    the property that actually matters: within one `run_config` call every batch
    saw the same config, and different `run_config` calls saw different ones.
    """
    queries = [q("t1", f"query {i}") for i in range(9)]
    chunk_searcher, built = make_searcher(
        tmp_path, monkeypatch, batch_size=2,
        rankings={rec.qkey: ["c1"] for rec in queries})
    for cell in [(0.5, 0.2), (1.6, 0.8)]:
        chunk_searcher.set_config(*cell)
        chunk_searcher.run_config(queries, k=1)
    real = [cfg for cfg, qids in built[0].calls
            if not qids[0].startswith("warmup")]
    assert set(real[:5]) == {(0.5, 0.2)}
    assert set(real[5:]) == {(1.6, 0.8)}


def test_duplicate_qkeys_are_rejected_rather_than_silently_collapsed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two queries sharing a qkey would lose a ranking with no error anywhere.

    `batch_search` returns a dict keyed by qid, so a duplicate key overwrites:
    the run file would be short by a query, every per-query mean would be
    computed over a different denominator than the manifest claims, and nothing
    would log a warning.
    """
    dup = q("t1", "alpha")
    chunk_searcher, _ = make_searcher(tmp_path, monkeypatch,
                                      rankings={dup.qkey: ["c1"]})
    chunk_searcher.set_config(*BASELINE_CONFIG)
    with pytest.raises(ValueError, match="duplicate qkeys"):
        chunk_searcher.run_config([dup, dup], k=1)


def test_different_configs_produce_different_rankings_in_the_fake(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake reorders on `set_bm25`, so downstream tests aren't vacuous.

    **[measured]** the real index's top-10 overlap with the baseline drops to
    0.72 at k1=1.2/b=0.75. If the fake returned one fixed ranking, every pooling
    and grid test would pass against a searcher that ignores its config entirely
    — the exact bug those tests are supposed to catch.
    """
    alpha = q("t1", "alpha")
    chunk_searcher, _ = make_searcher(
        tmp_path, monkeypatch,
        rankings={alpha.qkey: ["c1", "c2", "c3", "c4"]})
    seen = set()
    for cell in [(0.5, 0.2), (0.9, 0.4), (1.6, 0.8)]:
        chunk_searcher.set_config(*cell)
        out = chunk_searcher.run_config([alpha], k=2)
        seen.add(tuple(cid for cid, _ in out[alpha.qkey]))
    assert len(seen) > 1, f"config had no effect on the fake's ranking: {seen}"


# ---------------------------------------------------------------------------
# fetch_texts
# ---------------------------------------------------------------------------
def test_fetch_texts_uses_contents_because_raw_is_unusable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`.raw()` is None on this index (**[measured]**); `contents()` is the field.

    The fake's `raw()` returns None deliberately. A `.raw()`-based implementation
    would send the judge empty passages, every one would be graded 0, and the
    sweep would still produce a complete, plausible, meaningless score matrix.
    """
    chunk_searcher, _ = make_searcher(
        tmp_path, monkeypatch, texts={"c1": "the stored chunk text"})
    assert chunk_searcher.fetch_texts(["c1"]) == {"c1": "the stored chunk text"}


def test_fetch_texts_strips_the_leaked_page_header(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pool text is header-stripped before it can reach the judge (PLAN §2.1).

    Chunks fetched from the index carry no `prefix_chars`, so the regex branch is
    the only defence here. The header contains the document *title* — topical
    words that would inflate grades in a way no downstream metric could detect.
    """
    chunk_searcher, _ = make_searcher(
        tmp_path, monkeypatch,
        texts={"c1": "Page 3 of document: Library Budgets 2024\n\nreal text"})
    assert chunk_searcher.fetch_texts(["c1"]) == {"c1": "real text"}
    unstripped = chunk_searcher.fetch_texts(["c1"], strip_prefix=False)
    assert unstripped["c1"].startswith("Page 3 of document:")


def test_fetch_texts_omits_missing_ids_and_warns(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A chunk id with no document is omitted, not mapped to an empty string.

    "absent from the index" and "present but empty" need different handling —
    judging an empty passage bills a call to learn nothing — so they must be
    distinguishable to the caller, and the miss count has to reach the log rather
    than be inferred from a length difference nobody checks.
    """
    import logging

    chunk_searcher, _ = make_searcher(tmp_path, monkeypatch,
                                      texts={"c1": "present"})
    with caplog.at_level(logging.INFO):
        out = chunk_searcher.fetch_texts(["c1", "c-missing"])
    assert out == {"c1": "present"}
    assert "returned no document" in caplog.text


def test_fetch_texts_dedupes_ids(tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """A chunk pooled by several configs must be read from disk once.

    The stored-fields file is ~1 TB, so each fetch is a real disk seek; a chunk
    that 26 configs all retrieved would otherwise be read 26 times. Pool
    construction naturally produces those duplicates, so dedupe belongs here
    rather than in every caller.
    """
    chunk_searcher, built = make_searcher(tmp_path, monkeypatch,
                                          texts={"c1": "x"})
    chunk_searcher.fetch_texts(["c1", "c1", "c1"])
    assert [e for e in built[0].events if e.startswith("doc(")] == ["doc(c1)"]


def test_close_releases_the_index_handle(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`close()` must reach the underlying searcher, and stay safe when unopened.

    The sweep holds a 1.5 TB mmap; a driver that runs several stages in one
    process needs a deterministic point where the handle goes away. Calling it on
    a never-opened searcher must be a no-op, since the sweep's `finally` block
    runs even when `_open()` was the thing that failed.
    """
    chunk_searcher, built = make_searcher(tmp_path, monkeypatch)
    ChunkSearcher(tmp_path / "nope").close()  # no-op, no exception
    chunk_searcher.warmup()
    chunk_searcher.close()
    assert built[0].closed is True


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------
def test_stage_a_grid_is_the_plans_26_cells_including_the_baseline() -> None:
    """5x5 plus `(0.9, 0.4)` = 26 (PLAN §6.1).

    The baseline is *not* on the b-axis (`0.4` is absent from `GRID_B`), so it has
    to be appended explicitly — and it is the config the production server used,
    the one every candidate is tested against. Dropping it would leave the sweep
    with nothing to compare to.
    """
    grid = stage_a_grid()
    assert len(grid) == 26
    assert len(set(grid)) == 26
    assert BASELINE_CONFIG in grid
    assert BASELINE_CONFIG == (0.9, 0.4)
    assert grid[:2] == [(0.5, 0.2), (0.5, 0.35)]
    assert set(searcher_mod.GRID_K1) == {0.5, 0.7, 0.9, 1.2, 1.6}
    assert set(searcher_mod.GRID_B) == {0.2, 0.35, 0.5, 0.65, 0.8}


def test_stage_a_grid_order_is_stable() -> None:
    """Grid order fixes `first_seen_config` in `pool.jsonl`.

    Pool provenance is only reproducible if the cells are visited in the same
    order every time; an order that depended on set iteration would make the
    committed pool file differ between runs of identical code.
    """
    assert stage_a_grid() == stage_a_grid()


@pytest.mark.parametrize(("value", "expected"), [
    (0.9, "0.9"), (0.35, "0.35"), (1.6, "1.6"), (0.2, "0.2"), (1.0, "1"),
])
def test_config_names_are_the_numbers_a_human_typed(value: float,
                                                    expected: str) -> None:
    """`format_param` keeps run-file names greppable against the log.

    The config key is simultaneously the run-file stem, the TREC run tag, the
    score-matrix row label, and part of every `[SEARCH]` line. A fixed-precision
    format (`0.900000`) would make a published score table's rows unfindable in
    the sweep log they came from.
    """
    assert format_param(value) == expected


def test_config_key_and_run_file_name_agree() -> None:
    """One cell, one name, everywhere (PLAN §4.2's `k1_<k1>__b_<b>.txt`).

    `search-sweep`'s idempotence is "skip the config whose run file exists", so a
    mismatch between the name used to write and the name used to check would make
    every resumed sweep re-search everything — or worse, write a second file for
    a cell that already had one.
    """
    assert config_key(0.9, 0.4) == "k1_0.9__b_0.4"
    assert run_file_name(0.9, 0.4) == "k1_0.9__b_0.4.txt"
    assert run_file_name(1.2, 0.75) == f"{config_key(1.2, 0.75)}.txt"


@pytest.mark.parametrize("tokens", [
    ["0.9:0.4,1.2:0.75"], ["0.9:0.4", "1.2:0.75"], ["0.9/0.4 1.2/0.75"],
])
def test_parse_configs_accepts_the_forms_a_launch_command_uses(
        tokens: list[str]) -> None:
    """Stage B's cells arrive on the command line, however the operator types them.

    Which three cells Stage B confirms is only known after Stage A is scored, so
    they cannot be a constant — they are pasted into a launch command that goes
    verbatim into the worklog. Accepting comma- and space-separated forms means
    the recorded command works as written.
    """
    assert parse_configs(tokens) == [(0.9, 0.4), (1.2, 0.75)]


def test_parse_configs_collapses_duplicates_preserving_order() -> None:
    """A repeated cell would re-search and overwrite its own run file.

    Easy to type when Stage B's top-3 list happens to already contain the
    baseline — and the second pass would look like a successful config while
    quietly doubling the search time.
    """
    assert parse_configs(["0.9:0.4,1.2:0.5,0.9:0.4"]) == [(0.9, 0.4),
                                                          (1.2, 0.5)]


@pytest.mark.parametrize("bad", [["0.9"], ["0.9:0.4:0.5"], ["abc:0.4"], [""]])
def test_parse_configs_rejects_malformed_cells(bad: list[str]) -> None:
    """A typo'd cell must fail at parse time, before any searching.

    The alternative is a sweep that runs for twenty minutes and then writes a run
    file named after a config it did not use, or one that silently sweeps a
    shorter grid than the manifest records.
    """
    with pytest.raises(ValueError):
        parse_configs(bad)


# ---------------------------------------------------------------------------
# search-sweep, end to end over the fake index
# ---------------------------------------------------------------------------
@pytest.fixture
def sweep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
          bm25_config: object):
    """A callable running `cmd_search_sweep` against the fake index.

    Patches `ChunkSearcher._import_lucene_searcher` at class level (the sweep
    constructs its own searcher, so a per-instance patch cannot reach it) and
    writes a real `keyword-1063.jsonl` so the loader's own path is exercised
    rather than bypassed. Returns `(exit_code, run_dir)`.
    """
    from bm25tune import cli
    from bm25tune.extract import write_query_file

    queries = [q("rag2026-900", "library budget"),
               q("rag2026-900", "reference desk staffing"),
               q("rag2026-901", "soil moisture sensors")]
    write_query_file(bm25_config.queries_dir / cli.QUERIES_FULL_BASENAME,
                     queries)
    index_dir = tmp_path / "index"
    index_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("BM25_TUNE_INDEX_DIR", str(index_dir))

    rankings = {rec.qkey: [f"c{i}" for i in range(6)] for rec in queries}
    texts = {f"c{i}": f"passage text {i}" for i in range(6)}
    built: list[FakeLuceneSearcher] = []

    def factory(path: str) -> FakeLuceneSearcher:
        fake = FakeLuceneSearcher(path, rankings=rankings, texts=texts)
        built.append(fake)
        return fake

    monkeypatch.setattr(ChunkSearcher, "_import_lucene_searcher",
                        lambda self: factory)

    def run(*argv: str) -> tuple[int, Path]:
        code = cli.main(["search-sweep", *argv])
        return code, bm25_config.run_dir("t")

    run.built = built  # type: ignore[attr-defined]
    run.queries = queries  # type: ignore[attr-defined]
    return run


def test_a_sweep_writes_one_run_file_per_cell_plus_the_pool(sweep) -> None:
    """The artifact set `judge-pool` and `score` both depend on existing.

    A sweep that searched successfully but wrote the run files under a different
    name, or skipped `pool.jsonl`, fails only later — in the metered stage, after
    the cheap one already reported success.
    """
    code, run_dir = sweep("--stage", "B", "--run-id", "t",
                          "--configs", "0.5:0.2,1.6:0.8", "--depth", "3")
    assert code == 0
    assert sorted(p.name for p in (run_dir / "trecruns").iterdir()) == [
        "k1_0.5__b_0.2.txt", "k1_1.6__b_0.8.txt"]
    assert (run_dir / "pool.jsonl").is_file()
    assert (run_dir / "pool-texts.jsonl").is_file()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "sweep.log").is_file()


def test_the_pool_unions_both_configs_hits(sweep) -> None:
    """The sweep's own pool must span the grid, not just the last cell.

    This is the integration half of `test_pool.py`'s unit tests: the fake
    reorders on config change, so a sweep that overwrote `rankings[key]` instead
    of accumulating would produce a pool of exactly one config's depth — a
    plausible size, and a qrel that cannot fairly score the others.
    """
    from bm25tune.pool import read_pool

    _code, run_dir = sweep("--stage", "B", "--run-id", "t",
                           "--configs", "0.5:0.2,1.6:0.8", "--depth", "3")
    entries = read_pool(run_dir / "pool.jsonl")
    seen_configs = {e.first_seen_config for e in entries}
    assert seen_configs == {"k1_0.5__b_0.2", "k1_1.6__b_0.8"}
    assert {e.topic_id for e in entries} == {"rag2026-900", "rag2026-901"}


def test_a_fully_resumed_sweep_never_opens_the_index_at_all(sweep) -> None:
    """Resumption is "re-run the same command", and it must cost nothing.

    The 26-cell sweep takes ~21 minutes and can be interrupted; the recovery
    procedure is to re-issue the command. A resumed run has nothing to search and
    (after the incremental-text fix) nothing to fetch, so it must not pay the
    9.4 s cold start or touch the 1.5 TB mmap either — the whole point of
    deferring `warmup()` to the first cell that actually searches.

    Asserted via the factory's call list: a *constructed* `ChunkSearcher` is free,
    an *opened* one is not.
    """
    args = ("--stage", "B", "--run-id", "t", "--configs", "0.5:0.2,1.6:0.8",
            "--depth", "3")
    sweep(*args)
    opened_after_first = len(sweep.built)
    code, _run_dir = sweep(*args)
    assert code == 0
    assert len(sweep.built) == opened_after_first == 1


def test_a_resumed_sweep_builds_the_same_pool_from_the_run_files(
        sweep) -> None:
    """Skipped cells still have to contribute to the pool.

    The subtle bug idempotence invites: skip the search *and* the ranking, and the
    resumed run writes a pool missing every completed config. It would look like a
    successful, cheaper sweep, and the qrel would silently under-cover exactly the
    configs that had already finished.
    """
    from bm25tune.pool import read_pool

    args = ("--stage", "B", "--run-id", "t", "--configs", "0.5:0.2,1.6:0.8",
            "--depth", "3")
    _code, run_dir = sweep(*args)
    first = {e.key for e in read_pool(run_dir / "pool.jsonl")}
    sweep(*args)
    assert {e.key for e in read_pool(run_dir / "pool.jsonl")} == first


def test_a_resumed_sweep_does_not_null_out_the_manifests_provenance(
        sweep) -> None:
    """A resumed run knows less than the original; it must not overwrite with less.

    Observed for real during the WP2 plumbing check: the second invocation never
    opens the index, so `index_num_docs` was `None` and `warmup_s` `0.0`, and the
    merge wrote both — destroying the only record of which corpus the run files
    were produced against. Unmeasured fields are now omitted, and `created_utc`
    keeps saying when the run started.
    """
    import json

    args = ("--stage", "B", "--run-id", "t", "--configs", "0.5:0.2",
            "--depth", "3")
    _code, run_dir = sweep(*args)
    before = json.loads((run_dir / "manifest.json").read_text())
    assert before["index_num_docs"] == EXPECTED_NUM_DOCS
    sweep(*args)
    after = json.loads((run_dir / "manifest.json").read_text())
    assert after["index_num_docs"] == EXPECTED_NUM_DOCS
    assert after["created_utc"] == before["created_utc"]
    assert after["configs_skipped"] == 1


def test_no_fetch_texts_reuses_the_passages_already_on_disk(sweep) -> None:
    """`--no-fetch-texts` must not blank `pool.jsonl`'s digests.

    Also observed live: skipping the index read left `texts=None`, so every
    `text_sha256` was rewritten as `null` — silently disarming the check that a
    cached judgment refers to the passage still on disk. The digests are now
    re-derived from the existing `pool-texts.jsonl`.
    """
    from bm25tune.pool import read_pool

    args = ("--stage", "B", "--run-id", "t", "--configs", "0.5:0.2",
            "--depth", "3")
    _code, run_dir = sweep(*args)
    before = {e.chunk_id: e.text_sha256
              for e in read_pool(run_dir / "pool.jsonl")}
    assert all(before.values())
    sweep(*args, "--no-fetch-texts")
    after = {e.chunk_id: e.text_sha256
             for e in read_pool(run_dir / "pool.jsonl")}
    assert after == before


def test_only_newly_pooled_passages_are_fetched_on_a_widened_sweep(
        sweep) -> None:
    """Adding a config re-reads only the chunks it newly contributed.

    The realistic resume: Stage A dies partway, or a cell is added afterwards.
    Each fetch is a real seek into a ~1 TB stored-fields file, so re-reading the
    whole pool to add a handful of chunks is the difference between seconds and
    minutes — and the fake's per-id `doc()` calls make the waste visible.
    """
    base = ("--stage", "B", "--run-id", "t", "--depth", "3")
    sweep(*base, "--configs", "0.5:0.2")
    first_fetches = [e for e in sweep.built[0].events if e.startswith("doc(")]
    assert first_fetches
    sweep(*base, "--configs", "0.5:0.2,1.6:0.8")
    later_fetches = [e for e in sweep.built[1].events if e.startswith("doc(")]
    # The second config contributes strictly fewer new chunks than the pool size.
    assert 0 < len(later_fetches) < len(first_fetches)


def test_force_re_searches_a_cell_that_already_has_a_run_file(sweep) -> None:
    """`--force` is the escape hatch for a run file written by broken code.

    Without it, a cell whose run file exists can never be corrected in place, and
    an operator's only recourse is deleting artifacts by hand — which is exactly
    what `--fresh`'s rename-never-delete rule exists to avoid.
    """
    args = ("--stage", "B", "--run-id", "t", "--configs", "0.5:0.2",
            "--depth", "3")
    sweep(*args)
    before = len(sweep.built[0].calls)
    code, _run_dir = sweep(*args, "--force")
    assert code == 0
    assert len(sweep.built[1].calls) > 0
    assert before > 0


def test_stage_b_without_configs_refuses_rather_than_sweeping_26_cells(
        sweep) -> None:
    """Stage B's cells come from Stage A's scores; there is no safe default.

    Defaulting to the full grid would turn a 4-config confirmatory run over 1063
    queries into a 26-config one — inflating the judged pool (and the bill) by
    roughly the ratio of the grids, from a command that looked like a typo-free
    omission.
    """
    from bm25tune.cli import EXIT_ERROR

    code, _run_dir = sweep("--stage", "B", "--run-id", "t")
    assert code == EXIT_ERROR


def test_fresh_renames_the_old_run_dir_instead_of_deleting_it(sweep) -> None:
    """PLAN §5.8: derived artifacts are superseded, never destroyed.

    The old run dir holds the `sweep.log` that may be the only surviving evidence
    behind an earlier judgment call, so `--fresh` moves it aside under a
    timestamped name and says so.
    """
    args = ("--stage", "B", "--run-id", "t", "--configs", "0.5:0.2",
            "--depth", "3")
    _code, run_dir = sweep(*args)
    sweep(*args, "--fresh")
    superseded = [p for p in run_dir.parent.iterdir()
                  if p.name.startswith("t.superseded-")]
    assert len(superseded) == 1
    assert (superseded[0] / "trecruns").is_dir()


def test_a_sweep_run_id_pointing_at_the_judgment_log_is_refused(
        sweep, bm25_config: object) -> None:
    """`--fresh` must never be able to rename the append-only audit records.

    The judgment log is the ground truth for both the qrels and the spend, so a
    path-traversal `--run-id` reaching it would destroy already-paid-for work and
    make cost reconciliation unfalsifiable. Resolved paths are compared, so this
    crafted id is caught (PLAN §5.8).
    """
    from bm25tune.cli import EXIT_ERROR

    relative = "../judgments/log"
    code, _run_dir = sweep("--stage", "B", "--run-id", relative,
                           "--configs", "0.5:0.2", "--fresh")
    assert code == EXIT_ERROR
    assert not (bm25_config.log_dir / "trecruns").exists()
