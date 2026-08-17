# 2026-08-17 — prepare original TREC-DL 2022/2023 RAGDOLL judgments

## Goal

Run the untouched TREC-DL 2022 and 2023 query-passage pools through the same
RAGDOLL UMBRELA/Bing baseline used for the existing 2021 run:

- provider: `amazon-bedrock`
- model: `openai.gpt-oss-20b-1:0`
- prompt type: `bing`
- concurrency: `4`

## Exact inputs

Source CSVs:

- `data/ragdoll-robustness/gold/trec-dl/trec_dl_2022.csv`
- `data/ragdoll-robustness/gold/trec-dl/trec_dl_2023.csv`

The complete query strings and passage strings are preserved verbatim in the
derived request artifacts:

- `data/ragdoll-robustness/derived/ragdoll-inputs/original/2022.requests.jsonl`
- `data/ragdoll-robustness/derived/ragdoll-inputs/original/2023.requests.jsonl`

They were produced with:

```powershell
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/build_ragdoll_relevance_inputs.py --original --years 2022,2023
```

Converter result matrix:

| year | query requests | candidate judgments |
|---:|---:|---:|
| 2022 | 76 | 2,655 |
| 2023 | 82 | 2,460 |
| total | 158 | 5,115 |

## Planned judgment commands

The jobs are resumable and keep successes, failures, raw Pi events, and console
logs separate by year:

```powershell
$env:AWS_REGION = if ($env:AWS_REGION) { $env:AWS_REGION } else { "ap-southeast-2" }
uv run --project evaluation/ragdoll ragdoll umbrela judge --provider amazon-bedrock --model "openai.gpt-oss-20b-1:0" --prompt-type bing --input-file data/ragdoll-robustness/derived/ragdoll-inputs/original/2022.requests.jsonl --output-file evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2022.judgments.jsonl --failed-output evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2022.failed.jsonl --raw-events-dir evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2022.raw-events --max-concurrency 4 --resume 2>&1 | Tee-Object -FilePath evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2022.log
uv run --project evaluation/ragdoll ragdoll umbrela judge --provider amazon-bedrock --model "openai.gpt-oss-20b-1:0" --prompt-type bing --input-file data/ragdoll-robustness/derived/ragdoll-inputs/original/2023.requests.jsonl --output-file evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2023.judgments.jsonl --failed-output evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2023.failed.jsonl --raw-events-dir evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2023.raw-events --max-concurrency 4 --resume 2>&1 | Tee-Object -FilePath evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2023.log
```

## Blocker and dry-run finding

`aws sts get-caller-identity` returned `NoCredentials`, and `aws configure
list-profiles` returned no profiles, so no intentional metered judgment run was
started.

An attempted `--dry-run` exposed a RAGDOLL defect: the CLI accepts and stores
the flag, but `ragdoll.umbrela.flows.judge` does not branch on
`config.dry_run`. It therefore launched Pi workers. The exact processes from
those attempts were stopped, and their unusable `2022.failed.jsonl` and
`2022.raw-events` artifacts were removed. Pre-existing results were unchanged.

