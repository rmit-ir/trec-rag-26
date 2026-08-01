"""What `calibration.py` defends: that WP6's launch/no-launch decision is
reproducible from the grade numbers alone, and that no single-sided gate ever
admits a judge that calls almost everything relevant.

The gate is the one place in the harness where a wrong constant costs money
rather than just correctness — a too-loose gate launches an ~$0.23 calibration
into a multi-dollar sweep judged by a broken prompt, and a too-tight one rejects
a prompt that a careful human reading of the collection endorses (PLAN §3.3b).
So every bound is driven here by a synthetic distribution taken verbatim from
PLAN §3.3's `[verified]` table, with the required verdict hand-stated in the
plan, not read back from the code.

Three regressions these tests exist to catch:

- **The one-sided gate (the defect that motivated the 2026-07-31 rewrite).**
  `{0:1, 1:1, 2:50, 3:48}` — 98 % relevant — passed the pre-rewrite three
  conditions. `test_saturated_distribution_fails_the_ceiling` pins it as a FAIL
  on condition 3-from-above, and would fail again if the ceiling were ever
  dropped back to one-sided.
- **Inclusive bounds.** `facet-v1`'s modal share is *exactly* 0.600; a strict
  `<` would flip the going-in candidate on a rounding convention.
  `test_facet_v1_passes_on_the_inclusive_modal_bound` guards that.
- **Reading the smell test as accuracy.** `agent_agreement`/`roc_auc` must
  order the classes and half-credit ties; the report preamble must carry the
  §3.3b caveat. Tested here so a future edit can't quietly turn AUC into a
  pass/fail criterion.
"""
from __future__ import annotations

import pytest

from bm25tune import calibration as cal
from bm25tune import prompts


# --- The seven PLAN §3.3 synthetic distributions, verdicts stated in the plan.
# (counts, expect_pass, failed-condition names in any order)
GATE_CASES = [
    # =3 is 0.48 <= 0.50, so cond. 4 passes; only the >=2 ceiling catches it —
    # exactly PLAN §3.3's "FAIL cond. 3", and the reason the ceiling is needed.
    pytest.param({0: 1, 1: 1, 2: 50, 3: 48}, False, {cal.COND_SHARE_GE2},
                 id="saturated-98pct-relevant"),
    pytest.param({0: 7, 1: 29, 2: 2, 3: 2}, False, {cal.COND_MODAL,
                                                    cal.COND_SHARE_GE2},
                 id="umbrela-v1-measured"),
    pytest.param({0: 0, 1: 0, 2: 100, 3: 0}, False, {cal.COND_MODAL,
                                                     cal.COND_ALL_GRADES,
                                                     cal.COND_SHARE_GE2},
                 id="all-grade-2"),
    pytest.param({0: 0, 1: 0, 2: 0, 3: 100}, False, {cal.COND_MODAL,
                                                     cal.COND_ALL_GRADES,
                                                     cal.COND_SHARE_GE2,
                                                     cal.COND_SHARE_EQ3},
                 id="all-grade-3"),
    pytest.param({0: 7, 1: 8, 2: 36, 3: 9}, True, set(),
                 id="facet-v1-measured"),
    pytest.param({0: 32, 1: 28, 2: 29, 3: 11}, True, set(), id="mid-band"),
    # §3.3b hand-read pool-reweighted, as integer counts summing to a round n:
    # {0:14, 1:20, 2:40, 3:25} -> modal 0.402, >=2 0.653, =3 0.251. PASS.
    pytest.param({0: 14, 1: 21, 2: 40, 3: 25}, True, set(),
                 id="hand-read-pool-reweighted"),
]


@pytest.mark.parametrize("counts, expect_pass, expected_failures", GATE_CASES)
def test_gate_matches_plan_verdict(counts, expect_pass, expected_failures):
    """Every §3.3 synthetic distribution gets exactly the plan's verdict.

    Drives all four bounds independently — this is the contract that lets
    `calibrate` trust the constants instead of re-deriving them, so a drift in
    any GATE_* constant surfaces here rather than after the sweep has spent.
    """
    result = cal.evaluate_gate(counts)
    assert result.passed is expect_pass
    assert set(result.failed_names()) == expected_failures


def test_saturated_distribution_fails_the_ceiling():
    """The pre-2026-07-31 defect: 98 %-relevant must FAIL, and from ABOVE.

    A regression to a one-sided gate re-admits this and would show up as a
    missing `high` direction here, not just a flipped bool.
    """
    result = cal.evaluate_gate({0: 1, 1: 1, 2: 50, 3: 48})
    assert not result.passed
    ge2 = next(c for c in result.conditions if c.name == cal.COND_SHARE_GE2)
    assert ge2.direction == "high"
    assert ge2.observed == pytest.approx(0.98)


def test_facet_v1_passes_on_the_inclusive_modal_bound():
    """`facet-v1`'s modal share is exactly 0.600 — the inclusive bound must pass it.

    Guards the one place a `<` vs `<=` typo silently changes the going-in
    candidate's fate (PLAN §3.3 "every bound is inclusive").
    """
    result = cal.evaluate_gate({0: 7, 1: 8, 2: 36, 3: 9})
    assert result.modal_share == pytest.approx(0.60)
    assert result.passed
    modal = next(c for c in result.conditions if c.name == cal.COND_MODAL)
    assert modal.passed and modal.direction is None


def test_umbrela_v1_fails_share_from_below_not_above():
    """`umbrela-v1`'s 10 %-at->=2 fails the FLOOR, and the direction says so.

    The direction is the actionable half: `low` tells the operator to loosen the
    prompt, `high` to tighten it — opposite fixes, so recording which side was
    missed is the point of the per-condition verdict.
    """
    result = cal.evaluate_gate({0: 7, 1: 29, 2: 2, 3: 2})
    ge2 = next(c for c in result.conditions if c.name == cal.COND_SHARE_GE2)
    assert not ge2.passed and ge2.direction == "low"
    assert ge2.bound == cal.GATE_MIN_SHARE_GE2


def test_all_grade_two_flags_unused_grades():
    """A judge that only ever says "2" fails the all-grades-used condition.

    nDCG's exponential gain assumes the scale is used; a degenerate single-grade
    distribution has a healthy-looking share but no discriminating power.
    """
    result = cal.evaluate_gate({0: 0, 1: 0, 2: 100, 3: 0})
    ag = next(c for c in result.conditions if c.name == cal.COND_ALL_GRADES)
    assert not ag.passed and ag.direction == "low"


def test_empty_distribution_raises_not_four_false_failures():
    """An all-zero histogram is a driver bug, not four gate failures.

    Silently reporting FAIL×4 for a run that judged nothing would send the
    operator to fix the prompt instead of the pipeline.
    """
    with pytest.raises(cal.CalibrationError):
        cal.evaluate_gate({0: 0, 1: 0, 2: 0, 3: 0})


def test_out_of_range_grade_raises():
    """A grade outside 0-3 means the parser leaked; fail loud, don't clamp."""
    with pytest.raises(cal.CalibrationError):
        cal.evaluate_gate({0: 1, 4: 1})


def test_counts_are_summed_not_overwritten():
    """Duplicate/partial keys accumulate — `_normalize_counts` must add.

    A dict comprehension that assigned instead of added would drop counts on any
    caller that passed the same grade twice; cheap to get wrong, silent when it is.
    """
    result = cal.evaluate_gate({2: 10, 3: 5})
    assert result.n == 15
    assert result.counts[0] == 0 and result.counts[1] == 0


# --- Entropy ---------------------------------------------------------------

def test_entropy_is_max_on_uniform_and_zero_on_degenerate():
    """Entropy pins the two extremes: 2.0 bits uniform over 4 grades, 0.0 for one.

    Reported next to modal share because it catches `{0:50, 3:50}` — a healthy
    0.50 modal share that still uses only half the scale.
    """
    assert cal.grade_entropy({0: 25, 1: 25, 2: 25, 3: 25}) == pytest.approx(2.0)
    assert cal.grade_entropy({2: 100}) == pytest.approx(0.0)
    half = cal.grade_entropy({0: 50, 3: 50})
    assert half == pytest.approx(1.0)


# --- Pool reweighting ------------------------------------------------------

def test_reweight_projects_sample_shares_onto_pool_mix():
    """Reweighting moves an enriched-positive sample toward the pool's share.

    The sample over-samples positives ~1.8x (PLAN §3.1); the reweighted share>=2
    must land below the raw sample share, or the report compares two different
    quantities and reads as leniency.
    """
    by_class = {
        # positives skew high, negatives skew low — the realistic shape.
        "positive": {0: 1, 1: 4, 2: 20, 3: 15},
        "negative": {0: 25, 1: 20, 2: 8, 3: 2},
    }
    raw = cal.counts_from_grades(
        [g for cls in by_class.values() for g, n in cls.items() for _ in range(n)])
    raw_ge2 = (raw[2] + raw[3]) / sum(raw.values())
    pooled = cal.reweight_to_pool(by_class)
    assert pooled[2] + pooled[3] < raw_ge2
    assert sum(pooled.values()) == pytest.approx(1.0)


def test_reweight_renormalizes_when_a_class_is_absent():
    """A class the run never judged drops out and the rest renormalize.

    Otherwise a run with zero `unjudged` pairs would silently under-weight the
    positives and negatives it did judge.
    """
    pooled = cal.reweight_to_pool({"positive": {2: 10}, "negative": {0: 10}})
    assert sum(pooled.values()) == pytest.approx(1.0)


def test_reweight_with_no_overlap_raises():
    """No sampled class overlaps the pool mix -> undefined, so raise."""
    with pytest.raises(cal.CalibrationError):
        cal.reweight_to_pool({"positive": {}}, pool_mix={"negative": 10})


# --- AUC smell test --------------------------------------------------------

def test_auc_perfect_separation_and_half_credit_ties():
    """AUC = 1.0 when positives strictly dominate; ties score half.

    Grades take four values over hundreds of pairs, so ties are the common case;
    a tie-blind implementation would report ~0.5 for a judge that separates the
    classes perfectly at coarse granularity, inventing a false alarm.
    """
    assert cal.roc_auc([3, 3, 2], [0, 1, 1]) == pytest.approx(1.0)
    # all pairs tie -> 0.5 exactly (every comparison is half credit).
    assert cal.roc_auc([2, 2], [2, 2]) == pytest.approx(0.5)
    # one strict win, one tie, two losses out of four -> (1 + 0.5)/4.
    assert cal.roc_auc([2], [1, 2, 3, 3]) == pytest.approx(1.5 / 4)


def test_auc_none_when_a_class_is_empty():
    """AUC is undefined, not 0.5, when one class has no pairs.

    Returning 0.5 there would report a "no separation" finding for a sample that
    simply lacks a class to separate.
    """
    assert cal.roc_auc([1, 2], []) is None
    assert cal.roc_auc([], [1, 2]) is None


def test_agent_agreement_orders_classes_and_flags_anti_correlation():
    """`ordered` tracks committed>rejected; `anti_correlated` fires only below 0.5.

    These are the two report signals; per §3.3b Finding 1 mere overlap is
    expected, so only anti-correlation is the alarm and the flags must not
    conflate the two.
    """
    good = cal.agent_agreement({"positive": [3, 2, 2], "negative": [0, 1, 0]})
    assert good.ordered and not good.anti_correlated
    assert good.auc == pytest.approx(1.0)

    bad = cal.agent_agreement({"positive": [0, 1], "negative": [3, 2]})
    assert not bad.ordered and bad.anti_correlated


# --- Decision rule ---------------------------------------------------------

def _variant(version, counts, *, pos=None, neg=None):
    """Build a VariantResult from a grade histogram for the decision tests."""
    grades_by_class = {}
    if pos is not None:
        grades_by_class["positive"] = pos
    if neg is not None:
        grades_by_class["negative"] = neg
    return cal.VariantResult(
        prompt_version=version,
        gate=cal.evaluate_gate(counts),
        agreement=cal.agent_agreement(grades_by_class),
        counts_by_class={},
    )


def test_decision_picks_lowest_modal_share_among_passers():
    """Among gate passers the winner has the lowest modal share, not the best AUC.

    Optimizing AUC would select the variant that best mimics the agent's staging
    heuristic (§3.3b Finding 1); modal share is what the sweep actually needs
    because a mode-dominated judge ties neighbouring grid cells.
    """
    flat = _variant("mid-band", {0: 32, 1: 28, 2: 29, 3: 11},
                    pos=[2, 2], neg=[0, 1])          # lower modal share (0.321)
    peaky = _variant("facet-v1", {0: 7, 1: 8, 2: 36, 3: 9},
                     pos=[3, 3], neg=[0, 0])          # higher AUC, modal 0.600
    decision = cal.decide([peaky, flat])
    assert decision.winner == "mid-band"
    assert not decision.gated
    assert set(decision.passing) == {"mid-band", "facet-v1"}


def test_decision_tie_breaks_equal_modal_share_by_auc():
    """Equal modal share -> higher AUC wins the tie.

    AUC is the *secondary* key precisely so it only decides among otherwise
    equivalent judges, never overrides the primary spread criterion.
    """
    a = _variant("a", {0: 30, 1: 30, 2: 30, 3: 10}, pos=[3, 3], neg=[0, 0])
    b = _variant("b", {0: 30, 1: 30, 2: 30, 3: 10}, pos=[2, 1], neg=[1, 2])
    decision = cal.decide([b, a])
    assert decision.winner == "a"


def test_decision_all_fail_ranks_by_distance_from_band():
    """When every variant misses the band, best_effort is the smallest miss.

    Distance-from-band, not modal share, is the primary fallback key so the
    operator is pointed at the prompt needing the *least* correction.
    """
    far = _variant("far", {0: 60, 1: 30, 2: 8, 3: 2})    # 0.10 at >=2, miss 0.10
    near = _variant("near", {0: 45, 1: 40, 2: 12, 3: 3})  # 0.15 at >=2, miss 0.05
    decision = cal.decide([far, near])
    assert decision.gated
    assert decision.best_effort == "near"
    assert decision.ranked[0] == "near"


def test_decide_on_empty_raises():
    """No variants at all is a driver bug — raise rather than return a null decision."""
    with pytest.raises(cal.CalibrationError):
        cal.decide([])


# --- Report rendering ------------------------------------------------------

def _sample_results():
    return [
        _variant("facet-v1", {0: 7, 1: 8, 2: 36, 3: 9},
                 pos=[3, 2, 2], neg=[0, 1, 2]),
        _variant("umbrela-v1", {0: 7, 1: 29, 2: 2, 3: 2},
                 pos=[2, 1], neg=[0, 0]),
    ]


def test_report_leads_with_verdict_and_carries_the_caveats():
    """The report a reviewer opens must state the decision and the §3.3b caveats.

    A reader who opens only report.md must not be able to read agent agreement
    as accuracy, nor compare sample share to pool share — both are load-bearing
    warnings, so their absence is a regression.
    """
    results = _sample_results()
    decision = cal.decide(results)
    md = cal.render_report_md(results, decision, run_id="cal-test",
                              sample_path="data/bm25-tune/calibration/sample-280.jsonl",
                              n_pairs=280, model_id="openai.gpt-oss-20b-1:0")
    assert "## Verdict" in md
    assert "floor on usability, not the selection criterion" in md
    assert "smell test, not accuracy" in md
    assert "deliberately not the pool" in md
    # both label mixes appear, so the two shares are never confused.
    assert "pool label mix" in md
    # the winner is named in the verdict.
    assert f"`{decision.winner}`" in md


def test_report_marks_missed_condition_direction():
    """A failing variant's row shows WHICH bound moved and in which direction.

    `umbrela-v1` misses conditions 1 (modal, high) and 3 (share, low); the row
    must encode `1^` and `3v` so the operator reads the fix off the table.
    """
    results = _sample_results()
    md = cal.render_report_md(results, cal.decide(results), run_id="cal-test",
                              sample_path="s", n_pairs=280)
    assert "1^" in md and "3v" in md


def test_report_totals_cost_across_variants():
    """The cost row sums per-variant spend — the receipt the report exists to keep.

    PLAN requires costs stored for the paper's cost analysis; a report that
    dropped the total would lose the one figure WP7's budget check reads back.
    """
    results = [
        cal.VariantResult("a", cal.evaluate_gate({0: 1, 1: 1, 2: 1, 3: 1}),
                          cal.agent_agreement({}), cost_usd=0.10, calls=280),
        cal.VariantResult("b", cal.evaluate_gate({0: 1, 1: 1, 2: 1, 3: 1}),
                          cal.agent_agreement({}), cost_usd=0.13, calls=280),
    ]
    md = cal.render_report_md(results, cal.decide(results), run_id="c",
                              sample_path="s", n_pairs=280)
    assert "$0.2300" in md


def test_report_lists_prompt_provenance_sha_for_real_variants():
    """Each variant row cites its template sha256, pinning what was actually judged.

    A prompt edit forces a new sha (PLAN's registry contract); the report is
    where that pin becomes auditable against the cache keys.
    """
    results = _sample_results()
    md = cal.render_report_md(results, cal.decide(results), run_id="c",
                              sample_path="s", n_pairs=280)
    for v in ("facet-v1", "umbrela-v1"):
        sha = prompts.get_prompt(v).template_sha256[:16]
        assert sha in md


def test_gate_log_lines_are_greppable_per_condition():
    """`[GATE]` lines carry the distribution and one line per condition.

    PLAN §5.6 wants these greppable in the live log so a multi-variant run says
    which bound moved without reopening the report.
    """
    r = _variant("facet-v1", {0: 7, 1: 8, 2: 36, 3: 9})
    lines = cal.gate_log_lines(r)
    assert all(ln.startswith("[GATE]") for ln in lines)
    assert any("verdict=PASS" in ln for ln in lines)
    # one summary + four condition lines.
    assert len(lines) == 1 + len(cal.CONDITION_ORDER)
