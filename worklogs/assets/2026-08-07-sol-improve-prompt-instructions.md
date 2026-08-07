# Task

You are doing a deep root-cause analysis and then writing an improvement
plan for an agentic RAG system called `brief_revise_agent`, built for the
TREC RAG 2026 track. It currently loses to a stronger baseline system in the
same repo (`aus_agent`) on a rubric-judged arena over 30 held-out dev
topics. You have the full raw data below: both systems' complete answers on
every topic, `brief_revise_agent`'s search logs, its requirements brief per
topic, whether its review-and-revise pass fired, and the arena judge's
verdict (with the judge's own reasoning text) for every topic in both battle
orders. Use it. Don't speculate about failure modes you can't see evidence
for in the data below — ground every claim in a specific topic, a specific
sentence, a specific search query, or a specific judge comment.

**Hard constraint, non-negotiable**: the only document collection either
system may retrieve from is a fixed corpus called ClimbMix, reached through
a `search` tool (engines: `semantic`, `keyword`, `ssr` — Boolean/proximity,
`lucene_bool`) and a `get_documents` tool for full text by id. **No web
search, no other corpus, ever** — every citation in the final answer must be
a ClimbMix document id that was actually retrieved during the run. Within
that constraint you have full freedom: you may propose new tools, change
existing tool schemas, change the control flow, add or remove pipeline
stages, change prompts, change what gets logged, change the stopping
condition — anything, as long as retrieval stays ClimbMix-only and citations
stay grounded in what was actually retrieved.

# Background: the system and how it got here

## The track

TREC RAG 2026: given an open-ended "deep research" narrative (often
multi-part, sometimes with an implied audience, format, or scope), retrieve
evidence from ClimbMix and write a cited answer. Output is a list of
`{text, citations}` sentence objects, 0-3 citations each, whole answer
capped at 1024 words. Organizers score it two ways: (1) blind pairwise
system-vs-system battles judged by an LLM, and (2) per-response nugget/rubric
scoring against narrative-specific criteria. Two official axes matter for
citations specifically: **weighted citation precision** (of the sentences
that DO cite something, are the citations correct) and **weighted citation
recall** (of ALL sentences, are they supported — an uncited sentence scores
zero recall regardless of whether the claim is true). Submission deadline is
in ~24 hours.

## The two systems being compared

**`aus_agent`** — the incumbent, strongest system in the repo. One
continuously-accumulating tool-calling conversation, a single long
(267-line) heavily-tuned system prompt covering decomposition discipline,
search strategy, evidence curation, and the final-answer citation contract.
No separate stages, no separate roles. It commits generously (keeps most
plausibly-relevant staged documents rather than aggressively curating), and
writes the final cited report in the same conversation that did the
research.

**`brief_revise_agent`** — the new system under analysis. It is `aus_agent`
UNCHANGED (identical prompt, identical harness loop, identical retrieval
tools, identical budgets) plus exactly two additions:

1. **A pre-flight "requirements brief"**: before the research loop starts,
   one separate tool-less LLM call reads the narrative and produces up to 8
   requirements (up to 4 of them "implicit" — inferred rather than stated
   outright), each with a `specific_form` field describing what counts as
   actually covering it (a named entity, a mechanism, a number — not a
   category label). This gets rendered as an appendix on the system prompt,
   labeled advisory (a checklist to search and self-check against, not a
   rigid outline).
2. **A review-and-revise pass**: after the model writes what would be its
   final report, a hook intercepts it once (fires at most once, hard
   harness limit) before accepting it. The hook does two things: (a) a
   deterministic scan for sentences with zero citations (free, no LLM), and
   (b) one separate reviewer LLM call that reads the narrative, the brief,
   the numbered draft, the uncited-sentence list, and a text inventory of
   every committed (retrieved-and-kept) document, and returns up to 6 issues
   (types: `MISSING_REQUIREMENT`, `SHALLOW`, `UNCITED_CLAIM`,
   `WEAK_SENTENCE`), each with a concrete `fix`. If there are issues or
   uncited sentences, the model gets sent back ONCE with that feedback (plus
   the live word count against the 1024 cap, since additions must come with
   cuts) to revise, in the SAME conversation (so it still has every
   retrieved document). If nothing is wrong, the draft is accepted as-is.

Both the brief-writer and the reviewer are separate one-shot LLM calls (same
model, `gpt-5.6-luna`, same as the main loop) — they don't share the main
loop's tool-calling context, they only read text and return structured
JSON.

## Why this design, and what it was reacting to

Two EARLIER attempts at improving on `aus_agent` in this repo both failed,
for two different, instructive reasons, and `brief_revise_agent` was
designed specifically to avoid both:

- **`facet_rag`** (not in the data below, older system): decomposed the
  narrative into facets up front, ran each facet through its OWN isolated
  search-and-curate loop in parallel, then synthesized. Lost to `aus_agent`
  on retrieval-relevance (UMBRELA) on every measured topic. Root cause,
  confirmed by direct comparison: a curator stage aggressively trimmed each
  facet's evidence before it ever reached the writer, so the final synthesis
  worked from thin, pre-compressed notes instead of full documents —
  "content starvation."
- **`facets_agent`** (also not in the data below): kept `aus_agent`'s single-
  continuous-conversation shape, but replaced its long tuned prompt with a
  much shorter one that just told the model to decompose and self-check.
  Lost to `aus_agent` too (76.7% pooled preference for aus_agent over 30
  topics). Root cause, from an LLM diagnosis of the loss: about half the
  gap was `not_decomposed` (an implicit requirement — a comparison, an
  audience constraint, a cost dimension — never gets enumerated because
  nothing forces it to be written down before the model starts searching),
  and about half was `covered_but_shallow` (the requirement WAS searched,
  but the final sentence states a category — "use caching" — instead of the
  specific mechanism the corpus actually returned — "Redis with TTL
  eviction").

So `brief_revise_agent`'s two additions map directly onto those two root
causes, and — this is important — a follow-up analysis (before building
anything) found that `aus_agent` ITSELF has both of these defects, not just
the systems that lost to it: on the official rubric criteria, `aus_agent`
scored 0 on 42.5% of all criteria and never scored the max (3), was worst on
`Implicit Criteria` specifically (71% graded ≤1 out of 3), and left 26.0% of
its own answer SENTENCES with zero citations across the same 30-topic set
(you can see this directly in the `aus_agent` answers below — many
uncited sentences are exactly the "synthesis wrapper" or vague-category
shape the diagnosis predicts). The brief targets the first defect, the
review pass targets the second. Both additions were deliberately built as
the SMALLEST possible intervention: no new orchestration layer, no isolated
sub-contexts (the anti-`facet_rag` design choice), same long prompt kept
byte-identical (the anti-`facets_agent` design choice), one extra call
before the loop and one extra call after it.

## What actually happened, measured today

Full 30-topic dev run, both systems on `gpt-5.6-luna`, arena judged by a
THIRD model (`gpt-5.6-terra`, so the judge never generated either side's
answer — no self-preference confound), rubric-guided (judged against the
official per-topic ResearchRubrics criteria, not a naive "which is better"
prompt), both battle orders judged and pooled.

**Deterministic result (the part that isn't judge opinion):**
uncited-sentence rate across all 30 topics dropped from `aus_agent`'s 26.0%
(235/903 sentences) to `brief_revise_agent`'s 5.3% (42/786 sentences) — a
huge, real, mechanical win on citation recall specifically. Two topics
moved the wrong way on this metric even though the aggregate improved a lot
(both are in the raw data below — worth your own read, since the prior
analysis judged them "structurally benign" — synthesis/derivation sentences
— but that judgment wasn't rigorously checked against the rubric, only
eyeballed).

**Arena result (judge opinion, rubric-guided):** pooled, `aus_agent` is
preferred 58.3% of the time (35-25 over 60 battles). By CLEAN win groups
(a topic counts only if the judge preferred the same system in BOTH battle
orders — this repo has documented judge position-bias in the past, so clean
groups are trusted over the pooled number): **`aus_agent` wins 14 topics
clean, `brief_revise_agent` wins 9 topics clean, 7 are order-ambiguous.**
That is a big improvement over `facets_agent`'s 20-4 clean-loss record
against the same baseline — `brief_revise_agent` is the strongest system
built against `aus_agent` in this repo to date — but it's still a net loss,
and a preregistered decision rule (needs the challenger to clean-win ≥12
topics with `aus_agent` at ≤8) was NOT met, so `aus_agent` remains the
actual submission. This analysis is about what would need to change to
actually beat it, for a possible future iteration.

# What I need from you

## Part 1 — deep root-cause analysis

Read the raw per-topic data below (all 30 topics: 14 clean losses first,
then 7 ambiguous, then 9 clean wins, in that order — the losses are what
matters most, read those closely; skim the wins for contrast). For EACH of
the 14 clean-loss topics, identify, with a specific quote or specific
evidence:

- What did the judge actually say favored `aus_agent`? (Read the raw judge
  text — it's short, often just `[[A]]`/`[[B]]` with no reasoning since the
  prompt's a strict-verdict format, but check anyway — if there IS reasoning
  text, quote it.)
- Comparing the two answers directly: what does `aus_agent`'s answer contain
  that `brief_revise_agent`'s doesn't, or vice versa? Look for: missing
  content areas, weaker specificity, worse organization, tone/register
  mismatches, word-budget effects (is `brief_revise_agent` running out of
  room because it spent words on brief-driven content that didn't pay off?),
  citation patterns beyond the raw uncited-count (e.g. is
  `brief_revise_agent` citing something but weakly, or citing the RIGHT
  fact but attaching a less relevant document than `aus_agent` found for the
  same claim?).
- Look at `brief_revise_agent`'s search log and brief for that topic: did
  the brief ask for the right things? Did the searches actually go after
  what the brief asked for? Is there a mismatch between what was searched
  and what ended up in the answer?
- Did the review pass fire? If it fired, what can you infer about whether it
  helped or hurt (compare against topics where it didn't fire, or where a
  similar topic type won)?

Then synthesize ACROSS the 14 losses: what are the 3-5 actual dominant
failure patterns (not a laundry list — the specific, recurring ones with
the most evidence behind them)? For each pattern, name which loss topics
exhibit it (by id) so the pattern is falsifiable, not just asserted.

Also specifically address: is the "review pass helped uncited-rate but the
two things it can't fix are X and Y" story right, or is something else
going on that the original diagnosis (not_decomposed / covered_but_shallow)
didn't anticipate? The prior analysis was done blind to this specific data
— you have it now, use it to confirm, refine, or overturn that story.

## Part 2 — the improvement plan

Based on Part 1's actual findings (not the prior hypothesis), propose
concrete changes. You have full freedom within the ClimbMix-only
constraint: change prompts, change the brief schema, change the reviewer's
issue types or what it's shown, add a genuinely new tool (e.g. something
that lets the model check its own draft against the corpus differently, or
restructure how evidence reaches the writer), change the control flow
(more than one revision round? A different order of operations? Something
that runs DURING research rather than only before/after?), change the
stopping condition, change what's logged so a future diagnosis has better
data than this one did. Justify every change against a SPECIFIC finding
from Part 1 — no generic "add more retries" or "use a better model" advice.

Be realistic: whatever you propose needs to be buildable and testable in a
few hours by someone continuing this branch, not a research program. Rank
your proposed changes by expected impact vs. implementation cost, and be
explicit about which ones you'd cut first if there's only time for one or
two.

Write Part 2 as a plan document: a clear list of changes, each with (a) the
finding it targets, (b) what to build concretely (file/prompt/schema level,
not just prose), (c) how you'd know it worked (a specific, cheap-to-compute
metric — this repo already has the tooling to re-run the arena and to
compute uncited-sentence rate deterministically from saved artifacts, reuse
that rather than inventing new evaluation infrastructure).

---

# Raw data: all 30 topics

