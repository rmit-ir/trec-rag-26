# Original 2021 RAGDOLL relevance input

Extended `tasks/llm_judge_robustness/scripts/build_ragdoll_relevance_inputs.py`
with `--original` so untouched gold TREC-DL CSVs can be converted without
pretending they are a distractor category.

Command run:

```bash
uv run --project tasks/llm_judge_robustness python tasks/llm_judge_robustness/scripts/build_ragdoll_relevance_inputs.py --original --years 2021 --overwrite
```

Input:

`data/ragdoll-robustness/gold/trec-dl/trec_dl_2021.csv`

Output:

`data/ragdoll-robustness/derived/ragdoll-inputs/original/2021.requests.jsonl`

Conversion result: 54 queries and 2,395 candidates.
