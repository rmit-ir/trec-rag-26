# 2026-08-05 — aus_agent vs facets_agent: per-criterion follow-up (corrects the prior "Instruction Following" read)

**Branch:** `main` (post-merge). Follow-up to
`worklogs/2026-08-05-aus-agent-vs-facets-agent-per-criterion-scorecard.md`,
running its two flagged follow-ups: read the individual topics/criteria
behind the axis-level findings directly, rather than trusting the aggregate
numbers alone. No new LLM calls — this reuses the cached per-criterion
judgments already on disk
(`evaluation-results/arena/aus_agent-vs-facets_agent-15topic-rubric/criterion-scores/`).

## Finding 1: "References & Citation Quality" (facets_agent's win-group) is a single-criterion artifact — confirmed

Pulled every citation-quality criterion in facets_agent's 3-topic win-group.
Two of the three topics have NONE. The third
(`6847465956a0f6376a605493`, Markov chains) has exactly two:

| criterion | weight | aus_agent | facets_agent |
|---|---|---|---|
| "references Markov's 1913 work on... Pushkin's *Eugene Onegin*" | +4.0 | 0 | 1 |
| "citations in an official format (MLA/APA/Chicago/IEEE)" | +1.0 | 0 | 0 |

The entire axis-level effect is one specific historical fact facets_agent's
search happened to surface and aus_agent's didn't — not a citation-quality
advantage of any kind. Confirms the caveat already flagged in the prior
worklog.

## Finding 2: "Instruction Following" (aus_agent's win-group) is ALSO a single-criterion artifact — this corrects the prior worklog

The prior worklog read the +0.071 Instruction Following gap as "the largest
differential" and "consistent with the mechanism" (aus_agent's long prompt
spelling out instruction-following mechanics). Pulling the actual criteria
shows this was the wrong read:

| topic | criteria checked | tied | differ |
|---|---|---|---|
| all 7 topics in the group | 8 | **7** | **1** |

Seven of eight Instruction Following criteria across the entire 7-topic
win-group score IDENTICALLY for both systems (0-0, 1-1, or 2-2). The ENTIRE
axis-level gap is one criterion in one topic
(`6847465956a0f6376a605492`, weight +3.0, "the experimental objective is
explicitly defined... in terms of a secondary objective"): aus_agent scored
1 (partial), facets_agent scored 0. Recomputing the group average from just
this: `(0.5 + 0 + 0 + 0 + 0 + 0 + 0) / 7 = 0.0714` — reproduces the reported
+0.071 exactly. There is no broad instruction-following pattern here at all;
the earlier "clearest, best-supported finding" claim does not hold up and is
retracted.

## Finding 3: the real signal is `Implicit Criteria`, and the previous aggregation method was hiding it

The prior worklog's `per_axis_score` averages a NORMALIZED per-topic score
across topics, treating every topic equally regardless of how many criteria
it contributes to an axis. That is exactly why one-criterion topics dominated
the sparse axes above — and, it turns out, why it made the high-volume axes
(`Implicit Criteria`, `Explicit Criteria`) look like a "near-zero gap" when
they are not.

Recomputed directly instead: for every criterion where the two systems'
grades differ, which system scored better (accounting for sign — a lower
grade is "better" on a negative-weight/penalty criterion), and the
weight-and-magnitude-scaled size of that difference (`|weight| * |grade
diff| / 2`), summed across ALL criteria in the group (not averaged per
topic):

| axis | aus_agent win-group (7 topics) | facets_agent win-group (3 topics) |
|---|---|---|
| **Implicit Criteria** | aus ahead: 14 criteria favor aus_agent (weighted 24.5) vs 9 favor facets_agent (weighted 16.5) | **facets ahead**: 6 favor facets_agent (weighted 9.0) vs 4 favor aus_agent (weighted 5.5) |
| Explicit Criteria | mixed/inconsistent: 6 vs 6 by count, but facets_agent ahead by weighted magnitude (16.0 vs 12.5) | facets ahead: 2 vs 1 by count, weighted 5.0 vs 0.5 |
| Synthesis of Information | aus ahead: 3 vs 3 by count, weighted 5.0 vs 5.5 (~even) | aus ahead: 3 vs 1, weighted 4.0 vs 1.5 (contradicts the group's own arena outcome) |
| Instruction Following | 1 criterion total (see Finding 2) | 1 criterion total, same shape |
| Communication Quality | aus ahead: 2 vs 1 (weighted 3.5 vs 2.0) | 1 criterion total |
| References & Citation Quality | 0 differing | 1 criterion total (see Finding 1) |

**`Implicit Criteria` is the only axis where the direction agrees with the
arena outcome in BOTH win-groups**: in the 7 topics aus_agent won, aus_agent
also has the (modest) net edge on Implicit Criteria specifically; in the 3
topics facets_agent won, facets_agent has the net edge on the same axis. It
is also the highest-volume axis in the whole rubric set (175 of 391
criteria, 45%), so this is the best-powered signal available from this data,
not a sparse-axis artifact like Findings 1–2.

Sample of what "Implicit Criteria" differences actually look like (topic
`683a58c9a7e7fe4e76958498`, the retirement-investing blog post — 4 of the 8
sample criteria below favor aus_agent, 2 favor facets_agent, illustrating
that even within one topic the direction is not one-sided, it just nets out
one way):

- w=+4.0 "defines stocks as shares of a company, distinguishes common vs
  preferred stock": aus_agent=1, facets_agent=0
- w=+4.0 "defines bonds as loans": aus_agent=2, facets_agent=0
- w=+4.0 "defines IRA accounts...": aus_agent=0, facets_agent=1
- w=+4.0 "compares traditional and Roth savings accounts": aus_agent=0,
  facets_agent=1
- w=−3.0 "contains verifiably incorrect or outdated information": aus_agent=2
  (committed this mistake), facets_agent=0 (did not) — a real, meaningful
  loss for aus_agent on this specific topic, netted out by its wins on the
  definitional criteria above.

## Revised takeaway (supersedes the prior worklog's "concentrated in
stylistic axes" conclusion)

The two systems are not differentiated by instruction-following or
communication-style compliance — that read was an artifact of averaging
across topics with only one relevant criterion. Where the two systems
genuinely differ, it is in **which specific pieces of implicit/expected
information their answers happen to include or omit** — a mix of
definitions, factual specifics, and (in one topic) a real factual-accuracy
miss for aus_agent — not a difference in how well either system follows
instructions or communicates. This is a less tidy story than "aus_agent's
long prompt wins on instruction-following" but a more accurate one: on this
15-topic sample, the gap between the two systems is small, concentrated in
individual content details rather than a systematic axis, and the direction
that determined each arena battle came down to which system's retrieval
happened to surface which specific facts for that specific topic.

## Methodological note for future rubric-axis analyses

Prefer counting/summing over ALL criteria in a group (Finding 3's method)
over averaging per-topic normalized axis scores (the original scorecard
script's `per_axis_score` + `group_avg`) when an axis has few criteria per
topic — the per-topic average lets a single criterion in a single topic
dominate the reported number while looking like a broad pattern. The
original script and its output remain useful for volume-dense axes
(Implicit/Explicit Criteria, Synthesis of Information) where per-topic
normalization is less distorting; for sparse axes it should not be trusted
without pulling the underlying criteria, as done here.
