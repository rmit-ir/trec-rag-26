# Add PromptArmor v5 result to the 2021 keyword notebook

## Request

Add the completed 2021 keyword-injection PromptArmor v5 relevance judgments to the existing comparison notebook rather than creating a new notebook.

## Inputs

- Notebook: `tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb`
- Judgments: `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/promptarmor-v5/2021/judgments.jsonl`
- Failed tasks: `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/promptarmor-v5/2021/failed.jsonl`

The v5 ledger contains 2,378 completed rows across 54 queries. The separate failure ledger contains 17 rows.

## Changes

- Added `Keyword + v5` to the notebook's `RUN_PATHS` registry.
- Updated the notebook title and introduction to describe the v4/v5 comparison.
- Re-executed the notebook in place with the root `notebook` dependency group.

## Verification

Command:

```bash
UV_CACHE_DIR=tmp/uv-cache uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb 2>&1 | tee tmp/compare-2021-keywords-v5-nbconvert.log
```

The execution completed successfully. The refreshed outputs report:

- `Keyword + v5`: 2,378 completed unique tasks
- `Keyword + v5`: 2,365 tasks matched to `Original + Bing`
- Fair injected-run comparison: 2,198 tasks shared by seven injected runs
- Cohen's kappa against `Original + Bing`: 0.3728

The v5 run is included automatically in the distribution table and chart, matched-pair analysis, Cohen's kappa calculation, and mean-difference table through the shared run registry.
