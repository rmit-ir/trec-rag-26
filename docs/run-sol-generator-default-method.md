# Run the Sol generator with the default AUS method on the 2026 test topics

This runbook produces the official 119-topic test run for the original
`aus_agent` default method using `openai.gpt-5.6-sol`. The same configuration
scored `0.6508` on the fixed 30-topic development evaluation. That development
score is configuration evidence, not an estimate of test performance.

The method is one continuous staged-context conversation. It plans internally,
searches the semantic and keyword indexes, commits selected evidence, closes
coverage gaps, and writes line-per-sentence cited prose. Unlike the verified
`aus_agent_v2` control, it has no isolated coverage-plan or atomic-scout calls.

## Inputs and prerequisites

Run every command from the repository root. The official test input is:

```text
data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv
```

It must contain 119 rows (`rag2026-0` through `rag2026-118`) and have SHA-256
`72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`.
The root `.env` supplies the OpenAI-compatible gateway and ClimbMix search
credentials; do not copy secrets into commands, logs, metadata, or exports.

## Run steps

1. Check the official test TSV count and checksum.
2. Regenerate and open `docs/architecture.html#aus_agent`.
3. Run `rag2026-0` under a preflight-only run id.
4. Inspect the rich trace. Require `status=completed`, no v2 plan/scout/editor
   stages, successful search and commit calls, at least one committed reference,
   a non-empty cited answer, and zero `validate_rag_output` violations.
5. Run all 119 topics with ten independent topics in flight. Reusing the run id
   resumes from artifacts whose trace status is completed.
6. Export only the production run id, require exact test-topic coverage and
   narrative text, order it by the official TSV, and strip `trace`.

## Preflight command

```bash
set -o pipefail
UV_CACHE_DIR=/tmp/trec-rag-uv-cache-20260807 \
uv run --group aus-agent python src/systems/aus_agent/run.py \
  --qid rag2026-0 \
  --topics data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv \
  --backend openai --model openai.gpt-5.6-sol \
  --search-backends semantic,keyword \
  --k 20 --context-token-budget 500000 \
  --safety-max-rounds 100 --max-committed-per-step 20 \
  --prompt-variant default \
  --run-id preflight-sol-aus-default-test119-20260807 \
  2>&1 | tee /tmp/preflight-sol-aus-default-test119-20260807.log
```

## Complete run command

```bash
set -o pipefail
UV_CACHE_DIR=/tmp/trec-rag-uv-cache-20260807 \
TOPICS=data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv \
BACKEND=openai \
MODEL=openai.gpt-5.6-sol \
ENGINES=semantic,keyword \
K=20 \
MAXCOMMIT=20 \
CONCURRENCY=10 \
RUN_AUS_AGENT_CONTEXT_TOKEN_BUDGET=500000 \
RUN_AUS_AGENT_SAFETY_MAX_ROUNDS=100 \
bash tasks/task-comparison/scripts/run_topics_parallel.sh \
  default sol-aus-default-test119-20260807 \
  2>&1 | tee /tmp/sol-aus-default-test119-20260807.launch.log
```

Rerun the identical command to fill missing or failed topics. Monitor the
durable per-run log with:

```bash
tail -f tasks/task-comparison/logs/sol-aus-default-test119-20260807.log
```

## Saved artifacts and organizer export

Rich organizer-plus-trace files and strict trajectories are saved as:

```text
data/outputs/aus_agent/<timestamp>.<slug>.output.json
data/outputs/aus_agent/<timestamp>.<slug>.trajectory.json
```

Membership is identified by
`metadata.run_id=sol-aus-default-test119-20260807`. Export the separate official
submission file with:

```bash
uv run --no-project python scripts/export-rag-submission.py \
  data/outputs/aus_agent \
  --run-id sol-aus-default-test119-20260807 \
  --topics data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv \
  --output data/outputs/submissions/sol-aus-default-test119-20260807/rag_output_trec_rag_2026.jsonl
```

The final JSONL must have exactly 119 rows and only `metadata`, `references`,
and `answer` at the top level. The internal timestamped files retain their
traces for auditing and must not be submitted directly.

## Completed production run

The 2026-08-07 initial queue completed 117 topics. `rag2026-55` and
`rag2026-112` each received a gateway-side `400 validation_error` whose message
was `Internal server error`; rerunning the identical resumable command selected
only those two topics and both completed. The failed attempts remain in the
internal directory for audit, and the run-id-aware exporter ignores them only
because completed replacements exist and all 119 official topics pass its
coverage gate.

The organizer file is:

```text
data/outputs/submissions/sol-aus-default-test119-20260807/rag_output_trec_rag_2026.jsonl
```

SHA-256: `d6fcf2c14bb48dfc3f7476032ecf79c6d2704664434266efabe383dcace10fc5`.
The file is 1,049,984 bytes. Validation found 119 unique official IDs, exact
narratives and ordering, no top-level traces, and no format violations.
