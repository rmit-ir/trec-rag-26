# Claude Opus 4.8 and GPT-OSS-20B rubric comparison notebook

Created `tmp/compare_rubric_opus48_gptoss20b.ipynb` to compare the completed
unperturbed RAGDOLL rubric evaluations:

- `evaluation-results/aus-agent/opus-4-8/rubric-unperturbed`
- `evaluation-results/aus-agent/rubric-unperturbed`

The notebook compares evaluation health, criterion-verdict distributions,
aggregate ternary and binary scores, matched `(qid, run_id)` cells, and
per-system scores.

During input inspection, both runs contained 229 rows marked `completed`.
However, Claude Opus 4.8 contained 5,631 criterion verdicts recorded as `failed`,
while GPT-OSS-20B contained normal satisfied, partially-satisfied, and
not-satisfied verdicts. The notebook therefore reports invalid-verdict rates
before score plots and warns that the all-zero Opus 4.8 scores currently
represent an evaluation/parsing failure rather than evidence that the answers
are uniformly poor.
