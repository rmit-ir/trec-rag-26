# Add GPT-OSS-120B to keyword overrate comparison

## Change

Updated `tmp/compare_2021_keyword_overrate_underrate_gpt_oss_vs_gpt_5_6_terra.ipynb`
to compare GPT-OSS 20B, GPT-OSS 120B, and GPT-5.6 Terra against each model's
own original 2021 Bing judgments.

The notebook now reads:

- `evaluation-results/llm-judge-robustness/original/gpt-oss-120b/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/keywords/gpt-oss-120b/bing/2021/judgments.jsonl`

Model columns, delta calculations, overall and per-baseline rate tables, change
distributions, movement-overlap heatmaps, and the large-change inspection table
are generated from one three-model mapping.

## Verification

Executed successfully:

```bash
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_keyword_overrate_underrate_gpt_oss_vs_gpt_5_6_terra.ipynb
```

The GPT-OSS-120B original ledger contains 2,395 completed judgments. Its
keyword-injected ledger contains 2,391 completed judgments.

## Passage length follow-up

Added a `Passage length by judgment movement` section to the same notebook. It
reports the task count, mean, and median word count of the keyword-injected
passage for every model and movement direction: underrated, unchanged, and
overrated. Words are defined as whitespace-delimited tokens (`\\S+`). The
notebook was re-executed after this addition with the same command above.
