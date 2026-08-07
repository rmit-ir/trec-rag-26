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

## Not done yet

- Standalone scoring of the 5 new cells (4 Block 1 + divergent anchor) once
  their batches finish, plus the `aus_agent_v2` calibration run.
- The remaining 6 of sol's 7 divergent-screen cells (srf skipped, see
  above) -- code is wired, not yet launched; sol's own gate wants a
  one-topic smoke test per cell first, verifying from the trace that the
  flag actually changed model behavior before committing the full 15-topic
  batch.
- The actual mixed-effects model fit -- needs Block 1 + divergent-screen
  data in hand first.
- Arena confirmation of the eventual best cell(s).
