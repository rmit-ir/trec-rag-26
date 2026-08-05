# Terra unperturbed, leet, and zh rubric comparison

Created `tmp/compare_rubric_terra_unperturbed_leet_zh.ipynb` as a focused copy
of the broader judge comparison notebook. It loads only:

- `evaluation-results/aus-agent/gpt-5-6-terra/rubric-unperturbed`
- `evaluation-results/aus-agent/gpt-5-6-terra/rubric-instruct-injected-leet`
- `evaluation-results/aus-agent/gpt-5-6-terra/rubric-instruct-injected-zh`

Each condition contains 229 rows and normal rubric verdicts. The notebook
checks evaluation health and coverage, compares aggregate scores, and computes
matched-cell ternary-score deltas for leet versus unperturbed, zh versus
unperturbed, and zh versus leet. It also includes per-system score and topic
tables.
