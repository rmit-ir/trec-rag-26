# Query-at-end injector

## Request

Create an injector analogous to keyword injection that appends each complete query to the end of its passage.

## Implementation

- Added `tasks/llm_judge_robustness/scripts/query_injector.py`.
- The transformation normalizes embedded whitespace in the passage and query, preserves query case and punctuation, and emits `<passage> <query>`.
- Empty query text is rejected rather than silently producing an uninjected row.
- Default CSV output is `data/ragdoll-robustness/injected/query/trec_dl_<year>.csv`.
- Extended `build_ragdoll_relevance_inputs.py` with mutually exclusive `--query-injection` mode.
- Default RAGDOLL output is `data/ragdoll-robustness/derived/ragdoll-inputs/query/<year>.requests.jsonl`.
- Documented both commands in `tasks/llm_judge_robustness/README.md`.

## Verification

Focused tests:

```powershell
$env:UV_CACHE_DIR='D:\Work\trec-rag-26\tmp\uv-cache'
uv run --group dev --group o3-deep-research --group aus-agent pytest -p no:cacheprovider --basetemp tmp/pytest-query-injector tests/llm_judge_robustness/test_query_injector.py
```

Result: 3 passed.

Lint:

```powershell
$env:UV_CACHE_DIR='D:\Work\trec-rag-26\tmp\uv-cache'
uv run --project evaluation/ragdoll --group dev ruff check tasks/llm_judge_robustness/scripts/query_injector.py tasks/llm_judge_robustness/scripts/build_ragdoll_relevance_inputs.py tests/llm_judge_robustness/test_query_injector.py
```

Result: all checks passed.

End-to-end 2021 smoke build:

```powershell
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/query_injector.py --years 2021 --output-root tmp/query-injector-smoke/injected --overwrite
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/build_ragdoll_relevance_inputs.py --query-injection --years 2021 --input-root tmp/query-injector-smoke/injected --output-root tmp/query-injector-smoke/ragdoll-inputs --overwrite
```

The source was `data/ragdoll-robustness/gold/trec-dl/trec_dl_2021.csv`. The smoke build produced 2,398 CSV rows and 54 request rows containing 2,395 deduplicated candidates. Every injected CSV passage ended with its exact row query, and every request had non-empty `query.qid`, `query.text`, `candidates[].doc.docid`, and `candidates[].doc.segment` fields.

Production outputs were not generated during this session.

## Directory slug rename

The condition folders were subsequently renamed from `query_injector` to
`query`. Existing 2021-2023 CSV and RAGDOLL JSONL artifacts were moved in place,
and the script defaults, converter defaults, log labels, and README paths were
updated to match. The injector script name remains `query_injector.py`.
