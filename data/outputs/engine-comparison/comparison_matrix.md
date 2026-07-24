# Retrieval-backend comparison — 10 topics × 4 backends

*`aus_agent` deep-research loop (OpenAI `gpt-5.6-luna`, 500k-token budget). Each dev
topic is run four times, each restricted to ONE retrieval backend via
`--search-backends`, over the full ClimbMix corpus. Backends: **dense** (Jina-v5
DiskANN), **keyword** (hosted BM25 bag-of-words OR), **lucene** (full Lucene
query-parser over the same BM25 index), **ssr** (Cottontail fork — 26 stemmed
SimpleWarren burrows + `MultiShardSearchEngine` fan-out, with server-side query
case-fold and paragraph-aware evidence bands). This is the current SSR stack; see
"What the SSR update changed" for the before/after vs the retired Hazel SSR.*

---

## Bottom line — what each backend is best at

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

## Is a Boolean backend worth keeping? (free-choice test)

The comparison above **forces** each backend in isolation. The real product question
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
> the baseline. That routing work is a **planned follow-up** — the standalone
> single-backend runs above are the capability test; adding "when to use which" guidance
> comes after. Until then, treat the decision below as applying to Boolean *as a passive
> add-on*, not to Boolean *with proper routing*.

**Decision:**
- **As a free-choice tool alongside dense+sparse: not worth the serving cost.** The agent
  ignores it (SSR ~0%, lucene ~10%) for no measurable gain over dense+sparse alone.
- **Boolean pays off only when forced or routed:** single-backend precision runs,
  verification / fact-check sub-queries, disambiguation ("do these two rare entities
  co-occur?"), verbatim checks. To capture that value you must (a) explicitly route
  specific query types to a Boolean backend, or (b) strengthen the agent's planning /
  tool guidance so it *reaches* for Boolean on precision sub-tasks — merely offering the
  tool is not enough.
- If you keep exactly one Boolean option in free-choice mode, **lucene-Boolean** is the
  one the agent will at least occasionally use; **SSR is effectively never selected**.

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
