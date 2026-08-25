# Uninjected GPT-5.6 Terra TREC-DL 2021 rerun

## Request

Run the plain, uninjected TREC-DL 2021 passages through RAGDOLL with
`gpt-5.6-terra`, for a later notebook comparison against the keyword-injected
Terra judgments.

## Exact input and outputs

- Input: `data/ragdoll-robustness/derived/ragdoll-inputs/original/2021.requests.jsonl`
- Judgments: `evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.judgments.jsonl`
- Failures: `evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.failed.jsonl`
- Raw events: `evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.raw-events/`
- Log: `evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.log`
- Prompt: RAGDOLL UMBRELA `bing`
- Provider/model: `azure-openai-responses` / `gpt-5.6-terra`
- Concurrency: 4

## Recovery and launch

The first attempt produced 2,395 failures because Pi had no registered Terra
model. A second attempt after aliasing `OPENAI_BASE_URL` to
`AZURE_OPENAI_BASE_URL` confirmed that credentials alone were insufficient.
Created the gitignored, secret-free temporary registry
`tmp/pi-terra-agent/models.json`; it references the Azure endpoint and key only
through environment-variable names. `pi --list-models` then resolved
`azure-openai-responses / gpt-5.6-terra`.

The first registered-model attempt was stopped after 12 connection failures
inside the network-restricted sandbox. The run was relaunched with approved
network access and `--overwrite`, clearing the stale failure ledger. Launch
command:

```powershell
$env:UV_CACHE_DIR = 'D:\Work\trec-rag-26\tmp\uv-cache'
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable(
            $matches[1].Trim(),
            $matches[2].Trim().Trim('"').Trim("'"),
            'Process'
        )
    }
}
$env:AZURE_OPENAI_BASE_URL = $env:OPENAI_BASE_URL
uv run --project evaluation/ragdoll ragdoll umbrela judge --provider azure-openai-responses --model gpt-5.6-terra --prompt-type bing --input-file data/ragdoll-robustness/derived/ragdoll-inputs/original/2021.requests.jsonl --output-file evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.judgments.jsonl --failed-output evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.failed.jsonl --raw-events-dir evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.raw-events --agent-state-dir tmp/pi-terra-agent --max-concurrency 4 --overwrite 2>&1 | Tee-Object -FilePath evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.log
```

Initial healthy checkpoint: 50 completed judgments, 0 failures. The tracked run
was still active at this checkpoint.
