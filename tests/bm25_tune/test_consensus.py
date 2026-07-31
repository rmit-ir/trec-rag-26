"""The multi-prompt consensus qrels combiner and its CLI cascade (PLAN §6.2b).

What this file defends: the disagreement-triggered ensemble the operator
specified after Stage A, whose whole justification is that a single judge's qrel
carries one prompt's systematic bias and reproduces its own grade only ~84 % of
the time (`worklogs/2026-07-31-judge-temperature-sweep.md`). Two properties are
load-bearing and easy to break silently:

- **The conflict threshold and the aggregation rules.** Adjacent grades
  (|Δ|==1) must resolve to the *lower* one (round-down), so a config is never
  credited for relevance only one judge saw; only |Δ|>=2 escalates; the tiebreak
  is a median, not a mean, so it stays an actual grade. Getting any of these
  backwards changes every label without failing loudly.
- **The command spends nothing and stops before the tiebreak.** `consensus`
  only folds cached grades; the tiebreak is emitted as a normal pool for a
  metered `judge-pool`, and the discover pass must halt (exit 0) rather than
  auto-spend. The `no_network` autouse fixture is the backstop — a test that
  reached Bedrock would fail — but the design is what keeps that fixture idle.

The pure-combiner tests carry the arithmetic; the CLI tests carry the wiring
(qrels in → escalation pool + consensus qrels out, and the finalize round-trip
scoring through `score --qrels`).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from bm25tune import cli, consensus, extract, metrics, pool as pool_mod, store

RUN_ID = "20260731T000000-stageA"


# ---------------------------------------------------------------------------
# The pure combiner (no Config, no disk) — the arithmetic the CLI relies on.
# ---------------------------------------------------------------------------
def test_median_of_three_is_the_middle_grade_not_the_mean() -> None:
    """The tiebreak must return a grade some judge actually assigned.

    Median, so a lone outlier (0 among 3,3) cannot drag the label and the result
    never lands between rubric levels the way round(mean) would.
    """
    assert consensus.median_of_three(0, 3, 3) == 3
    assert consensus.median_of_three(0, 0, 3) == 0
    assert consensus.median_of_three(1, 3, 2) == 2
    # A mean would give 2 here (7/3≈2.3 → 2 as well), but the outlier case above
    # is where median and round(mean) diverge; pin the middle explicitly.
    assert consensus.median_of_three(3, 3, 0) == 3


def test_adjacent_grades_agree_and_round_down() -> None:
    """|Δ|==1 is treated as agreement, resolved to the conservative lower grade.

    (2,3)→2 not 3: when two judges split on relevance the experiment understates
    rather than credits a config for a chunk only one judge rated highly.
    """
    p = consensus.combine_pair("t", "c", 2, 3)
    assert p.status == consensus.STATUS_AGREE
    assert p.consensus == 2
    assert consensus.combine_pair("t", "c", 3, 2).consensus == 2
    assert consensus.combine_pair("t", "c", 0, 1).consensus == 0
    assert consensus.combine_pair("t", "c", 2, 2).consensus == 2


def test_two_grades_apart_is_a_pending_conflict_until_a_tiebreak_arrives() -> None:
    """|Δ|>=2 escalates: no consensus grade until the tiebreak prompt judges it.

    Left unresolved (consensus None) rather than guessed, so a half-finished
    cascade scores the pair as unjudged instead of fabricating a label.
    """
    pending = consensus.combine_pair("t", "c", 1, 3)
    assert pending.status == consensus.STATUS_PENDING
    assert pending.consensus is None

    resolved = consensus.combine_pair("t", "c", 1, 3, tiebreak=1)
    assert resolved.status == consensus.STATUS_RESOLVED
    assert resolved.consensus == 1  # median(1,3,1)
    assert resolved.grades == (1, 3, 1)


def test_a_single_judge_pair_keeps_its_one_grade_rather_than_being_dropped() -> None:
    """A parse failure in one prompt (grade absent) must not drop the pair.

    Dropping it would deflate judged@10 for every config; the surviving grade is
    used, flagged `single` for the audit trail.
    """
    only = consensus.combine_pair("t", "c", None, 2)
    assert only.status == consensus.STATUS_SINGLE
    assert only.consensus == 2
    assert consensus.combine_pair("t", "c", 3, None).consensus == 3


def test_build_consensus_discovers_the_escalation_set_then_finalizes() -> None:
    """The same function drives both cascade passes (discover, then finalize).

    Discover (no tiebreak) resolves agreements and lists conflicts as pending;
    finalize (with the tiebreak grades) folds those conflicts in by median.
    """
    primary = {"t1": {"a": 2, "b": 1, "c": 3}, "t2": {"d": 0}}
    secondary = {"t1": {"a": 3, "b": 3, "c": 3}, "t2": {"d": 3}}

    discover = consensus.build_consensus(primary, secondary)
    # a: |2-3|=1 agree→2 ; c: agree→3 ; b: |1-3|=2 conflict ; d: |0-3|=3 conflict
    assert discover.grades == {"t1": {"a": 2, "c": 3}}
    assert sorted(discover.pending) == [("t1", "b"), ("t2", "d")]
    assert discover.counts[consensus.STATUS_AGREE] == 2
    assert discover.counts[consensus.STATUS_PENDING] == 2

    final = consensus.build_consensus(
        primary, secondary, {"t1": {"b": 1}, "t2": {"d": 0}})
    assert final.pending == []
    assert final.grades["t1"] == {"a": 2, "b": 1, "c": 3}  # median(1,3,1)=1
    assert final.grades["t2"] == {"d": 0}                   # median(0,3,0)=0
    assert final.n_resolved() == 4


def test_trec_qrel_lines_are_sorted_four_column_and_reloadable() -> None:
    """The published form must round-trip through `metrics.load_qrels_trec`.

    Sorted for stable diffs, 4-column `topic 0 chunk grade` so the consensus
    label set scores through the same loader as a single-prompt qrel — but via
    the TREC path, which does not impose single-prompt identity.
    """
    grades = {"t2": {"z": 1}, "t1": {"b": 3, "a": 0}}
    lines = consensus.trec_qrel_lines(grades)
    assert lines == ["t1 0 a 0", "t1 0 b 3", "t2 0 z 1"]


# ---------------------------------------------------------------------------
# CLI wiring — real argparse, real Config, real disk; NO Bedrock (no-spend).
# ---------------------------------------------------------------------------
def _seed_qrels(cfg, prompt_version: str, grades: dict[str, dict[str, int]]) -> None:
    """Write a `qrels-<pv>.jsonl` snapshot exactly as `judge-pool` would."""
    cache = store.JudgmentCache(prompt_version=prompt_version)
    for topic_id, chunks in grades.items():
        for chunk_id, grade in chunks.items():
            cache.grades[store.jkey(prompt_version, topic_id, chunk_id)] = grade
    cfg.ensure_dirs(cfg.cache_dir)
    cache.snapshot(store.cache_snapshot_path(cfg.cache_dir, prompt_version))


def _seed_pool(cfg, keys: list[tuple[str, str]]) -> Path:
    """A minimal sweep run dir: `pool.jsonl` + `pool-texts.jsonl` over `keys`."""
    run_dir = cfg.run_dir(RUN_ID)
    run_dir.mkdir(parents=True, exist_ok=True)
    texts = {chunk: f"passage text for {chunk}" for _t, chunk in keys}
    entries = [pool_mod.PoolEntry(
        topic_id=t, chunk_id=c, first_seen_config="k1_0.9__b_0.4",
        text_sha256=extract.sha256_text(texts[c])) for t, c in keys]
    pool_mod.write_pool(run_dir / cli.POOL_BASENAME, entries)
    extract.write_jsonl(run_dir / cli.POOL_TEXTS_BASENAME, (
        {"chunk_id": c, "text": texts[c]} for c in sorted(texts)))
    return run_dir


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the per-run file logging from leaking across CLI tests."""
    monkeypatch.setattr(cli, "setup_logging",
                        lambda *a, **k: logging.getLogger("bm25tune"))


def test_discover_pass_writes_the_escalation_pool_and_stops_without_spending(
        bm25_config, caplog: pytest.LogCaptureFixture) -> None:
    """The first `consensus` pass resolves agreements and halts before spend.

    It must (a) write the consensus qrels with only the settled labels, (b) emit
    an escalation run dir holding ONLY the conflicting pairs, and (c) exit 0
    while printing the metered judge-pool command — never auto-spend. The
    `no_network` autouse fixture guarantees no Bedrock call slipped in.
    """
    cfg = bm25_config
    keys = [("t1", "a"), ("t1", "b"), ("t1", "c")]
    _seed_pool(cfg, keys)
    _seed_qrels(cfg, "facet-name-v1", {"t1": {"a": 2, "b": 1, "c": 3}})
    _seed_qrels(cfg, "facet-rare3-v1", {"t1": {"a": 3, "b": 3, "c": 3}})

    with caplog.at_level(logging.INFO):
        code = cli.main(["consensus", "--run-id", RUN_ID,
                         "--primary", "facet-name-v1",
                         "--secondary", "facet-rare3-v1"])
    assert code == cli.EXIT_OK

    run_dir = cfg.run_dir(RUN_ID)
    qrels = metrics.load_qrels(run_dir / cli.CONSENSUS_QRELS_BASENAME)
    # a agree→2, c agree→3 resolved now; b conflict is pending (absent).
    assert qrels.grade("t1", "a") == 2
    assert qrels.grade("t1", "c") == 3
    assert qrels.grade("t1", "b") is None

    tie_dir = cfg.run_dir(f"{RUN_ID}{cli.CONSENSUS_TIEBREAK_SUFFIX}")
    tie_pool = pool_mod.read_pool(tie_dir / cli.POOL_BASENAME)
    assert [e.key for e in tie_pool] == [("t1", "b")]
    # The escalation pool carries only the conflicting chunk's text.
    tie_texts = {json.loads(line)["chunk_id"]
                 for line in (tie_dir / cli.POOL_TEXTS_BASENAME)
                 .read_text().splitlines()}
    assert tie_texts == {"b"}
    assert any("STOPS here BY DESIGN" in r.message for r in caplog.records)


def test_finalize_pass_folds_the_tiebreak_and_scores_through_qrels_override(
        bm25_config) -> None:
    """With the tiebreak grades present, the conflict resolves by median and the
    consensus qrels is complete and scoreable.

    This is the end of the cascade: the operator has run the escalation
    judge-pool, so `--tiebreak` now has a grade for the conflicting pair, and the
    finalized qrels must (a) contain every pair and (b) load through
    `metrics.load_qrels` for `score --qrels`.
    """
    cfg = bm25_config
    keys = [("t1", "a"), ("t1", "b"), ("t1", "c")]
    _seed_pool(cfg, keys)
    _seed_qrels(cfg, "facet-name-v1", {"t1": {"a": 2, "b": 1, "c": 3}})
    _seed_qrels(cfg, "facet-rare3-v1", {"t1": {"a": 3, "b": 3, "c": 3}})
    # The tiebreak prompt judged the escalation pool: b only.
    _seed_qrels(cfg, "facet-v1", {"t1": {"b": 1}})

    code = cli.main(["consensus", "--run-id", RUN_ID,
                     "--primary", "facet-name-v1",
                     "--secondary", "facet-rare3-v1",
                     "--tiebreak", "facet-v1"])
    assert code == cli.EXIT_OK

    run_dir = cfg.run_dir(RUN_ID)
    qrels = metrics.load_qrels(run_dir / cli.CONSENSUS_QRELS_BASENAME)
    assert qrels.grade("t1", "a") == 2
    assert qrels.grade("t1", "b") == 1   # median(1,3,1)
    assert qrels.grade("t1", "c") == 3
    assert qrels.n_judged() == 3

    manifest = json.loads((run_dir / cli.MANIFEST_BASENAME)
                          .read_text(encoding="utf-8"))
    assert manifest["consensus_tiebreak"] == "facet-v1"
    assert manifest["consensus_resolved_labels"] == 3


def test_the_per_pair_audit_trail_records_every_vote_and_status(
        bm25_config) -> None:
    """`consensus-pairs.jsonl` must trace each label back to the votes behind it.

    A consensus grade with no record of the votes is unfalsifiable; the audit
    file is what lets a reader see *why* a pair agreed, escalated, or resolved.
    """
    cfg = bm25_config
    keys = [("t1", "a"), ("t1", "b")]
    _seed_pool(cfg, keys)
    _seed_qrels(cfg, "facet-name-v1", {"t1": {"a": 2, "b": 0}})
    _seed_qrels(cfg, "facet-rare3-v1", {"t1": {"a": 3, "b": 3}})

    cli.main(["consensus", "--run-id", RUN_ID, "--primary", "facet-name-v1",
              "--secondary", "facet-rare3-v1"])

    rows = {json.loads(line)["chunk_id"]: json.loads(line)
            for line in (cfg.run_dir(RUN_ID) / cli.CONSENSUS_PAIRS_BASENAME)
            .read_text().splitlines()}
    assert rows["a"]["status"] == consensus.STATUS_AGREE
    assert rows["a"]["grades"] == [2, 3] and rows["a"]["consensus"] == 2
    assert rows["b"]["status"] == consensus.STATUS_PENDING
    assert rows["b"]["grades"] == [0, 3] and rows["b"]["consensus"] is None


def test_a_conflict_absent_from_the_sweep_pool_is_refused_not_dropped(
        bm25_config) -> None:
    """A conflicting pair missing from the run's pool means the qrels were judged
    over a different pool — refuse rather than silently drop it.

    A dropped conflict would revert to its unresolved primary grade in scoring,
    a wrong label that looks like a resolved one.
    """
    cfg = bm25_config
    _seed_pool(cfg, [("t1", "a")])  # pool has only 'a'
    _seed_qrels(cfg, "facet-name-v1", {"t1": {"a": 2, "b": 1}})
    _seed_qrels(cfg, "facet-rare3-v1", {"t1": {"a": 3, "b": 3}})  # b conflicts

    code = cli.main(["consensus", "--run-id", RUN_ID, "--primary",
                     "facet-name-v1", "--secondary", "facet-rare3-v1"])
    assert code == cli.EXIT_ERROR


def test_a_missing_prompt_snapshot_is_a_hard_error_with_the_judge_command(
        bm25_config, caplog: pytest.LogCaptureFixture) -> None:
    """Combining a prompt that was never judged is the failure that looks like
    success — it must error, and name the judge-pool command that fixes it.
    """
    cfg = bm25_config
    _seed_pool(cfg, [("t1", "a")])
    _seed_qrels(cfg, "facet-name-v1", {"t1": {"a": 2}})
    # facet-rare3-v1 snapshot deliberately not seeded.

    with caplog.at_level(logging.ERROR):
        code = cli.main(["consensus", "--run-id", RUN_ID, "--primary",
                         "facet-name-v1", "--secondary", "facet-rare3-v1"])
    assert code == cli.EXIT_ERROR
    assert any("judge-pool" in r.message and "facet-rare3-v1" in r.message
               for r in caplog.records)
