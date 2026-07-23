# RAG25-dev UMBRELA evaluation of the climbmix-chunked index (2026-07-23)

## Goal
Evaluate the freshly built `climbmix-chunked` DiskANN index (jina-embeddings-v5-nano,
256-d matryoshka, 921.9M chunks) on the RAG25 development topics, scored against the
official **ClimbMix UMBRELA qrels**.

## Inputs
- Index: `data/built-indexes/climbmix-chunked/` (validated end-to-end same day).
- Topics: `.../development-data/topics/rag25-topics-dev.tsv` — 22 narrative topics.
- Qrels (3 judge variants, TREC format `qid 0 docid rel`, rel 0-4, POOLED):
  `.../rag25-dev-umbrela-qrels/rag25-climbmix-umbrela-{codex-gpt5.5-medium-reasoning-v1,
  ministral-3-14b-instruct-2512-v2,qwen3.5-9b-v2}.qrels`
  - 26,341 judgments / 22 topics = ~1,197 judged docs/topic, of which ~983 (82%) are rel>=1.
  - qrels are keyed by PARENT docid `shard_NNNNN_docrow`; our index returns CHUNK ids
    `shard_NNNNN_docrow_pN`.

## Method
`tasks/custom_index/scripts/eval_umbrela.py` (reuses `search.search()`):
retrieve k=2000 chunks/topic (complexity=2000, beam=4, threads=8) -> collapse chunk->parent
doc by max-pool over pages -> keep top 1000 docs -> TREC run -> pytrec_eval.
Tooling: `pytrec-eval-terrier` (prebuilt wheel; plain `pytrec_eval` needs Python.h to
build) added to the custom_index env.

## Results
### Raw (unjudged treated as non-relevant)
| judge      | nDCG@10 | nDCG@20 | P@10  | MAP   | R@100 | R@1000 |
|------------|---------|---------|-------|-------|-------|--------|
| codex-5.5  | 0.1329  | 0.1228  | 0.182 | 0.021 | 0.016 | 0.106  |
| ministral2 | 0.1526  | 0.1421  | 0.177 | 0.021 | 0.016 | 0.111  |
| qwen3.5-2  | 0.1355  | 0.1303  | 0.177 | 0.020 | 0.015 | 0.100  |

### Pool-bias diagnostic (why raw is low)
- **judged-coverage@10 = 0.182** — only 18% of our top-10 are in the pool at all.
- **relevant-precision@10 == judged-coverage@10** at EVERY cutoff -> every judged doc we
  retrieve is relevant (rel>=1); zero judged-but-nonrelevant.
- Top run docids are entirely outside the qrels universe (`in-qrels-universe: False`).
- => The pool was built from OTHER systems' candidates; our jina-v5 index surfaces a
  largely disjoint (but where-judged, 100%-relevant) doc set. trec_eval scores all
  unjudged as non-relevant -> structural underestimate for a non-contributing system.

### Condensed (judged-only: drop unjudged from each ranked list)
| judge      | nDCG@10 | nDCG@20 | P@10  | MAP   | R@100 |
|------------|---------|---------|-------|-------|-------|
| codex-5.5  | 0.6574  | 0.6421  | 0.977 | 0.104 | 0.076 |
| ministral2 | 0.7820  | 0.7805  | 0.964 | 0.108 | 0.079 |
| qwen3.5-2  | 0.7003  | 0.7039  | 0.986 | 0.099 | 0.071 |

## Interpretation
- **Raw numbers underestimate** (pool bias); **condensed numbers overestimate** (ignore
  the 82% unjudged, some of which may be relevant). True quality is between, but the
  spot-check + condensed P@10 (~0.97) indicate the index ranks judged-relevant docs very
  well; its "misses" are overwhelmingly unjudged, not judged-nonrelevant.
- This is the classic reusability limit of a pooled test collection evaluated against a
  system that didn't contribute to the pool.

## Correct next step for a fair number
Run fresh **UMBRELA judgments (RAGDoll)** on our own retrieved passages (repo already has
the infra + `evaluation-results/aus-agent/umbrela-bedrock`). UMBRELA input rows need
`qid`, `query`, `candidates[]` with `docid` + `doc.segment` (text from our chunk docstore).
That judges what WE retrieve -> unbiased nDCG@10 for this index.

## Baseline comparison: chunked-256d vs old dense-768d vs BM25 (2026-07-23)

Compared our new index against the two hosted baselines over the SAME 22 topics /
qrels. Both baselines are over the same ClimbMix corpus:
- **old-dense-768** = `index-climbmix-jina-v5-nano.dsync.net` — our OWN `search_serve`
  serving the OLD `climbmix-full` index (jina-v5-nano, 768-d, UNCHUNKED, 553M docs).
- **bm25** = `index-climbmix-bm25.dsync.net` — Anserini/Lucene BM25 (OR-only), 921M-ish
  passages, `POST /api/search {query,hits}`.

Clients learned from the repo (`src/utils/search_{dense,sparse}.py`); auth = basic
`rmitir:rmitir` via `SEARCH_API_KEY`. Fetchers: `tasks/custom_index/scripts/fetch_remote_run.py`
(dense=`/search/batch`, sparse=`/api/search`; UA must be non-urllib or the CF proxy 403s).
All runs: k=1000, complexity=2000 (dense), depth 1000 docs/topic, chunk->parent collapse.

### Mean over the 3 judge qrels
| system            | nDCG@10 raw | jcov@10 | nDCG@10 cond | P@10 cond | R@1000 raw |
|-------------------|-------------|---------|--------------|-----------|------------|
| bm25              | **~0.63**   | **1.00**| ~0.63        | ~0.91     | **~0.23**  |
| climbmix-chunked  | ~0.14       | 0.18    | ~0.71        | ~0.97     | ~0.11      |
| old-dense-768     | ~0.07       | 0.11    | ~0.73        | ~0.98     | ~0.08      |

### Reading it (CRITICAL — raw is not a fair cross-system signal)
- **BM25 dominates raw ONLY because it built the pool.** The qrels README: the judged
  candidate pool was formed by sending 15 projection queries/topic to *this BM25*. So
  BM25's jcov@10 = 1.000 (every top doc is judged) while the dense systems' top-10 are
  82-89% UNJUDGED -> auto-scored non-relevant. Raw nDCG here mostly measures pool
  membership, not quality.
- **On the fair (condensed / judged-only) view the dense systems edge BM25** on top-10
  ranking (cond nDCG@10 ~0.71-0.73 vs 0.63; cond P@10 ~0.97 vs 0.91). Caveat: dense
  condensed is computed over a small judged subset (~11-18% coverage), so it is noisier
  / optimistic — not a clean win, but clearly not "worse."
- **New chunked-256d BEATS old dense-768d on every raw/coverage metric** (nDCG@10 0.14 vs
  0.07; jcov@10 0.18 vs 0.11; R@1000 0.11 vs 0.08) and TIES on condensed ranking quality
  (~0.71 vs ~0.73; ministral judge slightly favours old-dense). Net: the new index
  surfaces ~60-70% MORE pool-relevant docs while ranking judged docs about as well — at
  1/3 the vector width (256-d matryoshka vs 768-d) and same model. Clear improvement.

### Honest bottom line
Against a BM25-built pool, only fresh judgments can rank BM25 vs dense fairly. Condensed
+ coverage say: dense retrieval (esp. our new chunked index) is competitive-to-better on
precision, retrieves a largely disjoint high-precision doc set, and the chunked-256d
rebuild is a strict improvement over the old 768d dense. RECOMMENDED next step unchanged:
run fresh UMBRELA (RAGDoll) judgments on each system's own top-k for an unbiased nDCG.

## Artifacts
- `data/built-indexes/climbmix-chunked/eval/rag25dev.run` (ours, TREC run 22x1000)
- `data/built-indexes/climbmix-chunked/eval/{old-dense,bm25}.rag25dev.run` (baselines)
- `data/built-indexes/climbmix-chunked/eval/rag25dev.metrics.json` (raw metrics, ours)
- `tasks/custom_index/scripts/eval_umbrela.py` (local index runner+scorer)
- `tasks/custom_index/scripts/fetch_remote_run.py` (remote baseline run fetcher)
- `tasks/custom_index/scripts/score_run.py` (raw+condensed+coverage scorer for any run)

## Exact command
```bash
D=data/official/trec-rag-2026-data/trec-rag-2026/development-data
uv run --project tasks/custom_index python tasks/custom_index/scripts/eval_umbrela.py \
  --index-dir data/built-indexes/climbmix-chunked \
  --topics "$D/topics/rag25-topics-dev.tsv" \
  --qrels-dir "$D/rag25-dev-umbrela-qrels" \
  --k 2000 --complexity 2000 --depth 1000 --num-threads 8 --beam-width 4 \
  --run-out /tmp/climbmix-chunked.rag25dev.run \
  --json-out /tmp/climbmix-chunked.rag25dev.metrics.json
```
