# Plan v2: post-search relevance pass — two configurations, A/B tested before either ships

Revised after gpt-5.6-terra's review of v1 (`worklogs/assets/2026-08-06-terra-review-prefilter-plan.txt`).
Terra's central point: a mandatory semantic filter judged against the
`requirement` text is pointed at facets_agent's actual documented failure
mode (recall on IMPLICIT requirements the agent itself never wrote down),
since that same requirement text is what the judge filters against — a
useful document can be labeled `irrelevant` by a single-pass smaller judge
and be gone with no recourse. v1's "keep adjacent_not_relevant" compromise
doesn't fix this: a confidently-wrong `irrelevant` verdict isn't
`adjacent_not_relevant`.

**Resolution: don't commit to suppression. Build ONE mechanism, two
configurations, and measure which (if either) actually helps before either
becomes the default.**

## 1. One mechanism: `search_result_filter` harness hook

Unchanged shape from v1 in principle, revised for safety per terra's #9:

```python
@dataclass
class SearchResultPass:
    documents: list[dict]   # reordered and/or reduced view of the ORIGINAL
                             # documents this search returned
    note: str | None        # annotation for the tool-result payload

search_result_filter: Callable[[str, list[dict]], SearchResultPass] | None = None
```

Called after `execute_full_text_search`, before `ledger.stage(...)`, same
as v1. **Harness-side validation, not trust** (fixes terra's #9): every
document in `.documents` must have an `id` present in the ORIGINAL result
set — anything else (fabricated, duplicated, mutated) is dropped and
logged, never staged. `filtered_count`/`kept_count` are computed by the
harness from the id sets, never taken from the filter's own claim. Fail
open on any exception, timeout, or malformed judge response (per v1 §2.1,
unchanged) — keeps the ORIGINAL, unfiltered documents.

Batch size cap per terra's #8: judge at most the first 20 documents of one
search call (matching this repo's existing per-call result-count norms);
overflow beyond that stays unfiltered/unranked, appended after the judged
portion, never silently dropped.

## 2. Two configurations of the SAME underlying judge call

Both call the same batch judge (`agent_harness.tools.judge`'s prompt and
model, `openai.gpt-oss-120b-1:0`) once per search, getting a
`relevant`/`adjacent_not_relevant`/`irrelevant` verdict per document — the
mechanism cost (one judge round-trip per search) is IDENTICAL between the
two. They differ only in what happens to the verdicts:

- **Version A — "minimize"** (`src/systems/facets_agent/filtering.py::minimize_filter`):
  keep only `relevant`. Drops `adjacent_not_relevant` AND `irrelevant`.
  This is the version that actually tests the user's original hypothesis
  (does the main model do BETTER when it sees LESS) — deliberately more
  aggressive than v1's compromise, since a compromise config would leave
  the A/B underpowered to tell the two mechanisms apart.
- **Version B — "rank"** (`src/systems/facets_agent/filtering.py::rank_filter`,
  terra's suggested alternative): drops NOTHING — `documents` is the full
  original set, reordered `relevant` → `adjacent_not_relevant` →
  `irrelevant`, each annotated with its verdict inline (e.g. a
  `[judge: adjacent_not_relevant]` tag prepended to the result the model
  reads). Recall is structurally protected by construction (nothing is
  removed), so this configuration has none of terra's #1/#2 risk — it's
  testing whether ORDERING/ANNOTATING reduces wasted triage effort without
  the recall cost of dropping anything.

facets_agent's `run_agent` gets `search_result_filter=None` as its actual
default (neither config ships as the default from this plan — that
decision waits for §4's result), with A and B selectable for the
experiment runs.

## 3. What v1's §3 got wrong, and what replaces it (terra's #2/#3/#6/#7)

v1 proposed rubric-score comparison as the primary signal. Terra correctly
called this a noisy downstream proxy that can't attribute a score movement
to a specific filtered document, and pointed out v1's own §0 finding (
rejected docs are compacted, not persistent) undercuts the "frees effort
budget" mechanism v1 asserted without measuring.

This plan does not attempt a full counterfactual evidence-recall audit
(terra's #3 ideal) — out of scope for a same-day A/B on 15 topics. Instead,
it adds the DIRECT measurements terra's #6/#7 asked for, alongside the
outcome metric, so a result is at least interpretable rather than just a
score delta:

- **Direct** (free, from trajectories): searches-per-topic, tool-call
  count, processed/peak context tokens, words in final answer — tests
  whether Version A actually reduces volume and whether Version B's
  ordering changes search behavior at all.
- **Verdict distribution per search**: relevant / adjacent_not_relevant /
  irrelevant counts — sanity-checks the judge isn't degenerate (all-one-
  label) before trusting anything downstream.
- **Outcome** (the existing tooling): rubric arena + per-criterion
  scorecard, run THREE ways on the same 15-topic sample — A vs aus_agent
  subset, B vs aus_agent subset, and **A vs B directly** (the user's
  explicit ask), since a head-to-head removes aus_agent as a shared
  confound and answers "which config is better" more directly than two
  separate comparisons against a third system.
- Explicitly flagged as a limitation, not silently glossed over: this
  remains an outcome-metric comparison, not a recall audit. A result here
  is suggestive, not proof either mechanism is safe at full scale.

## 4. Experiment

- Sample 15 of the 30 research-rubrics dev topics (50%), fixed random
  seed, saved qid list for reproducibility.
- Generate facets_agent on those 15 topics twice: once with Version A,
  once with Version B, same SHA otherwise, distinct run-ids.
- Reuse the EXISTING `aus-agent-dev30-20260806` and
  `facets-agent-dev30-e2708ab` (today's no-filter baseline) answers for
  those same 15 qids — no need to regenerate either; both are unaffected
  by this change and already cover all 30 topics.
- Score: A vs aus_agent(15), B vs aus_agent(15), baseline vs aus_agent(15)
  (for a three-way reference point), and A vs B directly.

## 5. Tests

- `search_result_filter=None`: byte-identical (same pattern as
  `pre_final_hook`'s absent-hook test).
- Harness-side id validation: a filter that returns a fabricated id is
  dropped, not staged (directly tests terra's #9 fix).
- Fail-open: filter exception leaves all original documents staged.
- Batch cap: more than 20 documents in one search — first 20 judged,
  remainder passed through unfiltered/unranked, never dropped.
- `minimize_filter`: keeps only `relevant`, drops the other two.
- `rank_filter`: keeps ALL original documents (count-preserving,
  regardless of verdict), reordered by verdict.

## 6. Explicitly deferred

- terra's #14 (safe hard-filters first: exact duplicates, boilerplate,
  already-seen-under-this-requirement) — a genuinely different, lower-risk
  mechanism than semantic judging, not built here, worth its own
  experiment if both A and B disappoint.
- Snippet extraction (v1 §2.4) — still gated on this experiment's result;
  more invasive than either config here.
- A full evidence-recall audit (terra's #3) — if either config looks
  promising on this 15-topic sample, that audit is the right next gate
  before a 30-topic or default-on decision, not this same-day pass.
