# Add GPT-OSS-120B to keyword comparison

## Change

Updated `tmp/compare_2021_keywords_gpt_oss_vs_gpt_5_6_terra.ipynb` to load
`evaluation-results/llm-judge-robustness/keywords/gpt-oss-120b/bing/2021/judgments.jsonl`.

The notebook now includes a three-model section for GPT-OSS 20B, GPT-OSS 120B,
and GPT-5.6 Terra. It reports the label distribution and pairwise agreement for
the intersection of completed `(qid, docid)` tasks.

## Execution

Executed with:

```bash
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_keywords_gpt_oss_vs_gpt_5_6_terra.ipynb
```

The executed notebook found 2,383 common completed tasks. Input completion
counts were 2,387 for GPT-OSS 20B, 2,391 for GPT-OSS 120B, and 2,395 for
GPT-5.6 Terra.
