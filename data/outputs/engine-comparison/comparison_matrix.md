# Retrieval-backend comparison — 10 topics × 4 backends

*Same `aus_agent` deep-research loop (OpenAI `gpt-5.6-luna`, full 500k-token budget), each topic run four times restricted to ONE retrieval backend via `--search-backends`, over the full 3.5 TB corpus. All 40 runs completed.*

## Findings

**Winner tally (best fit per topic, graded by reading queries + committed evidence + final answer):** dense ~5, keyword ~3, lucene ~2, **SSR 0**.

**1. Dense (semantic) is the most consistent winner** for these long, synthesis-heavy narrative topics. Natural-language queries map one-to-one onto the request's own facets, essentially never miss (**0 zero-result searches across all 10 topics**), and produce the most densely-cited reports in the fewest searches. Safest default for broad "help me understand / brief me" questions.

**2. Lucene-Boolean and keyword-BM25 win on entity-rich, fact-heavy topics** (2020-election specifics, COVID statistics, investment authorities). Required-term BM25 (`+term`) **degrades gracefully** — it ranks partial matches instead of hard-zeroing — and its **full-document passages** (vs snippets) surface the richest concrete anchors (dollar figures, dates, named episodes). Lucene retrieves/commits the most docs; keyword is the most search-efficient.

**3. SSR was never the best standalone backend for this task — for two distinct reasons:**
- **Over-constraint → truthful zeros.** On 7 of 10 topics the agent stacked 4–7 required terms into one `(^ ...)` AND; required co-occurrence in a single document collapsed to empty. Worst: de-minimis (rag2026-5) **11 zeros / 19 searches**; investment (rag2026-3) 6/15; nuclear-fuel (rag2026-9) 6/15, knocking out the pivotal HALEU facet. The agent kept *adding* rare tokens instead of dropping the weakest — the opposite of the right recovery.
- **Thin evidence windows (independent of zeros).** Even when ANDs stayed populated (rag2026-7), SSR returns short ~1.2k-char shortest-substring snippets vs full-document passages, so its committed evidence is shallower and more answer sentences go uncited.

**4. What SSR is actually for.** Its strengths — required co-occurrence, exact phrases, and *truthful zeros that confirm non-existence* — make it a **precision / disambiguation instrument** (surname collisions, "do these two rare entities co-occur?", verbatim fact-checks), not a broad-recall synthesis engine. Used as a bag-of-ANDs for open-ended research it fights its own precision.

**5. Actionable SSR tool-instruction fix (validated by this sweep).** The guidance says "2–4 terms" but the agent routinely wrote 5–7. It should (a) hard-cap AND arity at ~3, (b) lead with the single rarest term, (c) make the "**on zero, DROP a term (never add one)**" rule primary, and (d) prefer `(+ ...)`-inside-`(^ ...)` to keep one facet required while widening the rest.

> `#zero` = searches returning empty; `#uniqDoc` = distinct docids retrieved (recall proxy); `#commit` = docs retained as evidence. SSR `score` is synthetic rank-decay (1/rank), not comparable across engines.

## Per-topic comparison

### rag2026-0 — Hospital nursing DEI three-year plan under budget
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 8 search / 0 zero / 57 doc / 15 commit | 8 / 0 / 56 / 16 | 12 / 1 / 108 / 15 | 17 / 0 / 122 / 13 |
| **Trajectory** | 8 natural-language facet queries (5–9 terms) mapping onto pipeline, hiring, reporting, curriculum, then advancement/psych-safety/microlearning follow-ups; every query returned 8 hits. | 8 bag-of-words queries, round-2 refined to distinctive terms (National Commission, implicit-bias, psychological safety); pure OR bags, all 8 hits. | 12 GCL ANDs, mostly 4–5 required terms; one 5-term AND `(^ nursing DEI accountability metrics leadership)` returned ZERO, recovered by dropping terms. | Most iterative: 17 `+`required BM25 queries over 3 rounds, narrowing (retaliation, anonymous, simulation, scholarship); no zeros. |
| **Analysis** | Cleanest run: 0 empty/failed, fully-grounded report, every sentence cited incl. microlearning/hidden-curriculum specifics. | Effective & grounded; long full-text passages gave rich evidence, OR surfaced some off-facet docs it correctly rejected. | Worked but strained: one over-constrained AND zeroed, and short ~1.3k snippets left 5 plan-scaffolding sentences uncited — weakest grounding. | Broadest exploration but only 13 cited; extra iterations bought coverage yet the report leans more on model priors. |

**Verdict:** Dense served this broad conceptual topic best — one-pass facet coverage, zero misses, tightest fully-grounded report. SSR over-constrained once and its short windows left plan-structure sentences uncited.

### rag2026-1 — Biological effects of grief on an elderly widow
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 8 / 0 / 61 / 14 | 6 / 0 / 48 / 10 | 9 / 0 / 83 / 10 | 8 / 0 / 63 / 12 |
| **Trajectory** | 8 NL queries (7–11 words) mirroring sub-questions almost verbatim (heart/immune/hormones, complicated vs normal grief, takotsubo, PGD criteria). | 6 long bag-of-words queries (8–12 terms) piling concepts, relying on OR overlap. | 9 GCL `(^ ...)` ANDs (4–8 required terms), finest decomposition into sub-topics (glucocorticoid/immune, ECG/echo, adherence). | 8 terse `+`required queries of just 3–5 terms, one facet each with strict AND. |
| **Analysis** | Committed the most (14 refs); well-grounded on stress cardiomyopathy, DSM-5-TR 12-month criteria, medication review. | All 8 hits, term-piling worked under OR; grounded (takotsubo/troponin/ECG, suicide signs). | **The one topic SSR hit ZERO zeros** — grief-biology terms co-occur densely, so required-ANDs stayed populated; solid but slightly less quantified. | Short 3–5-term `+`ANDs stayed populated; best-quantified answer (21× day-1, 6× week-1 MI risk). |

**Verdict:** Unusual topic — all four had zero empty searches because grief-biology vocabulary co-occurs densely, so even SSR's required-ANDs stayed populated. Dense committed the most; Lucene's short `+`ANDs gave the most quantified answer. The one case SSR did NOT over-constrain — a property of the corpus, not of operator choice.

### rag2026-2 — Endorsing a health-care-as-a-right ballot campaign
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 10 / 0 / 74 / 10 | 7 / 0 / 56 / 13 | 14 / 5 / 82 / 18 | 14 / 0 / 137 / 19 |
| **Trajectory** | 10 NL queries (8–10 words) as parallel facet batches (universal coverage, medical debt, Medicaid, single-payer); no zeros. | 7 long BM25 bags (6–9 terms), all 8 hits, none zeroed. | 14 GCL ANDs, several 5–6 required terms; **5 zeroed — every AND containing "Medicaid expansion"** (e.g. `(^ Medicaid expansion employer insurance emergency room safety net)`), forcing 2–3 term rewrites. | 14 `+`required queries (3–5 terms); BM25 back-off kept all 10 populated, none zeroed; committed 20. |
| **Analysis** | First-pass usable hits on every facet; cleanest evidence spread (KFF, Oregon Medicaid, EMTALA, single-payer), best-grounded with fewest searches. | OR shrugged off long term lists; strong sources (28%-underinsured, Oregon +40% ER); long queries cost nothing here. | Still produced a solid report via short ANDs, but the central Medicaid facet repeatedly over-constrained to zero; most wasted searches, thinnest per-query coverage. | Stayed populated even on 5-term ANDs; richest quantified answer (160M employer-covered, 138% FPL, 2.5M coverage-gap); highest search cost. |

**Verdict:** Lucene and dense best — lucene for richest specific evidence, dense for the same coverage in far fewer searches. SSR weakest: strict required co-occurrence over-constrained the long "Medicaid expansion" ANDs to five truthful zeros.

### rag2026-3 — Lifelong investment plan for an 18-year-old with $10,000
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 9 / 0 / 71 / 12 | 10 / 0 / 90 / 12 | 15 / 7 / 79 / 9 | 11 / 0 / 103 / 13 |
| **Trajectory** | 9 NL phrases (7–10 terms) targeting named authorities (ASIC/Moneysmart/ATO), super, diversification, academic passive-investing; adapted to AU-specific tax/super. | 10 BM25 OR bags (6–9 terms) mixing topic, authority, academic terms; broadened smoothly. | 15 `(^ ...)` required-ANDs (4–7 stemmed terms); kept retrying narrower AU-specific variants after repeated empties. | 11 terse all-`+`required conjunctions (4–6 keywords, incl. literal `+18 +10000`). |
| **Analysis** | 0 failures, well-grounded (16/29 sentences cited); ~45% uncited scaffolding. | **Most fully-cited report — all 26 sentences cited**; OR matched enough evidence to ground every claim. | **6 of 15 zeroed** (every Australia/super/Moneysmart/ETF/tax probe); fewest refs (9) despite most attempts; misses AU super/tax grounding. | Most refs committed (13) but least grounded — only 11/32 sentences cited. |

**Verdict:** Keyword (BM25 OR) best — zero dead-ends, 100% sentence-level grounding. SSR clearly over-constrained: required co-occurrence zeroed 6/15 (every Australia/super/Moneysmart/ETF/tax probe), fewest refs despite most attempts.

### rag2026-4 — Nostalgia, the social clock, and midlife life decisions
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 8 / 0 / 48 / 12 | 7 / 0 / 38 / 8 | 8 / 1 / 54 / 8 | 9 / 0 / 69 / 9 |
| **Trajectory** | 8 NL queries (5–8 words) onto facets (nostalgia psych, social clock, comparison, rumination, decisions); adapted round-2 from round-1 hits. | 7 bag-of-words queries (5–7 terms), broad then narrowed to social-comparison, memory-reconstruction, transition-planning. | 8 `(^ ...)` ANDs anchored on nostalgia/social-clock + 3–4 qualifiers; one 4-term AND `(^ "social comparison" self-esteem friends success)` hit ZERO, then loosened. | 9 `+`required; opened with over-long 6-term AND `+life +choices +dating +career +move +city`, later split into tighter 3–4 term ANDs + phrase `+"social clock"`. |
| **Analysis** | Strongest fit: 6 hits every query, 12 committed, nearly every sentence cited (often two) — most densely grounded. | Worked well; BM25 OR surfaced on-topic psychology docs, fewer sources per claim than dense. | Required-AND returned short ~1.2k snippets; practical-advice sections left uncited — most citation-free sentences, thinnest grounding. | Grounded the definitional/social-clock claims well, but ~500-char snippets left advice sentences uncited — between dense and ssr. |

**Verdict:** Dense best — natural-language phrasing matched the psychology corpus, zero misses, richest most-cited synthesis. SSR weakest: REQUIRED co-occurrence over-constrained a soft advice topic (a 4-term AND returned an outright zero, and tiny snippets starved practical-advice citations).

### rag2026-5 — De minimis / Section 321 China direct-ship for small ecommerce
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 11 / 0 / 88 / 12 | 6 / 0 / 37 / 10 | **19 / 11 / 44 / 6** | 21 / 0 / 168 / 10 |
| **Trajectory** | 11 NL searches (6–13 words) covering every sub-question (de minimis, air freight, forced labor/UFLPA, Mexico/Canada inventory, 2025/2026 policy), refined with year/enforcement terms. | Just 6 broad OR queries, each packing many terms (Temu/Shein, USMCA, UFLPA, Xinjiang, postal suspension); relied on OR recall. | 19 `(^ ...)` required-ANDs; started 4–5 terms and **kept ADDING rare tokens** (UFLPA, CUSMA, quoted `"6-13 days"`) instead of dropping. | 21 queries mixing `+`required clauses with quoted phrases; adapted well, dropping to bare phrase queries (`"What is Section 321"`) when strict ANDs thinned. |
| **Analysis** | Zero misses, widest pool (88 docs); 12 refs, 17/19 segments cited — best-grounded. | No zeros, steady 8 hits; 20/21 segments cited — efficient despite fewest searches. | **11 of 19 ZERO** and several thin; over-constraint collapsed recall to 44 docs, only 6 refs, 8/18 cited — the textbook over-constraint case. | No zeros, mostly 10 hits; 10 refs, strong recall/grounding — close second to dense. |

**Verdict:** Dense best on this entity-dense topic — full coverage, largest pool, most-cited; keyword/lucene close. SSR the clear loser: required co-occurrence of long term-stacks (adding UFLPA/CUSMA/Xinjiang/phrases as ANDs) drove 11/19 to zero — the sharpest illustration that SSR must DROP terms on zero, not add them.

### rag2026-6 — Historical analysis of world change since COVID-19
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 12 / 0 / 93 / 17 | 9 / 0 / 62 / 12 | 10 / 1 / 90 / 17 | 16 / 0 / 159 / 27 |
| **Trajectory** | 12 NL queries mirroring the domain list (health, work, education, travel, economy, mental health, tech) as full noun phrases; broad fan-out then targeted follow-ups. | 9 bag-of-words queries; one long 11-term opener then compact 5–7 term facets, later trimming k 8→6. | 10 `(^ ...)` ANDs anchored on covid + 4–7 terms; the long opener `(^ 2025 post-pandemic lifestyle work travel education economy)` returned empty, recovered by per-domain decomposition. | 16 `+`required queries (most facets/rounds), each stacking 4–6 terms; broadest sweep, no empties, added date probes (+2025, +2023). |
| **Analysis** | 0 empties; 17 committed/cited; well-grounded, chronological, rich figures (74% tourism drop, 52% hybrid, first UK dose 8 Dec 2020). | Densest statistics of any run (1.7B students, remote work 5.2%→46.3%); best-evidenced, example-heavy. | 18 committed but tiny ~1.2–1.5k passages and 1/n scores → thinner grounding; coherent but fewer hard numbers. | Committed 30 / cited 27 — most evidence — but 500-char snippets → shallow per-doc depth; most granular on dates. |

**Verdict:** Keyword best — full-document hits gave the richest quantified, example-laden grounding with no wasted searches; dense close. SSR's one long 7-term AND over-constrained to a zero (forcing decomposition) and short passages gave thinner support; Lucene most docs but only 500-char snippets — breadth over depth.

### rag2026-7 — AI political-signals trading strategy, pension due-diligence
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 7 / 0 / 56 / 12 | 6 / 0 / 46 / 14 | 12 / 0 / 107 / 9 | 14 / 0 / 130 / 16 |
| **Trajectory** | 7 NL queries (8–14 words) from the question's facets, then STOCK Act / spoofing / adviser-fiduciary follow-ups; no zeros. | 6 broad BM25 bags, later seeded with Height Analytics, "SEC predictive data analytics"; every query 8 long full-body docs. | 12 `(^ ...)` required-ANDs, 5–7 terms then decomposed to 3–5; **no zeros here** (corpus populates 7-term ANDs). | 14 queries with 4–7 `+`required terms, widest fan-out, every facet decomposed; no zeros. |
| **Analysis** | Well-grounded; hit STOCK Act 45-day, 75.1% benchmark, flash crash, spoofing, but missed Height/Medicare and CFTC. | **Best-grounded: 34 sentences, zero uncited**; only answer to hit every anchor (STOCK Act, 75.1%, Height/Medicare, CFTC, flash crash, spoofing) via long passages. | **Weakest grounding despite no zeros** — thin ~1.2k passages + rank-decay surfaced generic docs; 9 refs, 19/27 uncited, closed with an "I could not establish" disclaimer. | Broad but shallow — 500-char cap starved depth; 21/31 uncited, caught only STOCK Act + CFTC. |

**Verdict:** Keyword best — full-body passages uniquely surfaced every concrete anchor with zero uncited; dense close second. Notably SSR did NOT over-constrain here (7-term ANDs stayed populated) yet still grounded worst — its short shortest-substring windows returned generic docs. **SSR's second, distinct weakness: thin evidence, independent of the zero-result problem.**

### rag2026-8 — Explaining 2020 fraud claims & election-integrity reforms
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 12 / 0 / 89 / 13 | 8 / 0 / 50 / 11 | 18 / 4 / 106 / 16 | 14 / 0 / 123 / 18 |
| **Trajectory** | 12 NL queries: 3 broad facets then 6–9 single-facet paraphrases (dead voters, Dominion recounts, Maricopa audit, poll watchers, risk-limiting audits); never zero. | 8 bag-of-words queries (4–5 terms), round-2 seeded with names surfaced earlier (Antrim, Fulton suitcases, 2000 Mules); 5–10 hits, no zeros. | 18 `(^ ...)` ANDs, mostly 2–4 anchors; **4 over-constrained 4–7-term ANDs returned ZERO** (Arizona-report, voting-restriction, voter-ID, Dominion-defamation). | 14 `+`required queries; round-2 seeded proper names (Maricopa/forensic, Wisconsin/address, defamation); always ≥8 hits, no zeros. |
| **Analysis** | Comprehensive; 18/21 cited incl. +360-vote Maricopa detail, 41% drop-box figure. | Efficient, fully grounded (18/18 cited); richest specific rebuttals (Antrim error, 2000 Mules debunk). | Most searches/docs but least efficient; the zeros cost it the Dominion-defamation and audit-report facets → more generic answer, fewer hard numbers. | Retrieved/committed the most; best-sourced concrete answer (Fox $787.5M, 36 states, 10,457 vs 45,109 margins), one repair dropped 2 hallucinated docids. |

**Verdict:** Lucene best — required-term BM25 stayed populated on every facet and surfaced the most verifiable specifics; dense/keyword close. SSR over-constrained: long 4–7-term ANDs produced four zero-result searches that dropped whole sub-claims — weakest grounding.

### rag2026-9 — Nuclear fuel-supply risk for a utility board's PPA/SMR decision
| | dense (semantic) | keyword (BM25-OR) | ssr (GCL-Boolean) | lucene (Boolean) |
|---|---|---|---|---|
| **stats** | 12 / 0 / 97 / 16 | 8 / 0 / 68 / 10 | 15 / 6 / 87 / 11 | 18 / 0 / 127 / 14 |
| **Trajectory** | 12 NL queries: 4 broad facets (Russia/China/Kazakhstan, front-end bottlenecks, HALEU, contracting) then 8 targeted follow-ups (sanctions, price formulas, PPA pass-through). | 8 BM25 OR queries, two rounds of 4 facets with plain distinctive terms; no zeros, stopped early. | 15 `(^ ...)` required-ANDs; opening 4–6-term ANDs + HALEU/TENEX/enrichment facets **zeroed (6 of 15)**, forcing 2–3-term rewrites and the phrase `"high assay" "low enriched uranium"` to recover HALEU. | 18 `+`required queries, widest iteration (Cameco/Orano shortfalls, China demand, HALEU); all non-empty, several capped at 4–8 hits. |
| **Analysis** | Cleanest fit: every facet answered, 19 committed/16 cited, quantified (Kazakhstan 43%, Russia 12/17%, ~5% cost, 91% long-term) — most complete/grounded. | Efficient, grounded (Slovak fuel-qualification example) but thinnest effort, less quantitative depth. | Over-constrained — long ANDs collapsed exactly the HALEU/Russian-enrichment facets the board most needs; fewest docs, shortest least-quantified answer. | Broadest net (18 committed) with UK HALEU-funding/Cameco/Orano specifics, but under-cited — many board-recommendation sentences uncited. |

**Verdict:** Dense best — full facet coverage, most quantified/grounded answer, no wasted queries. SSR clearly over-constrained: multi-term required ANDs returned 6 truthful zeros that knocked out HALEU and Russian-enrichment until it relaxed to short ANDs and a phrase.


---

# Appendix: numeric matrix & full query trajectories

| topic | backend | status | #search | #zero | #fail | #uniqDoc | #commit | ans.chars |
|---|---|---|--:|--:|--:|--:|--:|--:|
| rag2026-0 | dense(semantic) | completed | 8 | 0 | 0 | 57 | 15 | 30 |
| rag2026-0 | keyword(BM25-OR) | completed | 8 | 0 | 0 | 56 | 16 | 36 |
| rag2026-0 | ssr(GCL-Boolean) | completed | 12 | 1 | 0 | 108 | 15 | 24 |
| rag2026-0 | lucene(Boolean) | completed | 17 | 0 | 0 | 122 | 13 | 30 |
| rag2026-1 | dense(semantic) | completed | 8 | 0 | 0 | 61 | 14 | 16 |
| rag2026-1 | keyword(BM25-OR) | completed | 6 | 0 | 0 | 48 | 10 | 18 |
| rag2026-1 | ssr(GCL-Boolean) | completed | 9 | 0 | 0 | 83 | 10 | 14 |
| rag2026-1 | lucene(Boolean) | completed | 8 | 0 | 0 | 63 | 12 | 18 |
| rag2026-2 | dense(semantic) | completed | 10 | 0 | 0 | 74 | 10 | 22 |
| rag2026-2 | keyword(BM25-OR) | completed | 7 | 0 | 0 | 56 | 13 | 28 |
| rag2026-2 | ssr(GCL-Boolean) | completed | 14 | 5 | 0 | 82 | 18 | 25 |
| rag2026-2 | lucene(Boolean) | completed | 14 | 0 | 0 | 137 | 19 | 32 |
| rag2026-3 | dense(semantic) | completed | 9 | 0 | 0 | 71 | 12 | 29 |
| rag2026-3 | keyword(BM25-OR) | completed | 10 | 0 | 0 | 90 | 12 | 26 |
| rag2026-3 | ssr(GCL-Boolean) | completed | 15 | 7 | 0 | 79 | 9 | 20 |
| rag2026-3 | lucene(Boolean) | completed | 11 | 0 | 0 | 103 | 13 | 32 |
| rag2026-4 | dense(semantic) | completed | 8 | 0 | 0 | 48 | 12 | 16 |
| rag2026-4 | keyword(BM25-OR) | completed | 7 | 0 | 0 | 38 | 8 | 17 |
| rag2026-4 | ssr(GCL-Boolean) | completed | 8 | 1 | 0 | 54 | 8 | 18 |
| rag2026-4 | lucene(Boolean) | completed | 9 | 0 | 0 | 69 | 9 | 16 |
| rag2026-5 | dense(semantic) | completed | 11 | 0 | 0 | 88 | 12 | 19 |
| rag2026-5 | keyword(BM25-OR) | completed | 6 | 0 | 0 | 37 | 10 | 21 |
| rag2026-5 | ssr(GCL-Boolean) | completed | 19 | 11 | 0 | 44 | 6 | 18 |
| rag2026-5 | lucene(Boolean) | completed | 21 | 0 | 0 | 168 | 10 | 18 |
| rag2026-6 | dense(semantic) | completed | 12 | 0 | 0 | 93 | 17 | 30 |
| rag2026-6 | keyword(BM25-OR) | completed | 9 | 0 | 0 | 62 | 12 | 33 |
| rag2026-6 | ssr(GCL-Boolean) | completed | 10 | 1 | 0 | 90 | 17 | 31 |
| rag2026-6 | lucene(Boolean) | completed | 16 | 0 | 0 | 159 | 27 | 28 |
| rag2026-7 | dense(semantic) | completed | 7 | 0 | 0 | 56 | 12 | 27 |
| rag2026-7 | keyword(BM25-OR) | completed | 6 | 0 | 0 | 46 | 14 | 34 |
| rag2026-7 | ssr(GCL-Boolean) | completed | 12 | 0 | 0 | 107 | 9 | 27 |
| rag2026-7 | lucene(Boolean) | completed | 14 | 0 | 0 | 130 | 16 | 31 |
| rag2026-8 | dense(semantic) | completed | 12 | 0 | 0 | 89 | 13 | 21 |
| rag2026-8 | keyword(BM25-OR) | completed | 8 | 0 | 0 | 50 | 11 | 18 |
| rag2026-8 | ssr(GCL-Boolean) | completed | 18 | 4 | 0 | 106 | 16 | 16 |
| rag2026-8 | lucene(Boolean) | completed | 14 | 0 | 0 | 123 | 18 | 19 |
| rag2026-9 | dense(semantic) | completed | 12 | 0 | 0 | 97 | 16 | 30 |
| rag2026-9 | keyword(BM25-OR) | completed | 8 | 0 | 0 | 68 | 10 | 30 |
| rag2026-9 | ssr(GCL-Boolean) | completed | 15 | 6 | 0 | 87 | 11 | 19 |
| rag2026-9 | lucene(Boolean) | completed | 18 | 0 | 0 | 127 | 14 | 27 |

# Full search trajectories

## rag2026-0

### dense(semantic)  —  8 searches, 15 committed, 0 zero, 0 failed
   - (8) nursing school pipeline partnerships recruitment retention diversity equity inclusion
   - (8) nursing hiring promotion practices racial equity retention nurses of color
   - (8) healthcare reporting systems racism leadership accountability nurses
   - (8) nursing curriculum continuing education racism diversity equity inclusion
   - (8) nursing workforce diversity leadership advancement promotion structural practices accountability
   - (8) nurse racism retention psychological safety reporting retaliation outcomes measurement
   - (8) nursing diversity equity inclusion hiring bias promotion mentorship sponsorship flexible scheduling
   - (8) anti-racism nursing education evaluation competencies microlearning outcomes

### keyword(BM25-OR)  —  8 searches, 16 committed, 0 zero, 0 failed
   - (8) nursing school pipeline partnerships recruitment retention nurses of color
   - (8) nursing hiring promotion practices racial equity retention
   - (8) nursing reporting systems racism leadership accountability
   - (8) nursing curriculum continuing education racism diversity equity inclusion
   - (8) National Commission racism nursing reporting accountability retaliation
   - (8) nursing DEI metrics retention promotion workforce survey
   - (8) nurses of color racism workplace reporting system psychological safety
   - (8) DEI training nursing implicit bias effectiveness limitations

### ssr(GCL-Boolean)  —  12 searches, 15 committed, 1 zero, 0 failed
   - (10) (^ nurse (+ diversity inclusion equity) recruitment retention)
   - (10) (^ nursing school pipeline partnership recruitment)
   - (10) (^ nurse hiring promotion practice bias)
   - (10) (^ report racism nurse workplace)
   - (10) (^ nursing leadership accountability diversity)
   - (10) (^ nursing curriculum continuing education racism)
   - (10) (^ nurse retention turnover belonging racism)
   - (10) (^ nurse diversity metric promotion retention)
   - (10) (^ racism reporting retaliation follow up nurse)
   - (0) (^ nursing DEI accountability metrics leadership)
   - (10) (^ nurse implicit bias intervention cultural humility)
   - (10) (^ nursing promotion mentorship sponsorship minority)

### lucene(Boolean)  —  17 searches, 13 committed, 0 zero, 0 failed
   - (8) +nurs* +DEI +recruit* +retention
   - (8) +nurs* +racism +report* +accountability
   - (8) +nurs* +promotion +hiring +divers*
   - (8) +nurs* +curriculum +continuing +education +racism
   - (8) +nurs* +school +pipeline +partnership
   - (6) +nurs* +"National Commission" +racism +survey
   - (8) +healthcare +inclusive +leadership +accountability +promotion
   - (8) +nurs* +racism +report* +retaliat*
   - (8) +nurs* +hiring +promotion +equity +interview
   - (8) +nurs* +curriculum +antiracist +onboarding
   - (8) +nurs* +pipeline +mentor* +school
   - (8) +nurs* +retention +belonging +racism
   - (8) +nurs* +racism +report* +anonymous
   - (8) +nurs* +racism +survey +career +bullying
   - (8) +healthcare +DEI +metrics +retention +promotion
   - (8) +nurs* +continuing education +bias +racism +simulation
   - (8) +nurs* +pipeline +scholarship +retention


## rag2026-1

### dense(semantic)  —  8 searches, 14 committed, 0 zero, 0 failed
   - (8) grief biological effects body heart immune system stress hormones inflammation
   - (8) bereavement chest tightness warning signs older adult medical care
   - (8) normal mourning versus complicated grief time periods older adults
   - (8) grief support checkups blood pressure medication sleep appetite family support
   - (8) stress-induced cardiomyopathy broken heart syndrome symptoms after bereavement older women
   - (8) bereavement health check medication adherence blood pressure older adult primary care
   - (8) prolonged grief disorder twelve months diagnostic criteria older adults
   - (8) grief inflammation cortisol epinephrine immune function cardiovascular risk evidence limitations

### keyword(BM25-OR)  —  6 searches, 10 committed, 0 zero, 0 failed
   - (8) grief bereavement heart chest pain stress hormones inflammation immune system
   - (8) bereavement older adults warning signs medical evaluation chest tightness sleep appetite blood pressure
   - (8) prolonged grief disorder diagnostic time period older adults support treatment
   - (8) bereavement primary care checkup blood pressure medication adherence older adults counseling sleep appetite
   - (8) grief support normal mourning counseling social support older adults depression suicide warning signs
   - (8) takotsubo cardiomyopathy bereavement ECG troponin evaluation chest tightness women

### ssr(GCL-Boolean)  —  9 searches, 10 committed, 0 zero, 0 failed
   - (10) (^ grief heart chest tightness older adult sudden death)
   - (10) (^ grief immune system stress hormone inflammation sleep appetite)
   - (10) (^ grief warning signs time periods support checkup medication blood pressure)
   - (10) (^ takotsubo bereavement chest pain shortness breath heart attack)
   - (10) (^ glucocorticoid grief immune inflammation)
   - (10) (^ prolonged grief older adult treatment support)
   - (10) (^ bereavement blood pressure medication checkup)
   - (8) (^ chest pain emergency electrocardiogram echocardiogram)
   - (8) (^ grief medication adherence blood pressure older adult)

### lucene(Boolean)  —  8 searches, 12 committed, 0 zero, 0 failed
   - (8) +grief +heart +chest +tightness
   - (8) +grief +immune +inflammation
   - (8) +grief +stress +hormone +sleep
   - (8) +bereavement +older +blood pressure +appetite
   - (8) +bereavement +chest +pain +emergency +heart
   - (8) +grief +prolonged +support +counseling
   - (8) +grief +medication +adherence +older
   - (8) +bereavement +checkup +blood pressure +sleep


## rag2026-2

### dense(semantic)  —  10 searches, 10 committed, 0 zero, 0 failed
   - (8) health care as a right not privilege U.S. policy universal coverage affordability
   - (8) medical debt health insurance affordability United States policy
   - (8) Medicaid expansion employer-based insurance emergency room safety net United States
   - (8) single-payer health care taxes patient choice implementation risks United States
   - (8) employer-sponsored health insurance job loss coverage portability United States
   - (8) health care reform universal coverage federal taxes spending fiscal effects United States
   - (8) single payer patient choice provider payment wait times United States
   - (8) Medicaid expansion health outcomes access equity state budget evidence
   - (8) health insurance coverage affordability underinsurance cost sharing United States
   - (10) single payer patient choice taxes provider payment wait times United States

### keyword(BM25-OR)  —  7 searches, 13 committed, 0 zero, 0 failed
   - (8) health care right privilege universal coverage affordability medical debt
   - (8) Medicaid expansion employer-based insurance emergency room safety net
   - (8) single-payer health care taxes patient choice implementation risks
   - (8) health insurance administrative costs provider payment taxes fiscal practicality United States
   - (8) employer-sponsored insurance worker job lock patient choice provider network
   - (8) medical debt affordability out-of-pocket cost health insurance coverage implementation
   - (8) single payer proposal taxes provider rates wait times United States fiscal

### ssr(GCL-Boolean)  —  14 searches, 18 committed, 5 zero, 0 failed
   - (8) (^ health care right privilege universal coverage affordability)
   - (8) (^ medical debt health care affordability)
   - (0) (^ Medicaid expansion employer insurance emergency room safety net)
   - (8) (^ single payer proposal taxes patient choice implementation risk)
   - (0) (^ ACA Medicaid expansion coverage affordability)
   - (10) (^ emergency room uninsured health care safety net)
   - (10) (^ single payer taxes financing health insurance)
   - (10) (^ patient choice insurance single payer)
   - (10) (^ employer sponsored insurance wages coverage)
   - (0) (^ Medicaid expansion uninsured coverage states)
   - (0) (^ Medicaid state federalism eligibility coverage)
   - (10) (^ health reform implementation federalism separation powers)
   - (10) (^ health care tax revenue costs universal coverage)
   - (0) (^ Medicaid expansion low income uninsured access)

### lucene(Boolean)  —  14 searches, 19 committed, 0 zero, 0 failed
   - (10) +health care +right +privilege +universal coverage +policy
   - (10) +health care +affordability +medical debt +taxes
   - (10) +Medicaid +expansion +employer-based insurance +emergency room
   - (10) +single-payer +patient choice +implementation risks
   - (10) +Affordable Care Act +coverage +premium +subsidy +uninsured
   - (10) +employer-sponsored insurance +tax exclusion +workers +premiums
   - (10) +Medicaid expansion +coverage +health outcomes +state
   - (10) +single-payer +taxes +administrative costs +provider payment +choice
   - (10) +medical debt +uninsured +insurance +financial burden
   - (10) +universal coverage +rationing +waiting times +patient choice
   - (10) +single-payer +federal spending +taxes +health care
   - (10) +health insurance transition +single-payer +employers +providers
   - (10) +Medicaid expansion +emergency room +utilization +study
   - (10) +health care spending +United States +other countries +universal coverage


## rag2026-3

### dense(semantic)  —  9 searches, 12 committed, 0 zero, 0 failed
   - (8) Australia 18 year old investing $10,000 lifelong diversified portfolio superannuation tax
   - (8) academic evidence diversification low cost index investing long term asset allocation lifecycle investing
   - (8) Australian Securities and Investments Commission investing risks diversification fees scams financial advice
   - (8) Australia superannuation voluntary contributions tax concessional non concessional 18 year old
   - (8) Moneysmart emergency fund investing high interest savings account before investing
   - (8) Moneysmart exchange traded funds index funds diversification fees Australia
   - (8) ATO 2025-26 super contribution caps concessional non concessional Australia
   - (8) academic study active mutual fund performance fees passive investing long term evidence
   - (8) Moneysmart compound interest regular investing market volatility long term shares

### keyword(BM25-OR)  —  10 searches, 12 committed, 0 zero, 0 failed
   - (8) 18 year old ten thousand dollars investment plan future lifetime Australia
   - (8) academic investment diversification asset allocation long term investor fees
   - (8) Australia superannuation young investor investment tax authoritative
   - (10) ASIC Moneysmart diversification fees index funds investing Australia
   - (10) Australian government super guarantee 18 years $450 month 2026
   - (10) investment policy statement regular investing market timing behavioural gap academic
   - (10) emergency fund high interest debt before investing financial plan Australia
   - (10) index investing active fund performance fees broad market index academic study
   - (10) asset allocation life cycle young investor equities bonds academic evidence
   - (10) Australia financial advice investing risks leverage cryptocurrency ASIC Moneysmart

### ssr(GCL-Boolean)  —  15 searches, 9 committed, 7 zero, 0 failed
   - (10) (^ invest lifetime young adult diversification risk return)
   - (10) (^ ten thousand dollar invest future eighteen)
   - (0) (^ Australia superannuation young investor fees diversification)
   - (10) (^ investing fees diversification index fund evidence)
   - (0) (^ moneysmart diversification investment risk Australia)
   - (0) (^ moneysmart superannuation contribution young Australia)
   - (0) (^ emergency fund cash reserve investing Australia moneysmart)
   - (10) (^ academic index fund active fund fees long term performance diversification)
   - (10) (^ inflation shares bonds cash long term investment risk return)
   - (10) (^ compound interest regular contributions investment young)
   - (0) (^ superannuation contribution retirement Australia)
   - (0) (^ investment tax Australia capital gains dividend)
   - (0) (^ ETF exchange traded fund diversified low fee Australia)
   - (10) (^ dollar cost averaging lump sum investing evidence)
   - (10) (^ investor risk tolerance time horizon rebalance portfolio)

### lucene(Boolean)  —  11 searches, 13 committed, 0 zero, 0 failed
   - (10) +investment +plan +future +age +18 +10000
   - (10) +investor +lifetime +diversification +risk
   - (10) +Australia +investing +superannuation +tax +financial
   - (10) +diversification +asset +allocation +fees +index
   - (10) +superannuation +contribution +retirement +tax +Australia
   - (10) +compound +interest +investing +long-term +returns
   - (10) +Moneysmart +investing +diversification +fees
   - (10) +active +management +fees +index +fund +performance
   - (10) +superannuation +preservation +age +retirement +Australia
   - (10) +market +timing +long-term +diversification +risk
   - (10) +ETF +broad +market +Australia +fees +diversification


## rag2026-4

### dense(semantic)  —  8 searches, 12 committed, 0 zero, 0 failed
   - (6) psychology of nostalgia comfort old memories identity meaning
   - (6) social clock feeling behind peers life milestones adulthood
   - (6) nostalgia social comparison other people's timelines life decisions
   - (6) nostalgia useful coping when harmful rumination psychology
   - (6) personal goals instead of peer comparison life decisions social clock dating career
   - (6) nostalgic memories idealized past current life comparison hazy memories
   - (6) nostalgia identity continuity future planning transitions new job moving city
   - (6) rumination reflection problem solving actionable questions mindfulness old memories

### keyword(BM25-OR)  —  7 searches, 8 committed, 0 zero, 0 failed
   - (5) nostalgia psychological comfort identity meaning social connection
   - (5) social clock life milestones peers career marriage children age
   - (5) nostalgia memory idealized past comparison present decisions
   - (5) emerging adulthood life transitions dating career moving cities uncertainty
   - (6) social comparison peers life milestones wellbeing
   - (6) memory reconstruction idealization autobiographical memory nostalgia
   - (6) life transition decision values career relationship relocation practical planning

### ssr(GCL-Boolean)  —  8 searches, 8 committed, 1 zero, 0 failed
   - (8) (^ nostalgia psychological comfort past identity)
   - (8) (^ nostalgia social comparison friends life timeline)
   - (8) (^ nostalgia decision making future goals)
   - (8) (^ social clock adulthood career marriage children)
   - (8) (^ nostalgia "rose-colored" memory)
   - (0) (^ "social comparison" self-esteem friends success)
   - (8) (^ nostalgia autobiographical memory identity continuity)
   - (8) (^ social clock relocation job career marriage parenthood)

### lucene(Boolean)  —  9 searches, 9 committed, 0 zero, 0 failed
   - (8) +nostalgia +psychologically +comforting
   - (8) +"social clock" +friends +career
   - (8) +nostalgia +comparison +past
   - (8) +life +choices +dating +career +move +city
   - (8) +nostalgia +meaning +connectedness +future
   - (8) +nostalgia +regret +"what-ifs"
   - (8) +"social clock" +"social media" +stress
   - (8) +social +comparison +timeline +milestones
   - (8) +decision +values +career +relationship +city


## rag2026-5

### dense(semantic)  —  11 searches, 12 committed, 0 zero, 0 failed
   - (8) US de minimis Section 321 shipments China online shop $800 tariffs customs crackdown
   - (8) shipping straight from China to each customer delivery air freight small online brand
   - (8) forced labor compliance China imports US customs small ecommerce accessories home items
   - (8) holding inventory United States Mexico Canada ecommerce supply chain alternatives China direct shipping
   - (10) de minimis China policy change 2025 Section 321 customs
   - (8) UFLPA forced labor supply chain due diligence Xinjiang imports customs detention
   - (10) Mexico Canada inventory fulfillment US ecommerce customs tariffs alternative
   - (8) air freight China ecommerce dimensional weight lithium batteries delivery time
   - (10) de minimis tariff exemption China suspended postal shipments customs
   - (10) Section 321 China customs crackdown online retail shipments
   - (10) China low value parcels tariffs customs enforcement ecommerce 2026

### keyword(BM25-OR)  —  6 searches, 10 committed, 0 zero, 0 failed
   - (8) China direct customer shipping $800 de minimis Section 321 Temu Shein tariffs customs
   - (8) small business ecommerce de minimis air freight delivery cost China United States
   - (8) Section 321 forced labor compliance customs USMCA Mexico Canada inventory alternatives
   - (8) Section 321 China de minimis tariffs 2025 2026 customs crackdown
   - (8) UFLPA forced labor de minimis Section 321 ecommerce cotton Xinjiang customs detention
   - (8) China ecommerce air freight de minimis postal suspension delivery customs data low value shipments

### ssr(GCL-Boolean)  —  19 searches, 6 committed, 11 zero, 0 failed
   - (8) (^ "section 321" "800" de minimis)
   - (8) (^ china direct customer shipping de minimis tariff)
   - (8) (^ de minimis air freight delivery)
   - (8) (^ de minimis forced labor compliance)
   - (8) (^ inventory united states mexico canada supply chain)
   - (0) (^ UFLPA Xinjiang entity list shipment)
   - (7) (^ de minimis customs oversight reform lawmakers)
   - (0) (^ China de minimis tariff customs parcel)
   - (0) (^ air freight express shipping commercial invoice HS code)
   - (0) (^ Mexico Canada warehouse inventory ecommerce customs)
   - (0) (^ UFLPA "forced labor" Xinjiang)
   - (3) (^ "de minimis" "Section 321" customs)
   - (0) (^ CUSMA Canada Mexico "de minimis" small businesses)
   - (1) (^ de minimis air shipping "6-13 days")
   - (0) (^ Shein Temu de minimis lawmakers loophole)
   - (0) (^ de minimis tariff 2025 China)
   - (0) (^ de minimis customs crackdown China ecommerce)
   - (0) (^ warehouse Mexico United States inventory shipping ecommerce)
   - (0) (^ warehouse Canada United States inventory shipping ecommerce)

### lucene(Boolean)  —  21 searches, 10 committed, 0 zero, 0 failed
   - (10) +de minimis +Section 321 +China +ecommerce
   - (10) +de minimis +tariff +customs +crackdown
   - (10) +China +customer +shipping +air freight +delivery
   - (10) +forced labor +China +imports +de minimis
   - (10) +inventory +United States +Mexico +Canada +supply chain
   - (10) +"Section 321" +$800 +China
   - (10) +"de minimis" +suspend* +China +tariff
   - (10) +"de minimis" +inspection +counterfeit +customs
   - (9) +UFLPA +forced labor +de minimis
   - (10) +Mexico +USMCA +warehouse +inventory
   - (10) +Canada +warehouse +inventory +United States +shipping
   - (10) +de minimis +2025 +China +executive
   - (10) +de minimis +2026 +China +customs
   - (10) +Section 321 +data +country of origin +broker
   - (10) +de minimis +counterfeit +unsafe +packages
   - (10) +air freight +China +capacity +rates +ecommerce
   - (5) "What is Section 321"
   - (1) "How Long Does it Take to Ship and Deliver from China to USA"
   - (1) "How long does it take for a package from China to arrive in the US"
   - (5) +Mexico +sourcing +"supply chains" +workforce
   - (10) +forced labor +supply chain +disclosures +China +ecommerce


## rag2026-6

### dense(semantic)  —  12 searches, 17 committed, 0 zero, 0 failed
   - (8) life before COVID-19 pandemic public health work education travel economy social interactions technology
   - (8) early 2020 global COVID-19 outbreak lockdown response schools workplaces travel
   - (8) COVID-19 vaccine rollout 2020 2021 global public health changes
   - (8) post-pandemic life 2025 work culture education travel economy mental health social interaction technology
   - (8) COVID-19 pandemic economic impact inflation supply chains employment inequality
   - (8) COVID-19 pandemic mental health education learning loss digital technology adoption remote work
   - (8) COVID-19 travel restrictions international travelers tourism air pollution return to normal
   - (8) COVID-19 public health preventive measures masks ventilation vaccination healthcare system
   - (8) COVID-19 hybrid work remote work office return post-pandemic 2025
   - (8) COVID-19 2025 post-pandemic lifestyle travel education work technology
   - (8) COVID-19 social interaction isolation grief anxiety healthcare workers mental health recovery
   - (8) COVID-19 economy stimulus unemployment informal workers inequality recovery inflation

### keyword(BM25-OR)  —  9 searches, 12 committed, 0 zero, 0 failed
   - (8) life before COVID pandemic public health work education travel economy mental health social interactions technology
   - (8) early 2020 global response lockdown outbreak COVID-19
   - (8) COVID-19 vaccine rollout 2021 global impact
   - (8) 2025 post-pandemic lifestyle work travel education technology mental health
   - (6) pre-pandemic workplace office commuting remote work hybrid work 2025
   - (6) school closures online learning education digital divide COVID recovery 2025
   - (6) COVID travel tourism recovery 2025 international travel behavior
   - (6) COVID long term public health excess mortality long COVID 2025
   - (6) COVID inflation supply chains labor market economy recovery 2025

### ssr(GCL-Boolean)  —  10 searches, 17 committed, 1 zero, 0 failed
   - (10) (^ pandemic covid public health work education travel economy)
   - (10) (^ covid outbreak 2020 global response vaccine rollout)
   - (10) (^ covid mental health social interaction technology adoption)
   - (0) (^ 2025 post-pandemic lifestyle work travel education economy)
   - (10) (^ covid economic recession job loss business closure supply chain inflation)
   - (10) (^ covid travel restriction tourism border control reopening)
   - (10) (^ covid education school closure remote learning digital divide children)
   - (10) (^ covid vaccine rollout vaccination global inequality booster variant)
   - (10) (^ covid 2023 2024 2025 work hybrid travel technology)
   - (10) (^ covid social distancing isolation community relationships social interaction)

### lucene(Boolean)  —  16 searches, 27 committed, 0 zero, 0 failed
   - (10) +COVID +pandemic +public health +before after
   - (10) +COVID +pandemic +work +education +travel
   - (10) +COVID +pandemic +economy +mental health +social
   - (10) +COVID +vaccine +technology +2025
   - (10) +COVID +lockdown +mask +vaccine +rollout
   - (10) +COVID +remote +work +home +hybrid
   - (10) +COVID +remote +learning +school +education
   - (10) +COVID +mental +health +lonely +social
   - (10) +COVID +travel +restriction +tourism +recession
   - (10) +COVID +digital +technology +online +adoption
   - (10) +COVID +2025 +post-pandemic +lifestyle
   - (10) +COVID +long-term +management +health +emergency
   - (10) +COVID +economy +inflation +supply +employment
   - (10) +COVID +online +shopping +telehealth +digital
   - (10) +COVID +social +interaction +mask +distancing +community
   - (10) +COVID +before +2019 +travel +work +school


## rag2026-7

### dense(semantic)  —  7 searches, 12 committed, 0 zero, 0 failed
   - (8) AI political signals strategy congressional trades lobbying disclosures proposed bills geopolitical headlines social media trading
   - (8) legality ethics governance algorithmic trading public pension political information
   - (8) data quality model risk market impact regulation automated trading social media
   - (8) congressional stock trades STOCK Act insider trading disclosure legality
   - (8) algorithmic trading market manipulation spoofing risk controls regulation
   - (8) AI investment adviser fiduciary duty model risk regulation pension
   - (8) lobbying disclosure data quality political influence conflicts ethics

### keyword(BM25-OR)  —  6 searches, 14 committed, 0 zero, 0 failed
   - (8) AI political signals congressional trades lobbying disclosures proposed bills geopolitical headlines social media market impact
   - (8) political intelligence legality ethics congressional trading lobbying disclosure investment
   - (8) algorithmic trading model risk data quality market impact regulation pension fiduciary governance
   - (8) political intelligence insider trading material nonpublic information SEC congressional staff Height Analytics
   - (8) social media data privacy algorithmic trading misinformation market manipulation AI
   - (8) SEC artificial intelligence investment adviser predictive data analytics conflicts fiduciary 2024

### ssr(GCL-Boolean)  —  12 searches, 9 committed, 0 zero, 0 failed
   - (8) (^ congressional trade lobbying disclosure proposed bill market impact)
   - (8) (^ political signal algorithm trade social media geopolitical headline)
   - (8) (^ legality ethics data quality model risk market impact regulation)
   - (10) (^ congressional trade legality regulation disclosure)
   - (10) (^ lobbying disclosure legality ethics regulation)
   - (10) (^ social media data privacy quality algorithm trade)
   - (10) (^ public pension fiduciary investment governance model risk)
   - (10) (^ congressional trade insider information)
   - (10) (^ political trading market manipulation regulation)
   - (10) (^ algorithmic trading market impact controls audit)
   - (4) (^ model risk backtest data leakage overfit trading)
   - (10) (^ public pension fiduciary duty manager oversight)

### lucene(Boolean)  —  14 searches, 16 committed, 0 zero, 0 failed
   - (8) +congressional +trades +lobbying +disclosures +proposed +bills
   - (8) +geopolitical +headlines +social +media +algorithms +trade
   - (8) +political +signals +strategy +market +impact +governance
   - (8) +artificial +intelligence +investment +model +risk +regulation
   - (10) +insider +trading +Congress +nonpublic +information
   - (10) +AI +asset +management +governance +model +risk +SEC
   - (10) +social +media +misinformation +market +manipulation +trading
   - (10) +lobbying +disclosure +financial +market +trade
   - (10) +algorithmic +trading +market +impact +liquidity +risk
   - (10) +responsible +AI +financial +markets +recommendations
   - (10) +investment +adviser +AI +fiduciary +disclosure
   - (10) +AI +market +manipulation +surveillance +regulator
   - (10) +data +quality +social +media +alternative +data +investment
   - (10) +political +information +trading +ethics +disclosure +securities


## rag2026-8

### dense(semantic)  —  12 searches, 13 committed, 0 zero, 0 failed
   - (8) 2020 election fraud claims dead voters Dominion machines poll watchers blocked mail ballots drop boxes
   - (6) Arizona audit 2020 election findings evidence
   - (8) election integrity laws voting harder safeguards public trust participation
   - (8) 2020 election dead voters evidence voter rolls deceased ballots
   - (8) 2020 election mail ballots drop boxes fraud evidence chain of custody
   - (8) Dominion voting machines 2020 audits recounts evidence claims
   - (8) Arizona Senate Maricopa County audit results 2020 ballots
   - (8) 2020 election poll watchers blocked observation evidence
   - (8) risk limiting audits election transparency voter confidence access voting laws participation
   - (8) photo identification early voting restrictions voter participation registration evidence
   - (8) election law voting access mail ballot signature verification ballot tracking evidence
   - (8) 2020 election officials secure election no evidence widespread fraud audits recounts

### keyword(BM25-OR)  —  8 searches, 11 committed, 0 zero, 0 failed
   - (8) 2020 election fraud claims dead voters Dominion machines poll watchers blocked evidence
   - (8) mail ballots drop boxes 2020 election evidence security safeguards
   - (8) Arizona audit 2020 election findings evidence
   - (8) election integrity laws voting harder access participation safeguards trust
   - (5) Antrim County Dominion software glitch hand recount 2020 votes
   - (5) Fulton County poll watchers suitcase ballots table 2020 counting explanation
   - (5) dead people voting 2020 election fact check ballots deceased voters
   - (6) election trust audits paper ballots transparency bipartisan observers voter access safeguards

### ssr(GCL-Boolean)  —  18 searches, 16 committed, 4 zero, 0 failed
   - (8) (^ (+ "2020 fraud" election) (+ evidence debunk))
   - (8) (^ (+ "dead voter" dead vot) election 2020)
   - (8) (^ dominion machine election 2020)
   - (8) (^ (+ "poll watcher" observer) blocked election 2020)
   - (8) (^ (+ "mail ballot" "drop box") election 2020)
   - (8) (^ "Arizona audit" election 2020)
   - (8) (^ election integrity law voting harder participation)
   - (8) (^ dominion election machine vote count court 2020)
   - (0) (^ Arizona audit ballot count 2020 report)
   - (8) (^ election observer access counting room 2020 ballot)
   - (8) (^ election audit paper ballot bipartisan observer chain custody)
   - (8) (^ voter fraud exceedingly rare election safeguards)
   - (0) (^ voting restriction mail ballot voter ID early voting long lines evidence)
   - (8) (^ audit election ballot recount verification)
   - (8) (^ mail ballot signature verification drop box security chain)
   - (0) (^ voter ID law voting access evidence turnout)
   - (8) (^ election poll watcher rules intimidation assistance disability language)
   - (0) (^ Dominion defamation election false claims settlement)

### lucene(Boolean)  —  14 searches, 18 committed, 0 zero, 0 failed
   - (8) +2020 +fraud +dead voters +Dominion
   - (8) +2020 +poll watchers +blocked +mail ballots +drop boxes
   - (8) +Arizona +audit +election
   - (8) +election integrity laws +voting harder +participation
   - (10) +Maricopa +forensic +audit +Biden +Trump
   - (10) +Dominion +defamation +machines +2020
   - (10) +poll watcher +observer +counting +2020
   - (10) +mail ballot +drop box +safeguards +registered voter
   - (10) +voting restrictions +shortened +mail ballot +identification +2021
   - (10) +dead voters +Wisconsin +address +2020
   - (10) +election audits +paper ballots +transparency +public trust
   - (10) +election officials +poll watchers +training +transparency +trust
   - (10) +voter identification +mail ballot +drop box +access +fraud
   - (10) +2020 election +courts +state officials +fraud evidence


## rag2026-9

### dense(semantic)  —  12 searches, 16 committed, 0 zero, 0 failed
   - (8) uranium fuel supply risks Russia China Kazakhstan price spikes nuclear power purchase agreement
   - (8) uranium mining conversion enrichment fabrication bottlenecks nuclear fuel supply
   - (8) HALEU advanced reactors fuel supply risk
   - (8) long-term uranium contracts utility price protection fuel supply
   - (10) Russia uranium conversion enrichment dependence nuclear fuel supply disruption sanctions
   - (10) Kazakhstan uranium production disruption supply risk 2024 2025
   - (10) uranium price spike long-term spot market utilities inventory fuel supply
   - (10) HALEU supply chain enrichment fabrication advanced reactor fuel United States Russia China
   - (10) utility uranium procurement long term contracts inventories diversification fuel supply security
   - (10) nuclear fuel supply chain conversion capacity enrichment capacity bottleneck Russia Western utilities
   - (10) uranium contract price formula long term contracts spot escalation utility
   - (10) nuclear power purchase agreement fuel price risk uranium pass through

### keyword(BM25-OR)  —  8 searches, 10 committed, 0 zero, 0 failed
   - (10) uranium fuel supply risks Russia China Kazakhstan price spikes
   - (10) uranium mining conversion enrichment fabrication bottlenecks
   - (10) long-term uranium contracting utility nuclear fuel price protection
   - (10) HALEU advanced reactors fuel supply risk
   - (10) uranium conversion enrichment capacity Russia replacement inventories utilities
   - (10) nuclear fuel fabrication bottleneck reactor specific fuel diversification
   - (10) uranium long term contracts inventory flexibility delivery obligation utility
   - (10) Kazakhstan uranium transport Russia supply disruption China inventories

### ssr(GCL-Boolean)  —  15 searches, 11 committed, 6 zero, 0 failed
   - (10) (^ uranium (+ russia china kazakhstan) (+ price spike supply risk))
   - (10) (^ uranium mining conversion enrichment fabrication bottleneck)
   - (10) (^ uranium "long term" contract utility price risk)
   - (0) (^ HALEU advanced reactor fuel supply)
   - (0) (^ conversion uranium hexafluoride Russia capacity enrichment)
   - (10) (^ "high assay" "low enriched uranium" advanced reactor fuel)
   - (0) (^ HALEU "fuel" reactor supply)
   - (10) (^ uranium price volatility spot contract utility inventory)
   - (10) (^ uranium fabrication fuel supply reactor)
   - (0) (^ Russia uranium enrichment conversion ban supply)
   - (0) (^ TENEX HALEU Russia advanced reactor)
   - (10) (^ uranium long term contracts inventories utilities disruption)
   - (0) (^ uranium Russia enrichment capacity Europe United States China)
   - (10) (^ uranium price spike supply deficit mine suspension contract price)
   - (10) (^ uranium conversion capacity shortage enrichment bottleneck)

### lucene(Boolean)  —  18 searches, 14 committed, 0 zero, 0 failed
   - (8) +uranium +supply +risk +Russia +China +Kazakhstan
   - (8) +uranium +conversion +enrichment +fabrication +bottleneck
   - (8) +HALEU +advanced +reactor +supply
   - (8) +uranium +price +spike +long-term +contract utility
   - (10) +uranium +Kazakhstan +production +mine
   - (10) +Russia +uranium +conversion +enrichment +fuel
   - (10) +uranium +conversion +capacity +enrichment +western
   - (10) +long-term +contract +uranium +utility +inventory
   - (4) +Cameco +Orano +production +shortfall +uranium
   - (10) +HALEU +Russia +supply +enrichment
   - (10) +uranium +utility +contracting +inventory +term
   - (10) +uranium +spot +term +price +contract
   - (10) +Russian +uranium +ban +enrichment +alternative
   - (10) +uranium +fuel +stockpile +months +reactor
   - (10) +uranium +fabrication +fuel +qualification +supply
   - (10) +advanced +reactor +HALEU +fuel +availability
   - (8) +China +uranium +enrichment +conversion
   - (8) +China +uranium +fuel +supply +reactor
