# 2026-08-06 — facets_agent vs aus_agent: ranked factor analysis + improvement suggestions

Follow-up to the version-tagged 15-topic rubric comparison
(`aus-agent-15topic-5728aff` vs `facets-agent-15topic-5728aff`, both on HEAD
`5728aff`, judge=`gpt-5.6-terra`/`gpt-5.6-sol` — see prior session turns):
aus_agent won 86.7% of pairwise battles (order_consistency=1.0), 13/15 topics
outright. This worklog identifies WHY, ranks the contributing factors, and
proposes concrete facets_agent changes. Budget: $20, spent on one gpt-5.6-sol
pass (15 calls, see below) — free (code-reading + already-computed rubric
scores) covered the rest.

## Method

1. **Free — structural/behavioral diff** from both systems' trajectory files
   (tool-call counts, docs seen, answer length, citation density).
2. **Free — literal criterion diff** from the already-computed per-criterion
   scorecard (`evaluation-results/arena/aus_agent-vs-facets_agent-15topic-5728aff-rubric/criterion-scores/*.json`):
   every rubric criterion where the two systems' grades differ, with its full
   text, weight, and which system won it.
3. **Paid — root-cause diagnosis** (`worklogs/assets/2026-08-06-facets-agent-loss-diagnosis-probe.py`,
   judge=`gpt-5.6-sol`, 15 topics, one call per topic): for every criterion
   aus_agent won, fed the model facets_agent's own step-1 requirement/facet
   enumeration (extracted from `trajectory.raw_messages`), facets_agent's
   final answer, and the losing criteria list; asked it to classify each loss
   into one of four stages and suggest a concrete fix. Raw output:
   `evaluation-results/arena/aus_agent-vs-facets_agent-15topic-5728aff-rubric/loss-diagnosis/*.json`,
   aggregate: `worklogs/assets/2026-08-06-facets-agent-loss-diagnosis-aggregated.json`.

Cost note: no token-usage/billing probe is wired into this repo's eval
scripts, so exact spend isn't verifiable from here — 15 diagnosis calls
(topic + facets_agent's answer, ≤12k chars, truncated) plus the 60-battle
arena and 30-call scorecard from the same session, comparable in size to
calls already run this session without concern, is well within the $20 cap
on any plausible pricing for this model class.

## Structural finding (free, n=15 topics each)

| metric | aus_agent | facets_agent |
|---|---:|---:|
| words/answer | 897 | 700 (-22%) |
| sentences/answer | 31.8 | 22.7 (-29%) |
| % sentences cited | 75.9% | 97.0% |
| citations/answer | 31.5 | 35.9 |
| tool calls/topic | 11.3 | 19.7 (+75%) |
| unique docs seen/topic | 67.5 | 177.7 (+163%) |

facets_agent retrieves **2.6x more documents** and makes **75% more tool
calls**, yet writes a **shorter** final answer. It is not under-informed —
it is under-synthesizing what it gathers.

## Ranked factors (by weighted rubric-criterion impact)

Of 63 criteria aus_agent won (total weighted magnitude 115.0 across 15
topics), the diagnosis pass attributed:

| rank | factor | n criteria | weight | % of loss |
|---|---|---:|---:|---:|
| 1 | **Incomplete implicit-requirement decomposition** (`not_decomposed`) | 32 | 55.0 | 47.8% |
| 2 | **Shallow coverage of identified facets** (`covered_but_shallow`) | 29 | 54.5 | 47.4% |
| 3 | other/decomposed-not-covered | 2 | 5.5 | 4.8% |

These two factors are ~evenly split and together explain 95% of the weighted
gap. They are two faces of the same root cause (see below), not independent
problems.

### Factor 1 — step-1 decomposition misses implicit, context-inferred requirements (47.8%)

`prompts.py`'s step 1 (Phase 1/Phase 3 fixes, 2026-08-05) already fixed
**explicit bundled items** ("compare X, Y, and Z" → one requirement per
item). The remaining gap is **implicit dimensions the request never names**
but the topic type implies: regulatory/compliance regimes (GDPR/CCPA/PIPL),
cost-effectiveness, migration trade-offs/risk analysis, definitional
scaffolding for technical terms introduced mid-answer. facets_agent's own
step-1 enumeration for the software-scaling topic
(`6847465956a0f6376a60542a`) listed 9 requirements, all textually present in
the request — but never surfaced "GDPR/CCPA compliance" or "migration risk
analysis," both of which aus_agent covered and which the rubric explicitly
rewards (w=+3.0, w=+4.0).

**Fix**: extend `prompts.py` step 1 with a standing checklist of
commonly-implicit dimensions to actively check for (not just the request's
literal wording) — trade-offs/risks, cost, compliance/regulatory
requirements, terminology grounding — mirroring how Phase 1 already fixed
explicit-item bundling but leaving implicit-dimension coverage unaddressed.

### Factor 2 — facets are found and searched, but the answer stays generic (47.4%)

The facet IS in the enumeration, gets searched, evidence gets committed —
but the final sentence names a *category* ("use caching," "add monitoring")
instead of the *specific mechanism* the corpus surfaced and the rubric wants
(Redis/Memcached + TTL/eviction policy; Prometheus/Grafana + PagerDuty;
Kafka/RabbitMQ + fan-out-on-write vs fan-out-on-read).

This traces to a real tension in the current prompt (`prompts.py:128-134,
181-183`): step 3 says "**keep each facet's committed evidence minimal**...
commit only a result that adds something the facet doesn't already have,"
and step 5/closing says "**match the report's length to the request... not
padding toward a limit**." Both instructions conflate two different things —
*redundant restatement* (padding, correctly discouraged) and *concrete
specificity* (naming the actual product/number/mechanism a criterion wants,
currently getting suppressed as if it were padding).

**Fix**: add one sentence to `prompts.py` distinguishing the two explicitly
— e.g. "A named product, technology, number, or mechanism is never padding,
even if the facet already has a general answer; only restating the same
specific fact twice is." This is a single-line, low-risk prompt change
consistent with the file's own stated norm (`prompts.py` docstring: fix
things via prompt wording first, matching how Phases 1 and 3 were done).

### Factor 3 (supporting, not independently actionable) — retrieval/synthesis ratio

The structural over-fetch/under-write ratio (2.6x docs, -22% words) is the
mechanical symptom of factors 1+2, not a separate cause. Worth tracking as a
regression metric after any prompt change: fixing 1/2 should tighten this
ratio toward aus_agent's without a deliberate "write more" instruction (which
would risk reintroducing padding).

### Minor / low-confidence

- facets_agent's near-100% citation-per-sentence discipline (97% vs
  aus_agent's 76%) may itself be squeezing out synthesis sentences, since the
  prompt only allows an uncited sentence to "organize or connect" already-
  cited material, never introduce anything new. Consistent with factor 2 but
  didn't surface as its own diagnosis stage — not a priority change yet.
- facets_agent won 2 topics' Communication Quality criteria (list/table
  structure) despite the prompt's "No Markdown" rule, via structured prose.
  Not a fix target — just evidence the rule isn't costing structure quality.

## Recommended next step

Two single-sentence, low-risk additions to `src/systems/facets_agent/prompts.py`
(both prompt-only, matching this file's own established pattern for Phases
1/3): (a) a standing implicit-dimension checklist in step 1, (b) the
padding-vs-specificity distinction in step 3/step 5. Re-run the same 15-topic
version-tagged comparison (new run-id, current git SHA) after the change to
measure the effect against this worklog's baseline — the `not_decomposed`
and `covered_but_shallow` weighted percentages above are the numbers to watch.
