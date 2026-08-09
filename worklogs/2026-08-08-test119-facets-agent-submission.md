# Test119 submission: facets_agent

Date: 2026-08-08

## Config

Plain `facets_agent` defaults, matching the config behind its own best
recorded evidence (`facets-agent-dev30-20260806`, `aus_agent-vs-facets_agent-dev30-rubric-20260806`;
`facets-agent-15topic`, `facets_agent-vs-facet_rag-15topic`):
`openai`/`gpt-5.6-luna`, prompt=`facets_agent_minimal`, engines
`semantic+keyword+hybrid`, `k=10`. Weaker than `aus_agent` on every available
comparison but a third genuinely distinct architecture (minimal-prompt
continuous agent vs. `aus_agent`'s tuned prompt vs. `brief_revise_agent`'s
brief+review passes) -- included per report §10.3 as an
evaluation-method hedge, not as the strongest system in the portfolio.

```bash
export OPENAI_API_KEY="$(grep '^AZURE_OPENAI_API_KEY=' .env | cut -d= -f2-)"
SYSTEM=facets_agent RUN_PY=src/systems/facets_agent/run.py \
UV_GROUP=facets-agent \
EXTRA_ARGS="--backend openai --model gpt-5.6-luna --engines semantic,keyword,hybrid" \
CONCURRENCY=6 \
bash tasks/task-comparison/scripts/run_test119_generic_parallel.sh \
  facets-agent-test119-20260808
```

## Input

Same frozen 119-row official test TSV, SHA-256
`72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`.

## Execution

Single pass, concurrency 6, completed cleanly -- **119/119**, 0 failures.
(This run finished BEFORE the two `brief_revise_agent` jobs it was launched
alongside started hitting sustained 429s from the shared OpenAI quota; its
own smaller `gpt-5.6-luna` traffic wasn't the bottleneck.)

## Result

119/119 topics completed. References/topic 4-25 (mean 13.6, notably fewer
than either `brief_revise_agent` variant); words/topic 178-1018 (mean 613.0,
within cap); mean 11.7 search calls; mean 144,847 processed tokens/topic --
the cheapest of the three OpenAI-backed systems submitted this round.

## Cost

Placeholder \$5/1M OpenAI rate (no real rate card for `gpt-5.6-*` in this
repo). Estimated **\$0.724/topic, \$86.18 for the full 119-topic run**.

## Validation

- `validate_rag_output`: 0 violations.
- `autojudge_base.report_tool check --spec rag26`: internal run_id
  (`facets-agent-test119-20260808`, 29 chars) exceeds `run_id_max_len=20` --
  same fix as the `brief_revise_agent` submissions (`--output-run-id` on
  `scripts/export-rag-submission.py`). Organizer-facing tag:
  **`facets-t119`** (11 chars). Final check: **119/119 valid against
  rag26**.

## Artifacts

- `data/outputs/submissions/facets-t119/rag_output_trec_rag_2026.jsonl`
  (119 rows, SHA-256
  `03c5fa7a7e728690c54dc8229b19876c3526b4d3725203dfecd93a0ff7f1f99e`)
- Internal artifacts: `data/outputs/facets_agent/*.output.json`,
  `metadata.run_id=facets-agent-test119-20260808`.
- Launch log: `tasks/task-comparison/logs/facets-agent-test119-20260808.launch.log`.
