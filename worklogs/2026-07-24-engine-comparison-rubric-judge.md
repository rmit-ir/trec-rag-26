# 2026-07-24 — Engine comparison: rubric-grounded LLM-judge cut, and the routed-Boolean decision

## What this session did

Closed out the multi-engine retrieval-comparison study with its **ground-truth
cut**: a rubric-grounded LLM-as-judge run over 30 official research-rubric dev
topics, four backends each, judged by luna (`gpt-5.6-luna`) for UMBRELA 0–3 +
per-criterion rubric coverage. Then reconciled that ground-truth cut against the
two earlier **behavioral** cuts (within-SSR selection-ratio, backend×intent
commit-ratio taxonomy) and turned the whole thing into a decision about whether
and how to keep a Boolean engine.

**Thesis:** all three independent cuts agree. The natural-language engines
(keyword, dense/semantic) are the generalists that win aggregate multi-facet
research retrieval; the Boolean engines (ssr, lucene) are niche precision
instruments. The rubric-judge cut — which aggregates over broad, multi-facet
topics and therefore rewards recall/coverage — does not surface Boolean's
per-intent precision wins at the topic level, but the taxonomy cut shows those
wins are real for specific query intents. **Decision: do not use Boolean as a
primary/default engine (keyword+dense dominate); DO keep it as a ROUTED tool for
the intents where it demonstrably wins** (exact phrase / quote → ssr; required
co-occurrence & quantitative evidence → lucene). This is exactly the routed
follow-up the earlier free-choice test flagged as unanswered — now grounded in a
qualitative-judge cut and a per-intent behavioral cut, not guessed.

Nothing was re-run in this session; this is synthesis over three already-final
analyses. Deliverables: this worklog, and a refresh of
`data/outputs/engine-comparison/comparison_matrix.md` to lead with the grounded
4-way result.

---

## The four backends

| backend | stack |
|---|---|
| **semantic** (dense) | Jina-v5 DiskANN over full ClimbMix |
| **keyword** | hosted BM25 bag-of-words OR (`BagOfWordsQueryGenerator`, strips Boolean ops) |
| **lucene** (`lucene_bool`) | full Lucene query-parser (`+must`/`-not`/`"phrase"`/proximity) over the same BM25 index |
| **ssr** | Cottontail fork — 26 stemmed SimpleWarren burrows + `MultiShardSearchEngine`, server-side case-fold, paragraph-aware evidence bands (the current fork arm `cmp-ssr-fork-v2`, not the retired Hazel SSR) |

"NL engines" = keyword + dense. "Boolean engines" = lucene + ssr.

---

## Cut 1 (GROUND TRUTH) — rubric-grounded LLM-judge

Artifact: `data/outputs/engine-comparison/rubric-judge/out/rubric_judge_matrix.md`
(+ `.json`). Pipeline code: `data/outputs/engine-comparison/rubric-judge/`
(`rubric_prep.py` → `gen_subqueries.py` → `retrieve.py` → `judge.py` →
`score.py`, plus `backfill_semantic.py`).

### Method — exactly what was measured

- **Topics:** 30 dev topics (ids listed in the artifact header), each carrying
  official labels domain / conceptual_breadth / logical_nesting / exploration.
- **Rubric filter (`rubric_prep.py`):** keep ONLY criteria whose axis is in
  `{Explicit Criteria, Implicit Criteria, Synthesis of Information}` AND whose
  weight > 0. This drops all Communication / Instruction / Citation / Misc axes
  and every negative-weight penalty criterion. The survivors are the
  **information requirements** a retrieved pool must cover. Each gets a stable
  0-based `cid`.
- **Retrieval unit = MULTI SUB-QUERY per engine, NOT a single query and NOT the
  full agent trajectory.** For each topic, luna produces 3–6 engine-agnostic
  sub-needs covering the criteria, and for each sub-need writes FOUR queries —
  one per engine, in that engine's native idiom (semantic NL / keyword bag /
  ssr GCL / lucene query-parser). The per-engine query-writing guidance is
  lifted **verbatim** from `src/tools/search_tool.py` (the `_NL`/`_GCL`/
  `_LUCENE` guidance + `ENGINE_INFO` blurbs) so the four translations are
  competent and fair across engines. An engine's pool for a topic is the
  **union of its per-sub-need k=10 result lists**.
- **Judge (`judge.py`):** each UNIQUE (topic, doc) is judged ONCE by luna
  (`gpt-5.6-luna`), deduped across engines/sub-needs so relevance is a property
  of (topic, doc). Strict JSON out: `{"umbrela": 0-3, "coverage": [{cid, grade
  1|2}]}` — umbrela = holistic 0–3 relevance; coverage lists only criteria the
  doc supplies evidence for (grade 1 = partial, 2 = full, omitted = 0). Judge
  told to score ONLY on the shown doc text (6000-char cap), no outside
  knowledge. Judgments cached per-doc → resumable.
- **Metrics (`score.py`), per (topic, engine), then mean over topics:**
  - **coverage (lenient / strict)** = Σ weight of info criteria covered by ≥1 of
    THAT engine's surfaced docs / Σ weight of all info criteria. Attribution is
    by provenance — a doc counts for an engine only if that engine surfaced it.
    lenient = some covering doc graded ≥1; strict = graded ≥2.
  - **mUMBRELA** = mean holistic 0–3 over the engine's unique judged docs.
  - **nDCG@10** = per-sub-need (UMBRELA as gain, ideal = best ordering of the
    same retrieved set), averaged over the engine's sub-needs.

### Methods caveat — dense outage + resumable re-run

The dense (semantic) server was **502-down during the first full 30-topic run**,
so several topics had empty/errored semantic sub-needs. It was re-run
**dense-only** with `backfill_semantic.py`, which:

- reuses the already-generated `subqueries.json` (queries NOT regenerated),
  re-fetches ONLY the `semantic` engine at k=10 with full text;
- MERGES into `pool.json` (adds new docids, never overwrites existing text),
  REPLACES that topic's `semantic` provenance + `retrieved_raw` entries, and
  leaves **keyword / ssr / lucene provenance byte-for-byte intact**;
- refuses to touch any topic whose semantic arm is already complete (unless
  `--force`), so a stray run can't clobber good data, and it NEVER calls any
  engine other than semantic.

Integrity check after backfill: all 30 topics now have semantic docs; the
keyword / ssr / lucene per-topic doc counts in the matrix are **unchanged** from
the pre-outage run (they were never re-fetched). So the corrected 4-way
aggregate below rests on a clean semantic arm with the other three arms verified
untouched.

### Corrected 4-way aggregate

| engine | cov(lenient) | cov(strict) | mUMBRELA | nDCG@10 |
|---|--:|--:|--:|--:|
| **keyword** | **0.913** | **0.545** | **1.805** | **0.964** |
| **semantic** (dense) | 0.902 | 0.464 | 1.799 | 0.958 |
| ssr | 0.836 | 0.388 | 1.548 | 0.908 |
| lucene | 0.774 | 0.326 | 1.371 | 0.906 |

**Ranking: keyword ≈ dense (tie) > ssr > lucene.** Keyword is marginally ahead
of dense on every column, but the two NL engines are effectively a tie on
lenient coverage / mUMBRELA / nDCG. The one place they visibly separate is
**cov(strict): keyword 0.545 vs dense 0.464** — keyword's surfaced docs are more
often judged *fully* (grade ≥2) relevant, not just partially. Both NL engines
clear both Boolean engines on every metric.

### By-label highlights (lenient coverage / mUMBRELA)

- **exploration:** on **High-exploration** topics (n=5) the Boolean engines fall
  off hardest — lucene cov 0.672 / mUMBRELA 1.194, ssr 0.755 / 1.418, vs
  keyword 0.883 / 1.782 and dense 0.842 / 1.763. Broad open-ended needs are
  where required-term Boolean is weakest.
- **conceptual_breadth:** the single **High-breadth** topic is the starkest
  cell — lucene mUMBRELA 0.775, ssr 1.275 vs dense/keyword ~1.84.
- **domain:** Boolean sags most on **AI & ML** (lucene cov 0.686 / mUMBRELA
  1.101), **Hypotheticals & Philosophy**, and **Technical Documentation**;
  it is closest to NL on **General Consumer Research**, **Other**, and
  **Current Events** cov (though still behind on mUMBRELA).
- **logical_nesting:** the NL>Boolean gap is roughly flat across Shallow /
  Intermediate / Deep — nesting is not where Boolean recovers.

### By rubric-axis highlights (mean per-axis lenient coverage)

| axis | semantic | keyword | ssr | lucene |
|---|--:|--:|--:|--:|
| Explicit Criteria | 0.947 | 0.934 | 0.859 | 0.808 |
| Implicit Criteria | 0.912 | 0.931 | 0.831 | 0.786 |
| Synthesis of Information | 0.841 | 0.823 | 0.755 | **0.644** |

**Boolean is weakest on the Synthesis-of-Information axis** (lucene 0.644 — the
lowest cell in the table). Synthesis criteria demand connecting evidence across
a doc / across sub-needs; required-term Boolean, which rewards exact lexical
overlap, is least suited to it. The NL engines lead every axis, with the gap
widening from Explicit → Synthesis.

---

## Cut 2 (BEHAVIORAL) — backend×intent commit-ratio taxonomy

Artifact: `data/outputs/engine-comparison/commit_ratio_by_type.md` (+ taxonomy
definitions `query_type_taxonomy.md`, per-query labels
`query_classifications.jsonl`).

### Method

Four single-backend agent arms (10 topics each: `cmp-dense`, `cmp-keyword`,
`cmp-lucene`, `cmp-ssr-fork-v2`), 450 queries total. luna induced a **14-type
engine-agnostic intent taxonomy** and classified every query **with its full
topic-backend trajectory in context** (every prior query + hit count), so
openers / retries / pivots are distinguished. Metric = **first-surfacer commit
ratio**: for each query Q, `fs_committed` = docids Q was the FIRST query in its
topic-backend trajectory to surface AND that ended up in the topic's final
committed `references` set; cell **pooled ratio = Σ fs_committed / Σ returned**.
THIN cells (n_queries < 3 or Σ_returned < 20) flagged.

### Headline (col-pooled, first-surfacer ratio)

keyword **0.196** > dense **0.169** > lucene **0.117** > ssr **0.102**.
Keyword strongest overall, consistent with Cut 1.

### Best backend per intent — the niche Boolean wins

Keyword wins most intents (broad-exploratory, facet-drilldown,
named-entity-lookup, procedural, normative, and thin fact-verification/temporal/
causal), dense wins comparative. But the **Boolean engines own specific
intents**, and the non-thin ones are the load-bearing evidence for routing:

| intent | best backend | pooled | n / R | runner-up | thin? |
|---|---|--:|---|---|---|
| `exact-phrase-or-quote` | **ssr** | 0.167 | 3 / 30 | (only backend used) | no |
| `quantitative-evidence-seeking` | **lucene** | 0.141 | 10 / 78 | keyword 0.096 | no |
| `relational-cooccurrence` | **lucene** | 0.207 | 6 / 58 | keyword 0.188 | no |
| `definitional-or-conceptual` | lucene | 0.400 | 1 / 5 | dense 0.125 | **THIN** |

The first three are non-thin and are the intents the routing decision leans on:
**ssr for exact phrase/quote; lucene for required co-occurrence and quantitative
evidence.**

### Cross-engine confound (why this cut is only within-engine/within-type)

The col-pooled ranking is **confounded by denominator inflation**: Boolean arms
run more and wider probes (ssr 136 / lucene 142 searches vs keyword 75), so they
return ~2× more docs per committed doc, mechanically depressing their ratio.
Comparing WITHIN an intent controls for intent mix but NOT for per-cell
denominator differences. So this cut is a hypothesis generator for per-intent
routing, not a cross-engine quality verdict — that's what Cut 1 provides.

---

## Cut 3 (BEHAVIORAL) — within-SSR selection-ratio by query shape

Artifact: `data/outputs/engine-comparison/selection_ratio_by_type.md`
(code `selection_ratio.py`).

### Method + finding

Run `cmp-ssr-fork-v2`, 136 queries. For each SSR query, `sel_ratio =
fs_committed / returned` (novelty-corrected first-surfacer). Ranked by pooled
first-surfacer productivity **within SSR's own trajectories**:

| shape bucket | pooled |
|---|--:|
| phrase-bearing | **0.116** |
| multi-AND | 0.107 |
| anchor+OR | 0.097 |
| other | 0.081 |

Tag axis: entity-bearing 0.112, phrase-bearing 0.111 > OR-anchored 0.097.
**Inside SSR, the most productive query shapes are exactly phrase-bearing and
entity/co-occurrence queries** — the same fact-heavy/exact-phrase niche Cut 2
and Cut 1 point at. Strictly within-engine (Caveat 1 in the artifact); the
appendix cross-backend baseline table is confounded by the same denominator
inflation as Cut 2 (SSR pooled 0.102 lowest, but its absolute fs-committed count
122 exceeds keyword's 116 — pure denominator).

---

## Reconciliation — why all three agree

- **Cut 1 (ground truth, coverage-oriented):** aggregating over broad
  multi-facet research topics rewards recall. NL engines cover more of each
  topic's rubric, so keyword ≈ dense win everywhere; Boolean's per-intent
  precision doesn't surface at the topic level and it's weakest exactly where
  synthesis/exploration/breadth demand recall.
- **Cut 2 (behavioral, intent-resolved):** slice the same behavior by intent and
  Boolean's precision wins DO appear — ssr owns exact-phrase, lucene owns
  quantitative-evidence + relational-cooccurrence.
- **Cut 3 (behavioral, within-SSR shape):** SSR's own most-productive query
  shapes are the phrase/entity/co-occurrence shapes — the mechanism behind
  Cut 2's per-intent wins.

The three cuts are not in tension: Cut 1 says "as a generalist, Boolean loses";
Cuts 2 & 3 say "for specific precision intents, Boolean wins." Both are true
because the rubric-judge aggregate averages over broad topics that never isolate
those intents.

---

## DECISION

- **Do NOT use Boolean as a primary/default engine.** On the ground-truth
  rubric-judge cut keyword ≈ dense dominate on coverage, mUMBRELA, and nDCG, and
  Boolean is weakest exactly where broad research retrieval lives (synthesis
  axis, high-exploration / high-breadth topics). As a passive free-choice
  add-on the agent also barely reaches for it (see the earlier free-choice test
  below).
- **DO keep Boolean as a ROUTED tool** for the intents where it demonstrably
  wins in the taxonomy cut:
  - **exact phrase / quote → ssr** (owns `exact-phrase-or-quote`);
  - **required co-occurrence & quantitative evidence → lucene** (owns
    `relational-cooccurrence` and `quantitative-evidence-seeking`).
- This is the **routed follow-up the free-choice test explicitly flagged**. That
  test showed the agent, given NL backends and no routing guidance, picks
  Boolean ~0.8% (ssr) / ~10% (lucene) of the time for no measurable marginal
  gain — a fair test of *spontaneous adoption*, not of Boolean's *ceiling when
  routed*. This session grounds the routing target: we now know **which
  intents** to route (from Cut 2) and that Boolean isn't a viable default (from
  Cut 1), rather than guessing. Implementing the router (a directive
  tool-guidance rule mapping those intents to ssr/lucene) is the concrete next
  step.

---

## Caveats (apply to the whole study)

1. **luna-judge, not human qrels.** Cut 1's relevance labels come from
   `gpt-5.6-luna`, not TREC qrels — an LLM-judge proxy for ground truth. Treat
   the coverage/mUMBRELA/nDCG numbers as judge-grounded, not human-adjudicated.
2. **Multi-sub-query fairness rests on luna's per-engine translations.** Cut 1
   compares engines on luna-written sub-queries; fairness depends on each
   engine getting a competent native-idiom translation. That's mitigated by
   lifting the query-writing guidance verbatim from the production
   `search_tool.py`, but the translation quality itself is a luna judgment.
3. **Behavioral cuts (2 & 3) are confounded cross-engine.** "Committed" = the
   agent kept the doc as evidence, not that a qrel judged it relevant, and the
   same luna family wrote / judged / classified — a self-consistency bias.
   Denominator inflation (Boolean runs more/wider probes) makes the raw
   cross-engine ratios unfair; these cuts are only clean **within an engine** or
   **within an intent type**, and are hypothesis generators, not verdicts.
4. **Small N in the behavioral cuts.** 10 topics / 136–142 queries per arm; many
   per-(intent×backend) cells are tiny — the routing decision leans only on the
   **non-thin** Boolean-winning cells.

---

## Artifacts referenced

- `data/outputs/engine-comparison/rubric-judge/out/rubric_judge_matrix.md` (+ `.json`) — Cut 1 ground truth.
- `data/outputs/engine-comparison/rubric-judge/` — Cut 1 pipeline (`rubric_prep.py`, `gen_subqueries.py`, `retrieve.py`, `judge.py`, `score.py`, `backfill_semantic.py`).
- `data/outputs/engine-comparison/commit_ratio_by_type.md`, `query_type_taxonomy.md`, `query_classifications.jsonl` — Cut 2 behavioral taxonomy.
- `data/outputs/engine-comparison/selection_ratio_by_type.md`, `selection_ratio.py` — Cut 3 within-SSR shape.
- `data/outputs/engine-comparison/comparison_matrix.md` — the study's living summary, refreshed this session to lead with the grounded 4-way result.
