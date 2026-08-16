# Regular versus modified UMBRELA notebook

Created and executed:

`tmp/compare_2021_regular_vs_modified_umbrela.ipynb`

Exact primary inputs:

- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/related-topic/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/umbrela-2/gpt-oss-20b/related-topic/english/2021.judgments.jsonl`

Optional separate failure input, read automatically when present:

- `evaluation-results/llm-judge-robustness/umbrela-2/gpt-oss-20b/related-topic/english/2021.failed.jsonl`

The notebook retains the latest JSONL attempt per `task_id`, deduplicates by
`(qid, docid)`, restricts paired analysis to candidates completed by both
prompts, and reports coverage/retries/failures explicitly. It includes overall
mean and exact-agreement metrics, score distributions, modified-minus-regular
deltas, count and row-normalized transition heatmaps, per-query effects, and
the 50 largest passage-level disagreements. All cells executed successfully.

Follow-up fix: after an `--overwrite` launch, the modified primary file can be
temporarily absent until the first successful judgment. `read_jsonl()` formerly
returned a columnless DataFrame in that state, causing `KeyError: 'task_id'` in
the audit. Empty or absent inputs now return a typed judgment DataFrame with the
expected schema, and the paired cell prints that modified successes are not yet
available. Re-executed the entire notebook successfully with the modified file
absent and only an empty live-run log present.
