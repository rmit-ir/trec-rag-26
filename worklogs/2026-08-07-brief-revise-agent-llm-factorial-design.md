# 2026-08-07 — brief_revise_agent LLM factorial analysis: taxonomy, design, evaluation method

Separate parallel workstream from the round B/C/D thread (see
`worklogs/2026-08-07-brief-revise-agent-rounds-BCD-conclusion.md`). Goal:
measure the effect size of structural features AND generator-LLM choice on
`brief_revise_agent` answer quality, on the same 15-topic set, budgeted at
$50.

## 1. Factor taxonomy ($0.33: gpt-5.6-luna draft, gpt-5.6-terra review)

Survey material (`worklogs/assets/2026-08-07-luna-factor-taxonomy-draft.md`
input, not committed separately -- built from every system's README, key
`agent_harness` hook docstrings, and 16 `aus_agent_v2` module docstrings:
`coverage_plan.py`, `atomic_plan.py`, `observable_scout.py`, `plan_critic.py`,
`plan_reconcile.py`, `coverage_verify.py`, `audience_verify.py`,
`finish_review.py`, `answer_blueprint.py`, `claim_finish.py`,
`coverage_contract.py`, `candidate_union.py`, `semantic_closure.py`,
`ensemble_select.py`, `search.py`, `adaptive_research.py`) fed to
gpt-5.6-luna for a draft taxonomy, then gpt-5.6-terra independently
reviewed/corrected it against the same source material (not just
rubber-stamping -- terra removed one overreaching claim, corrected several
"already tested?" citations, fixed a mechanism-type classification).
Final: `worklogs/assets/2026-08-07-terra-factor-taxonomy-final.md`.

**13 structural factors + 3 model-role factors** (each model-role factor
sharing the same 5 LLM levels: `gpt-5.6-luna`/`terra`/`sol`,
`openai.gpt-oss-120b-1:0`, `qwen.qwen3-next-80b-a3b`). Naive full factorial:
2^9 × 4 × 3^3 structural × 5^3 model-role = **6,912,000 cells** -- a scale
check, not a proposal.

**Per-system breakdown** (the taxonomy conflated "generic agent_harness
capability" with "aus_agent_v2's own architecture" in its first pass;
reorganized after a follow-up user question):

- **aus_agent_v2's own factors** (not portable without work): `coverage_plan`
  (free-form prose plan with a word-budget-per-section, verified default ON),
  `atomic_plan`/`observable_scout` (the atomic obligation scout, verified
  default ON), `plan_critic`/`plan_reconcile`/`coverage_verify`/
  `audience_verify`/`finish_review`/`answer_blueprint` (all off by default,
  experimental), `coverage_contract` (1804-line executable contract, the
  next-candidate architecture, ungraded), `candidate_union`/`ensemble_select`
  (claim-union across architectures), `semantic_closure_verify`
  (post-handoff verifier), `search_k=20`, and adjacent-page auto-fetch
  (already ported into `brief_revise_agent` as "round B").
- **`brief_revise_agent`'s own factors**: requirements_brief, brief_schema
  (v1/v2), brief_word_budget, review_revise_pass, adjacent_page_augmentation,
  the reverted requirement-labelled retrieval screener.
- **Generic `agent_harness` factors, unused by EITHER system**:
  retrieval_engine_set, `search_result_filter`, `search_preview_policy`,
  `stage_search_results`, `judge_relevance_tool`, `commit_release` -- all
  built for `facets_agent`, available but untried here.

## 2. $50 design ($0.17: gpt-5.6-sol)

Full raw response: `worklogs/assets/2026-08-07-sol-factorial-design.md`.

**Block 0** (free): reuse all 5 existing `brief_revise_agent` Luna cells
(iter1/iter2/iter3/roundB/roundC) -- see the BCD-conclusion worklog for
their results.

**Block 1** ($34-43 of $50): vary ONLY the main research/writer model
(`gpt-5.6-terra`, `gpt-5.6-sol`, `openai.gpt-oss-120b-1:0`,
`qwen.qwen3-next-80b-a3b`), holding the brief analyst and reviewer fixed on
`gpt-5.6-luna` and every structural setting at the iteration-1 canonical
config. User's explicit priority: "the LLM probably matters a lot" -- all 4
new cells go to the model question, 0 to new structural variants, 0 to
interactions (deliberate, per sol: "the current evidence has five Luna
structural runs but no non-Luna run at all").

**Mandatory cost gate** (GPT-OSS/Qwen pricing is unmeasured in this repo):
run each Bedrock batch's first topic, check real metering, project the
full-15 cost with a 25% contingency, proceed only if projected total stays
under $47 (retaining $3 emergency headroom).

**Extension blocks 2-6** (ordered, cumulative, no cell ever replaced):
Block 2 = adjacent-pages × model interaction (4 cells), Block 3 = brief-
analyst model sweep (4 cells), Block 4 = reviewer model sweep (4 cells),
Block 5 = replication of the 5 baseline model cells (stochasticity check),
Block 6 = word-budget × model interaction (4 cells, though round C's own
result -- see BCD worklog -- makes this low-priority now).

**Analysis method**: NOT arena-style. A hierarchical cumulative-link
(ordinal) mixed-effects model on raw per-criterion 0-3 grades, topic random
intercept, cell/answer random intercept (grades from one judge call are
correlated), omnibus test per factor + 4 preplanned Holm-corrected
contrasts (each non-Luna model vs Luna), FDR-corrected criterion-level
secondary analysis. If arena is used at all, retain BOTH battle orders as
raw ordered observations (not just the clean win/loss summary), with an
explicit position-bias diagnostic -- this repo's own prior work already
found real judge order-bias (order_consistency as low as 0.533 in one
15-topic run).

## 3. Evaluation method: standalone rubric grading, not arena ($0.08: gpt-5.6-sol)

User question: arena (pairwise vs `aus_agent_v2`) or standalone (score each
cell independently)? Orchestrator found this repo already has a standalone
grader: `score_one()` in
`tasks/task-comparison/scripts/rubric_scorecard_aus_agent_vs_facets_agent.py`
-- one judge call per (system, topic) grades ALL ~31 official rubric
criteria (0-2) plus a holistic `overall` (0-3), no opponent needed. Full
sol response: `worklogs/assets/2026-08-07-sol-eval-method.md`.

**Decision: standalone grading becomes PRIMARY** (halves judge calls per
cell: 15 vs arena's 30; ordinal 0-3 grades are the right data shape for the
planned mixed-effects analysis; no position-bias confound). **Arena is
demoted to a confirmatory check on the top 1-2 cells only**, plus a
same-topic standalone calibration run of `aus_agent_v2` itself (15 extra
calls, cheap) so cells are comparable to a real baseline number, not just
to each other. Sol's explicit caution: bank the judging-cost savings as
safety margin against the still-unmeasured Bedrock generation cost FIRST;
only spend it on additional cells once real GPT-OSS/Qwen pricing is known.

New script (adapts `score_one` directly, does not reimplement it):
`tasks/task-comparison/scripts/standalone_rubric_score.py`. Validated
against the existing `brief-revise-iter1-exp15` artifacts: **overall mean
2.07/3**, weakest axis `References & Citation Quality` (mean 0.00/2, n=9)
-- this becomes the Luna reference point for Block 1's comparisons.

## 4. Execution status

- **Terra and Sol main-model batches**: launched
  (`br-model-main-terra-exp15-b1`, `br-model-main-sol-exp15-b1`), running in
  background, OpenAI backend, no region/credential issues.
- **GPT-OSS and Qwen batches**: BLOCKED. First attempt hit
  `ExpiredTokenException` -- the AWS Bedrock session token on this machine
  is expired. `aws` CLI is not installed in this sandbox to self-refresh;
  this repo's own history (`worklogs/2026-08-05-facet-rag-improved-3topics-and-hyde.md`)
  documents `aws sso login` as the standard fix, which needs the user.
  Waiting on a fresh token before starting either Bedrock batch's mandatory
  first-topic cost-gate probe.
- New `agent.py` params landed to support Block 1: `brief_backend`/
  `brief_model`/`brief_region`, `review_backend`/`review_model`/
  `review_region`, decoupling the brief-analyst and reviewer providers from
  the main run's `backend`/`model` (previously coupled to the same factory
  call). `run.py` gained matching CLI flags.

## Not done yet

- GPT-OSS/Qwen generation (blocked on credentials).
- Standalone scoring of the 4 new Block 1 cells (terra/sol batches not yet
  complete) and the `aus_agent_v2` calibration run.
- The actual mixed-effects model fit -- needs Block 1's data in hand first.
- Arena confirmation of the eventual best cell(s).
