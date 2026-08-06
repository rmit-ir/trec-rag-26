# 2026-08-05 — facets_agent Phase 1: implementation + 4-topic smoke test

**Branch:** `main`. Executes Phase 1 of `src/systems/facets_agent/PLAN.md`
(prompt-only changes, no schema/harness changes) and runs the plan's own
recommended "cheap gate" — the 4 worst-case topics it names — before
considering a full 15-topic re-run. Code committed separately as `815caa4`;
this worklog covers the draft/review process and the smoke-test results.

## Drafting: gpt-5.6-luna writes, gpt-5.6-terra reviews

Per the user's instruction to use the OpenAI gpt-5.6 models for this, within
a $10 budget. Two-role split, same reasoning as everywhere else this session
a judge/reviewer needed to not share a model with what it's judging:
`gpt-5.6-luna` (facets_agent's own generator) drafts, `gpt-5.6-terra`
(neither system's generator) reviews.

**Round 1**: fed `gpt-5.6-luna` the current `prompts.py` plus the exact
edit specification transcribed from `PLAN.md` §1.3 (every proposed sentence
for the opening paragraph, steps 1-5, and the final-report paragraph, plus
the module-docstring divergence justification). Draft came back functionally
complete but the `SYSTEM_PROMPT` body ran ~95 lines against the plan's
~80-84 target. `gpt-5.6-terra`'s review confirmed this (`line_count_ok:
false`) and, correctly, did NOT flag the pre-existing `Tools:` bullet list
as new bloat once told to only report against the specification.

**Round 2**: sent the draft back to `gpt-5.6-luna` for a targeted tightening
pass (steps 4 and 5 specifically named as the verbose blocks). Came back at
84 lines — but `gpt-5.6-terra`'s re-review (this time given the ORIGINAL
file too, so it could tell old structure from new) caught 3 real wording
bugs the compression introduced:

1. Step 4's stop condition read as ambiguous about what "unavailable" meant.
2. Step 5's coverage check ("recheck every identified requirement and commit
   evidence for it") accidentally implied every requirement must end up with
   committed evidence — contradicting the legitimate "properly searched, not
   in the corpus" outcome the plan is explicit about protecting.
3. The final paragraph's citation-discipline clause ("only organising,
   connecting, or cited conclusions may omit ids") was self-contradictory: a
   sentence that omits ids cannot itself be described as "cited."

Fixed by hand into the final `src/systems/facets_agent/prompts.py` (the
model catches were real, the fixes were small and precise enough not to
need a third paid round). Final `SYSTEM_PROMPT` body: **92 content lines**
(94 including the delimiter lines) — above the plan's ~80-84 target but
close to it, and the overshoot is entirely the 3 bug-fix sentences, which
the plan itself treats as acceptable ("the phase-1 overshoot to ~82 lines is
deliberate and time-boxed to one phase"). Full suite: 1589/1589 passing
before commit.

**Cost: $0.0644 (round 1) + $0.0674 (round 2) = $0.1318 total**, against
the $10 cap. Scripts and raw outputs:
`worklogs/assets/2026-08-05-phase1-draft-and-review.py` (+`.log`),
`worklogs/assets/2026-08-05-phase1-revise-and-rereview.py` (+`.log`), the
two draft versions and both review JSONs.

## What Phase 1 actually changed

See the committed `prompts.py` and its module docstring for the full text.
Summary: step 1 now asks the model to enumerate every requirement the
request states before grouping into facets (the plan's diagnosis: this,
not retrieval execution, is where the 73%-of-topics coverage gap
originates); steps 4-5 turn that into a checkable stop condition and a
pre-report self-check, tracked in the model's own reasoning only — there is
no tool-schema field for it yet, that is Phase 2, deliberately deferred so
this wording-only effect could be measured in isolation first (which is
what this smoke test is for); step 2 adds a paired named-candidate +
category query instruction; and the opening paragraph makes a deliberate,
named divergence from aus_agent by actively permitting and encouraging
query terms drawn from the model's own knowledge, with the citation
contract and an explicit "query yes, claim no" repetition as the guard
against that becoming assertion without verification.

## Smoke test: the plan's own 4-topic "cheap gate"

Ran the exact 4 topics `PLAN.md` §5 names, one per failure mode, under
`run_id=facets-agent-phase1-smoke`:

```bash
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
uv run --group facets-agent python src/systems/facets_agent/run.py \
  --qid <qid> --run-id facets-agent-phase1-smoke
```

All 4 completed, 0 violations. Full log:
`worklogs/assets/2026-08-05-phase1-smoke-run.log`. Comparison script:
`worklogs/assets/2026-08-05-phase1-smoke-compare.py` (+`.log`).

| topic | watch for | searches v1→v2 | refs v1→v2 | words v1→v2 |
|---|---|---|---|---|
| 6054a7 (UBI) | Ontario eligibility / political feasibility / UBI definition | 39→**23** (−41%) | 11→**19** (+73%) | 609→634 |
| 605476 (alt-history) | shared US-Soviet enemy / internal British opposition | 9→**14** (+56%) | 6→**9** (+50%) | 708→972 |
| 9af325 (Baudelaire) | book-by-book structure | 13→13 | 18→21 | 988→917 |
| 605391 (plant-based meat GTM) | named partners (Indomaret, GrabFood) | 17→**24** (+41%) | 16→**22** (+38%) | 937→938 |

**605391 — the clearest, strongest result.** v2's answer names `GrabFood`
explicitly — one of the two specific entities the original diagnosis
flagged as missing — plus `GoFood`, `TravelokaEats`, `Tesco Lotus`, `Villa
Market`, Green Rebel's actual partnerships (500+ foodservice outlets, a
50+-location Starbucks partnership, an IKEA collaboration), and SKU-level
competitor pricing (Beyond Meat S$24.95, Impossible S$16.90, OmniMeat
S$8.50, Quorn S$6). v1's answer, by contrast, stayed at the thematic level
("hotels, cafes, QSRs"). This is exactly the mechanism the plan's row 7
(the parametric-knowledge licence) predicted: named candidates the model
already knew, permitted into queries, found real support in the corpus.

**605476 — a real, predicted-shape improvement.** Searches went UP (9→14),
which the plan explicitly predicted as the correct signature of closing a
coverage gap ("closing gaps means searching MORE where under-searched, not
less"). The query log now explicitly targets "Communist Party of Great
Britain miners strike Labour left" and "British Empire Federation" —
directly hitting the "internal British opposition" gap the original
diagnosis named. The "shared US-Soviet enemy" gap is less clearly closed —
no query obviously targets a third-power rival (China) or an ideological
common ground — so this topic is a partial win: one of two named gaps
closed, not both.

**6054a7 — efficiency gain, but the specific named gaps weren't hit.**
Searches dropped 39→23 and references rose 11→19, both good signs the
redundant-re-search problem eased. But reading the 23 v2 queries, none
target Ontario's eligibility criteria, political feasibility/public
opinion, or a UBI definition — the three specific things the original
diagnosis named as missing. The model spent its (smaller) search budget
more efficiently re-covering the same three pilot programs (Finland,
Ontario, Stockton employment/wellbeing/fiscal findings) rather than
branching out to the requirements it never enumerated. This is the
plan's own predicted failure mode for phase 1 alone (§4: "a licence to
name candidates does nothing for a requirement the model never
enumerated") — the step-1 requirement-enumeration wording helped somewhat
(better yield) but didn't fully fix this topic's decomposition.

**9af325 — flat, and on inspection the original diagnosis looks overstated
for this topic.** Searches unchanged (13→13). Re-reading v1's actual answer
text (not just the diagnosis's summary of it) while investigating this:
v1 ALREADY organizes chronologically by book, explicitly naming each one
inline ("In *The Bad Beginning*... In *The Reptile Room*... In *The Wide
Window*... In *The Miserable Mill*... In *The Austere Academy*..."), and
both v1 and v2 end on a synthesizing conclusion sentence, not the abrupt
cutoff the original diagnosis described. The diagnosis's "no book headings"
complaint is technically true (the harness's final-report contract forbids
Markdown headers entirely — no system could satisfy a literal reading of
that request), but the substantive complaint (no book-by-book structure)
doesn't hold up against the actual text. Recorded here as a correction to
the strengths/weaknesses report's original framing of this topic, not as a
finding about Phase 1's effectiveness one way or the other — there wasn't
much room to improve something that wasn't as broken as described.

## Reading the result

2 of 4 clear, plan-predicted improvements (605391 strongly, 605476
partially); 1 real efficiency gain that didn't close the specific named gap
(6054a7); 1 flat result attributable to the original diagnosis overstating
the problem rather than to Phase 1 underperforming (9af325). This is a
genuinely mixed-but-net-positive signal, not a clean win — consistent with
the plan's own stated expectation (§4): "phase 1 lifts named-entity coverage
... while leaving the whole-requirement misses ... untouched, since a
licence to name candidates does nothing for a requirement the model never
enumerated. That would be the *expected* split, and it is the case for
shipping both [phase 1 and phase 2]." 6054a7's result is exactly that
predicted split in miniature: efficiency up, specific named-entity recall
up elsewhere (605391), but the requirement that needed enumeration and
never got it (Ontario eligibility) still didn't get searched.

## Not done this session

- The full 15-topic re-run and the plan's Tier 1 (deterministic trace
  metrics)/Tier 2 (rubric-recall) validation — the smoke test's 4 topics
  were read by hand rather than through the plan's preregistered metrics,
  since those need the Phase 2 `requirement`/`coverage` ledger fields to be
  measured precisely (Tier 1 #1-#4) or are designed for a 15-topic sample
  (Tier 2). This smoke test answers a narrower, cheaper question — "does
  the wording change visibly move behavior in the predicted direction on
  the worst cases" — and the answer is yes, partially, unevenly.
- Phase 2 (the `requirement`/`coverage` schema fields and the
  `search_tool_def` harness parameter) — not started. Given the smoke
  test's mixed result on 6054a7 (the requirement-enumeration step doesn't
  yet reliably surface everything on a topic with as many overlapping
  sub-facts as the UBI comparison), Phase 2's structured ledger is
  plausibly where the remaining gap gets closed, matching the plan's own
  reasoning for why phase 2 exists on top of phase 1.
