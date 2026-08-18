# 2026-08-18 — standalone TREC-DL 2022 and 2023 comparison notebooks

## Goal

Create standalone 2022 and 2023 notebooks analogous to
`tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb`.

## Artifacts

- `tmp/compare_2022_keywords_before_after_promptarmor_v4.ipynb`
- `tmp/compare_2023_keywords_before_after_promptarmor_v4.ipynb`
- Reproducible builder:
  `worklogs/assets/2026-08-18-build-single-year-trec-dl-comparisons.py`

Each notebook contains a coverage audit, relevance-label distribution table and
Seaborn chart, baseline-paired coverage, nominal Cohen's kappa, and mean judgment
difference. Missing Keyword + PromptArmor v4 ledgers remain explicit in the
tables rather than raising `FileNotFoundError`.

## Exact inputs

| Year | Condition | Judgment ledger |
|---:|---|---|
| 2022 | Original + Bing | `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2022.judgments.jsonl` |
| 2022 | Keyword + Bing | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2022/2022.judgments.jsonl` |
| 2022 | Keyword + v4 | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/promptarmor-v4/2022/judgments.jsonl` (unavailable) |
| 2022 | Yun Yi + Bing | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/bing/2022/judgments.jsonl` |
| 2022 | Yun Yi + v4 | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/promptarmor-v4-corrected/2022/judgments.jsonl` |
| 2023 | Original + Bing | `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2023.judgments.jsonl` |
| 2023 | Keyword + Bing | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2023/2023.judgments.jsonl` |
| 2023 | Keyword + v4 | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/promptarmor-v4/2023/judgments.jsonl` (unavailable) |
| 2023 | Yun Yi + Bing | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/bing/2023/judgments.jsonl` |
| 2023 | Yun Yi + v4 | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/promptarmor-v4-corrected/2023/judgments.jsonl` |

## Coverage audit

| Year | Run | Completed unique | Queries | Coverage |
|---:|---|---:|---:|---:|
| 2022 | Original + Bing | 2,641 | 76 | 99.5% |
| 2022 | Keyword + Bing | 2,655 | 76 | 100.0% |
| 2022 | Keyword + v4 | 0 (unavailable) | 0 | 0.0% |
| 2022 | Yun Yi + Bing | 2,618 | 76 | 98.6% |
| 2022 | Yun Yi + v4 | 2,531 | 76 | 95.3% |
| 2023 | Original + Bing | 2,448 | 82 | 99.5% |
| 2023 | Keyword + Bing | 2,448 | 82 | 99.5% |
| 2023 | Keyword + v4 | 0 (unavailable) | 0 | 0.0% |
| 2023 | Yun Yi + Bing | 2,432 | 82 | 98.9% |
| 2023 | Yun Yi + v4 | 2,334 | 82 | 94.9% |

The available injected-run intersections contain 2,497 tasks for 2022 and
2,298 tasks for 2023.

## Relevance-label distributions

| Year | Run | Basis | Label 0 | Label 1 | Label 2 | Label 3 |
|---:|---|---|---:|---:|---:|---:|
| 2022 | Original + Bing | full ledger | 488 | 1,035 | 298 | 820 |
| 2022 | Keyword + Bing | shared injected set | 147 | 854 | 520 | 976 |
| 2022 | Yun Yi + Bing | shared injected set | 3 | 2 | 4 | 2,488 |
| 2022 | Yun Yi + v4 | shared injected set | 505 | 876 | 318 | 798 |
| 2023 | Original + Bing | full ledger | 829 | 914 | 218 | 487 |
| 2023 | Keyword + Bing | shared injected set | 186 | 917 | 497 | 698 |
| 2023 | Yun Yi + Bing | shared injected set | 10 | 8 | 0 | 2,280 |
| 2023 | Yun Yi + v4 | shared injected set | 764 | 788 | 264 | 482 |

## Full baseline-paired matrix

| Year | Run | Status | Matched | Cohen kappa | Original mean | Run mean | Mean difference |
|---:|---|---|---:|---:|---:|---:|---:|
| 2022 | Keyword + Bing | ok | 2,641 | 0.3411 | 1.549 | 1.931 | +0.382 |
| 2022 | Keyword + v4 | missing run | 0 | N/A | N/A | N/A | N/A |
| 2022 | Yun Yi + Bing | ok | 2,604 | 0.0018 | 1.549 | 2.993 | +1.444 |
| 2022 | Yun Yi + v4 | ok | 2,517 | 0.5297 | 1.546 | 1.566 | +0.020 |
| 2023 | Keyword + Bing | ok | 2,437 | 0.2598 | 1.151 | 1.739 | +0.588 |
| 2023 | Keyword + v4 | missing run | 0 | N/A | N/A | N/A | N/A |
| 2023 | Yun Yi + Bing | ok | 2,421 | 0.0073 | 1.150 | 2.980 | +1.829 |
| 2023 | Yun Yi + v4 | ok | 2,323 | 0.5696 | 1.158 | 1.197 | +0.039 |

## Validation

```bash
uv run --group dev ruff check worklogs/assets/2026-08-18-build-single-year-trec-dl-comparisons.py
uv run --group notebook python worklogs/assets/2026-08-18-build-single-year-trec-dl-comparisons.py
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2022_keywords_before_after_promptarmor_v4.ipynb
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2023_keywords_before_after_promptarmor_v4.ipynb
```

The builder passed Ruff. Both notebooks executed all five code cells with zero
error outputs. The Windows ZeroMQ messages were runtime warnings only.
