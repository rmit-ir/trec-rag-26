# Released evaluation scores review

Reviewed the previously untracked `RMIT-ADM+S scores/` directory before committing
and pushing it. This adds the supplied evaluation TSVs, batch topic lists,
evaluation README, local score summary, and standalone scoring reference.

## Finding and correction

`SCORES.md` said the Batch 2 Bradley–Terry confidence intervals did not overlap.
The supplied intervals are 1006.6–1091.4 for `owa-glm5-t119` and
1081.0–1168.4 for `sol-research-first`, so they overlap. Corrected the takeaway
to describe the point estimates and avoid inferring significance from intervals.
No other blocking issue found for a local, single-process scoring CLI.

## Validation

- Checked all seven TSVs for unique run/narrative keys, team identity, topic
  coverage, aggregate means (within published rounding), summed preference
  counts, and confidence interval bounds.
- Checked the summary's rubric/nugget batch values and all 14 merged metric
  pairs against the published `all` rows and `(17 * B1 + 25 * B2) / 42`.
- Added hermetic tests for the documented CLI invocation, partial-support
  exclusion, missing-topic completion and rejection, zero vital denominators,
  invalid assignment labels, and half-up rounding.
- Full suite: `UV_CACHE_DIR=/tmp/trec-rag-uv-cache bash scripts/test.sh` —
  1,970 passed, 12 live tests deselected, no skips. One existing Starlette
  deprecation warning. The initial sandbox attempt could not download locked
  dependencies; the network-enabled retry passed.

The original assignment JSONL and grading prompts are withheld, so the released
scores cannot be independently reproduced from judgments. The tests use synthetic
assignments. No external services or LLM judges were called.
