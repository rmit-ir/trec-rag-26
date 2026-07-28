# Retrieval-backend comparison — dense · keyword · lucene · ssr

**Headline (GROUNDED, rubric-judge cut): keyword ≈ dense > ssr > lucene.** The
natural-language engines (keyword, dense) are the generalists that win aggregate
multi-facet research retrieval; the Boolean engines (ssr, lucene) are niche
precision instruments. This supersedes the earlier "free-choice / dense-unknown"
framing — that test flagged a routed follow-up as unanswered; it is now answered.

The study has three cuts. **Cut 1** (ground truth) is a rubric-grounded
LLM-as-judge run over 30 official research-rubric dev topics — the cross-engine
quality verdict. **Cuts 2 & 3** are behavioral (agent-commit) cuts that resolve
*which query intents* each engine wins; they are confounded cross-engine and are
only clean within-engine / within-intent, so they support Cut 1's verdict with
per-intent detail rather than re-deciding it.

**DECISION:** don't use Boolean as a primary/default engine — keyword+dense
dominate the ground-truth cut. DO keep Boolean as a **ROUTED tool** for the
intents where it demonstrably wins (Cut 2): **exact phrase/quote → ssr;
required co-occurrence & quantitative evidence → lucene**. Full write-up and
method in `worklogs/2026-07-24-engine-comparison-rubric-judge.md`.

---

## Cut 1 (GROUND TRUTH) — rubric-grounded LLM-judge, 30 topics × 4 backends

Artifact: `rubric-judge/out/rubric_judge_matrix.md`. Pipeline: `rubric-judge/`
(`rubric_prep.py` → `gen_subqueries.py` → `retrieve.py` → `judge.py` →
`score.py`, + `backfill_semantic.py`).

**Method.** 30 dev topics with official labels (domain / breadth / nesting /
exploration). Rubric filter keeps only **positive-weight Explicit / Implicit /
Synthesis-of-Information** criteria (drops Communication/Instruction/Citation/
Misc and all penalty criteria). Retrieval unit = **multi sub-query per engine**:
luna writes 3–6 engine-agnostic sub-needs, each with a native-idiom query for
all four engines (query-writing guidance lifted verbatim from
`src/tools/search_tool.py` for fairness); an engine's pool is the union of its
per-sub-need k=10 lists. Each unique (topic, doc) is judged ONCE by luna
(`gpt-5.6-luna`) → `{umbrela 0-3, coverage:[{cid, grade 1|2}]}`. Coverage = Σ
weight of info criteria covered by ≥1 of the engine's surfaced docs / Σ all
(lenient grade≥1, strict grade≥2); mUMBRELA = mean holistic over unique judged
docs; nDCG@10 per sub-need.

**Corrected 4-way aggregate:**

| engine | cov(lenient) | cov(strict) | mUMBRELA | nDCG@10 |
|---|--:|--:|--:|--:|
| **keyword** | **0.913** | **0.545** | **1.805** | **0.964** |
| **semantic** (dense) | 0.902 | 0.464 | 1.799 | 0.958 |
| ssr | 0.836 | 0.388 | 1.548 | 0.908 |
| lucene | 0.774 | 0.326 | 1.371 | 0.906 |

**keyword ≈ dense (tie) > ssr > lucene.** keyword is marginally ahead of dense on
every column; the two NL engines are effectively tied, separating clearly only
on **cov(strict) 0.545 vs 0.464** (keyword's docs are more often *fully*
relevant). Both NL engines beat both Boolean engines on every metric.

**Where Boolean is weakest:**
- **Synthesis-of-Information axis** — lucene 0.644, ssr 0.755 vs semantic 0.841 /
  keyword 0.823 (the gap widens Explicit → Implicit → Synthesis). Required-term
  Boolean is least suited to connecting evidence across a doc.
- **High-exploration topics** (n=5) — lucene cov 0.672 / mUMBRELA 1.194, ssr
  0.755 / 1.418 vs keyword 0.883 / 1.782, dense 0.842 / 1.763.
- **High-breadth** (n=1) and **AI & ML** domain (lucene mUMBRELA 1.101) are the
  other Boolean low points.

**Methods caveat — dense outage.** The dense server was 502-down during the first
full run. It was re-run **dense-only** via `backfill_semantic.py` (reuses the
existing sub-queries; re-fetches ONLY semantic; MERGES into pool / replaces
semantic provenance; leaves keyword/ssr/lucene byte-for-byte intact; refuses to
touch already-complete topics). Integrity check: all 30 topics now have semantic
docs, and keyword/ssr/lucene per-topic doc counts are **unchanged** from before
the outage. So the aggregate above rests on a clean semantic arm with the other
three arms verified untouched.

---

## Cut 2 (BEHAVIORAL) — backend×intent commit-ratio taxonomy

Artifact: `commit_ratio_by_type.md` (+ `query_type_taxonomy.md`,
`query_classifications.jsonl`). Four single-backend agent arms (10 topics each,
450 queries). luna induced a **14-type engine-agnostic intent taxonomy** and
classified every query with its full trajectory in context; metric =
**first-surfacer commit ratio** (Σ fs_committed / Σ returned per cell).

**Col-pooled headline:** keyword 0.196 > dense 0.169 > lucene 0.117 > ssr 0.102 —
keyword strongest overall, consistent with Cut 1.

**Boolean wins these (non-thin) intents — the routing evidence:**

| intent | best backend | pooled | n / R | runner-up |
|---|---|--:|---|---|
| `exact-phrase-or-quote` | **ssr** | 0.167 | 3 / 30 | (only backend used) |
| `quantitative-evidence-seeking` | **lucene** | 0.141 | 10 / 78 | keyword 0.096 |
| `relational-cooccurrence` | **lucene** | 0.207 | 6 / 58 | keyword 0.188 |

(keyword wins most other intents: broad-exploratory, facet-drilldown,
named-entity-lookup, procedural, normative; dense wins comparative.)

**Confound:** the col-pooled ranking is biased by **denominator inflation** —
Boolean arms run more/wider probes (ssr 136 / lucene 142 vs keyword 75 searches),
returning ~2× more docs per commit, mechanically depressing their ratio.
Comparing WITHIN an intent controls for intent mix but not per-cell denominator.
So this cut is clean within-engine / within-intent only — a per-intent routing
signal, not a cross-engine quality verdict (that's Cut 1).

---

## Cut 3 (BEHAVIORAL) — within-SSR selection-ratio by query shape

Artifact: `selection_ratio_by_type.md` (`selection_ratio.py`). Run
`cmp-ssr-fork-v2`, 136 queries, novelty-corrected first-surfacer ratio, ranked
**within SSR's own trajectories**: phrase-bearing **0.116** > multi-AND 0.107 >
anchor+OR 0.097 > other 0.081; entity-bearing 0.112, phrase 0.111 > OR-anchored
0.097. Inside SSR, the most productive shapes are exactly the phrase / entity /
co-occurrence shapes — the mechanism behind Cut 2's per-intent wins. Strictly
within-engine; the appendix cross-backend baseline is confounded by the same
denominator inflation.

---

## Reconciliation

All three cuts agree. **Cut 1** aggregates over broad multi-facet topics (rewards
recall) → NL generalists win, Boolean weakest on synthesis/exploration/breadth.
**Cuts 2 & 3** resolve behavior by intent/shape → Boolean's precision wins DO
appear for exact-phrase (ssr) and co-occurrence/quantitative (lucene). Not in
tension: as a generalist Boolean loses; for specific precision intents it wins.
The rubric aggregate never isolates those intents, so it can't see the wins —
which is exactly why the routing decision rests on Cut 2, and the quality verdict
on Cut 1.

**DECISION.** Don't use Boolean as a primary/default engine (keyword+dense
dominate Cut 1, and — see the free-choice test below — the agent barely reaches
for it unprompted). DO route it: **exact phrase/quote → ssr; required
co-occurrence & quantitative evidence → lucene.** This is the routed follow-up
the free-choice test flagged — now grounded (which intents, from Cut 2; not a
viable default, from Cut 1) rather than guessed. Implementing a directive router
mapping those intents to ssr/lucene is the concrete next step.

**Caveats (whole study):** (1) Cut 1 is luna-judge, not human qrels. (2)
Multi-sub-query fairness rests on luna's per-engine translations (mitigated by
the verbatim production guidance). (3) Behavioral cuts are agent-commit, not
qrels, and confounded cross-engine by denominator inflation — clean only
within-engine/within-intent. (4) Small N in the behavioral cuts; the routing
decision leans only on the non-thin Boolean-winning cells.

---

## Appendix A — forced single-backend capability sweep (10 topics)

*`aus_agent` deep-research loop (`gpt-5.6-luna`, 500k-token budget). Each dev
topic run four times, each restricted to ONE backend via `--search-backends`,
over full ClimbMix. Backends: **dense** (Jina-v5 DiskANN), **keyword** (hosted
BM25 OR), **lucene** (full Lucene query-parser over the same BM25 index),
**ssr** (Cottontail fork — 26 stemmed SimpleWarren burrows +
`MultiShardSearchEngine`, server-side case-fold, paragraph-aware evidence). This
is the capability test that predated Cut 1; kept for the per-topic detail and
the SSR-fork before/after.*

### Bottom line — what each backend is best at

**Dense (semantic) — the best default for broad "help me understand / brief me"
synthesis.** Natural-language queries map one-to-one onto the request's own facets
and essentially never miss (**0 zero-result searches across all 10 topics**),
producing the most densely-cited reports in the fewest searches. Best fit on the 5
open-ended narrative topics.

**Keyword / Lucene (BM25) — best for entity-rich, fact-heavy topics** (2020-election
specifics, COVID statistics, investment authorities). Required-term BM25 (`+term`)
**degrades gracefully** — it ranks partial matches instead of hard-zeroing — and its
**full-document passages** surface the richest concrete anchors (dollar figures,
dates, named episodes). Keyword is the most search-efficient; Lucene retrieves and
commits the most. Between them they win the 5 fact-heavy topics.

**SSR (GCL Boolean) — the precision instrument, now competitive.** With porter
stemming, server-side query case-fold, `(+ …)`-inside-`(^ …)` querying (require one
facet, OR the rest), and paragraph-aware evidence, SSR's two former deal-breakers —
over-constraint zeros and thin snippets — are gone: **7 zero-searches across 10
topics (was 36)** and **~3.8k-char paragraph-bounded evidence per hit (was ~1.3k)**.
It doesn't out-synthesize dense on open-ended topics, but it is now a viable backend
and the right tool for **required co-occurrence, exact phrases, and truthful-zero
existence checks** (surname collisions, "do these two rare entities co-occur?",
verbatim fact-checks).

**Winner tally: dense 5 · keyword 3 · lucene 2.** (Dense/keyword/lucene verdicts are
from the graded head-to-head sweep; SSR is the re-run fork arm. SSR is now
competitive on every topic — no more self-inflicted zeros — but wasn't re-graded as
an outright winner, since dense/keyword/lucene still lead their own categories.)

---

## Appendix B — free-choice test (does the agent adopt Boolean unprompted?)

The forced sweep above **forces** each backend in isolation. The real product question
is different: when the agent has natural-language backends and can *choose* per query,
does adding a Boolean option help? We ran the same dense+sparse base and let the agent
choose freely, adding one Boolean backend at a time (10 topics each):

| arm | total searches | engine mix (searches per engine) | refs | committed |
|---|--:|---|--:|--:|
| base (dense+sparse) | 94 | semantic 86 · keyword 8 | 137 | 665 |
| + lucene-Boolean | 94 | semantic 77 · **lucene 9** · keyword 8 | 143 | 727 |
| + ssr-Boolean | 122 | semantic 112 · keyword 9 · **ssr 1** | 160 | 819 |

**Finding 1 — the agent almost never picks a Boolean tool when NL backends are present.**
SSR was used in **1 of 122 searches (0.8%)** — zero on 9 of 10 topics. lucene-Boolean in
**9 of 94 (9.6%)** — zero on 7 of 10 topics, the few uses clustering on entity/phrase-heavy
topics (de-minimis, COVID). Dense dominates at ~85–90% of searches in every arm.

**Finding 2 — no measurable marginal gain over the baseline.** The refs/committed
differences between arms are explained by run-to-run variance in how many *semantic*
searches the agent chose (the +ssr arm simply ran 122 vs 94 searches), **not** by Boolean
contributions — on the topics where Boolean was actually used, grounding did not
systematically improve over base.

**Why:** Boolean's genuine strengths — precision, required co-occurrence, exact phrases,
truthful-zero existence checks — are real and show up when a Boolean backend is used in
**isolation** (the forced single-backend runs, where SSR/lucene are competitive on
fact-heavy topics). But as a **passive add-on** next to dense, gpt-5.6-luna won't route
to it on its own.

> **Fairness caveat — this measures spontaneous adoption, not Boolean's ceiling.** The
> agent gets *no* engine-selection guidance in its system prompt (it is engine-agnostic),
> and the tool description is **descriptive** (what each engine is good at) rather than
> **directive** (a rule that routes specific query types to Boolean). The default engine
> is `semantic`, and the model has a strong natural-language prior. So this free-choice
> result is a fair test of *"will the agent adopt Boolean unprompted?"* (no) — but NOT of
> *"does Boolean add value when the agent is guided to use it?"* A fair test of the latter
> needs a **routed re-run**: an explicit directive ("use a Boolean engine to verify a
> fact, pin an exact entity/quote, or check co-occurrence") + the two trios re-run against
> the baseline. That routing work was the **planned follow-up this study set out to
> resolve** — Cut 1 (rubric-judge) and Cut 2 (intent taxonomy) above now supply the
> two missing pieces (Boolean is not a viable default; and *which* intents to route).
> The standalone single-backend runs here are the capability test.

**Finding (superseded framing — now folded into the grounded decision at the top of
this doc).** As a *passive free-choice add-on* alongside dense+sparse, a Boolean tool is
not worth the serving cost: the agent ignores it (SSR ~0%, lucene ~10%) for no measurable
marginal gain, and if forced to keep exactly one in free-choice mode, **lucene** is the
only one the agent ever picks (**SSR is effectively never selected**). But that is a
statement about *spontaneous adoption*, not Boolean's ceiling. The grounded decision at
the top of this doc is the current verdict: Boolean is not a default, but IS worth keeping
as a **routed** tool for exact-phrase/quote (ssr) and co-occurrence / quantitative-evidence
(lucene) intents.

## Winner by topic

| topic | best | why the winner won | SSR (fork) now |
|---|---|---|---|
| rag2026-0 — nursing DEI 3-yr plan | **dense** | one-pass facet coverage, every sentence cited | 14 srch / **0 zero** (was 1); `(+)`-in-`(^)` throughout |
| rag2026-1 — biological effects of grief | **dense** | committed the most, well-grounded | 9 / **0**; grief-biology co-occurs densely, all four stayed clean |
| rag2026-2 — health-care-as-a-right | **lucene** | richest specific evidence (dense close) | 12 / **2** (was 5); residual zeros = hyphen/period bare terms |
| rag2026-3 — lifelong $10k investment plan | **keyword** | 100% sentence-level grounding | 20 / **0** (was 7) — biggest turnaround: case-fold fixes every Australia/super/ETF/tax probe |
| rag2026-4 — nostalgia & the social clock | **dense** | matched the psychology corpus, most-cited | 9 / **0** (was 1) |
| rag2026-5 — de-minimis / Section 321 | **dense** | full coverage, largest doc pool | 13 / **4** (was 11); a few over-nested openers still zero, then recovers |
| rag2026-6 — world change since COVID | **keyword** | richest quantified, example-laden grounding | 18 / **0** (was 1); rich paragraph evidence |
| rag2026-7 — AI political-signals trading | **keyword** | surfaced every anchor, zero uncited | 14 / **0**; now grounds richly (~4.5k-char evidence — the topic that exposed thin snippets) |
| rag2026-8 — 2020 fraud claims & reforms | **lucene** | most verifiable specifics | 16 / **1** (was 4) |
| rag2026-9 — nuclear fuel-supply risk | **dense** | most quantified/grounded, no wasted queries | 11 / **0** (was 6) — HALEU/Kazatomprom/Centrus all populate now |

## SSR fork arm — per-topic detail (current)

`#search / #zero / #uniqDoc` from the trajectory; `ev` = mean evidence chars/hit;
`maxAND` = largest required-term count in any `(^ …)`; `commit` = docs retained.

| topic | search | zero | uniqDoc | ev_chars | maxAND | commit |
|---|--:|--:|--:|--:|--:|--:|
| rag2026-0 | 14 | 0 | 97 | 4056 | 0 | 13 |
| rag2026-1 | 9 | 0 | 79 | 3077 | 4 | 10 |
| rag2026-2 | 12 | 2 | 80 | 3688 | 5 | 10 |
| rag2026-3 | 20 | 0 | 192 | 3398 | 4 | 17 |
| rag2026-4 | 9 | 0 | 87 | 3256 | 4 | 10 |
| rag2026-5 | 13 | 4 | 74 | 5702 | 5 | 13 |
| rag2026-6 | 18 | 0 | 177 | 3857 | 6 | 20 |
| rag2026-7 | 14 | 0 | 102 | 4457 | 7 | 18 |
| rag2026-8 | 16 | 1 | 143 | 2985 | 3 | 17 |
| rag2026-9 | 11 | 0 | 94 | 3901 | 3 | 13 |
| **total/mean** | **136** | **7** | **1125** | **3838** | ~ | **141** |

The healthy pattern to note in the trajectories (appendix): the agent now writes
`(^ term (+ a b))` — **require the anchor, OR the rest** — instead of stacking 5–7
required terms into one AND. That, plus case-fold, is why zeros collapsed. The 7
residual zeros are real: hyphenated/punctuated bare terms that are exact-and-unstemmed
(`employer-based`, `U.S.`), or a couple of over-nested openers on rag2026-5 — each
recovered on the next query.

## What the SSR update changed (vs the retired Hazel SSR)

The original SSR arm ran on the old Hazel `ssr-server` and was the worst backend on
this task for two reasons. Both are now fixed in the fork (branch
`claude/query-casefold-and-paragraph-hydration`, merged to `main`):

| metric (sum over 10 topics) | retired Hazel SSR | **fork SSR (current)** |
|---|---|---|
| zero-result searches | **36 (27%)** | **7 (5.1%)** |
| mean evidence chars/hit | 1272 | **3838 (3.0×)** |
| unique docs retrieved | 840 | 1125 |

1. **Over-constraint zeros → fixed.** Two changes: **server-side query case-fold**
   (the fork's bare-term GCL path was case-*sensitive* over a case-*folded* index, so
   `Russia`/`HALEU`/`Australia`/`Kazatomprom` matched 0 docs) and a **tool-instruction
   fix** steering the agent to `(+ …)`-inside-`(^ …)` and "on zero, DROP a term, never
   add one." Worst old cases: investment **7→0**, nuclear-fuel **6→0**, de-minimis
   **11→4**, election **4→1**.
2. **Thin evidence → fixed (reversed, actually).** SSR now returns **paragraph-aware
   bands** — grown from the cover's token span outward to whole-paragraph boundaries,
   sized to a 200/500/700-token min/target/max band like the pipeline chunker. Evidence
   went 1272 → 3838 chars/hit, on clean paragraph boundaries — richer than the original
   Hazel SSR that starved citations on rag2026-7.

Caveat for query authoring: **quoted phrases are exact and UNSTEMMED** (`"supply
chains"` ≠ "supply chain"), and hyphen/period tokens are exact — prefer bare stemmed
terms and `(+ …)` alternation.

---

# Appendix — numeric matrix (all 4 backends, SSR = fork)

`#search / #zero / #uniqDoc / #commit`. Dense/keyword/lucene are the graded sweep;
SSR is the current fork arm.

| topic | dense | keyword | lucene | ssr (fork) |
|---|---|---|---|---|
| rag2026-0 | 8/0/57/15 | 8/0/56/16 | 17/0/122/13 | 14/0/97/13 |
| rag2026-1 | 8/0/61/14 | 6/0/48/10 | 8/0/63/12 | 9/0/79/10 |
| rag2026-2 | 10/0/74/10 | 7/0/56/13 | 14/0/137/19 | 12/2/80/10 |
| rag2026-3 | 9/0/71/12 | 10/0/90/12 | 11/0/103/13 | 20/0/192/17 |
| rag2026-4 | 8/0/48/12 | 7/0/38/8 | 9/0/69/9 | 9/0/87/10 |
| rag2026-5 | 11/0/88/12 | 6/0/37/10 | 21/0/168/10 | 13/4/74/13 |
| rag2026-6 | 12/0/93/17 | 9/0/62/12 | 16/0/159/27 | 18/0/177/20 |
| rag2026-7 | 7/0/56/12 | 6/0/46/14 | 14/0/130/16 | 14/0/102/18 |
| rag2026-8 | 12/0/89/13 | 8/0/50/11 | 14/0/123/18 | 16/1/143/17 |
| rag2026-9 | 12/0/97/16 | 8/0/68/10 | 18/0/127/14 | 11/0/94/13 |

# Appendix — SSR (fork) full query trajectories

Number in parens = hits returned. Note the `(^ anchor (+ a b))` shape — require one
term, OR the alternatives — and the near-absence of the old 5–7-term required ANDs.

## rag2026-0 — 14 searches, 0 zero
   - (8) (^ nursing (+ recruitment retention))
   - (8) (^ nursing (+ racism discrimination))
   - (8) (^ nursing (+ diversity inclusion))
   - (8) (^ nursing (+ promotion leadership))
   - (8) (^ nursing (+ curriculum education))
   - (8) (^ racism (+ reporting complaint))
   - (8) (^ nursing (+ hiring promotion))
   - (8) (^ nursing (+ accountability racism))
   - (8) (^ nursing (+ outcomes turnover))
   - (8) (^ nurses (+ microaggression))
   - (8) (^ nurses (+ advancement barriers))
   - (8) (^ nursing (+ leadership diversity))
   - (8) (^ nursing (+ mentoring development))
   - (8) (^ nursing (+ climate microaggression))

## rag2026-1 — 9 searches, 0 zero
   - (10) (^ grief (+ heart chest tightness))
   - (10) (^ grief (+ immune inflammation))
   - (10) (^ grief (+ stress hormone sleep appetite))
   - (10) (^ grief (+ warning signs time periods))
   - (10) (^ takotsubo (+ chest pain shortness breath))
   - (10) (^ grief (+ blood pressure medication))
   - (10) (^ grief (+ complicated grief diagnosis))
   - (10) (^ cortisol DHEAS neutrophil grief)
   - (10) (^ grief (+ doctor checkup))

## rag2026-2 — 12 searches, 2 zero
   - (8) (^ "health care" right privilege)
   - (8) (^ universal coverage affordability)
   - (8) (^ medical debt)
   - (8) (^ Medicaid expansion employer insurance)
   - (8) (^ "single payer" tax)
   - (8) (^ "emergency room" safety net)
   - (8) (^ patient choice health care)
   - (0) (^ employer-based insurance)
   - (8) (^ universal coverage tax)
   - (0) (^ health care right U.S. policy)
   - (8) (^ Medicaid expansion coverage access)
   - (8) (^ medical debt affordability insurance)

## rag2026-3 — 20 searches, 0 zero
   - (10) (^ (+ invest investment) future)
   - (10) (^ "ten thousand dollars" invest)
   - (10) (^ 18 invest)
   - (10) (^ (+ lifetime "long term") investment)
   - (10) (^ (+ academic authoritative) invest)
   - (10) (^ Australia superannuation invest)
   - (10) (^ Australia diversification index fund)
   - (10) (^ Australia investment fees)
   - (10) (^ compounding investment)
   - (10) (^ diversification passive index)
   - (10) (^ investment risk return)
   - (10) (^ investment tax Australia)
   - (10) (^ investment scam)
   - (10) (^ (+ emergency savings) investment)
   - (10) (^ debt investment)
   - (10) (^ active passive return)
   - (10) (^ index fund retirement)
   - (10) (^ superannuation retirement)
   - (10) (^ ETF diversification)
   - (10) (^ financial advice Australia licensed)

## rag2026-4 — 9 searches, 0 zero
   - (10) (^ nostalgia social comparison)
   - (10) (^ nostalgia identity)
   - (10) (^ "social clock" adulthood)
   - (10) (^ nostalgia loneliness)
   - (10) (^ career dating move)
   - (10) (^ nostalgia comparison)
   - (10) (^ "past self" "current self")
   - (10) (^ nostalgia reflective evaluative)
   - (10) (^ "social clock" distress)

## rag2026-5 — 13 searches, 4 zero
   - (0) (^ ("de minimis" "section 321") tariff)
   - (0) (^ ("de minimis" customs) (China + import + shipment))
   - (0) (^ ("forced labor" customs) (China + import))
   - (0) (^ (inventory warehouse) (+ Mexico Canada United States) supply chain)
   - (10) (^ "de minimis" tariff)
   - (10) (^ "section 321" customs)
   - (10) (^ "forced labor" customs)
   - (10) (^ inventory warehouse mexico)
   - (10) (^ "de minimis" China tariff enforcement)
   - (10) (^ air freight China delivery ecommerce)
   - (2) (^ UFLPA "Section 321")
   - (10) (^ warehouse Canada ecommerce inventory)
   - (8) (^ "Section 321" China customs enforcement)

## rag2026-6 — 18 searches, 0 zero
   - (10) (^ pandemic "before covid" "after covid")
   - (10) (^ covid "early 2020" "global response")
   - (10) (^ covid vaccine rollout)
   - (10) (^ covid "public health")
   - (10) (^ covid "work culture")
   - (10) (^ covid education)
   - (10) (^ covid travel)
   - (10) (^ covid economy)
   - (10) (^ covid "mental health")
   - (10) (^ covid technology adoption)
   - (10) (^ covid 2025 "post-pandemic")
   - (10) (^ covid "public health" vaccine "long covid")
   - (10) (^ covid 2025 remote work hybrid)
   - (10) (^ covid social isolation interaction)
   - (10) (^ covid inflation supply chain)
   - (10) (^ covid travel recovery 2023)
   - (10) (^ covid online learning digital divide)
   - (10) (^ covid mental health 2025)

## rag2026-7 — 14 searches, 0 zero
   - (6) (^ congressional trade lobbying disclosure)
   - (6) (^ proposed bill geopolitical headline social media market)
   - (6) (^ algorithm trade legality regulation)
   - (6) (^ political signal data quality model risk)
   - (8) (^ congressional trade insider trading)
   - (8) (^ lobbying disclosure law)
   - (8) (^ algorithm trading market impact)
   - (8) (^ model risk algorithm social media)
   - (8) (^ public pension fiduciary artificial intelligence investment)
   - (8) (^ political information misinformation market)
   - (8) (^ financial regulation artificial intelligence model risk)
   - (8) (^ social media privacy data scraping)
   - (8) (^ pension fiduciary transparency black box)
   - (8) (^ market manipulation social media trading)

## rag2026-8 — 16 searches, 1 zero
   - (10) (^ (+ "dead voter" "dead voters") election 2020)
   - (10) (^ (+ dominion machine "dominion voting") election)
   - (10) (^ (+ "poll watcher" "poll watchers") blocked)
   - (10) (^ (+ "mail ballot" "drop box") election)
   - (10) (^ "Arizona audit" election)
   - (0) (^ (+ "election integrity law" "voting harder" voter)
   - (10) (^ dominion "voting machine")
   - (10) (^ dominion lawsuit election)
   - (10) (^ (+ "election law" "voting law") (+ restrict harder burden) voter)
   - (10) (^ (+ "voter suppression" "voting access") law)
   - (10) (^ (+ audit recount) "Arizona" 2020)
   - (10) (^ (+ safeguard transparency verification) election trust)
   - (10) (^ (+ court lawsuit) "2020 election" fraud evidence)
   - (10) (^ "risk-limiting audit" election)
   - (10) (^ (+ paper ballot audit) election security)
   - (10) (^ (+ drop box mail ballot) fraud evidence)

## rag2026-9 — 11 searches, 0 zero
   - (10) (^ uranium (+ mining supply price))
   - (10) (^ uranium (+ conversion enrichment fabrication))
   - (10) (^ uranium russia)
   - (10) (^ HALEU (+ advanced reactor SMR))
   - (10) (^ uranium "long-term contract")
   - (10) (^ Kazatomprom (+ production disruption))
   - (10) (^ uranium conversion (+ capacity Russia))
   - (10) (^ uranium enrichment (+ capacity Russia Europe))
   - (10) (^ uranium inventory utility (+ contracting))
   - (10) (^ Centrus HALEU)
   - (10) (^ uranium fabrication bottleneck)

---

## Cut 4 — committed-doc diversity, best-explanation, credibility & answer-level RAGDOLL

30 dev topics × 4 **isolated per-engine full agent runs** (`dev-*-30`, `gpt-5.6-luna`);
1,396 committed docs judged + 120 generated answers judged. Full method, inputs and
result matrix: `worklogs/2026-07-27-committed-diversity-and-answer-ragdoll.md`.
Artifacts: `data/task-comparison/diversity/`.

**NEW HEADLINE — retrieval quality does NOT fully propagate to answers.** At the
retrieval/committed-doc level the Cut-1 order holds (keyword ≈ dense > ssr > lucene),
but at the **answer** level **dense ≈ keyword ≈ ssr (overall 1.90–1.93) > lucene
(1.67)** — the LLM synthesizes competent answers from ssr's noisier evidence; only
lucene is weak enough to drag the answer down.

| engine | committed best-expl win-rate | mean UMBRELA | low-rel rate | Vendi/n (diversity) | unique-contrib | **answer overall** |
|---|--:|--:|--:|--:|--:|--:|
| keyword | **0.236** | **1.96** | **0.042** | 0.563 | 0.803 | 1.90 |
| dense   | 0.228 | 1.88 | 0.110 | 0.519 | 0.866 | **1.93** |
| lucene  | 0.209 | 1.93 | 0.066 | 0.507 | 0.860 | 1.67 |
| ssr     | 0.188 | 1.78 | **0.192** | **0.597** | **0.872** | 1.90 |

**Complementarity:** committed-docid Jaccard ≤ 0.044 across every engine pair; union
Vendi 13.3 ≈ 2× single-engine → engines are near-disjoint and additive.

**Findings:** (1) **diversity ≠ value** — ssr is most internally diverse yet commits
the weakest evidence (its "unique" docs are often unique-but-off-target, low-rel 0.192);
(2) **LLM synthesis compensates for weak retrieval up to a point** — ssr ties keyword/dense
on answers, lucene does not; (3) keyword leads retrieval quality on the fewest docs;
dense trades relevance for recall (most near-dups, 0.022).

**DECISION refinement:** retrieval verdict unchanged, but on *answers* **ssr is not a
laggard — it ties keyword/dense; lucene is the sole laggard.** Prefer **ssr over lucene**
as the routed Boolean arm.
