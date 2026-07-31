"""The three commands as one pipeline, and the four ways a paid run can stop.

`test_searcher.py`, `test_judge.py`, `test_metrics.py` and `test_pricing.py` each
pin one module against its own seam. Nothing there catches a mismatch *between*
them, and every such mismatch surfaces in the same place: the second, metered
invocation, after the free one already reported success. So this file drives
`cli.main` — real `argparse`, real `Config.from_env`, real log/cache/meter — with
exactly two fakes: the pyserini class (`_import_lucene_searcher`) and the Bedrock
transport (`converse`). No JVM, no boto3, no network, no spend.

What it defends, in order of what it costs to get wrong:

1. **Resume is free.** A credential expiry is the single most likely
   interruption of a multi-hour run, and "re-run the same command" is only
   correct if the second invocation re-judges *nothing*. That is asserted the
   only way it can be honestly asserted — by reading which passages the fake
   transport was actually asked about — rather than by trusting a cache-hit
   counter that could be counting the wrong thing.
2. **A budget stop costs no money twice.** Exit 5 mid-run must leave every
   already-billed judgment on disk, in the snapshot, and in the ledger, so the
   follow-up run with a raised cap pays only for the remainder.
3. **`--fresh` cannot destroy the audit record.** It renames derived artifacts
   and refuses outright when aimed at `judgments/log/` or `costs/` — the two
   directories in the experiment that cannot be regenerated (PLAN §5.8).
4. **One drain, four triggers.** cred expiry → `[CRED]` → 3, budget →
   `[BUDGET]` → 5, SIGINT → `[SIGNAL]` → 130, SIGTERM → `[SIGNAL]` → 143. Each
   is driven through `cli.main` here, so the exit code an operator (or a
   launching agent) branches on is the one this code path really returns. The
   signal handlers are invoked as functions — never raised as real signals,
   which pytest would not survive.

Everything runs against `bm25_config`'s tmp data dir, so no test can touch the
real `data/bm25-tune/`. The fake responses carry deliberately large `usage`
blocks (2000 in / 800 out) so a handful of calls can trip a cap that the
pre-flight — which is still working from the priors — happily approves: that
gap between estimate and reality is what makes a mid-run stop reachable at all,
and it is the situation layer 2 exists for (PLAN §5.7).
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import signal
from pathlib import Path
from typing import Callable

import pytest

from bm25tune import cli, extract, judge, metrics, pricing, store
from bm25tune.searcher import EXPECTED_NUM_DOCS, ChunkSearcher

PV = "facet-v1"
RUN_ID = "20260731T120000-stageB"
CONFIGS = "0.9:0.4,1.2:0.6"
DEPTH = 5
#: Candidates per query in the fake index. With `DEPTH` equal to it, the pooled
#: set is independent of the config-driven reordering, so the pool size is a
#: constant and the spend arithmetic below is exact.
CANDIDATES = 5
#: Deliberately larger than the `PRIOR_MEAN_*` figures the pre-flight uses, so a
#: cap can pass layer 1 and still be tripped by layer 2 a few calls later.
IN_TOKENS = 2000
OUT_TOKENS = 800
_RATES = pricing.load_rates("openai.gpt-oss-20b-1:0", "ap-southeast-2",
                            "standard")
#: What one fake call costs at the committed standard rates — recomputed from the
#: rate table rather than hardcoded, so a rate-table edit moves the caps in step
#: instead of turning these tests into a puzzle.
CALL_USD = _RATES.call_usd(IN_TOKENS, OUT_TOKENS)
#: What the *pre-flight* believes a call costs before any has been measured.
PRIOR_CALL_USD = _RATES.call_usd(pricing.PRIOR_MEAN_INPUT_TOKENS,
                                 pricing.PRIOR_MEAN_OUTPUT_TOKENS)


# ---------------------------------------------------------------------------
# The two fakes: a pyserini index and a Bedrock transport
# ---------------------------------------------------------------------------
class _FakeHit:
    def __init__(self, docid: str, score: float) -> None:
        self.docid = docid
        self.score = score


class _FakeDoc:
    """`contents()` carries the text; `raw()` is None, as measured on the index."""

    def __init__(self, contents: str) -> None:
        self._contents = contents

    def contents(self) -> str:
        return self._contents

    def raw(self) -> None:
        return None


class _FakeLucene:
    """The four `LuceneSearcher` methods the harness calls, config-sensitive.

    `batch_search` rotates each query's ranking by a config-derived offset, the
    way the real index reorders when `set_bm25` changes, so the run files of two
    grid cells genuinely differ and `score` has something to rank.
    """

    def __init__(self, index_dir: str, rankings: dict[str, list[str]],
                 texts: dict[str, str]) -> None:
        self.index_dir = index_dir
        self.num_docs = EXPECTED_NUM_DOCS
        self._rankings = rankings
        self._texts = texts
        self.bm25: tuple[float, float] | None = None
        self.searches = 0
        self.doc_calls: list[str] = []
        self.closed = False

    def set_bm25(self, k1: float, b: float) -> None:
        self.bm25 = (k1, b)

    def batch_search(self, queries, qids, k=10, threads=1):
        self.searches += 1
        shift = (0 if self.bm25 is None
                 else int(round(self.bm25[0] * 10 + self.bm25[1] * 100)))
        out = {}
        for qid in qids:
            ranked = list(self._rankings.get(qid, []))
            if ranked:
                offset = shift % len(ranked)
                ranked = ranked[offset:] + ranked[:offset]
            out[qid] = [_FakeHit(cid, float(len(ranked) - i))
                        for i, cid in enumerate(ranked[:k])]
        return out

    def doc(self, docid: str):
        self.doc_calls.append(docid)
        if docid not in self._texts:
            return None
        return _FakeDoc(self._texts[docid])

    def close(self) -> None:
        self.closed = True


def _response(prompt: str) -> dict:
    """A Converse envelope with the reasoning block FIRST, as measured.

    The grade is derived from the prompt's own digest, so every passage gets a
    stable grade in 0..3 and the qrels have a spread — a constant grade would
    make every config's nDCG identical and hide any scoring regression.
    """
    grade = int(hashlib.sha1(prompt.encode("utf-8")).hexdigest(), 16) % 4
    return {
        "output": {"message": {"role": "assistant", "content": [
            {"reasoningContent": {"reasoningText": {"text": "weighing it up"}}},
            {"text": f"##final score: {grade}"},
        ]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": IN_TOKENS, "outputTokens": OUT_TOKENS,
                  "totalTokens": IN_TOKENS + OUT_TOKENS},
    }


class _FakeError(Exception):
    """A boto3-shaped error: `classify_error` reads attributes, not classes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code},
                         "ResponseMetadata": {"HTTPStatusCode": 400}}


class _FakeConverse:
    """The injected transport: records every prompt, with two optional hooks.

    `pace` runs before the call and is how a test makes the writer thread keep
    up with zero-latency fakes; `hook` runs after the prompt is recorded and is
    how a test injects a failure, a signal, or a stop at a known call index.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.pace: Callable[[], None] | None = None
        self.hook: Callable[[int, str], None] | None = None

    def __call__(self, **kwargs: object) -> dict:
        if self.pace is not None:
            self.pace()
        messages = kwargs["messages"]  # type: ignore[index]
        prompt = messages[0]["content"][0]["text"]
        self.calls.append(prompt)
        if self.hook is not None:
            self.hook(len(self.calls), prompt)
        return _response(prompt)


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------
class Harness:
    """One tmp experiment: a fake index, a fake judge, and the real CLI.

    Holds the identities the assertions need — which chunk ids exist, which
    passage text belongs to which chunk — so a test can ask "was this pair sent
    to the model again?" of the transport rather than of a counter.
    """

    def __init__(self, cfg, converse: _FakeConverse,
                 queries: list[extract.QueryRec], texts: dict[str, str],
                 driver_box: dict) -> None:
        self.cfg = cfg
        self.converse = converse
        self.queries = queries
        self.texts = texts
        self._driver_box = driver_box

    # -- commands -----------------------------------------------------------
    def sweep(self, *extra: str) -> int:
        return cli.main(["search-sweep", "--stage", "B", "--run-id", RUN_ID,
                         "--configs", CONFIGS, "--depth", str(DEPTH), *extra])

    def judge_pool(self, *extra: str) -> int:
        return cli.main(["judge-pool", "--run-id", RUN_ID,
                         "--prompt-version", PV, "--concurrency", "1", *extra])

    def score(self, *extra: str) -> int:
        return cli.main(["score", "--run-id", RUN_ID,
                         "--prompt-version", PV, *extra])

    # -- state --------------------------------------------------------------
    @property
    def run_dir(self) -> Path:
        return self.cfg.run_dir(RUN_ID)

    @property
    def driver(self) -> judge.JudgePoolDriver:
        driver = self._driver_box.get("driver")
        assert driver is not None, "no JudgePoolDriver was built"
        return driver

    def pace_to_writer(self) -> None:
        """Make each fake call wait for the writer thread to catch up.

        Real Converse calls take ~1 s, so in production the writer is never
        behind the feeder. With a zero-latency fake the main loop can finish the
        whole pool before the writer consumes one record, which would make every
        "it stopped part-way" assertion a coin flip. Bounded, so a dead writer
        fails the test instead of hanging it.
        """
        import time

        def _pace() -> None:
            driver = self._driver_box.get("driver")
            if driver is None:
                return
            deadline = time.monotonic() + 10.0
            while driver._queue.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.001)

        self.converse.pace = _pace

    def stop_at(self, index: int, action: Callable[[], None]) -> None:
        """Run `action` from inside the `index`-th fake call."""
        def _hook(call_index: int, _prompt: str) -> None:
            if call_index == index:
                action()

        self.converse.hook = _hook

    def fail_from(self, index: int, code: str) -> None:
        """Raise a boto3-shaped `code` on the `index`-th call and every one after."""
        def _hook(call_index: int, _prompt: str) -> None:
            if call_index >= index:
                raise _FakeError(code)

        self.converse.hook = _hook

    # -- reading what happened ---------------------------------------------
    def log_records(self) -> list[dict]:
        records: list[dict] = []
        for segment in store.iter_segments(self.cfg.log_dir):
            records.extend(store.read_segment(segment).records)
        return records

    def graded_chunks(self) -> set[str]:
        """Chunk ids with a successful judgment in the log (the money spent)."""
        return {str(r["chunk_id"]) for r in self.log_records()
                if store.is_success(r)}

    def snapshot_keys(self) -> set[str]:
        path = store.cache_snapshot_path(self.cfg.cache_dir, PV)
        keys: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("kind") != store.CACHE_META_KIND:
                keys.add(row["jkey"])
        return keys

    def chunks_sent(self, since: int = 0) -> set[str]:
        """Which chunks the transport was asked about, from `since` onwards.

        Recovered from the passage text embedded in the prompt, because that is
        the only evidence that a *call was made* about a pair; a cache-hit
        counter is the thing under test, so it cannot also be the witness.
        """
        by_text = {text: chunk_id for chunk_id, text in self.texts.items()}
        sent: set[str] = set()
        for prompt in self.converse.calls[since:]:
            for text, chunk_id in by_text.items():
                if text in prompt:
                    sent.add(chunk_id)
        return sent

    def spent(self) -> float:
        return pricing.CostMeter.load(self.cfg.costs_dir).spent_usd()

    def pool_pairs(self) -> int:
        from bm25tune.pool import read_pool

        return len(read_pool(self.run_dir / cli.POOL_BASENAME))


@pytest.fixture(autouse=True)
def _quiet_logging() -> None:
    """Keep `main()`'s repeated `setup_logging` from muting `caplog`.

    Every `cli.main` call re-points the root logger at the run's `sweep.log`;
    pinning the level here keeps the `[BUDGET]`/`[SIGNAL]` lines these tests
    assert on visible without suppressing anything.
    """
    logging.getLogger().setLevel(logging.INFO)


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
            bm25_config: "object", mini_labeled_path: Path) -> Harness:
    """A tmp experiment wired to the fake index and the fake Bedrock transport.

    The query set is extracted from the *mini fixture* with WP1's own loader, so
    the topic narratives, the `qkey`s and the run-file names are the real
    artifacts rather than hand-rolled look-alikes. `BedrockJudge` and
    `JudgePoolDriver` are patched as factories (the CLI builds both itself), and
    the driver instance is captured so a test can reach the queue, the stats and
    the signal handlers the CLI installed.
    """
    queries = extract.load_keyword_queries(mini_labeled_path)
    extract.write_query_file(
        bm25_config.queries_dir / cli.QUERIES_FULL_BASENAME, queries)

    rankings: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    counter = 0
    for rec in queries:
        chunk_ids = []
        for _ in range(CANDIDATES):
            chunk_id = f"shard_00000_{counter}_p1"
            counter += 1
            chunk_ids.append(chunk_id)
            texts[chunk_id] = (
                f"Evidence unit {chunk_id} discussing {rec.query}.")
        rankings[rec.qkey] = chunk_ids

    index_dir = tmp_path / "index"
    index_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("BM25_TUNE_INDEX_DIR", str(index_dir))
    monkeypatch.setattr(
        ChunkSearcher, "_import_lucene_searcher",
        lambda self: (lambda path: _FakeLucene(path, rankings, texts)))

    converse = _FakeConverse()
    real_judge = judge.BedrockJudge

    def _judge_factory(model_id: str, region: str, **kwargs: object):
        return real_judge(model_id, region, converse=converse,
                          sleep=lambda _s: None, rng=random.Random(0),
                          **kwargs)

    monkeypatch.setattr(judge, "BedrockJudge", _judge_factory)

    driver_box: dict = {}
    real_driver = judge.JudgePoolDriver

    def _driver_factory(**kwargs: object):
        driver = real_driver(**kwargs)
        driver_box["driver"] = driver
        return driver

    monkeypatch.setattr(judge, "JudgePoolDriver", _driver_factory)
    return Harness(bm25_config, converse, queries, texts, driver_box)


def _digests(root: Path) -> dict[str, str]:
    """`relpath -> sha256` for every file under `root` (empty dict if absent)."""
    if not root.exists():
        return {}
    return {str(p.relative_to(root)):
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------
# The pipeline, end to end
# ---------------------------------------------------------------------------
def test_sweep_then_judge_then_score_produces_the_publishable_artifact_set(
        harness: Harness, caplog: pytest.LogCaptureFixture) -> None:
    """The three commands hand off through files, and nothing else.

    Each stage is a separate process in production, so the only contract between
    them is the bytes on disk: `trecruns/` + `pool.jsonl` + `pool-texts.jsonl`
    from the sweep, `cache/qrels-<pv>.jsonl` from the judge, `scores.*` from the
    scorer, and one `manifest.json` all three merge into. A break in that chain
    is only discoverable after the metered stage has run, which is why it is
    asserted here rather than left to the live smoke test.
    """
    assert harness.sweep() == cli.EXIT_OK
    run_dir = harness.run_dir
    assert sorted(p.name for p in (run_dir / "trecruns").iterdir()) == [
        "k1_0.9__b_0.4.txt", "k1_1.2__b_0.6.txt"]
    assert (run_dir / cli.POOL_TEXTS_BASENAME).is_file()
    pairs = harness.pool_pairs()
    assert pairs == len(harness.queries) * CANDIDATES

    with caplog.at_level("INFO"):
        assert harness.judge_pool() == cli.EXIT_OK
    assert len(harness.converse.calls) == pairs, (
        "one call per pooled pair, no retries and no re-judging")
    assert harness.graded_chunks() == set(harness.texts)
    assert harness.snapshot_keys() == {
        store.jkey(PV, r["topic_id"], r["chunk_id"])
        for r in harness.log_records() if store.is_success(r)}
    assert (run_dir / "costs.json").is_file()
    assert harness.spent() == pytest.approx(pairs * CALL_USD, rel=1e-6)

    with caplog.at_level("INFO"):
        assert harness.score() == cli.EXIT_OK
    for name in (cli.SCORES_CSV_BASENAME, cli.SCORES_MD_BASENAME,
                 cli.SCORES_PER_QUERY_BASENAME):
        assert (run_dir / name).is_file(), name
    manifest = json.loads((run_dir / cli.MANIFEST_BASENAME).read_text(
        encoding="utf-8"))
    assert manifest["grid"] and manifest["judge"]["prompt_version"] == PV
    assert sorted(manifest["scores"]) == ["k1_0.9__b_0.4", "k1_1.2__b_0.6"]
    assert "judged@10 dips" not in caplog.text, (
        "a fully judged pool must score without a coverage caveat")


def test_the_scored_qrels_are_the_judgments_the_log_says_were_paid_for(
        harness: Harness) -> None:
    """The scorer's label set has to be the log's, pair for pair and grade for grade.

    Two independent readers sit between the judge and the score — the cache
    snapshot and `metrics.load_qrels_jsonl` — and a disagreement in either would
    show up only as a slightly different nDCG, indistinguishable from a real
    ranking effect. So the grades are compared against the append-only log,
    which is the only thing that cannot be regenerated from something else.
    """
    assert harness.sweep() == cli.EXIT_OK
    assert harness.judge_pool() == cli.EXIT_OK
    qrels = metrics.load_qrels_jsonl(
        store.cache_snapshot_path(harness.cfg.cache_dir, PV),
        prompt_version=PV)
    from_log = {(r["topic_id"], r["chunk_id"]): r["grade"]
                for r in harness.log_records() if store.is_success(r)}
    assert {(t, c): qrels.grade(t, c) for t, c in from_log} == from_log
    assert len(set(from_log.values())) > 1, (
        "a single-grade fixture would make every config score identically")


# ---------------------------------------------------------------------------
# Resume: the property the whole cred-expiry design rests on
# ---------------------------------------------------------------------------
def test_a_run_killed_by_a_cred_expiry_rejudges_nothing_on_re_invocation(
        harness: Harness, caplog: pytest.LogCaptureFixture) -> None:
    """Exit 3, then "re-run the same command" must re-bill zero pairs.

    An expired SSO token is the most likely interruption of a multi-hour job, and
    the documented recovery is to refresh and re-issue the identical command. That
    is only sound if the second invocation asks the model about strictly the pairs
    the first one never finished — so the witness here is the set of passages the
    fake transport was actually handed, not the cache-hit counter (which is itself
    the thing under test).
    """
    assert harness.sweep() == cli.EXIT_OK
    total = harness.pool_pairs()
    harness.pace_to_writer()
    harness.fail_from(6, "ExpiredTokenException")

    with caplog.at_level("ERROR"):
        assert harness.judge_pool() == cli.EXIT_CRED_EXPIRY
    assert "[CRED]" in caplog.text
    assert "refresh SSO creds and re-run the same command" in caplog.text
    first_round = harness.graded_chunks()
    assert 0 < len(first_round) < total, (
        "the interruption must land part-way, or the test proves nothing")
    spent_after_first = harness.spent()
    calls_after_first = len(harness.converse.calls)

    harness.converse.hook = None
    caplog.clear()
    with caplog.at_level("INFO"):
        assert harness.judge_pool() == cli.EXIT_OK
    second_round = harness.chunks_sent(since=calls_after_first)
    assert second_round & first_round == set(), (
        f"re-judged (and re-paid for) {sorted(second_round & first_round)}")
    assert second_round | first_round == set(harness.texts)
    assert harness.spent() == pytest.approx(
        spent_after_first + len(second_round) * CALL_USD, rel=1e-6)
    assert harness.graded_chunks() == set(harness.texts)
    assert harness.snapshot_keys() == {
        store.jkey(PV, r["topic_id"], r["chunk_id"])
        for r in harness.log_records() if store.is_success(r)}, (
            "after a resumed run the log and the snapshot must agree exactly")


def test_a_resumed_run_that_is_fully_cached_makes_no_call_at_all(
        harness: Harness) -> None:
    """Re-running a finished `judge-pool` is free, not merely cheap.

    The cache consult happens before the pool is submitted, so a completed run
    re-invoked (by a retry loop, a launcher, or a human who lost the terminal)
    must cost exactly nothing. If a single call leaked through, every accidental
    re-run of the real 13k-pair pool would re-bill it.
    """
    assert harness.sweep() == cli.EXIT_OK
    assert harness.judge_pool() == cli.EXIT_OK
    calls, spent = len(harness.converse.calls), harness.spent()
    assert harness.judge_pool() == cli.EXIT_OK
    assert len(harness.converse.calls) == calls
    assert harness.spent() == spent


# ---------------------------------------------------------------------------
# The budget stop (PLAN §5.7 layers 1-3)
# ---------------------------------------------------------------------------
def _cap_that_passes_preflight_but_trips_midrun(pairs: int) -> float:
    """A cap layer 1 approves and layer 2 then trips, stated as a relationship.

    The mid-run stop is only reachable because the pre-flight works from the
    `PRIOR_MEAN_*` token counts while the real calls are bigger — so the cap has
    to sit strictly between the estimate and the truth. Computing it from the
    rate table (rather than hardcoding a float) means a rate or prior change
    re-derives it or trips the assertion, instead of quietly turning these tests
    into pre-flight refusals that still look like they passed.
    """
    estimated = pairs * PRIOR_CALL_USD
    actual = pairs * CALL_USD
    assert estimated < actual, "the fake responses must out-cost the priors"
    return estimated + (actual - estimated) / 2.0


def test_a_midrun_budget_trip_exits_five_and_the_next_run_pays_only_the_rest(
        harness: Harness, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Exit 5 must be a *stop*, not a loss: billed work stays on disk.

    The trip is raised on the writer thread, which keeps consuming afterwards
    because every queued record is already-paid-for work. If the queue were
    discarded instead, the money would be gone with no judgment to show for it,
    and the follow-up run with a raised cap would pay for the same pairs twice —
    the one failure mode that turns a $10 experiment into an open-ended one.
    """
    assert harness.sweep() == cli.EXIT_OK
    total = harness.pool_pairs()
    cap = _cap_that_passes_preflight_but_trips_midrun(total)
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", repr(cap))
    harness.pace_to_writer()

    with caplog.at_level("INFO"):
        assert harness.judge_pool() == cli.EXIT_BUDGET_STOP
    assert "→ OK" in caplog.text, "layer 1 must have approved the run"
    assert "HARD STOP" in caplog.text
    assert "prima facie a BUG" in caplog.text, (
        "a trip at a cap this far below the plan's estimate is a bug, not a "
        "budget to raise")
    billed = harness.graded_chunks()
    assert 0 < len(billed) < total
    assert harness.spent() == pytest.approx(len(billed) * CALL_USD, rel=1e-6)
    assert harness.snapshot_keys() == {
        store.jkey(PV, r["topic_id"], r["chunk_id"])
        for r in harness.log_records() if store.is_success(r)}, (
            "the drain must publish the snapshot for what was paid for")
    calls_after_stop = len(harness.converse.calls)

    caplog.clear()
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", "200.0")
    assert harness.judge_pool() == cli.EXIT_OK
    resumed = harness.chunks_sent(since=calls_after_stop)
    assert resumed & billed == set(), (
        f"the raised-cap run re-paid for {sorted(resumed & billed)}")
    assert resumed | billed == set(harness.texts)
    assert harness.spent() == pytest.approx(total * CALL_USD, rel=1e-6), (
        "the whole pool must cost exactly one call per pair across both runs")


def test_a_preflight_that_cannot_fit_refuses_with_exit_four_and_an_empty_log(
        harness: Harness, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Exit 4 promises "nothing was spent"; exit 5 does not.

    The two are the only signal a launching agent has for whether a partial,
    scoreable result exists — and only one of them is safe to retry with a raised
    cap. Asserted at the CLI boundary *and* against the filesystem: a refusal
    that had already opened a log segment would make the promise false.
    """
    assert harness.sweep() == cli.EXIT_OK
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", "0.0000001")
    with caplog.at_level("ERROR"):
        assert harness.judge_pool() == cli.EXIT_BUDGET_PREFLIGHT
    assert "[BUDGET] nothing was spent." in caplog.text
    assert harness.converse.calls == []
    assert list(store.iter_segments(harness.cfg.log_dir)) == []
    assert harness.spent() == 0.0


def test_scoring_a_budget_truncated_run_is_loud_about_the_missing_coverage(
        harness: Harness, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A partly judged pool still scores, but the shortfall must not read as ranking.

    PLAN §5.7 layer 3 deliberately keeps a truncated run scoreable — the numbers
    are how an operator decides whether to spend more. Unjudged chunks score gain
    0, so part of the spread between cells is coverage rather than ranking, and
    the only thing standing between that and a wrong conclusion is this warning.
    """
    assert harness.sweep() == cli.EXIT_OK
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", repr(
        _cap_that_passes_preflight_but_trips_midrun(harness.pool_pairs())))
    harness.pace_to_writer()
    assert harness.judge_pool() == cli.EXIT_BUDGET_STOP

    with caplog.at_level("INFO"):
        assert harness.score() == cli.EXIT_OK
    assert "judged@10 dips" in caplog.text
    assert (harness.run_dir / cli.SCORES_CSV_BASENAME).is_file(), (
        "the numbers must still be produced — they are how the operator "
        "decides whether the remainder is worth paying for")
    manifest = json.loads((harness.run_dir / cli.MANIFEST_BASENAME).read_text(
        encoding="utf-8"))
    assert manifest["qrels_judged_pairs"] < harness.pool_pairs(), (
        "the manifest must record the partial coverage these scores rest on")


# ---------------------------------------------------------------------------
# `--fresh`: renames derived artifacts, refuses the audit record (PLAN §5.8)
# ---------------------------------------------------------------------------
def test_fresh_renames_the_run_dir_and_leaves_the_log_and_ledger_byte_identical(
        harness: Harness) -> None:
    """The run dir is derived; `judgments/log/` and `costs/` are not.

    A `--fresh` sweep is the normal way to redo a run whose run files were
    written by broken code — and the run dir sits two directories away from the
    only two artifacts in the experiment that cannot be regenerated. So the old
    dir is moved aside under a timestamp (recoverable by a human who changes
    their mind), and the log and ledger are compared byte for byte afterwards.
    The re-judge is then a full cache hit, which is the payoff: `--fresh` on the
    search half costs no Bedrock money.
    """
    assert harness.sweep() == cli.EXIT_OK
    assert harness.judge_pool() == cli.EXIT_OK
    log_before = _digests(harness.cfg.log_dir)
    costs_before = _digests(harness.cfg.costs_dir)
    assert log_before and costs_before, "there must be something to protect"
    calls, spent = len(harness.converse.calls), harness.spent()

    assert harness.sweep("--fresh") == cli.EXIT_OK
    superseded = [p for p in harness.cfg.runs_dir.iterdir()
                  if p.name.startswith(f"{RUN_ID}.superseded-")]
    assert len(superseded) == 1
    assert (superseded[0] / "trecruns").is_dir(), "renamed, never deleted"
    assert _digests(harness.cfg.log_dir) == log_before
    assert _digests(harness.cfg.costs_dir) == costs_before

    assert harness.judge_pool() == cli.EXIT_OK
    assert len(harness.converse.calls) == calls, (
        "a re-swept pool is judged entirely from the log")
    assert harness.spent() == spent


def test_judge_pool_fresh_supersedes_the_snapshot_without_losing_a_grade(
        harness: Harness) -> None:
    """`--fresh` on the judge is scoped to the one derived file it owns.

    The qrels snapshot is a pure accelerator, so throwing it away must be safe —
    and it is safe *only* because the log can rebuild it. Both halves are checked
    here: the old snapshot is renamed rather than removed, and the reloaded cache
    still knows every grade, so the run costs nothing.
    """
    assert harness.sweep() == cli.EXIT_OK
    assert harness.judge_pool() == cli.EXIT_OK
    before = harness.snapshot_keys()
    calls, spent = len(harness.converse.calls), harness.spent()

    assert harness.judge_pool("--fresh") == cli.EXIT_OK
    assert list(harness.cfg.cache_dir.glob("*.superseded-*")), (
        "the old snapshot must be moved aside, not deleted"
    )
    assert harness.snapshot_keys() == before
    assert len(harness.converse.calls) == calls
    assert harness.spent() == spent
    assert (harness.run_dir / cli.POOL_BASENAME).is_file(), (
        "the run dir holds this command's input and is out of --fresh's scope")


@pytest.mark.parametrize("relative_run_id", ["../judgments/log", "../costs"])
def test_fresh_pointed_at_an_append_only_directory_is_refused_outright(
        harness: Harness, relative_run_id: str,
        caplog: pytest.LogCaptureFixture) -> None:
    """A crafted `--run-id` must not be able to rename the audit record.

    Both commands resolve the path before comparing, so traversal cannot reach
    `judgments/log/` (the raw judgments and the ground-truth spend) or `costs/`
    (the budget's durable state). Without this, one mistyped run id would destroy
    hours of paid-for work *and* make the cost reconciliation unfalsifiable — and
    the refusal has to happen before anything is moved, which is why the digests
    are compared afterwards.
    """
    assert harness.sweep() == cli.EXIT_OK
    assert harness.judge_pool() == cli.EXIT_OK
    log_before = _digests(harness.cfg.log_dir)
    costs_before = _digests(harness.cfg.costs_dir)

    with caplog.at_level("ERROR"):
        assert cli.main(["search-sweep", "--stage", "B", "--configs", CONFIGS,
                         "--run-id", relative_run_id, "--fresh"]) \
            == cli.EXIT_ERROR
        assert cli.main(["judge-pool", "--run-id", relative_run_id,
                         "--prompt-version", PV, "--fresh"]) == cli.EXIT_ERROR
    assert "append-only audit record" in caplog.text
    assert _digests(harness.cfg.log_dir) == log_before
    assert _digests(harness.cfg.costs_dir) == costs_before
    assert not list(harness.cfg.judgments_dir.glob("*.superseded-*"))
    assert not list(harness.cfg.data_dir.glob("costs.superseded-*"))


def test_the_store_refuses_fresh_on_both_protected_directories(
        harness: Harness) -> None:
    """The guard the CLI delegates to, asserted directly on the real paths.

    `--fresh` is spelled in several commands, and each one reaches this single
    check; pinning it here means a new `--fresh` flag inherits the protection by
    construction, and the error names `rebuild-cache` so the operator's next step
    is in the message rather than in the source.
    """
    cfg = harness.cfg
    for target in (cfg.log_dir, cfg.costs_dir, cfg.data_dir):
        with pytest.raises(store.ProtectedPathError) as excinfo:
            store.assert_fresh_allowed(target, log_dir=cfg.log_dir,
                                       costs_dir=cfg.costs_dir)
        assert "rebuild-cache" in str(excinfo.value)
    # A derived artifact, by contrast, is fair game.
    store.assert_fresh_allowed(harness.run_dir, log_dir=cfg.log_dir,
                               costs_dir=cfg.costs_dir)


# ---------------------------------------------------------------------------
# The drain: one routine, four triggers (PLAN §5.8)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("signum", "expected_code", "trigger"), [
    (signal.SIGINT, cli.EXIT_SIGINT, judge.TRIGGER_SIGINT),
    (signal.SIGTERM, cli.EXIT_SIGTERM, judge.TRIGGER_SIGTERM),
])
def test_a_signal_mid_run_flushes_every_completed_judgment_then_exits(
        harness: Harness, signum: int, expected_code: int, trigger: str,
        caplog: pytest.LogCaptureFixture) -> None:
    """130/143 with nothing lost: the log, the snapshot and the ledger all agree.

    An operator hitting Ctrl-C, or a scheduler sending SIGTERM, must not cost the
    run its already-billed judgments — so the handler only sets a flag and the
    main thread drains: it waits out the in-flight calls, snapshots the cache and
    checkpoints the meter before returning. The handler is *called as a function*
    from inside a fake Converse call rather than raised as a real signal, which
    would take pytest's own main thread with it.
    """
    assert harness.sweep() == cli.EXIT_OK
    total = harness.pool_pairs()
    harness.pace_to_writer()

    def _raise_flag() -> None:
        handler = signal.getsignal(signum)
        assert callable(handler), "judge-pool must install its own handler"
        handler(signum, None)

    harness.stop_at(6, _raise_flag)
    with caplog.at_level("ERROR"):
        assert harness.judge_pool() == expected_code
    assert "[SIGNAL]" in caplog.text
    assert harness.driver.trigger == trigger, (
        "the handler must set the trigger and nothing else")
    assert harness.driver.stats.judged < total, "the stop must be mid-run"

    graded = harness.graded_chunks()
    assert graded, "every completed judgment must reach the log"
    assert harness.snapshot_keys() == {store.jkey(PV, t, c) for t, c in (
        (r["topic_id"], r["chunk_id"]) for r in harness.log_records()
        if store.is_success(r))}
    assert harness.spent() == pytest.approx(
        pricing.judgment_log_total_usd(harness.cfg.log_dir), abs=1e-9), (
            "the meter must be checkpointed against the log before exiting")
    assert signal.getsignal(signum) is not _raise_flag
    assert harness.judge_pool() == cli.EXIT_OK, (
        "the drained run resumes with the same command")


def test_the_drain_exit_codes_are_the_ones_main_returns_for_every_trigger(
        harness: Harness) -> None:
    """The §5.8 trigger table and the CLI's constants must not drift apart.

    Three of these codes reach a human or a launcher as the *only* description of
    why a metered job stopped: 3 means re-auth and re-run, 5 means diagnose the
    spend, 130/143 mean the operator or the scheduler asked. `judge.py` owns the
    table and `cli.py` owns the constants, so they are compared here as well as
    exercised individually above — a silent renumbering would send the operator
    to the wrong procedure with money already spent.
    """
    assert judge.TRIGGER_EXITS[judge.TRIGGER_CRED] == ("[CRED]",
                                                       cli.EXIT_CRED_EXPIRY)
    assert judge.TRIGGER_EXITS[judge.TRIGGER_BUDGET] == ("[BUDGET]",
                                                         cli.EXIT_BUDGET_STOP)
    assert judge.TRIGGER_EXITS[judge.TRIGGER_SIGINT] == ("[SIGNAL]",
                                                         cli.EXIT_SIGINT)
    assert judge.TRIGGER_EXITS[judge.TRIGGER_SIGTERM] == ("[SIGNAL]",
                                                          cli.EXIT_SIGTERM)
    assert judge.TRIGGER_EXITS[judge.TRIGGER_COMPLETE] == ("[SUMMARY]",
                                                           cli.EXIT_OK)


def test_the_signal_handlers_are_restored_so_a_later_command_is_unaffected(
        harness: Harness) -> None:
    """`judge-pool` borrows SIGINT/SIGTERM; it must give them back.

    The harness is importable as a library and pytest runs many commands in one
    process. A handler left installed would silently swallow the *next*
    invocation's Ctrl-C — the run would keep going with the operator believing it
    had stopped, which is the one shutdown bug that spends money after the fact.
    """
    before = {s: signal.getsignal(s)
              for s in (signal.SIGINT, signal.SIGTERM)}
    assert harness.sweep() == cli.EXIT_OK
    assert harness.judge_pool() == cli.EXIT_OK
    assert {s: signal.getsignal(s)
            for s in (signal.SIGINT, signal.SIGTERM)} == before
