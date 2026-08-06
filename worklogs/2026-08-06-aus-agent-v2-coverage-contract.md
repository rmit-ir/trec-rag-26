# Research agent v2: executable coverage/evidence contract

**Date:** 2026-08-06
**Goal:** reach a mean rubric score of 0.80 on all 30 development topics through
method/architecture improvements, without modifying the original `aus_agent`.
**Spend this session:** $0.00; all analysis was offline over already-paid
artifacts. The corrected cumulative optimization-loop ledger is $1,096.72
against the operator's $300 hard cap, so no provider or grader call was made.

## Exact offline inputs

- Complete result ledger:
  `docs/auto-optimize/rubric-results.jsonl`.
- Fixed rubric rows, including waivers and signed weights:
  `data/task-comparison/dev-rubrics-fixed.jsonl`.
- Three-repeat Sol verdict caches:
  `data/task-comparison/rubric-eval/gpt-5.6-sol/<variant>/<qid>{,.r1,.r2}.json`.
- Candidate outputs and full trajectories:
  `data/outputs/{aus_agent,aus_agent_v2}/` selected by exact run id.
- Exact 30 requests for any future comparable run:
  `data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv`.
- Executable oracle analysis and its complete per-topic matrices:
  [`2026-08-06-aus-agent-v2-oracle-analysis.py`](assets/2026-08-06-aus-agent-v2-oracle-analysis.py)
  and
  [`2026-08-06-aus-agent-v2-oracle-analysis.log`](assets/2026-08-06-aus-agent-v2-oracle-analysis.log).
- Full plan/retrieval/commit/answer handoff audit, including threshold
  sensitivity and the raw artifact selectors:
  [`2026-08-06-aus-agent-v2-handoff-audit.md`](assets/2026-08-06-aus-agent-v2-handoff-audit.md).

No prompt was sent to a model in this session. The exact candidate prompt/tool
inputs to be tested are the literal strings and JSON schemas in
`coverage_plan.py`, `plan_critic.py`, `observable_scout.py`,
`prompts/system/default.md`, and the new `coverage_contract.py`; every future
saved run also persists their rendered values under `trace.input`.

## Corrected oracle: the content exists, but the pipeline does not unite it

The first oracle script incorrectly used generation `run_id` as the rubric
cache key. The baseline ledger row has `run_id=v2-dev30-default` but
`variant=sol-default`; because caches use `variant`, the baseline was silently
omitted from the first criterion union. The script now uses `run_id` for output
selection and `variant` for caches.

Core codes:

- B: `sol-default` / generation `v2-dev30-default`
- P: `sol-aus-v2-research-first-pre-repair-dev30-20260806`
- R: `sol-aus-v2-research-first-dev30-20260806`
- A: `sol-aus-v2-adaptive-dev30-20260806`

| Candidates | Whole-answer oracle | Criterion union |
|---|---:|---:|
| B | 0.6508 | 0.6508 |
| P | 0.7042 | 0.7042 |
| R | 0.6991 | 0.6991 |
| A | 0.6773 | 0.6773 |
| B + P | 0.7207 | 0.7551 |
| B + R | 0.7249 | 0.7623 |
| B + A | 0.6990 | 0.7359 |
| P + R | 0.7195 | 0.7367 |
| P + A | 0.7258 | 0.7569 |
| R + A | 0.7294 | 0.7630 |
| B + P + R | 0.7332 | 0.7793 |
| B + P + A | 0.7345 | 0.7852 |
| B + R + A | 0.7398 | **0.7957** |
| P + R + A | 0.7367 | 0.7785 |
| B + P + R + A | **0.7445** | **0.8048** |

All eight Sol-written complete runs have a whole-answer oracle of 0.7508 and a
criterion union of **0.8284**. The best three candidates remain below target;
at least four complementary behaviors are needed. Existing answer selectors
are adverse evidence: the prior four-topic selector scored 0.4634 while the
independent-candidate answer oracle was 0.5934. Therefore selecting completed
answers or routing requests cannot reach 0.80; complementary obligations must
be united before a single draft.

The four-core criterion union gains over P are broad, not one formatting trick:

| Axis | P | Four-core union | Gain |
|---|---:|---:|---:|
| References and citations | 0.5167 | 0.7333 | +0.2167 |
| Instruction following | 0.7066 | 0.8264 | +0.1198 |
| Implicit criteria | 0.7175 | 0.8066 | +0.0891 |
| Synthesis | 0.6900 | 0.7693 | +0.0792 |
| Explicit criteria | 0.8179 | 0.8831 | +0.0652 |
| Communication | 0.5763 | 0.6355 | +0.0591 |

The complete 30-topic oracle matrix is in the log asset above; no subset mean
is presented as a comparable run.

## Where P loses requirements

The conservative stage audit found 268 unmet reward criteria. At token recall
0.5 after removing rubric examples:

| Failure stage | Criteria | Weighted loss |
|---|---:|---:|
| Plan/discovery omission | 91 | 171.33 |
| Answer present but underfulfilled | 71 | 137.83 |
| Retrieved → commit loss | 44 | 78.67 |
| Committed → answer loss | 35 | 68.50 |
| Planned → retrieval loss | 18 | 43.50 |
| Planned form not executed | 6 | 16.50 |
| Unplanned form gap | 3 | 9.67 |

The run already retrieved 393.4 units/topic but committed only 35.0. This
falsifies “just search more” as the primary fix and directly supports an
executable obligation/evidence handoff.

Finance is the clearest pipeline failure: 401(k), IRA, S&P 500, Dow, Nasdaq,
Vanguard, Schwab and AGG were all committed but omitted from the answer. The
old global no-structure rule also conflicted with distinguishable blog posts.
Mahabharata likewise committed Ramayana, Trigarta, Avanti and Parikshit material
and then compressed all four away. Full criterion and term-flow matrices are in
the handoff-audit asset.

## Implemented candidate architecture

`coverage_contract.py` replaces the permissive answer blueprint only when the
new explicit candidate flag is enabled:

```text
request
  → isolated planner + semantic scout + observable scout
  → stable planner Pxx / scout Sxx contract rows
  → search(for_requirements=[ids])
  → automatic adjacent pages inherit the same search purpose
  → commit_context(supports=[requirement_id, claim, value_scope])
  → bounded selected-anchor closure status after each commit
  → submit_answer(sentences[text,evidence_ids,satisfies], unresolved)
  → deterministic closure/citation/exact-term validation
  → existing citation mapping + organizer output
```

This corrects six concrete defects:

1. Every plan/scout row receives a stable id; a one-item map cannot validate a
   20-item plan.
2. Search attempts are attached to explicit purposes. Invalid ids are rejected
   before dispatch.
3. A committed page can support only a row named by the search that found it;
   automatic adjacent pages retain that purpose but do not satisfy anything
   merely by being fetched.
4. Commit-time extraction is now selective and executable: only chosen
   `claim` + `value_scope` anchors tied to a row are kept. Generic hundreds-of-
   facts replay is removed.
5. The newest commit result and any premature final-turn correction carry a
   closure status bounded at 6,000 characters. This fixes the recency handoff
   without the old blueprint's 21,949–34,846-character packet.
6. `submit_answer` is the final answer, not a rehearsal before a second writer.
   It checks all must-answer ids, exact terms, committed/mapped citations,
   unresolved rows with real search attempts, citation count and 1,024 words.
   Untagged synthesis sentences remain allowed so the ledger does not force an
   atomized report.

The full-30-confirmed `pipeline.run_one` stays on the 0.7042 architecture.
`pipeline.run_contract_one` is a distinct candidate and enables the
complementary observable scout. CLI users opt in with
`--coverage-contract --observable-scout`.

## Answer form decision

Frozen author baselines remain decisive caution:

| Baseline | Topics | Heading topics | Table topics | Bullet topics | Numbered-list topics |
|---|---:|---:|---:|---:|---:|
| `base-agentic-bm25` | 119 | 0 | 1 | 0 | 0 |
| `base-singlepass` | 119 | 2 | 1 | 0 | 0 |

Broad Markdown/tables were not enabled. The candidate allows only a plain label
prefix when the request is itself a repeated deliverable, e.g.
`Blog post 1 — <opening sentence>`. The label and factual text remain one answer
item, so citation locality is preserved. Ordinary reports retain plain prose.

## Verification

Targeted behavior:

```text
bash scripts/test.sh tests/aus_agent_v2/test_coverage_contract.py tests/aus_agent_v2/test_adjacent_search.py tests/systems/test_aus_agent_v2.py
```

Result: 31 passed, one live test deselected.

Full hermetic suite:

```text
set -o pipefail
bash scripts/test.sh 2>&1 | tee worklogs/assets/2026-08-06-aus-agent-v2-coverage-contract-full-tests.log
```

Result: **1,679 passed, eight live tests deselected, zero skips/failures** in
16.71 seconds. Raw log:
[`2026-08-06-aus-agent-v2-coverage-contract-full-tests.log`](assets/2026-08-06-aus-agent-v2-coverage-contract-full-tests.log).

Architecture regeneration/open:

```text
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open
```

Result: six systems, 18 edges, five engines; log:
[`2026-08-06-aus-agent-v2-coverage-contract-architecture.log`](assets/2026-08-06-aus-agent-v2-coverage-contract-architecture.log).

`progress.svg` was regenerated after correcting its stale $500 cap and zero-
spend invocation. It now shows **$1,096.72 / $300 (365.6%)** in red and retains
the non-overlapping ordinal labels. Generator log:
[`2026-08-06-aus-agent-v2-coverage-contract-progress.log`](assets/2026-08-06-aus-agent-v2-coverage-contract-progress.log).

## Paid verification still required

Offline tests prove protocol behavior, not a rubric gain. The success condition
remains a complete 30-topic run and its three-pass score; 0.8048 is an oracle
upper bound, not an achieved system score. Because the operator's hard total
cap is already exceeded, the following commands are recorded but **must not be
run until the operator explicitly creates a fresh budget window**.

Generation (all 30, no subset score):

```bash
set -o pipefail
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --all --backend openai --model openai.gpt-5.6-sol \
  --coverage-contract --observable-scout \
  --run-id sol-aus-v2-coverage-contract-dev30 \
  2>&1 | tee worklogs/assets/<date>-aus-agent-v2-coverage-contract-dev30-live.log
```

The run must be monitored against the new explicitly authorized cap using
`goal_status.py`; a provider worker is stopped before, not after, the cap.
Grading must use all 30 generated topics, three Sol repeats, and append the
result ledger through the existing rubric-eval path. Promotion requires a
complete mean above 0.7042 first; the goal itself remains mean ≥0.80, no topic
below 0.65, no severe satisfied penalty, no over-cap answer, and confirmation
by a second judge model as encoded in `goal_status.py`.
