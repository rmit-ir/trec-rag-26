# aus_agent_v2 executable-claim and answer-form hardening

Date: 2026-08-06

## Outcome

This session hardened the ungraded `aus_agent_v2.run_contract_one` candidate
without changing the fully graded `aus_agent_v2.run_one` control or the
original `aus_agent` system.

No provider, search, Bedrock, OpenAI, or grader call was made. The corrected
cumulative optimization spend remains **$1,096.72**, already above the
operator's $300 total cap. Consequently this work establishes offline protocol
correctness, not a new rubric score; 0.8 remains unverified.

The candidate now has three executable properties that the previous prompt
arms lacked:

1. every planner row survives optional Markdown-bold labels;
2. a committed claim anchor selects material, boundary-matched source-verbatim
   terms that also occur in its declared claim or scope, and final cited prose
   cannot close that obligation unless it repeats every selected term from at
   least one cited mapped anchor;
3. raw Python is authorized only when the untouched request explicitly asks
   for Python code, bypasses prose/Markdown/citation parsing, retains multiline
   whitespace, and must parse as Python before organizer output is accepted.

Plain repeated-part labels are similarly request-gated for a literal blog-post
series. No general heading, table, list, Markdown, or arbitrary structured-
content capability was added. This follows the author-baseline evidence:

| Baseline | Answers | Markdown headings | Tables |
|---|---:|---:|---:|
| base-agentic-bm25 | 119 | 0 | 1 |
| base-singlepass | 119 | 2 | 1 |

## Why this was necessary

### Three primary plans were silently erased

The initial contract parser accepted `1. DELIVERABLE:` but not the equally
valid planner output `1. **DELIVERABLE:**`. In the frozen best 30-topic run,
three topics used the latter form:

| QID suffix | Topic | Real planner rows | Parsed before | Parsed now |
|---|---|---:|---:|---:|
| `60535d` | autonomous-agent regulation | 11 | 0 | 11 |
| `60542d` | Mahabharata politics | 12 | 0 | 12 |
| `60547f` | duties to digital minds | 12 | 0 | 12 |

Before the fix those topics retained only eight scout rows. Their deliverable,
audience, definition, explicit/implied scope, evidence, safety, and budget rows
were absent from the executable contract.

The pre-change audit contains the complete 30-topic matrix:
[`2026-08-06-aus-agent-v2-coverage-contract-audit-before.log`](assets/2026-08-06-aus-agent-v2-coverage-contract-audit-before.log).

### Fact extraction had no enforced consumer

The earlier facts arm extracted 876 claim/value/scope/source records but final
answers remained effectively unchanged. The first coverage-contract version
improved routing—it connected requirement → search → commit → answer—but a
final sentence could still tag a row and cite a mapped document without using
the selected concrete fact.

The new commit annotation requires `must_include`, one to four exact names,
values, dates, populations, or scope qualifiers. Generic fragments such as
`reported` are rejected; literals must be material, match token boundaries,
and occur in the declared claim or scope. The harness then checks both
directions:

```text
source document contains every selected literal
              ↓
commit anchor(requirement_id, document_id, claim, scope, must_include)
              ↓
final cited prose repeats every literal from one cited mapped anchor
```

This is deliberately narrower than semantic entailment. It proves a selected
fact survived the pipeline and remained source-local; it does not claim that
substring matching proves the whole sentence true. The model still owns claim
selection and synthesis.

### The pipeline destroyed runnable code the model had already written

The exact tested request was:

> Design a modified U-Net architecture to perform instance segmentation on
> noisy fluorescence microscopy images with overlapping cells or organelles.
> Describe the U-Net variant used (e.g., attention, residual, or
> transformer-based) and justify the architectural choices. Explain the loss
> functions and postprocessing techniques used to separate touching objects.
> Include Python code for key components (e.g., model, loss). Compare your
> approach to 2–3 existing models (e.g., Cellpose, Stardist, Mask R-CNN).

Frozen input artifact:
`data/outputs/aus_agent_v2/20260807T002205962434+1000.pre_repair_counterfactual.output.json`,
run id `sol-aus-v2-research-first-pre-repair-dev30-20260806`, QID
`6847465956a0f6376a6053ca`, raw generation `step-0039`.

Sol supplied three syntactically valid Python payloads for the model, loss,
and decoder. The ordinary prose projection then:

- treated `__init__` and paired `*` operators as Markdown emphasis;
- collapsed indentation;
- treated Python bracket expressions such as `[0]` as citation markers.

The complete offline replay is reproducible with:

```bash
PYTHONPATH=src/systems:src uv run --no-project python \
  worklogs/assets/2026-08-06-aus-agent-v2-python-projection-replay.py
```

Full result:
[`2026-08-06-aus-agent-v2-python-projection-replay.log`](assets/2026-08-06-aus-agent-v2-python-projection-replay.log).

| Block | Raw Sol draft | Old strict answer |
|---|---|---|
| model | parses | indentation failure |
| loss | parses | invalid syntax |
| decoder | parses | parses, but `[0]` was deleted and semantics changed |

The combined raw code parses. The new typed terminal accepted it, retained it
byte-for-byte, and did not mistake code indexing for citations.

The already-paid three-pass score for this topic was 0.7980769. All three
cached judges marked the +4 runnable-code criterion missing while separately
recognizing that model and loss code were present. If code preservation alone
caused that one criterion to become satisfied, the frozen verdict arithmetic
would be 0.8750 for this topic. That is a counterfactual calculation, not a new
grade and not a full-30 score claim.

## Final 30-topic offline audit

The final script reads the exact saved run artifacts, applies the current
contract and untouched-query form gate, and prints the full matrix followed by
JSONL containing every exact query, plan, scout addition, and answer used:

```bash
PYTHONPATH=src/systems:src uv run --no-project python \
  worklogs/assets/2026-08-06-aus-agent-v2-coverage-contract-audit.py
```

Script:
[`2026-08-06-aus-agent-v2-coverage-contract-audit.py`](assets/2026-08-06-aus-agent-v2-coverage-contract-audit.py).
Full matrix and raw inputs:
[`2026-08-06-aus-agent-v2-coverage-contract-audit.log`](assets/2026-08-06-aus-agent-v2-coverage-contract-audit.log).

| Measure | Before | After |
|---|---:|---:|
| total contract rows | 546 | 584 |
| mean rows/topic | 18.20 | 19.47 |
| range | 8–21 | 17–21 |
| must-answer rows | 508 | 543 |
| must-research rows | 437 | 463 |
| planner rows erased | 35 across 3 topics | 0 |
| deterministic Python form rows | 0 | 1 |
| deterministic series-label rows | 0 | 2 |

Request-form cues across the 30 exact requests were: explicit Python code 1,
literal blog-post series 2, literal table request 0, and literal section cue 2.
This is why the implementation grants only raw Python and plain series labels,
not broad Markdown or tables.

The saved winner already averaged 912.9 answer words and ranged from 752 to
1,022. The final contract now has 16–20 must-answer rows/topic, so validation
remains feasible under the 1,024-word hard cap but leaves little room for
duplicative prose. Untagged synthesis items remain allowed.

## Implementation

- `src/systems/aus_agent_v2/answer_form.py`
  - infers a narrow policy from the untouched request;
  - authorizes Python only for explicit Python-code/implementation wording;
  - authorizes at least three numbered plain labels only for a literal
    blog-post series, honoring an explicit requested count;
  - emits a contract-candidate-only system addendum.
- `src/systems/aus_agent_v2/coverage_contract.py`
  - accepts bold or plain planner labels;
  - adds stable `Fxx` request-form rows;
  - changes terminal input from misleading `sentences` to typed
    `answer_items` (`prose`, `label`, `code`);
  - preserves raw Python, rejects fences/NULs and oversized payloads rather
    than truncating them, and validates it with non-executing
    `compile(..., "exec")`;
  - rejects code and labels unless request-authorized;
  - requires commit anchors to carry material source-verbatim `must_include`
    terms tied to their declared claim/scope;
  - proves those boundary-matched terms occur in the staged source and final
    mapped prose.
- `src/systems/aus_agent_v2/agent.py`
  - installs the request-conditioned terminal schema and system addendum;
  - passes the form policy through contract construction and submission;
  - records the policy in trace input and summary.
- `src/systems/aus_agent_v2/pipeline.py`
  - keeps `run_one` unchanged as the verified 0.7042 control;
  - visualizes the separate request-form/terminal-contract candidate.
- tests cover parser survival, source-bound claim terms, answer carry-through,
  form gating, invalid Python, indentation/operator/bracket preservation,
  series labels, and organizer end-to-end multiline output.

The original `aus_agent` prompt remains untouched and the v2 model-facing base
prompt still begins “You are a research agent”; no Australian identity or
locale is introduced.

## Verification

Focused tests:

```bash
bash scripts/test.sh \
  tests/aus_agent_v2/test_coverage_contract.py \
  tests/systems/test_aus_agent_v2.py
```

Result: 43 passed, one live test deselected.

Final full hermetic suite:

```bash
bash scripts/test.sh 2>&1 | tee \
  worklogs/assets/2026-08-06-aus-agent-v2-answer-form-full-tests.log
```

Result: **1,693 passed, eight live tests deselected, zero failures/skips** in
17.14 seconds. Raw log:
[`2026-08-06-aus-agent-v2-answer-form-full-tests.log`](assets/2026-08-06-aus-agent-v2-answer-form-full-tests.log).

Architecture regeneration/open:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open
```

Result: six systems, 18 shared edges, five engines. Raw log:
[`2026-08-06-aus-agent-v2-answer-form-architecture.log`](assets/2026-08-06-aus-agent-v2-answer-form-architecture.log).

`docs/auto-optimize/progress.svg` was regenerated with the corrected cumulative
spend and full-30-only bars:

```bash
uv run --no-project python \
  tasks/task-comparison/scripts/rubric_plot.py --spent 1096.72
```

Raw log:
[`2026-08-06-aus-agent-v2-answer-form-progress.log`](assets/2026-08-06-aus-agent-v2-answer-form-progress.log).

## Paid verification still required

The objective is a measured full-30 score of at least 0.8. Offline correctness
cannot prove it. A comparable three-pass full-30 grade remains the acceptance
gate; subset scores cannot be compared with the leaderboard.

The following must not run under the exhausted $300 total cap. When the
operator explicitly creates a fresh paid budget window, generation should use
`run_contract_one`/`--coverage-contract` on all 30 topics, monitor cumulative
spend continuously, stop before that newly authorized cap, and then grade all
30 with the same frozen Sol judge and three repeats.
