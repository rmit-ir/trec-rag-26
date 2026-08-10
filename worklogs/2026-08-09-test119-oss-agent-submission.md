# Test119 submission: oss_agent (open-weight-only, glm-5 default)

Date: 2026-08-09/10

## Config

The plain baseline confirmed best after a full Tier-2 exploration round
(`worklogs/2026-08-09-oss-agent-open-weight-system.md`): `zai.glm-5` in
every role (main writer, brief analyst, blind scout, reviewer), `hybrid`-
only retrieval, adjacent-page augmentation on (S5), blind scout on (S14),
unmodified `review.hook` grading brief requirements only -- i.e. every
current default in `src/systems/oss_agent/agent.py`, no non-default
flags. Standalone rubric score on the 15-topic dev subset: **1.467/3**,
replicated at 1.333 on an independent 15-topic set. Every model call in
the pipeline is open-weight (`agent.ALLOWED_MODELS`/`_check_model`
enforced) -- no proprietary model anywhere in generation.

```bash
SYSTEM=oss_agent RUN_PY=src/systems/oss_agent/run.py \
UV_GROUP=oss-agent \
EXTRA_ARGS="--model zai.glm-5" \
CONCURRENCY=6 \
bash tasks/task-comparison/scripts/run_test119_generic_parallel.sh \
  oss-agent-glm5-test119-20260809
```

## Input

`data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv`,
119 rows (`rag2026-0`..`rag2026-118`) -- same frozen input every other
system's test119 run in this repo used.

## Execution

Two launches, both resuming the same `--run-id` (the generic runner
skips anything already `trace.status=completed`):

1. Concurrency 6, pure Bedrock (no shared-OpenAI-quota contention the
   earlier `gpt-5.6-*` systems hit) -- 117/119 completed, 2 failed with
   the same transient shared-harness `KeyError: 'tooluse_...'` seen
   during this system's own dev-set bake-off (a pre-existing
   `agent_harness.agent` edge case on certain non-Anthropic tool-call id
   formats, not `oss_agent`'s own code -- see
   `worklogs/2026-08-09-oss-agent-open-weight-system.md`'s "What's left
   open" section).
2. Resumed at concurrency 2, both remaining topics (`rag2026-39`,
   `rag2026-77`) -- **119/119 completed**, 0 failures.

## Result

119/119 topics completed. References/topic 1-40 (mean 15.9); words/topic
21-1005 (mean 754.0, within the 1024-word cap). Two topics
(`rag2026-65`, `rag2026-103`) finished with unusually short answers
(21 and 29 words) -- checked directly: both are genuine, real completions
(`trace.status=completed`, no error, no forced safety-backstop
truncation), not a technical failure -- glm-5 simply wrote very little
for those two topics. Format-valid either way (single cited sentence,
no `validate_rag_output` violations); not retried, since a retry has no
guaranteed different outcome and every other system's own test119 log in
this repo reports a similarly wide per-topic range without excluding the
short end.

Mean 12.7 search calls/topic, mean 420,979 processed tokens/topic.

## Cost

Real metered Bedrock rate (not the OpenAI-backend placeholder the
`gpt-5.6-*` systems' figures use): **\$0.163/topic, \$19.35 for the full
119-topic run** -- roughly 1/10th `brief_revise_agent`'s own \$1.638/
topic test119 figure, and well inside the project's remaining budget.

## Validation

`validate_rag_output` (this repo's own contract check): **0 violations,
119/119 valid.** The third-party `autojudge_base` verifier other
systems' test119 worklogs also ran is not set up on this machine (not
under `tmp/`, not pip-installed) -- not run here. Organizer-facing run
tag rewritten via `--output-run-id` to satisfy the `rag26` spec's
`run_id_max_len=20` convention (internal `run_id`,
`oss-agent-glm5-test119-20260809`, is 32 chars, kept for internal
bookkeeping only): **`oss-glm5-t119`** (13 chars).

```bash
uv run --group aus-agent python scripts/export-rag-submission.py \
  data/outputs/oss_agent \
  --run-id oss-agent-glm5-test119-20260809 \
  --output-run-id oss-glm5-t119 \
  --topics data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv \
  --output data/outputs/submissions/oss-glm5-t119/rag_output_trec_rag_2026.jsonl
```

`wrote 119 rows`, `ignored 2 superseded failed attempt(s)` (the two
`KeyError` attempts from the first launch, correctly excluded in favor
of their successful retries by the exporter's own dedup-by-latest-
completed logic).

## Artifacts

- `data/outputs/submissions/oss-glm5-t119/rag_output_trec_rag_2026.jsonl`
  (119 rows, SHA-256
  `a227e8784446d1233825ec822f1a12136b08fb36f173c7f6d456be1b71ced257`)
- Internal artifacts: `data/outputs/oss_agent/*.output.json`,
  `metadata.run_id=oss-agent-glm5-test119-20260809`.
- Launch log: `tasks/task-comparison/logs/oss-agent-glm5-test119-20260809.log`.
