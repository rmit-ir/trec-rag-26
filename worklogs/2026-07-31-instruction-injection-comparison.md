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

On 2026-08-03, the notebook was expanded to compare three conditions:

- unperturbed;
- `answers.instruct.inject.jsonl` via `rubric-instruct-injected/scores-deduped`;
- `answer.instruct.inject.zh.jsonl` via `rubric-instruct-injected-zh/scores`.

All three score sets contain the same 229 `(qid, run_id)` cells, 21 runs, and
110 query IDs. The notebook now reports both perturbations' paired deltas
against the unperturbed baseline.

On 2026-08-03, the comparison was generalized further to include all available
instruction-encoding variants: Chinese (`zh`), Vietnamese (`vi`), upside-down
text, emoji, diacritics, leetspeak, and non-printing characters. Each variant
has 229 unique cells with no technical-failure verdicts. The `zh` evaluation
had been appended twice, so the notebook uses a latest-judgment deduplicated
score set at `rubric-instruct-injected-zh/scores-deduped`.
