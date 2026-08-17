# Keyword vs Yun Yi judge comparison notebook

Updated `tmp/compare_2021_keywords_before_after_promptarmor_v4.ipynb` to compare 2021 keyword and Yun Yi passage injections under both the UMBRELA Bing prompt and PromptArmor v4.

## Issue fixed

The prior notebook calculated Krippendorff's alpha before constructing its matched DataFrames, causing a `NameError` when cells ran top to bottom. Earlier iterations also referenced the wrong Yun Yi result layout. Yun Yi Bing results are under `yun_yi/umbrela-bing/.../2021/judgments.jsonl`; corrected Yun Yi v4 results are under `yun_yi/promptarmor-v4-corrected/.../2021/judgments.jsonl`. The similarly named `yun_yi/promptarmor-v4/` directory is a known mislabeled run produced with the older `promptarmor` renderer and must not be used as v4 evidence.

## Inputs

- `evaluation-results/llm-judge-robustness/keywords/gpt-oss-20b/bing/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/keywords/promptarmor-v4/gpt-oss-20b/2021/judgments.jsonl`
- `evaluation-results/llm-judge-robustness/yun_yi/umbrela-bing/gpt-oss-20b/2021/judgments.jsonl`
- `evaluation-results/llm-judge-robustness/yun_yi/promptarmor-v4-corrected/gpt-oss-20b/2021/judgments.jsonl`

The notebook keeps the latest completed 0–3 judgment per `(qid, docid)` and restricts comparisons to the intersection shared by all four runs. It produces a coverage audit, grouped label chart, pairwise effect/agreement table, nominal Krippendorff alpha, delta plots, confusion matrices, and passage-tail examples.

The original/Bing ledger is registered in `RUN_PATHS` alongside the four injected runs, so it appears in the coverage audit and distribution chart. A separate `MATCHED_RUN_ORDER` restricts paired calculations to the four injected runs: the original ledger's candidate identities differ from those runs and have no `(qid, docid)` overlap. The final figure presents the original distribution as an explicitly unpaired reference with its own sample size.

All notebook code cells now contain concise comments explaining their data provenance, cleaning and alignment rules, statistical calculations, plot construction, and example selection logic.

At the user's request, every cell below the relevance-label distribution graph was removed. The notebook now ends after the distribution table and grouped distribution chart; pairwise statistics, delta plots, confusion matrices, and disagreement examples are no longer included.
