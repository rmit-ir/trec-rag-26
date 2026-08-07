# Research-agent optimization exploration: consolidated findings and variants

Date: 2026-08-06

This is the canonical decision summary for the research-agent optimization
exploration. It consolidates the earlier single-factor sweep, the subsequent
`aus_agent_v2` architecture experiments, the frozen evidence-flow audits, and
the final runnable candidates. It does not replace the raw worklogs or assets;
it provides one place to understand what was tried, what happened, which
systems remain useful, and how to run them.

No new experiment was run to create this summary. Incremental provider, search,
and judge calls were `0 / 0 / 0`; incremental cost was `$0.00`.

The highest verified comparable score at the end of the exploration is
**`0.704159` on all 30 development topics**. The requested `>=0.80` score has
not been achieved. The most promising ungraded candidate has an idealized
development-set criterion-union ceiling of `0.8284`; that is an upper bound,
not a forecast or achieved score.

The mechanically tracked cumulative cost is **`$1,096.72`**:

| Component | Cost |
| --- | ---: |
| Original `aus_agent` optimization generation | $381.73 |
| All `aus_agent_v2` generation | $580.04 |
| Rubric judging | $134.95 |
| **Total** | **$1,096.72** |

This exceeds the operator's standing absolute `$300` ceiling. Every current
paid runner is fail-closed before provider creation. A renewed credential alone
does not authorize another call; a new explicit absolute total cap and reserve
would be required.

## How to read the results

Four labels are used throughout:

- **verified full-30**: all 30 fixed development topics were generated and
  graded with three independent Sol judge passes;
- **subset diagnostic**: useful for mechanism or interaction discovery, but not
  comparable with the full-30 score;
- **offline oracle/audit**: deterministic analysis of already-paid artifacts,
  useful for locating capacity or defects but not a model-performance result;
- **implemented, ungraded**: runnable and hermetically tested, but without a
  comparable live score.

The score is the signed fixed-rubric mean produced by
`tasks/task-comparison/scripts/rubric_eval.py`. Full result rows, including
per-topic and per-axis scores, are in
`../docs/auto-optimize/rubric-results.jsonl`. Confidence intervals below are
paired topic bootstraps where available.

## Exact inputs and durable evidence

All live full-30 experiments use the exact requests in:

```text
data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv
```

The fixed evaluation input is:

```text
data/task-comparison/dev-rubrics-fixed.jsonl
```

Three-repeat Sol judge caches are under:

```text
data/task-comparison/rubric-eval/gpt-5.6-sol/
```

Complete generation artifacts and exact rendered model inputs, tool calls,
search strings, source ids, token counts, and saved answers are under:

```text
data/outputs/aus_agent/
data/outputs/aus_agent_v2/
```

The original prompt-arm texts are preserved verbatim in
`assets/2026-08-06-aus-agent-retired-experiments/prompts/`; their definitions
and intent are indexed in `../docs/auto-optimize/variants.md`. Tool surfaces at
each experimental boundary are preserved in the
`assets/2026-08-06-aus-agent-tools-v*/` snapshots.

The v2 candidate prompts and schemas are the literal versioned strings in
`../src/systems/aus_agent_v2/`. The complete 30 model-visible candidate-union
packets, including every exact query, immutable answer item, resolved document
id, source artifact path, and per-topic measurement, are preserved at
`assets/2026-08-06-aus-agent-v2-candidate-union-dev30.jsonl` with SHA-256
`e62a6fe7caee9489a96ab2308ce6055840cc291bfd160b9274f873d44a9c85f4`.

The detailed experiment narratives and raw matrices consolidated here are:

- `2026-08-06-rubric-optimization-loop.md`;
- `2026-08-06-aus-agent-multistage-pipeline.md`;
- `2026-08-06-aus-agent-v2-architecture-optimization.md`;
- `2026-08-06-aus-agent-v2-coverage-contract.md`;
- `2026-08-06-aus-agent-v2-answer-form-hardening.md`;
- `2026-08-06-aus-agent-v2-commit-correction.md`;
- `2026-08-06-aus-agent-v2-anchor-integrity.md`;
- `2026-08-06-aus-agent-v2-lean-contract.md`;
- `2026-08-06-aus-agent-v2-atomic-mutable-ledger.md`;
- `2026-08-06-aus-agent-v2-atomic-planner-transport.md`;
- `2026-08-06-aus-agent-v2-source-locality-and-semantic-closure.md`;
- `2026-08-06-aus-agent-v2-row-semantic-verifier.md`;
- `2026-08-06-aus-agent-v2-semantic-enforcement-candidate-union.md`.

Those source worklogs reference the complete console logs, scripts, raw typed
arguments, and per-topic matrices. This summary does not silently reconstruct
inputs from prose.

## Executive findings

1. The author baselines almost never use Markdown structure. Across 119 answers,
   `base-agentic-bm25` used zero heading topics and one requested table;
   `base-singlepass` used headings on two topics and one requested table. Broad
   headings, tables, bullets, or numbering were therefore not imposed. Such
   structure makes citation locality harder and the measured `cite-or-cut`
   intervention was actively harmful.
2. Two early changes produced real gains: removing the Australia/Melbourne
   locale cue (`+0.0253`) and changing the generator from Luna to Sol
   (`+0.0698`, CI `[+0.0404, +0.1014]`). These moved the baseline to `0.6508`.
3. Prompt wording, more reasoning, source labels, fact annotations, more answer
   allowance, and post-hoc whole-answer rewrites did not produce a bankable
   improvement. Several changed behavior substantially, so their nulls were
   not simply ignored instructions.
4. A new plan + blind atomic scout + integrated research architecture did
   improve the complete score from `0.6508` to `0.704159`. A direct repair pass
   then reduced it to `0.6991`, establishing that fresh rewriting loses useful
   coverage.
5. The dominant remaining failure is evidence-to-answer transport. Of 268
   unmet reward criteria in the best run, 44 had relevant material retrieved
   but not committed, 35 had committed material absent from the answer, and 71
   were present but underfulfilled.
6. Fact extraction was not a valid method null. The old system extracted facts
   but stored them in historical tool arguments without an enforced terminal
   consumer. Only 22 of 164 cards previously considered valid formed a complete
   source-to-claim invariant under the corrected contract.
7. Prompt-only finish-the-claim acted but traded breadth for precision. The
   correct follow-up is an enforced state transition, not more wording: local
   source spans, immutable answer/citation structure, typed verification, and
   one bounded text-only correction.
8. Existing complete answers are complementary. Whole-answer routing over all
   eight cannot exceed `0.7508` in the oracle, while a criterion-level union
   reaches `0.8284`. This motivated an extractive item selector rather than
   another writer.

## Phase 1: single-factor screen

### Measurement and structural baselines

The same 30 baseline answers scored under Luna and Sol judges showed Sol was
quieter (`0.0437` versus `0.0720` topic-level spread). The Sol judge was then
pinned and every full-30 result used three repeats.

| Configuration | Mean | Interpretation |
| --- | ---: | --- |
| Luna generator, Luna judge | 0.5350 | Starting measured baseline |
| Same answers, Sol judge | 0.5557 | Measurement change, not system gain |
| UTC clock and neutral “Research agent” identity | 0.5810 | `+0.0253` real harness gain |
| Sol generator, same default method | **0.6508** | `+0.0698`, CI `[+0.0404, +0.1014]` |

The neutral identity is deliberate. Prompt text says “research agent,” not
“AUS agent”; historical file and run ids retain `aus` only as implementation
names.

### Prompt arms

Control was Luna generation after the UTC fix: `0.5810`. Each row is 30 topics
and three Sol judge passes.

| Arm | Mean | Delta | 95% CI | Better | `<0.65` | Severe | Decision |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| finish-the-claim | 0.6047 | +0.0237 | `[−0.0030, +0.0515]` | 21/30 | 18 | 9 | Did not confirm on Sol |
| english-only | 0.5923 | +0.0113 | `[−0.0102, +0.0338]` | 17/30 | 18 | 10 | Do not promote |
| minimal | 0.5857 | +0.0047 | `[−0.0274, +0.0381]` | 16/30 | 18 | 10 | Statistical tie |
| no-meta-reference | 0.5853 | +0.0043 | `[−0.0145, +0.0225]` | 16/30 | 19 | 9 | Do not promote |
| name-the-source | 0.5793 | −0.0016 | `[−0.0244, +0.0206]` | 13/30 | 21 | 10 | Do not promote |
| decision-item | 0.5743 | −0.0067 | `[−0.0328, +0.0190]` | 13/30 | 19 | 14 | Penalty risk |
| paired-lead | 0.5737 | −0.0073 | `[−0.0292, +0.0143]` | 13/30 | 19 | 12 | Changed search pairing, no gain |
| compression | 0.5697 | −0.0113 | `[−0.0368, +0.0140]` | 14/30 | 18 | 12 | Reject |
| stated-form | 0.5675 | −0.0134 | `[−0.0357, +0.0084]` | 15/30 | 21 | 12 | Reject broad formatting |
| reading-a-result | 0.5617 | −0.0192 | `[−0.0439, +0.0048]` | 10/30 | 18 | 14 | Prompt did not fix handoff |
| decision-lead | 0.5578 | −0.0232 | `[−0.0416, −0.0050]` | 8/30 | 20 | 12 | **Kill** |
| cite-or-cut | 0.5474 | −0.0335 | `[−0.0555, −0.0099]` | 10/30 | 21 | 13 | **Kill** |

The `minimal` prompt was 77% smaller than the default and statistically tied,
showing that procedural prompt bulk itself was not buying score. It was not
promoted because its tiny sign reversed on Sol.

### Reasoning, tools, harness, and unfinished arms

| Intervention | Scope | Delta / outcome | Decision |
| --- | --- | --- | --- |
| `reasoning.mode=pro` | Gateway probe | Unknown values accepted; key is not parsed | Unavailable on Bedrock Mantle |
| effort medium | Luna full-30 | `−0.0115`, CI `[−0.0343, +0.0126]` | Null |
| effort high | Luna full-30 | `−0.0160`, CI `[−0.0434, +0.0127]` | Null |
| effort xhigh | Luna full-30 | `−0.0028`, CI `[−0.0265, +0.0223]` | Null |
| effort max | Sol full-30 | `−0.0048`, CI `[−0.0323, +0.0234]`; 1,564 reasoning tokens/topic | Properly powered null |
| absolute evidence density | Luna full-30 | `−0.0065`; 61.2% of chunks below 0.20 | Miscalibrated on chunks; replaced |
| within-batch `evidence_rank` | Luna full-30 | `+0.0025`, CI `[−0.0284, +0.0326]` | Null |
| `source_grade` | Luna full-30 | `−0.0017`, CI `[−0.0239, +0.0212]` | Null; penalties 11→9 |
| commit-time `facts` | Luna full-30 | `−0.0073`, CI `[−0.0367, +0.0226]`; 876 facts | Annotation had no terminal consumer |
| all three tools together | Sol full-30 | `−0.0213`, CI `[−0.0467, +0.0041]`; penalties 6→11 | Reject crowded commit turn |
| known candidates | Luna full-30 | `+0.0105`, CI `[−0.0160, +0.0370]`; Implicit `−0.0111` | Hypothesis refuted |
| coverage audit interrupt | Luna full-30 | `+0.0168`, CI `[−0.0149, +0.0499]`; four extra searches | Mechanism worked, score flat |
| 2,000-word allowance | Luna full-30 | `−0.0111`; 898 versus 894 words | Word cap was not binding |
| finish-the-claim confirmation | Sol full-30 | `−0.0139`, CI `[−0.0334, +0.0041]`; penalties 6→8 | Do not use prompt-only form |
| automatic neighbor pages | Implemented | Top-three hits acquire bounded adjacent pages | Never graded; not preferred over current options |
| identical-control replicate | Sol generation | 26/30 completed before credential expiry | Generation variance remains unmeasured |

The important interpretation is not “facts cannot help.” The facts arm changed
what was recorded, but the answer-writing transition did not consume that
state. Likewise, the coverage audit generated more retrieval without improving
the final synthesis. These observations redirected the exploration from prompt
advice to pipeline enforcement.

## Phase 2: architecture exploration

### Comparable full-30 results

| Run | Behavior | Mean | Delta vs Sol default | `<0.65` | Severe | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `v2-dev30-default` | Original Sol method, UTC | 0.6508 | — | 13 | 6 | Verified baseline |
| `sol-aus-v2-research-first-pre-repair-dev30-20260806` | Isolated plan + blind atomic scout + integrated research; no editor | **0.704159** | **+0.0534** | 6 | 6 | **Promoted verified control** |
| `sol-aus-v2-research-first-dev30-20260806` | Same, then direct post-draft repair | 0.6991 | +0.0483 | 8 | 6 | Repair rejected |
| `sol-aus-v2-adaptive-dev30-20260806` | Request router between parallel facets and integrated research | 0.6773 | +0.0265 | 10 | 8 | Rejected; `−0.0269` vs promoted control |

The promoted control is the only method change in this exploration with a
verified full-30 gain. The direct repair result is evidence against handing a
good complete answer to a fresh general writer.

### Decision-bearing subset diagnostics

| Intervention | Scope | Result | What it established |
| --- | --- | ---: | --- |
| citation-local finish repair | Two critical topics | `+0.0064` | Small local effect, insufficient alone |
| wide compact scout | Low eight | `−0.0058` | More inventory without transport did not help |
| fresh whole-answer rewrite | Low eight | `−0.040` to `−0.047` | Rewriting destroys coverage |
| plain structural labels | Low eight | `−0.0138` | Only request-specific structure is safe |
| parallel facets | Four-topic gate | `+0.0136` | Gate did not generalize; full-30 regressed |
| independent candidate oracle | Four topics | `0.5934` vs control `0.5175` | Better candidates existed, selectors failed to choose them |
| mandatory answer blueprint | Low eight | `+0.0098`, CI `[−0.0736, +0.0911]` | Strong request-shape interaction, no global promotion |

The blueprint helped retirement (`+0.1893`) and preschool safety (`+0.1506`)
but hurt engram/predictive modeling (`−0.1327`) and heterogeneous swarms
(`−0.1736`). A request-only blueprint router was prepared, but its full-30 run
stopped at 22 completed topics when the corrected spend ledger showed the hard
cap had already been exceeded. No partial mean was reported.

## The pipeline defect found by the audits

The best verified run retrieved an average of 393.4 units per topic and
committed 35.0. A frozen audit of its 268 unmet reward criteria located the
losses as follows:

| Failure stage | Criteria | Weighted positive loss |
| --- | ---: | ---: |
| Plan/discovery omission | 91 | 171.33 |
| Present in answer but underfulfilled | 71 | 137.83 |
| Retrieved but not committed | 44 | 78.67 |
| Committed but absent from answer | 35 | 68.50 |
| Planned but not retrieved | 18 | 43.50 |
| Planned form not executed | 6 | 16.50 |
| Unplanned form gap | 3 | 9.67 |

The two post-retrieval omission stages alone account for 79 criteria and 147.17
weighted points. This is why additional search is not the primary recommendation.

The corrected replay of 1,223 old fact cards showed that the earlier extractor
and a real finish-the-claim invariant were materially different:

| Old outcome | Corrected outcome | Rows |
| --- | --- | ---: |
| malformed | malformed | 3 |
| out of claim/scope | out of claim/scope | 734 |
| oversized term | oversized term | 321 |
| source missing | scope not carried | 1 |
| valid | quantitative/date literal not carried | 19 |
| valid | scope not carried | 123 |
| valid | valid | **22** |

Only 22 of 164 formerly “valid” cards carried a complete executable invariant.
The old system could therefore extract facts seriously and still write the
same answer.

A second frozen semantic audit proved that deterministic tagging was not enough:

| Check | Outcome |
| --- | ---: |
| Generic or unrelated closures accepted by old validator | 540 / 540 |
| Accepted closures with zero requirement-content tokens | 392 / 540 |
| Requirement-parroting closures accepted | 540 / 540 |
| Unanimously positive criteria falsely rejected by 0.10 lexical gate | 68 / 345 |
| Unanimously positive criteria falsely rejected by 0.20 lexical gate | 192 / 345 |

Thus neither “tagged to the row” nor a lexical-overlap threshold can implement
finish-the-claim correctly. The verifier must judge the requirement, candidate
claim, and its row-local cited source together, while abstaining on ambiguity.

## Complementarity and oracle bounds

The four core complete runs are:

- B: `v2-dev30-default`;
- P: `sol-aus-v2-research-first-pre-repair-dev30-20260806`;
- R: `sol-aus-v2-research-first-dev30-20260806`;
- A: `sol-aus-v2-adaptive-dev30-20260806`.

| Candidates | Whole-answer oracle | Criterion union |
| --- | ---: | ---: |
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
| B + R + A | 0.7398 | 0.7957 |
| P + R + A | 0.7367 | 0.7785 |
| B + P + R + A | **0.7445** | **0.8048** |
| All eight complete Sol-written runs | **0.7508** | **0.8284** |

These are development-set upper bounds obtained from cached criterion verdicts.
They ignore word competition, dependencies between sentences, contradictions,
negative criteria, and selector error. They prove useful content exists across
runs; they do not predict that the selector will capture it.

## Recommended system variants

### 1. Verified research-first control

**Status:** verified full-30, score `0.704159`.

**Behavior:** one isolated coverage plan and one request-only atomic scout are
given to the same evidence-owning research conversation. That conversation
searches, commits evidence, and writes the final cited answer. No post-draft
editor is enabled.

**Use it when:** a dependable currently measured system is required, or as the
control for any new full-30 experiment.

**Trade-off:** it is the strongest verified system but still loses committed
facts and underfulfills some claims. It is not the architecture most likely to
reach 0.8.

Single-topic invocation:

```bash
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --backend openai --model openai.gpt-5.6-sol \
  --qid 683a58c9a7e7fe4e76958498 \
  --run-id <new-run-id>
```

Coverage plan and atomic scout are defaults; experimental editors and extra
scouts remain off.

### 2. Extractive eight-run candidate union — recommended next experiment

**Status:** implemented, fully preflighted offline, ungraded. Idealized
criterion ceiling `0.8284`; no achieved score.

**Behavior:** loads two to eight completed artifacts for the exact same qid and
request, anonymizes their origins, resolves every original citation to an
immutable document id, and asks one selector for ordered item ids. It copies
selected prose and citations exactly. The selector cannot write or edit prose.

The default eight already-paid source runs are, in anchor-first order:

1. `sol-aus-v2-research-first-pre-repair-dev30-20260806`;
2. `v2-dev30-default`;
3. `sol-aus-v2-research-first-dev30-20260806`;
4. `sol-aus-v2-adaptive-dev30-20260806`;
5. `v2-dev30-minimal`;
6. `sol-dev30-effort-max`;
7. `sol-dev30-tools`;
8. `sol-dev30-finish-the-claim`.

Safety rules preserve at least 60% of anchor items and 65% of anchor words,
require an explicit non-anchor contribution, preserve within-source order,
account for every selected item, and require each dropped anchor item to map to
selected replacements. Any protocol fault returns the complete anchor
byte-for-byte.

**Why it ranks first:** it uses already-paid complete outputs, avoids another
retrieval run and another lossy general writer, and directly targets the gap
between the `0.7508` whole-answer oracle and `0.8284` criterion union.

**Trade-off:** the cached oracle is in-sample and optimistic. Only a live
selector followed by the same full-30 three-repeat grade can measure it.

Zero-provider-call preflight:

```bash
PYTHONPATH=src:src/systems uv run --frozen --offline \
  --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py --all --prepare-only
```

Paid resumable selector, only after a new explicit total budget is authorized:

```bash
uv run --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py --all --skip-existing \
  --budget-cap <explicit-new-total-cap> --per-topic-reserve-usd 10
```

The preflight resolved 240 completed source artifacts over 30 topics. Packets
ranged from 57,917 to 83,531 characters and 142 to 287 immutable items, all
below the 140,000-character limit. No model-visible packet contains the token
`AUS` or a source run id.

### 3. Semantic-contract finish-the-claim pipeline

**Status:** implemented and hermetically verified, ungraded.

**Behavior:** uses an atomic mutable coverage ledger, source-verbatim local
quotes, complete value/scope invariants, and a mandatory terminal evidence
handoff. The same researcher submits the real typed answer. A fresh verifier
then receives one row, the relevant answer item or aggregate, and only its
eligible cited evidence.

The verifier separates closure, support, and distinct-count judgments. A clear
rejection permits one text-only correction by the same researcher. Item type,
citation ids, requirement ids, ordering, and unresolved rows are immutable.
Persistent rejection becomes `semantic_rejected`; an uncheckable second audit
becomes `semantic_unverified`. Neither is exported or resumed as completed.

**Use it when:** testing whether enforcing the commit-to-answer transition
improves a fresh research run, or when semantic correctness is more important
than minimizing provider calls.

**Trade-off:** it costs a complete research generation plus verifier calls, and
the verifier still needs production calibration. Offline tests establish
protocol behavior, not semantic accuracy or score.

Single-topic invocation:

```bash
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --backend openai --model openai.gpt-5.6-sol \
  --coverage-contract --observable-scout \
  --atomic-contract-plan --dynamic-contract-rows \
  --terminal-evidence-handoff --semantic-closure-verify \
  --prompt-variant contract-lean \
  --qid 683a58c9a7e7fe4e76958498 \
  --run-id <new-run-id>
```

Full-30 parallel invocation, only after explicit paid authorization:

```bash
RUN_PAID_EXPERIMENT=YES \
AUTHORIZED_TOTAL_BUDGET_USD=<explicit-new-total-cap> \
IN_FLIGHT_RESERVE_USD=<explicit-reserve> \
CONCURRENCY=6 \
tasks/task-comparison/scripts/run_aus_agent_v2_parallel.sh
```

`CONCURRENCY=6` means six independent topics in flight; completion and grading
still require all 30 topics.

### 4. Lean atomic mutable-ledger pipeline

**Status:** implemented and hermetically verified, ungraded.

**Behavior:** a 417-word Sol-specific prompt replaces the 2,541-word legacy
prompt. A typed 10–24-row atomic planner, independent observable scout,
dynamic evidence-backed rows, source-local claim/scope anchors, and mandatory
terminal handoff make the evidence state executable before drafting. It omits
the semantic verifier, so it isolates the value of better transport from the
value and risk of a model gate.

**Use it when:** the candidate union fails and the next question is whether a
fresh generation can preserve more evidence without semantic-verifier cost or
false rejection.

**Trade-off:** it costs a full new research run and has no measured score. Its
offline capacity estimates are not forecasts: the fixed current inventory
ceiling was `0.7457`, while optimistic dynamic-row capacity reached about
`0.8002–0.8016`.

Invocation is the semantic-contract command above with
`--semantic-closure-verify` omitted.

### 5. Executable coverage contract — retained building block

**Status:** implemented, ungraded, superseded as a direct recommendation by the
lean atomic ledger.

**Behavior:** assigns stable ids to plan/scout obligations, binds search and
commit actions to those ids, stores selective source-grounded claim/scope
anchors, and requires typed terminal answer items with eligible citations.

**Use it when:** debugging the ledger or running an ablation against the atomic
planner and terminal handoff. It should not be the first paid variant.

Ablation invocation:

```bash
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --backend openai --model openai.gpt-5.6-sol \
  --coverage-contract --observable-scout \
  --qid 683a58c9a7e7fe4e76958498 \
  --run-id <new-run-id>
```

## Variants not recommended for another paid run

| Variant | Reason |
| --- | --- |
| Prompt-only finish-the-claim | Failed Sol confirmation and increased severe penalties |
| Broad Markdown or “cite every item” | Author baselines do not use it; `cite-or-cut` was significantly harmful |
| Fresh whole-answer editor | Direct repair and subset rewrites lost coverage |
| Parallel facets | Full-30 score fell to `0.6773`; split researchers fragmented relationships |
| More reasoning effort | Sol max used 6.6× probe reasoning and did not improve quality |
| Fact/source/rank annotations stacked at commit | Crowded the commit turn and nearly doubled severe penalties |
| Coverage audit plus more search | Changed trajectory shape but not answer quality |
| Higher word cap | The model used four extra words; the cap was not binding |
| Whole-answer selector/router | Oracle ceiling `0.7508`, below target; earlier selector missed better candidates |
| Automatic neighbor pages | Changes evidence reach but is less direct than the demonstrated post-retrieval handoff loss |

## Recommended decision sequence

1. Keep the `0.704159` research-first system as the measured control.
2. If a new budget is ever authorized, run and grade the extractive candidate
   union first. It has the largest demonstrated content headroom and the lowest
   additional generation burden.
3. If union selection fails, inspect whether it failed from selector choice,
   word competition, duplication, or contradictions. Do not respond by adding
   a free-form writer.
4. Next run the lean atomic mutable ledger to isolate evidence transport in a
   fresh generation.
5. Add semantic closure only after calibrating reject precision on
   production-shaped, topic-disjoint packets; then compare the semantic variant
   with the same lean run, not with a different research architecture.
6. Promote nothing until all 30 outputs are complete and the unchanged
   three-repeat grading protocol finishes. Subset scores and oracle ceilings
   remain diagnostics.

## Evaluation command

After a genuinely complete authorized run, use the fixed three-repeat grader:

```bash
PYTHONPATH=src uv run --group aus-agent python \
  tasks/task-comparison/scripts/rubric_eval.py \
  --run-id <complete-run-id> --variant <unique-variant-name> --repeats 3
```

The generation and grading artifacts, not this summary, are authoritative for
any future score claim.

## Final verification state

The final implementation commit before this summary was `eec616c4`. Its full
hermetic repository suite passed `1,787` tests with eight live tests deselected,
zero skips, and one existing deprecation warning in `17.35s`. The architecture
visualization was regenerated and its freshness check passed.

The original `aus_agent` was kept at its base behavior plus the UTC/neutral
identity fix. Architecture changes live under `src/systems/aus_agent_v2/`.
No experiment or grader process remained running at handoff.
