# Query intent taxonomy (luna-induced, engine-agnostic)

**Model:** `gpt-5.6-luna` (luna). **Induced from** 56 queries sampled across the four single-backend arms (`cmp-dense`, `cmp-keyword`, `cmp-lucene`, `cmp-ssr-fork-v2`), spread over topics and backends so the sample mixes NL (dense/keyword) and Boolean (lucene/ssr GCL) phrasings.

The taxonomy is **intent-based**: each type describes what a query is trying to accomplish, independent of NL-vs-Boolean surface form, so like-intent queries can be compared across engines.

## Query types

| id | definition |
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

## Trajectory roles (orthogonal)

A query's role in its topic's ordered search sequence.

| id | definition |
|---|---|
| `opening` | Initiates a topic search by establishing its broad subject or primary question. |
| `narrowing` | Restricts the active topic to a more specific facet, population, condition, or context. |
| `broadening` | Expands coverage after a narrow search by adding related concepts, contexts, or alternative terminology. |
| `retry-after-zero` | Reformulates or relaxes a query after the preceding search returns no documents. |
| `pivot-to-new-subtopic` | Moves from the current topic thread to a distinct subtopic within the broader research task. |
| `refinement` | Improves retrieval for the same subtopic through terminology, constraints, relationships, or query-structure changes. |
