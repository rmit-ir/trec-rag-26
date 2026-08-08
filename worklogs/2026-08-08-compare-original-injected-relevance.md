# Compare original and distractor-injected 2021 relevance judgments

Created and executed:

`tmp/compare_2021_original_vs_injected_relevance.ipynb`

The notebook reads the complete JSONL records from these persistent inputs:

- `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/related-topic/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/hypothetical/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/negation/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/modal-statement/2021.judgments.jsonl`

It preserves the full result matrices and raw passage examples in its executed
cell outputs. Records are paired on `(qid, docid)`; only `status == "completed"`
rows enter relevance comparisons. Failed and not-yet-produced rows remain
visible in the coverage audit rather than being silently treated as judgments.

Analysis includes coverage/failure counts, original and injected score
distributions, mean/median paired deltas, changed/decreased/increased rates,
row-normalized transition matrices, query-level effects, and the largest
passage-level changes.

Validation command:

```bash
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_original_vs_injected_relevance.ipynb
```

Added `seaborn` to the root `notebook` dependency group because notebooks in
this repository use that group exclusively. The executed validation completed
successfully.
