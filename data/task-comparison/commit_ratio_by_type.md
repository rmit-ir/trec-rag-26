# Commit ratio by query type (backend x intent, first-surfacer)

**Model (classifier + taxonomy):** `gpt-5.6-luna` (luna). **Runs:** four single-backend arms, 10 topics each — `cmp-dense`, `cmp-keyword`, `cmp-lucene`, `cmp-ssr-fork-v2` (labels `dense`/`keyword`/`lucene`/`ssr`).

**Metric — first-surfacer commit ratio.** For each search query Q, `fs_committed` counts docids that Q was the FIRST query (in its topic-backend trajectory) to surface AND that ended up in the topic's final committed `references` set; `returned` is len(returned_docids). A cell's **pooled ratio = Sigma fs_committed / Sigma returned** over its queries. This is the identical first-surfacer credit rule used by `selection_ratio.py`, generalized across all four backends.

**Query TYPE** is a luna-judged engine-agnostic intent label; **role** is a luna-judged trajectory role. Each query was classified with its FULL topic-backend trajectory (every query + hit count) in context, so retries/openers/pivots are distinguished. See `query_type_taxonomy.md` for definitions and `query_classifications.jsonl` for per-query labels.

**Totals:** 450 queries, Sigma_returned=3860, Sigma_fs_committed=522, overall pooled ratio **0.135**.

## Taxonomy summary

| type | definition |
|---|---|
| `broad-exploratory` | Seeks a broad overview of a topic, including its major dimensions, contexts, or themes. |
| `facet-drilldown` | Targets a specific subtopic, population, mechanism, practice, or consequence within a broader subject. |
| `named-entity-lookup` | Seeks information about a specifically named person, organization, product, place, law, program, or event. |
| `fact-or-claim-verification` | Seeks evidence establishing whether a stated fact, interpretation, or claim is accurate. |
| `disambiguation` | Distinguishes among meanings, interpretations, entities, periods, or uses of potentially ambiguous terms. |
| `exact-phrase-or-quote` | Seeks documents containing an exact phrase, quotation, wording, or fixed expression. |
| `quantitative-evidence-seeking` | Seeks numerical values, measurements, rates, costs, thresholds, statistics, or quantified comparisons. |
| `relational-cooccurrence` | Seeks entities or concepts occurring together in a specified relationship, association, pathway, or practice. |
| `definitional-or-conceptual` | Seeks definitions, conceptual explanations, meanings, frameworks, or interpretations of an idea or phenomenon. |
| `temporal-or-recency` | Seeks information bounded by a period, historical transition, chronology, change over time, or currentness. |
| `comparative` | Compares alternatives, populations, policies, conditions, periods, strategies, or outcomes. |
| `causal-or-mechanistic` | Seeks explanations of causes, effects, biological mechanisms, processes, or pathways linking phenomena. |
| `procedural-or-recommendation` | Seeks advice, plans, interventions, implementation steps, warnings, or action-oriented guidance. |
| `normative-or-policy` | Explores rights, values, equity, governance, regulation, public policy, or competing policy positions. |

## Backend x query-type matrix (pooled first-surfacer ratio)

Cell = pooled ratio, with `n`=n_queries and `R`=Sigma_returned. **†** flags THIN cells (n_queries < 3 or Sigma_returned < 20) — unreliable.

| query-type | dense | keyword | lucene | ssr | row pooled |
|---|---|---|---|---|---|
| `broad-exploratory` | 0.218 (n10,R78) | 0.222 (n8,R63) | 0.093 (n6,R54) | 0.100 (n5,R40) | **0.170** (n29,R235) |
| `facet-drilldown` | 0.183 (n38,R306) | 0.212 (n29,R222) | 0.119 (n61,R553) | 0.103 (n46,R416) | **0.142** (n174,R1497) |
| `named-entity-lookup` | 0.167 (n4,R30) | 0.212 (n7,R52) | 0.156 (n9,R77) | 0.070 (n15,R128) | **0.129** (n35,R287) |
| `fact-or-claim-verification` | 0.146 (n6,R48) | 0.231† (n2,R13) | 0.111 (n4,R36) | 0.086 (n6,R58) | **0.123** (n18,R155) |
| `exact-phrase-or-quote` | — | — | — | 0.167 (n3,R30) | **0.167** (n3,R30) |
| `quantitative-evidence-seeking` | 0.045 (n5,R44) | 0.096 (n6,R52) | 0.141 (n10,R78) | 0.079 (n4,R38) | **0.099** (n25,R212) |
| `relational-cooccurrence` | 0.083 (n3,R24) | 0.188† (n2,R16) | 0.207 (n6,R58) | 0.125 (n9,R80) | **0.152** (n20,R178) |
| `definitional-or-conceptual` | 0.125† (n1,R8) | — | 0.400† (n1,R5) | 0.067 (n3,R30) | **0.116** (n5,R43) |
| `temporal-or-recency` | 0.100 (n3,R30) | 0.125† (n1,R8) | 0.060 (n5,R50) | 0.100 (n5,R50) | **0.087** (n14,R138) |
| `comparative` | 0.231 (n6,R52) | 0.100† (n2,R20) | 0.125 (n5,R48) | 0.155 (n7,R58) | **0.163** (n20,R178) |
| `causal-or-mechanistic` | 0.227 (n3,R22) | 0.263† (n3,R19) | 0.061 (n11,R98) | 0.109 (n5,R46) | **0.114** (n22,R185) |
| `procedural-or-recommendation` | 0.184 (n10,R76) | 0.198 (n10,R86) | 0.138 (n14,R130) | 0.115 (n10,R96) | **0.155** (n44,R388) |
| `normative-or-policy` | 0.132 (n8,R68) | 0.200 (n5,R40) | 0.060 (n10,R100) | 0.087 (n18,R126) | **0.102** (n41,R334) |
| **col pooled** | **0.169** (n97,R786) | **0.196** (n75,R591) | **0.117** (n142,R1287) | **0.102** (n136,R1196) | **0.135** |

## Best backend per query-type (ranked within type)

For each intent, backends ranked by pooled first-surfacer ratio. `†` = winning cell is THIN (treat as suggestive only). The runner-up is shown to gauge margin.

| query-type | best backend | pooled | n / R | runner-up | note |
|---|---|--:|---|---|---|
| `broad-exploratory` | **keyword** | 0.222 | 8 / 63 | dense 0.218 |  |
| `facet-drilldown` | **keyword** | 0.212 | 29 / 222 | dense 0.183 |  |
| `named-entity-lookup` | **keyword** | 0.212 | 7 / 52 | dense 0.167 |  |
| `fact-or-claim-verification` | **keyword**† | 0.231 | 2 / 13 | dense 0.146 | THIN — suggestive only |
| `exact-phrase-or-quote` | **ssr** | 0.167 | 3 / 30 | (only backend) |  |
| `quantitative-evidence-seeking` | **lucene** | 0.141 | 10 / 78 | keyword 0.096 |  |
| `relational-cooccurrence` | **lucene** | 0.207 | 6 / 58 | keyword 0.188 |  |
| `definitional-or-conceptual` | **lucene**† | 0.400 | 1 / 5 | dense 0.125 | THIN — suggestive only |
| `temporal-or-recency` | **keyword**† | 0.125 | 1 / 8 | dense 0.100 | THIN — suggestive only |
| `comparative` | **dense** | 0.231 | 6 / 52 | ssr 0.155 |  |
| `causal-or-mechanistic` | **keyword**† | 0.263 | 3 / 19 | dense 0.227 | THIN — suggestive only |
| `procedural-or-recommendation` | **keyword** | 0.198 | 10 / 86 | dense 0.184 |  |
| `normative-or-policy` | **keyword** | 0.200 | 5 / 40 | dense 0.132 |  |

### Do the Boolean engines (lucene / ssr) win any intent?

- **exact-phrase-or-quote** -> **ssr** pooled 0.167 (n=3, R=30)
- **quantitative-evidence-seeking** -> **lucene** pooled 0.141 (n=10, R=78)
- **relational-cooccurrence** -> **lucene** pooled 0.207 (n=6, R=58)
- **definitional-or-conceptual** -> **lucene** pooled 0.400 (n=1, R=5) (THIN — suggestive)

## Trajectory-role x backend matrix (pooled first-surfacer ratio)

Secondary cut: does a backend do better on openers vs retries vs pivots? Same pooled metric; `†` = thin cell.

| role | dense | keyword | lucene | ssr | row pooled |
|---|---|---|---|---|---|
| `opening` | 0.179 (n10,R78) | 0.215 (n10,R79) | 0.091 (n10,R88) | 0.122 (n10,R82) | **0.150** (n40,R327) |
| `narrowing` | 0.182 (n22,R170) | 0.230 (n20,R165) | 0.131 (n44,R412) | 0.078 (n30,R282) | **0.141** (n116,R1029) |
| `broadening` | 0.140 (n12,R100) | 0.212 (n8,R66) | 0.159 (n18,R170) | 0.173 (n12,R104) | **0.166** (n50,R440) |
| `retry-after-zero` | — | — | — | 0.100† (n4,R10) | **0.100** (n4,R10) |
| `pivot-to-new-subtopic` | 0.190 (n32,R258) | 0.140 (n23,R171) | 0.100 (n34,R301) | 0.115 (n50,R460) | **0.131** (n139,R1190) |
| `refinement` | 0.139 (n21,R180) | 0.209 (n14,R110) | 0.101 (n36,R316) | 0.070 (n30,R258) | **0.113** (n101,R864) |

## CAVEATS — read before using any number here

1. **Behavioral / agent-relevance, NOT ground truth.** "Committed" means the agent kept the doc in `references`, not that a qrel judged it relevant. The same luna family wrote the queries, judged the commits, and (here) classified the intents — a self-consistency bias inflates whatever the model favours.

2. **Denominator inflation only PARTLY controlled.** Backends issued different query volumes and returned different pool sizes, which biases raw aggregate ratios. Comparing WITHIN a query-type controls for intent mix but NOT for per-cell denominator differences — a backend that returns more docs per query dilutes its own ratio.

3. **Thin cells.** Cells with n_queries < 3 or Sigma_returned < 20 are flagged `†`. Many per-(type x backend) cells are tiny (10 topics x 4 backends); treat flagged cells and any single-backend intent as hypothesis-generating, not conclusive.

4. **Classification is luna-judged.** Types and roles are model labels with a confidence field (in the JSONL); no human adjudication. Mislabels move queries between cells and can swing thin cells.

5. **First-surfacer credit is per topic-backend.** A doc committed in a topic is credited to the first query (in THAT backend's trajectory) to surface it, so ratios are not comparable to a hypothetical union across backends.
