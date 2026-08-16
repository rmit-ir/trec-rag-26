# Yun Yi Bing versus PromptArmor notebook

Created and executed:

`tmp/compare_2021_yun_yi_bing_vs_promptarmor.ipynb`

Exact primary inputs:

- `evaluation-results/llm-judge-robustness/yun_yi/umbrela-bing/gpt-oss-20b/2021/judgments.jsonl`
- `evaluation-results/llm-judge-robustness/yun_yi/umbrela-bing/gpt-oss-20b/2021/failed.jsonl`
- `evaluation-results/llm-judge-robustness/yun_yi/promptarmor/gpt-oss-20b/2021/judgments.jsonl`
- `evaluation-results/llm-judge-robustness/yun_yi/promptarmor/gpt-oss-20b/2021/failed.jsonl`

Coverage audit:

| Prompt | Success rows | Failure rows | Unique successes | Unique failures | Unique tasks seen |
|---|---:|---:|---:|---:|---:|
| Normal Bing | 2,376 | 20 | 2,376 | 20 | 2,395 |
| PromptArmor | 2,357 | 38 | 2,357 | 38 | 2,395 |

Normal Bing has one task present in both success and failure ledgers; paired
analysis uses the successful judgment. PromptArmor has no overlap. Both runs
cover all expected task IDs.

The common successful comparison set contains 2,338 candidates. Normal Bing's
mean judgment is 2.996151 and PromptArmor's is 2.972626. The paired mean delta
(PromptArmor minus Bing) is -0.023524; its fixed-seed 5,000-sample bootstrap 95%
CI is [-0.035, -0.013]. Exact label agreement is 98.5%; PromptArmor is lower on
1.3% and higher on 0.2% of paired candidates.

The executed notebook contains the complete comparison matrices: coverage and
failure audits, descriptive statistics, paired-effect summary, score and delta
distributions, count and row-normalized transition heatmaps, per-query effects,
and the 50 largest disagreements with passage endings.

Validation command:

```bash
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_yun_yi_bing_vs_promptarmor.ipynb
```

All cells executed successfully.
