# Related-topic language comparison notebook

Created and executed:

`tmp/compare_2021_related_topic_languages.ipynb`

The exact persistent input files are:

- `evaluation-results/llm-judge-robustness/original/gpt-oss-20b/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/related-topic/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/related-topic/hebrew/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/related-topic/chinese/2021.judgments.jsonl`
- `evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/related-topic/vietnamese/2021.judgments.jsonl`

The notebook treats JSONL ordering as attempt order, retains the latest record
per `task_id`, and then removes any duplicate `(qid, docid)` pair. Only
`status == "completed"` rows enter comparisons. Cross-version metrics use the
intersection completed in all five versions.

Execution audit:

| Version | Physical rows | Unique tasks | Retries | Completed | Failed |
|---|---:|---:|---:|---:|---:|
| Original | 2,395 | 2,395 | 0 | 2,382 | 13 |
| English | 2,395 | 2,395 | 0 | 2,384 | 11 |
| Hebrew | 2,413 | 2,395 | 18 | 2,392 | 3 |
| Chinese | 2,395 | 2,395 | 0 | 2,385 | 10 |
| Vietnamese | 2,395 | 2,395 | 0 | 2,377 | 18 |

The common completed comparison set contains 2,342 candidates. Mean judgments
on that set were: original 1.807857, English 2.004697, Hebrew 1.991460,
Chinese 1.965841, and Vietnamese 2.005551.

The executed notebook contains the full result matrices: coverage audit,
descriptive statistics, label distributions, paired deltas relative to the
original, exact-agreement and mean-absolute-difference heatmaps, per-query
effects, and the 40 largest cross-language passage disagreements.

Validation command:

```bash
uv run --group notebook jupyter nbconvert --to notebook --execute --inplace tmp/compare_2021_related_topic_languages.ipynb
```

All cells executed successfully.

Follow-up: changed the final disagreement table to show the last 700 characters
of each passage in `*_ending` columns. This exposes the appended distractors
instead of spending the table width on the shared passage beginnings. The
notebook was re-executed successfully after the change.

Correction: a 700-character tail could still begin in shared English passage
text, and pandas then truncated the cell from that beginning. Replaced it with
exact suffix extraction after whitespace-normalizing the original passage. The
final table now has `english_distractor`, `hebrew_distractor`,
`chinese_distractor`, and `vietnamese_distractor` columns containing only the
appended content. All 40 displayed rows matched their original prefix; no
fallback/prefix-mismatch rows occurred. Re-execution succeeded.
