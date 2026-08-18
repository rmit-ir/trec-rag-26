# 2026-08-18 — generalize the 2021 relevance comparison to TREC-DL 2021–2023

## Goal

Copy `tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb` to
`tmp/compare_trec_dl.ipynb` and extend the same five-condition comparison across
TREC-DL 2021, 2022, and 2023:

1. Original + Bing
2. Keyword + Bing
3. Keyword + PromptArmor v4
4. Yun Yi + Bing
5. Yun Yi + PromptArmor v4

The reproducible notebook builder is
`worklogs/assets/2026-08-18-build-compare-trec-dl.py`.

## Exact input ledgers

| Year | Condition | Judgment ledger |
|---:|---|---|
| 2021 | Original + Bing | `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2021.judgments.jsonl` |
| 2021 | Keyword + Bing | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/archive/bing-pre-uppercase/2021.judgments.jsonl` |
| 2021 | Keyword + v4 | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/promptarmor-v4/2021/judgments.jsonl` |
| 2021 | Yun Yi + Bing | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/bing/2021/judgments.jsonl` |
| 2021 | Yun Yi + v4 | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/promptarmor-v4-corrected/2021/judgments.jsonl` |
| 2022 | Original + Bing | `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2022.judgments.jsonl` |
| 2022 | Keyword + Bing | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2022/2022.judgments.jsonl` |
| 2022 | Keyword + v4 | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/promptarmor-v4/2022/judgments.jsonl` (**missing**) |
| 2022 | Yun Yi + Bing | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/bing/2022/judgments.jsonl` |
| 2022 | Yun Yi + v4 | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/promptarmor-v4-corrected/2022/judgments.jsonl` |
| 2023 | Original + Bing | `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2023.judgments.jsonl` |
| 2023 | Keyword + Bing | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2023/2023.judgments.jsonl` |
| 2023 | Keyword + v4 | `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/promptarmor-v4/2023/judgments.jsonl` (**missing**) |
| 2023 | Yun Yi + Bing | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/bing/2023/judgments.jsonl` |
| 2023 | Yun Yi + v4 | `evaluation-results/llm-judge-robustness/yun_yi/gpt-oss-20b/promptarmor-v4-corrected/2023/judgments.jsonl` |

The 2021 Keyword+Bing path deliberately uses the archived original notebook
ledger. Its passages match the existing 2021 Keyword+v4 campaign. Substituting
the newer uppercase Keyword+Bing ledger on only one side would confound passage
changes with prompt changes.

## Method

- Retain the latest completed 0–3 judgment per `(qid, docid)`.
- Show every expected ledger in the audit, including missing ledgers.
- Within each year, intersect `(qid, docid)` over all available injected runs
  before plotting their label distributions.
- Show Original+Bing from its full completed ledger when available.
- Compute baseline-paired Cohen's kappa and mean judgment difference only when
  Original+Bing and the comparison run exist and share tasks. Missing inputs are
  reported as statuses and `NaN`, not silently dropped or treated as zero.

## Coverage matrix

Expected task counts are 2,395 (2021), 2,655 (2022), and 2,460 (2023).

| Year | Run | Completed unique | Queries | Coverage |
|---:|---|---:|---:|---:|
| 2021 | Original + Bing | 2,382 | 54 | 99.5% |
| 2021 | Keyword + Bing | 2,385 | 54 | 99.6% |
| 2021 | Keyword + v4 | 2,380 | 54 | 99.4% |
| 2021 | Yun Yi + Bing | 2,376 | 54 | 99.2% |
| 2021 | Yun Yi + v4 | 2,290 | 54 | 95.6% |
| 2022 | Original + Bing | 2,639 | 76 | 99.4% |
| 2022 | Keyword + Bing | 2,655 | 76 | 100.0% |
| 2022 | Keyword + v4 | 0 (missing) | 0 | 0.0% |
| 2022 | Yun Yi + Bing | 2,618 | 76 | 98.6% |
| 2022 | Yun Yi + v4 | 2,531 | 76 | 95.3% |
| 2023 | Original + Bing | 2,448 | 82 | 99.5% |
| 2023 | Keyword + Bing | 2,448 | 82 | 99.5% |
| 2023 | Keyword + v4 | 0 (missing) | 0 | 0.0% |
| 2023 | Yun Yi + Bing | 2,432 | 82 | 98.9% |
| 2023 | Yun Yi + v4 | 2,334 | 82 | 94.9% |

Fair injected intersections: 2,248 tasks for 2021 (four runs), 2,497 for 2022
(three available runs), and 2,298 for 2023 (three available runs).

## Full distribution matrix on the notebook's comparison sets

| Year | Run | Label 0 | Label 1 | Label 2 | Label 3 |
|---:|---|---:|---:|---:|---:|
| 2021 | Original + Bing (full ledger) | 407 | 701 | 221 | 1,053 |
| 2021 | Keyword + Bing | 123 | 650 | 328 | 1,147 |
| 2021 | Keyword + v4 | 109 | 709 | 321 | 1,109 |
| 2021 | Yun Yi + Bing | 1 | 3 | 0 | 2,244 |
| 2021 | Yun Yi + v4 | 386 | 579 | 294 | 989 |
| 2022 | Original + Bing (full ledger) | 488 | 1,035 | 297 | 819 |
| 2022 | Keyword + Bing | 147 | 854 | 520 | 976 |
| 2022 | Yun Yi + Bing | 3 | 2 | 4 | 2,488 |
| 2022 | Yun Yi + v4 | 505 | 876 | 318 | 798 |
| 2023 | Original + Bing (full ledger) | 829 | 914 | 218 | 487 |
| 2023 | Keyword + Bing | 186 | 917 | 497 | 698 |
| 2023 | Yun Yi + Bing | 10 | 8 | 0 | 2,280 |
| 2023 | Yun Yi + v4 | 764 | 788 | 264 | 482 |

## Full baseline-paired result matrix

| Year | Run | Status | Matched | Cohen kappa | Original mean | Run mean | Mean difference |
|---:|---|---|---:|---:|---:|---:|---:|
| 2021 | Keyword + Bing | ok | 2,372 | 0.4558 | 1.804 | 2.105 | +0.301 |
| 2021 | Keyword + v4 | ok | 2,367 | 0.4660 | 1.805 | 2.076 | +0.271 |
| 2021 | Yun Yi + Bing | ok | 2,363 | 0.0028 | 1.806 | 2.996 | +1.190 |
| 2021 | Yun Yi + v4 | ok | 2,277 | 0.6010 | 1.819 | 1.843 | +0.024 |
| 2022 | Keyword + Bing | ok | 2,639 | 0.3411 | 1.548 | 1.930 | +0.382 |
| 2022 | Keyword + v4 | missing run | 0 | N/A | N/A | N/A | N/A |
| 2022 | Yun Yi + Bing | ok | 2,602 | 0.0018 | 1.548 | 2.993 | +1.445 |
| 2022 | Yun Yi + v4 | ok | 2,516 | 0.5301 | 1.546 | 1.565 | +0.019 |
| 2023 | Keyword + Bing | ok | 2,437 | 0.2598 | 1.151 | 1.739 | +0.588 |
| 2023 | Keyword + v4 | missing run | 0 | N/A | N/A | N/A | N/A |
| 2023 | Yun Yi + Bing | ok | 2,421 | 0.0073 | 1.150 | 2.980 | +1.829 |
| 2023 | Yun Yi + v4 | ok | 2,323 | 0.5696 | 1.158 | 1.197 | +0.039 |

## Execution

```bash
uv run --group notebook python worklogs/assets/2026-08-18-build-compare-trec-dl.py
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_trec_dl.ipynb
```

The populated notebook executed all five code cells with zero error outputs.
The Windows Proactor/ZeroMQ and unencrypted-local-kernel messages were runtime
warnings only; `nbconvert` completed with exit code 0 and wrote the notebook.

## Source notebook repair

After the Yun Yi result tree was reorganized, the copied source notebook still
embedded the former `yun_yi/umbrela-bing/gpt-oss-20b/` and
`yun_yi/promptarmor-v4-corrected/gpt-oss-20b/` paths. Its inputs now use the
canonical model-first paths under `yun_yi/gpt-oss-20b/`. The notebook's
undeclared `scikit-learn` dependency was also replaced with the same direct
nominal Cohen's kappa calculation used by `compare_trec_dl.ipynb`. The repaired
`tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb` executed in full
with zero error outputs.
