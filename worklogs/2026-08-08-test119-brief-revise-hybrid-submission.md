# Test119 submission: brief_revise_agent (hybrid-alone engine)

Date: 2026-08-08

## Config

Same as the base cell (`gpt-5.6-sol`, `k=10`, round-B structure, `luna`
brief-analyst/reviewer) except retrieval engine set is `hybrid` only, not the
default `semantic,keyword` pair (`br-enginesweep-hybrid-exp15` in the
factorial analysis). Best-scoring cell on standalone rubric in the whole
factor-analysis report (2.333, +0.067 over base, replicated on a second
15-topic set) -- but **arena-confirmed worse than the base cell**
head-to-head against `aus_agent_v2` (33.3% vs 40% win rate,
`worklogs/2026-08-07-brief-revise-agent-llm-factorial-design.md` §25/§26).
Included per report §10.3 as the hedge on the standalone/nugget-rubric axis
specifically, not because it is the stronger system overall.

```bash
export OPENAI_API_KEY="$(grep '^AZURE_OPENAI_API_KEY=' .env | cut -d= -f2-)"
SYSTEM=brief_revise_agent RUN_PY=src/systems/brief_revise_agent/run.py \
UV_GROUP=brief-revise-agent \
EXTRA_ARGS="--backend openai --model gpt-5.6-sol --search-backends hybrid" \
CONCURRENCY=6 \
bash tasks/task-comparison/scripts/run_test119_generic_parallel.sh \
  brief-revise-hybrid-test119-20260808
```

## Input

Same frozen 119-row official test TSV as every other test119 run this
session, SHA-256 `72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`.

## Execution

Same 429-rate-limit story as the base cell (see
`worklogs/2026-08-08-test119-brief-revise-base-submission.md` for the shared
diagnosis): concurrency 6 (alongside 2 other OpenAI-backed systems) got
60/119; concurrency 3 (alongside the base cell's own resume) got 103/119;
concurrency 2, run alone, finished the remaining 16 -- **119/119**, 0
failures on the final pass.

## Result

119/119 topics completed. References/topic 8-47 (mean 24.7); words/topic
609-1001 (mean 834.3, within cap); mean 22.6 search calls (fewer than the
base cell's 26.4, consistent with §7's finding that single-engine retrieval
costs less per topic than the two-engine default); mean 300,621 processed
tokens/topic.

## Cost

Same placeholder \$5/1M OpenAI rate as the base cell. Estimated
**\$1.503/topic, \$178.87 for the full 119-topic run** -- 8% cheaper than the
base cell's \$194.91, matching §7's per-topic finding that `hybrid`-alone is
the one component in the whole report that is both cheaper and higher-scoring
on standalone than the default config.

## Validation

- `validate_rag_output`: 0 violations.
- `autojudge_base.report_tool check --spec rag26`: same `run_id_max_len=20`
  fix as the base cell (see that report for the full explanation).
  Organizer-facing tag: **`brief-hybrid-t119`** (17 chars). Final check:
  **119/119 valid against rag26**.

## Artifacts

- `data/outputs/submissions/brief-hybrid-t119/rag_output_trec_rag_2026.jsonl`
  (119 rows, SHA-256
  `8a42c111ad33eec5e88d0901f8fb5bb60c123802bf8d9912405d58ea6415d5c8`)
- Internal artifacts: `data/outputs/brief_revise_agent/*.output.json`,
  `metadata.run_id=brief-revise-hybrid-test119-20260808`.
- Launch logs: `tasks/task-comparison/logs/brief-revise-hybrid-test119-20260808.launch.log`.
