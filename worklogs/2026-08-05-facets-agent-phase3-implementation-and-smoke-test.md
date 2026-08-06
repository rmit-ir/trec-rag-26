# 2026-08-05 — facets_agent Phase 3: minimal step-1 fix for bundled-requirement enumeration

**Branch:** `main`. A minimal, targeted follow-up to Phase 2's own diagnosis
(`worklogs/2026-08-05-facets-agent-phase2-implementation-and-smoke-test.md`):
the tool-carried coverage ledger only checks off what step 1 enumerates, and
on 6054a7 step 1 collapsed a three-country UBI comparison into one bundled
requirement, so the ledger closed out with Ontario's eligibility criteria and
political feasibility never separately checked. This is a **prompt-only**
fix — no schema or harness change — per the user's instruction to make the
smallest change that addresses the issue, using Azure gpt-5.6 models to
draft/review within a $5 budget.

## Drafting: gpt-5.6-luna drafts, gpt-5.6-terra reviews, one round

Gave `gpt-5.6-luna` the current `prompts.py`, a written diagnosis of the
6054a7 failure (in general terms — no topic-specific wording allowed into
the draft), and a task spec constrained to: edit step 1 only, 1-2 sentences,
no new numbered step, no change to any other paragraph, general wording (no
UBI/Finland/Ontario examples), plus a short dated paragraph in the module
docstring. `gpt-5.6-terra` reviewed the draft against the spec with an
explicit diff-style check (step 1 changed, nothing else changed, docstring
addition present and minimal, insertion general not topic-specific, line
growth ≤~4 lines). **First round passed clean**: `{"step1_only_changed":
true, "other_steps_unchanged": true, "docstring_addition_present_and_minimal":
true, "insertion_is_general_not_topic_specific": true,
"line_growth_acceptable": true, "issues": [], "overall_verdict":
"ship_as_is"}`. A manual `diff` against the original file confirmed the
review's read: the only changes were the new docstring paragraph and two
sentences inserted mid-step-1, word-for-word identical everywhere else.

**Cost: $0.0719** (draft $0.0483 + review $0.0236), against the $5 cap.
Script and raw outputs: `worklogs/assets/2026-08-05-phase3-draft-and-review.py`
(+ `.log`), `worklogs/assets/2026-08-05-phase3-draft-v1.py`,
`worklogs/assets/2026-08-05-phase3-review-v1.json`.

## What changed

`src/systems/facets_agent/prompts.py`, step 1, inserted after "Take them one
at a time, in the request's own words.":

> If a requirement names or implies multiple items — such as countries,
> sources, categories, examples, or comparison points bundled into one
> sentence — split it into one requirement per item, not one bundled
> requirement. Otherwise partial evidence can mark it covered without
> checking each item.

Plus a 6-sentence Phase 3 paragraph in the module docstring explaining the
diagnosis and why this is prompt-only. Nothing else in the file changed —
verified by diff, not just by the reviewer's say-so. `SYSTEM_PROMPT` body
grew from 89 to 94 lines. Full suite: 1594/1594 passing.
`docs/architecture.html` regenerated (prompt text is inlined into it).

## Smoke test: same 4 topics, run_id=facets-agent-phase3-smoke

```bash
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
uv run --group facets-agent python src/systems/facets_agent/run.py \
  --qid <qid> --run-id facets-agent-phase3-smoke
```

Two of the four topics ended up run twice (an artifact of retrying after the
harness's own foreground timeout cut a batch mid-topic, not a bug in the
system) — both pairs of runs are consistent with each other, which is useful
corroboration rather than noise. All completed runs: 0 protocol violations
beyond the harness's own citation-repair safety net doing exactly what it's
for (dropping an uncommitted docid, capping citations at 3/sentence — both
expected, healthy operation, not new problems). 100% schema compliance
continued: every search call carried `requirement`, every commit call
carried `coverage`. Latest run per topic:

| topic | searches v1→p1→p2→p3 | refs v1→p1→p2→p3 | p3 ledger entries |
|---|---|---|---|
| 6054a7 (UBI) | 39→23→18→**24** | 11→19→8→**12** | **9** (was 4 in phase 2) |
| 605476 (alt-history) | 9→14→12→**6** | 6→9→13→**10** | 6 (was 7) |
| 9af325 (Baudelaire) | 13→13→8→**10** | 18→21→14→**12** | 7 (unchanged) |
| 605391 (plant-based meat GTM) | 17→24→12→**15** | 16→22→19→**19** | **16** (was 9 in phase 2) |

**6054a7 — the fix worked, and reproducibly (seen in both independent
runs).** The final coverage ledger split from 4 coarse entries to **9**,
explicitly separating `"Cover Finland's UBI pilot"`, `"Cover Canada's UBI
pilot programs"`, and `"Cover U.S. UBI pilot programs"` as distinct entries
instead of one bundled comparison requirement — exactly the split the
diagnosis said was missing. Searches rose back to 24 (from Phase 2's 18),
now visibly spent on per-country peer-reviewed-evidence queries
(`"Kangas Jauhiainen Simanainen Ylikännö 2020 Finland basic income
experiment peer reviewed employment wellbeing"`,
`"Ontario Basic Income Pilot McMaster report peer reviewed journal"`) rather
than repeating the same broad multi-country query. References recovered to
12 (from Phase 2's 8). Reading the actual answer: it now states Ontario's
pilot design explicitly (C$16,989/year, 50-cent benefit-withdrawal rate per
dollar earned) and, notably, **one ledger entry came back `unavailable` for
the first time across all three phases' smoke tests** —
`"Use evidence from peer-reviewed economic studies"` — because after
searching named authors and journal terms on all three engines, the corpus
did not clearly establish peer-reviewed status for the country-pilot
sources. The answer honors this precisely: *"The corpus contained post-2015
randomized and economic analyses, policy reports, and expert commentary, but
it did not clearly establish peer-reviewed publication status for the
country-pilot evidence, so those sources should not be presented as
uniformly peer-reviewed economic studies."* This is the row-7/`unavailable`
safeguard working as designed — the model searched from a specific
requirement, didn't find it, and said so instead of asserting it — and it is
the first time any smoke test has exercised that path.

**605391 — the fix generalized well beyond the diagnosed topic.** Ledger
grew from 9 entries (Phase 2) to **16**, splitting "compare consumer-demand
trends" into three separate per-country entries (Singapore, Thailand,
Indonesia) and splitting the "risks and opportunities" bucket into three
separate entries (regulatory shifts, supply-chain localization,
sustainability branding) that Phase 2 had bundled into one. This was not the
topic the fix was diagnosed against, so this is real evidence the change
addresses the general bundling failure mode, not just the one worked
example.

**605476 and 9af325 — essentially unchanged, as expected.** Both requests
already hand the model an explicit numbered/enumerable structure (605476's
five numbered timeline assumptions; 9af325's already-narrow single-case
overview), so step 1's own enumeration was already granular before this
change and stayed that way. Minor count fluctuations (605476's searches
14→12→6, refs 9→13→10) read as ordinary run-to-run variance rather than a
regression — the ledger entries and their `covered` statuses are materially
the same shape across phase 2 and phase 3 for both topics.

## Reading the result

The targeted fix closed the specific gap it was diagnosed against (6054a7's
per-country split), generalized to a second topic that wasn't part of the
diagnosis (605391's per-country and per-risk-category split), left the two
already-well-decomposed topics unaffected, and — as a side effect neither
targeted nor expected — produced the first `unavailable`-ledger-entry sighting
across three phases of smoke testing, with the answer text handling it
exactly as the safeguard is meant to (naming the gap instead of asserting
through it). No regressions: 0 protocol violations, schema compliance still
100%, full test suite green. This closes the loop the Phase 2 worklog
opened: the coverage ledger's floor is no longer bounded by the model
collapsing multi-item comparisons into single requirements.

## Not done this session

- The full 15-topic re-run and `PLAN.md` §5's Tier 1/Tier 2 validation across
  all three phases together — still only smoke-tested on the same 4 topics
  each phase has used throughout.
- No further prompt iteration attempted; the one-round draft/review passed
  clean and the smoke test confirmed the predicted effect, so a second paid
  round was not warranted (mirrors Phase 1's reasoning for stopping at a
  clean pass rather than open-endedly iterating).
