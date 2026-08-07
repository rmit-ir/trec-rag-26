# Research agent v2: architecture optimization

**Date:** 2026-08-06  
**Objective:** exceed the 0.6508 Sol baseline through research/answer method
changes, with 0.80 as the target, while keeping `aus_agent` at baseline + UTC
locale correction and developing architecture only in `aus_agent_v2`.

This supersedes the stale grading-status and candidate-architecture sections of
[`2026-08-06-aus-agent-multistage-pipeline.md`](2026-08-06-aus-agent-multistage-pipeline.md).
That earlier file claimed full grading was not authorized; the user subsequently
authorized live generation and rubric grading explicitly.

## Reproducibility and exact inputs

Every model input is durable rather than reconstructed from prose here:

- The exact 30 requests are the organizer TSV at
  `data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv`.
- The exact frozen difficult-topic gate is
  `data/task-comparison/topics-aus-v2-low8.tsv`.
- The complete research prompt used by both branches is
  `src/systems/aus_agent_v2/prompts/system/default.md`; the rendered timestamp
  and request wrapper are `TASK_PROMPT` in `agent.py` and are also stored
  verbatim in every output's `trace.input`.
- Exact planning, request-only scout, facet decomposition/synthesis, blueprint,
  and router prompts/tool schemas are the literal constants in
  `coverage_plan.py`, `plan_critic.py`, `facet_research.py`,
  `answer_blueprint.py`, and `blueprint_route.py` in this same commit.
- Exact request-only routing decisions and their raw model output are
  [`2026-08-06-aus-agent-v2-adaptive-router-dev30.jsonl`](assets/2026-08-06-aus-agent-v2-adaptive-router-dev30.jsonl)
  and
  [`2026-08-06-aus-agent-v2-blueprint-router-v2-dev30.jsonl`](assets/2026-08-06-aus-agent-v2-blueprint-router-v2-dev30.jsonl).
- Exact commands, timestamps, search strings, commit decisions, retry events,
  and terminal summaries are in the `*-live.log` and `*-grade.log` assets named
  below. Each generated artifact is also retained under
  `data/outputs/aus_agent_v2/` and selected by its exact `run_id`.
- The full fixed rubric input is
  `data/task-comparison/dev-rubrics-fixed.jsonl`; waivers and signed scoring are
  implemented in `tasks/task-comparison/scripts/rubric_eval.py`.

No subset mean in this worklog is called a full-30 score. Every rubric result
uses three independent Sol judge passes per topic; the full result ledger,
including per-topic and per-topic-axis matrices, is
`docs/auto-optimize/rubric-results.jsonl`.

## Baselines and output-form decision

The frozen author baselines were inspected before changing answer form:

| Baseline | topics | heading topics | table topics | bullet topics | numbered-list topics |
|---|---:|---:|---:|---:|---:|
| `base-agentic-bm25` | 119 | 0 | 1 | 0 | 0 |
| `base-singlepass` | 119 | 2 | 1 | 0 | 0 |

The one table topic explicitly asks for a grading table, and every structured
object carries citations. Broad Markdown was therefore not enabled: it would
create headings/table cells that cannot reliably satisfy citation locality.
The title in every original and v2 system prompt is `# Research agent`, not
`AUS research agent`; UTC is injected into the model request instead of the
host's Australia/Melbourne locale.

Comparable full-30 anchors:

| run | architecture | mean | below 0.65 | severe penalties | mean words |
|---|---|---:|---:|---:|---:|
| `v2-dev30-default` | Sol baseline | 0.6508 | — | — | — |
| `sol-aus-v2-research-first-dev30-20260806` | plan + scout + continuous research + direct repair | 0.6991 | 8 | 6 | 946.5 |
| `sol-aus-v2-research-first-pre-repair-dev30-20260806` | plan + scout + continuous research | **0.7042** | 6 | 6 | 912.9 |

The confirmed method gain before routing is therefore +0.0534 over the Sol
baseline. Direct post-draft repair reduced it by 0.0051, so the promoted control
is the pre-repair architecture.

## Why fact extraction and finish-the-claim were not valid nulls

The corrected saved-run audit is executable at
[`2026-08-06-finish-facts-pipeline-audit.py`](assets/2026-08-06-finish-facts-pipeline-audit.py)
and its full 30-topic/criterion matrices are
[`2026-08-06-finish-facts-pipeline-audit.log`](assets/2026-08-06-finish-facts-pipeline-audit.log).

- Prompt-only finish-the-claim converted 95/387 partial criteria to satisfied,
  but downgraded 152 previously satisfied criteria and shortened the answer.
  It acted, but traded breadth for precision.
- Commit-time extraction produced 1,223 cards. Although 90.2% came from a
  parent document later cited, only 7.5% of normalized values appeared exactly
  in prose. The old pipeline stored annotations in historical tool arguments
  and had no final state transition that consumed them.

The correct conclusion was therefore “handoff missing,” not “facts cannot
help.” `answer_blueprint.py` implements the missing transition: commit-time
fact state + complete intended claims + exact committed ids are validated and
replayed at the context tail immediately before prose. A later successful
retrieval invalidates the blueprint.

## Adaptive parallel-facet full-30 experiment

The first architecture hypothesis routed requests between three parallel
evidence researchers plus synthesis and the strongest continuous control. A
four-topic gate was +0.0136, and a counterfactual simple route was +0.0495, so a
request-only router was frozen before generation.

Run: `sol-aus-v2-adaptive-dev30-20260806`  
Raw generation:
[`2026-08-06-aus-agent-v2-adaptive-dev30-live.log`](assets/2026-08-06-aus-agent-v2-adaptive-dev30-live.log)  
Three-pass grade:
[`2026-08-06-aus-agent-v2-adaptive-dev30-grade.log`](assets/2026-08-06-aus-agent-v2-adaptive-dev30-grade.log)  
Full paired matrix and deterministic 50,000-sample topic bootstrap:
[`2026-08-06-aus-agent-v2-adaptive-dev30-paired-matrix.log`](assets/2026-08-06-aus-agent-v2-adaptive-dev30-paired-matrix.log)

| branch | n | control | adaptive | delta | wins-losses |
|---|---:|---:|---:|---:|---:|
| parallel evidence | 10 | 0.7052 | 0.6505 | −0.0547 | 3–7 |
| integrated research | 20 | 0.7037 | 0.6906 | −0.0130 | 9–10 |
| **all full 30** | **30** | **0.7042** | **0.6773** | **−0.0269** | **12–17** |

Paired 95% CI: `[−0.0637, +0.0066]`. Full-30 goal conditions were 10
topics below 0.65 and 8 severe penalties across 7 topics. The main axis losses
were Implicit Criteria −0.0409 and Synthesis −0.0306. Parallel facets had
fragmented the exact relationships the final answer needed, so this route was
rejected.

## Mandatory evidence-to-answer blueprint gate

Run: `sol-aus-v2-answer-blueprint-low8-20260806`  
Exact eight requests: `data/task-comparison/topics-aus-v2-low8.tsv`  
Raw generation:
[`2026-08-06-aus-agent-v2-answer-blueprint-low8-live.log`](assets/2026-08-06-aus-agent-v2-answer-blueprint-low8-live.log)  
Three-pass grade:
[`2026-08-06-aus-agent-v2-answer-blueprint-low8-grade.log`](assets/2026-08-06-aus-agent-v2-answer-blueprint-low8-grade.log)  
Full paired matrix:
[`2026-08-06-aus-agent-v2-answer-blueprint-low8-paired-matrix.log`](assets/2026-08-06-aus-agent-v2-answer-blueprint-low8-paired-matrix.log)

| qid suffix / topic | control | blueprint | delta |
|---|---:|---:|---:|
| `58498` retirement posts | 0.2716 | 0.4609 | +0.1893 |
| `605492` medical-label experiment | 0.5307 | 0.5526 | +0.0219 |
| `60542d` Mahabharata politics | 0.4583 | 0.5160 | +0.0577 |
| `9af32d` preschool safety | 0.4904 | 0.6410 | +0.1506 |
| `58488` engram/predictive model | 0.6864 | 0.5537 | −0.1327 |
| `6054a7` UBI comparison | 0.5616 | 0.5868 | +0.0252 |
| `605367` Taj Mahal + dating | 0.6867 | 0.6267 | −0.0600 |
| `60547e` heterogeneous swarm | 0.7062 | 0.5326 | −0.1736 |
| **low-eight mean only** | **0.5490** | **0.5588** | **+0.0098** |

The paired CI `[−0.0736, +0.0911]` does not justify global promotion. It does
prove the mechanism is implemented: all eight called `prepare_answer` exactly
once with no invalid ids/retries, and 184/191 intended claims (96.3%) had at
least 60% lexical carry-through into final prose. Complete carry-through matrix:
[`2026-08-06-aus-agent-v2-answer-blueprint-carrythrough.log`](assets/2026-08-06-aus-agent-v2-answer-blueprint-carrythrough.log).

The interaction is interpretable: expository/applied deliverables gained,
while coupled novel technical systems lost Synthesis (axis −0.0563). This led
to a second request-only route, not a global blueprint.

## Blueprint-vs-continuous request route

The first 30-request audit selected 20 blueprint / 10 continuous but failed the
known mixed-domain topic. Its exact output is
[`2026-08-06-aus-agent-v2-blueprint-router-dev30.jsonl`](assets/2026-08-06-aus-agent-v2-blueprint-router-dev30.jsonl).
The prompt was corrected with an explicit multi-domain override and all 30
requests were re-audited. The frozen v2 matrix is
[`2026-08-06-aus-agent-v2-blueprint-router-v2-dev30.jsonl`](assets/2026-08-06-aus-agent-v2-blueprint-router-v2-dev30.jsonl): 15 blueprint / 15
continuous, matching all eight known gate interactions.

Full-30 routed run: `sol-aus-v2-blueprint-routed-dev30-20260806`  
Initial raw generation:
[`2026-08-06-aus-agent-v2-blueprint-routed-dev30-live.log`](assets/2026-08-06-aus-agent-v2-blueprint-routed-dev30-live.log)  
First resume:
[`2026-08-06-aus-agent-v2-blueprint-routed-dev30-resume1.log`](assets/2026-08-06-aus-agent-v2-blueprint-routed-dev30-resume1.log)  
Resilient resume:
[`2026-08-06-aus-agent-v2-blueprint-routed-dev30-resume2-resilient.log`](assets/2026-08-06-aus-agent-v2-blueprint-routed-dev30-resume2-resilient.log)  
Three-pass grade: pending generation completion.

Generation was stopped at 22/30 completed topics when the operator imposed a
$300 total Bedrock cap and the corrected cross-system ledger showed that cap
had already been exceeded. The 50 artifacts (including failed and interrupted
attempts) cost $50.0195 from their persisted token counts. No partial mean is
reported and no grade was launched; the 22 answers remain reproducible but are
not comparable with a complete 30-topic score.

The first two attempts encountered a broad Mantle incident alternating HTTP
502, 503, and 504 responses. The SDK exhausted its normal retry window after a
topic had already accumulated searches and committed evidence, which exposed a
pipeline reliability defect: a transient transport outage discarded that
topic's entire in-memory research state. Neither attempt completed a topic, and
failed/interrupt artifacts are excluded by trace status.

The repair is deliberately v2-local. `provider.py` wraps one unchanged OpenAI
turn in a bounded long-window retry; the baseline `aus_agent` provider remains
at its base implementation. Since the base provider appends assistant state
only after a successful response, this outer retry cannot duplicate a tool call
or alter the trajectory. The live recovery probe is
[`2026-08-06-mantle-v2-resilient-health.log`](assets/2026-08-06-mantle-v2-resilient-health.log):
it preserved one turn through four outage cycles and then returned `OK`.
Targeted provider/system tests passed 103 cases, and the complete hermetic suite
passed 1,663 with eight live tests deselected and no skips; logs are
[`2026-08-06-aus-agent-v2-resilient-provider-tests.log`](assets/2026-08-06-aus-agent-v2-resilient-provider-tests.log)
and
[`2026-08-06-aus-agent-v2-full-tests-resilient-provider.log`](assets/2026-08-06-aus-agent-v2-full-tests-resilient-provider.log).

The supplied Mantle credential was decoded without recording the secret. It is
a URL-safe Base64 envelope containing a presigned AWS request, not a JWT. The
first envelope had `X-Amz-Date=20260806T140512Z`; the replacement had
`X-Amz-Date=20260806T175044Z`. Both advertise `X-Amz-Expires=43200`, but that
12-hour SigV4 envelope is **not** the effective lease: Mantle applies a separate
four-hour limit. The replacement's operational cutoff is therefore about
`2026-08-06T21:50:44Z` (17:50:44 New York), not the envelope's nominal
`2026-08-07T05:50:44Z`.

## Budget audit and stop condition

The earlier budget monitor in
`tasks/task-comparison/scripts/goal_status.py` inspected only
`data/outputs/aus_agent/` and only run ids containing `dev30-`. It therefore
omitted **every** `aus_agent_v2` probe, failed attempt, partial run, and complete
generation. That was a material accounting defect, not zero spend.

The corrected monitor prices every persisted v2 artifact from
`trace.summary.tokens` at the committed Sol/Luna/Terra rates, while retaining
the existing `dev30-` boundary for the older shared `aus_agent` directory. Its
raw output is
[`2026-08-06-aus-agent-v2-budget-audit.log`](assets/2026-08-06-aus-agent-v2-budget-audit.log):

| component | USD |
|---|---:|
| original `aus_agent` optimization generation | 381.73 |
| all `aus_agent_v2` generation | 580.04 |
| rubric judging | 134.95 |
| **total** | **1,096.72** |

The operator's new cap is $300, so the monitor now defaults to $300 and exits
`BUDGET EXCEEDED` at 365.6%. All live model workers were interrupted immediately
after this audit and a process-table check found none remaining. No further
provider call is authorized unless the operator explicitly establishes a fresh
budget window.

## Result ledger

Subset probes are diagnostics only. Their exact run/grade logs are retained in
`worklogs/assets/2026-08-06-aus-agent-v2-*`; the principal decisions were:

| intervention | scope | result / decision |
|---|---|---|
| finish-the-claim, citation-local | critical 2 | +0.0064 local; works but too small alone |
| wide compact scout | low 8 | −0.0058; reject |
| fresh whole-answer rewrite | low 8 | −0.040 to −0.047; destructive coverage loss |
| plain prose structural labels | low 8 | −0.0138 overall; only topic-specific benefit |
| parallel facets | gate 4 | +0.0136; failed full-30 generalization |
| independent candidate oracle | gate 4 | 0.5934 vs 0.5175, but selectors failed to identify it |
| mandatory answer blueprint | low 8 | +0.0098 globally, strong request-shape interaction |

## Verification and cleanup

Targeted blueprint tests: 4 passed. Targeted blueprint-route tests: 2 passed.
After promoting the fully graded 0.7042 configuration as the public default,
the targeted system suite passed 14 cases and the complete hermetic suite passed
1,664 cases with eight live tests deselected, no skips, and no failures. Exact
logs are
[`2026-08-06-aus-agent-v2-promoted-default-tests.log`](assets/2026-08-06-aus-agent-v2-promoted-default-tests.log)
and
[`2026-08-06-aus-agent-v2-final-full-tests.log`](assets/2026-08-06-aus-agent-v2-final-full-tests.log).

`docs/architecture.html` was regenerated and launched on the `aus_agent_v2`
deep link; the exact generator output is
[`2026-08-06-aus-agent-v2-promoted-arch-viz.log`](assets/2026-08-06-aus-agent-v2-promoted-arch-viz.log).
The default diagram now contains only plan → atomic scout → integrated
research/search/commit → cited draft → map/save; unconfirmed experimental
editors are documented but not drawn as if they were active. Both the model-run
process check after the budget stop and the final terminal audit found no live
experiment or grader processes.
