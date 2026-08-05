# 2026-08-05 — aus_agent vs facets_agent: per-criterion rubric scorecard

**Branch:** `facets_agent`. Follow-up to the rubric arena
(`worklogs/2026-08-05-aus-agent-vs-facets-agent-rubric-arena.md`), which left
one open question: do the 7 topics aus_agent won cluster on identifiable
rubric axes (e.g. "Instruction Following") that facets_agent's answers
systematically miss, versus the 3 facets_agent won?

The arena judge only ever produces a holistic win/loss per battle — it never
says which criteria drove a verdict. Answering the question needed a
different judge task: grade each answer against every rubric criterion
individually, then aggregate by axis and compare within the arena's own
win/loss/ambiguous groupings.

## Method

New script:
`tasks/task-comparison/scripts/rubric_scorecard_aus_agent_vs_facets_agent.py`,
adapted from the existing single-run rubric judge
(`tasks/task-comparison/rubric-judge/judge_answers.py`) with two changes both
necessary for this question:

- Kept **every** rubric axis and **every** criterion, including negative-weight
  penalty criteria (`judge_answers.py` restricts to `INFO_AXES` and drops
  penalties, because it exists to score information coverage — but
  "Instruction Following" and "Communication Quality," exactly what this
  question is about, would be invisible under that filter).
- Score aggregation therefore has to handle signed weights correctly:
  `contribution = weight * grade / 2` per criterion (grade 0/1/2), so a
  fully-satisfied positive criterion contributes `+weight` and a
  fully-COMMITTED negative-weight criterion (the answer made the flagged
  mistake) contributes `-|weight|`; normalized by the axis's total `|weight|`
  per topic so axes with different numbers of criteria are comparable
  (roughly `[-1, 1]`).

One LLM call per `(system, topic)` — 30 total (15 topics × 2 systems) — grades
every criterion 0/1/2 plus a holistic 0–3 overall grade. Judge:
`gpt-5.6-terra`, same choice as the arena (generated neither answer set —
both systems ran on `gpt-5.6-luna` — so no self-preference risk here either).

```bash
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
uv run --group aus-agent python \
  tasks/task-comparison/scripts/rubric_scorecard_aus_agent_vs_facets_agent.py \
  --workers 6
```

Grouped by the arena's own outcome (from the rubric-arena worklog): 7 topics
aus_agent won outright, 3 facets_agent won outright, 5 were position-bias
noise ("ambiguous"). Full log:
`worklogs/assets/2026-08-05-rubric-scorecard-aus-agent-vs-facets-agent.log`.

## Result 1: the "ambiguous" group is a genuine tie, not hidden signal

| group | n | aus_agent overall (0-3) | facets_agent overall (0-3) |
|---|---|---|---|
| aus_agent-won | 7 | 2.00 | 1.86 |
| facets_agent-won | 3 | 2.00 | 2.33 |
| ambiguous | 5 | 2.00 | 2.00 |

The ambiguous group's overall grades are **identical** (2.00 = 2.00) under an
independent per-criterion scorer. This confirms the rubric-arena worklog's
read of those 5 topics: the judge's inconsistent picks there reflect the
measured "prefer Assistant B" position bias operating on a genuine near-tie,
not a real preference the arena's aggregate happened to obscure.

## Result 2: where aus_agent's win-group edge comes from

Per-axis average score, `aus_agent − facets_agent`, within the 7-topic
aus_agent-won group (positive = aus_agent ahead):

| axis | diff | criteria/topic (this group) |
|---|---|---|
| Instruction Following | **+0.071** | 1.14 |
| Communication Quality | +0.027 | 1.71 |
| Explicit Criteria | +0.029 | 6.86 |
| Implicit Criteria | +0.026 | 12.43 |
| Synthesis of Information | −0.018 | 3.71 |
| References & Citation Quality | 0.000 | 0.57 |

The two axes with the LARGEST, most information-dense criteria counts
(Implicit Criteria, Explicit Criteria — 12.4 and 6.9 criteria/topic, together
over 80% of all criteria in this dataset) show only a **near-zero
differential** (+0.026, +0.029) in the group aus_agent won. Substantive
information coverage is essentially indistinguishable between the two
systems here. The largest gap is **Instruction Following** (+0.071) — which
directly supports the mechanism proposed in the arena worklog (aus_agent's
long prompt explicitly instructs many of the things this axis grades, e.g.
format/structure compliance; facets_agent's minimal prompt states the
research process but says much less about instruction-following mechanics).

**Caveat, stated plainly**: Instruction Following (1.14 criteria/topic here)
and References & Citation Quality (0.57/topic) are SPARSE axes — most
individual topics carry 0–2 criteria under them, so a per-topic average on
either is built from very few data points and is noisy. Checked whether this
is a topic-composition artifact (the aus_agent-won topics simply *asking*
for more instruction-following compliance by chance) rather than a
behavioral difference: criteria density is comparable across all three
groups (1.14 vs 1.00 vs 0.80 Instruction-Following criteria/topic for
aus_agent-won / facets_agent-won / ambiguous respectively) — not a large
confound, but the underlying signal is still built on few criteria per
topic. Read the Instruction Following finding as suggestive and consistent
with the arena result, not as a statistically robust axis-level conclusion.

## Result 3: facets_agent's own win-group tells a different story

Per-axis diff within the 3-topic facets_agent-won group (positive =
aus_agent ahead, so NEGATIVE here means facets_agent ahead):

| axis | diff |
|---|---|
| References & Citation Quality | **−0.133** |
| Implicit Criteria | −0.054 |
| Explicit Criteria | −0.032 |
| Instruction Following | +0.062 (aus_agent still ahead here) |
| Communication Quality | +0.111 (aus_agent still ahead here) |
| Synthesis of Information | +0.085 (aus_agent still ahead here) |

Notably, aus_agent is NOT behind on Instruction Following or Communication
Quality even in facets_agent's own win-group — facets_agent wins these 3
topics specifically on **References & Citation Quality** and **Implicit
Criteria** coverage, not on the style/instruction axes. References &
Citation Quality is the sparsest axis in the whole dataset (10 criteria
across all 15 topics, 0.67/topic here) — this is very likely dominated by
one or two topics' rubrics rather than a general pattern, and should not be
read as "facets_agent is better at citations" without checking the
individual topics behind it (not done this session).

## Takeaway

The clearest, best-supported finding: on the topics where the two systems
differ, the difference is concentrated in stylistic/procedural axes
(Instruction Following, Communication Quality), not in substantive
information coverage (Explicit/Implicit Criteria, which dominate the rubric
by volume and show almost no gap either way). This is consistent with, but
does not by itself prove, the mechanism proposed in the arena worklog:
aus_agent's long prompt spells out instruction-following mechanics that
facets_agent's minimal prompt leaves implicit.

## Follow-ups (not done this session)

- Read the individual topics behind facets_agent's References & Citation
  Quality edge directly (only ~2 topics carry that axis in its win-group) to
  confirm it is not a single-topic artifact.
- If the Instruction Following hypothesis is worth acting on: the natural
  next step is NOT more measurement but a prompt experiment — add one
  or two sentences to `facets_agent/prompts.py` about following explicit
  format/structure requirements in the request, then re-run this same
  scorecard to see if the gap closes without regressing facets_agent's
  Implicit-Criteria/Synthesis performance (currently roughly at parity).
