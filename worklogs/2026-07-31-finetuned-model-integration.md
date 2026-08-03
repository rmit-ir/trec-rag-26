# Fine-tuned jina-v5-nano-256d: pipeline integration + single-shard test (2026-07-31)

## Goal
Wire the fine-tuned embedding model
**`RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d`** (private HF repo) into the
custom-index embed/index pipeline as the **new default model**, make the dense
search server able to load it, then prove it end-to-end by indexing a single
test shard on **CPU only** (another user was on the GPUs) and judging the top-10.
Full-corpus encoding is intentionally **not** started — awaiting go-ahead.

## Model facts (probed on CPU, HF_TOKEN from repo .env)
- **Tokenizer byte-identical to the base** `jinaai/jina-embeddings-v5-text-nano`
  (same vocab sha, same sample token ids, pad_id 128004). => the existing
  pre-tokenized store (`work/climbmix-chunked/tokens/`, 6543 shards, prompt
  `"Document: "`) is **reusable as-is — no re-tokenize.**
- **Native output dim = 256** (`model.truncate_dim = 256`) => **no matryoshka
  truncate step** (TRUNCATE_DIM stays 0; the model truncates internally).
- Prompts: `{query: "Query: ", document: "Document: "}`, default `document`.
  Document prompt matches the token store's baked-in prompt.
- **Architecture changed shape vs the base.** It is now a *standard*
  Sentence-Transformers pipeline:
  `[0] Transformer -> token_embeddings(768) | [1] Pooling(lasttoken,
  include_prompt) -> sentence_embedding(768) | [2] Normalize`, plus
  `truncate_dim=256` applied by `encode()` AFTER the pipeline. The base model
  used jina's *custom single module* whose `forward(feats, task=...)` returned
  `"sentence_embedding"` directly. The old Stage-B encoder called exactly that
  and now raises `KeyError: 'sentence_embedding'` on the fine-tune.
- Exact `encode()` transform (verified equal to 1.3e-7):
  `features -> chain all 3 modules -> sentence_embedding(768, unit) ->
  slice[:256] -> L2-renormalize`.

## Code changes
- **`tasks/custom_index/scripts/env_util.py`** (new): stdlib `.env` loader
  (`load_repo_env`) that sets `HF_TOKEN` from the repo `.env` if absent (never
  prints it); `DEFAULT_MODEL` constant = the fine-tuned repo id.
- **`tasks/custom_index/scripts/st_embed.py`** (new): `embed_features(model,
  feats, task)` runs the full ST module pipeline on a pre-tokenized features
  dict, then applies `truncate_dim` slice + L2-renorm — reproduces `encode()`
  exactly and also works for a single-module model (passes `sentence_embedding`
  through). `resolve_out_dim(model)` returns the post-truncation dim.
- **`encode_pretokenized.py`**: default `--model` -> fine-tune; `load_repo_env()`
  at import; Stage-B forward now uses `embed_features` (was
  `model[0].forward(...)["sentence_embedding"]`); output dim from
  `resolve_out_dim` (256); feats moved to model device.
- **`verify_pretok.py`, `tokenize_corpus.py`, `encode_documents.py`,
  `search.py`**: `load_repo_env()` + (where applicable) default `--model` ->
  fine-tune. `verify_pretok` now exercises the same `embed_features` path.
- **`index_pipeline.sh`**: `MODEL` default -> fine-tune (TRUNCATE_DIM stays 0).
- **`tasks/search_serve/scripts/env_util.py`** (new, self-contained copy) +
  `load_repo_env()` wired into `server.py` preamble and `cli.py`, so the server
  can pull the private model. The query model itself still flows from the served
  index's `encoding_meta.json` (index-driven), so pointing the server at a
  new-model index makes it encode queries with the fine-tune automatically.

## Correctness gate
`verify_pretok.py --model <fine-tune> --shard shard_00000.jsonl --n 128
--max-seq-len 1024` (CPU): **cosine min=mean=1.000000** (pre-tokenized
right-padded batch path == `model.encode(prompt_name=document,
task=retrieval)`). Proves the reused token store + new embed transform yield
faithful vectors.

## CPU throughput (shard_00000, longest chunks first = worst case)
- float32, 48 threads: **7 ch/s** on the 1024 longest chunks.
- bf16 (AMX), 64 threads: **13 ch/s** on the 2016 longest chunks.
- bf16 is ~1.85x faster and is what a CPU serve uses anyway (encoder auto-picks
  bf16 on amx_bf16). Throughput ~doubles as chunk length drops toward the mean
  (385 tok), so the full 141,807-chunk shard ETA ~60-90 min on CPU.

## Exact commands
```bash
# correctness gate
CUDA_VISIBLE_DEVICES="" uv run --project tasks/custom_index python \
  tasks/custom_index/scripts/verify_pretok.py \
  --shard tasks/custom_index/work/climbmix-chunked/corpus/shard_00000.jsonl \
  --n 128 --max-seq-len 1024

# Stage-B encode of one shard, CPU/bf16 (worker mode, single shard)
CUDA_VISIBLE_DEVICES="" OMP_NUM_THREADS=64 MKL_NUM_THREADS=64 \
uv run --project tasks/custom_index python \
  tasks/custom_index/scripts/encode_pretokenized.py --worker-rank 0 \
  --tokens-dir tasks/custom_index/work/climbmix-chunked/tokens \
  --out-dir   tasks/custom_index/work/climbmix-chunked/encoded-agent-test \
  --model RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d \
  --batch-size 32 --device cpu --dtype bfloat16 --max-seq-len 1024 \
  --total-shards 1 --step-start-epoch 0 --stems shard_00000

# chunk docstore for the same shard
uv run --project tasks/custom_index python \
  tasks/custom_index/scripts/build_chunk_docstore.py \
  --corpus tasks/custom_index/work/climbmix-chunked/_test_corpus_00000 \
  --out    data/built-indexes/climbmix-agent-test/docstore \
  --compression zstd-9 --parallel 8

# build DiskANN (memory) index from the single encoded shard  [TBD after encode]
# retrieval + judge                                            [TBD after encode]
```

## Results
### Encode + build (CPU only, GPUs untouched)
- Encoded `shard_00000` (141,807 chunks) with the fine-tune, bf16, 64 threads,
  in **2707 s (45 min)**, final **52 ch/s** -> `encoded-agent-test/shard_00000.fbin`
  (141,807 x 256, meta records model=fine-tune, query_prompt_name=query).
- Chunk docstore: 141,807 records, 84.5 MB, 2.92x zstd.
- In-memory DiskANN (mips, R=64, L=100): 141,807 pts, avg degree 57, built in 4.6 s
  -> `data/built-indexes/climbmix-agent-test/` (encoding_meta.model = fine-tune,
  dim 256, NO matryoshka_truncated_from -> query encode returns 256-d natively).

### Judgment — fine-tuned model
- **Self-retrieval** (n=40, query = first 18 words of a random chunk, vs 141,807):
  hit@1 **0.62**, hit@10 **0.88**, same-parent hit@10 **0.90**, MRR@10 **0.725**.
- **Topical top-10** (5 generic queries: inflation, vaccines, type-2 diabetes,
  solar panels, DNN training) — all clearly on-topic by reading. => model embeds
  and retrieves correctly end-to-end.

### Comparison vs the base model (before fine-tune), same shard/queries, both 256-d
Reused the EXISTING base encode `encoded/shard_00000.fbin` (768-d) ->
matryoshka-truncate to 256 (`truncate_vectors.py`, the original pipeline) ->
memory index `data/built-indexes/climbmix-base-test/` -> same judge.

| metric | base 256-d | fine-tuned 256-d |
|---|---|---|
| self-retrieval hit@1 | 0.62 | 0.62 |
| self-retrieval hit@10 | 0.93 | 0.88 |
| self-retrieval MRR@10 | 0.731 | 0.725 |
| topical overlap@10 vs other | — | 5-9 / 10 per query |

- Near-tied on the self-retrieval *near-duplicate* proxy (base marginally ahead);
  5-9/10 topical top-10 overlap. Where they differ the fine-tune's swaps look
  reasonable-to-better (e.g. "best practices for training DNNs": ft #1 is a
  hands-on train/evaluate/save chunk vs base's CNN-architectures abstract).
- **Conclusion: the fine-tune works correctly and is on par with base on this
  generic single-shard probe.** This is NOT evidence it is *better* — that needs
  the labelled/dev-topic eval it was trained for. The test's purpose ("is the
  model working correctly") is satisfied: yes.
- Aside: the BASE model's custom `custom_st.py` raises
  `JinaEmbeddingsV5Model has no attribute config_class` on a *second* load in one
  process (jina dynamic-module fragility). The fine-tune's *standard* 3-module ST
  pipeline does not have this issue.

### Sequencing answer for the re-chunk/re-encode brief (§6)
Model is validated => land the fine-tune and the new chunk/metadata layout in the
SAME re-encode pass (~53 GPU-days vs ~106 for two passes).

## Disk state / cleanup (2026-07-31)
Server is not serving; user backed up all data files. Stage sizes:
`corpus` 1.6T (chunked jsonl), `tokens` 1.4T, `encoded` 2.6T (base 768-d),
built indexes: `climbmix-full` 2.3T, `climbmix-chunked` 1.8T; raw parquet
`data/climbmix-400b-shuffle` 559G. **The whole-doc JSONL source
`work/climbmix-full/corpus` (chunking_meta.source_corpus) NO LONGER EXISTS on
this box** -> the parquet is the ONLY unchunked doc source and MUST be kept for
re-chunking (parquet -> prepare_corpus.sh -> whole-doc jsonl -> chunk_corpus.py).
Safe to delete (~6.7T, not inputs to the new-model encode/index/docstore,
backed up): `…/encoded`, `built-indexes/climbmix-full`,
`built-indexes/climbmix-chunked`, `built-indexes/climbmix-smoke`.
Keep: parquet (559G), `tokens` (reusable iff embed text unchanged), `corpus`
(§7 baseline until v2 verified).

## Artifacts
- Index: `data/built-indexes/climbmix-agent-test/` (+ `/docstore`)
- Base comparison index: `data/built-indexes/climbmix-base-test/`
- Encoded test vectors: `…/work/climbmix-chunked/encoded-{agent,base}-test/`
- Probe/judge scripts: `worklogs/assets/2026-07-31-{judge_retrieval,st_embed_probe}.py`

