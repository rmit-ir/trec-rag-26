# Hebrew, Chinese, and Vietnamese 2021 robustness evaluation

Selected languages: Hebrew, Chinese, and Vietnamese. Scoped the evaluation to
2021 to match the existing original/English experiment; expanding all three
years would increase the requested paid judging from 28,740 to about 90,000
candidate judgments.

Validated all translated distractor inputs before injection. Each of the four
categories contained 51 translated distractors for 2021 in every selected
language. Injection appended those distractors to 2,291 of 2,398 source CSV
rows per language/category. Conversion produced 12 RAGDOLL inputs, each with
the same raw input matrix: 54 queries and 2,395 candidates.

Persistent input paths follow:

`data/ragdoll-robustness/derived/ragdoll-inputs/distractors/<category>/<language>/2021.requests.jsonl`

where category is `related-topic`, `hypothetical`, `negation`, or
`modal-statement`, and language is `hebrew`, `chinese`, or `vietnamese`.

Added the resumable paid-run wrapper:

`tasks/llm_judge_robustness/scripts/run_ragdoll_multilingual_2021.sh`

It writes judgments to:

`evaluation-results/llm-judge-robustness/distractors/gpt-oss-20b/<category>/<language>/2021.judgments.jsonl`

No paid evaluation was launched in the agent environment because it contained
no AWS access key, profile, or session credentials. The wrapper validates AWS
identity before starting and passed Git Bash syntax validation.

Created and executed:

`tmp/compare_2021_multilingual_distractor_relevance.ipynb`

The notebook's complete raw inputs are the original 2021 judgments, the four
English category judgment files, and the 12 multilingual paths above. It pairs
on `(qid, docid)`, excludes non-completed records, and preserves the full result
matrix in coverage tables, paired summaries, language/category delta heatmaps,
distribution plots, and largest-change passage tables. Its current execution
shows baseline results and pending multilingual files; rerunning after RAGDOLL
finishes refreshes all outputs.
