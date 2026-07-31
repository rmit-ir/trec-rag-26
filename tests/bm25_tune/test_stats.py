"""What `stats.py` defends: whether the sweep is allowed to claim a winner.

PLAN §3.4 and R1 predict the outcome will be a hair's difference between
neighbouring grid cells on grades that pile up at 2. Everything separating "k1=0.7
is better" from "k1=0.7 drew a luckier query sample" lives in this module, so each
of the following would let a null be written up as a result, with no visible
symptom:

- **an approximate distribution tail.** `t` and `normal` are implemented here by
  hand (no scipy, PLAN §4.1), so a wrong `betainc` branch or a lost far-tail
  precision would move p-values in exactly the region where the decision flips.
  Both tails are pinned to scipy-derived constants below.
- **a lost pairing.** The design is paired — same query, same narrative, same
  topic-level ideal — and the pairing removes most of the variance. An
  implementation that silently intersected mismatched query sets would make `n`
  depend on which config failed where.
- **a missing Bonferroni.** Three candidates tested at 0.05 each is a ~14 % chance
  of at least one false winner, and the candidates were *chosen* by looking at
  Stage A.
- **the wrong query set.** The confirmatory tests must run on the held-out
  complement, derived by **set difference against the persisted subsample file** —
  recomputing it from `seed=13` would silently turn the confirmatory analysis back
  into the selection analysis the day the sampler's tie-breaking changes.
- **an irreproducible CI.** A bootstrap interval that moves between runs cannot be
  cited, so the seed must actually determine the numbers.
- **ignored clustering.** Queries within a topic are correlated; the query-level
  n = 825 overstates the independent sample size. PLAN §6.4 makes the topic-level
  result the headline where the two disagree, which only works if the topic-level
  test exists and the artifact says which case it is in.

Expected values here are either hand-computable in closed form (noted per test) or
scipy-derived constants, cross-checked in an ephemeral env — `scipy.stats.ttest_rel`
for the paired t, `scipy.stats.t.sf` at df 1/4/10/118/824 for the tail, and
`scipy.stats.wilcoxon(method='approx', correction=False, zero_method='wilcox')`
for the signed-rank statistic and p. scipy is never a dependency of the task or
the root env, and is never imported from `stats.py`.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pytest

from bm25tune import stats as S

# The known-answer paired vector, chosen because its t is exactly -sqrt(5).
#   a - b = [-1, -2, -2, 0, 0]; mean = -1.0; sd (ddof=1) = 1.0
#   t = -1.0 / (1.0 / sqrt(5)) = -sqrt(5) = -2.23606797749979
#   df = 4; two-sided p = 0.08900934250008567  (scipy.stats.ttest_rel)
PAIRED_A = [1.0, 2.0, 3.0, 4.0, 5.0]
PAIRED_B = [2.0, 4.0, 5.0, 4.0, 5.0]
PAIRED_DELTAS = [a - b for a, b in zip(PAIRED_A, PAIRED_B)]
PAIRED_T = -math.sqrt(5.0)
PAIRED_P = 0.08900934250008567


# ---------------------------------------------------------------------------
# Distribution tails
# ---------------------------------------------------------------------------
def test_t_tail_matches_scipy_across_the_dfs_this_experiment_uses() -> None:
    """`t_sf` pinned to `scipy.stats.t.sf` at df 1, 4, 10, 118, 824.

    Those are not arbitrary: df 118 is the topic-level test (119 topics) and
    df 824 the query-level held-out test (825 queries), the two that decide the
    experiment. A continued fraction that converges to the wrong branch is
    typically fine in the body and wrong in the tail — so the check is at t = 2.3,
    right where p crosses the Bonferroni threshold of 0.0167.
    """
    expected = {
        1: 0.13054758708862277,
        4: 0.04146951855619118,
        10: 0.022127156642143573,
        118: 0.011602778471083468,
        824: 0.010848662732458852,
    }
    for df, sf in expected.items():
        assert S.t_sf(2.3, df) == pytest.approx(sf, rel=1e-12)
        assert S.t_two_sided_p(2.3, df) == pytest.approx(2 * sf, rel=1e-12)


def test_the_t_tail_is_symmetric_in_the_sign_of_t() -> None:
    """`t_sf(-t) == 1 - t_sf(t)`, and the two-sided p ignores the sign.

    A candidate genuinely *worse* than the baseline is a real, reportable outcome
    (the grid brackets the baseline on both axes), so a sign error that returned a
    near-1 p for a strong negative effect would silently discard half the possible
    findings.
    """
    assert S.t_sf(-2.3, 824) == pytest.approx(1 - S.t_sf(2.3, 824), rel=1e-12)
    assert S.t_two_sided_p(-2.3, 824) == pytest.approx(
        S.t_two_sided_p(2.3, 824), rel=1e-14)


def test_t_at_zero_is_a_p_of_one() -> None:
    """No difference at all -> p = 1, from the closed form `I_1(df/2, 1/2)`.

    A boundary the continued fraction has to handle by short-circuit (`x = 1`);
    letting it iterate there returns garbage, and t = 0 is a case this data
    produces for real when two grid cells rank identically.
    """
    assert S.t_two_sided_p(0.0, 824) == pytest.approx(1.0, abs=1e-12)


def test_normal_tail_matches_the_textbook_z_values() -> None:
    """`normal_sf` at z = 0, 1.96, 2.5758 — the Wilcoxon p's only input.

    Computed via `erfc`, not `1 - cdf`, because the latter loses all precision in
    the far tail. 1.959963985 -> 0.025 and 2.5758293 -> 0.005 are the two-sided
    5 % and 1 % points, so an error here shifts every Wilcoxon p across a
    conventional threshold.
    """
    assert S.normal_sf(0.0) == pytest.approx(0.5, abs=1e-15)
    assert S.normal_sf(1.959963984540054) == pytest.approx(0.025, abs=1e-12)
    assert S.normal_sf(2.5758293035489004) == pytest.approx(0.005, abs=1e-12)
    # Far tail: the region a "1 - cdf" implementation rounds to zero.
    assert S.normal_sf(8.0) == pytest.approx(6.220960574271794e-16, rel=1e-9)


def test_betainc_rejects_an_out_of_range_x() -> None:
    """`x` outside [0, 1] raises instead of returning a nonsense probability.

    Reachable only through a bug upstream (a NaN t, a negative df), and a p-value
    of 1.7 propagating into `stats.json` would be worse than a crash.
    """
    with pytest.raises(S.StatsError):
        S.betainc(1.0, 1.0, 1.5)
    with pytest.raises(S.StatsError):
        S.t_sf(2.0, 0)


# ---------------------------------------------------------------------------
# Paired t
# ---------------------------------------------------------------------------
def test_paired_t_matches_the_known_answer_vector() -> None:
    """t = -sqrt(5), p = 0.089009342500086, df = 4 on a hand-checkable vector.

    Deltas `[-1, -2, -2, 0, 0]` give mean -1.0 and sd exactly 1.0, so
    `t = mean / (sd/sqrt(n)) = -sqrt(5)` by inspection — the whole statistic is
    verifiable without a library. The p-value is scipy's `ttest_rel`, which is
    what pins the tail to the same convention a reviewer would re-run.
    """
    t, p, df = S.paired_t_test(PAIRED_DELTAS)
    assert t == pytest.approx(PAIRED_T, rel=1e-14)
    assert p == pytest.approx(PAIRED_P, rel=1e-12)
    assert df == 4
    assert S.mean(PAIRED_DELTAS) == pytest.approx(-1.0, abs=1e-15)
    assert S.stdev(PAIRED_DELTAS) == pytest.approx(1.0, abs=1e-15)


def test_stdev_uses_the_sample_denominator() -> None:
    """ddof = 1, not n — the population sd would inflate every t by sqrt(n/(n-1)).

    On the 825-query held-out set that is only a 0.06 % shift, which is exactly
    why it would never be noticed and why it is pinned: `[1,2,3,4,5]` has sample
    sd sqrt(2.5), population sd sqrt(2).
    """
    assert S.stdev([1, 2, 3, 4, 5]) == pytest.approx(math.sqrt(2.5), rel=1e-15)
    with pytest.raises(S.StatsError):
        S.stdev([1.0])


def test_identical_rankings_give_p_one_rather_than_crashing() -> None:
    """All-zero deltas -> (0.0, 1.0, n-1); sd = 0 must not divide by zero.

    Two grid cells producing identical rankings on every query is a *likely*
    outcome on mode-dominated grades, not a pathological one. It has to arrive in
    the report as "no difference", not as a traceback that kills the whole
    `stats` run and takes the other comparisons with it.
    """
    t, p, df = S.paired_t_test([0.0] * 6)
    assert (t, p, df) == (0.0, 1.0, 5)
    assert S.cohens_d([0.0] * 6) is None


def test_paired_t_needs_at_least_two_pairs() -> None:
    """n < 2 raises rather than returning a null-filled result.

    A well-formed `stats.json` full of nulls reads as "tested, no effect"; a
    refusal reads as "not testable". Only one of those is true when a metric was
    defined on a single query.
    """
    with pytest.raises(S.StatsError):
        S.paired_t_test([0.5])


def test_cohens_d_is_the_paired_form() -> None:
    """`d_z = mean(delta)/sd(delta)` = -1.0 on the known-answer vector.

    The *paired* d, by design: the two-sample pooled sd would understate the
    effect by the between-query correlation the pairing removes, which on this
    data is most of the variance. -1.0 falls out of mean -1.0 over sd 1.0.
    """
    assert S.cohens_d(PAIRED_DELTAS) == pytest.approx(-1.0, abs=1e-14)


# ---------------------------------------------------------------------------
# Wilcoxon signed-rank
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("deltas,statistic,p_value", [
    ([1, -2, 3, 4, -5, 6], 7.0, 0.463071015014588),
    ([1, 1, -2, 2], 3.5, 0.5774686624272996),
    ([0, 0, 1, -2, 3, 4, -5, 6], 7.0, 0.463071015014588),
    ([3, 3, 3, -3, -3, 1, 2, 2], 12.0, 0.3883232289789249),
])
def test_wilcoxon_matches_scipys_normal_approximation(
        deltas: list[float], statistic: float, p_value: float) -> None:
    """`min(W+, W-)` and p pinned to scipy's `method='approx'`, no continuity term.

    Four vectors, each carrying one thing that can go wrong: a plain signed set;
    ties in `|delta|` needing average ranks (`[1, 1, -2, 2]` -> W = 3.5, a *half*
    rank, which an integer-ranking implementation cannot produce); leading zeros
    that must be dropped; and a tie-heavy vector where the `sum(t**3 - t)/48`
    variance correction actually bites. Reporting `min(W+, W-)` is what makes the
    number in `stats.json` directly re-checkable against a scipy one-liner.
    """
    result = S.wilcoxon_signed_rank([float(d) for d in deltas])
    assert result.statistic == pytest.approx(statistic, abs=1e-12)
    assert result.p_value == pytest.approx(p_value, rel=1e-9)


def test_zeros_are_dropped_so_the_effective_n_is_reported() -> None:
    """Adding two exact ties changes nothing but `n_zero` — and that is reported.

    `zero_method="wilcox"`: zeros carry no directional information, so they leave
    the ranking. But on mode-dominated grades a large share of queries can tie
    exactly, and a test whose effective n is a third of the query count must say
    so rather than borrowing the query count's authority.
    """
    without = S.wilcoxon_signed_rank([1.0, -2.0, 3.0, 4.0, -5.0, 6.0])
    with_zeros = S.wilcoxon_signed_rank([0.0, 0.0, 1.0, -2.0, 3.0, 4.0,
                                         -5.0, 6.0])
    assert with_zeros.p_value == pytest.approx(without.p_value, rel=1e-12)
    assert with_zeros.n_nonzero == 6
    assert with_zeros.n_zero == 2
    assert without.n_zero == 0


def test_tie_correction_is_applied_and_recorded() -> None:
    """Tied `|delta|`s reduce the variance by `sum(t**3 - t)/48`.

    Without the correction the p-value is conservative by an amount that scales
    with the tie rate — and the tie rate here is high by construction, so the
    uncorrected test would systematically fail to detect the small real effects
    the sweep is looking for. `[3,3,3,-3,-3,1,2,2]` has a 5-way and a 2-way tie:
    (125-5)/48 + (8-2)/48 = 2.625.
    """
    result = S.wilcoxon_signed_rank([3.0, 3.0, 3.0, -3.0, -3.0, 1.0, 2.0, 2.0])
    assert result.tie_correction == pytest.approx((125 - 5) / 48 + (8 - 2) / 48,
                                                  abs=1e-12)
    assert result.n_nonzero == 8


def test_average_ranks_split_ties_rather_than_ordering_them_arbitrarily() -> None:
    """Tied values share the mean of the ranks they span.

    `[5, 1, 1, 3]` -> ranks `[4, 1.5, 1.5, 3]`. Breaking ties by input order
    instead would make the statistic depend on qkey sort order — reproducible,
    but arbitrary, and different from every published Wilcoxon.
    """
    assert S._average_ranks([5.0, 1.0, 1.0, 3.0]) == [4.0, 1.5, 1.5, 3.0]


def test_a_small_sample_is_flagged_as_an_invalid_approximation() -> None:
    """The normal approximation is computed but marked invalid below n = 20.

    PLAN §6.4 specifies the approximation for n > 100, which is the real case.
    A smoke run or a sparse metric can still land here, and a silently
    approximate p-value in an artifact is worse than a caveated one.
    """
    small = S.wilcoxon_signed_rank([1.0, -2.0, 3.0])
    assert small.approximation_valid is False
    big = S.wilcoxon_signed_rank([float(i) for i in range(1, 31)])
    assert big.approximation_valid is True
    assert S.WILCOXON_APPROX_MIN_N == 20


def test_all_ties_yield_p_one_and_no_approximation_claim() -> None:
    """Every pair tied -> p = 1, `n_nonzero = 0`, approximation flagged invalid.

    The identical-rankings case again, through the distribution-free path: no
    evidence of a difference in either direction, and nothing to approximate.
    """
    result = S.wilcoxon_signed_rank([0.0, 0.0, 0.0])
    assert (result.p_value, result.n_nonzero, result.n_zero) == (1.0, 0, 3)
    assert result.approximation_valid is False


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def test_bootstrap_ci_is_reproducible_under_the_fixed_seed() -> None:
    """Same seed, same interval, bit for bit — twice, and across a fresh call.

    A CI that moves between runs cannot be cited, and `stats.json` is a committed
    artifact (PLAN §7.4). Seed 13 is fixed by PLAN §6.4 precisely so a reviewer
    re-running the command reproduces the published interval exactly.
    """
    deltas = [0.1, -0.05, 0.2, 0.0, 0.3, -0.1, 0.15, 0.05]
    first = S.bootstrap_ci(deltas, resamples=500, seed=13)
    second = S.bootstrap_ci(deltas, resamples=500, seed=13)
    assert first == second
    assert first[2] == 0.95
    assert S.BOOTSTRAP_SEED == 13
    assert S.BOOTSTRAP_RESAMPLES == 10_000


def test_a_different_seed_moves_the_interval() -> None:
    """The seed genuinely drives the resampling, so "seed 13" is a real claim.

    Without this, a bug that ignored the seed would pass the reproducibility test
    above trivially — the interval would be reproducible because it was constant.
    """
    deltas = [0.1, -0.05, 0.2, 0.0, 0.3, -0.1, 0.15, 0.05]
    assert S.bootstrap_ci(deltas, resamples=500, seed=13) != (
        S.bootstrap_ci(deltas, resamples=500, seed=14))


def test_the_bootstrap_ci_brackets_the_observed_mean_delta() -> None:
    """The percentile interval contains the point estimate it is an interval for.

    A resampling bug (drawing without replacement, resampling the wrong axis,
    off-by-one percentile indices) usually shows up as an interval that misses
    the mean — cheap to check, and the failure would otherwise look like a
    surprisingly tight or offset CI in the report.
    """
    deltas = [0.1, -0.05, 0.2, 0.0, 0.3, -0.1, 0.15, 0.05]
    lo, hi, _ = S.bootstrap_ci(deltas, resamples=2000, seed=13)
    assert lo <= S.mean(deltas) <= hi


def test_a_constant_delta_gives_a_degenerate_interval() -> None:
    """Every delta identical -> lo == hi == that delta, no spread invented.

    Resampling a constant vector can only produce that constant. If the interval
    had width here, the resampler would be introducing variance from somewhere it
    should not — and this is the exact case two near-identical configs produce.
    """
    lo, hi, _ = S.bootstrap_ci([0.25] * 10, resamples=200, seed=13)
    assert lo == pytest.approx(0.25, abs=1e-12)
    assert hi == pytest.approx(0.25, abs=1e-12)


def test_bootstrap_refuses_a_degenerate_request() -> None:
    """n < 2 or resamples < 1 raises instead of returning an empty interval."""
    with pytest.raises(S.StatsError):
        S.bootstrap_ci([0.1])
    with pytest.raises(S.StatsError):
        S.bootstrap_ci([0.1, 0.2], resamples=0)


# ---------------------------------------------------------------------------
# Bonferroni
# ---------------------------------------------------------------------------
def test_the_bonferroni_threshold_is_computed_not_rounded() -> None:
    """alpha/3 = 0.016666..., not the plan's display value 0.0167.

    Rounding the threshold *up* makes a p of 0.01668 "significant" when it is
    not. PLAN §6.4 writes 0.0167 as prose; the code must use the exact quotient,
    and this test is the reason the constant is a division rather than a literal.
    """
    assert S.FAMILY_ALPHA == 0.05
    assert S.N_COMPARISONS == 3
    assert S.BONFERRONI_ALPHA == pytest.approx(0.05 / 3, rel=1e-15)
    assert S.BONFERRONI_ALPHA < 0.0167


def test_bonferroni_multiplies_the_p_and_clamps_at_one() -> None:
    """`min(1, p*m)`: 0.02 -> 0.06 at m = 3; 0.5 -> 1.0, never 1.5.

    The adjusted p is reported so a reader can compare it to 0.05 directly, which
    is the comparison people actually make. The clamp matters because an
    "adjusted p-value" above 1 is not a probability and would look like a bug in
    the artifact rather than a large p.
    """
    assert S.bonferroni(0.02, 3) == pytest.approx(0.06, rel=1e-15)
    assert S.bonferroni(0.5, 3) == 1.0
    assert S.bonferroni(0.02, 1) == pytest.approx(0.02, rel=1e-15)


def test_significance_uses_the_corrected_threshold_not_the_raw_alpha() -> None:
    """A p of 0.03 is significant at 0.05 and NOT at 0.05/3.

    This is the whole point of the correction, and the case where an uncorrected
    implementation would publish a winner. The vector is constructed so its
    two-sided p lands between the two thresholds.
    """
    # Deltas with a large-ish mean relative to spread over 6 pairs: p ~ 0.03.
    deltas = [0.05, 0.04, 0.06, 0.05, 0.03, -0.02]
    _, p, _ = S.paired_t_test(deltas)
    assert 0.05 / 3 < p < 0.05, f"vector no longer straddles the thresholds: {p}"
    result = S.compare({f"t{i}::q": d for i, d in enumerate(deltas)},
                       {f"t{i}::q": 0.0 for i in range(len(deltas))},
                       metric="ndcg10_exp", candidate="cand", baseline="base",
                       resamples=200)
    assert result.p_value == pytest.approx(p, rel=1e-12)
    assert result.alpha_bonferroni == pytest.approx(0.05 / 3, rel=1e-15)
    assert result.significant is False


# ---------------------------------------------------------------------------
# compare()
# ---------------------------------------------------------------------------
def _keyed(values: list[float], topics: int = 4) -> dict[str, float]:
    """Spread `values` over `topics` topics as `<topic>::<i>` qkeys."""
    return {f"t{i % topics}::q{i}": v for i, v in enumerate(values)}


def test_compare_reports_the_whole_battery_for_one_comparison() -> None:
    """One call yields p, corrected p and threshold, d, CI, Wilcoxon, wins/losses.

    Quoting any one of them alone is how a mode-dominated null gets written up as
    a win, so PLAN §6.4 requires them together and `TestResult` is deliberately
    one flat record rather than something a caller assembles per metric.
    """
    cand = _keyed([0.5, 0.4, 0.6, 0.3, 0.7, 0.5])
    base = _keyed([0.4, 0.4, 0.5, 0.4, 0.5, 0.5])
    result = S.compare(cand, base, metric="ndcg10_exp", candidate="k1_0.7__b_0.3",
                       baseline="k1_0.9__b_0.4", resamples=500)
    assert result.n == 6
    assert result.wins == 3 and result.losses == 1 and result.ties == 2
    assert result.mean_delta == pytest.approx((0.1 + 0.1 - 0.1 + 0.2) / 6,
                                              abs=1e-12)
    assert result.candidate_mean == pytest.approx(S.mean(list(cand.values())))
    assert result.baseline_mean == pytest.approx(S.mean(list(base.values())))
    assert result.ci_low <= result.mean_delta <= result.ci_high
    assert result.wilcoxon.n_nonzero == 4
    assert result.df == 5
    assert result.confirmatory is True
    assert result.query_set == "held-out"


def test_compare_refuses_mismatched_query_sets() -> None:
    """A qkey in one config and not the other raises — the test must stay paired.

    Silently intersecting would make the reported `n` depend on which config
    happened to fail on which query, so two comparisons in the same table could be
    over different query populations while both were labeled "held-out".
    """
    with pytest.raises(S.StatsError, match="query sets differ"):
        S.compare({"t1::a": 0.5, "t1::b": 0.4}, {"t1::a": 0.4},
                  metric="m", candidate="c", baseline="b")


def test_compare_needs_two_pairs() -> None:
    """A single paired query cannot support a test, and says so.

    Reachable for a sparse secondary metric on a topic with one judged-relevant
    chunk; a one-query "significance" claim would be indefensible.
    """
    with pytest.raises(S.StatsError, match=">= 2 paired queries"):
        S.compare({"t1::a": 0.5}, {"t1::a": 0.4}, metric="m", candidate="c",
                  baseline="b")


def test_the_topic_level_test_uses_per_topic_mean_deltas() -> None:
    """Clustering robustness: n becomes the topic count, not the query count.

    Queries within a topic share a narrative and a qrel, so the query-level
    n = 825 overstates the independent sample size. Here 8 queries over 2 topics
    give `topic_n = 2` and a topic mean delta equal to the mean of the two topic
    means — which, with unequal topic sizes, is deliberately *not* the query mean.
    """
    cand = {"tA::1": 1.0, "tA::2": 1.0, "tA::3": 1.0, "tB::1": 0.0}
    base = {k: 0.0 for k in cand}
    result = S.compare(cand, base, metric="m", candidate="c", baseline="b",
                       resamples=200)
    assert result.topic_n == 2
    assert result.mean_delta == pytest.approx(0.75)          # query-level
    assert result.topic_mean_delta == pytest.approx(0.5)     # topic-level
    assert result.topic_p_value is not None


def test_topics_are_derived_from_the_qkey_prefix_when_not_supplied() -> None:
    """`<topic_id>::<sha1[:12]>` is enough to group queries by topic.

    That is `extract.QueryRec.qkey`'s format, so the clustering test works from a
    run file alone. An explicit mapping still wins, because a caller that has the
    scored records should not depend on string parsing.
    """
    cand = {"tA::1": 1.0, "tA::2": 1.0, "tB::1": 0.0, "tB::2": 0.0}
    base = {k: 0.0 for k in cand}
    derived = S.compare(cand, base, metric="m", candidate="c", baseline="b",
                        resamples=100)
    explicit = S.compare(cand, base, metric="m", candidate="c", baseline="b",
                         resamples=100,
                         topics={k: k.split("::")[0] for k in cand})
    assert derived.topic_n == explicit.topic_n == 2
    # One topic per query collapses the topic test to the query test.
    per_query_topics = {k: k for k in cand}
    flat = S.compare(cand, base, metric="m", candidate="c", baseline="b",
                     resamples=100, topics=per_query_topics)
    assert flat.topic_n == 4
    assert flat.topic_p_value == pytest.approx(flat.p_value, rel=1e-12)


def test_the_headline_note_states_the_clustering_verdict() -> None:
    """PLAN §6.4's "topic-level wins" rule is written into every result.

    The rule is a finding-time instruction that would otherwise live only in the
    plan and in a reviewer's memory. Emitting it beside the numbers means the
    artifact cannot be read without it.
    """
    assert "topic-level null is the honest" in S._headline_note(True, False)
    assert "significant at both" in S._headline_note(True, True)
    assert "no significant difference" in S._headline_note(False, False)
    assert "no topic-level test" in S._headline_note(True, None)


def test_a_single_topic_leaves_the_topic_test_undefined_and_says_so() -> None:
    """One topic -> `topic_significant is None` plus an explanatory note.

    Fabricating a topic-level p from n = 1 would be worse than omitting it, and an
    omission with no note reads as "the check passed".
    """
    cand = {"tA::1": 1.0, "tA::2": 0.5}
    base = {k: 0.0 for k in cand}
    result = S.compare(cand, base, metric="m", candidate="c", baseline="b",
                       resamples=100)
    assert result.topic_significant is None
    assert "no topic-level test" in result.headline_note


# ---------------------------------------------------------------------------
# The held-out set
# ---------------------------------------------------------------------------
def test_held_out_is_the_set_difference_against_the_persisted_subsample() -> None:
    """1063 - 238 = 825, by set difference — never recomputed from the seed.

    PLAN §6.4 is emphatic, and WP1's actual draw (238, not the plan's ~250) is why:
    re-deriving from `seed=13` would silently change the held-out set the day
    `stratified_subsample`'s tie-breaking, sort order or `per_topic` default
    changes, turning the confirmatory analysis back into the selection analysis
    with no visible symptom. The counts here are the real ones.
    """
    full = [f"t{i % 119}::q{i}" for i in range(1063)]
    subsample = full[:238]
    held = S.held_out_qkeys(full, subsample)
    assert len(held) == 825
    assert not set(held) & set(subsample)
    assert set(held) | set(subsample) == set(full)


def test_a_subsample_that_is_not_a_subset_is_refused() -> None:
    """A stray subsample qkey means the two files describe different populations.

    "Held out" would then be a lie — the complement would include queries the
    candidates were selected on, or exclude queries that were never sampled. Both
    invalidate the confirmatory claim, silently.
    """
    with pytest.raises(S.StatsError, match="different query populations"):
        S.held_out_qkeys(["a::1", "a::2"], ["a::1", "b::9"])


def test_load_qkeys_reads_the_query_file_and_rejects_a_bad_row(
        tmp_path: Path) -> None:
    """The `qkey` column is read from `queries/*.jsonl`; a row without one raises.

    This is the file the held-out set is derived from, so a silently skipped row
    would shrink the held-out set and no count downstream would notice.
    """
    path = tmp_path / "keyword-1063.jsonl"
    path.write_text("\n".join([
        json.dumps({"topic_id": "t1", "query": "a", "qkey": "t1::aaa"}),
        json.dumps({"topic_id": "t1", "query": "b", "qkey": "t1::bbb"}),
    ]) + "\n")
    assert S.load_qkeys(path) == ["t1::aaa", "t1::bbb"]

    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"topic_id": "t1"}) + "\n")
    with pytest.raises(S.StatsError, match="no `qkey` field"):
        S.load_qkeys(bad)

    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    with pytest.raises(S.StatsError, match="no query rows"):
        S.load_qkeys(empty)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def _per_config(configs: dict[str, list[float]], metric: str = "ndcg10_exp",
                topics: int = 4) -> dict:
    return {name: {metric: _keyed(values, topics)}
            for name, values in configs.items()}


def test_the_report_separates_confirmatory_from_descriptive() -> None:
    """Held-out tests carry the inference; full-set tests are labeled descriptive.

    The candidates were SELECTED on part of the full set, so a p-value over all
    1063 is a selection artifact. It is still reported — dropping it would hide
    the point estimate everyone will ask for — but the label is what stops it
    being quoted as evidence.
    """
    values = [0.5, 0.4, 0.6, 0.3, 0.7, 0.5, 0.45, 0.55]
    base_values = [0.4, 0.4, 0.5, 0.4, 0.5, 0.5, 0.4, 0.5]
    per_config = _per_config({"cand": values, "base": base_values})
    full = sorted(per_config["base"]["ndcg10_exp"])
    held = full[2:]
    report = S.build_report(
        run_id="rid", baseline="base", candidates=["cand"],
        metrics=["ndcg10_exp"], prompt_version="facet-v1",
        per_config=per_config, held_out=held, full=full, resamples=200)
    assert [r.query_set for r in report.confirmatory] == ["held-out"]
    assert [r.query_set for r in report.descriptive] == ["full"]
    assert all(r.confirmatory for r in report.confirmatory)
    assert not any(r.confirmatory for r in report.descriptive)
    assert report.confirmatory[0].n == len(held)
    assert report.descriptive[0].n == len(full)
    assert report.query_sets == {"held_out": len(held), "full": len(full)}


def test_the_report_carries_the_interpretation_rules_as_notes() -> None:
    """PLAN §6.4's caveats are embedded in `stats.json`, not left in the plan.

    Whoever reads the artifact months later will not have the plan open. The three
    that matter most: the correction, the confirmatory/descriptive split, and that
    the metric values are deflated so only differences are interpretable.
    """
    per_config = _per_config({"cand": [0.5] * 6, "base": [0.4] * 6})
    full = sorted(per_config["base"]["ndcg10_exp"])
    report = S.build_report(
        run_id="rid", baseline="base", candidates=["cand"],
        metrics=["ndcg10_exp"], prompt_version="facet-v1",
        per_config=per_config, held_out=full, full=full, resamples=100)
    text = " ".join(report.notes)
    assert "Bonferroni" in text
    assert "SELECTED on the Stage-A subsample" in text
    assert "set difference" in text
    assert "deflated" in text
    assert report.alpha_bonferroni == pytest.approx(0.05, rel=1e-15)  # m=1 here


def test_the_correction_divisor_follows_the_actual_candidate_count() -> None:
    """Three candidates -> alpha/3; one candidate -> alpha/1.

    Hardcoding 3 would over-correct a two-candidate re-analysis and under-correct
    a five-candidate one. The plan pre-registers three, and the CLI warns when the
    count differs, but the *arithmetic* must describe the family actually tested.
    """
    configs = {"base": [0.4] * 6, "c1": [0.5] * 6, "c2": [0.45] * 6,
               "c3": [0.6] * 6}
    per_config = _per_config(configs)
    full = sorted(per_config["base"]["ndcg10_exp"])
    report = S.build_report(
        run_id="rid", baseline="base", candidates=["c1", "c2", "c3"],
        metrics=["ndcg10_exp"], prompt_version="facet-v1",
        per_config=per_config, held_out=full, full=full, resamples=100)
    assert report.n_comparisons == 3
    assert report.alpha_bonferroni == pytest.approx(0.05 / 3, rel=1e-15)
    assert {r.candidate for r in report.confirmatory} == {"c1", "c2", "c3"}
    for result in report.confirmatory:
        assert result.alpha_bonferroni == pytest.approx(0.05 / 3, rel=1e-15)


def test_the_report_refuses_an_absent_baseline_or_candidate() -> None:
    """A typo'd config name raises rather than yielding an empty report.

    An empty `confirmatory` list beside exit code 0 reads as "tested, nothing
    significant" — the most expensive possible way to fail.
    """
    per_config = _per_config({"cand": [0.5] * 6, "base": [0.4] * 6})
    full = sorted(per_config["base"]["ndcg10_exp"])
    with pytest.raises(S.StatsError, match="baseline config"):
        S.build_report(run_id="rid", baseline="nope", candidates=["cand"],
                       metrics=["ndcg10_exp"], prompt_version="p",
                       per_config=per_config, held_out=full, full=full)
    with pytest.raises(S.StatsError, match="candidate config"):
        S.build_report(run_id="rid", baseline="base", candidates=["nope"],
                       metrics=["ndcg10_exp"], prompt_version="p",
                       per_config=per_config, held_out=full, full=full)


def test_the_report_serializes_to_json() -> None:
    """`stats.json` must actually be JSON-serializable, nested dataclasses included.

    `TestResult` holds a `WilcoxonResult`, which `json.dumps` cannot reach through
    a bare `asdict` round-trip in every Python version; discovering that at the
    end of a long run would lose the analysis.
    """
    per_config = _per_config({"cand": [0.5, 0.4, 0.6, 0.3, 0.7, 0.5],
                              "base": [0.4, 0.4, 0.5, 0.4, 0.5, 0.5]})
    full = sorted(per_config["base"]["ndcg10_exp"])
    report = S.build_report(
        run_id="rid", baseline="base", candidates=["cand"],
        metrics=["ndcg10_exp"], prompt_version="facet-v1",
        per_config=per_config, held_out=full, full=full, resamples=100)
    payload = json.loads(json.dumps(report.to_json()))
    assert payload["run_id"] == "rid"
    assert payload["confirmatory"][0]["wilcoxon"]["n_nonzero"] >= 1
    assert payload["bootstrap_seed"] == 13


def test_summary_lines_use_the_greppable_prefix_and_name_the_verdict() -> None:
    """`[SUMMARY]` per confirmatory test, with delta, CI, p and significance.

    The log is the live view of a long run, and the prefixes are the contract
    between it and whoever is watching (PLAN §5.6). A line without the p-value or
    the CI would invite exactly the point-estimate-only reading the module exists
    to prevent.
    """
    from bm25tune.logging_setup import LOG_PREFIXES

    per_config = _per_config({"cand": [0.5, 0.4, 0.6, 0.3, 0.7, 0.5],
                              "base": [0.4, 0.4, 0.5, 0.4, 0.5, 0.5]})
    full = sorted(per_config["base"]["ndcg10_exp"])
    report = S.build_report(
        run_id="rid", baseline="base", candidates=["cand"],
        metrics=["ndcg10_exp"], prompt_version="facet-v1",
        per_config=per_config, held_out=full, full=full, resamples=100)
    lines = S.summary_lines(report, metric="ndcg10_exp")
    assert "[SUMMARY]" in LOG_PREFIXES
    assert all(line.startswith("[SUMMARY] ") for line in lines)
    assert "alpha_bonferroni=" in lines[0]
    assert "delta=" in lines[1] and "CI=[" in lines[1] and "p=" in lines[1]
    assert ("SIGNIFICANT" in lines[1]) or (" ns" in lines[1])


# ---------------------------------------------------------------------------
# The `stats` subcommand end to end
# ---------------------------------------------------------------------------
def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


@pytest.fixture
def testable_run(tmp_path: Path) -> Path:
    """A data dir with qrels, both query files, and 4 configs over 8 topics.

    The full query file has 16 queries and the persisted subsample 4, so the
    held-out complement is 12 — the same set-difference arithmetic as the real
    1063/238/825, small enough to check by hand.
    """
    topics = [f"t{i}" for i in range(8)]
    qkeys = [f"{t}::q{j}" for t in topics for j in range(2)]
    rows = [{"kind": "cache_meta", "prompt_version": "facet-v1"}]
    for t in topics:
        for c, grade in enumerate([3, 2, 2, 1, 0, 2]):
            rows.append({"jkey": f"facet-v1::{t}::{t}_c{c}", "grade": grade})
    _write_jsonl(tmp_path / "judgments" / "cache" / "qrels-facet-v1.jsonl", rows)
    for name, keys in (("keyword-1063.jsonl", qkeys),
                       ("subsample-250.jsonl", qkeys[:4])):
        _write_jsonl(tmp_path / "queries" / name,
                     [{"qkey": q, "topic_id": q.split("::")[0], "topic": "n",
                       "query": "q", "k_orig": 10} for q in keys])

    trecruns = tmp_path / "runs" / "rid" / "trecruns"
    trecruns.mkdir(parents=True)
    orders = {
        "k1_0.9__b_0.4": [0, 1, 2, 3, 4, 5],   # baseline: already ideal
        "k1_0.7__b_0.3": [1, 0, 2, 3, 4, 5],
        "k1_1.2__b_0.75": [4, 0, 1, 2, 3, 5],
        "k1_0.4__b_0.9": [5, 4, 3, 2, 1, 0],
    }
    for stem, order in orders.items():
        lines = []
        for qkey in qkeys:
            topic = qkey.split("::")[0]
            for rank, c in enumerate(order, start=1):
                lines.append(f"{qkey} Q0 {topic}_c{c} {rank} "
                             f"{1.0 / rank:.6f} {stem}")
        (trecruns / f"{stem}.txt").write_text("\n".join(lines) + "\n")
    return tmp_path


def test_stats_writes_a_report_over_the_held_out_complement(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`stats` derives held-out = full - subsample and records both counts.

    16 - 4 = 12 here; 1063 - 238 = 825 in the real run. The counts landing in
    `stats.json` is what lets a reader verify the confirmatory set was the
    complement and not, say, the full set relabeled.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    assert main(["stats", "--run-id", "rid", "--bootstrap", "200",
                 "--metrics", "ndcg10_exp"]) == EXIT_OK
    payload = json.loads(
        (testable_run / "runs" / "rid" / "stats.json").read_text())
    assert payload["query_sets"] == {"held_out": 12, "full": 16}
    assert payload["baseline"] == "k1_0.9__b_0.4"
    assert len(payload["candidates"]) == 3
    assert {r["query_set"] for r in payload["confirmatory"]} == {"held-out"}
    assert {r["n"] for r in payload["confirmatory"]} == {12}
    assert {r["n"] for r in payload["descriptive"]} == {16}


def test_stats_uses_the_persisted_subsample_not_a_recomputed_one(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Editing the subsample FILE changes the held-out set — the file is the source.

    The strongest available check that nothing re-derives the draw from `seed=13`:
    here the file is shrunk to 2 rows and the held-out set must grow to 14. If the
    sampler were re-run instead, the count would be unchanged and the confirmatory
    analysis would silently include queries the candidates were selected on
    (PLAN §6.4).
    """
    from bm25tune.cli import EXIT_OK, main

    sub = testable_run / "queries" / "subsample-250.jsonl"
    kept = sub.read_text().splitlines()[:2]
    sub.write_text("\n".join(kept) + "\n")
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    assert main(["stats", "--run-id", "rid", "--bootstrap", "200",
                 "--metrics", "ndcg10_exp"]) == EXIT_OK
    payload = json.loads(
        (testable_run / "runs" / "rid" / "stats.json").read_text())
    assert payload["query_sets"] == {"held_out": 14, "full": 16}


def test_stats_reports_a_missing_subsample_file_as_an_error(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """No subsample file -> exit 1 saying the held-out set is a set difference.

    The tempting fallback (treat the full set as held out) would produce a
    complete, plausible `stats.json` whose p-values are selection artifacts. So the
    absence has to be fatal, and the log has to explain why rather than just
    naming a path.
    """
    from bm25tune.cli import EXIT_ERROR, main

    (testable_run / "queries" / "subsample-250.jsonl").unlink()
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    with caplog.at_level(logging.INFO):
        assert main(["stats", "--run-id", "rid"]) == EXIT_ERROR
    assert "SET DIFFERENCE" in caplog.text
    assert "extract-queries" in caplog.text


def test_stats_defaults_the_baseline_to_the_pyserini_default_cell(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`k1_0.9__b_0.4` is the baseline every candidate is measured against.

    PLAN §0 fixes it: it is pyserini's default *and* the cell measured to be
    score-identical to the hosted server the RAG systems actually used. A different
    default would make "improves on the baseline" mean something else, and the
    number would still look publishable.
    """
    from bm25tune.cli import EXIT_OK, build_parser, main

    assert build_parser().parse_args(
        ["stats", "--run-id", "x"]).baseline == "k1_0.9__b_0.4"
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    assert main(["stats", "--run-id", "rid", "--bootstrap", "200",
                 "--metrics", "ndcg10_exp"]) == EXIT_OK
    payload = json.loads(
        (testable_run / "runs" / "rid" / "stats.json").read_text())
    for result in payload["confirmatory"]:
        assert result["baseline"] == "k1_0.9__b_0.4"
        assert result["candidate"] != "k1_0.9__b_0.4"


def test_stats_rejects_an_unknown_baseline_or_candidate(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A config name absent from the run files is exit 1, listing what is there.

    A typo'd `--candidates` would otherwise produce an empty `confirmatory` list
    beside exit 0 — indistinguishable from "tested, nothing significant", which is
    the most expensive way this harness could mislead.
    """
    from bm25tune.cli import EXIT_ERROR, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    with caplog.at_level(logging.INFO):
        assert main(["stats", "--run-id", "rid", "--baseline",
                     "k1_9.9__b_9.9"]) == EXIT_ERROR
    assert "k1_0.9__b_0.4" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert main(["stats", "--run-id", "rid", "--candidates",
                     "k1_nope__b_nope"]) == EXIT_ERROR
    assert "candidate config" in caplog.text


def test_stats_warns_when_the_family_is_not_the_pre_registered_three(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """One candidate still runs, with a warning that this is not the plan's family.

    The correction must follow the family actually tested (that is the honest
    arithmetic), but a run with a different candidate count is no longer the
    pre-registered analysis of PLAN §6.4 — and "we tested one candidate at
    alpha 0.05" written up as pre-registered is precisely the p-hacking the
    correction exists to prevent.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    with caplog.at_level(logging.INFO):
        assert main(["stats", "--run-id", "rid", "--bootstrap", "200",
                     "--metrics", "ndcg10_exp", "--candidates",
                     "k1_0.7__b_0.3"]) == EXIT_OK
    assert "no longer the pre-registered" in caplog.text
    payload = json.loads(
        (testable_run / "runs" / "rid" / "stats.json").read_text())
    assert payload["n_comparisons"] == 1
    assert payload["alpha_bonferroni"] == pytest.approx(0.05)


def test_stats_records_its_parameters_in_the_manifest(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Baseline, candidates, both set sizes, resamples and seed land in the manifest.

    PLAN §7.2: a run is auditable from its manifest alone. The seed and resample
    count are what make the published CI reproducible, and they are the two
    parameters most likely to be varied during debugging and then forgotten.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    assert main(["stats", "--run-id", "rid", "--bootstrap", "200",
                 "--metrics", "ndcg10_exp"]) == EXIT_OK
    manifest = json.loads(
        (testable_run / "runs" / "rid" / "manifest.json").read_text())["stats"]
    assert manifest["baseline"] == "k1_0.9__b_0.4"
    assert manifest["held_out_n"] == 12 and manifest["full_n"] == 16
    assert manifest["bootstrap_resamples"] == 200
    assert manifest["bootstrap_seed"] == 13


def test_stats_tests_every_metric_when_none_is_named(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default is all six pre-registered metrics, not just the primary.

    PLAN §3.3 pre-registers the secondaries precisely so they cannot be chosen
    after the primary disappoints. Running them by default is what makes the
    pre-registration binding rather than aspirational.
    """
    from bm25tune.cli import EXIT_OK, main
    from bm25tune.metrics import METRIC_NAMES

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    assert main(["stats", "--run-id", "rid", "--bootstrap", "100"]) == EXIT_OK
    payload = json.loads(
        (testable_run / "runs" / "rid" / "stats.json").read_text())
    assert {r["metric"] for r in payload["confirmatory"]} == set(METRIC_NAMES)
    assert len(payload["confirmatory"]) == 3 * len(METRIC_NAMES)


def test_stats_can_pull_the_baseline_from_a_second_run(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--run-id-b` adds another run's configs, first run winning a collision.

    PLAN §5.6's signature takes two run ids so a baseline swept earlier can be
    tested against candidates swept later without re-running the search — a real
    saving on a 1063-query sweep, and the alternative (copying run files between
    dirs) destroys provenance.
    """
    from bm25tune.cli import EXIT_OK, main

    other = testable_run / "runs" / "rid-b" / "trecruns"
    other.mkdir(parents=True)
    src = testable_run / "runs" / "rid" / "trecruns" / "k1_0.9__b_0.4.txt"
    (other / "k1_0.9__b_0.4.txt").write_text(src.read_text())
    src.unlink()
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    assert main(["stats", "--run-id", "rid", "--run-id-b", "rid-b",
                 "--bootstrap", "200", "--metrics", "ndcg10_exp"]) == EXIT_OK
    payload = json.loads(
        (testable_run / "runs" / "rid" / "stats.json").read_text())
    assert len(payload["candidates"]) == 3
    assert payload["baseline"] == "k1_0.9__b_0.4"


def test_stats_output_is_reproducible_across_runs(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two identical invocations produce identical `stats.json` bodies.

    `stats.json` is committed (PLAN §7.4), and a bootstrap CI that shifts between
    runs cannot be cited. Only the timestamped manifest entry differs, which is why
    the comparison is on the report file rather than on the whole run dir.
    """
    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    path = testable_run / "runs" / "rid" / "stats.json"
    assert main(["stats", "--run-id", "rid", "--bootstrap", "200",
                 "--metrics", "ndcg10_exp"]) == EXIT_OK
    first = path.read_bytes()
    assert main(["stats", "--run-id", "rid", "--bootstrap", "200",
                 "--metrics", "ndcg10_exp"]) == EXIT_OK
    assert path.read_bytes() == first


def test_stats_requires_a_run_id() -> None:
    """`--run-id` is mandatory — no guessing which sweep is being tested.

    Falling back to the newest run dir would write `stats.json` into whichever
    sweep happened to be latest, next to another run's `scores.csv`.
    """
    from bm25tune.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["stats"])


def test_neither_score_nor_stats_touches_the_network_or_bedrock(
        testable_run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WP4 costs $0: both subcommands run to completion with no client at all.

    The root `no_network` and `no_ambient_creds` fixtures already fail an
    unmarked test that opens a socket; this asserts the stronger property that
    neither path even *imports* `boto3`, which is what keeps re-scoring free and
    the whole suite runnable on a credential-less CI runner (PLAN §4.1).
    """
    import sys

    from bm25tune.cli import EXIT_OK, main

    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(testable_run))
    monkeypatch.delitem(sys.modules, "boto3", raising=False)
    assert main(["score", "--run-id", "rid"]) == EXIT_OK
    assert main(["stats", "--run-id", "rid", "--bootstrap", "100",
                 "--metrics", "ndcg10_exp"]) == EXIT_OK
    assert "boto3" not in sys.modules
