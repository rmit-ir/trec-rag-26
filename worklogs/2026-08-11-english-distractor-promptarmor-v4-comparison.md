# English distractor PromptArmor v4 comparison

Date: 2026-08-11

## Objective

Evaluate the 2021 English related-topic distractor passages with the corrected PromptArmor v4 prompt and compare their relevance-label distribution against corrected v4 on Yun Yi, Yun Yi with Bing, and the original uninjected Bing baseline.

## Exact evaluation input

`data/ragdoll-robustness/derived/ragdoll-inputs/distractors/related-topic/2021.requests.jsonl`

The input contains 54 query rows and 2,395 candidate passages.

The requested output location is:

`evaluation-results/llm-judge-robustness/distractors/promptarmor-v4/gpt-oss-20b/related-topic/english/2021/`

The evaluation must use `--prompt-type promptarmorv4`; `--prompt-type promptarmor` would select the old vulnerable prompt.

## Comparison notebook

Created `tmp/compare_2021_v4_yun_yi_vs_english_distractor.ipynb`. It compares:

1. Original uninjected / Bing
2. Yun Yi / Bing
3. Yun Yi / corrected PromptArmor v4
4. English related-topic distractor / corrected PromptArmor v4

The notebook audits success/failure coverage, refuses to plot incomplete ledgers, intersects successful `qid`/`docid` candidates across all four conditions, and produces a grouped relevance-label proportion chart plus count/mean/standard-deviation summary. Its JSON and every Python code cell were syntax-validated.

## Launch status

An attempted Bedrock launch from the managed execution environment was rejected before execution by the approval service. No output directory or partial evaluation artifacts were created. The exact command was handed off for execution in the user's authenticated terminal. The notebook should be executed only after the success and failure ledgers together account for all 2,395 task identities.

## Completed evaluation and notebook execution

The user subsequently completed and cleaned the evaluation. Final English distractor v4 coverage was 2,381 successes and 14 failure-only tasks, accounting for all 2,395 expected task identities.

The notebook was executed successfully in place. Its common completed set contains 2,246 candidates. The complete mean-distribution summary on that set is:

| Condition | Count | Mean | Standard deviation |
|---|---:|---:|---:|
| Original / Bing | 2,246 | 1.819 | 1.175 |
| Yun Yi / Bing | 2,246 | 2.996 | 0.097 |
| Yun Yi / corrected PromptArmor v4 | 2,246 | 1.842 | 1.165 |
| English related-topic distractor / corrected PromptArmor v4 | 2,246 | 2.012 | 0.994 |

The English distractor v4 mean is approximately +0.192 above original, +0.169 above Yun Yi v4, and -0.984 below Yun Yi/Bing. The populated notebook contains the requested grouped relevance-label distribution chart with a shared denominator across all four conditions.
