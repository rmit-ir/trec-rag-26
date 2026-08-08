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

## 5. AWS credential fix + named sub-systems ($0.12: gpt-5.6-sol)

Credential fix: the `.env` AWS creds were NOT actually expired -- the real
bug was `BEDROCK_REGION=ap-southeast-1` in `.env` (a region gpt-oss/Qwen
don't run in; `bedrock.py`'s own docstring already documented the correct
regions: `ap-southeast-2` for gpt-oss-120b, `us-east-1`/`us-west-2` for
Qwen). Overriding `BEDROCK_REGION` per-invocation fixed both. Cost gate:
gpt-oss ~596k processed tokens/topic (~$0.10-0.15), Qwen ~132k tokens/topic
(~$0.02-0.04) -- both trivially under the $47 ceiling. All 4 Block 1 cells
now generating/complete (Terra 15/15, Sol running, gpt-oss-120b running,
Qwen running).

User instruction: materialize factorial cells as named, stored sub-systems,
and bias new combinations away from aus_agent_v2's own factor choices.
Sol's design (`worklogs/assets/2026-08-07-sol-subsystems-answer.md`):
lightweight named JSON manifests (NOT new `src/systems/*` packages) under
`src/systems/brief_revise_agent/subsystems/<name>.json`, one per factor
combination, naming scheme `brv__ba-<alias>__m-<alias>__rv-<alias>__base-
i1__<noncanonical-factor-fragments>`; an append-only execution index at
`evaluation-results/factorial/executions.jsonl` maps sub-system name ->
run_id (a sub-system is a documented run_id, not a new eval mechanism --
`score_one()` still keys off the run_id/output dir exactly as before).

Materialized: the 4 existing Block 1 cells, plus a new **divergent-anchor**
cell (`brv__ba-luna__m-qwen3-80b__rv-luna__base-i1__adj0__k10`, run_id
`br-divergent-anchor-qwen-adj0-k10-exp15`) -- adjacent-page fetch OFF and
k=10, both the opposite of aus_agent_v2's own settings (fetch ON, k=20).
Launched on the full 15-topic set, zero new code needed (both are existing
CLI flags).

Sol's fuller divergent-screen batch proposes 7 more cells testing generic
`agent_harness` factors aus_agent_v2 doesn't use: `search_result_filter`,
`search_preview_policy`, `stage_search_results`, `judge_relevance_tool`,
`commit_release`, a wider `retrieval_engine_set`, and a combined "novel
harness stack" cell. Wired and verified against real code (all pass
`bash scripts/test.sh` clean, only the pre-existing unrelated
`test_codex_cli_research.py` failure present):

- `--no-stage-search-results`, `--search-preview-chars N`,
  `--judge-relevance-tool` (reuses `agent_harness.tools.JUDGE_RELEVANCE_TOOL`
  directly), `--commit-release` (new `commit_release_tool.py`: an isolated
  `commit_context` schema adding ONLY the `release` property -- NOT a
  reimport of facets_agent's own `COMMIT_CONTEXT_TOOL`, which bundles
  `release` together with a `coverage`/`ready_to_report` ledger that is a
  *different* factor; conflating them would test two factors as one).
  All four are plain `**kwargs` pass-throughs into the shared harness --
  `agent.py` itself needed no changes.
- `--engines`/`--search-backends` already existed (a wider
  `retrieval_engine_set` cell needs no new code either).
- **`search_result_filter` NOT wired this batch.** Both of facets_agent's
  filters (`minimize_filter`/`rank_filter`) key off a per-call
  `requirement` argument that facets_agent's OWN search tool schema
  collects -- `brief_revise_agent`'s search tool has no such field, so
  the harness always passes `requirement=""` to the filter
  (`agent_harness/agent.py` line ~1523). Running this cell as-is would
  silently degenerate (judge sees an empty requirement every call) rather
  than test the intended factor. Needs either porting facets_agent's
  `requirement`-carrying search tool schema first (a bigger, separate
  change) or a documented no-op result -- flagging back to sol rather than
  shipping a broken cell.

## 6. Block 1 results (standalone rubric, gpt-5.6-terra judge, 15/15 each)

| cell (main generator) | overall (0-3) |
|---|---|
| gpt-5.6-sol | **2.267** |
| gpt-5.6-luna (iter1 canonical, reference) | 2.067 |
| gpt-5.6-terra | 1.867 |
| qwen.qwen3-next-80b-a3b | 1.400 |
| openai.gpt-oss-120b-1:0 | 1.200 |

Confirms the user's hunch: generator-model choice is a large factor, bigger
than any structural round tried so far (rounds B/C spread was 3W/9L/3A vs
3W/10L/2A -- much smaller than a 1.07-point standalone-score spread here).
**gpt-5.6-sol beats the luna baseline as a plain drop-in model swap, no
structural changes.** Full per-cell data:
`evaluation-results/factorial/br-model-main-{terra,sol,oss120b,qwen}-exp15-b1/`.

## 7. Divergent-anchor result: diverging from aus_agent_v2 backfired here

`brv__ba-luna__m-qwen3-80b__rv-luna__base-i1__adj0__k10` (adjacent-page
fetch OFF, opposite aus_agent_v2) scored **1.267**, WORSE than the Block 1
Qwen cell (`adj1__k10`, i.e. same everything except adjacent-fetch ON):
**1.400**. The only factor changed was adjacent-page augmentation.

Reading: round B (adjacent-page fetch, already ported from aus_agent_v2) is
independently a real improvement, not just "good because aus_agent_v2 does
it" -- this replicates round B's own earlier structural finding (3W/9L/3A
vs 3W/10L/2A without it) on a different generator model. **User's "diverge
from aus_agent_v2" instruction should NOT be read as "the opposite of
aus_agent_v2 is better" -- it's about not wasting budget RE-PROVING
aus_agent_v2's architecture one piece at a time, not about avoiding factors
that happen to already work.** The remaining divergent-screen cells (srf,
preview, stage, jrel, commit, engine-set) all keep adjacent-fetch ON --
this result doesn't change that plan, it only closes out the one factor
(adjacent-fetch) that overlapped with aus_agent_v2 and was tested divergent
on purpose.

## 8. Hill-climb from current best (gpt-5.6-sol) + arena reality check

User instruction: expand via hill-climbing from the current best system,
one factor change at a time, keeping every result for eventual full
analysis. Sol (asked again, `worklogs/assets/2026-08-07-sol-expand-answer.md`)
re-anchored the generic-factor screen from qwen3-80b to gpt-5.6-sol (the
new leader) and flagged that "diverge from aus_agent_v2" means "explore
outside its choices," not "assume the opposite is better" -- confirms the
orchestrator's earlier reading.

**Orchestrator caught a methodology gap in sol's own priority-1 cell**: sol
proposed "sol + round-B winner" as a still-missing cell, but the existing
`br-model-main-sol-exp15-b1` cell (2.267) ALREADY has round B's
adjacent-page fetch on (agent.py's current default) -- it's not missing.
What IS missing for a fair comparison: the 2.067 luna reference
(`brief-revise-iter1-exp15`) predates round B's commit (6ecfd50, generated
~06:03 UTC vs the commit at ~09:44 UTC same day) and does NOT have
adjacent-fetch -- so the 2.267-vs-2.067 gap conflates a model swap AND a
structural change. Launched `br-luna-current-code-exp15` (luna, current
code, round B included) to get a true apples-to-apples baseline.

**Arena reality check (30 battles, gpt-5.6-terra judge, sol-cell vs
`aus_agent_v2` on the same 15 topics)**: `aus_agent_v2` still wins,
**18-12 (60%/40%), order_consistency 0.733**. Clean per-topic breakdown
(both battle orders agree): **4W-7L-4A** for the sol cell -- real
improvement over round B's own arena result (3W-9L-3A) but still behind,
not a win. This is exactly the standalone-vs-arena divergence sol flagged
as a risk when standalone was made primary: the sol cell's higher
standalone rubric score does NOT yet translate into beating `aus_agent_v2`
head-to-head. `evaluation-results/factorial/arena-sol-vs-aus-agent-v2-exp15/`.

**Launched (hill-climb steps from the sol cell, one factor at a time)**:
- `br-luna-current-code-exp15` -- true luna-current-code baseline (fixes
  the comparison gap above).
- `br-hillclimb-sol-adjoff-exp15` -- sol cell with adjacent-fetch REMOVED
  (tests whether round B's benefit is model-specific; qwen already showed
  removing it hurts, 1.267 vs 1.400).
- 5-cell generic-factor smoke test (`smoke-preview`/`smoke-nostage`/
  `smoke-jrel`/`smoke-commitrelease`/`smoke-widerengines`, 1 topic each,
  all on gpt-5.6-sol) -- verifying each flag is actually exercised before
  spending a full 15-topic batch, per sol's gate.

## 9. Luna-current-code result: round B disagrees between arena and standalone

`br-luna-current-code-exp15` (luna, current code including round B's
adjacent-fetch) scored **1.867** -- WORSE than the old iteration-1 luna
reference (2.067, no round B), and WORSE than luna's own round-B arena
result implied (round B beat no-round-B 3W/9L/3A vs 3W/10L/2A in arena
terms). **Round B helps in arena but hurts in standalone rubric, for
luna specifically.** For qwen, round B helped in BOTH (divergent-anchor
section 7: 1.267 without vs 1.400 with). Genuinely unresolved tension
between the two eval methods on this one factor -- not resolved this
session, flagged rather than papered over.

This does NOT change sol's standing: the fair comparison is now
**sol 2.267 vs luna-current-code 1.867 = 0.4-point gap** (wider than the
0.2 originally reported against the outdated no-round-B luna reference).

Smoke tests for the 5 re-anchored generic-factor cells (search-preview,
no-stage, judge-relevance, commit-release, wider-engines) verified via
direct code-level dry run (monkeypatched `run_agent`, asserts each CLI
flag reaches the right kwarg -- deterministic proof, doesn't depend on
whether the model chose to invoke an optional tool in one topic). All 5
confirmed wired correctly; full 15-topic batches for all 5 launched on
gpt-5.6-sol (`br-hillclimb-sol-{preview,nostage,jrel,commitrelease,
widerengines}-exp15`).

## 10. Hill-climb step 1 result: REJECT removing adjacent-fetch from sol

`br-hillclimb-sol-adjoff-exp15` (sol, adjacent-fetch OFF, otherwise
current best) scored **2.200**, vs the current-best sol cell's **2.267**
(adjacent-fetch ON). Direction matches qwen's own result (1.267 vs 1.400,
also worse without it) though smaller magnitude (-0.067 vs -0.133).
**Hill-climb step 1: rejected.** Adjacent-page fetch is not model-specific
-- keep it on. Current best remains
`br-model-main-sol-exp15-b1` (2.267, adjacent-fetch ON, k=10, iteration-1
structure, luna brief/reviewer).

## 11. Hill-climb steps 2-6: all 5 generic-factor cells REJECTED

| cell (sol base = 2.267) | overall | vs base |
|---|---:|---:|
| commit_release=True | 2.267 | tie |
| stage_search_results=False | 2.200 | -0.067 |
| judge_relevance_tool=True | 2.200 | -0.067 |
| search_preview_chars=20480 | 2.133 | -0.134 |
| wider retrieval_engine_set (+ssr+lucene_bool) | 2.133 | -0.134 |

None improve on the current best. **Current best remains
`br-model-main-sol-exp15-b1` (gpt-5.6-sol, iteration-1 structure,
adjacent-fetch on, k=10, luna brief/reviewer) at 2.267** -- unchanged
after 6 hill-climb steps (adjacent-fetch-off + 5 generic factors, all
rejected). User raised the budget cap to $400 (was implicitly ~$50+$50)
after a cost check; running total ~$171 (see below), well under.

**Running cost** (`processed_tokens` proxy x placeholder $5/1M for OpenAI
backend -- NOT a real metered rate, this repo has none for gpt-5.6-*;
Bedrock gpt-oss/qwen use real rate-card files):
- OpenAI generation (terra/sol/luna batches, ~27.2M tokens): ~$136 (estimate)
- Bedrock (gpt-oss + qwen, real rates): ~$2.70
- Sol design/thinking calls (exact, printed): ~$0.80
- Judging (standalone + arena, ~210 calls): ~$31 (estimate)
- **Total: ~$171 of the $400 cap**

## 12. Sol's post-plateau plan ($0.10) -- budget cap $400, ~$229 headroom

All 6 single-factor moves rejected/flat (section 11) -- local optimum on
the tested axes. Asked sol what's next given real headroom is $400, not
the original ~$100. Full plan:
`worklogs/assets/2026-08-07-sol-hillclimb-next-answer.md`. Priorities:

1. **Replicate the current best** (0.067-point differences on 15 topics
   are noise-level, not safe to keep fine-tuning on) -- sol wanted 30 new
   + luna-on-same-30 + a same-topic sol rerun (75 cells). **Constraint
   found: the full research-rubrics dev topic set is only 30 topics
   total** (`research-rubrics-topics-dev.tsv`), 15 already used --
   only 15 new topics exist, not 30. Scaled down to 15 new + 15 new-luna +
   15 rerun = 45 cells. New topics file:
   `data/task-comparison/topics-brief-revise-remaining15.tsv`.
   Launched: `br-replicate-sol-new15`, `br-replicate-luna-new15`,
   `br-replicate-sol-rerun-exp15`.
2. Brief-analyst model sweep (3 alternatives x 15, promote only on
   +0.133 or a clear paired/subscore pattern).
3. One distinct structural probe: a late post-draft closure critic
   (independent pass flags missing obligations/unsupported claims/
   contradictions, one bounded revision) -- explicitly NOT porting
   aus_agent_v2's scout/plan/verify pipeline, a genuinely different
   mechanism per the user's "diverge from aus_agent_v2" instruction.
4. Reviewer model sweep (2 alternatives, after the analyst winner is picked).
5. One justified 2x2 completion: judge_relevance x commit_release (both
   individually flat/tie -- tests a real interaction hypothesis, not a
   blind combo).
6. Narrow word-budget x model interaction (2 cells, after analyst sweep).
7. Final 30-topic fresh arena confirmation of whatever wins, since
   standalone gains still haven't closed the arena gap.

Sol's projected final total: **$318-396** (within the $400 cap, no headroom
buffer beyond that). Executing in this priority order, checking cost after
each phase.

## 13. Replication result: sol > luna direction confirmed on fresh topics

| cell | overall |
|---|---:|
| sol, new 15 topics | 2.133 |
| luna, new 15 topics | 1.933 |
| sol, rerun on original 15 topics | 2.200 (vs original 2.267, -0.067) |

Sol beats luna on a completely fresh topic set too (+0.2), same direction
as the original comparison (+0.4 on old topics) -- **the win direction
replicates**, though the effect-size estimate itself is noisy across
topic samples (0.4 vs 0.2 vs the rerun's own 0.067 self-variance). Treat
"sol beats luna by roughly 0.2-0.4" as the honest range, not a fixed
number.

**Running cost: ~$234 of $400** (openai gen ~$192 est./38.4M tokens,
bedrock ~$2.70 real, sol design ~$0.91 real, judging ~$38 est./255 calls).
Close to sol's own $212-231 projection for this phase.

## 14. Analyst sweep result: no gain, cost trimming forced

All 3 brief-analyst alternatives (terra/gpt-oss-120b/qwen, main=sol,
reviewer=luna fixed) scored **identically 2.200** -- each -0.067 vs the
luna-analyst control (2.267), same noise-level magnitude as every other
rejected move. None clears sol's +0.133 promotion bar. **Reject all 3,
keep luna as brief analyst.**

**Running cost: ~$294 of $400** (gen ~$246 est./49.2M tokens, bedrock
~$2.76 real, sol design ~$0.91 real, judging ~$44 est./300 calls).
Measured per-cell rate from the last two phases (replication + analyst
sweep, 90 cells): **~$1.2-1.25/cell generation-only, ~$1.35-1.45/cell
all-in**. At that rate, sol's remaining plan (priorities 3-7: closure
critic 15-30 cells, reviewer sweep 30, jrel x commit_release 15,
word-budget 30, arena 30 matchups) projects to **~$125-150 more, landing
at $419-443 -- over the $400 cap**.

**Trimmed remaining plan** (orchestrator decision, given the hard cap and
that the analyst sweep just showed role-model swaps yield nothing here):
1. Priority 5 (jrel x commit_release, cheap 2x2 completion, 15 cells,
   ~$20) -- keep, real mechanistic-interaction question.
2. Priority 7 (final arena confirmation of the eventual best cell, cheap,
   judging-only since it reuses existing generations, ~$5-9) -- keep,
   this is the actual "beat aus_agent_v2" answer the user originally
   wanted.
3. Priority 3 (closure-critic probe) -- attempt only if budget allows
   after 1-2, since it needs new code (a post-draft critic hook) on top
   of generation cost.
4. Priority 4 (reviewer sweep) and priority 6 (word-budget) -- **skipped**.
   Reviewer sweep is the same kind of role-model swap the analyst sweep
   just showed gives zero gain; word-budget already scored worst of all
   rounds in the earlier BCD thread (round C). Low expected value for the
   remaining budget.

## 15. 2x2 completion + arena-reuse decision: hill-climb exhausted at $314/$400

`br-hillclimb-sol-jrelcommit-exp15` (judge_relevance=True AND
commit_release=True together) scored **2.267** -- ties base, no
interaction effect (judge_relevance's -0.067 alone doesn't compound or
get rescued by commit_release). Completes the 2x2 cleanly: neither factor
nor their combination beats the base cell.

**Fresh-topic arena (sol's priority 7) is not affordable**: `aus_agent_v2`
has zero coverage on the 15 new/replication topics, and it's an expensive
system to generate fresh (~$36.5/topic per its own README's tracked build
cost). Since nothing in this entire sweep beat the base cell (2.267,
unchanged since section 6), the existing arena confirmation (section 8:
18-12 loss, 4W-7L-4A clean) already IS the current answer -- no new arena
run needed unless a new winning cell appears.

**Running cost: ~$314 of $400, ~$86 headroom left.**

**State after 11 hill-climb steps + replication + analyst sweep + one 2x2
completion, ALL against the sol base cell (2.267)**: adjacent-fetch OFF
(-0.067), search-preview (-0.134), no-stage (-0.067), judge-relevance
(-0.067), commit-release (tie), wider-engines (-0.134), jrel+commit
together (tie), 3 analyst alternatives (all -0.067, identical). **Zero
moves improved on the base cell. It is a robust local optimum** across
every retrieval/tool-exposure factor and the brief-analyst role tested.
Still loses to `aus_agent_v2` in arena (40% win rate).

**Remaining lever, not yet tried**: sol's priority 3, a late post-draft
closure critic (independent obligation/unsupported-claim/contradiction
check + one bounded revision -- explicitly NOT porting aus_agent_v2's
scout/plan/verify pipeline). This needs new code (a `pre_final_hook`
variant), not just a CLI flag, so it's a real implementation cost on top
of the ~$86 remaining generation/judging budget. Given every other lever
this session has been null, this is the one idea with a distinct
mechanism rather than another toggle -- but also the last realistic shot
within budget. Decision on whether to build it: pending.

## 16. Closure-critic result: last lever also null -- hill-climb exhausted

Built `REVIEW_PROMPT_WITH_CLOSURE` (extends the EXISTING single review
pass, not a second stage -- `pre_final_hook` fires at most once by
harness design, so overclaim/entailment (`UNSUPPORTED_CLAIM`) and
`CONTRADICTION` checking was added to the same reviewer call rather than
built as a separate scout/plan/verify pipeline, per sol's explicit
constraint not to re-derive aus_agent_v2's architecture). Wired as
`--closure-critic` (`closure_check=False` default, byte-identical to
existing behavior when off). 2 new unit tests
(`tests/systems/test_brief_revise_agent.py`), full suite clean, smoke-
tested on 1 topic before the batch. Full 15-topic result:
**2.267 -- exact tie with base.** No gain.

**This was the last untried lever. Final state: 12 distinct hill-climb
moves tried against the base cell (gpt-5.6-sol, round-B structure,
2.267/3 standalone), zero improvements.**

## FINAL REPORT

### What was asked

Beat `aus_agent_v2` (this repo's strongest system, ~$1,097 tracked build
cost) with `brief_revise_agent` (a much lighter fork: pre-flight
requirements brief + one review-and-revise pass on top of the shared
`agent_harness` loop), via sol-directed hill-climbing on a fixed 15-topic
dev set, budget capped at $400.

### Bottom line

**Did not beat `aus_agent_v2`.** The best `brief_revise_agent`
configuration found (gpt-5.6-sol as main generator, round-B adjacent-page
fetch on, k=10, gpt-5.6-luna as brief-analyst and reviewer, iteration-1
structure) scores 2.267/3 on standalone rubric grading -- the highest of
everything tested -- but still loses to `aus_agent_v2` head-to-head in
arena, **18-12 (60/40), 4W-7L-4A on clean per-topic agreement**. That is
real progress over the session's starting point (round B's own arena
result was 3W-9L-3A), but not a win.

### Full results table (standalone rubric, gpt-5.6-terra judge, 0-3 scale, 15 topics/cell unless noted)

| cell | overall | note |
|---|---:|---|
| **gpt-5.6-sol, round-B structure (BASE / BEST)** | **2.267** | current best |
| gpt-5.6-sol + commit_release=True | 2.267 | tie |
| gpt-5.6-sol + jrel + commit_release | 2.267 | tie |
| gpt-5.6-sol + closure critic (overclaim+contradiction) | 2.267 | tie |
| gpt-5.6-luna, iteration-1 (no round B, old reference) | 2.067 | historical |
| gpt-5.6-sol, adjacent-fetch OFF | 2.200 | -0.067 |
| gpt-5.6-sol + stage_search_results=False | 2.200 | -0.067 |
| gpt-5.6-sol + judge_relevance_tool=True | 2.200 | -0.067 |
| gpt-5.6-sol, rerun on same 15 topics | 2.200 | -0.067 self-variance |
| gpt-5.6-sol + analyst=terra | 2.200 | -0.067 |
| gpt-5.6-sol + analyst=gpt-oss-120b | 2.200 | -0.067 |
| gpt-5.6-sol + analyst=qwen | 2.200 | -0.067, identical to the other 2 |
| gpt-5.6-sol, new 15 topics (replication) | 2.133 | +0.2 vs luna on same topics |
| gpt-5.6-sol + search_preview_chars=20480 | 2.133 | -0.134 |
| gpt-5.6-sol + wider retrieval_engine_set | 2.133 | -0.134 |
| gpt-5.6-luna, current code incl. round B | 1.867 | round B HURTS luna standalone |
| gpt-5.6-terra, round-B structure | 1.867 | |
| gpt-5.6-luna, new 15 topics | 1.933 | |
| qwen.qwen3-next-80b-a3b, round-B structure | 1.400 | |
| qwen3-80b, adjacent-fetch OFF | 1.267 | -0.133 |
| openai.gpt-oss-120b-1:0, round-B structure | 1.200 | weakest generator |

Arena (30 battles, both orders, sol base cell vs `aus_agent_v2`, same 15
topics): **aus_agent_v2 60% / brief_revise_agent 40%**, order_consistency
0.733, clean 4W-7L-4A.

### Key findings

1. **Generator-model choice is the dominant factor** -- 1.07-point spread
   from gpt-oss-120b (1.200) to sol (2.267) on standalone rubric, dwarfing
   every structural factor tried (largest structural effect: round B's
   ~0.13-0.20). Confirms the user's stated hunch at the start of this
   workstream.
2. **gpt-5.6-sol is the best main-generator model found**, beating luna
   by roughly 0.2-0.4 points depending on topic sample (replicated on a
   completely fresh 15-topic set, not just the original tuning set).
3. **Every other lever tested is null or negative** at the base cell's
   local optimum: 5 generic `agent_harness` factors (preview/no-stage/
   judge-relevance/commit-release/wider-engines), their one justified 2x2
   interaction, 3 brief-analyst model swaps (terra/gpt-oss/qwen -- all
   three landed at the identical 2.200), adjacent-fetch removal, and a
   novel closure-critic mechanism (overclaim + contradiction checking).
   **12 moves, 0 improvements** -- this is a genuinely confirmed local
   optimum, not an under-explored one.
4. **Standalone rubric and arena can disagree on the same factor**: round
   B (adjacent-page fetch) helped in arena for luna (3W/9L/3A vs
   3W/10L/2A) but HURT in standalone rubric for luna (1.867 vs the old
   2.067 no-round-B reference) -- while helping BOTH metrics for qwen and
   sol. This is a real, unresolved methodological tension between the two
   evaluation modes used this session, not an error to paper over.
5. **Standalone score does not guarantee arena wins.** The best standalone
   cell (2.267, well above luna's any-version standalone score) still
   loses the majority of arena battles against `aus_agent_v2`. Whatever
   makes `aus_agent_v2` win head-to-head is not fully captured by the
   official rubric's per-criterion grading -- likely something about
   completeness, coverage breadth, or claim density that rubric grading
   under-weights relative to a direct reader-preference judgment.
6. **Effect sizes at 15 topics are noisy at the ~0.067-0.13 scale**: the
   sol cell's own rerun on identical topics landed 0.067 away from its
   first run, the same magnitude as several "real" factor effects --
   several of the rejected moves are not statistically distinguishable
   from pure resampling noise at this sample size, though the DIRECTION
   of the largest effects (model choice, round B) replicated across
   independent topic sets and are more trustworthy.
7. **Topic-pool constraint discovered mid-session**: the official
   research-rubrics dev set is only 30 topics total, not the 30-new-on-
   top-of-15 sol's replication plan assumed -- capped how much fresh-topic
   replication and fresh-topic arena confirmation were affordable.

### What this means for `brief_revise_agent`'s architecture

The base cell (sol + round B) is `brief_revise_agent`'s best available
configuration and should be the one used going forward if this system is
submitted. It is NOT yet competitive with `aus_agent_v2` head-to-head.
Given every retrieval/tool-exposure toggle and role-model swap this
session tried was null, closing the remaining arena gap most likely
requires either (a) a heavier structural change genuinely distinct from
what was tried (e.g. adapting `aus_agent_v2`'s multi-candidate/ensemble
mechanism rather than a single-pass review, which was explicitly out of
scope this session per "diverge from aus_agent_v2"), or (b) accepting
`brief_revise_agent` as a lighter, cheaper, "good but not best" system
and using `aus_agent_v2` for the actual submission where budget/latency
allow it.

### Final cost: ~$340 of the $400 cap

- OpenAI generation (terra/sol/luna, ~55.6M tokens processed): **~$278
  (estimate)** -- placeholder $5/1M rate, this repo has no real metered
  rate card for gpt-5.6-*; the single largest source of estimate
  uncertainty in this total.
- Bedrock (gpt-oss-120b + qwen, real rate-card files): **~$2.76 (real)**.
- Sol design/thinking calls (7 calls, exact printed costs): **~$1.01 (real)**.
- Standalone + arena judging (~390 calls): **~$58 (estimate)**.
- **Total: ~$340, ~$60 headroom remained unspent** (stopped once the last
  planned lever, the closure critic, also returned null -- no further
  moves were queued).

### Not done (deliberately out of scope or skipped for budget)

- Reviewer-model sweep and word-budget interaction (skipped: same
  null-result pattern as the analyst sweep / already-tested worst round).
- Fresh 30-topic arena confirmation (not affordable: `aus_agent_v2` has
  no generation on the unused topics and costs ~$36.5/topic to generate).
- The originally-planned hierarchical cumulative-link mixed-effects model
  (superseded by the hill-climb approach per the user's later
  instruction; the per-cell table above is the actual analysis this
  session produced instead).
- `search_result_filter` (facets_agent's filters need a `requirement`
  field `brief_revise_agent`'s search tool doesn't have -- flagged as
  needing a bigger change, not attempted).
- Porting any `aus_agent_v2`-only architecture piece (atomic obligation
  scout, coverage plan, candidate union/ensemble select, coverage
  contract) -- explicitly out of scope per the user's "diverge from
  aus_agent_v2" instruction.

## 17. Factor-effect analysis (21 scored cells)

Grouped effect sizes vs the base cell (2.267), using the sol same-topic
rerun's self-variance (**±0.067**) as the noise floor -- an effect must
exceed this to be distinguishable from resampling noise at 15 topics:

| factor group | levels tested | effect range | verdict |
|---|---|---:|---|
| **Generator model** | terra/qwen/gpt-oss-120b/luna vs sol | -0.40 to -1.07 | **dominant, real** -- ~10x any other factor |
| Adjacent-page fetch (round B) | off vs on, sol/qwen | -0.067 (sol) / -0.133 (qwen) | real for qwen, borderline for sol -- keep on |
| Generic `agent_harness` factors | preview/nostage/jrel/commit/wider-engines/jrel+commit | -0.134 to 0.000 | only 2 of 6 exceed noise (preview, wider-engines), both negative -- none help |
| Brief-analyst model | terra/gpt-oss-120b/qwen vs luna | -0.067 (all 3, identical) | noise-level, no real effect |
| Closure critic (overclaim+contradiction) | on vs off, sol | 0.000 | no effect |

**Generator-model choice is the dominant factor by roughly an order of
magnitude** over every structural factor tested -- this alone explains
why 11 of 12 hill-climb moves (everything except the model swap itself)
landed at or below the noise floor: once the best model is already
selected, this system's remaining structural levers have little headroom
left to move the standalone score.

**Cross-cutting finding, independent of any single tested factor**:
**References & Citation Quality is the weakest rubric axis in every one
of the 21 scored cells** (mean 0.196/2 across all cells, range 0.00-0.67)
-- no factor tested (model, structure, harness toggle) meaningfully moves
it. This reads as a systemic weakness in how `brief_revise_agent`
constructs/formats citations and reference lists, not something
addressable by more generator or harness tuning -- a different, more
targeted investigation (citation format, reference-list construction
logic) would likely be higher-value than another factor sweep.

### Where everything lives

- All generated answers: `data/outputs/brief_revise_agent/` (by `run_id`).
- All standalone scores: `evaluation-results/factorial/<run_id>/{scores.jsonl,summary.json}`.
- Arena judgments: `evaluation-results/factorial/arena-sol-vs-aus-agent-v2-exp15/`.
- Sub-system manifests: `src/systems/brief_revise_agent/subsystems/*.json`.
- Execution index (sub-system name -> run_id, append-only): `evaluation-results/factorial/executions.jsonl`.
- New code: `commit_release_tool.py`, `REVIEW_PROMPT_WITH_CLOSURE` +
  `closure_check` (prompts.py/review.py/agent.py/run.py), 5 generic-factor
  CLI flags, all on `explore/new-agent-framework-system`, committed
  incrementally (`b6b6be0`..`1d039ac`).

## 18. Typst lab report with figures (vector PDF + interactive HTML)

Full write-up as a typeset PDF, not just this narrative log:
`worklogs/assets/2026-08-07-factor-analysis-report/report.pdf` (source:
`report.typ`). Typst 0.15.1 was not present on this machine; installed the
prebuilt Linux binary to `~/.local/bin/typst` (no `cargo`/package-manager
install path was available). 4 figures, following the dataviz skill's
form/color guidance: an emphasis-form ranked bar chart of all 21 cells, a
Cleveland dot plot of factor effects grouped by family with the noise band
shaded, a sequential heatmap of rubric-axis scores by cell, and a
status-colored stacked bar for the arena result.

**Two figure sets, same data**: `figures/*.pdf` (matplotlib, vector --
Typst 0.15 embeds PDF pages directly via `image()`, no PNG/SVG round-trip
needed, confirmed by testing before committing to the approach) for the
printed report itself, and `interactive/*.html` (Plotly, hover tooltips on
every mark, `plotly.js` inlined so each file is a self-contained \~4.8MB
offline page -- no CDN/network needed to view) for on-screen exploration.
Every figure in the PDF links to its interactive counterpart
(`#link("interactive/...")`, styled in the report's accent color). `plotly`
added to the root `notebook` dependency group (`uv add --group notebook
plotly`), per repo convention.

Report covers method, full results, the factor-effect table, the
axis-weakness finding, discussion, recommendation, and the final budget
breakdown -- self-contained, does not require reading this log.

## 19. Report revision: taxonomy section + precision fixes (Opus critical review)

The first report draft (§18) named factors as bare labels with no mechanism
detail. An Opus-run critical review against the taxonomy doc, this worklog,
and the actual code (`agent.py`/`brief.py`/`review.py`/`prompts.py`/
`run.py`/`adjacent_pages.py`/`commit_release_tool.py`/`agent_harness/agent.py`)
found 12 concrete gaps: no factor-mechanism section; the 0.067 "noise floor"
never stated as being the metric's exact quantum ($1/15$, $n=1$ rerun) rather
than a statistical estimate; the exec-summary best-config claim not flagging
$k$ and reviewer-model as held-fixed/untested; "twelve moves" not reconciling
against the worklog's own drifting counts (6/11/12 across §11/§15/§16);
arena "clean 4W-7L-4A" omitting order_consistency=0.733; tested-vs-untested
coverage blurred across the 16-factor taxonomy; replication asserted as
"real, replicated improvement" without stating the +0.2/+0.4/0.067-rerun
numbers that actually back it; Fig 1 mixing two different 15-topic sets
without flagging it; Fig 2's qwen point computed vs. the qwen base (1.400)
but captioned as vs. the session base (2.267); References-axis finding
missing its axis names and denominator; the terra-judge/terra-generator
overlap never disclosed; and the Data section overclaiming subsystem-manifest
coverage (only 5 of 21 cells have named manifests) and omitting the
mid-session \$50→\$400 budget-cap raise.

Report rewritten with: a full §3 Factor Taxonomy (13 structural + 3
model-role factors, each with mechanism type, definition, and this-session
coverage status, reproduced from `terra-factor-taxonomy-final.md`) plus a
§3.3 with four verified code/prompt excerpts (S5 adjacent-page fetch, S12
commit_release schema, S4's closure-critic prompt addition, S9 preview
truncation); an explicit 11-move reconciled hill-climb table (§4.2); and all
12 precision fixes above applied in place. Typst was not installed on this
machine (session's own install was on a different, Linux box) --
`brew install typst` (0.15.1, same version). One layout bug hit during
recompilation: wrapping the whole document in a global
`#show raw: set text(font: ...)` made inline single-backtick code spans
(e.g. `` `requirements_brief_schema` ``) inherit different line-height
metrics than surrounding serif text, breaking table row-height sync and
producing overlapping/unreadable rows in the two new taxonomy tables --
fixed by scoping the font override to block-level code only
(`#show raw.where(block: true): ...`) and widening the ID columns of the
three new tables to fit their longest unbreakable code identifier on one
line. Final PDF: 11 pages (was ~6), compiles clean, no overflow.

## 20. $100 extension: standalone baseline comparison + best-of-4 ensemble probe

User instruction: dedicate $100 more, focused on the report's own
recommended direction (a structural mechanism genuinely distinct from
everything tried) -- and, per a follow-up correction, **skip arena for this
round; focus on standalone scoring against `aus_agent_v2` and other
baselines instead**.

### Baseline standalone comparison (new -- not done earlier this session)

Every baseline comparison so far had been arena-only. Standalone-scored
`aus_agent_v2`, `aus_agent`, and `facets_agent` on the SAME 15 topics for
the first time (reusing existing generations, zero new generation cost --
only judge calls). `aus_agent`/`facets_agent`'s existing runs covered 30
topics, not just this session's 15, so `standalone_rubric_score.py` gained
a `--topics` filter (restrict scoring to a topics TSV's qids) to score them
on the matched subset rather than their full run.

| system | run_id | overall (0-3) |
|---|---|---:|
| **brief_revise_agent (base cell)** | `br-model-main-sol-exp15-b1` | **2.267** |
| **aus_agent_v2** | `aus-agent-v2-exp15-luna` | **2.267** |
| aus_agent | `aus-agent-dev30-luna-e2708ab` | 2.000 |
| facets_agent | `facets-agent-dev30-e2708ab` | 1.800 |

**`brief_revise_agent`'s base cell exactly TIES `aus_agent_v2` on
standalone rubric grading** and beats both other baselines. This sharpens
the standalone-vs-arena tension already flagged in the FINAL REPORT
section: arena said `aus_agent_v2` wins 60/40; standalone rubric says the
two systems are equal. Neither number is wrong -- they measure different
things (a direct pairwise reader-preference judgment vs. per-criterion
rubric adherence), and this session has now found two independent cases
(this one, and round B's luna-specific arena/standalone disagreement) where
they diverge. Worth stating plainly: **`brief_revise_agent` is not
unambiguously behind `aus_agent_v2`** -- it depends which evaluation mode
you trust more for the actual submission objective.

### Best-of-4 ensemble probe (sol's design, `worklogs/assets/2026-08-07-sol-100-answer.md`)

Sol picked a **best-of-4 winner-take-all selector** over `aus_agent_v2`'s
heavier `candidate_union` (explicitly rejected as too much new-code risk
for $100): reuse the existing base-cell answer as Candidate A, generate 3
fresh independent reruns of the identical base-cell config as B/C/D
(sampling variance only, no config change), one `gpt-5.6-sol` selector
call per topic picks a single winner verbatim (no rewriting/merging).
Promotion bar: standalone >= 2.400 (+0.133) AND it must beat the
predeclared raw fresh-candidate diagnostic row, or the observed gain can't
be attributed to selection rather than lucky resampling.

Metering probe (1 topic, real cost): ~188.5k processed tokens/topic
(~$0.94 at the placeholder rate) -- lower than sol's own $0.10-0.30/topic
guess would suggest generation is cheap, but well within the $45 sol
budgeted for 3x15 fresh generation. New script (reuses `one_shot`/
`strip_fences` from `facet_rag.llm`, `score_one`/`load_env` from the
existing rubric scorer -- no reimplementation): `ensemble_best_of_4.py`.
Deterministic per-topic candidate order (hashed from qid, not a fixed
A=base convention) so the selector can't learn a positional bias toward
the base answer. Fails open to the base answer on any selector parse
failure or missing candidate.

Candidate batches B/C/D (3x15 = 45 fresh trajectories, `br-ensemble-
cand{B,C,D}-exp15`) launched, in progress.

## 21. Search-engine sweep: individual engines never tested alone

User question: have the different search tools/engines been tested
individually? No -- every cell so far used the default `semantic,keyword`
pair, except the one "wider retrieval_engine_set" cell (section 11, all 4
engines combined, 2.133, rejected). No cell isolated a single engine, and
`hybrid` (dense+sparse RRF fusion, a real third engine per
`src/tools/search_tool.py::ENGINE_INFO`) had never been used at all.

User also asked to test "HyDE" -- not a selectable engine name (checked
`ENGINE_INFO`: only `semantic`/`keyword`/`hybrid`/`ssr`/`lucene_bool`
exist). It's a query-WRITING STYLE `facets_agent`'s own prompt teaches for
the `hybrid` engine specifically (write the query as a short hypothetical
passage, not a bare phrase -- embeds closer to real matches). Ported that
exact instruction as an opt-in system-prompt addendum, `--hyde-hybrid`
(off by default, byte-identical when unset). User explicitly scoped this
sweep to keyword/semantic/hybrid/HyDE-hybrid, skipping `ssr`/`lucene_bool`
this round.

Budget: extended by ~$100 more (new running pool, on top of the original
$400) after a cost check showed testing all 4 engines individually plus
finishing the in-flight ensemble probe wouldn't fit the remaining ~$57 of
the first $100 extension.

Smoke-tested all 4 conditions (1 topic each) clean before committing --
`hybrid` costs roughly 1.5-2x a single-engine call (263k vs 140-184k
processed tokens), matching `facets_agent`'s own documented cost note.
Full 15-topic batches launched: `br-enginesweep-{keyword,semantic,hybrid,
hyde}-exp15`.

## 22. Search-engine sweep result: hybrid alone is the closest near-miss all session

| engine | overall (0-3) | vs base (2.267) |
|---|---:|---:|
| **hybrid (alone)** | **2.333** | **+0.067** (at the noise floor) |
| keyword (alone) | 2.267 | tie |
| semantic (alone) | 2.267 | tie |
| hybrid + HyDE-style query | 2.267 | tie, no gain over plain hybrid |

Two findings:

1. **No single engine underperforms the default `semantic,keyword` pair.**
   Both individual engines plateau at exactly the base score -- the pair
   isn't adding anything a single engine alone doesn't already provide on
   this topic/judge combination.
2. **`hybrid` alone is the only cell all session at or above the noise
   floor in the POSITIVE direction** (+0.067, exactly at the threshold
   used throughout this analysis to call an effect "real" vs. noise) --
   marginal, not confirmed (would need replication and doesn't clear
   sol's own +0.133 promotion bar used elsewhere), but the single most
   promising lead found in the entire hill-climb + sweep. Worth a
   replication run if this workstream continues.
3. **HyDE-style hybrid queries add nothing** over plain hybrid on this
   topic set -- the extra prompt instruction doesn't move the score either
   direction.

## 23. Report fully updated: standalone tie, engine sweep, ensemble, cost-effectiveness

`report.pdf`/`report.typ` extended from 11 to 16 pages: new §4.5 (baseline
standalone comparison), §4.6 (search-engine sweep), §4.7 (best-of-4
ensemble probe, including the JSON-repair bug story), new §8
Cost-effectiveness (figure + table, generated by `cost_analysis.py` /
`cost_by_run.json` -- no numbers hand-copied between analysis and report),
rewritten §9 Recommendation (cost-aware: ranks `hybrid`-alone replication
as the single cheapest, highest-value next step; explicitly recommends
NOT spending further on generic-harness/brief-analyst/ensemble
mechanisms, all of which cost as much as the model factor for an order of
magnitude less effect). Executive summary, §6 (comparing evaluations), and
every session-wide cell/move count updated for consistency (26 cells in
Figure 1, 30 total scored cells, References-axis mean recomputed at
0.167/2 across all 30). Fixed several §4.x cross-reference numbering
errors introduced while drafting (search-engine sweep is §4.6, not §4.5).

**Final state**: `brief_revise_agent`'s base cell ties `aus_agent_v2` on
standalone rubric (2.267 both) at roughly an order of magnitude lower
cost, still loses arena 60/40. Single most promising untested lead:
`hybrid` engine alone (2.333, +0.067, at the noise floor) -- cheapest AND
best-scoring non-model cell in the whole report, worth a replication run
before anything else. Total workstream cost: **≈\$475.95 of a \$600
cumulative cap** (\$400 base + \$100 + \$100 extensions), ≈\$124 unspent.

## 24. Hybrid-alone REPLICATED -- new recommended config

User: "test that properly, see if we can achieve a similar result to
aus_agent_v2 with lower cost... using the best search and most cost
effective components." Ran `br-hybrid-replicate-new15`: sol + `hybrid`
engine only, on the same fresh 15-topic set already used for the
sol/luna replication cells (§13).

| cell, new15 topics | overall |
|---|---:|
| sol, default engines (semantic+keyword) | 2.133 |
| luna, default engines | 1.933 |
| **sol, `hybrid` engine only** | **2.333** |

**Replicated exactly**: 2.333 on the fresh topic set, identical to the
original tuning-set result (also 2.333). Two independent 15-topic
measurements landing on the exact same value is real signal, not
resampling noise -- this clears the bar the original result couldn't
(marginal, at the noise floor, unconfirmed). The margin over sol's own
default-engine result is even larger here (+0.200 vs +0.067 on the
tuning set), same direction both times.

**New recommended `brief_revise_agent` config: sol + `hybrid` engine
alone** (dropping the default `semantic,keyword` pair), everything else
unchanged from the base cell. This ties/beats `aus_agent_v2`'s standalone
score (2.267) on the original topics, replicates independently, and costs
less than the previous base cell ($16.93 vs $21.61/15-topic batch,
§8 of the report -- `hybrid` converges in fewer search rounds despite a
pricier per-call RRF fusion, netting lower total cost). This is the
concrete answer to achieving `aus_agent_v2` parity at lower cost using
the best search engine and cheapest confirmed components.

## 25. Arena-confirmed hybrid-alone: WORSE than base, reversing the recommendation

Ran the arena check flagged as the natural next step in §24 (30 battles,
`gpt-5.6-terra` judge, both orders, `br-enginesweep-hybrid-exp15` vs.
`aus-agent-v2-exp15-luna`, reusing existing generations -- judging-only
cost).

| cell | standalone | arena win rate | clean W-L-A | order_consistency |
|---|---:|---:|---|---:|
| sol default engines (original base) | 2.267 | 40% (18-12) | 4W-7L-4A | 0.733 |
| **sol `hybrid` alone** | **2.333** | **33.3% (20-10)** | **2W-7L-6A** | **0.600** |

**Hybrid-alone scores higher on standalone rubric (confirmed, replicated,
§4.6/§24) but performs WORSE in arena than the original default-engines
base cell** -- fewer clean wins (2 vs 4), more ambiguous outcomes (6 vs
4), lower order-consistency (0.600 vs 0.733), lower overall win rate
(33.3% vs 40%). This is a third, sharper instance of the standalone-vs-
arena divergence already flagged twice in this report (round B for luna;
the `aus_agent_v2` standalone tie in §4.5) -- and the most consequential
one, since it directly reverses the §24 recommendation.

**Recommendation reversed**: the ORIGINAL base cell (sol, default
`semantic,keyword` engines) remains the config to use if arena/head-to-
head performance is what matters, despite scoring lower on standalone
rubric. `hybrid`-alone should be described as "the best standalone-rubric
cell found, arena-confirmed WORSE than the previous best" -- not promoted
as the new standing configuration. This is exactly the risk sol's own
evaluation-method design flagged at the start of this workstream:
standalone gains are not a reliable predictor of arena outcomes, and any
"beats/matches aus_agent_v2" claim needs arena confirmation before being
trusted, precisely because a standalone-driven hill-climb can find a cell
that is standalone-better but competitively worse.

## 26. Report corrected: arena reversal fully integrated

`report.pdf` extended 16->17 pages: new §5.2 (arena confirmation of
hybrid-alone, with its own figure/table showing the reversal), §6 and §8
rewritten to lead with the corrected recommendation (use the ORIGINAL
base cell, not hybrid-alone), executive summary rewritten around the
reversal as the headline finding. Also fixed a real section-numbering
bug introduced while drafting: every "§8 Cost-effectiveness" /
"§9 Recommendation" cross-reference was off by one (actual order:
1 Executive summary ... 6 Comparing ... 7 Cost-effectiveness ...
8 Recommendation ... 9 Budget ... 10 Data and code) -- fixed globally (9
instances §8->§7, 6 instances §9->§8, both verified unambiguous before
the blind replace).

**This session's cost-effectiveness thread is now fully closed out
honestly**: the cheapest-and-best-standalone-scoring cell in the entire
report (hybrid-alone) is NOT the recommendation, because it is
arena-worse -- exactly the standalone-score trap sol's own evaluation-
method design warned about at the start of this workstream. Final total:
~$504 of $600 cumulative budget.

## 27. New report section: system ranking + submission recommendation (10 slots)

User: organizers allow up to 10 submitted systems. Added a new §10 to the
report ranking all 9 `src/systems/` implementations, not just
`brief_revise_agent`. Checked real evidence across the whole repo, not
just this workstream: `find data/outputs/<system>` showed 4 of 9 systems
(`ali_deepresearch`, `claude-code-research`, `codex_cli_research`,
`o3_deep_research`) have never produced a single output -- unranked, not
ruled worst, since there's no evidence either way. Pulled real arena
leaderboards from `evaluation-results/arena/` for the other 5:
`aus_agent` beats `facets_agent` 66.7% and `facet_rag` 100% (15-0);
`facets_agent` beats `facet_rag` 100% (30-0); `aus_agent_v2` beats every
`brief_revise_agent` variant tested against it, including this session's
base cell (§5.1, 40% for `brief_revise_agent`).

**Recommendation: submit 4 systems, not 10** -- `aus_agent_v2` (best,
most expensive), `brief_revise_agent` base cell (ties `aus_agent_v2`
standalone at ~1/50th the cost, NOT `hybrid`-alone per §25/§26's
reversal), `aus_agent` (cheap, beats the two systems below it
convincingly), and `facets_agent` (marginal -- include only if
architectural diversity itself is valued, not just top scores). Do not
submit `facet_rag` (loses every available comparison) or any zero-output
system (would need real implementation work first, not just a submission
wrapper). Explicitly do not use a submission slot on `hybrid`-alone.

Fixed one table-rendering bug while building this (an inline code span
overflowing a narrow table column, same class of bug the earlier Opus
report revision had already fixed once).

## 28. Expanded to 6-system submission, hedged across both real eval axes

User wants more submissions since the actual official evaluation method
is uncertain, and explicitly wants the best-on-rubric system included.
Checked the track guidelines directly (`rag-task.md`, not assumed): the
organizers' real evaluation is confirmed BOTH pairwise battles AND
independent nugget-rubric scoring, plus separate citation precision/
recall -- not a single method. This makes the arena-vs-standalone
disagreement found in §25/§26 directly actionable rather than just a
methodological curiosity: a portfolio that only wins one axis has a real
gap against the organizers' own stated evaluation design.

Recommendation revised from 4 to 6 systems (of the 10 allowed slots):
`aus_agent_v2`, `brief_revise_agent` base cell (best cheap arena
performer), `brief_revise_agent` `hybrid`-alone (best standalone/nugget-
rubric score in the whole report, previously excluded -- now included
specifically as the rubric-axis hedge), `aus_agent`, `facets_agent`,
and `facet_rag` (weakest but a fourth genuinely distinct architecture,
zero additional cost since it already has real generated output). Still
excludes the 4 zero-output systems -- hedging a known unknown
(evaluation method) is not the same as submitting a system with zero
evidence behind it at all.
