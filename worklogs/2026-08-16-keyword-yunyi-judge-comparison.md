# Keyword vs Yun Yi judge comparison notebook

Updated `tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb` to compare 2021 keyword and Yun Yi passage injections under both the UMBRELA Bing prompt and PromptArmor v4.

## Issue fixed

The prior notebook calculated Krippendorff's alpha before constructing its matched DataFrames, causing a `NameError` when cells ran top to bottom. Earlier iterations also referenced the wrong Yun Yi result layout. Yun Yi Bing results are under `yun_yi/umbrela-bing/.../2021/judgments.jsonl`; Yun Yi v4 results are under `yun_yi/promptarmor-v4/.../2021/judgments.jsonl`.

## Inputs

- `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/keywords/promptarmor-v4/gpt-oss-20b/2021/judgments.jsonl`
- `evaluation-results/llm-judge-robustness/yun_yi/umbrela-bing/gpt-oss-20b/2021/judgments.jsonl`
- `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v4/gpt-oss-20b/2021/judgments.jsonl`

The notebook keeps the latest completed 0–3 judgment per `(qid, docid)` and restricts comparisons to the intersection shared by all four runs. It produces a coverage audit, grouped label chart, pairwise effect/agreement table, nominal Krippendorff alpha, delta plots, confusion matrices, and passage-tail examples.
