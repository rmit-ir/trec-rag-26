# LLM judge robustness

## Multilingual TREC-DL queries

`scripts/translate_queries.py` extracts unique queries from the 2021–2023
TREC-DL gold CSVs and writes one resumable JSONL file per language and year:

```text
data/ragdoll-robustness/derived/query-translations/<language>/<year>.jsonl
```

English rows are copied without an API call. Other languages use Amazon
Translate's synchronous `TranslateText` API. Credentials are loaded through the
normal AWS credential chain, with the repository `.env` loaded when present.

The source has one 2021 qid (`1107704`) attached to two different query
strings. Both are preserved. Such variants retain the original `qid` and get a
stable hash-suffixed `translation_id`; ordinary queries use the qid as their
translation ID.

From the repository root:

```powershell
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/translate_queries.py --dry-run
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/translate_queries.py
```

Use `--max-requests 1` for a one-request paid pilot. Each completed request is
checkpointed atomically; rerunning the same command resumes by translation ID.
`--languages` and `--years` accept comma-separated selections. The region can
be overridden with `--region` or `AWS_REGION`.

Every non-dry invocation appends a run record to `_runs.jsonl` and atomically
updates `_cost-total.json` beneath the output root. Costs use successful
requests' English input character counts at the configurable standard rate
(`--usd-per-million-characters`, default `$15.00`). This is an estimate before
free-tier credits, taxes, or account-specific pricing; CloudWatch's
`AWS/Translate` `CharacterCount` metric is authoritative for billed usage.

The script produces English, Arabic, Simplified Chinese, Russian, Hebrew,
Hindi, Vietnamese, Thai, Tagalog, Swahili, Gaeilge (Irish), and Amharic. All
target codes are supported by Amazon Translate.

## Distractor generation

`scripts/generate_distractors.py` adapts the four perturbation prompts under
`configs/perturbations/` to TREC-DL queries and relevance-2+ gold passages. It
uses the repository's Azure OpenAI-compatible endpoint with deployment
`gpt-5.6-terra` by default (`DISTRACTOR_MODEL_ID` or `--model-id` overrides it).
Set `OPENAI_BASE_URL` and either `OPENAI_API_KEY` or `AZURE_OPENAI_API_KEY` in
the root `.env`.

```powershell
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/generate_distractors.py --dry-run
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/generate_distractors.py --max-requests 1
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/generate_distractors.py
```

English is the default. Pass `--languages all` after query translation is
complete to generate every language. Outputs are resumable and partitioned as
`data/ragdoll-robustness/derived/distractors/<category>/<language>/<year>.jsonl`.
Query variants without a relevance-2+ passage are skipped and listed once in
`distractors/skipped-no-grade2-evidence.csv` with their maximum available grade.
After a complete or bounded run, cumulative per-distractor token usage is
written to `data/ragdoll-robustness/derived/distractors/usage.csv`. Supply both
`--input-usd-per-million-tokens` and `--output-usd-per-million-tokens` to add
cost estimates using the rates for your Azure deployment; rates are not assumed.

## Injecting distractors into judged CSVs

`scripts/inject_distractors.py` appends each English distractor to the end of
every passage belonging to its matching query variant. It preserves row count,
passage IDs, relevance grades, queries, and column order, and writes copies to
`data/ragdoll-robustness/injected/distractors/<category>/`.

```powershell
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/inject_distractors.py
```

Existing outputs are protected; use `--overwrite` to rebuild them. Complete
eligible-query coverage is required unless `--allow-partial` is explicit.

## Building RAGDOLL relevance inputs

`scripts/build_ragdoll_relevance_inputs.py` converts every injected judged CSV
into RAGDOLL's UMBRELA `query` + `candidates[].doc.segment` JSONL schema. Files
are clearly partitioned under
`data/ragdoll-robustness/derived/ragdoll-inputs/distractors/<category>/`.

```powershell
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/build_ragdoll_relevance_inputs.py
```

The converter preserves candidate pids as docids and hash-disambiguates the one
2021 qid associated with two distinct query strings. Outputs are atomic and
overwrite protected.
