# Run the verified research-first control on the 2026 test topics

This runbook produces the official 119-topic test run for the promoted
`aus_agent_v2` research-first control. Its development result was `0.704159`;
that score describes the fixed 30-topic development evaluation and is not a
claim about unseen test performance.

The control uses an isolated prose coverage plan, a request-only atomic
obligation scout, and one evidence-owning research conversation that searches,
commits evidence, and writes the cited answer. It does not run a post-draft
editor, coverage verifier, contract ledger, semantic closure pass, or candidate
union.

## Inputs and prerequisites

Run every command from the repository root. The official input is:

```text
data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv
```

It must contain 119 rows (`rag2026-0` through `rag2026-118`) and have SHA-256:

```text
72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c
```

The root `.env` must provide the OpenAI-compatible gateway credentials and the
semantic/keyword ClimbMix search credentials. Never put their values in logs,
docs, output metadata, or the submission file.

## Run steps

1. Check the official test TSV count and checksum.
2. Regenerate and open `docs/architecture.html#aus_agent_v2`; select the
   **Verified research-first control** branch.
3. Run one preflight topic under a preflight-only run id.
4. Inspect its rich `*.output.json` trace. Require `status=completed`, enabled
   `coverage_plan` and `plan_critic`, disabled optional editor/contract stages,
   successful search and commit calls, at least one committed reference, a
   non-empty cited answer, and zero `validate_rag_output` violations.
5. Run all 119 topics. The parallel runner treats topics as independent,
   launches ten at a time, and resumes only topics whose matching artifact has
   `trace.status=completed`.
6. Export exactly that run id in official TSV order. The exporter requires one
   valid artifact for every official narrative and strips `trace`.

## Preflight command

```bash
set -o pipefail
UV_CACHE_DIR=/tmp/trec-rag-uv-cache-20260807 \
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --qid rag2026-0 \
  --topics data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv \
  --backend openai --model openai.gpt-5.6-sol \
  --search-backends semantic,keyword \
  --k 20 --context-token-budget 500000 \
  --safety-max-rounds 40 --max-committed-per-step 10 \
  --coverage-plan --coverage-scout --plan-critic-additions 8 \
  --no-compact-scout-plan --no-observable-scout \
  --no-plan-reconcile --no-coverage-verify \
  --no-audience-verify --no-finish-review --no-answer-blueprint \
  --no-coverage-contract --no-atomic-contract-plan \
  --no-dynamic-contract-rows --no-terminal-evidence-handoff \
  --no-semantic-closure-verify --prompt-variant default \
  --run-id preflight-sol-aus-v2-research-first-test119-20260807 \
  2>&1 | tee /tmp/preflight-sol-aus-v2-research-first-test119-20260807.log
```

## Complete run command

```bash
set -o pipefail
UV_CACHE_DIR=/tmp/trec-rag-uv-cache-20260807 \
TOPICS=data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv \
BACKEND=openai \
MODEL=openai.gpt-5.6-sol \
ENGINES=semantic,keyword \
CONCURRENCY=10 \
LOG=tasks/task-comparison/logs/sol-aus-v2-research-first-test119-20260807.log \
bash tasks/task-comparison/scripts/run_aus_agent_v2_control_parallel.sh \
  sol-aus-v2-research-first-test119-20260807 \
  2>&1 | tee /tmp/sol-aus-v2-research-first-test119-20260807.launch.log
```

Rerun the identical command to fill only missing or failed topics. Monitor it
with:

```bash
tail -f tasks/task-comparison/logs/sol-aus-v2-research-first-test119-20260807.log
```

## Saved artifacts and organizer export

Rich organizer-plus-trace files and strict trajectories are saved as:

```text
data/outputs/aus_agent_v2/<timestamp>.<slug>.output.json
data/outputs/aus_agent_v2/<timestamp>.<slug>.trajectory.json
```

Both carry `metadata.run_id=sol-aus-v2-research-first-test119-20260807`; the
run id, not the filename, identifies membership in this run.

Create the separate trace-free submission folder and official JSONL with:

```bash
uv run --no-project python scripts/export-rag-submission.py \
  data/outputs/aus_agent_v2 \
  --run-id sol-aus-v2-research-first-test119-20260807 \
  --topics data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv \
  --output data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl
```

The final file must contain exactly 119 single-line JSON objects, in official
topic order, with only the top-level `metadata`, `references`, and `answer`
fields.

## Completed production run

The 2026-08-07 production execution completed all 119 topics without a failed
attempt. Its organizer file is:

```text
data/outputs/submissions/sol-aus-v2-research-first-test119-20260807/rag_output_trec_rag_2026.jsonl
```

SHA-256: `744c2d0624a1b834b94ad87fbc50548b1957f22a09beb1903230da72fe4986d8`.
The file is 1,114,270 bytes. Validation found 119 unique official IDs, exact
narratives and ordering, no top-level traces, and no format violations.
