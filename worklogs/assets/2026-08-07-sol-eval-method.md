## Decision

Yes. Make standalone rubric grading the **primary factorial endpoint**, and demote arena evaluation to a **confirmatory comparison against `aus_agent_v2` for only the top one or two cells**.

Why:

- It halves the number of judge calls per factorial cell: **15 instead of 30**.
- Each call returns substantially richer evidence: approximately 31 criterion-level ordinal grades rather than one win/loss/tie.
- It aligns directly with the factorial question: which factors and interactions improve answer quality, and on which rubric dimensions?
- It avoids spending half the evaluation budget on battle-order duplication.
- Existing Terra/Sol generations remain fully usable; no generation work is wasted.

The real downside is construct validity: standalone grading measures rubric quality, while arena directly measures the stated competitive objective, **“beat `aus_agent_v2`.”** A cell can score well absolutely yet lose head-to-head because of style, answer length, judge-relative calibration, or dimensions not fully represented in the rubric. Therefore, arena should not disappear—it should become a targeted final check.

I would use this evaluation hierarchy:

1. **Primary:** standalone official-rubric grades for every factorial cell.
2. **Calibration:** if existing `aus_agent_v2` answers are available, run those through the same `score_one()` pipeline on the same 15 topics. This costs only 15 additional standalone calls total and gives a directly comparable in-run baseline.
3. **Confirmatory:** arena against `aus_agent_v2` for the best one cell, or at most the best two cells if budget permits.

The README’s `0.7042` can be cited as historical context, but it is only directly comparable if the rubric set, judge model/version, grading prompt, aggregation formula, and topic set are identical. Since it covers all 30 topics while Block 1 uses 15, re-scoring `aus_agent_v2` on the same 15 topics is preferable.

---

## Revised Block 1 budget

Let:

- \(C\) = number of Block 1 cells
- \(J_s\) = dollar cost of one `score_one()` call
- \(J_a\) = dollar cost of one arena call
- \(K\) = number of finalist cells receiving arena confirmation, normally 1 or 2
- \(G\) = total Block 1 generation cost, unchanged

### Judge-call counts

| Evaluation plan | Judge calls |
|---|---:|
| Original arena for every cell | \(30C\) |
| Standalone primary only | \(15C\) |
| Standalone + arena for top 1 | \(15C + 30\) |
| Standalone + arena for top 2 | \(15C + 60\) |
| Add same-topic standalone calibration of `aus_agent_v2` | Add 15 |

Thus, before finalist confirmation, judging is cut exactly in half by call count. Relative to the original plan, the net call savings are:

- Top one arena finalist: \(15C - 30\)
- Top two arena finalists: \(15C - 60\)

The dollar formulas are:

\[
B_{\text{old}} = G + 30C J_a
\]

\[
B_{\text{new}} = G + 15C J_s + 30KJ_a
\]

or, with same-run standalone scoring of `aus_agent_v2`:

\[
B_{\text{new+baseline}} = G + 15(C+1)J_s + 30KJ_a
\]

Call count should not be treated as perfectly proportional to dollars. `score_one()` omits the opponent answer but asks for roughly 31 grades, so its output may be longer than an arena verdict. It should still normally be cheaper, but actual input/output token usage should be metered.

### Should Block 1 add cells now?

The evaluation change creates room in principle, but I would **not commit the saved budget immediately**, because GPT-OSS and Qwen generation cost remains the largest unresolved risk and the AWS session is currently blocking measurement.

Recommended sequence:

1. Finish or meter at least a small GPT-OSS/Qwen generation sample after credentials are refreshed.
2. Reserve:
   - all remaining base-cell generation,
   - all standalone grading,
   - 15 calls for optional same-run `aus_agent_v2` calibration,
   - 30 arena calls for one finalist,
   - a generation-cost safety margin.
3. Only then release the remaining headroom to additional cells.

For each additional cell using model \(m\), the marginal cost is approximately:

\[
15(G_m + J_s)
\]

where \(G_m\) is the measured generation cost per topic for that model.

If money remains, prioritize **a small adjacent-pages × model interaction extension from Block 2** over a broad Block 3 analyst-model sweep. The interaction extension is more informative for the existing factorial design and requires fewer opportunistic comparisons. A broad model sweep should wait unless measured Bedrock costs leave clearly sufficient headroom.

In short: **bank the savings initially as safety margin, then conditionally add the highest-value interaction cells after real Bedrock costs are known.** Do not let the nominal halving of judge calls jeopardize the hard $50 cap.

---

## Updated primary analysis

### Data shape

For topic \(t\), factorial cell \(c\), and rubric criterion \(r\):

\[
y_{tcr} \in \{0,1,2,3\}
\]

There are approximately 31 criterion grades produced jointly for each cell-topic answer.

### Primary model

Use a hierarchical cumulative-link mixed model, preferably proportional-odds unless diagnostics show a serious violation:

\[
\operatorname{logit}\Pr(y_{tcr} \le k)
=
\theta_{r,k}
-
\left(
X_c\beta + u_t + v_{tc} + b_r
\right)
\]

with:

- criterion-specific thresholds \(\theta_{r,k}\),
- fixed effects for the prespecified factorial factors and supported interactions,
- topic random intercept \(u_t\),
- a cell-topic/answer random intercept \(v_{tc}\), accounting for the fact that all criterion grades for one answer come from the same answer and judge call,
- criterion-level variation, ideally including partially pooled criterion-specific factor effects when sample size and fitting stability allow.

The primary factorial tests should be **omnibus tests of each factor and prespecified interaction across the rubric as a whole**, followed by model-derived planned contrasts between cells. Report predicted grade probabilities and a readable marginal quantity such as expected normalized grade:

\[
E[y]/3
\]

Do not treat the roughly \(31 \times 15\) grades in a cell as independent observations; criteria from the same answer are correlated and were generated in one judge call.

### Criterion-specific interpretation

Do not make 31 independent models the sole primary analysis. That would fragment power and turn the primary result into a multiple-testing exercise.

Instead:

1. Use the hierarchical all-criteria ordinal model for the primary overall factorial conclusions.
2. Fit criterion-specific cumulative-link models as secondary localization analyses.
3. Apply Benjamini–Hochberg FDR correction across the approximately 31 criterion-level tests for each prespecified factor or contrast family.
4. Clearly distinguish:
   - confirmatory factorial effects,
   - FDR-controlled criterion findings,
   - exploratory criterion patterns.

If the hierarchical ordinal model proves unstable, the fallback primary endpoint can be the answer-level mean of available criterion grades, normalized to 0–1, analyzed with topic blocking/mixed effects. However, the ordinal model should remain the first choice because it preserves the actual 0–3 scale.

### `ograde`

Retain `ograde` as a secondary summary endpoint and sanity check unless the script/documentation establishes that it is the official predeclared aggregate. Avoid making it co-primary after seeing results.

Also preserve missing/N/A criteria as missing; do not convert them to zero. Any criterion weighting or exclusion rule must be fixed before examining cell outcomes.

### Winner selection

Predeclare the selection rule for arena confirmation—for example:

- highest model-estimated overall rubric score, subject to no critical criterion regression; or
- top two cells by adjusted expected normalized grade.

Because finalists are selected using the standalone results, arena confidence intervals should still be reported, not merely a winner label. If only one finalist can be afforded, compare that cell against `aus_agent_v2` in both battle orders across all 15 topics.

---

## `score_one()` implementation and cost notes

The existing function should be reused/adapted from:

`tasks/task-comparison/scripts/rubric_scorecard_aus_agent_vs_facets_agent.py`

Important operational points:

- It is **one judge request per system answer**, not one request per rubric criterion.
- It grades one answer against all official criteria and returns criterion-level 0–3 grades plus `ograde`.
- No opponent answer or battle-order duplication is required.
- Therefore the base evaluation workload is exactly **15 calls per cell**.
- Reuse its existing prompt, rubric loading, parsing, and output schema rather than recreating a second grader.
- The surrounding script name may contain assumptions about the two historical systems, filenames, labels, or output paths; adapt those orchestration details while preserving the proven grading call.
- Log actual input tokens, output tokens, retries, parse failures, and judge model/version. One nominal call can become multiple billed requests if retry logic fires.
- Store one row per `cell × topic × criterion`, plus a call/answer identifier so the analysis can model within-call correlation.
- Pin the rubric version and judge configuration for the entire experiment.

I would not guess the exact Python parameter list without quoting the checked source. The orchestrator should call the function using its real in-repository signature and add only a thin batch wrapper mapping each generated answer into that interface.

**Bottom line:** standalone rubric grading should become primary. Keep one finalist arena comparison reserved, optionally two after costs are measured; use the remaining theoretical savings first as Bedrock-cost protection and only then to add a compact adjacent-pages × model interaction extension.