# Compare GPT-OSS with GPT-5.6 Terra on 2021 keyword injection

## Request

Create a Jupyter notebook comparing the GPT-OSS and GPT-5.6 Terra RAGDOLL relevance judgments.

## Exact inputs

- GPT-OSS judgments: `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2021/2021.judgments.jsonl`
- GPT-5.6 Terra judgments: `evaluation-results/llm-judge-robustness/keywords/gpt-5.6-terra/bing/2021/judgments.jsonl`
- Pairing key: `(qid, docid)`
- Valid labels: `0`, `1`, `2`, `3`

The ledgers persist all 54 exact query strings and all injected passage strings. The created notebook displays the underlying task-level query and passage text for large disagreements. All 2,387 paired rows have byte-identical query and injected passage text across the two runs; the notebook asserts this on every execution.

## Artifact

Created and executed:

`tmp/compare_2021_keywords_gpt_oss_vs_gpt_5_6_terra.ipynb`

Execution command:

```bash
UV_CACHE_DIR=tmp/uv-cache uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_keywords_gpt_oss_vs_gpt_5_6_terra.ipynb 2>&1 | tee tmp/compare-2021-gpt-oss-vs-terra-nbconvert.log
```

## Coverage

| Model | Completed unique tasks | Queries |
|---|---:|---:|
| GPT-OSS 20B | 2,387 | 54 |
| GPT-5.6 Terra | 2,395 | 54 |

Paired tasks: 2,387. Terra has eight additional completed tasks; GPT-OSS has no completed task absent from Terra.

## Full judgment transition matrix

Rows are GPT-OSS labels and columns are Terra labels.

| GPT-OSS \\ Terra | 0 | 1 | 2 | 3 |
|---:|---:|---:|---:|---:|
| 0 | 14 | 84 | 7 | 1 |
| 1 | 14 | 420 | 98 | 12 |
| 2 | 4 | 202 | 240 | 39 |
| 3 | 2 | 152 | 484 | 614 |

Paired label distributions:

| Model | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| GPT-OSS 20B | 106 | 544 | 485 | 1,252 |
| GPT-5.6 Terra | 34 | 858 | 829 | 666 |

Paired label percentages:

| Model | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| GPT-OSS 20B | 4.44% | 22.79% | 20.32% | 52.45% |
| GPT-5.6 Terra | 1.42% | 35.94% | 34.73% | 27.90% |

The notebook presents these distributions as tables and as adjacent grouped count and percentage charts.

## Summary metrics

- Exact agreement: 53.9589%
- Agreement within one label: 92.5429%
- Cohen's kappa: 0.3428
- Quadratic weighted kappa: 0.5868
- GPT-OSS mean: 2.2078
- Terra mean: 1.8911
- Terra minus GPT-OSS mean: -0.3167
- Terra higher: 10.0964%
- Terra lower: 35.9447%
- Absolute label difference of at least two: 178 tasks

GPT-OSS low-label promotion rates under Terra:

| GPT-OSS source label | Tasks | Terra label 2 or 3 | Percentage |
|---|---:|---:|---:|
| 0 | 106 | 8 | 7.55% |
| 1 | 544 | 110 | 20.22% |
| 0 or 1 | 650 | 118 | 18.15% |

## Notebook contents

The notebook contains a coverage audit, paired-input validation, agreement summary, count and percentage distributions, count and row-percentage transition heatmaps, 0/1-to-2/3 promotion rates, per-query disagreement analysis, and task-level examples differing by at least two labels.

The final notebook execution completed with no error outputs.

## Gold-label distribution extension

Added the official TREC-DL 2021 gold relevance labels to the distribution table
and both grouped bar charts. The exact gold input is:

`data/ragdoll-robustness/gold/trec-dl/trec_dl_2021.csv`

Gold rows are joined by source `(qid, docid)`. Translated-query run IDs carry an
identity suffix after `__`; the notebook strips that suffix only for the gold
lookup and retains the complete run `qid` for all model comparisons. Three
duplicate gold keys have identical labels; execution now rejects conflicting
duplicates and collapses same-label duplicates before the validated one-to-one
join. All 2,387 paired model tasks received a gold label.

The refreshed count distribution is:

| Series | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| Gold labels | 945 | 654 | 506 | 282 |
| GPT-OSS 20B | 106 | 544 | 485 | 1,252 |
| GPT-5.6 Terra | 34 | 858 | 829 | 666 |

Re-execution used:

```powershell
$env:UV_CACHE_DIR = 'D:\Work\trec-rag-26\tmp\uv-cache'
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_keywords_gpt_oss_vs_gpt_5_6_terra.ipynb 2>&1 | Tee-Object -FilePath tmp/compare-2021-gpt-oss-vs-terra-gold-nbconvert.log
```

`nbconvert` refreshed the notebook successfully. The PowerShell wrapper returned
exit code 1 because Jupyter warnings were emitted on stderr, but the artifact was
written, all eight code cells have fresh execution counts, and it contains zero
error outputs.
