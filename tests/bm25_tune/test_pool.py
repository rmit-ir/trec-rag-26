"""What `pool.py` defends: the fairness of every comparison the sweep publishes.

Pooling is the load-bearing scientific decision of the harness, and it fails
*silently* in both directions:

- **Union too narrow** (per config, or per query) and each config is scored
  against a qrel built from its own output, so a config that misses relevant
  chunks cannot be penalised for missing them. The score matrix still comes out
  complete and plausible — it just doesn't measure what it claims.
- **Union too wide** (no depth cut) and the judging bill inflates for chunks no
  nDCG@10 comparison can ever reward. At ~$0.002/judgment over ~50 topics this is
  real money, and the only symptom is a bigger invoice.

So the tests here are mostly *identity* tests on the union: same chunk, two
configs -> one pool entry; same chunk, two queries of a topic -> one entry; same
chunk, two topics -> two entries (the cache key is `(prompt_version, topic_id,
chunk_id)`, PLAN §5.3 — a chunk judged for topic A says nothing about topic B).

The fixtures deliberately use `mini-labeled.jsonl`'s real topic ids and chunk ids
so the shapes here match what `extract-queries` actually produces, and the
scripted rankings **differ per config** — mirroring the **[measured]** 0.72
top-10 overlap between grid cells. A fake where all configs returned the same
ranking would make every one of these tests pass against a pool builder that
ignored the config axis entirely.

Also covered: the persistence round-trips. `pool.jsonl` and the TREC run files
cross a process boundary into `judge-pool` and `score`, and `search-sweep`'s
resumption rule is "skip a config whose run file exists" — so a run file that
cannot be read back the way it was written turns a resumed sweep into a silently
under-pooled one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bm25tune.extract import (QueryRec, load_keyword_queries, sha256_text)
from bm25tune.pool import (PoolEntry, PoolError, build_pool, log_pool,
                           pool_entries, pool_stats, read_pool, read_trec_run,
                           write_pool, write_trec_run)

TOPIC_A = "rag2026-900"
TOPIC_B = "rag2026-901"


def q(topic_id: str, text: str) -> QueryRec:
    return QueryRec.make(topic_id, f"narrative for {topic_id}", text, 30)


@pytest.fixture
def queries() -> list[QueryRec]:
    """Two topics; topic A has two queries, topic B has one.

    The asymmetry is the point: a bug that pooled per query instead of per topic
    passes trivially when every topic has exactly one query.
    """
    return [q(TOPIC_A, "library budget"), q(TOPIC_A, "reference desk staffing"),
            q(TOPIC_B, "soil moisture sensors")]


# ---------------------------------------------------------------------------
# The union: across configs
# ---------------------------------------------------------------------------
def test_a_chunk_retrieved_by_two_configs_is_pooled_once(
        queries: list[QueryRec]) -> None:
    """One judgment must serve every config — that is the whole cost model.

    **[measured]** configs mostly reorder a shared candidate set (1.44x inflation
    over 6 configs, not 6x). If the union double-counted by config, the pool would
    grow linearly in grid size and Stage A alone would cost ~26x its budget.
    """
    alpha = queries[0].qkey
    runs = {
        "k1_0.5__b_0.2": {alpha: [("shard_00001_11_p1", 9.0),
                                  ("shard_00002_77_p1", 8.0)]},
        # Same two chunks, reordered — the measured behaviour of a config change.
        "k1_1.6__b_0.8": {alpha: [("shard_00002_77_p1", 7.0),
                                  ("shard_00001_11_p1", 6.5)]},
    }
    pool = build_pool(runs, queries)
    assert pool == {TOPIC_A: {"shard_00001_11_p1", "shard_00002_77_p1"}}


def test_a_chunk_only_one_config_finds_still_enters_the_pool(
        queries: list[QueryRec]) -> None:
    """The union is a union, not an intersection.

    An intersection would judge only the chunks every config agrees on — the
    chunks that cannot discriminate between configs. Everything the sweep is
    looking for lives in the symmetric difference, so a config's unique hits are
    exactly what must be judged.
    """
    alpha = queries[0].qkey
    runs = {
        "k1_0.5__b_0.2": {alpha: [("shared", 9.0), ("only-low-b", 8.0)]},
        "k1_1.6__b_0.8": {alpha: [("shared", 9.0), ("only-high-b", 8.0)]},
    }
    assert build_pool(runs, queries) == {
        TOPIC_A: {"shared", "only-low-b", "only-high-b"}}


# ---------------------------------------------------------------------------
# The union: across a topic's queries
# ---------------------------------------------------------------------------
def test_a_chunk_retrieved_by_two_queries_of_a_topic_is_pooled_once(
        queries: list[QueryRec]) -> None:
    """Per *topic*, not per query — the reuse that makes Stage B affordable.

    A topic has 3–16 keyword queries with heavily overlapping rankings, and the
    judge scores the chunk against the topic *narrative*, not the keyword string.
    So the same (topic, chunk) judgment is valid for every query of that topic.
    Pooling per query instead would multiply the bill by the mean queries/topic
    (~9) while producing byte-identical judgments.
    """
    alpha, beta = queries[0].qkey, queries[1].qkey
    runs = {"k1_0.9__b_0.4": {alpha: [("shard_00001_11_p1", 9.0)],
                              beta: [("shard_00001_11_p1", 4.0)]}}
    pool = build_pool(runs, queries)
    assert pool == {TOPIC_A: {"shard_00001_11_p1"}}
    assert sum(len(v) for v in pool.values()) == 1


def test_the_same_chunk_under_two_topics_is_two_pool_entries(
        queries: list[QueryRec]) -> None:
    """Relevance is topic-relative, so the pair is the unit, not the chunk.

    The cache key is `(prompt_version, topic_id, chunk_id)` (PLAN §5.3). Keying
    the pool on `chunk_id` alone would let a judgment made for one topic satisfy
    another — producing a qrel that grades passages against the wrong information
    need, with no artifact recording that it happened.
    """
    alpha, gamma = queries[0].qkey, queries[2].qkey
    runs = {"k1_0.9__b_0.4": {alpha: [("shard_00001_11_p1", 9.0)],
                              gamma: [("shard_00001_11_p1", 3.0)]}}
    pool = build_pool(runs, queries)
    assert pool == {TOPIC_A: {"shard_00001_11_p1"},
                    TOPIC_B: {"shard_00001_11_p1"}}
    assert sum(len(v) for v in pool.values()) == 2


def test_both_axes_union_at_once(queries: list[QueryRec]) -> None:
    """Configs x queries collapse into one per-topic set in a single pass.

    Pooling one axis correctly and the other by accident is easy; this pins the
    combined behaviour, which is what the sweep actually calls — two configs over
    two queries of one topic, five distinct chunks, one pool.
    """
    alpha, beta = queries[0].qkey, queries[1].qkey
    runs = {
        "k1_0.5__b_0.2": {alpha: [("c1", 9.0), ("c2", 8.0)],
                          beta: [("c2", 7.0), ("c3", 6.0)]},
        "k1_1.6__b_0.8": {alpha: [("c1", 9.0), ("c4", 8.0)],
                          beta: [("c3", 7.0), ("c5", 6.0)]},
    }
    assert build_pool(runs, queries) == {TOPIC_A: {"c1", "c2", "c3", "c4", "c5"}}


# ---------------------------------------------------------------------------
# The depth cutoff
# ---------------------------------------------------------------------------
def test_depth_truncates_each_ranking_before_the_union(
        queries: list[QueryRec]) -> None:
    """Judging past depth 30 is money spent on ranks nDCG@10 cannot reward.

    Truncation happens here rather than being trusted from the searcher, because
    a run file may legitimately be deeper than the pool depth — a Stage-A run
    re-used at a larger `k`, or a hand-built run for a probe.
    """
    alpha = queries[0].qkey
    runs = {"k1_0.9__b_0.4": {alpha: [(f"c{i}", 50.0 - i) for i in range(50)]}}
    assert build_pool(runs, queries, depth=5) == {
        TOPIC_A: {"c0", "c1", "c2", "c3", "c4"}}
    assert len(build_pool(runs, queries)[TOPIC_A]) == 30


def test_depth_keeps_the_top_of_the_ranking_not_an_arbitrary_slice(
        queries: list[QueryRec]) -> None:
    """Truncation must take the *head*, in the searcher's order.

    A slice from the wrong end would pool the worst-scoring 30 of a deeper run —
    a pool that is the right size and contains almost nothing a good config
    retrieved, so every config would score near zero and the comparison would
    look like a tie.
    """
    alpha = queries[0].qkey
    ranking = [("best", 10.0), ("middle", 5.0), ("worst", 1.0)]
    assert build_pool({"cfg": {alpha: ranking}}, queries, depth=2) == {
        TOPIC_A: {"best", "middle"}}


def test_a_ranking_shorter_than_depth_is_taken_whole(
        queries: list[QueryRec]) -> None:
    """A narrow keyword query that returns 4 hits must not error or pad.

    Real keyword queries from the log do retrieve fewer than 30 chunks; padding
    or raising here would either invent chunk ids or abort a legitimate sweep.
    """
    alpha = queries[0].qkey
    assert build_pool({"cfg": {alpha: [("c1", 1.0)]}}, queries,
                      depth=30) == {TOPIC_A: {"c1"}}


def test_a_zero_or_negative_depth_is_rejected() -> None:
    """`depth=0` would produce an empty pool and a silently unjudgeable run.

    Every config would then score 0.0 against an empty qrel and the sweep would
    report a perfect tie — indistinguishable from "no config helps", which is a
    conclusion someone might act on.
    """
    with pytest.raises(ValueError, match="depth must be >= 1"):
        build_pool({}, [], depth=0)


# ---------------------------------------------------------------------------
# Cross-artifact consistency
# ---------------------------------------------------------------------------
def test_a_ranking_for_an_unknown_qkey_is_a_hard_error(
        queries: list[QueryRec]) -> None:
    """Run files and the query set must describe the same experiment.

    A qkey in a run file but not in the query set means the two artifacts came
    from different extractions (a re-run `extract-queries`, a stale `trecruns/`
    dir). Dropping it quietly would shrink the pool and deflate every config's
    recall in a way no reader of the score table could detect, so the sweep stops
    and names the tool to re-run.
    """
    with pytest.raises(PoolError, match="unknown qkey"):
        build_pool({"cfg": {"rag2026-999::deadbeef": [("c1", 1.0)]}}, queries)


def test_a_qkey_claimed_by_two_topics_is_a_hard_error() -> None:
    """The qkey -> topic map must be a function, or pooling is nondeterministic.

    `qkey` embeds the topic id, so this can only happen if a query set was
    hand-edited or merged across extractions — in which case whichever row won
    the map would decide which topic gets the chunk, and the pool would depend on
    input order.
    """
    forged = QueryRec(topic_id=TOPIC_B, topic="other", query="library budget",
                      qkey=q(TOPIC_A, "library budget").qkey, k_orig=30)
    with pytest.raises(PoolError, match="maps to both"):
        build_pool({}, [q(TOPIC_A, "library budget"), forged])


def test_pooling_works_on_queries_loaded_from_the_real_input_shape(
        mini_labeled_path: Path) -> None:
    """End-to-end against `extract-queries`' actual output, not hand-built recs.

    `build_pool` keys everything on `QueryRec.qkey`/`topic_id`, so it is only
    correct if those are the fields the extractor really produces. This is the
    one test that pins the two modules together — including the fixture's
    duplicated (topic, query) pair, which the extractor collapses and which would
    otherwise reach the searcher as a duplicate qkey.
    """
    recs = load_keyword_queries(mini_labeled_path)
    assert len(recs) == len({r.qkey for r in recs})  # extractor deduped
    runs = {"k1_0.9__b_0.4": {r.qkey: [(f"chunk-for-{r.qkey}", 1.0)]
                              for r in recs}}
    pool = build_pool(runs, recs)
    assert set(pool) == {r.topic_id for r in recs}
    assert sum(len(v) for v in pool.values()) == len(recs)


# ---------------------------------------------------------------------------
# pool_entries / provenance
# ---------------------------------------------------------------------------
def test_first_seen_config_records_which_cell_contributed_a_chunk(
        queries: list[QueryRec]) -> None:
    """Provenance a `set[str]` pool cannot carry, and it must be the *first*.

    It answers "did the whole grid find this chunk, or did one extreme cell drag
    it in" for free when reading `pool.jsonl`. "First" (in sweep order) rather
    than "any" is what makes the file byte-reproducible across re-runs of
    identical code.
    """
    alpha = queries[0].qkey
    runs = {"k1_0.5__b_0.2": {alpha: [("shared", 9.0)]},
            "k1_1.6__b_0.8": {alpha: [("shared", 9.0), ("late", 8.0)]}}
    by_chunk = {e.chunk_id: e.first_seen_config
                for e in pool_entries(runs, queries)}
    assert by_chunk == {"shared": "k1_0.5__b_0.2", "late": "k1_1.6__b_0.8"}


def test_pool_entries_are_sorted_so_the_file_diffs_cleanly(
        queries: list[QueryRec]) -> None:
    """`pool.jsonl` is an artifact humans diff between runs.

    Discovery order would make two runs of identical code produce different
    files, so a real change to the pool would be invisible in the noise of
    reordered lines.
    """
    alpha, gamma = queries[0].qkey, queries[2].qkey
    runs = {"cfg": {gamma: [("c9", 1.0), ("c1", 0.9)],
                    alpha: [("c5", 1.0), ("c2", 0.9)]}}
    entries = pool_entries(runs, queries)
    assert [(e.topic_id, e.chunk_id) for e in entries] == [
        (TOPIC_A, "c2"), (TOPIC_A, "c5"), (TOPIC_B, "c1"), (TOPIC_B, "c9")]


def test_pool_entries_and_build_pool_never_disagree(
        queries: list[QueryRec]) -> None:
    """The judged set and the recorded set must be the same set.

    `judge-pool` reads `pool.jsonl` while the manifest's counts come from
    `build_pool`/`pool_stats`. If the two traversals diverged, the run would
    report having judged a pool it did not judge — and the mismatch would only
    surface as unexplained gaps in the qrel.
    """
    alpha, beta, gamma = (queries[0].qkey, queries[1].qkey, queries[2].qkey)
    runs = {"cfg-1": {alpha: [("c1", 9.0), ("c2", 8.0)],
                      beta: [("c2", 7.0)]},
            "cfg-2": {gamma: [("c3", 9.0)], alpha: [("c4", 5.0)]}}
    pool = build_pool(runs, queries, depth=2)
    entries = pool_entries(runs, queries, depth=2)
    assert {(t, c) for t, chunks in pool.items() for c in chunks} == {
        e.key for e in entries}


def test_text_sha256_pins_the_passage_the_judge_was_shown(
        queries: list[QueryRec]) -> None:
    """The digest is of the *stripped* text, and absent when text is unknown.

    It is the only way to detect later that a cached judgment refers to text that
    has since changed (a re-chunked index at the same path). `None` rather than a
    digest of `""` for an unfetched chunk, so "we never had the text" and "the
    text was empty" stay distinguishable.
    """
    alpha = queries[0].qkey
    runs = {"cfg": {alpha: [("c1", 9.0), ("c2", 8.0)]}}
    entries = pool_entries(runs, queries, texts={"c1": "the passage"})
    digests = {e.chunk_id: e.text_sha256 for e in entries}
    assert digests == {"c1": sha256_text("the passage"), "c2": None}


# ---------------------------------------------------------------------------
# pool_stats
# ---------------------------------------------------------------------------
def test_inflation_is_measured_against_observed_ranking_lengths(
        queries: list[QueryRec]) -> None:
    """The denominator is what was retrieved, not `depth`.

    Using `depth` would understate inflation whenever a keyword query returns
    fewer than 30 hits — making the pool look more redundant than it is and the
    judge-cost projection optimistic, which is the wrong direction for a number
    that gates spend.
    """
    alpha = queries[0].qkey
    # Each config returns 2 hits; the union is 3. Inflation = 3/2.
    runs = {"cfg-1": {alpha: [("c1", 9.0), ("c2", 8.0)]},
            "cfg-2": {alpha: [("c1", 9.0), ("c3", 8.0)]}}
    stats = pool_stats(runs, queries, depth=30)
    assert stats.single_config_mean == 2.0
    assert stats.per_query_mean == 3.0
    assert stats.inflation_vs_single == pytest.approx(1.5)


def test_stats_count_configs_queries_and_topics_actually_present(
        queries: list[QueryRec]) -> None:
    """Manifest counts describe the run, not the intended grid.

    A resumed or partial sweep must record the configs and queries it really
    pooled; inheriting the intended numbers from the CLI args would make a
    26-cell manifest for a 3-cell run, and every later comparison would be
    against a run that never happened.
    """
    alpha, gamma = queries[0].qkey, queries[2].qkey
    runs = {"cfg-1": {alpha: [("c1", 1.0)], gamma: [("c2", 1.0)]},
            "cfg-2": {alpha: [("c1", 1.0)], gamma: [("c2", 1.0)]}}
    stats = pool_stats(runs, queries)
    assert (stats.configs, stats.queries, stats.topics) == (2, 2, 2)
    assert stats.unique_pairs == 2
    assert stats.to_json()["unique_pairs"] == 2


def test_stats_on_an_empty_run_set_do_not_divide_by_zero() -> None:
    """A sweep whose every config was already done still reports stats.

    Fully-resumed sweeps happen (that is the point of idempotence), and a
    `ZeroDivisionError` in the summary path would fail a run that had in fact
    completed successfully.
    """
    stats = pool_stats({}, [])
    assert stats.unique_pairs == 0
    assert stats.inflation_vs_single == 0.0


def test_log_pool_reports_the_extremes_not_just_the_mean(
        queries: list[QueryRec], caplog: pytest.LogCaptureFixture) -> None:
    """A runaway topic is invisible in an average, and it is where cost hides.

    `[POOL]` is a documented grep prefix, so the line must actually be emitted at
    INFO with the smallest and largest topic named — that is how an operator
    decides whether a pool size is plausible before authorising the judge run.
    """
    import logging

    alpha, gamma = queries[0].qkey, queries[2].qkey
    runs = {"cfg": {alpha: [(f"c{i}", 1.0) for i in range(9)],
                    gamma: [("c-only", 1.0)]}}
    pool = build_pool(runs, queries)
    with caplog.at_level(logging.INFO):
        log_pool(pool_stats(runs, queries), pool)
    assert "[POOL]" in caplog.text
    assert f"{TOPIC_B}=1 chunks" in caplog.text
    assert f"{TOPIC_A}=9 chunks" in caplog.text


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_pool_jsonl_round_trips(tmp_path: Path,
                                queries: list[QueryRec]) -> None:
    """`judge-pool` runs in a separate process; this file is the whole handoff.

    Any field lost in the round-trip is a field `judge-pool` silently defaults —
    losing `text_sha256`, for instance, would disable the "did the passage
    change" check with no error anywhere.
    """
    alpha = queries[0].qkey
    entries = pool_entries({"cfg": {alpha: [("c1", 9.0)]}}, queries,
                           texts={"c1": "text"})
    path = tmp_path / "pool.jsonl"
    assert write_pool(path, entries) == 1
    assert read_pool(path) == entries


def test_pool_jsonl_is_one_json_object_per_line(tmp_path: Path,
                                                queries: list[QueryRec]) -> None:
    """JSONL, so a 60 k-row pool streams and a partial file is still greppable.

    The plan specifies JSONL for every artifact (PLAN §4.2); a JSON array would
    force the whole pool into memory in `judge-pool` and make `wc -l`/`grep` on a
    run in progress useless.
    """
    alpha = queries[0].qkey
    path = tmp_path / "pool.jsonl"
    write_pool(path, pool_entries({"cfg": {alpha: [("c1", 9.0), ("c2", 8.0)]}},
                                  queries))
    rows = [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert set(rows[0]) == {"topic_id", "chunk_id", "first_seen_config",
                            "text_sha256"}


def test_write_pool_leaves_no_tmp_file_behind(tmp_path: Path,
                                              queries: list[QueryRec]) -> None:
    """Atomic write: `judge-pool` must never see a half-written pool.

    A truncated `pool.jsonl` would under-judge the run while looking complete, so
    the file appears only once fully written — and the `.tmp` must not linger,
    since a stray one would be picked up by a glob over the run dir.
    """
    alpha = queries[0].qkey
    path = tmp_path / "pool.jsonl"
    write_pool(path, pool_entries({"cfg": {alpha: [("c1", 9.0)]}}, queries))
    assert [p.name for p in sorted(tmp_path.iterdir())] == ["pool.jsonl"]


def test_read_pool_rejects_a_corrupt_line_with_its_line_number(
        tmp_path: Path) -> None:
    """A truncated pool must fail loudly, naming where.

    The alternative — skipping unparseable lines — would silently drop chunks
    from the judged set, which is the same failure as an under-built pool but
    harder to spot because the file *looks* right.
    """
    path = tmp_path / "pool.jsonl"
    path.write_text('{"topic_id": "t", "chunk_id": "c", '
                    '"first_seen_config": "cfg"}\n{"broken\n')
    with pytest.raises(PoolError, match=r"pool\.jsonl:2"):
        read_pool(path)


def test_trec_run_file_has_the_six_columns_trec_eval_expects(
        tmp_path: Path, queries: list[QueryRec]) -> None:
    """`qkey Q0 chunk_id rank score tag`, ranks dense and 1-based.

    These files are the run's durable output — re-scoreable with `trec_eval`
    independently of our `metrics.py`, which is the cross-check that our nDCG is
    right. A wrong column order or 0-based rank makes them silently unusable by
    the standard tool.
    """
    alpha = queries[0].qkey
    path = tmp_path / "k1_0.9__b_0.4.txt"
    written = write_trec_run(path, {alpha: [("c1", 9.5), ("c2", 8.25)]},
                             tag="k1_0.9__b_0.4")
    assert written == 2
    rows = [line.split() for line in path.read_text().splitlines()]
    assert [r[1] for r in rows] == ["Q0", "Q0"]
    assert [r[3] for r in rows] == ["1", "2"]
    assert rows[0] == [alpha, "Q0", "c1", "1", "9.500000", "k1_0.9__b_0.4"]


def test_trec_run_ranks_are_re_derived_not_inherited(
        tmp_path: Path, queries: list[QueryRec]) -> None:
    """Depth truncation must renumber, so ranks stay dense from 1.

    A run file written at depth 2 from a 5-hit ranking has to say ranks 1–2. Any
    gap or offset would shift `trec_eval`'s discount positions and change the
    nDCG we publish.
    """
    alpha = queries[0].qkey
    path = tmp_path / "run.txt"
    write_trec_run(path, {alpha: [(f"c{i}", 10.0 - i) for i in range(5)]},
                   tag="cfg", depth=2)
    assert [line.split()[3] for line in path.read_text().splitlines()] == ["1",
                                                                          "2"]


def test_trec_run_round_trips_for_idempotent_resumption(
        tmp_path: Path, queries: list[QueryRec]) -> None:
    """A resumed sweep pools from files on disk, so read must invert write.

    `search-sweep` skips a config whose run file exists — and then still has to
    include that config's hits in the pool. If the parse lost or reordered hits,
    a resumed sweep would build a *different*, smaller pool than a fresh one, and
    the two runs' score matrices would not be comparable.
    """
    alpha, beta = queries[0].qkey, queries[1].qkey
    rankings = {alpha: [("c1", 9.5), ("c2", 8.25)], beta: [("c3", 7.0)]}
    path = tmp_path / "run.txt"
    write_trec_run(path, rankings, tag="cfg")
    assert read_trec_run(path) == rankings


def test_read_trec_run_orders_by_the_rank_column_not_file_order(
        tmp_path: Path) -> None:
    """Rank is authoritative, so a concatenated or sorted-by-docid run still pools.

    Run files get moved, `sort`ed, and hand-inspected. Trusting line order would
    make the pool's depth cut take an arbitrary subset of a file whose lines were
    shuffled — while producing a pool of exactly the right size.
    """
    path = tmp_path / "run.txt"
    path.write_text("q1 Q0 c-second 2 8.0 cfg\nq1 Q0 c-first 1 9.0 cfg\n")
    assert read_trec_run(path) == {"q1": [("c-first", 9.0), ("c-second", 8.0)]}


def test_read_trec_run_rejects_a_malformed_line_with_its_line_number(
        tmp_path: Path) -> None:
    """A corrupt run file must not be silently treated as a completed config.

    This is the failure mode idempotence creates: a crash mid-write (or a
    truncated copy) leaves a file whose existence says "config done". Parsing has
    to be the thing that catches it, since the existence check cannot.
    """
    path = tmp_path / "run.txt"
    path.write_text("q1 Q0 c1 1 9.0 cfg\nq1 Q0 oops\n")
    with pytest.raises(PoolError, match=r"run\.txt:2"):
        read_trec_run(path)


def test_read_trec_run_rejects_a_non_numeric_rank(tmp_path: Path) -> None:
    """A 6-column line with junk in the rank field is still unusable.

    Column *count* is not validity — a whitespace-mangled or half-overwritten
    line can keep its shape while losing its numbers, and coercing that to 0
    would put the hit at the top of the ranking.
    """
    path = tmp_path / "run.txt"
    path.write_text("q1 Q0 c1 one 9.0 cfg\n")
    with pytest.raises(PoolError, match="not numeric"):
        read_trec_run(path)


def test_pool_entry_key_is_the_cache_key_pair() -> None:
    """`PoolEntry.key` is `(topic_id, chunk_id)` — the judgment cache's identity.

    `judge-pool` uses it to look up an existing judgment (PLAN §5.3, minus the
    prompt version it adds itself). If it were chunk-only or reordered, cache
    lookups would hit the wrong row and reuse a judgment made for another topic.
    """
    entry = PoolEntry(topic_id=TOPIC_A, chunk_id="c1", first_seen_config="cfg")
    assert entry.key == (TOPIC_A, "c1")
