# Instruction-annotation rubric comparison

Date: 2026-07-31

The new `rubric-instruct-injected/graded.jsonl` contained 637 rows for 229
unique `(qid, run_id)` cells. Every cell appeared two or three times because
the evaluation was rerun into the same output without resume/overwrite. None
of the rows contained a technical `failed` verdict.

Added `scripts/dedupe-ragdoll-graded.py`, which retains the last occurrence of
each `task_id` without modifying the source artifact. The clean derived inputs
and scores are:

- `evaluation-results/aus-agent/rubric-instruct-injected/graded.deduped.jsonl`
- `evaluation-results/aus-agent/rubric-instruct-injected/scores-deduped/`

The comparison notebook uses the deduplicated scores so each answer cell has
equal weight against the 229-cell unperturbed baseline.
