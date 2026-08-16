# Original vs Yun Yi prompt comparison notebook

Date: 2026-08-10

## Objective

Create and validate a notebook comparing the 2021 uninjected UMBRELA/Bing relevance judgments with the Yun Yi injection judged by both the normal UMBRELA/Bing prompt and PromptArmor.

## Exact inputs

- Original / Bing primary ledger: `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2021.judgments.jsonl`
- Yun Yi / Bing successful ledger: `evaluation-results/llm-judge-robustness/yun_yi/umbrela-bing/gpt-oss-20b/2021/judgments.jsonl`
- Yun Yi / Bing failure ledger: `evaluation-results/llm-judge-robustness/yun_yi/umbrela-bing/gpt-oss-20b/2021/failed.jsonl`
- Yun Yi / PromptArmor successful ledger: `evaluation-results/llm-judge-robustness/yun_yi/promptarmor/gpt-oss-20b/2021/judgments.jsonl`
- Yun Yi / PromptArmor failure ledger: `evaluation-results/llm-judge-robustness/yun_yi/promptarmor/gpt-oss-20b/2021/failed.jsonl`

The original primary ledger contains both successful and failed rows. The Yun Yi runs use separate success and failure ledgers. The notebook normalizes task identity as `qid + docid`, retains the latest attempt for duplicate identities, and restricts effect estimates to candidates completed in all three conditions.

## Coverage audit

| Condition | Primary rows | Successful tasks | Failure rows | Unique failed tasks | Success/failure overlap | Unique tasks seen | Missing tasks |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original / Bing | 2395 | 2382 | 13 | 13 | 0 | 2395 | 0 |
| Yun Yi / Bing | 2376 | 2376 | 20 | 20 | 1 | 2395 | 0 |
| Yun Yi / PromptArmor | 2357 | 2357 | 38 | 38 | 0 | 2395 | 0 |

Common completed candidate set: 2,326 of 2,395 candidates.

## Full paired result matrix

Bootstrap confidence intervals use 5,000 paired resamples with a fixed random seed.

| Comparison | Mean delta | 95% bootstrap CI | Exact agreement | Lower rate | Higher rate |
|---|---:|---:|---:|---:|---:|
| Yun Yi / Bing minus Original | +1.188 | [+1.141, +1.236] | 44.5% | 0.0% | 55.5% |
| Yun Yi / PromptArmor minus Original | +1.164 | [+1.116, +1.212] | 45.3% | 0.2% | 54.5% |
| PromptArmor minus Bing on Yun Yi | -0.024 | [-0.036, -0.013] | 98.5% | 1.3% | 0.2% |

Mean judgments on the common set:

| Condition | Mean | Standard deviation |
|---|---:|---:|
| Original / Bing | 1.808255 | 1.176560 |
| Yun Yi / Bing | 2.996131 | 0.094959 |
| Yun Yi / PromptArmor | 2.972485 | 0.254203 |

## Artifact and validation

Notebook: `tmp/compare_2021_original_vs_yun_yi_prompts.ipynb`

Executed in place with:

```bash
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_original_vs_yun_yi_prompts.ipynb
```

Execution completed successfully. The populated notebook includes coverage auditing, paired effect estimates, score and shift distributions, transition heatmaps, query-level effects, and examples showing the end of the original passage beside the exact appended Yun Yi suffix.

## PromptArmor v2 extension

The same notebook was extended and re-executed after the independent rerun was saved as:

- V2 successful ledger: `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v2/gpt-oss-20b/2021/judgments.jsonl`
- V2 failure ledger: `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v2/gpt-oss-20b/2021/failed.jsonl`

V2 coverage was 2,334 completed tasks and 61 failed tasks, with all 2,395 expected task identities represented. The common completed set across original, Yun Yi/Bing, PromptArmor v1, and PromptArmor v2 contained 2,266 candidates.

### Four-way matched result matrix

| Comparison | Mean delta | 95% bootstrap CI | Exact agreement | Lower rate | Higher rate |
|---|---:|---:|---:|---:|---:|
| Yun Yi / Bing minus Original | +1.183 | [+1.134, +1.231] | 44.6% | 0.0% | 55.3% |
| Yun Yi / PromptArmor v1 minus Original | +1.160 | [+1.112, +1.210] | 45.4% | 0.2% | 54.4% |
| PromptArmor v1 minus Bing on Yun Yi | -0.023 | [-0.034, -0.012] | 98.5% | 1.3% | 0.2% |
| Yun Yi / PromptArmor v2 minus Original | +1.170 | [+1.121, +1.219] | 44.8% | 0.2% | 54.9% |
| PromptArmor v2 minus Bing on Yun Yi | -0.012 | [-0.022, -0.004] | 99.1% | 0.7% | 0.2% |
| PromptArmor v2 minus PromptArmor v1 | +0.011 | [-0.003, +0.024] | 98.0% | 0.7% | 1.3% |

The v2-v1 interval crosses zero, so this matched rerun does not establish a systematic difference between the two PromptArmor runs. The notebook now includes v2 in every relevant audit, distribution, transition, query-level, and example table or plot.

## PromptArmor v4 wiring

The notebook source was extended to read PromptArmor v4 from `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v4/gpt-oss-20b/2021/`, add v4 comparisons against original, Bing, v1, and v2, and include v4 in all plots and example tables. A completeness guard now stops analysis if any ledger represents fewer than the expected 2,395 task identities.

At the time of this edit, v4 was incomplete: 256 successful rows and 2 failed rows (258/2,395 identities), while the `uv` wrapper process remained present and the files had stopped growing. Consequently, the notebook was syntax-validated but deliberately not executed against the partial v4 snapshot. All code cells parsed successfully with Python's `ast` parser. The notebook should be executed in place after the v4 success and failure ledgers total 2,395 unique tasks.

### Completed v4 result

After resuming, v4 contained 2,368 successful tasks and 44 physical failure rows. Those failure rows represent 43 unique failed tasks, and 16 task identities occur in both success and failure ledgers because a resume attempt later succeeded. The union accounts for all 2,395 expected task identities with no missing tasks.

The notebook was executed successfully after completion. The strict common-success set across all five conditions contains 2,244 candidates. V4's mean judgment on this set is 2.976827.

| V4 comparison | Mean delta | 95% bootstrap CI | Exact agreement | Lower rate | Higher rate |
|---|---:|---:|---:|---:|---:|
| V4 minus Original | +1.162 | [+1.114, +1.211] | 44.8% | 0.4% | 54.8% |
| V4 minus Yun Yi / Bing | -0.019 | [-0.030, -0.009] | 98.7% | 1.2% | 0.2% |
| V4 minus PromptArmor v1 | +0.003 | [-0.012, +0.016] | 97.6% | 1.2% | 1.2% |
| V4 minus PromptArmor v2 | -0.007 | [-0.020, +0.006] | 98.1% | 1.2% | 0.7% |

Both v4-v1 and v4-v2 confidence intervals cross zero, providing no clear evidence of a systematic difference among these PromptArmor runs on the common completed candidates.

## Corrected PromptArmor v4 replacement (2026-08-11)

The prior `promptarmor-v4` condition above was subsequently proven mislabeled: its command selected `--prompt-type promptarmor`, because v4 had not yet been wired into the CLI/renderer. After wiring `promptarmorv4`, a clean evaluation was saved under:

- Corrected v4 successes: `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v4-corrected/gpt-oss-20b/2021/judgments.jsonl`
- Corrected v4 failures: `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v4-corrected/gpt-oss-20b/2021/failed.jsonl`

The corrected run has 2,290 successes and 105 failures, accounting for all 2,395 expected task identities. The notebook now points to this corrected directory and labels the condition `Yun Yi / PromptArmor v4 (corrected)`. The previous mislabeled v4 artifact is no longer read by the notebook.

The strict common-success set across all five conditions contains 2,164 candidates. Corrected v4 has a mean judgment of 1.853050, compared with 1.826248 for original and 2.995841 for Yun Yi/Bing.

| Corrected v4 comparison | Mean delta | 95% bootstrap CI | Exact agreement | Lower rate | Higher rate |
|---|---:|---:|---:|---:|---:|
| Corrected v4 minus Original | +0.027 | [-0.000, +0.055] | 72.7% | 13.2% | 14.1% |
| Corrected v4 minus Yun Yi / Bing | -1.143 | [-1.192, -1.093] | 44.6% | 55.3% | 0.1% |
| Corrected v4 minus PromptArmor v1 | -1.120 | [-1.167, -1.070] | 45.3% | 54.4% | 0.3% |
| Corrected v4 minus PromptArmor v2 | -1.130 | [-1.179, -1.080] | 45.0% | 54.7% | 0.3% |

This corrected result reverses the earlier conclusion: the marker-aware v4 prompt removes almost all of the injection-induced score inflation and returns judgments close to the uninjected baseline.

## Remove PromptArmor v2 (2026-08-11)

At the user's request, PromptArmor v2 was removed from the notebook's inputs, audit, common-set join, effect calculations, distributions, transition heatmaps, query summaries, and passage examples. The notebook now compares four conditions: original/Bing, Yun Yi/Bing, PromptArmor v1, and corrected PromptArmor v4.

The notebook executed successfully after the removal. The common-success set increased from 2,164 to 2,223 candidates. On this four-way set, corrected v4 has mean 1.846154 versus 1.821413 for original and 2.995951 for Yun Yi/Bing.

| Corrected v4 comparison | Mean delta | 95% bootstrap CI | Exact agreement | Lower rate | Higher rate |
|---|---:|---:|---:|---:|---:|
| Corrected v4 minus Original | +0.025 | [-0.002, +0.052] | 72.7% | 13.1% | 14.1% |
| Corrected v4 minus Yun Yi / Bing | -1.150 | [-1.197, -1.101] | 44.4% | 55.5% | 0.1% |
| Corrected v4 minus PromptArmor v1 | -1.126 | [-1.175, -1.078] | 45.1% | 54.6% | 0.3% |
