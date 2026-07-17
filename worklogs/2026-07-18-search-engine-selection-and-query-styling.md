# 2026-07-18 — engine-selectable search tool + query-styling study

## Engine selection (`search_engine` parameter)

`run_search_tool` / the `search` tool schema / the CLI (`--engine`) now take
`search_engine`: **`semantic`** (dense Jina-v5, **default** — user's call,
made mid-implementation), `keyword` (BM25), `fusion` (dense+sparse RRF, the
old always-on behaviour). Unknown values return the standard `{"error": ...}`
row. Output row shape unchanged (`{rank, id, docid, kind, rrf_score, text}`);
`rrf_score` carries the engine's native score (inner-product / BM25) for
single-engine runs — key name kept because four systems consume it. The
aus_agent adapter forwards the argument only when the model supplies it, so
the backend default is the single source of truth. 45/45 tests (one new
pass-through test).

**Behaviour change to remember:** every caller that omits the parameter —
aus_agent runs where the model doesn't choose, `ali_deepresearch` tools,
`claude-code-research` corpus script — now gets dense-only retrieval instead
of fusion.

**Artifact hygiene:** swept `data/outputs/` for the old long values
(`search_semantic`/`search_keyword`/`search_fusion`) after all sub-agents
finished — zero files matched (the old names only ever appeared in CLI
probes, which write no artifacts). Nothing to delete; replay safety intact.

**Viewer:** `outputs_viewer` step labels for search calls now render
`[<engine>] <query>` when the call recorded a `search_engine` (old
trajectories render unchanged). Minimal by design; `tsc --noEmit` clean.

## Query-style × engine study (96 result sets, judged by reading)

Sub-agent derived 10 search tasks (8 query types) from 6 dev topics, ran
3–4 query styles each against all three engines at k=5. Final aggregates
(relevant@5, real queries, n=28): **fusion 4.64 ≈ semantic 4.50 >
keyword 3.89**; by style: natural-question → fusion 4.8/semantic 4.7;
compact keywords → fusion 4.7/semantic 4.6; entity-anchored → fusion 4.4.

Findings (by confidence):

1. **[strong] Meta-word soup fails everywhere, worst on semantic.** All
   "bad" styles ≈ 0/5. Refines the earlier finding: the dominant failure
   is dense **centroid drift** (audience/format words drag the embedding
   off-topic), not only dense/sparse disagreement — keyword partially
   recovers when distinctive terms survive; semantic collapses to 0.
2. **[strong] Semantic likes natural questions; keyword hates them**
   (stopword dilution: 2–3/5 on question phrasing).
3. **[strong] Keyword wins only for exact named strings — with the full
   distinctive term.** Danger case: "Sepp Hochreiter long short-term
   memory" scored **0/5 on semantic** (drifted to biological long-term
   memory); adding "Schmidhuber 1997" rescued it to 5/5. Names colliding
   with common-word senses are the dense danger zone.
4. **[strong] Compact distinctive-term queries are the safest style on
   every engine and where fusion peaks** (RRF agreement stacks).
5. **[moderate] Fusion is the most robust choice** — never 0 on a good
   style; degrades toward but rarely below the worse engine.
6. **[moderate] The name split cuts both ways**: rare surnames/IDs →
   keyword (semantic drifts); well-known product/concept names → semantic
   (keyword matched incidental mentions: CS:GO 2/5 — ad-cost and
   mute-guide pages). Fusion 5/5 on both, hence "fusion when unsure".
   Bare single-entity queries are noisy; one qualifier fixes them, and a
   single common word ("income", "sharing") is 0/5 on every engine.
7. **[suggestive] Numeric/statistical intent**: no engine surfaces the
   specific number reliably; query topic+entity instead of the
   number-question.
8. **[suggestive] Engine choice only matters on hard/ambiguous/entity
   queries** — densely-covered web topics score 5/5 everywhere.

Corpus quirks: ClimbMix pages are headline/FAQ-shaped, so phrasing a query
like a webpage title or FAQ boosts both engines (especially semantic);
near-duplicate SEO clones can stack in fusion's top-5; adult-dating spam
contaminates "carbon dating" queries on every engine.

## Instruction changes applied (from the findings)

- Shared schema `search_engine` description: per-engine selection guidance
  (concepts/questions → semantic; exact names/rare strings with the full
  term → keyword; mixed name+concept or compact-term queries → fusion).
- aus_agent `query` description: one facet per query as a short specific
  phrase — distinctive content words or a webpage-title/FAQ-style question;
  one disambiguating qualifier on proper names; omit audience/format/task
  words; topic+entity (not the number) for numeric facts.
- aus_agent tool description: one-line style↔engine matching rule.

Raw sweep log: scratchpad `sweep.log` (session-local).

## Post-update rerun (`aus-agent-luna-dev3`, same six test queries)

| run | dev2 (before) | dev3 (after) |
|---|---|---|
| investing | 6 srch / 11 refs / 1011 w / 115K | 7 / 10 / 918 / 127K, 1 bounce |
| social media | 10 / 12 / 913 / 225K | 11 / **15** / 898 / 216K, 0 bounces |
| UBI | 12 / 13 / 738 / 256K | 10 / 13 / 889 / **177K** (−31%) |
| WWW / deposit / solar | 1 srch each | 1 srch each, 24–97 w — robust |

- **Query styling clearly improved where it was worst.** The investing
  round-1 soup ("…understandable applicable all adults prior experience…")
  is gone — every query is now a compact distinctive-term set. UBI queries
  are entity-anchored (Kela 2020, Ontario cancellation 2018, Stockton
  SEED, Roosevelt Institute). Genre suffixes ("academic study case study")
  persist on social media — the study measured those as roughly neutral.
- **UBI got 31% cheaper at equal refs** — better queries found the same
  evidence in fewer, more targeted rounds.
- **Engine choice: the model picks `fusion` explicitly on all 27 queries**
  (broad and narrow) and never omits the parameter, so the semantic
  omit-default is effectively unused by aus_agent. It read "fusion = the
  safest choice" and adopted always-fusion rather than varying per query
  type. Acceptable per the study (fusion 4.64, never catastrophic), and
  arguably the right degenerate policy — but the per-type variation the
  guidance describes did not materialize; keyword may still go unused even
  on rare-surname queries. Watch for a case where that costs recall before
  tuning the wording further.
- Narrow probes also chose fusion, added disambiguators per guidance
  ("photovoltaic cells"), and stayed at 1 search / 1 commit.

## Fusion removed — binary engine choice (`aus-agent-luna-dev4`)

Follow-up to the always-fusion observation. User's call: since staged
results are deduplicated at commit anyway, extra queries are nearly free —
so drop the "safe" option and make the model the fusion layer, issuing
per-engine styled queries instead of one compromise string RRF'd. Changes:

- `SEARCH_ENGINES = ("semantic", "keyword")`; the fused branch is gone from
  the tool (`utils/search.py` itself stays — search_serve and others still
  use it). Unknown values (incl. "fusion") return the standard error row.
- aus_agent schema now **requires** `search_engine` — every query is a
  deliberate engine choice.
- Engine/field descriptions teach per-engine styling (semantic = natural
  phrase or question; keyword = bare distinctive terms, no stopwords) and
  "cover an important facet with both engines, one styled query each;
  duplicates are deduplicated downstream."
- Legacy callers that omit the parameter still default to semantic.
  45/45 tests pass.

Test round (luna):

| run | searches | refs | words | tokens | note |
|---|---|---|---|---|---|
| solar (narrow) | 2 | 2 | 77 | 17.7K | perfect pair: semantic natural phrase + keyword term set |
| investing (broad) | 5 | 9 | 1013 | **87.8K** | cheapest investing run yet (dev2 115K / dev3 127K), 0 bounces |

Observations:

- **The pairing behaviour works when distinctive terms exist**: solar's two
  queries are genuinely differently styled per engine.
- **When a facet has no rare tokens, the "pair" degrades to a shuffle**:
  investing round 1's keyword query is the semantic query reordered —
  all common words, nothing for BM25 to anchor on. Not harmful (dedup),
  just not additive.
- **Round 2+ engine assignment is sensible**: three conceptual gap-filling
  queries all went semantic, matching the guidance rather than blind
  pairing. Keyword went unused after round 1 — the run again never chased
  exact strings like "401(k)"/"Roth", which are ideal keyword queries; the
  gap is target selection, not engine mechanics.
- Cost DOWN ~25–30% on the broad topic at similar output quality —
  single-engine calls are cheaper than fused and the model spent fewer,
  more decisive rounds.

Net: keep the binary setup. Remaining watch item: whether keyword gets
used for named-entity chasing on entity-rich topics (UBI-style) — if not,
one line in the keyword description naming "program names, statutes,
account types" as candidates may be worth testing.
