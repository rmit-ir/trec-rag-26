# 2026-08-05 — facets_agent re-run: full evaluation redone

**Branch:** `main`. facets_agent was re-run on the same 15 topics from another
session (post-merge, so on the code including the `release_committed`
duplicate-resurrection fix from
`worklogs/2026-08-05-aus-agent-vs-facets-agent-per-criterion-followup.md`'s
predecessor commit `7dcbca5`). Found the fresh batch in the synced data dir
(`/research/remote/petabyte/users/oleg/trec_rag_26_data/outputs/facets_agent/`,
timestamps ~08:41-08:50, later than the original 07:06-07:26 batch and than
the PR merge), same `run_id=facets-agent-15topic`, same 15 qids, all
`completed`, 0 violations. Swapped it into `data/outputs/facets_agent/`
(old batch moved aside locally, not deleted, in case of later comparison
value) and re-ran all three evaluations from scratch, clearing every cache
that keys on `task_id` rather than content (the arena/scorecard scripts
cache per-battle and per-criterion judgments to disk for resumability, and
none of those cache keys encode the answer text — reusing them against new
answers would have silently returned stale judgments for the old ones).

**Important caveat up front**: this is one new stochastic sample, not a
repeated/controlled experiment. Below notes what changed from the prior
results, but nothing here should be read as proof the `release_committed`
fix (or any other code change) caused the differences — LLM generation is
non-deterministic, and re-running the exact same code on the exact same
topics would likely also shift results somewhat. Where a difference is large
enough to be interesting, it's reported as "the new run shows X", not "the
fix caused X."

## Re-run 1: arena vs facet_rag (judge=gpt-5.6-luna, naive prompt)

Unchanged: **facets_agent 30-0-0** again (same as the original run in
`worklogs/2026-08-05-facets-agent-vs-facet-rag-arena.md`). Same caveats
apply unmodified (facet_rag's uncited-answer topic, length disparity,
self-preference risk since gpt-5.6-luna both judges and generates
facets_agent's answers) — this comparison's methodological weaknesses were
never about facets_agent's specific answers, so a new facets_agent batch
doesn't change the reasoning. Log:
`worklogs/assets/2026-08-05-rerun-arena-facets-agent-vs-facet-rag.log`.

## Re-run 2: rubric arena vs aus_agent (judge=gpt-5.6-terra)

aus_agent's answers were NOT re-run (nothing about the fix touches aus_agent
-- its own prompt/tool schema never mentions `release`, confirmed already in
the original PR). Only facets_agent's side changed.

| | previous run | this run |
|---|---|---|
| aus_agent wins | 19 (63.3%) | **21 (70.0%)** |
| facets_agent wins | 11 (36.7%) | 9 (30.0%) |
| order_consistency | 0.667 | 0.533 (more position-bias noise this time) |
| raw A/B split | B 66.7% | B 60.0% (still biased toward B, weaker) |

Clean win/loss groups (topic wins BOTH orientations = clean; otherwise
ambiguous) shifted substantially:

| group | previous run (n) | this run (n) |
|---|---|---|
| aus_agent clean wins | 7 | 7 (same count, mostly same topics -- see below) |
| facets_agent clean wins | 3 | **1** |
| ambiguous | 5 | 7 |

facets_agent's clean-win count dropped from 3 to 1. The one topic it still
wins outright (`683a58c9a7e7fe4e76958498`, the retirement-investing blog
post) is a "pick the less-bad one" result, not a quality win: the
per-criterion scorer gives BOTH systems an overall grade of **1/3** on that
topic (see Re-run 3). Log:
`worklogs/assets/2026-08-05-rerun-arena-aus-agent-vs-facets-agent-rubric.log`.

## Script fix: ARENA_GROUPS must never be hardcoded

Running the scorecard script (`rubric_scorecard_aus_agent_vs_facets_agent.py`)
against the new answers with its OLD hardcoded `ARENA_GROUPS` constant (from
the previous run) printed a scorecard against the WRONG topic groupings --
a real bug, caught only by chance because the group sizes visibly still said
7/3/5 when the fresh arena run had produced 7/1/7. Fixed properly, not just
patched for this run:

- `load_arena_groups(judgments_path)` derives the win/loss/ambiguous grouping
  LIVE from the arena's own `judgments.jsonl` every time the script runs.
  `ARENA_GROUPS` no longer exists as a constant.
- Added `criterion_tally`, which sums weighted per-criterion differences
  across ALL criteria in a group (not averaged per topic) -- this is the
  method the previous follow-up worklog had to reconstruct by hand to catch
  the Instruction-Following single-criterion artifact; it's now a permanent
  second table the script prints and writes to the JSON output every run, so
  that investigation doesn't need to be redone by hand again.

## Re-run 3: per-criterion scorecard (judge=gpt-5.6-terra)

Using the (now-correct) live groups: aus_agent clean wins = 7 topics,
facets_agent clean wins = 1 topic, ambiguous = 7 topics.

**Overall grade (0-3) by group:**

| group | n | aus_agent | facets_agent |
|---|---|---|---|
| aus_agent-won | 7 | **2.29** | 1.71 |
| facets_agent-won | 1 | 1.00 | 1.00 |
| ambiguous | 7 | 2.14 | 2.00 |

Unlike the previous run (where the aus_agent-won group's overall grades were
nearly tied, 2.00 vs 1.86, and the axis-level story turned out to be a
single-criterion artifact on close inspection), this run's aus_agent-won
group shows a real, larger gap (2.29 vs 1.71) that IS broadly supported
across axes in the `criterion_tally` breakdown:

| axis (aus_agent-won group, n=7 topics) | total criteria | tied | aus_agent better | facets_agent better |
|---|---|---|---|---|
| Implicit Criteria | 74 | 56 | 13 (w=16.5) | 5 (w=6.0) |
| Explicit Criteria | 34 | 27 | 6 (w=11.0) | 1 (w=1.5) |
| Synthesis of Information | 40 | 32 | 5 (w=9.0) | 3 (w=5.5) |
| Instruction Following | 11 | 8 | 3 (w=5.0) | 0 |
| Communication Quality | 9 | 6 | 2 (w=5.0) | 1 (w=1.0) |
| References & Citation Quality | 6 | 6 (fully tied) | 0 | 0 |

Every axis with enough criteria to say anything favors aus_agent this time
(the one exception, Miscellaneous, is a single criterion). This is a
genuinely different, more robust pattern than the previous run's, where the
aus_agent-won group's "Instruction Following" edge collapsed to one
criterion in one topic under the same kind of scrutiny (applying the same
`criterion_tally` method to THIS run's Instruction Following row: 11
criteria, only 3 differ, all 3 favor aus_agent -- a small but real,
non-single-criterion signal this time, unlike before).

`Implicit Criteria` remains the highest-volume, best-powered axis (as in the
original follow-up worklog) and again shows the largest raw weighted
advantage. Sample of what these differences look like (mixed direction
within topics, netting toward aus_agent):

- w=+2.0 "highlights regular audits/updates of AI systems": aus_agent=1,
  facets_agent=2 (favors facets_agent)
- w=+3.0 "references earlier Counter-Strike titles to place CS:GO in
  context": aus_agent=1, facets_agent=2 (favors facets_agent)
- w=+3.0 "mentions a common enemy between the US and USSR": aus_agent=2,
  facets_agent=1 (favors aus_agent)
- w=−2.0 "asserts major geopolitical shifts (dissolution of NATO, etc.)":
  aus_agent=0 (did not commit this speculative-claim mistake),
  facets_agent=1 (did, partially) -- favors aus_agent
- w=+2.0 "defines contractarianism...": aus_agent=1, facets_agent=2 (favors
  facets_agent)
- w=+2.0 "defines deontology...": aus_agent=2, facets_agent=1 (favors
  aus_agent)

Individual criteria go both ways even within one topic (as in the original
follow-up worklog's finding) -- it is the NET across many criteria, not a
one-sided pattern, that favors aus_agent this time.

**The facets_agent-won group is now a single topic and reads as a genuine
tie, not a win.** Both systems score overall=1/3 on
`683a58c9a7e7fe4e76958498`; the arena's consistent facets_agent preference
there is the judge picking the less-weak of two weak answers, confirmed
directly against the raw verdicts (`[[B]]` when facets_agent was B, `[[A]]`
when facets_agent was A -- consistently facets_agent, but on a topic neither
system actually answered well).

**The ambiguous group (7 topics) is close but not an exact tie this time**
(2.14 vs 2.00, versus the previous run's exact 2.00=2.00) -- still
consistent with "these are near-ties the position bias resolves
inconsistently," just not as perfectly clean a confirmation as before.
Notably, `Implicit Criteria` favors aus_agent even within this "ambiguous"
group (14 vs 7 criteria, weighted 28.0 vs 13.0) -- suggesting aus_agent's
modest edge on this axis is not confined to its own win-group, it just isn't
always enough to flip the arena's holistic verdict.

Full log: `worklogs/assets/2026-08-05-rerun-rubric-scorecard.log`. Raw data:
`evaluation-results/arena/aus_agent-vs-facets_agent-15topic-rubric/criterion_scorecard_summary.json`
(now includes both the per-topic-averaged table and the `criterion_tally`
table, gitignored/local).

## Revised overall reading

This run tells a more one-sided story than the original: aus_agent's edge is
broader (more axes, not just one sparse one) and larger (both in arena
preference rate, 70% vs 63.3%, and in the scorecard's overall-grade gap in
its win-group, 2.29 vs 1.71 rather than a near-tie). facets_agent's
apparent 3-topic strength from the original run mostly did not reproduce --
its remaining "win" is a tie-breaker on a topic where neither system did
well.

Whether this reflects the new facets_agent batch actually being weaker (by
chance, or because of some interaction with the merged fix), or is simply
sampling noise in one 15-topic run with a judge that has its own measured
position bias, cannot be determined from a single before/after pair. The
methodologically sound next step, if this is worth settling, is running
facets_agent multiple times on the same topics and comparing the
DISTRIBUTION of arena/scorecard outcomes to aus_agent's, not treating either
single run as ground truth.
