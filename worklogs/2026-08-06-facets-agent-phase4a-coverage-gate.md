# 2026-08-06 — facets_agent Phase 4a: the coverage gate, shipped

Follow-up to `worklogs/2026-08-06-facets-agent-loss-factor-analysis.md` (the
gpt-5.6-sol root-cause diagnosis: aus_agent's rubric edge splits ~evenly
between `not_decomposed`, 47.8%, and `covered_but_shallow`, 47.4%). Three
follow-up directions were proposed; this session shipped the lowest-risk,
self-contained one plus a cheap prompt tweak, and documented the other two as
deferred (`src/systems/facets_agent/PLAN.md` §7, "Phase 4"). Full design
reasoning lives there — this worklog is the implementation record.

## What shipped

**1. `pre_final_hook` — a generic harness mechanism** (`src/agent_harness/agent.py`).
New optional `run_agent` parameter: a callable given `{query_id, query,
ledger, candidate_sentences, last_commit_arguments, raw_messages}` right
before a valid final report is accepted, returning `None` (accept) or a
feedback string (send the model back once). Fires at most once per run
(structurally cannot loop), and defaults to `None` for every existing caller
— aus_agent, facet_rag, and any future system are byte-identical unless they
opt in. This was already spec'd, never built, in `PLAN.md` §3 as a deferred
"pre-final coverage gate"; building it now because the new diagnosis gives a
second, independent reason to want it.

One real bug caught mid-implementation: the first draft had the hook parse
`raw_messages` directly for the last `commit_context` call's arguments —
that's each **provider's own native format** (`providers/base.py`'s own
docstring says so), so a hook written against OpenAI's shape would silently
break on Bedrock, and was untestable against the generic `ScriptedProvider`
tests use. Fixed by having the harness itself track
`last_commit_arguments` (the already-normalized dict `apply_commit` uses) and
hand that to the hook instead — backend-agnostic, and what
`tests/agent_harness_context/test_pre_final_hook.py` actually exercises.

**2. `facets_agent.review.coverage_gate` — the default hook.** Reads the last
`commit_context` call's `coverage` ledger (facets_agent's own Phase-2 schema);
if any entry is still `status: open`, sends the model back naming them
instead of accepting the report. Wired as `facets_agent.agent.run_agent`'s
default `pre_final_hook` (override with `pre_final_hook=None` to disable, or
another callable in tests).

**3. Prompt-only citation-ordering hint** (`prompts.py`, PLAN §7.3 tier 1).
The shared citation cap (`agent_harness/agent.py::_parse_final_prose`,
confirmed unchanged by the agent_harness extraction) keeps only the first
three ids a sentence lists — positional, not ranked. One added sentence
asks the model to list the three most specifically-supporting ids first
when more than three could apply. Zero shared-code risk; a real re-ranking
pass (via a judge tool) stays deferred per PLAN §7.3.

## Deferred (PLAN.md §7.2, §7.1's second half)

- The external-judge tool (Qwen/gpt-oss via Bedrock) for offloading
  per-document relevance judging from the primary model — self-contained,
  but needs a genuine `agent_harness.agent._execute_tool_calls` dispatch
  change (new tool name), which deserves its own tested increment.
- `coverage_gate`'s richer sibling: re-scanning `ledger.rejected_ids`'
  original text (confirmed still recoverable from `ledger.call_history` even
  after the model's own view compacts it away) via the judge tool, for
  material that could close a `covered_but_shallow` gap without a new
  search. Depends on the judge tool existing first.
- Real citation re-ranking (replacing the positional first-3 truncation) —
  a 3-system-shared change (aus_agent, facets_agent, facet_rag all route
  through `_parse_final_prose`), needs its own measurement pass.

## Tests

`tests/agent_harness_context/test_pre_final_hook.py` (4 cases, generic
mechanism): absent-hook byte-identical, `None`-returning hook fires once and
receives the right shape, a feedback-returning hook gets exactly one
continuation turn and is never consulted twice, `last_commit_arguments` is
`None` (not a missing key) when nothing was ever committed.

`tests/systems/test_facets_agent.py` (+7 cases): `coverage_gate` unit tests
(no-op on missing/empty/all-resolved coverage, names every open entry with
its note), plus two end-to-end tests — the default wiring actually blocks a
premature report and lets a resolved one through, and `pre_final_hook=None`
disables it. One bug caught by the run itself: my new `COVERAGE_SCRIPT`
constant shadowed an existing same-named one earlier in the file (from the
Phase 2 test suite) — renamed to `COVERAGE_GATE_SCRIPT`.

`bash scripts/test.sh`: 1604 passed, 8 deselected (live), 0 skips.
`python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check`: passes.

## Not run this session

No live 15/30-topic re-run against real backends — this is a mechanism and
prompt change, not yet measured against the loss-factor-analysis worklog's
baseline. Next step per PLAN.md §7's sequencing: re-run the same
version-tagged comparison (new run-id, current git SHA) and watch the
`not_decomposed`/`covered_but_shallow` weighted percentages move.
