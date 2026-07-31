# RAGDOLL rubric comparison notebook

Date: 2026-07-31

Created `tmp/compare_rubric_unperturbed_injected.ipynb` to compare the fixed
rubric results in:

- `evaluation-results/aus-agent/rubric-unperturbed/scores`
- `evaluation-results/aus-agent/rubric-injected/scores`

The raw inputs are the three RAGDOLL score tables from each directory:
`run_scores.csv`, `cell_scores.csv`, and `category_failures.csv`.

At notebook creation time, both conditions contained 229 cells, 21 runs, and
110 unique query IDs. The notebook validates exact `(qid, run_id)` pairing
before computing:

- global mean and median changes;
- improved, unchanged, and worsened cell counts;
- per-run score changes;
- per-category failure changes;
- the 15 largest cell improvements and regressions;
- run-delta, category-failure, and paired-score plots.

Judgment comes directly from RAGDOLL's paired fixed-rubric scores. Positive
score deltas mean the injected answer scored higher; positive failure deltas
mean the injected answer failed more criteria.
