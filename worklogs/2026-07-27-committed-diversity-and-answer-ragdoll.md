# 2026-07-27 — Committed-doc diversity, best-explanation, credibility & answer-level RAGDOLL

**Goal.** Extend the backend comparison beyond retrieval-quality counts with four
new questions, all grounded on the 30 official research-rubric dev topics:
1. **Within-engine diversity** — are an engine's committed docs richly varied or
   redundant (does it support the answer from many angles)?
2. **Cross-engine complementarity** — do engines surface different evidence; how
   standout is each vs the others?
3. **Credibility / resilience** (no URLs available → content-quality proxies) — does
   an engine commit weak/off-target/repeated content?
4. **Answer-level RAGDOLL** — which engine's *generated answer* best covers the
   rubric (does retrieval quality propagate to the answer)?

This complements `comparison_matrix.md` Cut 1 (retrieval-pool rubric-judge:
keyword ≈ dense > ssr > lucene). **New headline: that retrieval gap largely
WASHES OUT at the answer level for ssr — dense ≈ keyword ≈ ssr on answer rubric
coverage; only lucene lags.** Diversity ≠ value: ssr is the most internally
diverse engine yet commits the weakest evidence.

## Inputs (exact, reproducible)

**Per-engine full agent runs** — 4 isolated single-engine runs over all 30 dev
topics (previously only a mixed run + a 10 *test*-topic pilot existed). Driver:
`tasks/task-comparison/scripts/gen_per_engine_dev30.sh` (sequential, `--skip-existing`,
model `gpt-5.6-luna`). Command per arm:
```
uv run --group aus-agent python src/systems/aus_agent/run.py --all \
  --topics data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv \
  --backend openai --model gpt-5.6-luna \
  --search-backends <semantic|keyword|ssr|lucene_bool> --run-id dev-<dense|keyword|ssr|lucene>-30 --skip-existing
```
Result: 30/30 topics per arm, all with `references`, 0 empty. Committed docs/topic:
dense 13.3, keyword 11.6→(10.8 avg over committed w/text), ssr 11.9, lucene 15.1.
Backends live at run time: dense `index-climbmix-jina-v5-nano.dsync.net`, keyword
`index-climbmix-bm25.dsync.net/api/search`, ssr `index-climbmix-ssr.dsync.net`
(+ local shim :8099), lucene local `tasks/bm25_index/boolsearch/bs.sh` (whole-doc index).

**Committed-doc dataset** — `tasks/task-comparison/scripts/build_diversity_dataset.py`
(run in `tasks/search_serve` env with `.env` sourced for the Pyserini token).
- 1,396 unique committed docids (each unique to one topic), from `metadata.run_id`
  + `references` of the 4 `dev-*-30` runs → `committed_map.json` (qid→engine→[docid]).
- Canonical text: 218 from `rubric-judge/out/pool.json`, 1,178 fetched via Pyserini
  `src/utils/fetch_doc.py`. **0 fetch failures.**
- Embeddings: `jinaai/jina-embeddings-v5-text-nano`, `task=retrieval`,
  `prompt_name=document`, L2-normalized, bf16, `max_seq_len=512`, **dim 768** —
  mirrors the dense index build. Artifacts: `embeddings.npy [1396,768]`,
  `docids.json`, `doc_text.jsonl`, `build_report.json`.

**Judging** (`gpt-5.6-luna`, reuses `rubric-judge/common.py`):
- Committed-doc judge — `rubric-judge/judge_committed.py` (imports `judge.py`'s exact
  prompt; shared cache `out/judgments/`). 1,176 new calls + 220 reused = **1,396
  docs judged, 0 errors** → `{umbrela 0-3, coverage:[{cid,grade 1|2}]}` per doc.
- Answer judge — `rubric-judge/judge_answers.py`: one call per (engine, topic)
  scoring the concatenated `answer[].text` vs the topic's info criteria →
  `{criteria_coverage:[{cid,grade 0-2}], overall 0-3}`. **120 judged, 0 errors.**
  (Length/format/citation-style requirements ignored per spec — information content only.)

Info-criteria filter = positive-weight Explicit/Implicit/Synthesis axes (same as
Cut 1); **568 info criteria** across the 30 topics (`rubrics_info.json`).

## Cut 4a — within-engine diversity (jina-v5 cosine, near-dup ≥ 0.90; mean over 30 topics)

| engine | docs/topic | mean pairwise dist | near-dup rate | Vendi | Vendi/n | unique-contrib | Vendi gain |
|---|--:|--:|--:|--:|--:|--:|--:|
| dense   | 13.2 | 0.584 | 0.022 | 6.60 | 0.519 | 0.866 | 6.69 |
| keyword | 10.8 | 0.579 | 0.004 | 5.83 | 0.563 | 0.803 | 7.47 |
| ssr     | 12.3 | 0.629 | 0.007 | 6.83 | 0.597 | 0.872 | 6.46 |
| lucene  | 14.1 | 0.575 | 0.012 | 6.47 | 0.507 | 0.860 | 6.83 |

Vendi = effective # of distinct docs (exp entropy of the cosine-gram eigenvalues).
**ssr** is the most internally diverse (top pairwise dist, Vendi/n, unique-contrib);
**dense** repeats the most (near-dup 0.022, ~5× keyword) and has ~lowest Vendi/n;
**keyword** is tightest (fewest docs, near-zero redundancy) but least unique.

## Cut 4b — cross-engine complementarity

Committed-docid Jaccard (mean over topics), all pairs tiny → near-disjoint sets:

| pair | Jaccard | pair | Jaccard | pair | Jaccard |
|---|--:|---|--:|---|--:|
| dense·keyword | 0.030 | dense·ssr | 0.023 | dense·lucene | 0.023 |
| keyword·ssr | 0.034 | keyword·lucene | 0.044 | ssr·lucene | 0.032 |

**Union Vendi (all 4 pooled) = 13.30 vs ~5.8–6.8 single-engine.** Pooling engines
~doubles the effective distinct support: the engines are strongly complementary,
not redundant. Every engine (even ssr/lucene) contributes unique rubric criteria
(Cut 4c "unique criteria").

## Cut 4c — rubric best-explanation (which engine supplies the best evidence per criterion)

Best-explainer of a criterion = engine whose committed docs give the top coverage
grade for it; ties share credit. Over 568 info criteria:

| engine | sole wins | co-best share | win-rate | wtd sole-share | unique criteria | cov(≥1) | cov(≥2) |
|---|--:|--:|--:|--:|--:|--:|--:|
| dense   | 39 | 129.4 | 0.228 | 0.070 | 20 | 0.738 | 0.315 |
| keyword | 44 | 134.2 | **0.236** | **0.077** | **22** | **0.749** | 0.309 |
| ssr     | 31 | 106.7 | 0.188 | 0.047 | 12 | 0.664 | 0.273 |
| lucene  | 36 | 118.6 | 0.209 | 0.061 | 15 | 0.708 | 0.291 |

**keyword > dense > lucene > ssr** — consistent with Cut 1. keyword explains the
most criteria best and uniquely covers the most (22).

## Cut 4d — credibility / resilience proxies (no URLs → content-quality proxies)

| engine | mean UMBRELA | low-rel rate (≤1) | highly-rel rate (=3) | near-dup rate |
|---|--:|--:|--:|--:|
| dense   | 1.879 | 0.110 | 0.000 | 0.022 |
| keyword | **1.958** | **0.042** | 0.000 | 0.004 |
| ssr     | 1.784 | **0.192** | 0.002 | 0.007 |
| lucene  | 1.934 | 0.066 | 0.000 | 0.012 |

**ssr commits the weakest evidence** — ~1 in 5 committed docs is off-target/empty
(low-rel 0.192, ~4.5× keyword), lowest mean UMBRELA. **dense repeats content most.**
keyword is the cleanest. So ssr's high "unique contribution" (4a) is substantially
*unique-but-weak* content — the "not resilient / retrieving bad content" signal.

## Cut 4e — answer-level RAGDOLL (weighted rubric coverage of the GENERATED ANSWER)

| engine | answer cov(≥1) | answer cov(full=2) | overall (0–3) |
|---|--:|--:|--:|
| dense   | 0.754 | **0.472** | **1.93** |
| keyword | 0.763 | 0.465 | 1.90 |
| ssr     | **0.769** | 0.457 | 1.90 |
| lucene  | 0.726 | 0.405 | 1.67 |

**THE key finding — retrieval quality does NOT fully propagate.** At the *committed-doc*
level ssr is clearly worst (4c/4d); at the *answer* level **dense ≈ keyword ≈ ssr**
(overall 1.90–1.93, partial cov 0.75–0.77) and only **lucene lags** (1.67). The LLM
synthesizes competent answers even from ssr's noisier/diverse evidence — the
retrieval gap washes out for ssr but NOT for lucene, whose retrieval is weak enough
to drag the answer down.

## Findings

1. **Engines are strongly complementary** (docid Jaccard ≤0.044; union Vendi 13.3 ≈
   2× single). Multi-engine retrieval enriches support; it does not pile on dups.
2. **Diversity ≠ value.** ssr is the *most* internally diverse yet the *weakest* on
   coverage/relevance — its distinct content is often unique-but-off-target.
3. **LLM synthesis compensates for weak retrieval — up to a point.** ssr's answers
   match keyword/dense despite worse committed docs; lucene is weak enough that its
   answers still suffer. So on *answers*, **dense ≈ keyword ≈ ssr > lucene**.
4. **keyword is the retrieval-quality leader** (best-explanation, cleanest evidence,
   least redundancy) on the fewest docs; dense trades relevance for recall (most
   near-dups).

## Decision refinement (vs comparison_matrix.md)

- Retrieval ground truth unchanged: **keyword ≈ dense > ssr > lucene** (Cut 1/4c/4d).
- **New:** on *answer* quality, **ssr is NOT a laggard — it ties keyword/dense; lucene
  is the sole laggard.** ssr earns its ensemble slot more than lucene does: its
  diverse (if noisy) evidence yields answers the LLM covers well.
- Keep the routed-Boolean stance, but **prefer ssr over lucene** as the Boolean arm:
  ssr's complementarity + answer-level parity beat lucene's weak-retrieval-and-answer.

## Artifacts & cost

- Metrics: `data/task-comparison/diversity/{diversity_metrics,committed_analysis}.{md,json}`,
  `answer_quality.json`, `build_report.json`, `committed_map.json`, `doc_text.jsonl`,
  `embeddings.npy`, `docids.json`.
- Scripts: `tasks/task-comparison/scripts/{gen_per_engine_dev30.sh,build_diversity_dataset.py,diversity_metrics.py}`,
  `tasks/task-comparison/rubric-judge/{judge_committed,score_committed,judge_answers}.py`.
- Judgments cached (resumable): `rubric-judge/out/judgments/` (committed docs),
  `rubric-judge/out/answer_judgments/` (answers).
- Cost: generation 4×30 runs ≈ 12.5M input + 0.37M output tok (`gpt-5.6-luna`);
  judging 1,176 committed + 120 answer = **1,296 new luna calls, 0 errors**
  (220 committed docs reused from the Cut-1 cache).

## Gotchas (keep out of future debugging time)

- **`fetch_doc` needs `PYSERINI_API_TOKEN` in the process env.** The `custom_index`
  subprocess did not inherit it → all 1,178 fetches failed *silently* (report showed
  n_failed=1178) and clobbered a good build. Fix: `set -a; source .env; set +a` before
  `uv run`, or run in an env whose script calls `load_dotenv`. Always check
  `build_report.json:n_failed==0` before trusting the dataset.
- **Two builds writing the same output dir race.** A sub-agent build + my build both
  targeted `diversity/`; interleaved writes produced a mixed set. Run ONE builder;
  verify row-count == len(docids) == doc_text lines and 0 NaN/zero-rows after.
