# SSR selection-ratio by query type (first-surfacer, novelty-corrected)

**Run:** `cmp-ssr-fork-v2` — the current SSR fork arm. Chosen because its per-topic search counts (14/9/12/20/9/13/18/14/16/11 = 136) match the published fork matrix exactly; `cmp-ssr` is the old Hazel arm and `cmp-ssr-fork` an earlier fork (163 searches).

**Metric:** for each SSR search query Q, `sel_ratio = fs_committed / returned`, where `fs_committed` counts only docids that Q was the FIRST query to surface AND that ended up in the topic's final committed reference set. `raw_committed` is the un-corrected count (any returned docid in the committed set) and is kept only to show the novelty gap. `returned == 0` (zero-result) => `sel_ratio = 0`.

**Caveats — read before using any number here:**

1. **Within-engine only.** These ratios describe productivity *inside the SSR trajectories* and are NOT comparable to the dense/keyword/lucene arms — each engine walked a different trajectory over a different candidate pool, so the committed sets and the queries differ.

2. **Agent-relevance, not ground truth.** "Committed" means the agent kept the doc as evidence, not that a qrel judged it relevant. The same model wrote the query and judged the commit, so there is a self-consistency bias inflating any query shape the model favours.

3. **Small N.** 10 topics, 136 queries. Per-bucket cells are tiny; treat this as a first-pass hypothesis generator, not a verdict.

---

**Parse sanity:** 136 searches, 7 zero-result (expected 136 searches / 7 zeros) — MATCH.

## Per-query detail (grouped by topic)

| topic | query | bucket | tags | ret | fs_c | raw_c | sel |
|---|---|---|---|--:|--:|--:|--:|
| rag2026-0 | `(^ nursing (+ recruitment retention))` | anchor+OR | or | 8 | 2 | 2 | 0.250 |
| rag2026-0 | `(^ nursing (+ racism discrimination))` | anchor+OR | or | 8 | 1 | 1 | 0.125 |
| rag2026-0 | `(^ nursing (+ diversity inclusion))` | anchor+OR | or | 8 | 0 | 0 | 0.000 |
| rag2026-0 | `(^ nursing (+ promotion leadership))` | anchor+OR | or | 8 | 1 | 1 | 0.125 |
| rag2026-0 | `(^ nursing (+ curriculum education))` | anchor+OR | or | 8 | 1 | 1 | 0.125 |
| rag2026-0 | `(^ racism (+ reporting complaint))` | anchor+OR | or | 8 | 2 | 2 | 0.250 |
| rag2026-0 | `(^ nursing (+ hiring promotion))` | anchor+OR | or | 8 | 0 | 0 | 0.000 |
| rag2026-0 | `(^ nursing (+ accountability racism))` | anchor+OR | or | 8 | 0 | 1 | 0.000 |
| rag2026-0 | `(^ nursing (+ outcomes turnover))` | anchor+OR | or | 8 | 0 | 1 | 0.000 |
| rag2026-0 | `(^ nurses (+ microaggression))` | anchor+OR | or | 8 | 2 | 2 | 0.250 |
| rag2026-0 | `(^ nurses (+ advancement barriers))` | anchor+OR | or | 8 | 0 | 0 | 0.000 |
| rag2026-0 | `(^ nursing (+ leadership diversity))` | anchor+OR | or | 8 | 0 | 1 | 0.000 |
| rag2026-0 | `(^ nursing (+ mentoring development))` | anchor+OR | or | 8 | 1 | 1 | 0.125 |
| rag2026-0 | `(^ nursing (+ climate microaggression))` | anchor+OR | or | 8 | 0 | 0 | 0.000 |
| rag2026-1 | `(^ grief (+ heart chest tightness))` | anchor+OR | or | 10 | 0 | 0 | 0.000 |
| rag2026-1 | `(^ grief (+ immune inflammation))` | anchor+OR | or | 10 | 3 | 3 | 0.300 |
| rag2026-1 | `(^ grief (+ stress hormone sleep appetite))` | anchor+OR | or | 10 | 2 | 2 | 0.200 |
| rag2026-1 | `(^ grief (+ warning signs time periods))` | anchor+OR | or | 10 | 1 | 1 | 0.100 |
| rag2026-1 | `(^ takotsubo (+ chest pain shortness breath))` | anchor+OR | or | 10 | 1 | 1 | 0.100 |
| rag2026-1 | `(^ grief (+ blood pressure medication))` | anchor+OR | or | 10 | 1 | 2 | 0.100 |
| rag2026-1 | `(^ grief (+ complicated grief diagnosis))` | anchor+OR | or | 10 | 0 | 0 | 0.000 |
| rag2026-1 | `(^ cortisol DHEAS neutrophil grief)` | multi-AND | entity | 10 | 1 | 2 | 0.100 |
| rag2026-1 | `(^ grief (+ doctor checkup))` | anchor+OR | or | 10 | 1 | 2 | 0.100 |
| rag2026-2 | `(^ "health care" right privilege)` | phrase-bearing | phrase | 8 | 0 | 0 | 0.000 |
| rag2026-2 | `(^ universal coverage affordability)` | multi-AND | — | 8 | 1 | 1 | 0.125 |
| rag2026-2 | `(^ medical debt)` | other | — | 8 | 1 | 1 | 0.125 |
| rag2026-2 | `(^ Medicaid expansion employer insurance)` | multi-AND | entity | 8 | 3 | 3 | 0.375 |
| rag2026-2 | `(^ "single payer" tax)` | phrase-bearing | phrase | 8 | 1 | 1 | 0.125 |
| rag2026-2 | `(^ "emergency room" safety net)` | phrase-bearing | phrase | 8 | 1 | 1 | 0.125 |
| rag2026-2 | `(^ patient choice health care)` | multi-AND | — | 8 | 0 | 0 | 0.000 |
| rag2026-2 | `(^ employer-based insurance)` (0) | other | — | 0 | 0 | 0 | 0.000 |
| rag2026-2 | `(^ universal coverage tax)` | multi-AND | — | 8 | 2 | 2 | 0.250 |
| rag2026-2 | `(^ health care right U.S. policy)` (0) | multi-AND | entity | 0 | 0 | 0 | 0.000 |
| rag2026-2 | `(^ Medicaid expansion coverage access)` | multi-AND | entity | 8 | 1 | 1 | 0.125 |
| rag2026-2 | `(^ medical debt affordability insurance)` | multi-AND | — | 8 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ (+ invest investment) future)` | anchor+OR | or | 10 | 2 | 2 | 0.200 |
| rag2026-3 | `(^ "ten thousand dollars" invest)` | phrase-bearing | phrase | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ 18 invest)` | other | — | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ (+ lifetime "long term") investment)` | anchor+OR | phrase,or | 10 | 1 | 1 | 0.100 |
| rag2026-3 | `(^ (+ academic authoritative) invest)` | anchor+OR | or | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ Australia superannuation invest)` | multi-AND | entity | 10 | 1 | 1 | 0.100 |
| rag2026-3 | `(^ Australia diversification index fund)` | multi-AND | entity | 10 | 1 | 1 | 0.100 |
| rag2026-3 | `(^ Australia investment fees)` | multi-AND | entity | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ compounding investment)` | other | — | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ diversification passive index)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-3 | `(^ investment risk return)` | multi-AND | — | 10 | 1 | 3 | 0.100 |
| rag2026-3 | `(^ investment tax Australia)` | multi-AND | entity | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ investment scam)` | other | — | 10 | 2 | 2 | 0.200 |
| rag2026-3 | `(^ (+ emergency savings) investment)` | anchor+OR | or | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ debt investment)` | other | — | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ active passive return)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-3 | `(^ index fund retirement)` | multi-AND | — | 10 | 0 | 0 | 0.000 |
| rag2026-3 | `(^ superannuation retirement)` | other | — | 10 | 1 | 1 | 0.100 |
| rag2026-3 | `(^ ETF diversification)` | other | entity | 10 | 1 | 1 | 0.100 |
| rag2026-3 | `(^ financial advice Australia licensed)` | multi-AND | entity | 10 | 2 | 2 | 0.200 |
| rag2026-4 | `(^ nostalgia social comparison)` | multi-AND | — | 10 | 2 | 2 | 0.200 |
| rag2026-4 | `(^ nostalgia identity)` | other | — | 10 | 1 | 1 | 0.100 |
| rag2026-4 | `(^ "social clock" adulthood)` | phrase-bearing | phrase | 10 | 3 | 3 | 0.300 |
| rag2026-4 | `(^ nostalgia loneliness)` | other | — | 10 | 2 | 2 | 0.200 |
| rag2026-4 | `(^ career dating move)` | multi-AND | — | 10 | 0 | 0 | 0.000 |
| rag2026-4 | `(^ nostalgia comparison)` | other | — | 10 | 0 | 0 | 0.000 |
| rag2026-4 | `(^ "past self" "current self")` | phrase-bearing | phrase | 10 | 0 | 1 | 0.000 |
| rag2026-4 | `(^ nostalgia reflective evaluative)` | multi-AND | — | 10 | 0 | 1 | 0.000 |
| rag2026-4 | `(^ "social clock" distress)` | phrase-bearing | phrase | 10 | 2 | 3 | 0.200 |
| rag2026-5 | `(^ ("de minimis" "section 321") tariff)` (0/FAIL) | phrase-bearing | phrase | 0 | 0 | 0 | 0.000 |
| rag2026-5 | `(^ ("de minimis" customs) (China + import + shipment))` (0/FAIL) | phrase-bearing | phrase,entity | 0 | 0 | 0 | 0.000 |
| rag2026-5 | `(^ ("forced labor" customs) (China + import))` (0/FAIL) | phrase-bearing | phrase,entity | 0 | 0 | 0 | 0.000 |
| rag2026-5 | `(^ (inventory warehouse) (+ Mexico Canada United States) supply chain)` (0/FAIL) | anchor+OR | or,entity | 0 | 0 | 0 | 0.000 |
| rag2026-5 | `(^ "de minimis" tariff)` | phrase-bearing | phrase | 10 | 1 | 1 | 0.100 |
| rag2026-5 | `(^ "section 321" customs)` | phrase-bearing | phrase | 10 | 2 | 2 | 0.200 |
| rag2026-5 | `(^ "forced labor" customs)` | phrase-bearing | phrase | 10 | 2 | 2 | 0.200 |
| rag2026-5 | `(^ inventory warehouse mexico)` | multi-AND | — | 10 | 2 | 2 | 0.200 |
| rag2026-5 | `(^ "de minimis" China tariff enforcement)` | phrase-bearing | phrase,entity | 10 | 1 | 1 | 0.100 |
| rag2026-5 | `(^ air freight China delivery ecommerce)` | multi-AND | entity | 10 | 2 | 2 | 0.200 |
| rag2026-5 | `(^ UFLPA "Section 321")` | phrase-bearing | phrase,entity | 2 | 1 | 1 | 0.500 |
| rag2026-5 | `(^ warehouse Canada ecommerce inventory)` | multi-AND | entity | 10 | 2 | 2 | 0.200 |
| rag2026-5 | `(^ "Section 321" China customs enforcement)` | phrase-bearing | phrase,entity | 8 | 0 | 1 | 0.000 |
| rag2026-6 | `(^ pandemic "before covid" "after covid")` | phrase-bearing | phrase | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid "early 2020" "global response")` | phrase-bearing | phrase | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid vaccine rollout)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid "public health")` | phrase-bearing | phrase | 10 | 0 | 0 | 0.000 |
| rag2026-6 | `(^ covid "work culture")` | phrase-bearing | phrase | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid education)` | other | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid travel)` | other | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid economy)` | other | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid "mental health")` | phrase-bearing | phrase | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid technology adoption)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid 2025 "post-pandemic")` | phrase-bearing | phrase | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid "public health" vaccine "long covid")` | phrase-bearing | phrase | 10 | 2 | 2 | 0.200 |
| rag2026-6 | `(^ covid 2025 remote work hybrid)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid social isolation interaction)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid inflation supply chain)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid travel recovery 2023)` | multi-AND | — | 10 | 2 | 2 | 0.200 |
| rag2026-6 | `(^ covid online learning digital divide)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-6 | `(^ covid mental health 2025)` | multi-AND | — | 10 | 0 | 0 | 0.000 |
| rag2026-7 | `(^ congressional trade lobbying disclosure)` | multi-AND | — | 6 | 1 | 1 | 0.167 |
| rag2026-7 | `(^ proposed bill geopolitical headline social media market)` | multi-AND | — | 6 | 1 | 1 | 0.167 |
| rag2026-7 | `(^ algorithm trade legality regulation)` | multi-AND | — | 6 | 0 | 0 | 0.000 |
| rag2026-7 | `(^ political signal data quality model risk)` | multi-AND | — | 6 | 0 | 0 | 0.000 |
| rag2026-7 | `(^ congressional trade insider trading)` | multi-AND | — | 8 | 1 | 1 | 0.125 |
| rag2026-7 | `(^ lobbying disclosure law)` | multi-AND | — | 8 | 1 | 1 | 0.125 |
| rag2026-7 | `(^ algorithm trading market impact)` | multi-AND | — | 8 | 2 | 2 | 0.250 |
| rag2026-7 | `(^ model risk algorithm social media)` | multi-AND | — | 8 | 2 | 2 | 0.250 |
| rag2026-7 | `(^ public pension fiduciary artificial intelligence investment)` | multi-AND | — | 8 | 1 | 1 | 0.125 |
| rag2026-7 | `(^ political information misinformation market)` | multi-AND | — | 8 | 1 | 1 | 0.125 |
| rag2026-7 | `(^ financial regulation artificial intelligence model risk)` | multi-AND | — | 8 | 1 | 1 | 0.125 |
| rag2026-7 | `(^ social media privacy data scraping)` | multi-AND | — | 8 | 1 | 1 | 0.125 |
| rag2026-7 | `(^ pension fiduciary transparency black box)` | multi-AND | — | 8 | 0 | 1 | 0.000 |
| rag2026-7 | `(^ market manipulation social media trading)` | multi-AND | — | 8 | 0 | 0 | 0.000 |
| rag2026-8 | `(^ (+ "dead voter" "dead voters") election 2020)` | anchor+OR | phrase,or | 10 | 2 | 2 | 0.200 |
| rag2026-8 | `(^ (+ dominion machine "dominion voting") election)` | anchor+OR | phrase,or | 10 | 0 | 0 | 0.000 |
| rag2026-8 | `(^ (+ "poll watcher" "poll watchers") blocked)` | anchor+OR | phrase,or | 10 | 1 | 1 | 0.100 |
| rag2026-8 | `(^ (+ "mail ballot" "drop box") election)` | anchor+OR | phrase,or | 10 | 1 | 1 | 0.100 |
| rag2026-8 | `(^ "Arizona audit" election)` | phrase-bearing | phrase,entity | 10 | 0 | 0 | 0.000 |
| rag2026-8 | `(^ (+ "election integrity law" "voting harder" voter)` (0/FAIL) | anchor+OR | phrase,or | 0 | 0 | 0 | 0.000 |
| rag2026-8 | `(^ dominion "voting machine")` | phrase-bearing | phrase | 10 | 1 | 1 | 0.100 |
| rag2026-8 | `(^ dominion lawsuit election)` | multi-AND | — | 10 | 1 | 1 | 0.100 |
| rag2026-8 | `(^ (+ "election law" "voting law") (+ restrict harder burden) voter)` | anchor+OR | phrase,or | 10 | 3 | 3 | 0.300 |
| rag2026-8 | `(^ (+ "voter suppression" "voting access") law)` | anchor+OR | phrase,or | 10 | 0 | 0 | 0.000 |
| rag2026-8 | `(^ (+ audit recount) "Arizona" 2020)` | anchor+OR | phrase,or,entity | 10 | 1 | 1 | 0.100 |
| rag2026-8 | `(^ (+ safeguard transparency verification) election trust)` | anchor+OR | or | 10 | 1 | 1 | 0.100 |
| rag2026-8 | `(^ (+ court lawsuit) "2020 election" fraud evidence)` | anchor+OR | phrase,or | 10 | 0 | 0 | 0.000 |
| rag2026-8 | `(^ "risk-limiting audit" election)` | phrase-bearing | phrase | 10 | 2 | 2 | 0.200 |
| rag2026-8 | `(^ (+ paper ballot audit) election security)` | anchor+OR | or | 10 | 0 | 1 | 0.000 |
| rag2026-8 | `(^ (+ drop box mail ballot) fraud evidence)` | anchor+OR | or | 10 | 1 | 1 | 0.100 |
| rag2026-9 | `(^ uranium (+ mining supply price))` | anchor+OR | or | 10 | 0 | 0 | 0.000 |
| rag2026-9 | `(^ uranium (+ conversion enrichment fabrication))` | anchor+OR | or | 10 | 1 | 1 | 0.100 |
| rag2026-9 | `(^ uranium russia)` | other | — | 10 | 1 | 1 | 0.100 |
| rag2026-9 | `(^ HALEU (+ advanced reactor SMR))` | anchor+OR | or,entity | 10 | 2 | 2 | 0.200 |
| rag2026-9 | `(^ uranium "long-term contract")` | phrase-bearing | phrase | 10 | 2 | 2 | 0.200 |
| rag2026-9 | `(^ Kazatomprom (+ production disruption))` | anchor+OR | or,entity | 10 | 0 | 0 | 0.000 |
| rag2026-9 | `(^ uranium conversion (+ capacity Russia))` | anchor+OR | or,entity | 10 | 3 | 3 | 0.300 |
| rag2026-9 | `(^ uranium enrichment (+ capacity Russia Europe))` | anchor+OR | or,entity | 10 | 0 | 0 | 0.000 |
| rag2026-9 | `(^ uranium inventory utility (+ contracting))` | anchor+OR | or | 10 | 2 | 2 | 0.200 |
| rag2026-9 | `(^ Centrus HALEU)` | other | entity | 10 | 0 | 2 | 0.000 |
| rag2026-9 | `(^ uranium fabrication bottleneck)` | multi-AND | — | 10 | 0 | 0 | 0.000 |

## KEY — aggregation by shape bucket (ranked by pooled ratio)

| rank | shape bucket | n_q | Σret | Σfs_c | mean sel | **pooled** |
|--:|---|--:|--:|--:|--:|--:|
| 1 | phrase-bearing | 27 | 224 | 26 | 0.113 | **0.116** |
| 2 | multi-AND | 47 | 412 | 44 | 0.105 | **0.107** |
| 3 | anchor+OR | 46 | 412 | 40 | 0.092 | **0.097** |
| 4 | other | 16 | 148 | 12 | 0.077 | **0.081** |

## Aggregation by structural tag

| tag | n_q | Σret | Σfs_c | mean sel | pooled |
|---|--:|--:|--:|--:|--:|
| has_phrase=True | 37 | 314 | 35 | 0.107 | 0.111 |
| has_or=True | 46 | 412 | 40 | 0.092 | 0.097 |
| has_prox=True | 0 | 0 | 0 | 0.000 | 0.000 |
| has_entity=True | 25 | 196 | 22 | 0.108 | 0.112 |
| ALL queries | 136 | 1196 | 122 | 0.099 | 0.102 |

## Novelty gap (raw vs first-surfacer)

Pooled **raw_committed = 138** returned-slots landed in a committed set, but only **fs_committed = 122** were credited after first-surfacer correction — the correction removed **16** double-counted re-surfacings (12% of raw). Raw pooled ratio would have been 0.115 vs corrected 0.102.

## Finding

Ranked by first-surfacer productivity the **phrase-bearing** shape leads (pooled 0.116) while **other** trails (pooled 0.081). On the tag axis, entity-bearing queries pool at 0.112 vs 0.100 for non-entity queries, phrase-bearing at 0.111, and OR-anchored at 0.097. The standing hypothesis is that SSR shines on fact-heavy/entity/exact-phrase/co-occurrence queries. The entity and phrase signals support that story within this arm, but the effect sizes are small and rest on tiny per-cell N. Because the model both wrote and judged, a high ratio reflects what the agent chose to trust, not independent relevance — so read these as hypotheses to test against qrels, not a verdict.

---

## Appendix — cross-backend baseline (context for the within-SSR ratios)

The ratios above are strictly within-SSR (see Caveat 1). For context only, here are the four single-backend arms (10 topics each). The pooled first-surfacer selection ratio is `Σ fs_committed / Σ returned` across each arm's whole trajectory.

| backend (single-arm) | run_id | searches | docs returned | fs-committed | pooled fs-ratio |
|---|---|--:|--:|--:|--:|
| keyword (BM25-OR) | cmp-keyword | 75 | 591 | 116 | 0.196 |
| dense (semantic) | cmp-dense | 97 | 786 | 133 | 0.169 |
| lucene (Boolean) | cmp-lucene | 142 | 1287 | 151 | 0.117 |
| ssr (fork v2) | cmp-ssr-fork-v2 | 136 | 1196 | 122 | 0.102 |

By this ratio SSR is the lowest (0.102), and the two Boolean engines (lucene 0.117, ssr 0.102) both sit below the two natural-language engines (keyword 0.196, dense 0.169). But the gap is largely a denominator artifact, not a quality verdict. The absolute first-surfacer-committed counts all fall in the same band — dense 133, keyword 116, lucene 151, ssr 122 — so SSR actually committed more docs than keyword. What differs is the denominator: SSR and lucene return roughly 2x more docs (1196 / 1287 vs 591 / 786), because Boolean usage means many cheap probes plus retries, and the per-step commit budget is capped. A bigger return pile mechanically depresses the ratio.

So this metric reads as "Boolean runs more/wider probes per committed doc" — a usage pattern — not "Boolean's retrieved docs are worse." The ratio is only clean *within* an engine and cannot crown a backend across engines. That is why the rubric-grounded LLM-judge comparison (separate, in progress) is the real cross-engine test.
