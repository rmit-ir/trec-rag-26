"""BM25 retrieval over the chunked ClimbMix Lucene index (PLAN §5.2, §6.1).

What this module owns: **one** `LuceneSearcher` for an entire sweep, and the
grid of `(k1, b)` cells that searcher is flipped through.

Three constraints shape every line here, all of them **[measured]** (PLAN §1):

1. **`pyserini` is imported inside `_open()`, never at module scope.** The whole
   `tests/bm25_tune/` suite runs in the repo-root env with no JVM and no
   `pyserini` installed; a module-scope import would force an `importorskip`,
   and a skipped test is a test that proves nothing (PLAN §4.1/§7.3). The seam
   the tests use is `_import_lucene_searcher()`, so `_open()`'s real logic —
   fail-fast on the index dir, the `num_docs` assertion, the pending-config
   apply — is exercised hermetically against a fake class.
2. **Search is cheap; do not parallelize it in Python.** `batch_search(20, k=30,
   threads=16)` costs 9.4 s on the first call (JVM warmup + mmap faulting) and
   1.3–1.6 s after — ~13 queries/s. The full 26-cell × 1063-query sweep is
   ~21 minutes. Judging costs 2–3 orders of magnitude more, so all engineering
   effort belongs there: one process, one searcher, `threads=16` inside a config.
3. **Configs are applied strictly sequentially.** `set_bm25` mutates a shared
   `Similarity` on the live Java object; flipping it while a `batch_search` is in
   flight would silently score part of a batch under the wrong config, producing
   a run file that no amount of downstream checking could detect as wrong
   (PLAN R9). `set_config` therefore *raises* if a search is in progress rather
   than trusting the caller to read a comment.

The index itself is read-only under another user's home (PLAN R7), addressed
only through `BM25_TUNE_INDEX_DIR`, and its chunk count is asserted on open so a
moved or rebuilt index cannot silently change what the experiment measured.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from .extract import QueryRec, strip_page_prefix
from .logging_setup import get_logger

log = get_logger("searcher")

#: **[measured]** chunk count of `climbmix-bm25-chunked`. Asserted on open, and
#: recorded in the run manifest, because a different number means a different
#: corpus — which would invalidate every cached judgment keyed on a chunk id
#: (PLAN R7).
EXPECTED_NUM_DOCS = 921_892_634

#: Retrieval depth per config. Metric is nDCG@10, so 30 leaves 3x headroom for
#: rank movement between configs while pool inflation stays modest (PLAN §5.5).
DEFAULT_DEPTH = 30

#: Threads handed to `batch_search`. The JVM does the fan-out, so the GIL is
#: irrelevant; **[measured]** 16 sustains ~13 queries/s.
DEFAULT_THREADS = 16

#: Queries per `batch_search` call. Smaller than the query set on purpose: the
#: call is synchronous and opaque, so the batch size *is* the progress
#: granularity an operator watching `tail -f` gets (PLAN §5.2).
BATCH_SIZE = 64

#: pyserini's default, and **[measured]** score-identical to the hosted
#: production server aus_agent actually queried — hence the baseline to beat.
BASELINE_CONFIG: tuple[float, float] = (0.9, 0.4)

#: PLAN §6.1's 5x5 coarse grid. Extends two steps below the pyserini default on
#: both axes (chunks are length-controlled, so low `b`/low `k1` is the plausible
#: winning direction) while still covering Lucene's 1.2/0.75 corner region.
GRID_K1: tuple[float, ...] = (0.5, 0.7, 0.9, 1.2, 1.6)
GRID_B: tuple[float, ...] = (0.2, 0.35, 0.5, 0.65, 0.8)

#: Throwaway queries for `warmup()`. Deliberately generic English so the call
#: touches ordinary postings lists rather than a rare-term shortcut — the point
#: is to pay the JVM/mmap cold cost, not to be fast.
WARMUP_QUERIES: tuple[str, ...] = (
    "public library reference services budget",
    "soil moisture irrigation scheduling",
    "workplace training and development policy",
)


class SearcherError(RuntimeError):
    """The index could not be opened, or is not the index we expect.

    Distinct from `ConfigError` (which covers an unset/unreadable env var) so
    "the path is wrong" and "the path is right but holds a different corpus" get
    different messages — the second is the dangerous one (PLAN R7).
    """


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------
def format_param(value: float) -> str:
    """`0.9 -> "0.9"`, `0.35 -> "0.35"`, `1.6 -> "1.6"`.

    `%g` rather than a fixed precision so a config key is the number a human
    typed, not `0.900000`. Run-file names, TREC run tags, score-table rows and
    log lines all derive from this one function, so the grid cell in a published
    score matrix is greppable in the sweep log.
    """
    return f"{float(value):g}"


def config_key(k1: float, b: float) -> str:
    """The canonical name of one grid cell: `k1_0.9__b_0.4`.

    Doubles as the run-file stem (PLAN §4.2), the TREC run tag, and the key of
    the `runs` dict `pool.build_pool` consumes — one string, so a run file can
    never be attributed to the wrong config.
    """
    return f"k1_{format_param(k1)}__b_{format_param(b)}"


def run_file_name(k1: float, b: float) -> str:
    """`trecruns/` basename for a cell (PLAN §4.2's `k1_<k1>__b_<b>.txt`)."""
    return f"{config_key(k1, b)}.txt"


def stage_a_grid() -> list[tuple[float, float]]:
    """PLAN §6.1's 26 cells: the 5x5 grid plus the `(0.9, 0.4)` baseline.

    The baseline is appended rather than folded into the axes because `b=0.4` is
    not one of the five `b` values — it is pyserini's default and the config
    aus_agent's production runs used, so it must be swept even though the grid
    would otherwise skip it. Order is stable (k1-major) so `first_seen_config`
    in the pool file is reproducible across re-runs.
    """
    cells = [(k1, b) for k1 in GRID_K1 for b in GRID_B]
    if BASELINE_CONFIG not in cells:
        cells.append(BASELINE_CONFIG)
    return cells


def parse_configs(tokens: Sequence[str]) -> list[tuple[float, float]]:
    """Parse `--configs 0.9:0.4,1.2:0.75` (or space-separated) into cells.

    Stage B sweeps the top-3 Stage-A cells plus the baseline, and *which* three
    is only known after Stage A is scored — so the cells have to be nameable on
    the command line. Duplicates are collapsed while preserving order, because a
    repeated cell would otherwise re-search and overwrite its own run file.

    Cells may be separated by commas, whitespace, or separate argv items (all
    three appear in launch commands pasted from a worklog); the two numbers of a
    cell are separated by `:` or `/`. Splitting cells first and *then* the pair
    keeps `"0.9/0.4 1.2/0.75"` unambiguous.
    """
    cells: list[tuple[float, float]] = []
    for token in tokens:
        for item in str(token).replace(",", " ").split():
            parts = item.replace(":", " ").replace("/", " ").split()
            if len(parts) != 2:
                raise ValueError(
                    f"--configs expects k1:b pairs, got {item!r} "
                    "(e.g. --configs 0.9:0.4,1.2:0.75)")
            try:
                cell = (float(parts[0]), float(parts[1]))
            except ValueError as exc:
                raise ValueError(
                    f"--configs {item!r}: k1 and b must be numbers") from exc
            if cell not in cells:
                cells.append(cell)
    if not cells:
        raise ValueError("--configs was given no k1:b pair")
    return cells


# ---------------------------------------------------------------------------
# The searcher
# ---------------------------------------------------------------------------
class ChunkSearcher:
    """One `LuceneSearcher` over the chunked index, flipped through the grid.

    **Never flip the config while a search is in flight.** `set_bm25` replaces a
    mutable `Similarity` on the shared Java `SimpleSearcher`, so a `set_config`
    call racing a `batch_search` would score some queries of the batch under the
    old config and some under the new one — a run file that looks perfectly
    well-formed and is wrong. **[measured]** flipping *between* batches on one
    live instance is safe and produces distinct, self-consistent rankings for six
    configs in a row (PLAN §1/R9). Parallelism belongs *inside* a config, via
    `batch_search(threads=...)`.

    That rule is enforced, not merely documented: `run_config` sets an in-flight
    flag and `set_config` raises `RuntimeError` while it is set.

    Lazy by construction — `__init__` touches neither the filesystem nor the JVM,
    so constructing one costs nothing and a subcommand that never searches never
    pays the 9.4 s cold start.
    """

    def __init__(self, index_dir: str | Path, threads: int = DEFAULT_THREADS,
                 *, batch_size: int = BATCH_SIZE,
                 expected_num_docs: int | None = EXPECTED_NUM_DOCS) -> None:
        self.index_dir = Path(index_dir)
        self.threads = int(threads)
        self.batch_size = max(int(batch_size), 1)
        self.expected_num_docs = expected_num_docs
        self.num_docs: int | None = None
        self._searcher: Any | None = None
        self._config: tuple[float, float] | None = None
        self._searching = False
        self._warmed = False
        self.open_seconds = 0.0
        self.warmup_seconds = 0.0

    # -- opening ------------------------------------------------------------
    def _import_lucene_searcher(self) -> Any:
        """Return `pyserini.search.lucene.LuceneSearcher`, imported *here*.

        The one place `pyserini` enters the process, and the seam the hermetic
        tests replace (PLAN §7.3). An `ImportError` here is almost always one of
        two operator mistakes — running under the repo-root env instead of
        `uv run --project tasks/bm25_tune`, or an unset `JAVA_HOME` — so it is
        translated into a message that names both rather than a bare traceback.
        """
        try:
            from pyserini.search.lucene import LuceneSearcher
        except Exception as exc:  # ImportError, or a JVM startup failure
            raise SearcherError(
                "could not import pyserini.search.lucene. Run under the task "
                "env and with JDK 21 on JAVA_HOME:\n"
                '  export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"\n'
                "  uv run --project tasks/bm25_tune python -m bm25tune ...\n"
                f"({type(exc).__name__}: {exc})") from exc
        return LuceneSearcher

    def _open(self) -> Any:
        """Open the index once, assert its identity, apply the pending config.

        Fails fast and loudly in three distinct ways, because the index is ~1.5 TB
        of another user's read-only home and every one of these has happened
        during development: the path does not exist, pyserini/JVM is unavailable,
        or the directory holds a *different* corpus than the experiment measured.
        The last is the one worth the assertion — a silently re-chunked index
        would make every cached judgment refer to text that is no longer there.
        """
        if self._searcher is not None:
            return self._searcher

        # Checked before the pyserini import so the common operator error gets
        # the actionable message even when the JVM is not available at all.
        if not self.index_dir.is_dir():
            raise SearcherError(
                f"index dir {self.index_dir} is not a directory — check "
                "BM25_TUNE_INDEX_DIR, and that the read-only mount under the "
                "owning user's home is present (PLAN R7)")

        lucene_searcher = self._import_lucene_searcher()
        started = time.monotonic()
        try:
            searcher = lucene_searcher(str(self.index_dir))
        except Exception as exc:
            raise SearcherError(
                f"failed to open Lucene index at {self.index_dir}: "
                f"{type(exc).__name__}: {exc}") from exc
        self.open_seconds = time.monotonic() - started

        num_docs = int(getattr(searcher, "num_docs", -1))
        self.num_docs = num_docs
        if (self.expected_num_docs is not None
                and num_docs != self.expected_num_docs):
            raise SearcherError(
                f"index at {self.index_dir} holds {num_docs} docs, expected "
                f"{self.expected_num_docs} — this is not the chunked ClimbMix "
                "index the experiment was measured against; STOP rather than "
                "updating the expectation (PLAN R7)")

        log.info("[LOAD] opened %s num_docs=%d in %.1fs threads=%d",
                 self.index_dir, num_docs, self.open_seconds, self.threads)
        self._searcher = searcher
        if self._config is not None:
            # A config set before the first search is applied here, so
            # `set_config` stays free of JVM startup cost.
            self._apply(*self._config)
        return searcher

    # -- config -------------------------------------------------------------
    def set_config(self, k1: float, b: float) -> None:
        """Select the BM25 cell for the *next* `run_config` call.

        Refuses while a search is in flight (see the class docstring): the
        alternative is a run file mixing two scoring functions with nothing
        downstream able to notice. If the index is not open yet the config is
        remembered and applied on open, which keeps `__init__` + `set_config`
        JVM-free and therefore unit-testable.
        """
        if self._searching:
            raise RuntimeError(
                "set_config called while a batch_search is in flight — the "
                "Similarity is shared mutable state on the Java searcher, so "
                "this would score part of the batch under the wrong config "
                "(PLAN §5.2/R9). Configs are strictly sequential.")
        self._config = (float(k1), float(b))
        if self._searcher is not None:
            self._apply(k1, b)

    def _apply(self, k1: float, b: float) -> None:
        self._searcher.set_bm25(float(k1), float(b))
        log.info("[SEARCH] config k1=%s b=%s", format_param(k1),
                 format_param(b))

    @property
    def config(self) -> tuple[float, float] | None:
        """The currently selected `(k1, b)`, or `None` before `set_config`."""
        return self._config

    # -- warmup -------------------------------------------------------------
    def warmup(self) -> float:
        """Pay the cold start once, before anything is timed. Returns seconds.

        **[measured]** the first `batch_search` costs 9.4 s (JVM class loading +
        mmap page faults on a 1.5 TB index) against 1.3–1.6 s for every call
        after it. Without this, the first grid cell's wall time is ~7x the rest
        and reads as a regression in the sweep log — so the cost is paid here and
        logged under `[WARMUP]`, which is the whole point of the method.

        Idempotent: repeated calls are no-ops, so a resumed sweep does not pay
        again, and warmup never disturbs the selected config (it searches under
        whatever `set_config` chose, and changes nothing).
        """
        if self._warmed:
            return self.warmup_seconds
        searcher = self._open()
        started = time.monotonic()
        self._searching = True
        try:
            searcher.batch_search(list(WARMUP_QUERIES),
                                  [f"warmup-{i}" for i in
                                   range(len(WARMUP_QUERIES))],
                                  k=DEFAULT_DEPTH, threads=self.threads)
        finally:
            self._searching = False
        self.warmup_seconds = time.monotonic() - started
        self._warmed = True
        log.info("[WARMUP] %d throwaway queries in %.1fs (cold start: JVM + "
                 "mmap faulting, ~9.4s measured — later configs are ~7x "
                 "faster, so do not read the first cell's time as a "
                 "regression)", len(WARMUP_QUERIES), self.warmup_seconds)
        return self.warmup_seconds

    # -- searching ----------------------------------------------------------
    def run_config(self, queries: Sequence[QueryRec],
                   k: int = DEFAULT_DEPTH) -> dict[str, list[tuple[str, float]]]:
        """Search every query at the current config. `qkey -> [(chunk_id, score)]`.

        Batched `self.batch_size` at a time purely for observability: one
        `batch_search` over 1063 queries would be a single 80-second opaque call,
        whereas 17 batches produce 17 progress lines an operator can watch.

        Duplicate `qkey`s are rejected rather than tolerated — pyserini returns a
        dict keyed by qid, so two queries sharing a key would silently collapse
        into one ranking and the run file would be short by a query with no error
        anywhere.
        """
        searcher = self._open()
        if self._config is None:
            raise RuntimeError(
                "run_config called before set_config — the scoring function "
                "would be whatever pyserini defaults to, and the run file would "
                "be labelled with a config it was not scored under")
        qkeys = [q.qkey for q in queries]
        if len(set(qkeys)) != len(qkeys):
            duplicates = sorted({key for key in qkeys if qkeys.count(key) > 1})
            raise ValueError(
                f"duplicate qkeys in the query set ({duplicates[:5]}); "
                "batch_search is keyed by qid, so these rankings would collapse")

        k1, b = self._config
        results: dict[str, list[tuple[str, float]]] = {}
        started = time.monotonic()
        total = len(queries)
        for offset in range(0, total, self.batch_size):
            batch = list(queries[offset:offset + self.batch_size])
            batch_started = time.monotonic()
            self._searching = True
            try:
                hits = searcher.batch_search(
                    [q.query for q in batch], [q.qkey for q in batch],
                    k=int(k), threads=self.threads)
            finally:
                self._searching = False
            for rec in batch:
                results[rec.qkey] = [
                    (str(hit.docid), float(hit.score))
                    for hit in (hits.get(rec.qkey) or [])]
            log.info("[SEARCH] k1=%s b=%s %d/%d in %.1fs",
                     format_param(k1), format_param(b),
                     min(offset + len(batch), total), total,
                     time.monotonic() - batch_started)
        elapsed = time.monotonic() - started
        retrieved = sum(len(v) for v in results.values())
        log.info("[SEARCH] k1=%s b=%s done %dq in %.1fs (%d hits, %.1f q/s)",
                 format_param(k1), format_param(b), total, elapsed, retrieved,
                 total / elapsed if elapsed else 0.0)
        return results

    # -- document text ------------------------------------------------------
    def fetch_texts(self, chunk_ids: Sequence[str], *,
                    strip_prefix: bool = True) -> dict[str, str]:
        """Stored text for pooled chunks. `chunk_id -> text`.

        Uses `doc(id).contents()`: **[measured]** `.raw()` is None/False on this
        index, so the obvious call returns nothing and a naive implementation
        would hand the judge empty passages — graded 0 across the board, with the
        sweep still producing a plausible-looking score matrix.

        `strip_prefix` removes a leaked `"Page N of document: <title>"` header
        (PLAN §5.1). It defaults to True because this method is the *only* way
        pool text enters the harness and PLAN §2.1 requires the judge to always
        receive stripped text; chunks fetched from the index carry no
        `prefix_chars`, so the regex branch is the one that fires. Misses are
        counted and logged, never silently assumed absent.

        Missing ids are **omitted** from the result rather than mapped to `""` —
        an empty passage and an absent chunk need different handling upstream,
        and a count of the misses is logged.
        """
        searcher = self._open()
        ids = list(dict.fromkeys(str(cid) for cid in chunk_ids))
        texts: dict[str, str] = {}
        missing: list[str] = []
        empty: list[str] = []
        stripped_count = 0
        started = time.monotonic()
        for offset in range(0, len(ids), self.batch_size):
            batch = ids[offset:offset + self.batch_size]
            for chunk_id, contents in self._fetch_batch(searcher, batch):
                if contents is None:
                    missing.append(chunk_id)
                    continue
                text = str(contents)
                if strip_prefix:
                    text, did_strip = strip_page_prefix(text, None)
                    stripped_count += int(did_strip)
                if not text.strip():
                    empty.append(chunk_id)
                texts[chunk_id] = text
        log.info("[SEARCH] fetch_texts %d/%d chunks in %.1fs "
                 "(stripped=%d missing=%d empty=%d)",
                 len(texts), len(ids), time.monotonic() - started,
                 stripped_count, len(missing), len(empty))
        if missing:
            log.warning("[SEARCH] %d pooled chunk ids returned no document "
                        "(first few: %s) — they are excluded from the pool "
                        "rather than judged as empty", len(missing),
                        missing[:5])
        if empty:
            log.warning("[SEARCH] %d chunks have empty contents (first few: "
                        "%s); `.raw()` is unusable on this index, so an empty "
                        "`contents` means the stored field is genuinely empty",
                        len(empty), empty[:5])
        return texts

    def _fetch_batch(self, searcher: Any,
                     chunk_ids: Sequence[str]) -> Iterable[tuple[str, Any]]:
        """Yield `(chunk_id, contents_or_None)` for a batch of ids.

        Prefers `batch_doc(ids, threads)` (the JVM fans the random reads out
        across threads — the stored-fields file is ~1 TB, so these are real disk
        seeks) and falls back to per-id `doc()` when the installed pyserini has
        no `batch_doc`, so a version bump degrades in speed rather than breaking.
        """
        batch_doc = getattr(searcher, "batch_doc", None)
        if callable(batch_doc):
            docs = batch_doc(list(chunk_ids), self.threads) or {}
            for chunk_id in chunk_ids:
                doc = docs.get(chunk_id)
                yield chunk_id, None if doc is None else doc.contents()
            return
        for chunk_id in chunk_ids:
            doc = searcher.doc(chunk_id)
            yield chunk_id, None if doc is None else doc.contents()

    # -- teardown -----------------------------------------------------------
    def close(self) -> None:
        """Close the underlying searcher if one was ever opened.

        Not required for correctness (the process exit releases the mmap) but it
        makes a long-lived driver — and a test that opens a fake — deterministic
        about when the index handle goes away.
        """
        searcher, self._searcher = self._searcher, None
        self._warmed = False
        if searcher is not None and hasattr(searcher, "close"):
            searcher.close()
