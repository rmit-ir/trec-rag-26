# 2026-07-18 — living-plan prompt change; query formulation vs fusion search

**System:** `src/systems/aus_agent/`, luna via Azure, run-id `aus-agent-luna-dev2`.

## Prompt change: the plan is now a living document

Response to the discovery-breadth finding (rubric attainment tracks search
count). Four edits to `prompts/system.md`, in place of a bolted-on "widening
pass" (kept generic per user direction; widening pass parked unless testing
shows it's still needed):

1. Plan item 4: the coverage-area list "is provisional: searching reveals
   what the request actually needs, and the plan is revised as it does."
2. Decide step rewritten as reflect-then-judge: revise the plan against what
   retrieval has shown (retrieval-revealed aspects join the coverage areas;
   areas whose reformulated searches keep failing are recorded as
   unsupportable, not retried forever); loop on any area lacking support "or
   supported only thinly where the request deserves depth"; exit only when
   **every coverage area of the current plan is resolved** — committed
   material or failed searches behind it.
3. Sizing note gains a quality floor: "Small is not shallow: even the
   shortest answer rests on the strongest support the corpus offers."
4. Budget section no longer licenses early stopping: "keep improving … while
   you can name a specific weakness"; an unresolved/thin coverage area "is
   always such a weakness."

Tests updated (4 new flattened assertions); 44/44 pass.

## A/B test

- **Investing dev topic** (worst offender, was 4 searches / 6 refs / ~35%
  attainment): now **6 searches / 2 commits / 11 refs / 41 sentences /
  1011 words / 115K tokens**. Round 2 pivoted to gaps (target-date funds,
  CDs/liquidity, fees/volatility) and the answer gained target-date funds,
  CDs, brokers — call it ~45%. Still missing the heavyweight rubric
  entities (401(k)/IRA/Roth, index names): queries stayed generic, see
  below. No word-limit bounce this time (1011 ≤ 1024).
- **Narrow ad-hoc factual question**: 1 search / 1 commit / 2 refs /
  4 sentences / 131 words / 15K tokens — every quoted statistic verified
  verbatim in retrieved text. No bloat on simple questions; the quality
  floor held (dense, fully cited answer). (Health-topic probes avoided in
  future ad-hoc tests per user.)

Verdict: the living plan widens breadth proportionally and cheaply. The
remaining gap is not *how much* the model searches but *what it types into
the box* — see below.

## Query formulation vs the fusion engine

The search tool sends each query **verbatim to both** retrievers — Jina-v5
dense + BM25 sparse, RRF-fused (`rrf_k=60`, equal weights, depth
`max(k, 50)`; `utils/search.py`). Compared luna's actual queries against
clean variants on the live engine:

| variant | top-5 quality |
|---|---|
| A. luna round-1 soup: "ways people can invest money for retirement and large purchases **understandable applicable all adults prior experience** investing" | generic listicles, a 17-char stub doc, one junk hit ("Category Archives: Children"); RRF scores show dense and sparse agreed on only 1 of 5 hits |
| B. natural question: "what types of accounts and investments should a beginner use to save for retirement?" | 5/5 on-topic beginner guides |
| C. compact keywords: "retirement accounts 401k IRA index funds beginner" | 5/5, incl. the exact doc the rubric wanted ("the two most common types of retirement accounts are 401(k)s and IRAs") |
| D. targeted entity: "401k IRA Roth traditional tax differences" | 5/5 Roth-vs-traditional comparison docs |
| E/F. genre suffix ("academic study journalist report") on/off | mixed — suffix not clearly harmful; both sets usable, small overlap |

Findings:

1. **Copying request meta-language into queries hurts both retrievers.**
   Audience/format words ("understandable", "all adults", "blog posts",
   "technical report") describe the *answer*, not the evidence: they add
   noise terms for BM25 and dilute the dense embedding across unrelated
   concepts. The provenance rule ("queries from the question's own wording")
   is being obeyed too literally — it governs where terms may come from,
   not that every request word belongs in a query.
2. **Dense/sparse agreement is a quality signal.** The soup query's two
   ranked lists were nearly disjoint (fused scores ≈ single-list 1/61);
   clean facet queries get both modes voting for the same documents.
3. **The corpus had everything the investing rubric wanted** one compact
   query away (C and D prove it) — confirming the gap is query wording,
   not corpus coverage or search count.

Proposed next step (not yet applied): one clarifying line in the Search
step and/or the tool's `query` field description — build queries from the
question's *content* terms, one facet per query, dropping audience/format/
instruction words; keep queries short, natural phrases around distinctive
terms so dense and sparse reinforce each other.

## Robustness test (sub-agent, 5 further runs under the new prompt)

| run | searches/commits | refs | words | tokens | note |
|---|---|---|---|---|---|
| social media (rerun) | 10/3 | 12 | 913 | 225K | vs old-prompt 8/2, 11 refs, 823 w, 113K |
| UBI pilots (new broad) | 12/3 | 13 | 738 | 256K | textbook plan revision |
| "Who invented the WWW?" | 1/1 | 2 | 31 | 12K | no bloat |
| term deposit vs savings | 1/1 | 2 | 83 | 11K | no bloat |
| how solar panels work | 1/1 | 2 | 80 | 17K | no bloat |

- **Breadth improved.** Social-media rerun exceeded its baseline on every
  count and expanded round-over-round into facets round 1 surfaced
  (misinformation/journalism, workplace, activism/disasters, cyberbullying/
  hate speech, social capital); answer covers ~7 domains with case studies.
  UBI showed the cleanest living-plan signature possible: broad probe →
  named pilots surfaced (Finland Kela, Ontario, Stockton SEED, Alaska PFD)
  → per-pilot deep dives + a new fiscal-cost axis → corroborating studies
  (systematic review, NBER) → genuine cross-pilot synthesis. 85 rejected vs
  14 committed docs — active filtering.
- **Robust on simple questions.** All three narrow runs: exactly 1 search,
  1 commit, 2–3 fully-cited sentences; every spot-checked headline claim
  (Berners-Lee/CERN/1989/Cailliau; fixed-term/penalty/variable-rate; p-n
  junction/DC/inverter) found verbatim in retrieved text. The coverage-area
  exit does not inflate trivially satisfiable plans.
- **Costs.** Broad-topic tokens roughly doubled (225K/256K vs 113K
  baseline); the social-media rerun bounced the 1024-word cap twice
  (1171 → 1039 → 913) before passing. Both are breadth-side costs; no
  regression on narrow questions.
- **Still unprobed axes**: regulation/policy and non-Western platforms —
  the gains came from deepening surfaced facets, not from expert-volunteered
  axes the corpus never mentioned. The parked "widening pass" (edit 2)
  remains the candidate if those rubric axes matter; query formulation is
  the bigger lever first.
