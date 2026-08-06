# Plan: mandatory pre-filter — a cheap model judges each search result before facets_agent's main model ever sees it

## 0. Grounding: what the verification actually showed

From this session's dev30 measurement (30 topics, `facets-agent-dev30-e2708ab`
vs `aus-agent-dev30-20260806`):

- facets_agent uses ~2.1x aus_agent's peak context tokens (75.3K vs 33.1K)
  and sees ~2.1x the documents (156 vs 75.5).
- **Committed (persistent, full-text) document count is comparable to
  aus_agent** (14.8 vs 16.1 avg) — the gap is entirely in REJECTED volume
  (150.5 vs 63.6, 2.4x), which gets compacted to a one-line marker after
  one turn, not permanently retained.
- Within facets_agent's own 30 topics, doc/context volume has ~zero
  correlation with that topic's own rubric grade (r=0.05 docs seen, r=0.04
  peak context, r=0.12 committed count).

Conclusion: this is NOT evidence of context-dilution/confusion (no
dose-response). It IS evidence of wasted turn/effort budget — reading and
triaging ~150 mostly-irrelevant results per topic is real cost that
competes with the two things the prior loss-factor analysis
(`worklogs/2026-08-06-facets-agent-loss-factor-analysis.md`) found actually
drive the rubric gap: incomplete implicit-requirement decomposition
(47.8% of weighted loss) and shallow synthesis specificity (47.4%). The
case for pre-filtering is "stop burning the model's effort on manual
triage, spend it on decomposition/synthesis instead" — not "reduce context
size because size itself hurts."

## 1. The central risk this plan has to design around

`PLAN.md` §1's own history is a direct warning here: aus_agent's round-one
anti-seeding rule was DELIBERATELY not applied to facets_agent because
facets_agent's measured failure is **false negatives (recall)**, not false
positives — "0 invented-docid repairs, 0 protocol violations... importing a
precision constraint into a system whose deficit is recall is the wrong
trade." A mandatory pre-filter that drops results before the main model
ever sees them is exactly a precision instrument. If the judge is
imperfect (it will be — it's a smaller model doing single-pass triage) and
filters out a document that was actually useful, that requirement silently
loses evidence it would otherwise have had a chance at, with no recourse —
unlike the OPT-IN `judge_relevance` tool (Phase 4b, already shipped), where
the main model sees the judge's opinion but keeps deciding for itself.
**This plan must be conservative about what it filters, must fail open on
judge error or uncertainty, and must be measured against RECALL regressions
specifically, not just token savings.**

## 2. Design

### 2.1 New harness hook: `search_result_filter`

`agent_harness/agent.py::run_agent`, new optional parameter:

```python
search_result_filter: Callable[[str, list[dict]], SearchFilterResult] | None = None
```

Called once per `search` tool call, after `execute_full_text_search`
returns but before `ledger.stage(...)` — the one point in the loop where
raw results exist but haven't entered the model's context yet. Receives
the call's `requirement` argument (facets_agent's own field; `""` for a
caller without one) and the returned `documents` list. Returns a
`SearchFilterResult(kept: list[dict], filtered_count: int, note: str |
None)`. `None` (the default) means no filtering — byte-identical to today
for every caller that doesn't pass it, same discipline as `pre_final_hook`
and `judge_tool`.

**Fail-open, not fail-closed**: if the filter raises, times out, or returns
something unusable, the harness keeps ALL original documents and proceeds
— a broken judge call must never silently starve a facet of evidence. This
mirrors `judge_relevance`'s own "a tool call cannot fail the run" principle,
now applied to something that sits in the mandatory path rather than an
optional side-call.

**Transparency**: the search tool's result payload gets one line noting
`N of M results filtered as not relevant to "<requirement>"` when filtering
happened, so the model isn't confused by a search that appears to have
returned less than it asked for, and can react (broaden the query, drop the
requirement framing) rather than silently miss the signal.

### 2.2 facets_agent's filter function

`src/systems/facets_agent/filtering.py` (new), reusing
`agent_harness.tools.judge`'s existing batch-verdict machinery — literally
the same judge call `judge_relevance` already makes, just invoked
automatically per search instead of at the model's discretion:

- ONE judge call per search (batching all of that call's documents
  together), not one per document — cost/latency control.
- **Keep `relevant` AND `adjacent_not_relevant`; drop only `irrelevant`.**
  This is the conservative choice §1 requires: the hardest, most
  useful-when-right category (`adjacent_not_relevant`) is exactly the one
  most likely to contain false negatives from a smaller judge model
  operating on a single pass with no chance to reconsider — so it stays in
  front of the main model, which can still reject it, rather than being
  silently discarded before the main model gets a vote. This trades away
  some of the token savings the design is chasing, deliberately, in
  exchange for not reopening the recall problem Phase 1–3 fixed.
- On judge failure/timeout/malformed response: keep everything (fail
  open, per §2.1).
- On a requirement missing/empty (shouldn't happen — facets_agent's schema
  requires it — but defensively): keep everything, don't filter blind.

### 2.3 Cost / latency

Every `search` call now costs one extra judge round-trip (a real, new
per-search wall-clock cost — in tension with "search is cheap" only in the
sense that a SEARCH call gets slower, not that fewer searches should be
run; the number of searches the model chooses to make is untouched). At
~18 searches/topic × 30 topics, that's ~540 extra judge calls for one
dev30 run — cheap in dollars (same judge model already used for
`judge_relevance`/RAGDoll support judging), but adds real latency per
search. Not parallelizable against the search itself (results must exist
before they can be judged), though independent parallel `search` calls
within one turn can have their filter calls run concurrently the same way
`_execute_tool_calls` already parallelizes the searches themselves.

### 2.4 Snippet extraction — phase 2, NOT built now, gated on phase 1's result

If filtering alone doesn't move the rubric grade, the next lever is
shrinking each KEPT document to just its relevant span rather than full
text — a bigger change (alters what `documents_from_search`/staging
carries, likely needs its own judge call per kept document to extract the
span, multiplying the per-search judge cost again). Deliberately deferred:
building this before knowing whether filtering alone helps would spend a
second, more invasive change on an unvalidated first one.

## 3. Validation plan

Re-run the same 30-topic dev set with `search_result_filter` on, same SHA
otherwise, new run-id. Compare against `facets-agent-dev30-e2708ab`
(today's Phase 4a baseline) and `aus-agent-dev30-20260806` on:

- **Primary (recall regression guard, per §1)**: rubric `criterion_tally`
  by axis — specifically watch whether `Implicit`/`Explicit Criteria` grades
  get WORSE on any topic relative to today's baseline, not just whether the
  aggregate moves. A net win that hides individual recall losses is the
  failure mode this whole plan is designed to avoid.
- rejected-doc count and peak context tokens (should drop substantially —
  the mechanism being tested).
- searches-per-topic (does the model search MORE because each search now
  yields fewer usable-looking results, offsetting token savings?).
- rubric pairwise preference rate and clean-win counts (the outcome
  metric).
- filtered_count distribution (how aggressive is the judge actually being
  — a sanity check the filter isn't accidentally dropping everything or
  nothing).

**Cheap gate before the full 30-topic spend**: run on a handful of topics
first (reusing the pattern from the original ledger plan's own "cheap gate
before spending any of it" — `PLAN.md` §5's four-topic check) and inspect
filtered-out documents by hand on at least one topic, to catch an obviously
broken or over-aggressive judge before spending the full run.

## 4. Tests

- `search_result_filter=None` (default): byte-identical to today, same
  pattern as `test_pre_final_hook.py`'s "absent hook" test.
- A filter that returns a subset: staged documents match the subset, the
  compacted note appears in the result payload, filtered documents never
  reach `ledger.stage`.
- Fail-open: a filter that raises leaves ALL documents staged, doesn't
  fail the run.
- facets_agent's own `filtering.py`: unit tests mirroring
  `test_judge_tool.py`'s pattern (missing requirement, judge exception,
  `irrelevant`-only dropped, `adjacent_not_relevant` kept) — this is the
  test that actually encodes and protects §2.2's conservative-keep
  decision, so a future change can't silently make it more aggressive
  without a test failing.

## 5. Sequencing

1. Harness hook (`search_result_filter`) + facets_agent's `filtering.py`,
   tests, full suite.
2. Cheap gate: 4-topic run, hand-inspect filtered docs on one topic.
3. Full 30-topic re-run, version-tagged, compared against today's
   baseline per §3.
4. Decision point: if recall holds and grade/token metrics improve, keep
   it on by default (mirroring how `pre_final_hook`/`judge_tool` are on by
   default for facets_agent). If recall regresses on any topic, revert to
   `None` and write up why before considering §2.4.
