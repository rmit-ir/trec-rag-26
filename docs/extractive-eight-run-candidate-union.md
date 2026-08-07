# Extractive Eight-Run Candidate Union Runbook

This runbook describes how to build the final extractive union over eight
complete answers for each **test topic**. It does not run or grade the 30-topic
development set.

The runnable CLI is
`src/systems/aus_agent_v2/union_run.py`. It spends nothing on retrieval or
answer generation: those eight source runs must already exist. A live union run
uses one fresh selector per topic and saves normal strict and rich RAG
artifacts.

## Important test-topic rule

The CLI defaults to the development-topic TSV. Therefore every test-topic
command in this runbook must include:

```bash
--topics <TEST_TOPICS_TSV>
```

`<TEST_TOPICS_TSV>` must contain one `qid<TAB>narrative` row per test topic.
With that option, `--all` means all rows in the supplied test-topic file—not the
30 development topics.

No test-topic file is currently present under `data/official/`; replace the
placeholder after the organizer releases or supplies it.

## Required source artifacts

Place every rich `*.output.json` under the standard data tree:

```text
data/outputs/<system-name>/
```

For every test topic, the eight source artifacts must have:

- eight unique, non-empty `metadata.run_id` values;
- the same `metadata.narrative_id` as the topic TSV;
- a `metadata.narrative` exactly matching that TSV row;
- `trace.status == "completed"`;
- valid organizer references, answer items, and citations; and
- exactly one complete artifact for each `(run_id, qid)` pair.

The union scanner searches `data/outputs/*/*.output.json`. Duplicate complete
artifacts with the same run id and topic are rejected rather than selected
arbitrarily.

Choose the strongest independently validated source run as the anchor. The
anchor must be one of the eight `--candidate-run` values.

## Current selection contract

The current `candidate-union-v1` implementation selects immutable organizer
answer items. It never rewrites, joins, splits, or paraphrases their text. The
harness remaps their original document citations deterministically.

A valid union must:

- select at least one item from a non-anchor run;
- retain at least 60% of the anchor's items and 65% of its words;
- account for every omitted anchor item with selected non-anchor replacements;
- preserve each source run's relative item order;
- account for every selected item in a request-coverage row;
- remain at or below 1,024 words; and
- pass the normal RAG output and citation validators.

Any provider or protocol failure returns the exact anchor answer. Consequently,
a completed output is not automatically evidence that a union was accepted;
inspect the union trace as described below.

Before paid execution, inspect several prepared packets. If answer items split
claims from their necessary qualifiers, values, or scope, upgrade v1 to
citation-closed claim spans before running the selector.

## Reusable source arguments

Use the eight actual run ids and the best run as the anchor:

```bash
CANDIDATE_ARGS=(
  --candidate-run <RUN_1>
  --candidate-run <RUN_2>
  --candidate-run <RUN_3>
  --candidate-run <RUN_4>
  --candidate-run <RUN_5>
  --candidate-run <RUN_6>
  --candidate-run <RUN_7>
  --candidate-run <RUN_8>
  --anchor-run <BEST_RUN>
)
```

## 1. Validate one test topic without a model call

This constructs the exact anonymous selector packet and validates all eight
source artifacts. `--prepare-only` never creates a provider:

```bash
uv run --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py \
  --topics <TEST_TOPICS_TSV> \
  --qid <TEST_QID> \
  --prepare-only \
  "${CANDIDATE_ARGS[@]}"
```

Review the reported request size, total candidate items, anchor words, and the
actual packet contents before proceeding.

## 2. Prepare every test-topic packet without a model call

```bash
uv run --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py \
  --topics <TEST_TOPICS_TSV> \
  --all \
  --prepare-only \
  --packet-output \
    data/outputs/aus_agent_v2/test-candidate-union-packets.jsonl \
  "${CANDIDATE_ARGS[@]}"
```

This must succeed for every test topic before paid execution. The packet file
is a reproducibility artifact under `data/`, not source code.

## 3. Run one paid selector smoke test

Use a representative test topic to verify provider/tool behavior and artifact
creation. This does not reveal a test score; it is only an operational check.

```bash
uv run --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py \
  --topics <TEST_TOPICS_TSV> \
  --qid <TEST_QID> \
  --backend openai \
  --model openai.gpt-5.6-sol \
  --run-id <TEST_UNION_RUN_ID> \
  --budget-cap <AUTHORIZED_ABSOLUTE_TOTAL_CAP> \
  --per-topic-reserve-usd 10 \
  "${CANDIDATE_ARGS[@]}"
```

The budget cap is an **absolute cumulative optimization cap**, not a new
allowance for this command. The historical ledger already exceeds $300, so a
`--budget-cap 300` invocation correctly refuses before provider creation. Do
not raise the cap without explicit authorization for a new absolute total.

## 4. Run all test topics resumably

After the preparation and smoke test succeed:

```bash
uv run --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py \
  --topics <TEST_TOPICS_TSV> \
  --all \
  --skip-existing \
  --backend openai \
  --model openai.gpt-5.6-sol \
  --run-id <TEST_UNION_RUN_ID> \
  --budget-cap <AUTHORIZED_ABSOLUTE_TOTAL_CAP> \
  --per-topic-reserve-usd 10 \
  "${CANDIDATE_ARGS[@]}"
```

`--skip-existing` makes an interrupted batch resumable by skipping test topics
already completed under the same union run id. The budget gate is checked again
before every selector call.

## 5. Inspect acceptance and fallback behavior

Union artifacts are written under:

```text
data/outputs/aus_agent_v2/
```

For each rich output, inspect:

```text
trace.summary.candidate_union
```

The important fields are:

- `accepted: true` — an actual multi-run union passed validation;
- `fallback` — why the exact anchor was returned instead;
- `errors` — protocol or validation failures;
- `selected_items` and `answer_words` — final size;
- `candidate_runs` and `anchor_run` — source provenance;
- `coverage_accounting` — selected-item coverage rows; and
- `anchor_replacements` — explicit accounting for dropped anchor items.

Do not treat an anchor fallback as a successful union. Before submission,
verify that every expected test qid has exactly one completed output under the
intended union run id and separately export/validate it through the repository's
normal submission workflow.

## What the selector is and is not doing

For each test topic, the data flow is:

```text
8 complete same-topic outputs
        ↓
anonymous immutable answer items + original docids
        ↓
one selector chooses item ids and coverage accounting
        ↓
deterministic byte-for-byte assembly and citation remapping
        ↓
word-limit, provenance, anchor-retention, and RAG validation
        ↓
accepted union, or exact anchor fallback
```

The selector does not search ClimbMix, generate replacement prose, introduce
headings or tables, or repair claims. Any future citation-closed claim-span
upgrade must preserve this same immutable-selection and fail-closed boundary.
