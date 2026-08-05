# GPT-5.6 Terra and GPT-OSS-20B rubric comparison notebook

Copied the existing Claude Opus 4.8 comparison notebook into
`tmp/compare_rubric_gpt56terra_gptoss20b.ipynb` and retargeted it to:

- `evaluation-results/aus-agent/gpt-5-6-terra/rubric-unperturbed`
- `evaluation-results/aus-agent/rubric-unperturbed`

The notebook was subsequently expanded to compare four conditions:

- GPT-5.6 Terra unperturbed
- GPT-5.6 Terra instruction-injected
- GPT-OSS-20B unperturbed
- GPT-OSS-20B instruction-injected
- GPT-5.6 Terra Chinese (`zh`) instruction-injected

All four current result sets contain normal rubric verdicts. Terra has 229
cells in each condition; GPT-OSS has 229 unperturbed cells and 637 injected
cells. The notebook therefore reports raw coverage but computes injection and
cross-judge deltas only on matched `(qid, run_id)` cells. It includes health
checks, aggregate score plots, four matched comparisons, delta distributions,
and per-system score/topic tables. The Terra `zh` condition contains 229 cells
and 5,631 valid criterion verdicts. Two additional matched comparisons measure
its change from Terra unperturbed and from Terra's standard injected answers.
