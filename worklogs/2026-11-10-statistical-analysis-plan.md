# Statistical analysis plan for the official evaluation results

Date: 2026-11-10. Status: plan for review, not yet implemented in `scripts/generate_figures_and_tables.py`.

## 1. Purpose

Replace the current ad hoc paired tests (Section 6.1 of the report) with a plan that (a) controls multiplicity where we compare many systems, (b) treats the two side-by-side (SxS) comparisons as single pairwise comparisons with a test suited to Bradley-Terry (BT) ratings, and (c) states assumptions and limits explicitly.

## 2. Data available

### 2.1 Coverage scores (NIST TSVs in `RMIT-ADM+S scores/`)

| Collection | Narratives | Items |
|---|---|---|
| B1 human rubrics | 17 | rubric items written by NIST assessors |
| B2 manual nuggets | 25 | human nuggets; 2 narratives have no vital item |
| B2 auto nuggets | 25 | AutoNuggetizer nuggets |

- All 7 of our runs are scored on every narrative of every collection (complete narrative x system block design, one observation per cell).
- Per cell: `vital_strict` and `all_strict`, fractions in [0,1]. Only full support counts (README definition); partial support scores zero. A zero denominator scores zero.
- Per narrative the TSVs also give min, max and median over all participants' runs (rounded). Other teams' individual scores are not available.
- A single LLM judge (GPT-6.1 Sol, medium reasoning) made one assignment pass. Item-level assignments are not released.
- Item counts are not released. Smallest denominators consistent with all seven runs' scores (lower bounds only): B1 vital median 3, B1 all median 7, B2 manual vital 7, B2 manual all 15, B2 auto all 25 on every narrative. For 12 of 17 B1 narratives there are at most 2 distinct vital values, so the true denominators are not identifiable. These must not be reported as item counts.
- Two B2-manual narratives (`rag2026-89`, `rag2026-114`) have `vital_strict_max = 0.0` field-wide because the vital denominator is zero. The metric is structurally undefined there.

### 2.2 Side-by-side preference (only `owa-glm5` and `sol-research-first`)

| | B1 BT (95% CI) | B1 W/T/L | B2 BT (95% CI) | B2 W/T/L |
|---|---|---|---|---|
| `owa-glm5` | 1212.8 [1156.3, 1269.3] | 123/23/34 | 1049.0 [1006.6, 1091.4] | 122/28/94 |
| `sol-research-first` | 1062.7 [1013.7, 1111.6] | 93/30/64 | 1124.7 [1081.0, 1168.4] | 135/26/68 |

- BT is fitted per batch with arena-rank over all judgments; the CI is a sandwich estimator at judgment level, not clustered by narrative.
- Per-narrative W/T/L is available for both runs. Opponents are not identified, and the runs' battle totals differ, so they are not simply facing each other.
- Not available: per-judgment records, the covariance of the two ratings.

### 2.3 Limits that apply to every analysis

- One run per system: run-to-run generation noise is not separable from the system effect. Inference generalizes over topics only, for these exact runs.
- One judge pass: judge noise is not captured.
- B1 and B2 differ in narratives and rubric construction; they are not pooled naively.
- Power is low at N = 17 and 25. Non-significant results are reported as "no evidence of a difference", with the minimum detectable difference.

### 2.4 Sparsity of B1 differences

Nonzero paired differences per pair (21 pairs per collection and metric), min / median / max:

| Collection, metric | Nonzero diffs | Pairs with >1% degenerate bootstrap resamples |
|---|---|---|
| B1 vital | 2 / 4 / 10 | 12 of 21 (worst 11.9%) |
| B1 all | 4 / 7 / 12 | 2 of 21 |
| B2 manual vital, all | 7 / 14 / 21, 13 / 19 / 24 | 0 |
| B2 auto vital, all | 17 / 24 / 25, 19 / 24 / 25 | 0 |

B1 `all_strict` ties are largely ceiling effects (for the two SxS runs, both score 1.0 on 8 of 17 narratives).

## 3. Part A: all-pairs comparison of our 7 systems on coverage

Six families (B1, B2 manual, B2 auto, each for vital and all), 21 pairs each. Narratives are blocks; systems are treatments.

### 3.1 Primary procedure

Romano-Wolf step-down on a narrative-level studentized bootstrap-t.

1. For each pair, observed statistic t_ij = mean(d_ij) / SE_ij with the pair-specific paired SE = SD(d_ij) / sqrt(N). A pooled ANOVA MSE is not used: bounded scores make variances of differences depend on the pair's mean level.
2. Resample narratives with replacement (the whole row of 7 scores), recompute mean and SE inside each resample, and form t*_ij = (mean* - mean) / SE*.
3. Adjusted p-values from the step-down max of |t*| over the remaining pairs; simultaneous CIs from the single-step max quantile.
4. At least 20,000 resamples, fixed seed, results stored in the audit JSON.

Reasons: no normality assumption, no subset pivotality requirement, heteroscedasticity handled by pair-specific studentization, p-values and CIs come from the same distribution so they cannot contradict each other.

### 3.2 Sparse-difference rule (fixed in advance)

- A pair with fewer than 8 nonzero differences is not analyzed with the bootstrap-t. A resample can then have SE* = 0 with a nonzero numerator (probability about (z/N)^N, for example 1.05% for 13 of 17 zeros), which gives infinite statistics.
- For those pairs use the exact sign-flip test conditional on the nonzero differences and report no simultaneous CI. With 4 nonzero differences the smallest two-sided p is 0.125, so these pairs carry little inferential power. Report this as a limitation of the B1 benchmark rather than as evidence of equality.
- A pair with all differences zero gets t = 0 and is excluded from the max set.
- The rule depends only on counts of nonzero differences and is applied uniformly, not chosen per pair after seeing results.

### 3.3 Cross-checks

1. Label-permutation studentized max-T within narratives (the permutation analogue of Tukey HSD). It tests the global null only and is not exact for pairwise nulls under unequal variances.
2. Simultaneous sign-flip max-T over the 21 difference vectors. It assumes joint symmetry of centered scores, which ceiling-bound data may violate.
3. Tukey-Kramer from a two-way ANOVA with narrative as a block, using the residual MSE and `scipy.stats.studentized_range`. This is the familiar-name check; plain `pairwise_tukeyhsd` is not used because it ignores blocking.
4. Flag every pair whose significance differs between the primary and the cross-checks.

### 3.4 Planned contrasts

The four ablation pairs (`brief-hybrid` vs `brief-base`, `sol-research-first` vs `sol-default`, `owa-glm5` vs `brief-hybrid`, `facets` vs `facetrag`) are shown in the main text. They were selected after the results were visible, so they are reported as exploratory within the 21-pair family: Holm-4 and the 21-pair Romano-Wolf adjusted p-values side by side.

### 3.5 Details

- Drop the two zero-vital narratives for B2-manual vital analyses (N = 23); keep N = 25 for `all_strict` and note the N = 25 figure in a footnote.
- Effect sizes: mean difference in percentage points, paired standardized effect (d_z) with a bootstrap-t or BCa interval. Plain percentile bootstrap intervals are not used (they undercover at N = 17 and produced the earlier CI vs p-value mismatch).
- Collections are not pooled. B2 auto and B2 manual share narratives and are separate families.
- Secondary: stratified permutation across B1 and one B2 collection with a System x Batch interaction test (narratives differ between batches, so batch differences use independent-sample logic). Friedman/Nemenyi is demoted to an optional appendix check.
- Reporting uses a forest plot of pairwise differences with unadjusted intervals (inner) and simultaneous intervals (outer), not compact-letter displays.

## 4. Part B: track median and maximum

Descriptive only: counts of narratives at or above the median (tolerance as in the current code), with exact binomial CIs. No p-values. The median includes our own runs and is rounded, and other teams' per-narrative scores are unavailable, so these are not tests of superiority.

## 5. Part C: side-by-side Bradley-Terry

Two single pairwise comparisons (one per batch), Holm over the two, plus a heterogeneity test.

### C1. Wald test on the rating difference (primary)

SE = CI half-width / 1.96 (CIs are symmetric); z = (r1 - r2) / sqrt(SE1^2 + SE2^2).

| Batch | Difference (`owa-glm5` minus `sol-research-first`) | z | p | Holm p |
|---|---|---|---|---|
| B1 | +150.1 | 3.94 | 8.3e-5 | 1.7e-4 |
| B2 | -75.7 | 2.44 | 0.015 | 0.015 |

- Overlapping CIs are not a test (B2 CIs overlap while the difference is significant).
- Under standard Elo scaling (to be confirmed in the arena-rank source), 150 points is about a 70% win probability and 76 points about 61%.
- Correlation sensitivity: the variance of the rating difference is invariant to the identifiability constraint, but the marginal SEs and their covariance are not, so the sign of the correlation rho between the two estimates is unknown. Report only the tipping point: B2 reaches p = 0.05 at rho = -0.55 (p = 0.084 at -0.99); B1 stays significant for every admissible rho (z = 2.80, p = 0.005 at -0.99).

### C2. Narrative-clustered nonparametric check

Per narrative and run: s = (W + 0.5 T) / (W + T + L). Test d_t = s(A,t) - s(B,t) with a paired sign-flip permutation and a bootstrap-t interval, both unweighted and weighted by battle count. Assumes comparable opponent pools, which cannot be verified.

### C3. Contrast design effect (stress test for C1)

Under independent judgments, the expected variance of d_t is v_t = sigma_A^2 / m_At + sigma_B^2 / m_Bt, with pooled judgment-level variance of outcomes {1, 0.5, 0} per run. With weights w_t = (1/m_At + 1/m_Bt)^-1 the design effect is Cochran's Q / (N - 1), where Q = sum_t w_t (d_t - d_w)^2 / sigma^2.

- Reference distribution by simulating independent judgments (the chi-square approximation is crude at about 10 battles per narrative with ties).
- Report phi with a CI, and the z of C1 divided by sqrt(max(1, phi)).
- It reflects genuine narrative-by-system heterogeneity, which is appropriate when generalizing over topics. Opponent strength remains confounded.

### C4. Heterogeneity across batches

d1 = +150.1 and d2 = -75.7 are independent (different narratives, separate fits): z = (d1 - d2) / sqrt(var1 + var2) = 4.59. Assumes the Elo units are comparable across batches.

### C5. Request to the organizers (two tiers)

1. Anonymized per-judgment rows (narrative, system A, system B, outcome), so BT can be refit with a narrative-cluster bootstrap.
2. Failing that, an arena-rank run clustered by narrative with the 2 x 2 covariance of our two ratings.
3. Also ask for item counts per narrative (vital and okay), which would allow an item-weighted binomial sensitivity analysis.

## 6. Coverage versus human preference for the two SxS runs

Coverage difference `owa-glm5` minus `sol-research-first` (negative = `sol-research-first` ahead):

| Collection | vital | all | `owa-glm5` ahead on narratives (vital W/T/L; all W/T/L) |
|---|---|---|---|
| B1 | -0.039 | -0.065 | 1/13/3; 0/13/4 |
| B2 manual | -0.134 | -0.096 | 1/10/14; 3/6/16 |
| B2 auto | -0.361 | -0.317 | 0/0/25; 0/0/25 |

Humans prefer `owa-glm5` in B1 (+150 Elo) while the LLM judge scores it lower or tied; both agree in B2. Compare like with like (B1 human to B2 manual), and test the System x Batch interaction for this pair on coverage. Explanations (length, presentation style, judge self-preference with the Sol family) are hypotheses and are not claimed. An exploratory length analysis is feasible from our own outputs: per-narrative answer length against the per-narrative preference score and the coverage difference, labeled hypothesis-generating (n = 17 and 25).

## 7. Reporting conventions

- Report raw and adjusted p-values and CIs, naming the method in table notes.
- State the limits of Section 2.3 once.
- Say "no evidence of a difference", not "equal", for non-significant results, with the minimum detectable difference.
- All numbers computed in `scripts/generate_figures_and_tables.py` with fixed seeds, written to the audit JSON.

## 8. Open decisions

1. Whether to send the organizer request (C5).
2. Whether the contrast in Section 3.4 may be labeled planned (it cannot, on the facts above).
3. Whether the stratified pooled analysis goes into the main text or the appendix.

## 9. Implementation results (scripts/statistical_analysis.py, seed 2026, 20,000 draws)

Run with `python3 scripts/generate_figures_and_tables.py` (about 15 s; skip with `--skip-statistical-plan`). Output: audit JSON key `statistical_plan` and `figures/pairwise-forest.pdf`.

- Part C, B1: Wald z = 3.94 (p = 8.3e-5, Holm 1.7e-4); narrative-clustered sign-flip p = 0.0057 (13 narratives favor `owa-glm5`, 4 `sol-research-first`); contrast DEFF = 1.29 (CI 0.52-1.94); DEFF-adjusted z = 3.47. Robust.
- Part C, B2: Wald z = -2.44 (p = 0.015, tipping rho = -0.55); narrative-clustered sign-flip p = 0.110 (battle-weighted 0.140, CI [-0.227, +0.008]); DEFF = 1.54 (CI 0.62-2.77, null p = 0.038); DEFF-adjusted z = -1.97 (p = 0.049). The B2 preference result does not survive narrative clustering cleanly and should be described as suggestive.
- Heterogeneity across batches: z = 4.59 (p = 4.4e-6).
- Part D: System x Batch interaction on coverage for `owa-glm5` minus `sol-research-first`: vital p = 0.134 (n = 17 vs 23), all p = 0.659. No evidence that the coverage gap differs between B1 and B2-manual; the stratified B1 + B2-manual pooled analysis has no significant pair-by-batch interactions after Holm-21.
- Part A: Romano-Wolf bootstrap-t is much more conservative than Holm on exact sign-flip p-values (for example `owa-glm5` vs `brief-hybrid`, B2 manual vital: raw 0.001, Holm-21 0.015, label-permutation max-T 0.057, Romano-Wolf 0.111). The pairs that differ between methods are listed in the audit field `methods_disagree`. In B1, 16 of 21 vital pairs and 14 of 21 all pairs are sparse (< 8 nonzero differences) and are tested only by the exact sign-flip. Contrasts between `facetrag` and the other systems are robust across every method.
- Length analysis (Section 6) implemented in `scripts/length_analysis.py` after the Sol submissions were found in Kun's directory on sunfyre; results in `analysis/length-analysis.md` (per-narrative counts in `analysis/length-per-narrative.csv`; raw answers not stored).

## 10. Final decisions (2026-11-11) — supersedes the primary-method choices above

Code: `tasks/official_stats/` (`statistical_analysis.py`, `length_analysis.py`, `readability_vs_preference.py`);
all outputs: `worklogs/assets/2026-11-11-official-stats/` (`statistical-analysis-results.md` is the full review file;
`console-statistical-analysis.txt` is the run summary). Reproduce:

```bash
uv run --project tasks/official_stats python tasks/official_stats/statistical_analysis.py
uv run --project tasks/official_stats python tasks/official_stats/length_analysis.py --counts worklogs/assets/2026-11-11-official-stats/length-per-narrative.csv
uv run --project tasks/official_stats python tasks/official_stats/readability_vs_preference.py
```

`length_analysis.py` needs raw submissions (`--run tag=path`) only to rebuild `length-per-narrative.csv`; the counts
CSV is committed so the analysis reruns without them.

Decisions, all at alpha = 0.05, one test per question:

| Question | Test |
|---|---|
| All-pairs system comparison (21 pairs per collection x metric) | **Tukey HSD** on the narrative-blocked two-way model (primary). Romano-Wolf, label-permutation and sign-flip max-T, Holm-21 are sensitivity columns only. |
| Planned ablation contrasts (4) | Holm over the four sign-flip p-values (Tukey p also shown) |
| Each SxS batch | Bradley-Terry Wald z from the published CIs, plus narrative-clustered sign-flip p |
| Between-batch comparison | Two-sample permutation on the **per-narrative battle-score difference** (B1 +0.158 vs B2 -0.093, p = 0.0024). The earlier BT diff-of-diffs (+225.8, z = 4.59) assumes the two separately fitted BT scales are comparable; it is kept in the output labelled as assumption-laden and is not used in the paper. |
| Length vs coverage | Mean within-narrative Spearman (permutation p), Holm over 6 collection x metric rows; Tukey HSD on log words for length differences |
| Readability (B1 only) | Paired sign test (exact binomial) per formula with Holm; Spearman vs per-narrative preference as an exploratory association |

Results (details and all 21 pairs in `statistical-analysis-results.md`):

- Tukey significant pairs of 21: B1 vital 6, B1 all 6, B2 manual vital 9, B2 manual all 10, B2 auto vital 15, B2 auto all 15
  (Romano-Wolf: 5, 6, 5, 6, 14, 14). No pair among brief-hybrid, brief-base, sol-default, sol-research-first is significant in any family.
  facetrag is below every other run except owa-glm5 in B2 manual vital (p = 0.117). owa-glm5 vs the four leading runs is significant in
  B2 manual (e.g. vs brief-hybrid p = 0.004 all_strict) and B2 auto, not in B1.
- Ablation contrasts (all_strict, Holm-4): hybrid-base and research-first-default never significant; facets-facetrag significant in all three
  (B1 p = 0.010); owa-glm5 - brief-hybrid significant in B2 manual (0.003) and auto (<0.001), not B1 (0.094).
- SxS: B1 +150.1 rating points, Wald z = 3.94, p = 8.3e-5; 13/4 narratives, clustered p = 0.0057. B2 -75.7, z = -2.44, p = 0.015;
  9/16 narratives, clustered p = 0.110. Tipping correlation: B1 stays significant at rho = -0.99 (p = 0.005), B2 does not (p = 0.084).
- Length: within-narrative rho = +0.42 (B1), +0.52 (B2 manual), +0.72 (B2 auto) for all_strict, Holm p = 0.001 each (all six rows significant).
  Tukey on log words: 17 of 21 pairs differ; facetrag about 0.4x others, owa-glm5 0.76-0.86x the four leading runs.
- Readability (B1, n = 17): owa-glm5 lower Flesch-Kincaid grade on 17/17 (sign test p = 1.5e-5, Holm 1.1e-4); no association with the per-narrative
  preference margin (FK rho = +0.27, p = 0.30; smallest Holm p = 0.83). Length ratio unrelated to preference or coverage differences
  (Holm p = 1.0 in B1, 0.215 in B2). No System x Batch interaction on coverage (vital p = 0.135, all p = 0.66).
