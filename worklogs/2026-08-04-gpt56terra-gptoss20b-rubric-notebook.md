# GPT-5.6 Terra and GPT-OSS-20B rubric comparison notebook

Copied the existing Claude Opus 4.8 comparison notebook into
`tmp/compare_rubric_gpt56terra_gptoss20b.ipynb` and retargeted it to:

- `evaluation-results/aus-agent/gpt-5-6-terra/rubric-unperturbed`
- `evaluation-results/aus-agent/rubric-unperturbed`

The notebook retains evaluation-health checks, verdict distributions,
aggregate ternary and binary scores, matched-cell differences, and per-system
comparisons. At inspection time, the newly timestamped GPT-5.6 Terra results
still contained 5,631 `failed` criterion verdicts across 229 completed rows, so
the notebook warns that the stored zero scores are not a valid quality result.
