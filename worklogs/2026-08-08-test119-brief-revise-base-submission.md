# Test119 submission: brief_revise_agent (base cell)

Date: 2026-08-08

## Config

Base cell from the factorial analysis (`worklogs/2026-08-07-brief-revise-agent-llm-factorial-design.md`
§4, `br-model-main-sol-exp15-b1`): `gpt-5.6-sol` generator, default
`semantic,keyword` retrieval engines, `k=10`, round-B structure (adjacent-page
fetch ON, current code defaults for every other structural toggle), `luna`
brief-analyst/reviewer. Ties `aus_agent_v2` on this repo's own standalone
rubric (2.267 both) at roughly 1/50th the tracked build cost -- report §10.3's
rationale for including it.

```bash
export OPENAI_API_KEY="$(grep '^AZURE_OPENAI_API_KEY=' .env | cut -d= -f2-)"
SYSTEM=brief_revise_agent RUN_PY=src/systems/brief_revise_agent/run.py \
UV_GROUP=brief-revise-agent \
EXTRA_ARGS="--backend openai --model gpt-5.6-sol" \
CONCURRENCY=6 \
bash tasks/task-comparison/scripts/run_test119_generic_parallel.sh \
  brief-revise-base-test119-20260808
```

## Input

`data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv`,
119 rows (`rag2026-0`..`rag2026-118`), SHA-256
`72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c` -- same
frozen input used for the already-submitted `aus_agent`/`aus_agent_v2` runs
(`worklogs/2026-08-07-test119-production-runs.md`).

## Execution

Not a clean single pass: 3 launches were needed, all resuming the same
`--run-id` (artifacts already `trace.status=completed` are skipped, so
resuming is safe and free of duplicate work):

1. Concurrency 6, launched alongside `brief-revise-hybrid` and `facets_agent`
   simultaneously (3 OpenAI-backed jobs at once, `gpt-5.6-sol`/`gpt-5.6-luna`
   sharing the same `westus` Azure OpenAI quota) -- 43/119 completed, 76
   failed with `openai.RateLimitError: 429` after exhausting the client's own
   retry budget.
2. Resumed at concurrency 3 (alongside `brief-revise-hybrid` at concurrency
   3, `facet_rag` unaffected on a separate Bedrock quota) -- 96/119, 23 still
   failing on 429s even at the lower combined load.
3. Resumed at concurrency 2, run alone (not concurrent with the hybrid
   variant this time) -- **119/119 completed**, 0 failures.

Lesson for future test119 batches: this shared OpenAI quota cannot sustain
more than roughly one system's worth of concurrency-6 traffic at a time --
run OpenAI-backed systems serially, or at combined concurrency well under 6,
not naively in parallel.

## Result

119/119 topics completed. References/topic 5-43 (mean 25.8); words/topic
554-1007 (mean 830.2, all within the 1024-word cap); mean 26.4 search calls,
mean 327,585 processed tokens/topic.

## Cost

No real OpenAI rate card in this repo for `gpt-5.6-*` (placeholder \$5/1M
blended, likely an underestimate -- see report §7's caveat). Estimated
**\$1.638/topic, \$194.91 for the full 119-topic run**.

## Validation

- `validate_rag_output` (this repo's own contract check): 0 violations.
- `autojudge_base.report_tool check --spec rag26` (third-party TREC AutoJudge
  verifier, github.com/trec-auto-judge/auto-judge-base): caught a real gap
  the internal check misses -- `rag26`'s `run_id_max_len=20` (NIST run-tag
  convention). This repo's internal run_ids are intentionally long/
  descriptive (`brief-revise-base-test119-20260808` = 35 chars) for
  bookkeeping across many experiment cells, so `scripts/export-rag-submission.py`
  gained an `--output-run-id` flag that rewrites the emitted tag only,
  leaving internal artifacts/resume-tracking untouched. Organizer-facing tag:
  **`brief-base-t119`** (15 chars). Final check: **119/119 valid against
  rag26**.

## Artifacts

- `data/outputs/submissions/brief-base-t119/rag_output_trec_rag_2026.jsonl`
  (119 rows, SHA-256
  `291765f4665301330afdf013b30a78c7a36942345c0a1d7c15415d4196d1ddc3`)
- Internal artifacts: `data/outputs/brief_revise_agent/*.output.json`,
  `metadata.run_id=brief-revise-base-test119-20260808`.
- Launch logs: `tasks/task-comparison/logs/brief-revise-base-test119-20260808.launch.log`.
