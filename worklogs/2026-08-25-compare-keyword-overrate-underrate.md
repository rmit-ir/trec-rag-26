# Compare keyword-injection overrate and underrate

## Request and definitions

Compare GPT-OSS 20B and GPT-5.6 Terra overrate and underrate percentages, using each model's results under the `original` folder as its baseline.

For each model and the same `(qid, docid)` task:

- `delta = keyword-injected judgment - original judgment`
- overrated: `delta > 0`
- underrated: `delta < 0`
- unchanged: `delta == 0`

This definition measures movement caused by the keyword-injected evaluation relative to each judge's own uninjected result. It does not use TREC gold labels as the baseline.

## Exact inputs

- GPT-OSS original: `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2021.judgments.jsonl`
- GPT-OSS keyword injected: `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2021/2021.judgments.jsonl`
- GPT-5.6 Terra original: `evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.judgments.jsonl`
- GPT-5.6 Terra keyword injected: `evaluation-results/llm-judge-robustness/keywords/gpt-5.6-terra/bing/2021/judgments.jsonl`

The ledgers persist all exact query and passage strings. The notebook retains those raw strings in its task-level inspection table and rejects mismatched query text between each model's original and injected rows.

## Artifact

Created and executed:

`tmp/compare_2021_keyword_overrate_underrate_gpt_oss_vs_gpt_5_6_terra.ipynb`

Execution command:

```powershell
$env:UV_CACHE_DIR='D:\Work\trec-rag-26\tmp\uv-cache'
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_keyword_overrate_underrate_gpt_oss_vs_gpt_5_6_terra.ipynb 2>&1 | Tee-Object -FilePath tmp/compare-2021-keyword-overrate-underrate-nbconvert.log
```

The notebook contains 2,374 tasks across 54 queries in the intersection of valid completed tasks from all four ledgers.

## Overall results

| Model | Overrated | Overrate | Overrate 95% CI | Underrated | Underrate | Underrate 95% CI | Unchanged | Unchanged | Mean delta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-OSS 20B | 807 | 33.99% | 32.11%-35.92% | 192 | 8.09% | 7.06%-9.25% | 1,375 | 57.92% | +0.400 |
| GPT-5.6 Terra | 564 | 23.76% | 22.09%-25.51% | 194 | 8.17% | 7.14%-9.34% | 1,616 | 68.07% | +0.190 |

- Terra minus GPT-OSS overrate: -10.24 percentage points.
- Terra minus GPT-OSS underrate: +0.08 percentage points.
- GPT-OSS changed upward by at least two labels on 13.23% of tasks; Terra did so on 3.37%.
- GPT-OSS changed downward by at least two labels on 1.26% of tasks; Terra did so on 0.04%.

## Full delta distribution

Counts, where columns are `injected - original`:

| Model | -3 | -2 | -1 | 0 | +1 | +2 | +3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-OSS 20B | 0 | 30 | 162 | 1,375 | 493 | 264 | 50 |
| GPT-5.6 Terra | 0 | 1 | 193 | 1,616 | 484 | 78 | 2 |

Percentages:

| Model | -3 | -2 | -1 | 0 | +1 | +2 | +3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-OSS 20B | 0.00% | 1.26% | 6.82% | 57.92% | 20.77% | 11.12% | 2.11% |
| GPT-5.6 Terra | 0.00% | 0.04% | 8.13% | 68.07% | 20.39% | 3.29% | 0.08% |

## Rates by original label

| Model | Original label | Tasks | Overrated | Overrate | Underrated | Underrate | Unchanged |
|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-OSS 20B | 0 | 405 | 319 | 78.77% | 0 | 0.00% | 21.23% |
| GPT-OSS 20B | 1 | 699 | 387 | 55.36% | 18 | 2.58% | 42.06% |
| GPT-OSS 20B | 2 | 218 | 101 | 46.33% | 31 | 14.22% | 39.45% |
| GPT-OSS 20B | 3 | 1,052 | 0 | 0.00% | 143 | 13.59% | 86.41% |
| GPT-5.6 Terra | 0 | 157 | 136 | 86.62% | 0 | 0.00% | 13.38% |
| GPT-5.6 Terra | 1 | 1,034 | 315 | 30.46% | 13 | 1.26% | 68.28% |
| GPT-5.6 Terra | 2 | 548 | 113 | 20.62% | 48 | 8.76% | 70.62% |
| GPT-5.6 Terra | 3 | 635 | 0 | 0.00% | 133 | 20.94% | 79.06% |

## Full movement-direction overlap

Rows are GPT-OSS movement and columns are Terra movement.

| GPT-OSS \\ Terra | Underrated | Unchanged | Overrated |
|---|---:|---:|---:|
| Underrated | 23 | 134 | 35 |
| Unchanged | 138 | 1,031 | 206 |
| Overrated | 33 | 451 | 323 |

## Verification

The notebook was parsed after execution. It has 15 cells, no missing cell IDs, and zero error outputs. It includes coverage auditing, overall percentages with Wilson 95% intervals, grouped rate charts, baseline-label breakdowns, full delta distributions, direction overlap, per-query distributions, and task-level examples with changes of at least two labels.
