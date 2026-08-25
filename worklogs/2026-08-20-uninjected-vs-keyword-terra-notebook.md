# Uninjected vs keyword-injected GPT-5.6 Terra notebook

## Request and exact inputs

Create a Jupyter notebook visualizing the effect of keyword injection while
holding the judge and task set constant.

- Uninjected Terra: `evaluation-results/llm-judge-robustness/original/gpt-5.6-terra/2021.judgments.jsonl`
- Keyword-injected Terra: `evaluation-results/llm-judge-robustness/keywords/gpt-5.6-terra/bing/2021/judgments.jsonl`
- Gold labels: `data/ragdoll-robustness/gold/trec-dl/trec_dl_2021.csv`
- Pairing key: `(qid, docid)`
- Valid labels: `0`, `1`, `2`, `3`

Both model ledgers contain 2,395 completed unique tasks across 54 queries. All
2,395 task keys and query strings match. Every keyword-injected passage differs
from its uninjected counterpart. Gold lookup removes the translation identity
suffix following `__` from `qid` only for the source-gold join; all paired tasks
received a gold label.

## Artifact

Created and executed:

`tmp/compare_2021_uninjected_vs_keyword_terra.ipynb`

Execution command:

```powershell
$env:UV_CACHE_DIR = 'D:\Work\trec-rag-26\tmp\uv-cache'
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_uninjected_vs_keyword_terra.ipynb 2>&1 | Tee-Object -FilePath tmp/compare-2021-uninjected-vs-keyword-terra-nbconvert.log
```

The notebook contains seven executed code cells and zero error outputs.
PowerShell returned exit code 1 because Jupyter warnings were written to stderr;
`nbconvert` nevertheless completed and wrote the 428,318-byte notebook.

## Full distributions

Counts:

| Series | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| Gold labels | 950 | 656 | 506 | 283 |
| Uninjected Terra | 157 | 1,047 | 551 | 640 |
| Keyword-injected Terra | 34 | 863 | 830 | 668 |

Percentages:

| Series | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| Gold labels | 39.67% | 27.39% | 21.13% | 11.82% |
| Uninjected Terra | 6.56% | 43.72% | 23.01% | 26.72% |
| Keyword-injected Terra | 1.42% | 36.03% | 34.66% | 27.89% |

## Full transition matrix

Rows are uninjected labels and columns are keyword-injected labels.

| Uninjected \\ Keyword | 0 | 1 | 2 | 3 |
|---:|---:|---:|---:|---:|
| 0 | 21 | 100 | 34 | 2 |
| 1 | 13 | 714 | 275 | 45 |
| 2 | 0 | 48 | 388 | 115 |
| 3 | 0 | 1 | 133 | 506 |

Full label-change distribution (`keyword - uninjected`):

| Change | Tasks | Percentage |
|---:|---:|---:|
| -2 | 1 | 0.04% |
| -1 | 194 | 8.10% |
| 0 | 1,629 | 68.02% |
| +1 | 490 | 20.46% |
| +2 | 79 | 3.30% |
| +3 | 2 | 0.08% |

## Summary metrics

- Exact agreement: 68.0167%
- Agreement within one label: 96.5762%
- Cohen's kappa: 0.5346
- Quadratic weighted kappa: 0.7327
- Uninjected mean: 1.6990
- Keyword-injected mean: 1.8902
- Mean change: +0.1912
- Keyword judgment higher: 23.8413%
- Keyword judgment lower: 8.1420%
- Absolute change of at least two labels: 82 tasks

The notebook visualizes counts and percentages for gold/uninjected/keyword
labels, count and row-percentage transition heatmaps, a per-query mean-change
bar chart, and a complete table of the 82 task-level changes of at least two
labels with both passage versions.
