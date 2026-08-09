# Test119 submission: facet_rag

Date: 2026-08-08

## Config

Plain `facet_rag` defaults: Bedrock `openai.gpt-oss-120b-1:0` orchestrator +
`qwen.qwen3-next-80b-a3b` analyzer, all four retrieval engines available,
`max-chars=20000`. The weakest system with real generated output in this
repo by every available comparison (loses to both `aus_agent` and
`facets_agent` in arena, report §10.2) -- included per §10.3 as a fourth
genuinely distinct architecture (facet decomposition + separate per-facet
curation) at effectively zero marginal decision cost, since an unknown
official judge/rubric could rate it differently than this repo's own
internal evaluation loop has.

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN  # stale
                                                                  # exported
                                                                  # vars shadow
                                                                  # a refreshed
                                                                  # .env token
SYSTEM=facet_rag RUN_PY=src/systems/facet_rag/run.py UV_GROUP=facet-rag \
EXTRA_ARGS="" \
CONCURRENCY=6 \
bash tasks/task-comparison/scripts/run_test119_generic_parallel.sh \
  facet-rag-test119-20260808
```

## Input

Same frozen 119-row official test TSV, SHA-256
`72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`.

## Execution

Blocked initially on an expired AWS session token
(`botocore.exceptions.ClientError: ExpiredTokenException`); the user's first
`.env` refresh didn't take effect because stale `AWS_ACCESS_KEY_ID`/
`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` were already exported in the
shell and shadowed the fresh `.env` values (python-dotenv's `load_dotenv()`
does not override already-set env vars by default) -- fixed by explicitly
`unset`-ting them before every invocation. Two passes at concurrency 6: first
pass 118/119 (one topic, `rag2026-49`, needed a retry -- unrelated transient
failure, not the AWS issue, which was already resolved by then); second pass
picked up the last topic. **119/119 completed**, 0 net failures. On the
`brief_revise_agent` export, the exporter's failed-attempt superseding logic
needed a small fix: it only special-cased `trace.status=="failed"`, but
`facet_rag`'s own pipeline emits other terminal-but-unsuccessful statuses too
(e.g. `no_references`, seen on the one retried topic here) -- broadened to
"anything but completed/budget_exhausted" (`scripts/export-rag-submission.py`).

## Result

119/119 topics completed. References/topic 7-21 (mean 13.9); words/topic
142-802 (mean 388.9, well under the 1024 cap and notably shorter than the
other three systems -- consistent with this repo's own prior finding,
`worklogs/2026-08-05-facets-agent-vs-facet-rag-arena.md`, that `facet_rag`'s
answers run substantially shorter); mean 33.7 search calls (highest of the
four -- multi-facet orchestration issues more searches per topic); mean
461,381 processed tokens/topic (highest raw token count, but cheapest in
dollar terms since it runs on Bedrock, not OpenAI).

## Cost

Real metered Bedrock rate-card blend (`gpt-oss-120b`/`qwen`, not a
placeholder). Estimated **\$0.178/topic, \$21.21 for the full 119-topic
run** -- by far the cheapest of the four systems submitted this round, an
order of magnitude below the OpenAI-backed systems despite the highest token
count, because Bedrock's per-token rate is much lower than the placeholder
OpenAI rate used elsewhere in this report.

## Validation

- `validate_rag_output`: 0 violations.
- `autojudge_base.report_tool check --spec rag26`: internal run_id
  (`facet-rag-test119-20260808`, 27 chars) exceeds `run_id_max_len=20` --
  same `--output-run-id` fix as the other three submissions. Organizer-facing
  tag: **`facetrag-t119`** (13 chars). Final check: **119/119 valid against
  rag26**.

## Artifacts

- `data/outputs/submissions/facetrag-t119/rag_output_trec_rag_2026.jsonl`
  (119 rows, SHA-256
  `2171112c6c2f38eaaeea6c052ced6bcaa196e1e1bd5156529fb214101cc4ebd5`)
- Internal artifacts: `data/outputs/facet_rag/*.output.json`,
  `metadata.run_id=facet-rag-test119-20260808`.
- Launch log: `tasks/task-comparison/logs/facet-rag-test119-20260808.launch.log`.
