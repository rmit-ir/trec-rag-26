# 2026-08-06 — rubric-driven prompt optimization: what moved the score, and what did not

A full single-factor screen of 12 prompt variants against the official
ResearchRubrics dev set, plus the harness and model changes discovered along the
way. **The headline is a negative result with a positive corollary: no prompt
patch banked, while two non-prompt changes delivered +0.095 between them.**

Everything below is reproducible from artifacts on disk. Run ids, scripts, and
raw numbers are named at each step.

---

## 1. Why the measure changed

The prior loop scored answers by anonymized pairwise *arena* battles against the
organizer baselines. That was abandoned for three reasons, each measured:

- **The arena is a dead heat and judge-dependent.** `ours-keyword` vs
  `base-agentic-bm25` scored 0.4853 over 238 both-order battles. Worse, the
  verdict moves with the judge's *identity* — see §2.
- **It resolves nothing at n=20.** Order consistency is 0.782, so the judge
  disagrees with itself on 22% of topics from presentation order alone.
- **The dev set has ground truth.** 30 ResearchRubrics topics ship 755 weighted
  criteria. Scoring against fixed criteria needs no opponent and no baseline.

## 2. Judge identity moves the arena by 0.275 — measured, not assumed

Identical answers, identical topics, only the judge changes:

| judge | wrote what | ours-keyword | ours-semantic | verdict |
|---|---|---|---|---|
| `gpt-5.6-luna` | **our** answers | 0.450 [0.250, 0.650] | 0.425 [0.250, 0.600] | INCONCLUSIVE |
| `gpt-5.6-terra` | neither side | 0.250 [0.125, 0.400] | 0.300 [0.150, 0.450] | KILL |
| `gpt-5.6-sol` | **both baselines** | 0.175 [0.025, 0.350] | 0.250 [0.100, 0.425] | KILL |

Monotone in affiliation, on both runs independently. The published 0.485 "dead
heat" is a luna number and luna is the interested party. Under a disinterested
judge we were clearly behind — which independently corroborated what weighted
citation support already said (−0.073 paired, worse on 14/20).

Notably this does **not** transfer to rubric grading: sol scores luna-written
answers *higher* than luna does (0.5557 vs 0.5350). Rubric grading is an
entailment check against fixed criteria, structurally far less prone to
self-preference than a preference vote.

## 3. The official rubrics cannot be scored as shipped

`tasks/task-comparison/scripts/fix_dev_rubrics.py` →
`data/task-comparison/dev-rubrics-fixed.jsonl` (+ `dev-rubrics-waived.md`).

Two independent defects, both of which corrupt a score silently:

- **97 of 755 criteria carry NEGATIVE weight** (−5 to −1) — the penalties
  ("the response incorrectly defines a theorem", "contains messy, unnecessary
  formulas"). RAGDoll's `_coerce_criterion` does `if weight <= 0: return None`,
  so feeding the official file to its loader **deletes exactly the criteria that
  detect bad behaviour** — 13.0% of criteria, 14.0% of absolute weight, on all
  30 topics. Scores can only inflate, and nothing says so.
- **53 criteria demand output the TREC answer contract forbids** — 33 visual
  ("includes a geometric diagram"), 12 Markdown/layout, 8 citation apparatus
  (MLA/APA format, rendered reference lists). No conforming submission can
  satisfy them; grading them as failures penalizes obeying the rules.

Resolution: penalties kept with `signed_weight` (satisfying one *subtracts*),
impossible criteria waived out of both numerator and denominator with an
auditable reason. **Word-count criteria were checked individually rather than
waived as a class** — "at most 2,000 words" is *satisfied* by a 1,024-word
answer and is free points; only a lower bound above the cap is a real conflict,
and none existed. Waiving them would have handed us 8 undeserved weight-points.

## 4. Instrument defects found — each produced a plausible wrong number

None of these threw an error. That is the point.

| defect | symptom | fix |
|---|---|---|
| single-shot grading | judge spread is **0.072/topic**, larger than every effect being screened; one arm banked then un-banked on a re-grade, its target axis flipping +0.086 → −0.018 | `--repeats 3`, averaged; noise floor reported next to every result |
| grading cache keyed by topic only | rubric changed between two arms → cached verdicts silently realigned onto a different criteria list; arms scored against 710 vs 702 criteria and both looked fine | SHA fingerprint of the exact criteria list per cache entry |
| failed runs scored as answers | a 401 wrote 30 stubs reading `"Run failed: AuthenticationError…"`, which parse as valid answers and score exactly 0.0 — logged as a **−0.55 catastrophic regression** | `load_run` requires `trace.status == "completed"`; refuses to score when nothing survives |
| resume counted stubs as done | `sol-dev30-minimal` sat at 29 answers + 1 error message; the retry silently did nothing | same status check in `run_topics_parallel.sh` |
| failure records cached | a transient 401 poisoned a topic permanently | only `completed` records are written |
| `metadata.model` read from the wrong key | model id lives in `trace.metadata`; spend reported **$0.00** for a $4 run | read `trace.metadata.model` |
| spend summed from `trace.summary.cost` | pre-instrumentation runs have tokens but empty cost blocks — understated spend ~45% | price from `trace.summary.tokens`, which every artifact has |
| budget matched `run_id` by literal prefix | `sol-dev30-*` and `v2-dev30-*` never charged; reported $28 against a true $108 | substring match on `dev30-` |
| judge model read from `OPENAI_MODEL_ID` | switching the *generator* to sol would have silently switched the *judge*, orphaning every prior arm | `default_judge()` separate from `default_model()` |

**Pattern worth naming: a broken input that looks like a valid one is far more
dangerous than a crash.** Seven of the nine above are that shape.

## 5. The judge: sol is quieter, and that buys resolution

Same 30 baseline answers, three gradings each:

| judge | noise/topic | mean | <0.65 | severe | cost |
|---|---|---|---|---|---|
| luna | 0.0720 | 0.5350 | 24 | 16 | $0.50 |
| **sol** | **0.0437** | 0.5557 | 20 | 11 | $3.37 |

39% quieter → smallest resolvable mean effect drops ~0.030 → ~0.018. Judge
pinned to sol (`judge_client.default_judge`), `RUBRIC_JUDGE_MODEL` overrides.

## 6. What actually moved the score

Decomposed, separating measurement changes from real gains:

| | mean | note |
|---|---|---|
| starting baseline (luna gen, luna judge) | 0.5350 | |
| ↳ under sol judge | 0.5557 | +0.021 — **measurement**, not improvement |
| ↳ locale fix (UTC clock, no `AUS` title) | 0.5810 | **+0.025 real** |
| ↳ sol as generator | **0.6508** | **+0.070 real**, CI [+0.0404, +0.1014] |

**+0.095 of genuine improvement, none of it from a prompt patch.**

### 6a. The locale fix

Every request began with
`Current date and time: … +1000 (Australia/Melbourne)` from `agent.now_full()`,
and every prompt was titled `# AUS research agent`. A `localization` patch had
been written to tell the model *not* to volunteer Australian framing — fighting
a cue the harness supplied on every topic. Fixing `now_full()` to emit UTC and
retitling 22 prompt files was worth **+0.0253**, more than any patch screened.
The patch was retired without ever being run.

### 6b. sol as generator

`sol-default` 0.6508 vs `v2l-default` 0.5810: **+0.0698, CI [+0.0404, +0.1014]**,
better on 24/30 topics. `sol-minimal` vs `v2l-minimal`: +0.0609
[+0.0281, +0.0940]. Both clear zero decisively — the only unambiguous wins in
the study. Topics below 0.65 fall 20 → 13; severe penalties 11 → 6.
Cost: $31.88/arm vs luna's $3.45.

## 7. The full single-factor screen — 12 arms, 0 banked

Control `v2l-default` = 0.5810. 30 topics, sol judge, 3 gradings averaged,
post-UTC-fix, luna generator. Run ids `v2l-dev30-*`. Variant descriptions:
`docs/auto-optimize/variants.md`.

| arm | mean | delta | 95% CI | better | <0.65 | severe | verdict |
|---|--:|--:|---|--:|--:|--:|---|
| finish-the-claim | 0.6047 | +0.0237 | [−0.0030, +0.0515] | 21/30 | 18 | 9 | — |
| english-only | 0.5923 | +0.0113 | [−0.0102, +0.0338] | 17/30 | 18 | 10 | — |
| minimal | 0.5857 | +0.0047 | [−0.0274, +0.0381] | 16/30 | 18 | 10 | — |
| no-meta-reference | 0.5853 | +0.0043 | [−0.0145, +0.0225] | 16/30 | 19 | 9 | — |
| name-the-source | 0.5793 | −0.0016 | [−0.0244, +0.0206] | 13/30 | 21 | 10 | — |
| decision-item | 0.5743 | −0.0067 | [−0.0328, +0.0190] | 13/30 | 19 | 14 | — |
| paired-lead | 0.5737 | −0.0073 | [−0.0292, +0.0143] | 13/30 | 19 | 12 | — |
| compression | 0.5697 | −0.0113 | [−0.0368, +0.0140] | 14/30 | 18 | 12 | — |
| stated-form | 0.5675 | −0.0134 | [−0.0357, +0.0084] | 15/30 | 21 | 12 | — |
| reading-a-result | 0.5617 | −0.0192 | [−0.0439, +0.0048] | 10/30 | 18 | 14 | — |
| decision-lead | 0.5578 | −0.0232 | [−0.0416, −0.0050] | 8/30 | 20 | 12 | **KILL** |
| cite-or-cut | 0.5474 | −0.0335 | [−0.0555, −0.0099] | 10/30 | 21 | 13 | **KILL** |
| *(control)* | 0.5810 | — | | | 20 | 11 | |

**Readings.**

- **Nothing banks.** With the noise floor at ~0.018 and a properly powered
  design, the best patch still misses by 0.003. This is not "underpowered" —
  it is a screen that ran and returned a negative result.
- **Two patches actively hurt.** `cite-or-cut` (−0.0335) told the agent to cut
  every sentence it could not cite; against rubrics that reward breadth under a
  word cap, deleting content costs more than the citations gain.
  `decision-lead` (−0.0232) reordered the answer to lead with the decisive
  finding and lost more elsewhere.
- **`minimal` ties `default` at 77% of the size** (3,631 B vs 15,910 B).
  Per-axis it *gains* References +0.255 and Synthesis +0.085 while losing
  Communication −0.051. All the procedural scaffolding — success plan, coverage
  areas, query-formulation rules, research loop, stopping heuristics — buys
  nothing measurable.
- **Prompt effects may not transfer across generators.** On luna,
  `minimal` > `default` (+0.0047); on sol, `default` > `minimal` (−0.0043).
  Both insignificant, but the sign flips — a caveat on screening cheaply and
  confirming expensively.

## 8. Where the ceiling comes from

- **The answer is word-bound, not context-bound.** Answers run 844–891 words
  against the 1,024 cap with maxima of 1003–1022, while peak context is
  **36.5k of a 500,000-token budget (7.3%)**. The "Budget and stopping" prompt
  section describes a constraint that never binds.
- **The rubrics assume a longer answer than the contract allows.** ~20.4 reward
  criteria per topic; the rubrics' own criteria reference 2,000-word responses.
  At 1,024 that is ~50 words per criterion; we write ~43.
- **The failure profile is correct triage, not sloppiness.** Weight-5 criteria
  satisfied 63.7%; weight-2, 31.6%. The agent covers what matters first.
- **25.2% of criteria land *partially satisfied*** — raised but not landed.
  That pool is worth ~0.08–0.10 and, unlike the 33.4% missing, does not need
  more words. `finish-the-claim` was built for it and is the top arm.

## 9. Document trustworthiness — the model is already good at one half

`tasks/task-comparison/scripts/doc_quality.py`. ClimbMix exposes **no
provenance**: the doc endpoint returns a bare string — no URL, domain, author,
or date. Credibility must be judged from prose. Scorer uses three signal
families (specificity; content-farm/SEO register; LLM-generated tells), scored
over 5,928 cached documents.

| | corpus available | documents we cited |
|---|---|---|
| mean quality | 0.360 | **0.497** (CI [0.467, 0.526]) |
| share filler (<0.20) | 31.7% | **8.3%** |
| share evidential (≥0.70) | 9.8% | 11.8% |

**The agent already rejects junk 4× better than chance, and finds the best
barely above chance.** So a quality *gate* at commit would replace a working
filter with a cruder one. The leverage is at the top end — annotate search
results and let the model break ties — and ultimately in retrieval: if only
9.8% of what comes back is evidential, citing better than 11.8% is impossible
however well the agent chooses.

Corollaries: **information-gain scoring is unnecessary** (100% of listed
references are cited — 14.0/14.0, nothing redundant survives), and **diversity
scoring is unnecessary** (dense/sparse are already 93% disjoint).

## 10. Cost

Per-arm, 30 topics: luna generation $3.45, sol generation $31.88 (9×), sol
grading ~$3.4 (3 repeats). Session total at time of writing: **$201.24 of the
$500 cap**, 438 topics priced.

Pricing tables for gpt-5.6-{luna,sol,terra} are committed under
`src/ragrun/prices/` — **operator-supplied list prices converted to per-1K, NOT
fetched from the AWS Pricing API** (no credentials on this host); the `source`
field of each table says so.

`aus_agent` never called `cost_for_provider`, so `stats.cost` was never attached
and every run reported `unpriced_calls`. Now attached in `_turn_stats`, the one
place every turn passes through. `reasoning_tokens` is now captured too — every
run to date used the API's default reasoning settings (`effort=medium`,
`mode=standard`) and recorded nothing about them.

## 11. Operational notes

- **The Bedrock credential is a ~2,500-char AWS STS session token, not an
  `ABSK` long-term key.** Observed alive 11:24 → 14:35 UTC, first 401 at 14:42:
  **≥3.3 hours**, dying inside a 7-minute window. It killed an arm mid-run. Any
  unattended sequence longer than ~3 hours will be cut in half.
- **Topics are independent; run them in parallel.** `run.py --all` is
  sequential — 99s/topic × 30 = ~50 min/arm. `run_topics_parallel.sh` at
  concurrency 6 does the same in ~9 min, with artifact-driven resume.
- **`get_documents` is effectively dead**: 19 calls against 1,862 searches (1%),
  after both a rewritten description and an explicit prompt rule routing to it.

## 12. What follows

Agreed plan: **finish the luna screen as a shortlist (done, §7), then spend on
tool changes rather than more prompt variants.** The evidence is that harness
changes returned +0.095 while twelve prompt variants returned nothing bankable.

1. **`reasoning.effort` / `reasoning.mode`** — plumbed and defaulted-off
   (`--reasoning-effort`, `--reasoning-mode`, `OPENAI_REASONING_*`), untested.
   Cheapest remaining experiment with real upside: $3.45 on luna.
2. **Fact extraction at commit time** — extend `commit_context`'s `reason` to
   require the specific value being kept (figure, date, source, scope). Attacks
   the 25.2% partial-credit pool at the architecture level, where
   `reading-a-result` tried prose and scored −0.0192.
3. **Fold `get_documents` into `search`** — return neighbouring pages of a
   high-scoring chunk automatically and delete the tool.
4. **`doc_quality` as a search-result annotation and tie-breaker**, explicitly
   not a gate (§9).
5. **Confirm `finish-the-claim` on sol** — the only near-significant arm, and
   sol is the generator we would ship.

Tool snapshots are taken before each change:
`worklogs/assets/2026-08-06-aus-agent-tools-<tag>/` via
`tasks/task-comparison/scripts/snapshot_tools.py`. The tool *description* is
part of the prompt the model sees, so a one-word edit changes behaviour as
surely as a prompt patch — and is far easier to make without noticing.

## Artifacts

- protocol + goal + leaderboard: `docs/auto-optimize/README.md`
- variant descriptions in prose: `docs/auto-optimize/variants.md`
- patch ledger: `docs/auto-optimize/patches.md`
- per-arm results: `docs/auto-optimize/rubric-results.jsonl`
- charts: `docs/auto-optimize/progress.svg`, `experiment-mindmap.svg`
- goal check (exit 0 = met): `tasks/task-comparison/scripts/goal_status.py`
- rubric fix + waiver audit: `data/task-comparison/dev-rubrics-{fixed.jsonl,waived.md}`
- frozen splits: `data/task-comparison/topics-{dev20,confirm40,holdout59}.tsv`

---

## 13. After the prompt screen: model, reasoning, and tool levers

The screen in §7 closed the prompt lever. What follows is every non-prompt lever
tried since, with the reason each closed — the reasons matter more than the
nulls, because a null with no mechanism is indistinguishable from a botched
implementation.

### 13a. `reasoning.mode = pro` — not available, proven in two seconds

Accepted by the Bedrock gateway and apparently inert (+10% reasoning tokens).
Rather than run a $32 arm on an ambiguous signal, a discriminator settled it:

```
effort=bogus   REJECTED  "Invalid value: 'bogus'. Supported values are: 'none', ..."
mode=bogus     ACCEPTED  (no validation)
mode=pro       ACCEPTED  (no validation)
```

The gateway validates `effort` strictly and **does not parse `mode` at all**.
Confirmed against documentation: pro is honoured only by OpenAI's own API and
Azure; Bedrock's OpenAI-compatible endpoint accepts and silently ignores it.
Also learned: `mode=pro` does **not** raise effort — it leaves it at `medium`,
so the valid A/B would have been `{pro,xhigh}` vs `{standard,xhigh}`, not the
`pro/medium` vs `standard/medium` first attempted.

### 13b. `reasoning.effort` — real, but does not bind on this workload

Plumbed (`--reasoning-effort`, `OPENAI_REASONING_EFFORT`) with
`reasoning_tokens` captured for the first time. In isolation the ladder is real
and monotone — low 57, medium 68, high 79, xhigh 116 reasoning tokens on one
hard prompt. **In the agent loop it barely moves**: 612 / 639 / 684 tokens per
topic for medium / high / xhigh — +12%, not the +70% isolation suggested.

| arm | vs control | 95% CI |
|---|--:|---|
| effort=medium | −0.0115 | [−0.0343, +0.0126] |
| effort=high | −0.0160 | [−0.0434, +0.0127] |
| effort=xhigh | −0.0028 | [−0.0265, +0.0223] |

Mechanism: most turns in an agentic loop are tool-calling turns that need no
deliberation. Raising the ceiling on turns that never approach it does nothing.
**Caveat, stated because it was initially overstated:** this was measured on
luna only, and `max` is documented as sol-only. The null is luna's; the
parameter is not fully closed on sol.

### 13c. `evidence_density` — the idea was fine, the implementation was wrong

First implementation attached an absolute 0–1 heuristic score to every search
result. Score effect: −0.0065. The audit showed the model *did* read it — cited
results averaged 0.243 against 0.205 for uncited — but the distribution was
useless:

| | mean | median | <0.20 | ==0.000 | >0.50 |
|---|--:|--:|--:|--:|--:|
| search-result chunks | 0.212 | 0.150 | 61.2% | 21.0% | 9.8% |
| full documents | 0.347 | 0.320 | — | — | 30.2% |

**The scorer was calibrated on full documents (~2,000+ words) and applied to
chunks (~500–800).** Per-1k-word rates are unstable at that length: six "you"s
in a 300-word chunk reads as 20/1k and takes the full second-person penalty; the
same six in a 3,000-word document reads as 2/1k and takes none. 61% of results
landed under 0.20 and 21% at exactly zero — a tie-breaker whose candidates are
all indistinguishably near-zero cannot break ties.

Replaced with `evidence_rank` — position **within the batch** (`"3 of 20"`).
Rank sidesteps calibration entirely: the model is choosing among these results,
so relative order is all it needs, and ordering is invariant to the length
effects that wrecked the absolute number.

### 13d. LLM source grading — replacing the heuristic with judgement

`commit_context` gains an optional `source_grade`: the model classifies each
kept document as `research | official | journalism | reference | commercial |
forum | unclear`, judged from its prose.

Three reasons this is the better instrument:

- **It measures what the rubrics score.** −4 for citing forum or wiki material
  to justify a claim, −5 for citing work that does not exist. Those are
  questions about what a source *is*, not about figure density.
- **Only the model can answer.** The corpus exposes no provenance — the doc
  endpoint returns a bare string, no URL, author, or date. The agent reading the
  prose is the only component with the evidence.
- **It is free where it happens.** A separate classifier pass would re-send
  ~2–3 KB × 20 results per round to judge text the agent already holds. Grading
  at commit reuses that context at zero marginal cost.

`unclear` is in the enum deliberately: forcing a grade on an unplaceable
document produces a confident wrong label, and the −5 penalty for fabricated
attribution makes that the expensive direction to be wrong in.

### 13e. Fact extraction at commit time

`commit_context.facts[]` — `claim` / `value` / `scope` / `source`, extracted
while the document's text is still in context. Targets the 25.2% of criteria
scoring *partially satisfied* and the 42–47% of omitted figures that were in
documents the agent itself cited.

**Two single-topic tuning passes, and the second made it worse** — value fields
containing a digit went 18.4% → 10.5% after "tightening" the schema. That
comparison is worthless: n=1, a geometry-pedagogy topic (among the least numeric
in the set), two stochastic runs, against a system whose judge noise alone moves
a score by 0.011. **Recorded as a methodological error rather than a result** —
it is the same mistake the repeat-grading guard in §4 exists to prevent,
committed one layer up.

Corpus reference gathered instead of more tuning: **7.5 hard figures per 1k
words on average, median 4.2, and 22% of documents contain none at all.** The
material is thinner than the schema assumed, so prose in `value` may reflect
documents that carry no verbatim number rather than a model that will not
comply.

### 13f. A confound caught before it was paid for

`facts` and `evidence_rank` were both implemented before either was measured,
and both were live in the same code. Two "single-factor" arms would have been
**the identical configuration run twice** — two confident numbers about nothing.
Every tool change now sits behind its own environment toggle
(`AUS_AGENT_COMMIT_FACTS`, `AUS_AGENT_COMMIT_SOURCE_GRADE`,
`AUS_AGENT_EVIDENCE_RANK`), read at call time rather than import time, so an arm
measures exactly one change. The run was killed and its 9 partial artifacts
removed.

### 13g. Tool versioning

`tasks/task-comparison/scripts/snapshot_tools.py` copies the 8 files making up
the model-facing surface into `worklogs/assets/2026-08-06-aus-agent-tools-<tag>/`
with SHA-256s, sizes, git HEAD and a dirty-tree flag. Snapshots so far:
`v1-reasoning-plumbed`, `v2-pre-doc-quality`, `v3-pre-facet-backend`,
`v4-pre-fact-extraction`, `v5-pre-toggles`.

Beyond what git gives: **a tool's description is part of the prompt the model
reads**, so a one-word edit changes behaviour exactly like a prompt patch, and
answering "what was the contract when run_id X was generated" from a commit
graph that also holds unrelated work is the wrong instrument.

### 13h. facet_rag

Runs on sol after adding `--backend {bedrock,openai}` — both roles were
hardcoded to `make_provider("bedrock", …)`, which needs AWS credentials this
host does not have. One topic completed: 4 facets, 23 searches, 569 words,
**$3.14/topic — 3× aus_agent's $1.06**, largely because it constructs a fresh
provider per role per call and therefore gets **zero cache reads** (286k input
tokens, `cache_read: 0`). Parked at the operator's direction.

Note for any future comparison: its stock config is a genuinely
heterogeneous three-model system (orchestrator `gpt-oss-120b` ap-southeast-2,
analyzer `qwen3-next-80b` us-east-1), neither reachable through this gateway.
Running it on sol collapses all three roles onto one model, so the comparison
reads as architecture **plus model mix**, not architecture alone.

---

## 14. Confirmation on the shipping generator, and a ninth measurement bug

### 14a. `finish-the-claim` does not confirm on sol

The top of the twelve prompt arms (+0.0237 on luna, the only CI to miss zero by
less than the noise floor) was re-run on sol, the generator we would ship:

```
sol-finish-the-claim vs sol-default   (both judged by sol)
mean 0.6508 -> 0.6369   paired delta -0.0139  CI [-0.0334, +0.0041]  better 13/30
below 0.65  13 -> 14    severe penalties  6 -> 8
```

Trends negative and worsens both safety conditions. **Not confirmed.**

### 14b. The comparison script compared across judges

The first run of that comparison reported **+0.0173** — a false positive. The
script keyed results by variant name alone, and `sol-default` exists under two
judges (sol 0.6508, terra 0.6195). It silently compared the sol-judged arm
against the **terra-judged** control, turning a −0.014 regression into a +0.017
improvement.

Ninth measurement defect of the session, and the same shape as the other eight:
**not a crash, a plausible wrong number.** Rows are now keyed on
`(variant, judge)` and the judge is printed in the header.

### 14c. Does luna screening transfer to sol? Yes — nothing was missed

The worry was that twelve arms screened on luna measured the wrong system. Two
prompts have now been run on both generators:

| prompt | luna | sol | sol − luna |
|---|--:|--:|--:|
| default | 0.5810 | 0.6508 | +0.0698 |
| minimal | 0.5857 | 0.6465 | +0.0608 |

The **generator** effect transfers cleanly (+0.070, +0.061). The **prompt**
effect flips sign (`minimal` +0.0047 on luna, −0.0043 on sol) — but both are
inside the noise floor, as is `finish-the-claim` on both generators (+0.024 /
−0.014). The correct reading is **not** "luna is a poor proxy" but "prompt
effects are noise on both generators". Screening cheap was sound, and there is
no case for re-screening twelve arms at sol prices (~$400).

### 14d. Second-judge confirmation — goal condition 4 met

```
sol-default   judge=sol    0.6508   <0.65=13   severe=6
              judge=terra  0.6195   <0.65=17   severe=9
```

Terra scores 0.031 lower — some self-preference in sol grading sol-written
answers, but far below the arena's 0.275 swing, and the ordering is unchanged.
Rubric grading is an entailment check against fixed criteria and is structurally
more robust than a preference vote. **The generator win is real, not a judging
artifact**; the defensible session gain against a disinterested judge is
+0.065–0.070 rather than the +0.095 headline, since part of that was the judge
change, which was measurement rather than improvement.

### 14e. `known-candidates` — a well-evidenced hypothesis, refuted

Of the high-weight Implicit criteria the best run misses, **20 of 20** name an
entity the question never mentions (Roth, Nasdaq, Russell 2000,
"board-certified dermatologists"), and `default.md` forbade searching for
exactly those. Relaxing the rule to "prior knowledge decides what to look FOR,
only retrieval decides what you may ASSERT" scored **+0.0105
[−0.0160, +0.0370]** — and **Implicit Criteria went DOWN (−0.0111)**, the axis
it was built to move.

So the prohibition was not the binding constraint. The agent does not fail to
cover Roth-vs-traditional because it was forbidden to look; it fails because it
does not work out that the question implies it. Knowing what a complete answer
requires is a harder problem than being permitted to search for it.

### 14f. Final tally — 24 arms

| operates on | arms | result |
|---|---|---|
| answer wording | 12 prompt patches | 0 banked, 2 killed |
| reasoning depth | 3 effort rungs, `mode=pro` | null / unavailable |
| document selection | `evidence_rank`, `source_grade` | null |
| what is recorded | `facts` | null |
| search permission | `known-candidates` | null |
| **harness cues** | **locale fix** | **+0.025** |
| **who writes** | **luna → sol** | **+0.070** |

**Recommended configuration: the plain `default` prompt on `gpt-5.6-sol` with
the UTC clock.** No patch, no tool addition — it beats everything built here.

Twenty-one single-factor arms failed to move the score on an instrument that
could resolve them (judge noise 0.043, floor ~0.018, 3 gradings, 30 topics).
The two that worked were structural. The remaining 0.149 sits in Implicit
Criteria — 38.4% of weight, 0.651, **0.134 recoverable** — which requires the
agent to work out what a question implies before deciding it is done, and which
no single-factor arm has touched.

---

## 15. The last three arms — and two conclusions I had to retract

### 15a. Tool changes combined on sol — worse, not additive

All three tool changes enabled together on the shipping generator:

```
sol-tools vs sol-default   (both judged by sol)
mean 0.6508 -> 0.6295   paired delta -0.0213  CI [-0.0467, +0.0041]  better 12/30
below 0.65  13 -> 13    severe penalties  6 -> 11
```

Three orthogonal changes, individually flat, together trend negative — and
**severe penalties nearly double**. The penalty jump is the informative part:
asking the model to extract facts, grade sources *and* weigh a rank on every
commit adds bookkeeping to the exact turn where it decides what evidence to
keep, and something gets crowded out. Combination was the one place these could
plausibly hurt, and it did.

### 15b. Coverage audit — the mechanism worked, the score did not

A harness-injected turn, fired once, at the moment the agent first emits no tool
calls (i.e. has decided it is finished): *list what a knowledgeable reader would
expect a complete answer to contain, including what the request implies but
never states; say whether committed evidence supports each; then search the
gaps.* A structural interrupt rather than advice competing with 16 KB of other
advice in the system prompt.

It changed behaviour — the first intervention all session to move trajectory
shape rather than wording. Smoke run: agent finished at round 7, the audit sent
it back for **four more searches and another commit round**, ending with 21
references instead of the usual 14.

```
v2l-coverage-audit vs v2l-default
mean 0.5810 -> 0.5978   paired delta +0.0168  CI [-0.0149, +0.0499]
Implicit Criteria  0.5973 -> 0.6084  (+0.0111)
Communication Quality  0.4427 -> 0.3869  (-0.0558)
```

More evidence, no better answer. **Retraction:** on this result I concluded "the
binding constraint is the answer budget, not the agent's judgement." §15c shows
that was wrong.

### 15c. The word cap was never binding — retracting §8

Given explicit permission to write to ~2,000 words:

| | mean words | max | over 1,024 | score |
|---|--:|--:|--:|--:|
| control | 894 | 1024 | 0/30 | 0.5810 |
| 2,000-word allowance | **898** | 1024 | 0/30 | 0.5699 |

**The model wrote four more words.** It never approached the allowance. So the
1,024 cap was never the ceiling: the agent stops at ~890 words because that is
where it runs out of things to say.

This retracts two earlier claims:

- §8's "the answer is word-bound" and §15b's "the budget is the constraint".
  Both wrong. The ceiling is what the agent can find and say.
- The arithmetic in §8 — that our 41.4% satisfied rate tracked our 44.5% share
  of the rubrics' assumed 2,000-word budget — was **a coincidence of two numbers
  that I built an explanation on**. Recorded as a warning: it was persuasive,
  quantitative, and false.

### 15d. Final tally — 27 arms

| operates on | arms | result |
|---|---|---|
| answer wording | 12 prompt patches | 0 banked, 2 killed |
| reasoning depth | 3 effort rungs, `mode=pro` | null / unavailable |
| document selection | `evidence_rank`, `source_grade` | null |
| what is recorded | `facts` | null |
| all three tools together | 1 | −0.021, penalties 6→11 |
| search permission | `known-candidates` | null, Implicit went DOWN |
| coverage judgement | `coverage-audit` | null (mechanism verified) |
| answer length | `wordcap-probe` | null (allowance unused) |
| **harness cues** | **locale fix** | **+0.025** |
| **who writes** | **luna → sol** | **+0.070** |

**24 of 27 arms measured zero** on an instrument resolving to ~0.018 (judge
noise 0.043, 3 gradings, 30 topics). The two that worked were structural.

**Recommended configuration: plain `default` prompt on `gpt-5.6-sol` with the
UTC clock.** No patch, no tool addition.

### 15e-pre. Retraction: reasoning effort was closed on the wrong model

§13b concluded that `reasoning.effort` "does not bind on this workload", from
612 / 639 / 684 reasoning tokens per topic at medium / high / xhigh. **Every one
of those measurements was on luna.** `max` is documented as sol-only and was
never tested on the generator we ship.

Measured on sol, one prompt, identical text:

| effort | reasoning tokens | vs medium | latency |
|---|--:|--:|--:|
| medium | 467 | — | 26.2s |
| xhigh | 2,070 | **4.4x** | 41.6s |
| max | 3,106 | **6.6x** | 48.3s |

A 6.6x compute range, against luna's +12%. The luna null said nothing about sol.
Worse, the luna arm that was run used `high` — a rung worth +16% compute — chosen
without measuring the ladder first, so it was underpowered by construction.

**Third instance of one error in different clothing**, and the reason it is worth
naming separately each time:

- the evidence scorer: calibrated on full documents, applied to chunks
- `finish-the-claim`: screened on luna, confirmed on sol only after prompting
- `reasoning.effort`: measured on luna, generalised to a model where it behaves
  six times differently

In each case the idea was sound and the measurement was not. "The result is
null" and "the measurement could not have detected it" look identical in a
results table.

### 15e. What is actually left

Both remaining structural explanations are now eliminated: coverage judgement is
not the limit (the audit found gaps and changed nothing) and the word budget is
not the limit (the allowance went unused). The agent finds what it can find and
says what it can say; 0.65 is where that lands on these rubrics.

What that leaves, none of which is another single-factor arm:

- **The retrieval corpus.** 22% of ClimbMix documents contain no hard figure;
  median 7.5 per 1k words. Cited-source quality does not predict rubric score
  (r = −0.085, −0.182), so this is not about picking better documents from what
  is there — it is about what is there.
- **A different agent architecture.** facet_rag is implemented and runnable on
  sol (§13h) but was parked; it is the only alternative architecture available.
- **Accepting 0.65 as the honest number** for this system on these rubrics.

### 15f. A note on the stopping rule

The `/goal` loop could stop on *goal met* or *budget exceeded*. An exhaustion
clause was removed at the operator's direction — correctly, since "we have run
out of ideas of one kind" is an operator judgement, not a scoreboard's. But that
left no way to represent the state actually reached: **search space empty,
budget unspent** ($336 of $500). The loop kept requesting continuation with no
defensible hypothesis remaining.

If this harness is reused unattended, the clause should return with an
operator-chosen threshold — e.g. three consecutive nulls after the last banked
change — so it stops on evidence rather than on judgement or not at all.

---

## 16. Arms 28-29, and the measurement that should have come first

### 16a. `effort=max` on sol — a properly powered null

§15e-pre established that the effort ladder is real on sol (6.6x medium) and had
only ever been measured on luna. Arm 28 ran it:

```
sol-effort-max vs sol-default   (both judged by sol)
mean 0.6508 -> 0.6459   paired delta -0.0048  CI [-0.0323, +0.0234]  better 15/30
below 0.65  13 -> 14    severe penalties  6 -> 8
reasoning tokens: 1,564/topic (medium run predates capture; probe measured 467)
```

The knob fully engaged and quality did not move. **Reasoning effort is now
closed on both generators** — and closed properly, by a test that could have
detected an effect, rather than by inference from the model where the ladder is
flat. The earlier luna-only conclusion was right for the wrong reason.

### 16b. Cost was under-reported by ~$70 for several turns

I estimated the `effort=max` arm from medium-effort rates. Max-effort reasoning
tokens bill as output, so the real figure was far higher: the goal check read
**$457.43 of $500 (91.5%)** when I had been reporting ~$385. The pricing layer
had the correct number throughout; I simply did not re-run it after launching.

**Operational fix if this harness runs unattended:** call `goal_status.py` after
every arm, not when the operator asks. A budget that is only checked when
someone thinks to check it is not a budget.

### 16c. The budget guard trips too late

`goal_status.py` emits BUDGET EXCEEDED at `spent >= cap` — i.e. only after an
overrun has already happened. The useful question is "can the next unit of work
be afforded", not "has the cap already been breached". Measured cost of a sol
arm, from four completed arms: $34.68-$38.66 generation + ~$3.40 grading.
At $42.57 remaining, exactly one more arm fits, with $4.49 to spare.

Recorded rather than silently patched: changing a stop threshold mid-run while a
loop is asking you to continue is the kind of edit that needs an operator's
sign-off, not an agent's judgement.

### 16d. Generation variance — never measured, and it should have been first

**Every one of the 28 arms is a single generation run.** Judge noise was
measured carefully and early (0.043/topic, 3 gradings averaged, floor ~0.018).
Generation noise was never measured at all.

That is a hole under the whole study. If re-running an identical configuration
moves the mean by more than ~0.02, then most of the 25 nulls were reported
against a baseline noisier than the effects being tested, and several arms —
`finish-the-claim` (+0.024 luna), `coverage-audit` (+0.017), `known-candidates`
(+0.011) — sit inside that band and cannot be distinguished from a re-roll of
the control.

Arm 29 is `sol-dev30-default-rep2`: the best configuration re-run with **no
change whatsoever**, to measure that variance directly. It is the last $38 of
the budget and it is the measurement that should have been made on day one,
before any arm was screened.

Whatever it returns, the correct reading of this worklog depends on it:

- **spread < 0.02** — the nulls stand as reported, and the two structural wins
  (+0.025 locale, +0.070 generator) are comfortably outside it.
- **spread >= 0.02** — every delta in the tables above needs re-reading against
  a wider band, and the honest conclusion shrinks to "the generator swap is the
  only effect this study could resolve".

This is the same failure the worklog documents nine times over, committed at the
top level: **an effect that cannot be detected and an effect that is absent look
identical in a results table.** Judge noise was checked. Generation noise was
assumed.

---

## 17. Arm 29 incomplete, and the one lever that was never built

### 17a. The generation-variance replicate did not finish

`sol-dev30-default-rep2` — the best configuration re-run with no change, to
measure how much the *generator* varies between runs — completed **26 of 30
topics**. The remaining 4 died on a 401: the STS credential expired again, the
same ~3-4 hour lifetime documented in §11.

`rubric_eval` refused to score the partial run rather than reporting a mean over
26 topics as if it were 30. That is the §4 failure-stub guard working
automatically, on exactly the class of error it was written for.

**26 topics are generated and paid for; 4 remain (~$5 + ~$3.40 grading).**
Resume is artifact-driven, so one command picks up exactly the missing four:

```bash
MODEL=openai.gpt-5.6-sol CONCURRENCY=5 \
  bash tasks/task-comparison/scripts/run_topics_parallel.sh default sol-dev30-default-rep2
PYTHONPATH=src uv run --group aus-agent python \
  tasks/task-comparison/scripts/rubric_eval.py \
  --run-id sol-dev30-default-rep2 --variant sol-default-rep2 --repeats 3
```

Until it lands, **generation variance remains unmeasured** and §16d's caveat
stands over every number in this document.

### 17b. Neighbour pages — built, never run

The one lever from the agreed list that was never implemented, despite being
listed as "queued" in six separate messages. Now built, behind
`AUS_AGENT_NEIGHBOUR_PAGES`.

`search` fetches the adjacent pages of its top-3 results itself and attaches
them, instead of asking the model to request them:

- `shard_x_p3` -> fetches `_p2` and `_p4`; page 1 has no predecessor
- bounded at top-3 results, so at most 6 extra chunks per search
- each neighbour truncated to the same per-result budget
- a missing page costs one cheap request and is dropped
- tagged `kind: "neighbour_page"` with `adjacent_to`, so the model can tell
  harness-volunteered context from evidence that matched its own query

Rationale, and it is the operator's: `get_documents` was called **19 times
against 1,862 searches (1%)** after two attempts to encourage it — a rewritten
tool description spelling out the mechanism, then an explicit prompt rule
routing a needs-depth lead to it. Asking a third time is not a plan; remove the
decision instead.

This is the only untested lever that changes **what evidence reaches the
agent**, rather than how it processes what it already has. Every "process it
better" lever in this study came back null, which is an argument for running it
first when budget returns.

### 17c. Final position

| | |
|---|---|
| best | `sol-default` — **0.6508** (sol judge), 0.6195 (terra) |
| goal | 0.80 — 2 of 5 conditions met |
| spend | **$488.30 of $500** |
| arms | 29 run: 2 worked, 25 null, 1 unavailable, 1 incomplete |
| recommended | plain `default` prompt, `gpt-5.6-sol`, UTC clock |

Outstanding, in priority order:

1. **Finish the replicate** (~$8). It determines how to read every number here.
   Three arms sit between +0.011 and +0.024 and cannot currently be told apart
   from re-rolling the control.
2. **Run the neighbour-pages arm** (~$38 on sol, ~$7 on luna).
3. Everything else is closed.

### 17d. A note on an unrelated in-progress change

`src/systems/aus_agent/finish_review.py` appeared at 04:32, outside this
session, and adds a `finish_review` key to `trace.config`. That breaks
`test_happy_run_trace_config_is_recorded` (1605 pass, 1 fail). It is untouched
here — the failing test belongs to that work, not to the neighbour-pages change,
which touches only `tools/search.py` and never references it.
