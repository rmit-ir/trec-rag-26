# 2026-08-19 - add combined injection result to 2021 notebook

## Input

Added the completed Bing evaluation ledger for the combined keyword + Yun Yi
injection:

`evaluation-results/llm-judge-robustness/yunyi_keyword_injector/gpt-oss-20b/bing/2021/judgments.jsonl`

The run accounts for all 2,395 requested tasks: 2,363 completed judgments and
32 rows in `failed.jsonl`. No PromptArmor v4 ledger exists for this combined
condition yet, so the notebook includes only the available Bing result.

## Notebook change

Updated `tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb` in place.
The combined condition is registered as `Yun Yi + Keywords + Bing` and now
participates in the coverage audit, common-task distributions, baseline-paired
Cohen's kappa, and mean-difference table. Shared-run descriptions now derive
from the registered runs instead of assuming exactly four conditions. The
distribution chart is wider and rotates its longer run labels.

## Execution

```text
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb
```

The notebook completed with all five code cells executed and no cell errors.
The execution log is `tmp/compare-2021-yunyi-keyword-notebook.log`.

The intersection across the five injected runs contains 2,216 tasks. The full
regenerated shared-set distribution matrix (the original row remains its
unpaired full ledger) is:

| Run | 0 | 1 | 2 | 3 |
| --- | ---: | ---: | ---: | ---: |
| Original + Bing | 407 | 701 | 221 | 1,053 |
| Keyword + Bing | 121 | 638 | 322 | 1,135 |
| Keyword + v4 | 107 | 694 | 318 | 1,097 |
| Yun Yi + Bing | 1 | 3 | 0 | 2,212 |
| Yun Yi + v4 | 378 | 568 | 291 | 979 |
| Yun Yi + Keywords + Bing | 0 | 2 | 1 | 2,213 |

Baseline-paired results:

| Run | Matched | Cohen's kappa | Original mean | Run mean | Difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| Keyword + Bing | 2,372 | 0.4558 | 1.804 | 2.105 | +0.301 |
| Keyword + v4 | 2,367 | 0.4660 | 1.805 | 2.076 | +0.271 |
| Yun Yi + Bing | 2,363 | 0.0028 | 1.806 | 2.996 | +1.190 |
| Yun Yi + v4 | 2,277 | 0.6010 | 1.819 | 1.843 | +0.024 |
| Yun Yi + Keywords + Bing | 2,350 | 0.0005 | 1.812 | 2.998 | +1.186 |

## Combined PromptArmor v4 extension

Added the completed combined-injection PromptArmor v4 ledger:

`evaluation-results/llm-judge-robustness/yunyi_keyword_injector/gpt-oss-20b/promptarmor-v4/2021/judgments.jsonl`

The run accounts for all 2,395 requested tasks: 2,298 completed judgments and
97 rows in `failed.jsonl`. The notebook registers this condition as
`Yun Yi + Keywords + v4`; it participates in the same audit, shared-set
distribution, Cohen's kappa, and mean-difference calculations. The distribution
figure width increased from 14 to 16 inches to accommodate the seventh run.

The re-executed notebook completed all five code cells without errors. Adding
the v4 ledger reduces the intersection across the six injected runs to 2,121
tasks. Final shared-set distribution matrix:

| Run | 0 | 1 | 2 | 3 |
| --- | ---: | ---: | ---: | ---: |
| Original + Bing | 407 | 701 | 221 | 1,053 |
| Keyword + Bing | 116 | 614 | 306 | 1,085 |
| Keyword + v4 | 103 | 664 | 301 | 1,053 |
| Yun Yi + Bing | 1 | 3 | 0 | 2,117 |
| Yun Yi + v4 | 363 | 539 | 282 | 937 |
| Yun Yi + Keywords + Bing | 0 | 2 | 1 | 2,118 |
| Yun Yi + Keywords + v4 | 92 | 471 | 424 | 1,134 |

Final baseline-paired results:

| Run | Matched | Cohen's kappa | Original mean | Run mean | Difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| Keyword + Bing | 2,372 | 0.4558 | 1.804 | 2.105 | +0.301 |
| Keyword + v4 | 2,367 | 0.4660 | 1.805 | 2.076 | +0.271 |
| Yun Yi + Bing | 2,363 | 0.0028 | 1.806 | 2.996 | +1.190 |
| Yun Yi + v4 | 2,277 | 0.6010 | 1.819 | 1.843 | +0.024 |
| Yun Yi + Keywords + Bing | 2,350 | 0.0005 | 1.812 | 2.998 | +1.186 |
| Yun Yi + Keywords + v4 | 2,285 | 0.3574 | 1.809 | 2.218 | +0.409 |
