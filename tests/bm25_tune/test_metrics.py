"""What `metrics.py` defends: that the numbers the whole experiment turns on
mean what the report says they mean.

The sweep's conclusion is a *difference* between grid cells, and PLAN §3.4 warns
that difference will be small — the calibrated judge piles grades up at 2. At
that scale every convention is load-bearing, and each of the following mistakes
produces a plausible-looking matrix that is simply wrong, with no symptom:

- **rank base.** 0-based ranks make rank 1's discount `1/log2(1) = inf`; the
  usual "fix" (`1/log2(rank + 2)`) shifts every position by one and moves every
  reported nDCG by ~1-3 %.
- **gain convention.** `2**g - 1` and `g` disagree by several points on the same
  ranking, and can order two configs differently. Both are reported for exactly
  that reason, so the report has to name which one it quotes.
- **ideal construction.** The ideal comes from the *topic's* whole pooled qrel,
  not from the query's own retrieved set (PLAN §5.5). Getting this wrong would not
  raise; it would give each config its own denominator and turn every paired
  delta into a mix of "ranked better" and "found a different ceiling".
- **unjudged handling.** Unjudged = 0, which silently penalizes an under-judged
  config; the `judged@10` coverage column is the only thing that distinguishes
  "worse ranking" from "not finished judging".
- **binarization threshold.** The pre-registered secondaries fix `>= 2` for the
  binarized nDCG and Recall and require MAP at **both** `>= 1` and `>= 2`
  (PLAN §3.3). A threshold applied to the wrong metric silently answers a
  different question.

So the tests here are written against **hand-computed** values, not against
whatever the code returns. The primary worked example (three documents, four
judged chunks) is carried out longhand in `test_ndcg10_exp_matches_the_hand_worked_example`
and reused throughout; it was additionally cross-checked against
`sklearn.metrics.ndcg_score` in an ephemeral env (agreement to 1e-15 on a
full-topic ranking, where sklearn's per-query ideal coincides with ours).

The file-format tests matter for a different reason: `score` is the one stage
that can be re-run for free, so it must survive every shape a resumed or
concurrent sweep can leave on disk — out-of-order rank rows, duplicate
`(qid, docid)` pairs, `grade: null` parse failures in the cache snapshot.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pytest

from bm25tune import metrics as M

# The worked example every nDCG test below refers back to. Four judged chunks in
# one topic, three of them retrieved.
TOPIC_GRADES = {"A": 3, "B": 0, "C": 2, "D": 1}
RANKING = ["A", "B", "C"]
D2 = 1.0 / math.log2(3)  # rank-2 discount, 0.6309297535714575
D3 = 1.0 / math.log2(4)  # rank-3 discount, exactly 0.5
D4 = 1.0 / math.log2(5)  # rank-4 discount, 0.43067655807339306


# ---------------------------------------------------------------------------
# Gains and the discount
# ---------------------------------------------------------------------------
def test_exponential_gain_is_the_burges_form() -> None:
    """`2**g - 1` -> 0, 1, 3, 7 — the reason exp gain is the primary.

    The 3-vs-2 reward is 7 vs 3 (a factor 2.33) where linear gain gives 3 vs 2
    (1.5). PLAN §3.4 expects the judge's grades to bunch at 2, so the sweep's
    discrimination lives almost entirely in the few 3s; a gain that flattens them
    throws away the signal the experiment is measuring.
    """
    assert [M.exp_gain(g) for g in (0, 1, 2, 3)] == [0.0, 1.0, 3.0, 7.0]


def test_linear_gain_is_the_trec_eval_form() -> None:
    """`gain = g` — this is `trec_eval`'s `ndcg_cut_10`, reported for comparability.

    Without a linear-gain column nothing in the report can be lined up against a
    published TREC number, and a reader would reasonably assume the primary
    column already was one.
    """
    assert [M.linear_gain(g) for g in (0, 1, 2, 3)] == [0.0, 1.0, 2.0, 3.0]


def test_binary_gain_thresholds_at_the_value_given_not_above_it() -> None:
    """`grade >= threshold`, inclusive — an off-by-one here moves every grade-2.

    Grade 2 is the modal label (PLAN §3.4), so an exclusive comparison would
    reclassify the *majority* of relevant chunks as non-relevant and every
    binarized secondary would collapse towards zero.
    """
    strict = M.binary_gain(2)
    assert [strict(g) for g in (0, 1, 2, 3)] == [0.0, 0.0, 1.0, 1.0]
    loose = M.binary_gain(1)
    assert [loose(g) for g in (0, 1, 2, 3)] == [0.0, 1.0, 1.0, 1.0]


def test_discount_uses_one_based_ranks() -> None:
    """`1/log2(rank+1)`: rank 1 -> 1.0, rank 3 -> exactly 0.5.

    Rank 1 scoring exactly 1.0 is the fingerprint of the correct rank base: with
    0-based ranks it is infinite, and with the `rank+2` "fix" it is 0.63. The
    rank-3 value being exactly 0.5 pins the same thing from the other side.
    """
    assert M.discount(1) == 1.0
    assert M.discount(2) == pytest.approx(0.6309297535714575, abs=1e-15)
    assert M.discount(3) == 0.5


def test_discount_refuses_a_zero_or_negative_rank() -> None:
    """A 0-based caller must crash, not silently produce `inf`.

    `1/log2(0+1)` is a ZeroDivisionError and `1/log2(1)` is `inf`; either would
    propagate into a DCG as `inf` or `nan` and poison one config's mean while the
    others looked fine.
    """
    with pytest.raises(M.MetricsError):
        M.discount(0)
    with pytest.raises(M.MetricsError):
        M.discount(-1)


# ---------------------------------------------------------------------------
# The worked example
# ---------------------------------------------------------------------------
def test_ndcg10_exp_matches_the_hand_worked_example() -> None:
    """The primary metric, computed longhand for topic {A:3, B:0, C:2, D:1}.

    Ranking `[A, B, C]`, exponential gain `2**g - 1`, discount `1/log2(rank+1)`:

        DCG  = (2^3-1)/log2(2) + (2^0-1)/log2(3) + (2^2-1)/log2(4)
             = 7*1.0        + 0*0.63093      + 3*0.5
             = 8.5

    The ideal is the **topic's** top-10 grades sorted descending — `[3, 2, 1, 0]`,
    which includes `D`, a chunk this ranking never retrieved:

        IDCG = 7*1.0 + 3*0.6309297535714575 + 1*0.5 + 0*0.43067655807339306
             = 7 + 1.8927892607143725 + 0.5
             = 9.392789260714373

        nDCG@10 = 8.5 / 9.392789260714373 = 0.9049495058460971

    Every one of those three lines is a place a rewrite can go wrong while still
    returning a number in [0, 1], which is why the intermediate DCG and IDCG are
    asserted separately rather than only the ratio.
    """
    graded = [TOPIC_GRADES[c] for c in RANKING]
    assert M.dcg(graded, M.exp_gain) == pytest.approx(8.5, abs=1e-12)
    ideal = M.ideal_grades(TOPIC_GRADES)
    assert ideal == [3, 2, 1, 0]
    assert M.dcg(ideal, M.exp_gain) == pytest.approx(
        7 + 3 * D2 + 1 * D3 + 0 * D4, abs=1e-12)
    assert M.dcg(ideal, M.exp_gain) == pytest.approx(9.392789260714373,
                                                     abs=1e-12)
    assert M.ndcg_at_k(graded, TOPIC_GRADES) == pytest.approx(
        0.9049495058460971, abs=1e-12)


def test_ndcg10_linear_differs_from_exponential_on_the_same_ranking() -> None:
    """The same ranking, linear gain: DCG 4.0 / IDCG 4.7618595 = 0.8400080.

        DCG  = 3*1.0 + 0*0.63093 + 2*0.5                      = 4.0
        IDCG = 3*1.0 + 2*0.6309297535714575 + 1*0.5 + 0*...    = 4.761859507142915
        nDCG = 0.8400079830158563

    0.840 vs the primary's 0.905 on *identical input* is the whole argument for
    printing both columns: a report that quotes "nDCG@10 = 0.84" without naming
    the gain convention is not reproducible, and the two can rank two configs
    differently when the difference between them is a few thousandths.
    """
    graded = [TOPIC_GRADES[c] for c in RANKING]
    assert M.dcg(graded, M.linear_gain) == pytest.approx(4.0, abs=1e-12)
    assert M.dcg(M.ideal_grades(TOPIC_GRADES), M.linear_gain) == pytest.approx(
        3 + 2 * D2 + 1 * D3, abs=1e-12)
    assert M.ndcg_at_k(graded, TOPIC_GRADES, gain=M.linear_gain) == (
        pytest.approx(0.8400079830158563, abs=1e-12))


def test_ndcg10_binarized_at_2_drops_the_grade_1_chunk() -> None:
    """Binarized >=2: `D` (grade 1) leaves both the ranking and the ideal.

        DCG  = 1*1.0 + 0*0.63093 + 1*0.5      = 1.5
        IDCG = 1*1.0 + 1*0.6309297535714575   = 1.6309297535714575
        nDCG = 0.9197207891481876

    The ideal shrinking too is the part worth pinning: binarizing only the
    retrieved grades while normalizing by the graded ideal would produce a
    ratio that is not an nDCG at all, and on a qrel with many 1s it can exceed 1.
    """
    graded = [TOPIC_GRADES[c] for c in RANKING]
    gain = M.binary_gain(2)
    assert M.dcg(graded, gain) == pytest.approx(1.5, abs=1e-12)
    assert M.dcg(M.ideal_grades(TOPIC_GRADES), gain) == pytest.approx(
        1 + D2, abs=1e-12)
    assert M.ndcg_at_k(graded, TOPIC_GRADES, gain=gain) == pytest.approx(
        0.9197207891481876, abs=1e-12)


# ---------------------------------------------------------------------------
# The topic-level ideal, and what it deliberately costs
# ---------------------------------------------------------------------------
def test_the_ideal_comes_from_the_topic_qrel_not_the_retrieved_set() -> None:
    """A query that retrieves only its best chunk still scores below 1.0.

    Ranking `[A]` alone is a *perfect* ranking of what it retrieved, yet it
    scores 7/9.3928 = 0.745 because the topic's ideal also contains C and D. This
    is PLAN §5.5's deliberate deflation, and it is the single property that makes
    the paired test in `stats.py` clean: the denominator belongs to the topic, so
    it is identical for every config and cancels out of every delta.

    An implementation that built the ideal from the query's own retrieved grades
    would return exactly 1.0 here — indistinguishable from correct on any
    single-config run, and quietly fatal to every comparison.
    """
    perfect_of_what_it_got = M.ndcg_at_k([3], TOPIC_GRADES)
    assert perfect_of_what_it_got == pytest.approx(7 / 9.392789260714373,
                                                   abs=1e-12)
    assert perfect_of_what_it_got < 1.0
    # And the deflation is a property of the topic, not of the ranking length:
    # the same single hit against a topic whose pool is only that chunk is 1.0.
    assert M.ndcg_at_k([3], {"A": 3}) == pytest.approx(1.0, abs=1e-12)


def test_a_ranking_that_reproduces_the_topic_ideal_scores_exactly_one() -> None:
    """The ceiling is reachable — 1.0 when the ranking *is* the topic's ideal.

    Together with the previous test this brackets the normalization: deflated for
    a partial ranking, exactly 1.0 for the complete one. If only the deflation
    property were tested, a scorer that divided by a too-large constant would
    pass while never being able to reward a perfect ranking.
    """
    graded = [3, 2, 1, 0]
    for gain in (M.exp_gain, M.linear_gain, M.binary_gain(2)):
        assert M.ndcg_at_k(graded, TOPIC_GRADES, gain=gain) == pytest.approx(
            1.0, abs=1e-12)


def test_a_topic_with_no_relevant_chunk_yields_none_not_zero() -> None:
    """An all-zero topic makes nDCG undefined; the value is `None`.

    0.0 would be a lie in the direction that matters: it says "this config
    ranked nothing useful" when the truth is "there was nothing useful to rank",
    and averaging it in drags every config's mean down by an amount set by the
    qrel rather than by the config. `ConfigScore.defined` then records how many
    queries each metric was actually computed on, so the exclusion is visible in
    `scores.csv` rather than inferred.
    """
    assert M.ndcg_at_k([0, 0], {"A": 0, "B": 0}) is None
    # The same topic can be undefined under one gain and defined under another:
    # a topic of grade-1 chunks has no non-zero ideal at the >=2 binarization,
    # while exp/linear gain score it normally. So "undefined" is a property of
    # (topic, gain), which is why `defined` is tracked per metric, not per query.
    only_ones = {"A": 1, "B": 1}
    assert M.ndcg_at_k([1], only_ones, gain=M.binary_gain(2)) is None
    assert M.ndcg_at_k([1], only_ones) == pytest.approx(1 / (1 + D2), abs=1e-12)


def test_ideal_grades_truncates_at_the_cutoff() -> None:
    """Only the topic's top-`k` grades form the ideal — 10 by default.

    A pooled topic can carry 100+ judged chunks; normalizing an nDCG@10 by an
    IDCG over all of them would make the metric unreachable by construction and
    shrink every difference between configs towards the noise floor.
    """
    big = {f"c{i}": (3 if i < 20 else 0) for i in range(40)}
    assert M.ideal_grades(big) == [3] * 10
    assert M.ideal_grades(big, k=3) == [3, 3, 3]


# ---------------------------------------------------------------------------
# Unjudged handling
# ---------------------------------------------------------------------------
def test_unjudged_chunks_score_gain_zero() -> None:
    """A chunk absent from the qrel contributes nothing (PLAN §5.5).

    With pooled judging to depth 30 this should never happen, so when it does the
    cause is a pooling or scoring mismatch — which is precisely why it must not
    raise: a partially judged pool has to remain scoreable (PLAN §5.7 layer 3).
    """
    qrels = M.Qrels(grades={"t1": {"A": 3}})
    assert qrels.grade("t1", "ZZZ") is None
    assert qrels.graded("t1", "ZZZ") == 0
    assert qrels.graded("nosuchtopic", "A") == 0


def test_judged_at_10_reports_the_coverage_that_the_zeros_hide() -> None:
    """`judged@10` separates "ranked badly" from "not finished judging".

    The penalty for an unjudged hit is identical to the penalty for a genuinely
    irrelevant one, so without this counter a run stopped early by the budget
    guard would look like a ranking regression. Here 2 of 3 top hits are judged.
    """
    qrels = M.Qrels(grades={"t1": {"A": 3, "C": 2}})
    score = M.score_query("cfg", "t1::abc", ["A", "UNJUDGED", "C"], qrels)
    assert score.judged_at_10 == 2
    assert score.retrieved == 3
    assert score.coverage_at_10 == pytest.approx(2 / 3)
    # The unjudged chunk was scored as grade 0, i.e. it did not vanish from the
    # ranking: rank 3 keeps C's 0.5 discount rather than being promoted to 0.63.
    assert score.metrics["ndcg10_exp"] == pytest.approx(
        (7 + 3 * 0.5) / (7 + 3 * D2), abs=1e-12)


def test_coverage_is_none_when_nothing_was_retrieved() -> None:
    """An empty ranking has no coverage to report — `None`, not 1.0 or 0.0.

    A missing query in a run file becomes an empty ranking (never a skip), and
    counting that as 100 % judged would let a config with failed queries report
    perfect coverage.
    """
    qrels = M.Qrels(grades={"t1": {"A": 3}})
    score = M.score_query("cfg", "t1::abc", [], qrels)
    assert score.retrieved == 0
    assert score.coverage_at_10 is None
    assert score.metrics["ndcg10_exp"] == 0.0


# ---------------------------------------------------------------------------
# The two precision@10 measures (secondary/exploratory, added 2026-07-31)
# ---------------------------------------------------------------------------
def test_precision10_and_graded_precision10_on_the_worked_example() -> None:
    """Both hand-computed on the same {A:3, B:0, C:2, D:1} / [A, B, C] example.

    Longhand, with the flat-10 denominator:

        graded top-10 = [3, 0, 2] (three retrieved, seven empty slots)
        p10_bin2 = #{g >= 2} / 10 = |{A(3), C(2)}| / 10 = 2 / 10  = 0.2
        gp10     = sum(g) / (10 * 3) = (3 + 0 + 2) / 30 = 5 / 30 ~= 0.166667

    Reusing the nDCG worked example on purpose: the same ranking scores 0.905 on
    `ndcg10_exp` and 0.2 on `p10_bin2`, which is the deflation gap in one line —
    nDCG is normalized by a topic-level ideal, these are not, so the two columns
    must never be read on the same scale.
    """
    graded = [TOPIC_GRADES[c] for c in RANKING]
    assert M.precision_at_k(graded, 10, 2) == pytest.approx(0.2, abs=1e-15)
    assert M.graded_precision_at_k(graded, 10) == pytest.approx(5 / 30,
                                                                abs=1e-15)


def test_both_precisions_reach_1_only_on_a_full_top10_of_grade_3() -> None:
    """`gp10 == p10_bin2 == 1.0` iff ten slots of the maximum grade.

    This is the "reduces to P@10" property that justifies calling `gp10` a
    precision at all: at the ceiling the graded and binary forms must agree
    exactly, so a reader who only understands P@10 is not misled by the column
    next to it. Ten grade-2s show they part company below the ceiling — `gp10`
    reads 2/3 there while `p10_bin2` still claims a perfect 1.0.
    """
    assert M.graded_precision_at_k([3] * 10) == 1.0
    assert M.precision_at_k([3] * 10) == 1.0
    assert M.graded_precision_at_k([2] * 10) == pytest.approx(2 / 3)
    assert M.precision_at_k([2] * 10) == 1.0


def test_both_precisions_are_zero_on_an_all_grade_0_top10() -> None:
    """The floor is 0.0 and it is a real 0.0, not `None`.

    Unlike Recall/MAP there is no qrel-derived denominator that can vanish, so
    "the config found nothing relevant" is a *measured* zero and belongs in the
    mean. Reporting `None` here would quietly drop the worst configs from the
    aggregate and flatter the grid.
    """
    assert M.graded_precision_at_k([0] * 10) == 0.0
    assert M.precision_at_k([0] * 10) == 0.0


def test_grade_1_only_ranking_keeps_signal_in_gp10_that_p10_discards() -> None:
    """Ten grade-1 chunks: `p10_bin2 == 0.0` but `gp10 == 1/3`.

    The single strongest reason to report both. Binarizing at >= 2 makes a ranking
    of ten marginally-relevant chunks indistinguishable from ten irrelevant ones,
    so a k1/b cell that trades grade-0s for grade-1s registers as *no change* on
    `p10_bin2`; `gp10` sees it. Conversely `p10_bin2` is the one a reader can
    interpret without knowing the rubric — hence both columns, not one.
    """
    assert M.precision_at_k([1] * 10, 10, 2) == 0.0
    assert M.graded_precision_at_k([1] * 10) == pytest.approx(1 / 3)
    # ...and the loose threshold is not a substitute: it flattens 1 and 3 again.
    assert M.precision_at_k([1] * 10, 10, 1) == 1.0


def test_both_precisions_are_indifferent_to_rank_while_ndcg_is_not() -> None:
    """Permuting the top 10 moves `ndcg10_exp` and leaves both precisions fixed.

    This is the property that earns them a place *next to* nDCG rather than
    instead of it, so it is pinned rather than assumed: the precisions measure the
    quality of the retrieved **set**, nDCG measures its **ordering**. A grid cell
    where nDCG moves but these do not has only reshuffled the same ten chunks —
    a diagnosis the report cannot make from nDCG alone. If a future refactor
    sneaks a discount into either measure, this test is what fails.
    """
    topic = {f"c{i}": g for i, g in enumerate([3, 3, 2, 2, 2, 1, 1, 0, 0, 0])}
    best = [3, 3, 2, 2, 2, 1, 1, 0, 0, 0]
    worst = list(reversed(best))
    assert M.graded_precision_at_k(best) == M.graded_precision_at_k(worst)
    assert M.precision_at_k(best) == M.precision_at_k(worst)
    # sum(3,3,2,2,2,1,1,0,0,0) = 14, over 10 slots x GRADE_MAX 3.
    assert M.graded_precision_at_k(best) == pytest.approx(14 / 30)
    assert M.precision_at_k(best) == pytest.approx(0.5)  # five chunks at >= 2
    # Same multiset, and nDCG separates them by a wide margin.
    ndcg_best = M.ndcg_at_k(best, topic)
    ndcg_worst = M.ndcg_at_k(worst, topic)
    assert ndcg_best == pytest.approx(1.0)  # `best` *is* the topic's ideal
    assert ndcg_worst is not None and ndcg_worst < 0.75


def test_precisions_divide_by_a_flat_10_not_by_what_was_retrieved() -> None:
    """A 3-hit ranking is scored over 10 slots, not over 3 (PLAN §5.5).

    The denominator decision, pinned from the direction it can be got wrong.
    `[3, 0, 2]` scores 0.2 / 0.1667 over a flat 10; over `min(retrieved, 10) = 3`
    it would score 0.667 / 0.556 — so a config that retrieved almost nothing but
    got it right would *outrank* one that filled all ten slots with nine relevant
    chunks (0.9). The empty slots belong to the config, not to the evaluation.
    Contrast `coverage_at_10`, which deliberately does divide by `min(retrieved,
    10)` because an unfilled slot cannot be unjudged.
    """
    graded = [3, 0, 2]
    assert M.precision_at_k(graded, 10, 2) == pytest.approx(0.2)
    assert M.precision_at_k(graded, 10, 2) != pytest.approx(2 / 3)
    assert M.graded_precision_at_k(graded, 10) == pytest.approx(5 / 30)
    assert M.graded_precision_at_k(graded, 10) != pytest.approx(5 / 9)
    # An empty ranking is 0.0 on both — a query the config failed on scored
    # nothing, and must not be silently excluded from the mean.
    assert M.precision_at_k([], 10, 2) == 0.0
    assert M.graded_precision_at_k([], 10) == 0.0


def test_precisions_ignore_everything_past_the_cutoff() -> None:
    """Rank 11 contributes nothing at k=10, and widening k lets it in.

    An off-by-one in the slice would silently make the columns P@11 while the
    header still said 10 — undetectable in the output and enough to change which
    grid cell wins.
    """
    ranked = [0] * 10 + [3, 3]
    assert M.precision_at_k(ranked, 10, 2) == 0.0
    assert M.graded_precision_at_k(ranked, 10) == 0.0
    assert M.precision_at_k(ranked, 12, 2) == pytest.approx(2 / 12)
    assert M.graded_precision_at_k(ranked, 12) == pytest.approx(6 / 36)


def test_precisions_are_none_only_when_the_cutoff_itself_is_meaningless() -> None:
    """`k < 1` -> `None`, matching the module's undefined-is-never-0.0 rule.

    The only way to make these undefined is to ask for zero slots; a `0.0` there
    would be a division-by-zero result dressed up as a measurement, and would
    enter the mean as if a config had been evaluated.
    """
    assert M.precision_at_k([3, 3], 0, 2) is None
    assert M.graded_precision_at_k([3, 3], 0) is None
    assert M.precision_at_k([3, 3], -1, 2) is None
    assert M.graded_precision_at_k([3, 3], -1) is None


def test_gp10_is_bounded_by_the_validated_grade_range() -> None:
    """`GRADE_MAX` is the divisor, so `gp10 <= 1` follows from grade validation.

    The bound is not enforced in `graded_precision_at_k` — it is inherited from
    `_coerce_grade` rejecting grades outside 0-3. This test states that
    dependency explicitly, because relaxing the grade validation (e.g. to accept
    a judge emitting 4) would silently make this measure exceed 1.0 rather than
    raise.
    """
    assert M.GRADE_MAX == 3
    with pytest.raises(M.MetricsError, match="outside the rubric"):
        M._coerce_grade(4, "test")
    # A hypothetical out-of-range grade would breach the bound — hence the guard.
    assert M.graded_precision_at_k([4] * 10) > 1.0


def test_the_two_precisions_are_exploratory_not_pre_registered() -> None:
    """They are in `METRIC_NAMES` but out of `PRE_REGISTERED_METRICS`.

    PLAN §3.3 pre-registers six metrics; these two were added 2026-07-31, after
    the fact, at the user's request. Keeping the two tuples distinct is what stops
    a later reader from quoting a `gp10` p-value as a confirmatory result, and
    keeps §6.4's Bonferroni family at 3 candidate-vs-baseline comparisons — which
    counts configs, not metrics.
    """
    from bm25tune import stats as S

    assert set(M.EXPLORATORY_METRICS) == {"gp10", "p10_bin2"}
    assert set(M.METRIC_NAMES) == (set(M.PRE_REGISTERED_METRICS)
                                   | set(M.EXPLORATORY_METRICS))
    assert not set(M.PRE_REGISTERED_METRICS) & set(M.EXPLORATORY_METRICS)
    assert M.PRIMARY_METRIC == "ndcg10_exp"  # unchanged by the addition
    assert S.N_COMPARISONS == 3
    assert any("EXPLORATORY" in note for note in S.STANDING_NOTES)


def test_the_precision_columns_sit_between_ndcg_and_recall() -> None:
    """Column order: nDCG first, then the precisions, then Recall/MAP.

    `ndcg10_exp` must stay column one because readers stop there, and the new
    columns go next so they are seen without scrolling past six others. Order is
    a single tuple used by every writer, so pinning it here covers `scores.csv`,
    `scores.md` and `scores-per-query.csv` at once.
    """
    assert M.METRIC_NAMES == ("ndcg10_exp", "ndcg10_lin", "ndcg10_bin2",
                              "gp10", "p10_bin2", "recall10_bin2",
                              "map30_bin1", "map30_bin2")
    assert M.METRIC_NAMES[0] == M.PRIMARY_METRIC
    assert set(M.METRIC_LABELS) == set(M.METRIC_NAMES)


def test_score_query_reports_the_precisions_even_on_an_unjudgeable_topic() -> None:
    """They are defined on a topic where Recall/MAP are not — 0.0 vs `None`.

    The asymmetry is deliberate and shows up in `scores.csv` as `p10_bin2_n`
    counting more queries than `recall10_bin2_n`. A topic with no relevant chunk
    has nothing to recall (undefined) but the config still filled ten slots with
    nothing useful (a measured zero), so the two columns legitimately have
    different `n` and a reader must not treat that as a bug.
    """
    qrels = M.Qrels(grades={"t1": {"A": 0, "B": 0}})
    score = M.score_query("cfg", "t1::abc", ["A", "B"], qrels)
    assert score.metrics["recall10_bin2"] is None
    assert score.metrics["ndcg10_exp"] is None
    assert score.metrics["gp10"] == 0.0
    assert score.metrics["p10_bin2"] == 0.0


# ---------------------------------------------------------------------------
# Recall and MAP, at both thresholds
# ---------------------------------------------------------------------------
def test_recall10_divides_by_the_topics_relevant_count() -> None:
    """Denominator = the topic's judged-relevant count, not `min(R, 10)`.

    `trec_eval`'s `num_rel` convention (PLAN §5.5). With a pooled topic-level
    qrel R is routinely far above 10, so Recall@10 is capped well below 1 — the
    absolute value is meaningless and only the config-to-config difference is
    interpretable. Using `min(R, 10)` instead would rescale every topic by a
    different factor depending on its pool size.
    """
    topic = {f"r{i}": 2 for i in range(20)}
    topic["junk"] = 0
    ranked = [2] * 10  # 10 relevant chunks in the top 10
    assert M.recall_at_k(ranked, topic, 10, 2) == pytest.approx(10 / 20)
    assert M.count_relevant(topic, 2) == 20
    assert M.count_relevant(topic, 1) == 20
    assert M.count_relevant(topic, 3) == 0


def test_recall10_threshold_changes_both_numerator_and_denominator() -> None:
    """At >=1 the grade-1 chunk counts on both sides of the fraction.

    For {A:3, B:0, C:2, D:1} and ranking [A, B, C]:
      >=2 -> 2 of 2 relevant retrieved = 1.0
      >=1 -> 2 of 3 relevant retrieved = 0.666...
    A threshold applied to only one side would give 2/2 = 1.0 at both, hiding the
    fact that D was never found.
    """
    graded = [TOPIC_GRADES[c] for c in RANKING]
    assert M.recall_at_k(graded, TOPIC_GRADES, 10, 2) == pytest.approx(1.0)
    assert M.recall_at_k(graded, TOPIC_GRADES, 10, 1) == pytest.approx(2 / 3)


def test_recall_is_none_when_the_topic_has_no_relevant_chunk() -> None:
    """0/0 is undefined, and reporting 0.0 would punish the config for the qrel."""
    assert M.recall_at_k([0], {"A": 0}, 10, 2) is None
    assert M.recall_at_k([1], {"A": 1}, 10, 2) is None


def test_map30_at_both_pre_registered_thresholds() -> None:
    """MAP@30 hand-computed at >=1 and >=2 (PLAN §3.3 requires both).

    Ranking `[A(3), B(0), C(2)]` over topic {A:3, B:0, C:2, D:1}:

      >=2: relevant at ranks 1 and 3; R (topic-wide) = 2
           AP = (1/1 + 2/3) / 2 = 1.6666.../2 = 0.8333333333333333
      >=1: relevant at ranks 1 and 3; R = 3 (D is relevant but unretrieved)
           AP = (1/1 + 2/3) / 3 = 0.5555555555555555

    Reporting only one threshold would let the sweep's conclusion depend on an
    unstated binarization choice; the two differ by 0.28 on this tiny example.
    """
    graded = [TOPIC_GRADES[c] for c in RANKING]
    assert M.average_precision_at_k(graded, TOPIC_GRADES, 30, 2) == (
        pytest.approx((1.0 + 2 / 3) / 2, abs=1e-12))
    assert M.average_precision_at_k(graded, TOPIC_GRADES, 30, 1) == (
        pytest.approx((1.0 + 2 / 3) / 3, abs=1e-12))


def test_map_respects_the_cutoff_and_the_precision_denominator() -> None:
    """Only ranks <= k contribute, and precision@i uses the 1-based rank.

    A relevant chunk at rank 31 must not count at MAP@30, and `precision@i` must
    be `found/i` with `i` 1-based — a 0-based `i` divides by zero at the first
    relevant hit, and `found/(i+1)` deflates every AP by up to 50 %.
    """
    topic = {"x": 2, "y": 2}
    ranked = [2] + [0] * 29 + [2]  # rank 1 and rank 31
    assert M.average_precision_at_k(ranked, topic, 30, 2) == pytest.approx(
        (1.0 / 1) / 2, abs=1e-12)
    # Widen the cutoff and the rank-31 hit appears, at precision 2/31.
    assert M.average_precision_at_k(ranked, topic, 40, 2) == pytest.approx(
        (1.0 + 2 / 31) / 2, abs=1e-12)


def test_map_is_none_when_the_topic_has_no_relevant_chunk() -> None:
    """Same undefined-vs-zero rule as recall; asserted separately because the
    two use different code paths to the same denominator."""
    assert M.average_precision_at_k([0], {"A": 0}, 30, 2) is None


def test_score_query_computes_every_metric_in_one_pass() -> None:
    """All of `METRIC_NAMES` comes out of one call, none silently missing.

    `stats.py` iterates `METRIC_NAMES`, so a metric absent from this dict would
    be dropped from the report with no error — the pre-registration exists
    precisely to stop metrics being chosen after seeing the results. The same
    single pass is what makes the secondaries free to re-optimize on later: every
    column is derived from the cached grades at score time, so no metric ever
    needs a second judging run.
    """
    qrels = M.Qrels(grades={"t1": TOPIC_GRADES})
    score = M.score_query("cfg", "t1::abc", RANKING, qrels)
    assert set(score.metrics) == set(M.METRIC_NAMES)
    assert M.PRIMARY_METRIC == "ndcg10_exp"
    assert score.metrics["ndcg10_exp"] == pytest.approx(0.9049495058460971,
                                                        abs=1e-12)
    assert score.metrics["map30_bin1"] == pytest.approx(0.5555555555555555,
                                                        abs=1e-12)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def test_mean_of_topic_means_reweights_unequal_topics() -> None:
    """A 3-query topic counts as much as a 1-query one (PLAN §5.5).

    Topics contribute 3-16 keyword queries, so the plain query mean lets a large
    topic outvote five small ones. Here topic t1 scores 0.0 on three queries and
    t2 scores 1.0 on one: the query mean is 0.25, the topic mean 0.5. When the
    two aggregates disagree about the winner the honest report says so — which is
    only possible if both are computed.
    """
    scores = [
        M.QueryScore("c", "t1::a", "t1", 1, 1, {"m": 0.0}),
        M.QueryScore("c", "t1::b", "t1", 1, 1, {"m": 0.0}),
        M.QueryScore("c", "t1::c", "t1", 1, 1, {"m": 0.0}),
        M.QueryScore("c", "t2::a", "t2", 1, 1, {"m": 1.0}),
    ]
    assert M.mean(s.metrics["m"] for s in scores) == pytest.approx(0.25)
    assert M.mean_of_topic_means(scores, "m") == pytest.approx(0.5)


def test_aggregates_skip_none_and_count_what_they_used() -> None:
    """Undefined values are excluded from the mean and counted in `defined`.

    Without the count, two configs' means could be computed over different query
    counts and compared as if they were the same number. `<metric>_n` in
    `scores.csv` is what makes that detectable.
    """
    scores = [
        M.QueryScore("c", "t1::a", "t1", 1, 1, {"m": 1.0}),
        M.QueryScore("c", "t2::a", "t2", 1, 1, {"m": None}),
    ]
    assert M.mean_of_topic_means(scores, "m") == pytest.approx(1.0)
    assert M.mean([]) is None


def test_score_run_scores_a_missing_query_as_an_empty_ranking() -> None:
    """A query absent from the run file is scored 0, never skipped.

    A config that failed to retrieve for a query really did score nothing there.
    Skipping it would shrink that config's `n` and *raise* its mean — rewarding
    the failure — and the paired test would then be comparing different query
    sets under the same label.
    """
    qrels = M.Qrels(grades={"t1": TOPIC_GRADES, "t2": {"Z": 3}})
    run = M.RunFile(config="k1_0.9__b_0.4", path=None,
                    rankings={"t1::abc": RANKING})
    scored = M.score_run(run, qrels, ["t1::abc", "t2::xyz"])
    assert scored.n_queries == 2
    assert scored.defined["ndcg10_exp"] == 2
    assert scored.by_query["ndcg10_exp"] == pytest.approx(
        (0.9049495058460971 + 0.0) / 2, abs=1e-12)


def test_score_all_orders_the_matrix_best_primary_first() -> None:
    """The table is sorted by the primary metric, and keeps every cell.

    Sorting is a convenience; keeping every cell is the requirement (PLAN §7.4).
    A sweep that reported only its winner would be unfalsifiable — the
    neighbouring cells are the evidence that a peak is a peak and not the noise
    PLAN §3.4 warns about.
    """
    qrels = M.Qrels(grades={"t1": TOPIC_GRADES})
    good = M.RunFile("k1_1.2__b_0.4", None, {"t1::a": ["A", "C"]})
    bad = M.RunFile("k1_0.9__b_0.4", None, {"t1::a": ["B", "B"]})
    scored = M.score_all([bad, good], qrels, ["t1::a"])
    assert [s.config for s in scored] == ["k1_1.2__b_0.4", "k1_0.9__b_0.4"]
    assert len(scored) == 2


# ---------------------------------------------------------------------------
# Qrels I/O
# ---------------------------------------------------------------------------
def test_qrels_jsonl_reads_the_cache_snapshot_shape(tmp_path: Path) -> None:
    """The snapshot `store.py` writes is readable, jkey-only rows included.

    Scoring must not be the thing that blocks on a field rename in WP3's writer,
    so `topic_id`/`chunk_id` are taken from explicit fields when present and
    parsed out of the `jkey` otherwise — `jkey` is the cache's only mandatory key.

    The leading `kind: cache_meta` line is a header, not a judgment: read as one
    it has no topic and the whole snapshot would be refused.
    """
    from bm25tune import store

    assert M.CACHE_META_KIND == store.CACHE_META_KIND, (
        "metrics.py duplicates the header `kind` to keep its import graph a "
        "leaf; the two definitions must not drift")
    path = tmp_path / "qrels-facet-v1.jsonl"
    path.write_text("\n".join([
        json.dumps({"kind": store.CACHE_META_KIND,
                    "prompt_version": "facet-v1", "entries": 2}),
        json.dumps({"jkey": "facet-v1::t1::A", "prompt_version": "facet-v1",
                    "topic_id": "t1", "chunk_id": "A", "grade": 3}),
        json.dumps({"jkey": "facet-v1::t1::C", "grade": 2}),
    ]) + "\n")
    qrels = M.load_qrels_jsonl(path, "facet-v1")
    assert qrels.grades == {"t1": {"A": 3, "C": 2}}
    assert qrels.n_judged() == 2
    assert qrels.distribution() == {2: 1, 3: 1}


def test_qrels_jsonl_skips_null_grades_rather_than_scoring_them_zero(
        tmp_path: Path) -> None:
    """A `grade: null` row is a parse failure, not a judgment of 0.

    PLAN §5.4 records unparseable judge output as null. Reading it as 0 would
    manufacture a negative judgment nobody made and inflate `judged@10` at the
    same time — the pair of errors most likely to look like a real result.
    """
    path = tmp_path / "qrels-facet-v1.jsonl"
    path.write_text("\n".join([
        json.dumps({"jkey": "facet-v1::t1::A", "grade": 3}),
        json.dumps({"jkey": "facet-v1::t1::B", "grade": None}),
    ]) + "\n")
    qrels = M.load_qrels_jsonl(path, "facet-v1")
    assert qrels.grades == {"t1": {"A": 3}}
    assert qrels.grade("t1", "B") is None


def test_qrels_refuses_a_foreign_prompt_version(tmp_path: Path) -> None:
    """Mixing two prompt versions into one qrel is refused, not merged.

    This is the exact poisoning PLAN §5.3's namespaced cache exists to prevent: a
    `umbrela-v1` grade satisfying a `facet-v1` lookup yields a perfectly
    well-formed qrel for a label set that never existed, and no downstream check
    could detect it.
    """
    path = tmp_path / "qrels-facet-v1.jsonl"
    path.write_text(json.dumps({"jkey": "umbrela-v1::t1::A", "grade": 3}) + "\n")
    with pytest.raises(M.MetricsError, match="prompt version"):
        M.load_qrels_jsonl(path, "facet-v1")


def test_a_grade_outside_the_rubric_is_an_error_not_a_clamp(
        tmp_path: Path) -> None:
    """Grade 7 raises: `2**7 - 1 = 127` would silently rescale the topic's ideal.

    The rubric is 0-3 (PLAN §3.2), so anything else is a judge-parsing bug. A
    clamp would hide it; the deflated-but-consistent ideal that makes the paired
    test valid depends on every grade being in range.
    """
    path = tmp_path / "qrels-facet-v1.jsonl"
    path.write_text(json.dumps({"jkey": "facet-v1::t1::A", "grade": 7}) + "\n")
    with pytest.raises(M.MetricsError, match="outside the rubric"):
        M.load_qrels_jsonl(path, "facet-v1")


def test_qrels_round_trip_through_the_published_trec_form(
        tmp_path: Path) -> None:
    """The committed 4-column `qrels-<pv>.txt` reproduces the same scores.

    PLAN §7.4 commits the TREC form as the artifact a third party reproduces the
    matrix from. If scoring only worked off the JSONL cache, that committed file
    would be undereviewable decoration.
    """
    qrels = M.Qrels(grades={"t1": TOPIC_GRADES})
    path = tmp_path / "qrels-facet-v1.txt"
    assert M.write_qrels_trec(path, qrels) == 4
    assert path.read_text().splitlines()[0] == "t1 0 A 3"
    reloaded = M.load_qrels(path, "facet-v1")
    assert reloaded.grades == qrels.grades
    graded = [TOPIC_GRADES[c] for c in RANKING]
    assert M.ndcg_at_k(graded, reloaded.topic("t1")) == pytest.approx(
        0.9049495058460971, abs=1e-12)


def test_a_malformed_trec_qrels_line_is_rejected(tmp_path: Path) -> None:
    """3 columns instead of 4 raises rather than being parsed positionally.

    A qrels file whose columns shifted would still parse into *something*, giving
    a plausible matrix built from the wrong grades — the failure mode nothing
    downstream can catch.
    """
    path = tmp_path / "qrels.txt"
    path.write_text("t1 0 A\n")
    with pytest.raises(M.MetricsError, match="4 TREC qrels columns"):
        M.load_qrels_trec(path)


# ---------------------------------------------------------------------------
# Run-file I/O
# ---------------------------------------------------------------------------
def test_run_rows_are_ordered_by_the_rank_column_not_file_order(
        tmp_path: Path) -> None:
    """A resumed or concurrent sweep may interleave rows; rank wins.

    Trusting file order would score a shuffled ranking and produce nDCG that is
    wrong but entirely plausible — no exception, no warning, just a different
    winner.
    """
    path = tmp_path / "k1_0.9__b_0.4.txt"
    path.write_text("\n".join([
        "t1::a Q0 C 3 1.0 tag",
        "t1::a Q0 A 1 3.0 tag",
        "t1::a Q0 B 2 2.0 tag",
    ]) + "\n")
    run = M.load_trec_run(path)
    assert run.rankings["t1::a"] == ["A", "B", "C"]
    assert (run.k1, run.b) == (0.9, 0.4)
    assert run.config == "k1_0.9__b_0.4"


def test_a_duplicate_qid_docid_pair_is_dropped_and_counted(
        tmp_path: Path) -> None:
    """The best rank is kept and the duplicate is reported, not silently merged.

    A fan-out bug that emits a chunk twice inflates precision at every cutoff.
    Dropping it fixes the score; *counting* it is what surfaces the bug, since
    `duplicate_rows` lands in `scores.csv`.
    """
    path = tmp_path / "k1_0.9__b_0.4.txt"
    path.write_text("\n".join([
        "t1::a Q0 A 1 3.0 tag",
        "t1::a Q0 A 2 2.9 tag",
        "t1::a Q0 B 3 2.0 tag",
    ]) + "\n")
    run = M.load_trec_run(path)
    assert run.rankings["t1::a"] == ["A", "B"]
    assert run.duplicates == 1


def test_a_short_run_row_is_rejected(tmp_path: Path) -> None:
    """Fewer than 5 columns raises rather than being read positionally.

    `qid Q0 docid rank score tag` is the contract; a truncated line means the
    writer changed, and guessing which field is which would silently score the
    wrong chunk ids.
    """
    path = tmp_path / "run.txt"
    path.write_text("t1::a Q0 A 1\n")
    with pytest.raises(M.MetricsError, match="6 TREC run columns"):
        M.load_trec_run(path)


def test_an_unparseable_config_stem_still_scores(tmp_path: Path) -> None:
    """A renamed run file loses its k1/b columns but is not refused.

    WP2 owns the filename. A score table that refused to render because a stem
    gained a suffix would be a worse failure than a table with two blank columns,
    so the tolerance is deliberate — and the config keeps its stem as its key so
    nothing is silently merged.
    """
    path = tmp_path / "baseline-hosted.txt"
    path.write_text("t1::a Q0 A 1 3.0 tag\n")
    run = M.load_trec_run(path)
    assert (run.k1, run.b) == (None, None)
    assert run.config == "baseline-hosted"
    assert M.parse_config_stem("k1_0.9__b_0.4") == (0.9, 0.4)
    assert M.parse_config_stem("nonsense") == (None, None)


def test_load_run_dir_orders_by_grid_position(tmp_path: Path) -> None:
    """Run files come back in (k1, b) order so the matrix reads as a grid.

    Filesystem glob order is lexicographic, which puts `k1_1.2` before `k1_0.9`
    — a matrix a reader cannot scan for a ridge is a matrix that hides one.
    """
    for stem in ("k1_1.2__b_0.4", "k1_0.9__b_0.75", "k1_0.9__b_0.4"):
        (tmp_path / f"{stem}.txt").write_text("t1::a Q0 A 1 1.0 tag\n")
    runs = M.load_run_dir(tmp_path)
    assert [r.config for r in runs] == ["k1_0.9__b_0.4", "k1_0.9__b_0.75",
                                        "k1_1.2__b_0.4"]


def test_an_empty_trecruns_dir_is_an_error(tmp_path: Path) -> None:
    """Scoring nothing must fail loudly, not write an empty matrix.

    An empty `scores.csv` next to a green exit code is the worst possible
    outcome: it looks like the run was scored.
    """
    (tmp_path / "trecruns").mkdir()
    with pytest.raises(M.MetricsError, match="no \\*.txt run files"):
        M.load_run_dir(tmp_path / "trecruns")
    with pytest.raises(M.MetricsError, match="no trecruns dir"):
        M.load_run_dir(tmp_path / "absent")


def test_topic_is_recovered_from_the_qkey(tmp_path: Path) -> None:
    """`<topic_id>::<sha1[:12]>` — a run file is self-describing.

    That is why scoring needs no query file: the topic-level qrel is locatable
    from the TREC qid alone. A qid without the separator must raise, because
    guessing the topic would score the query against another topic's qrel.
    """
    assert M.topic_of_qkey("rag2026-17::a1b2c3d4e5f6") == "rag2026-17"
    with pytest.raises(M.MetricsError, match="no '::' separator"):
        M.topic_of_qkey("plain-qid")


# ---------------------------------------------------------------------------
# Output artifacts
# ---------------------------------------------------------------------------
def test_scores_csv_carries_every_metric_in_both_aggregations(
        tmp_path: Path) -> None:
    """Each metric contributes three columns: query mean, topic mean, and n.

    The full matrix is the deliverable (PLAN §7.4). Dropping the topic mean would
    hide the clustering disagreement PLAN §5.5 asks about; dropping `_n` would
    make two means computed over different query counts look comparable.
    """
    qrels = M.Qrels(grades={"t1": TOPIC_GRADES})
    run = M.RunFile("k1_0.9__b_0.4", None, {"t1::a": RANKING}, 0.9, 0.4)
    scored = M.score_all([run], qrels, ["t1::a"])
    path = M.write_scores_csv(tmp_path / "scores.csv", scored)
    header = path.read_text().splitlines()[0].split(",")
    for name in M.METRIC_NAMES:
        assert name in header
        assert f"{name}_topicmean" in header
        assert f"{name}_n" in header
    assert header[:3] == ["config", "k1", "b"]
    assert "judged_at_10" in header and "duplicate_rows" in header
    row = path.read_text().splitlines()[1].split(",")
    assert row[0] == "k1_0.9__b_0.4"


def test_scores_md_carries_the_deflation_caveat_with_the_numbers(
        tmp_path: Path) -> None:
    """The caveat is *in* the artifact, not only in the plan.

    A reader who opens `scores.md` and quotes an absolute nDCG has made the one
    mistake this metric design invites. PLAN §5.5 requires the warning to travel
    with the numbers, which means asserting it is present rather than trusting a
    convention.
    """
    qrels = M.Qrels(grades={"t1": TOPIC_GRADES})
    run = M.RunFile("k1_0.9__b_0.4", None, {"t1::a": RANKING}, 0.9, 0.4)
    scored = M.score_all([run], qrels, ["t1::a"])
    text = M.render_scores_md(scored, run_id="rid", prompt_version="facet-v1",
                              qrels=qrels, query_set="held-out", n_queries=1)
    assert "only differences between configs are" in text.lower()
    assert "judged@10" in text
    assert "`k1_0.9__b_0.4`" in text
    for name in M.METRIC_NAMES:
        assert name in text


def test_per_query_csv_makes_the_paired_tests_auditable(tmp_path: Path) -> None:
    """The per-(config, query) values behind every aggregate are persisted.

    `stats.json`'s paired tests are computed from exactly these numbers. Without
    the file they are only reproducible by re-running the scorer; with it they are
    checkable from the committed artifacts alone.
    """
    qrels = M.Qrels(grades={"t1": TOPIC_GRADES})
    run = M.RunFile("k1_0.9__b_0.4", None, {"t1::a": RANKING}, 0.9, 0.4)
    scored = M.score_all([run], qrels, ["t1::a"])
    path = M.write_per_query_csv(tmp_path / "per-query.csv", scored)
    lines = path.read_text().splitlines()
    assert lines[0].split(",")[:5] == ["config", "qkey", "topic_id",
                                       "retrieved", "judged_at_10"]
    assert lines[1].startswith("k1_0.9__b_0.4,t1::a,t1,3,3,")


def test_summary_lines_use_the_greppable_ndcg_prefix() -> None:
    """`[NDCG]` per config, so a sweep log is greppable (PLAN §5.6).

    The log is the live view of a multi-hour run; the prefixes are the contract
    between it and whoever is watching. A renamed prefix breaks the watcher
    silently.
    """
    from bm25tune.logging_setup import LOG_PREFIXES

    qrels = M.Qrels(grades={"t1": TOPIC_GRADES})
    run = M.RunFile("k1_0.9__b_0.4", None, {"t1::a": RANKING}, 0.9, 0.4)
    lines = M.summary_lines(M.score_all([run], qrels, ["t1::a"]))
    assert len(lines) == 1
    assert lines[0].startswith("[NDCG] ")
    assert "[NDCG]" in LOG_PREFIXES
    for name in M.METRIC_NAMES:
        assert f"{name}=" in lines[0]


# ---------------------------------------------------------------------------
# The `score` subcommand end to end
# ---------------------------------------------------------------------------
@pytest.fixture
def scoreable_run(tmp_path: Path) -> Path:
    """A data dir with a cache snapshot, a query file and two run files.

    Built by hand rather than by running WP2/WP3, so `score` is tested against the
    *documented* on-disk contract (PLAN §4.2) instead of against whatever the
    sibling writers currently emit — a divergence between the two is exactly the
    bug this catches.
    """
    (tmp_path / "judgments" / "cache").mkdir(parents=True)
    (tmp_path / "queries").mkdir(parents=True)
    trecruns = tmp_path / "runs" / "rid" / "trecruns"
    trecruns.mkdir(parents=True)

    (tmp_path / "judgments" / "cache" / "qrels-facet-v1.jsonl").write_text(
        "\n".join([json.dumps({"kind": M.CACHE_META_KIND,
                               "prompt_version": "facet-v1"})]
                  + [json.dumps({"jkey": f"facet-v1::t1::{c}", "grade": g})
                     for c, g in TOPIC_GRADES.items()]
                  + [json.dumps({"jkey": "facet-v1::t2::Z", "grade": 3})])
        + "\n")
    (tmp_path / "queries" / "keyword-1063.jsonl").write_text(
        "\n".join(json.dumps({"qkey": q, "topic_id": q.split("::")[0],
                              "topic": "n", "query": "q", "k_orig": 10})
                  for q in ("t1::aaa", "t2::bbb")) + "\n")
    for stem, order in (("k1_0.9__b_0.4", ["A", "B", "C"]),
                        ("k1_1.2__b_0.75", ["C", "A", "B"])):
        rows = [f"t1::aaa Q0 {c} {i} {1.0 / i:.6f} {stem}"
                for i, c in enumerate(order, start=1)]
        rows.append(f"t2::bbb Q0 Z 1 1.000000 {stem}")
        (trecruns / f"{stem}.txt").write_text("\n".join(rows) + "\n")
    return tmp_path


def test_score_writes_the_full_matrix_for_every_grid_cell(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`score` produces scores.csv/.md/-per-query.csv covering both configs.

    The deliverable is the whole matrix, not the winner (PLAN §7.4): the
    neighbouring cells are the only evidence that a peak is a peak rather than the
    noise PLAN §3.4 predicts. A `score` that emitted just the best row would look
    successful and be useless.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    run_dir = scoreable_run / "runs" / "rid"
    rows = (run_dir / "scores.csv").read_text().splitlines()
    assert len(rows) == 3  # header + 2 configs
    assert {r.split(",")[0] for r in rows[1:]} == {"k1_0.9__b_0.4",
                                                  "k1_1.2__b_0.75"}
    assert (run_dir / "scores.md").is_file()
    assert (run_dir / "scores-per-query.csv").read_text().count("\n") == 5


def test_score_records_its_inputs_in_the_manifest(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The manifest names the qrels file, its grade histogram and the query count.

    PLAN §7.2's promise is that a run is auditable from its manifest alone. Which
    label set produced a matrix is the first thing a reader needs and the easiest
    thing to lose — re-judging under a new prompt version leaves the old
    `scores.csv` looking current.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    manifest = json.loads(
        (scoreable_run / "runs" / "rid" / "manifest.json").read_text())
    assert manifest["prompt_version"] == "facet-v1"
    assert manifest["qrels_judged_pairs"] == 5
    assert manifest["score_query_count"] == 2
    assert manifest["primary_metric"] == "ndcg10_exp"
    assert set(manifest["scores"]) == {"k1_0.9__b_0.4", "k1_1.2__b_0.75"}


def test_score_persists_the_precisions_so_no_re_run_is_ever_needed(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`gp10`/`p10_bin2` land in all three artifacts plus the manifest, in one pass.

    This is the whole requirement behind adding them: someone who later decides
    to pick k1/b by maximizing precision@10 must be able to do it from the
    committed files, with no re-judging (which costs money) and no re-sweep. If
    any writer here were driven by a hand-listed metric set instead of
    `METRIC_NAMES`, that person would have to re-run the pipeline.

    Hand-computed for `k1_0.9__b_0.4`, over 2 queries and a flat 10 slots:
      t1::aaa ranks [A(3), B(0), C(2)] -> gp10 = 5/30, p10_bin2 = 2/10
      t2::bbb ranks [Z(3)]             -> gp10 = 3/30, p10_bin2 = 1/10
      means: gp10 = (5/30 + 3/30)/2 = 4/30 = 0.133333, p10_bin2 = 0.15
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    run_dir = scoreable_run / "runs" / "rid"

    header = (run_dir / "scores.csv").read_text().splitlines()[0].split(",")
    for name in ("gp10", "p10_bin2"):
        assert [name, f"{name}_topicmean", f"{name}_n"] == [
            c for c in header if c.startswith(name)]
    # Immediately after the nDCG columns, before recall/MAP.
    assert header.index("gp10") == header.index("ndcg10_bin2_n") + 1
    assert header.index("p10_bin2") < header.index("recall10_bin2")

    rows = dict(zip(header, next(
        r.split(",") for r in (run_dir / "scores.csv").read_text().splitlines()
        if r.startswith("k1_0.9__b_0.4,"))))
    assert float(rows["gp10"]) == pytest.approx(4 / 30, abs=1e-6)
    assert float(rows["p10_bin2"]) == pytest.approx(0.15, abs=1e-6)
    assert rows["gp10_n"] == "2" and rows["p10_bin2_n"] == "2"

    per_query = (run_dir / "scores-per-query.csv").read_text().splitlines()
    assert "gp10" in per_query[0].split(",")
    assert "gp10" in (run_dir / "scores.md").read_text()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["scores"]["k1_0.9__b_0.4"]["gp10"] == pytest.approx(4 / 30)
    assert manifest["scores"]["k1_0.9__b_0.4"]["p10_bin2"] == pytest.approx(0.15)


def test_score_reports_the_precisions_as_rank_flat_end_to_end(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """The two fixture configs differ on nDCG but tie on both precisions.

    The rank-permutation property, asserted through the real pipeline rather than
    only against the functions: `k1_0.9__b_0.4` ranks [A, B, C] and
    `k1_1.2__b_0.75` ranks [C, A, B] — the same three chunks reordered. That is
    exactly the case the two measures exist to identify, and it is also why the
    `score` log now names each metric's argmax cell: with a rank-flat metric the
    best cell is frequently *not* the primary's winner, and a reader who only
    saw `[SUMMARY] best ndcg10_exp` would never learn that.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    with caplog.at_level(logging.INFO):
        assert main(["score", "--run-id", "rid"]) == EXIT_OK
    manifest = json.loads(
        (scoreable_run / "runs" / "rid" / "manifest.json").read_text())
    a, b = manifest["scores"]["k1_0.9__b_0.4"], manifest["scores"][
        "k1_1.2__b_0.75"]
    assert a["gp10"] == pytest.approx(b["gp10"])
    assert a["p10_bin2"] == pytest.approx(b["p10_bin2"])
    assert a["ndcg10_exp"] != pytest.approx(b["ndcg10_exp"])
    text = caplog.text
    assert "best gp10" in text and "best p10_bin2" in text
    assert "secondary/exploratory, not pre-registered" in text
    # The primary's own line keeps its original, unqualified form.
    assert "best ndcg10_exp" in text


def test_score_merges_into_an_existing_manifest_rather_than_replacing_it(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WP2's search fields survive scoring (PLAN §7.2's merge rule).

    Three stages write this file — search, judge, score — and a stage that wrote
    it wholesale would erase the others. The provenance a reviewer needs (index
    path, depth, git sha) is written by search and would vanish at score time.
    """
    from bm25tune.cli import EXIT_OK, main

    manifest = scoreable_run / "runs" / "rid" / "manifest.json"
    manifest.write_text(json.dumps({"index_dir": "/data/idx", "depth": 30}))
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    merged = json.loads(manifest.read_text())
    assert merged["index_dir"] == "/data/idx" and merged["depth"] == 30
    assert "scores" in merged


def test_score_is_free_to_re_run_and_deterministic(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-scoring overwrites without `--force` and produces identical bytes.

    Deliberately *unlike* `extract-queries` and the run dir, whose overwrite guard
    protects paid-for work: scoring reads the cache and costs $0, so re-running
    after more judgments land is the intended workflow (PLAN §5.7 layer 3) and a
    clobber guard would only obstruct it. Determinism is what makes that safe.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    first = (scoreable_run / "runs" / "rid" / "scores.csv").read_bytes()
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    assert (scoreable_run / "runs" / "rid" / "scores.csv").read_bytes() == first


def test_score_reports_a_missing_qrels_file_with_the_command_to_run(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """No cache snapshot -> exit 1 naming `judge-pool`, not a traceback.

    This is the most likely operator error (scoring before judging finished), and
    a launching agent branches on the exit code rather than parsing the log
    (PLAN §5.7) — so it must be 1, and the log must say what to run.
    """
    from bm25tune.cli import EXIT_ERROR, main

    (scoreable_run / "judgments" / "cache" / "qrels-facet-v1.jsonl").unlink()
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    with caplog.at_level(logging.INFO):
        assert main(["score", "--run-id", "rid"]) == EXIT_ERROR
    assert "judge-pool" in caplog.text


def test_score_warns_when_judged_coverage_is_incomplete(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A partially judged pool still scores, but the shortfall is logged loudly.

    Unjudged chunks score gain 0, so under-judging is indistinguishable from a
    ranking loss in the matrix. PLAN §5.7 layer 3 requires a budget-truncated run
    to remain scoreable, which makes the warning the only thing standing between
    a coverage artifact and a reported finding.
    """
    from bm25tune.cli import EXIT_OK, main

    cache = scoreable_run / "judgments" / "cache" / "qrels-facet-v1.jsonl"
    cache.write_text("\n".join([
        json.dumps({"kind": M.CACHE_META_KIND, "prompt_version": "facet-v1"}),
        json.dumps({"jkey": "facet-v1::t1::A", "grade": 3}),
        json.dumps({"jkey": "facet-v1::t2::Z", "grade": 3}),
    ]) + "\n")
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    with caplog.at_level(logging.INFO):
        assert main(["score", "--run-id", "rid"]) == EXIT_OK
    assert "judged@10 dips to" in caplog.text
    assert "coverage, not" in caplog.text


def test_score_requires_a_run_id() -> None:
    """`--run-id` is mandatory: there is no "current run" to guess at.

    Defaulting to the newest run dir would silently score yesterday's sweep after
    a failed launch — and write `scores.csv` into it, next to the old numbers.
    """
    from bm25tune.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["score"])


def test_a_second_score_against_another_qrels_does_not_clobber_the_first(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--label` keeps both matrices; without it the second `score` overwrote.

    One run dir is legitimately scored twice — against the single-prompt qrels
    and then against §6.2b's consensus qrels — and having both is the only way to
    show the consensus changed the ranking. The basenames are fixed, so the
    consensus pass silently replaced the single-judge matrix it was supposed to
    be compared against, and the loss is invisible in the output.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    run_dir = scoreable_run / "runs" / "rid"
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    first = (run_dir / "scores.csv").read_text()

    # A consensus-shaped qrels: TREC 4-column, no prompt version anywhere.
    consensus = run_dir / "qrels-consensus.txt"
    consensus.write_text("t1 0 A 3\nt1 0 B 0\nt1 0 C 0\nt2 0 Z 0\n")
    assert main(["score", "--run-id", "rid", "--qrels", str(consensus),
                 "--label", "consensus"]) == EXIT_OK

    assert (run_dir / "scores.csv").read_text() == first, (
        "the unlabelled matrix must survive a labelled re-score")
    assert (run_dir / "scores-consensus.csv").is_file()
    assert (run_dir / "scores-consensus.md").is_file()
    assert (run_dir / "scores-per-query-consensus.csv").is_file()

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["qrels_judged_pairs"] == 5, (
        "the first pass's manifest record must survive too")
    assert manifest["score_consensus"]["qrels_judged_pairs"] == 4
    assert manifest["score_consensus"]["qrels_file"] == str(consensus)


def test_scoring_an_overridden_qrels_does_not_claim_a_prompt_version(
        scoreable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `--qrels` matrix must not be labelled with `--prompt-version`'s default.

    `--prompt-version` keeps its default when `--qrels` overrides the path, so
    the consensus matrix was headed `prompt version: facet-v1` — naming one of
    three votes as if it were the whole label set, which reads as a single-judge
    result. Worse, passing that default into `load_qrels` would apply the
    single-prompt identity check to a file that spans versions by design.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(scoreable_run))
    run_dir = scoreable_run / "runs" / "rid"
    consensus = run_dir / "qrels-consensus.txt"
    consensus.write_text("t1 0 A 3\nt1 0 B 1\nt2 0 Z 2\n")
    assert main(["score", "--run-id", "rid", "--qrels", str(consensus),
                 "--label", "consensus"]) == EXIT_OK

    text = (run_dir / "scores-consensus.md").read_text()
    assert "facet-v1" not in text, (
        "the header must not name a prompt version it cannot know")
    assert "qrels-consensus.txt" in text, "it must name the label set it used"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["score_consensus"]["prompt_version"] is None
