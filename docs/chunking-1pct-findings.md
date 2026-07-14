# chunking-1pct findings — fixed vs paragraph-aware × 256d vs 768d (2026-07-14)

Chunking-strategy cost test on a 1% sample of climbmix-400b-shuffle, run in
the sibling `climbmix-400b-autoresearch` repo (`experiments/chunking-1pct/`
holds the config, scripts, and raw measure JSONs). Copied here because the
storage / latency / timing findings inform index-building decisions for
TREC RAG 2026 (`tasks/custom_index`, `tasks/search_serve`).

## Setup

- **Sample**: first 65 / 6543 parquet shards (pre-shuffled) = 5,499,904 docs (1.01%)
- **Token estimate**: 1 word ≈ 1.3 tokens → 1024-tok chunk = 787 words, 128-tok overlap = 98 words
- **fixed**: sliding window 787 words, step 689 (98-word overlap)
- **para**: pack whole `\n\n`-paragraphs ≤787 words; oversized paragraph cut at last
  single `\n` → last sentence punctuation → hard cut (no overlap). Lossless (validated).
- **Encode**: jina-embeddings-v5-text-nano, 768d native fp32 on disk (bf16 compute),
  max_seq_len 512, document prompt
- **Matryoshka**: post-encode truncation to 256d + L2 renorm (`truncate_dim: 256`);
  768d = same encodes, no truncation
- **Index**: DiskANN disk, mips, R=64, L_build=100, PQ 32 B/vec, 64 build threads
- **Latency**: bare `StaticDiskIndex.search()` (no encode, no docstore), 220 agent
  sub-queries, warm-up pass first, beam_width=2, 4 threads, idle box, shared query
  vectors (truncated+renormalized for the 256d indexes)

## Chunking stats

| | fixed | para |
|---|---|---|
| chunks (5.5M docs) | 6,579,507 | 6,553,526 |
| chunks/doc | 1.196 | 1.192 |
| avg words/chunk | 423 | 409 |

## Storage — full artifact chain (1% sample)

| artifact | fixed | para |
|---|---|---|
| source parquet (shared) | 5.55 GiB | ← |
| chunk jsonl | 16.12 GiB | 15.67 GiB |
| raw embeddings 768d fp32 (fbin + docids) | 18.95 GiB | 18.88 GiB |
| **index total, 256d matryoshka** | **9.87 GiB** | **9.83 GiB** |
|   · vectors.fbin 256d | 6.27 GiB | 6.25 GiB |
|   · DiskANN files | 3.46 GiB | 3.45 GiB |
| **index total, 768d (no matryoshka)** | **24.17 GiB** | **24.08 GiB** |
|   · vectors.fbin 768d | 18.82 GiB | 18.75 GiB |
|   · DiskANN files | 5.22 GiB | 5.20 GiB |

256d index = **2.45× smaller** than 768d. (DiskANN files shrink only 1.5× —
the PQ codes (32 B/vec) and graph adjacency don't scale with dim.)

## DiskANN query latency (p50 / p95 ms, 220 queries)

| | fixed 256d | para 256d | fixed 768d | para 768d |
|---|---|---|---|---|
| k=10, L=64 | 8.6 / 10.1 | 7.6 / 9.1 | 9.7 / 11.5 | 10.6 / 11.7 |
| k=100, L=128 | 18.0 / 20.0 | 14.8 / 17.5 | 19.6 / 22.3 | 19.3 / 21.0 |

- **256d is ~10–25% faster than 768d** at the same knobs (smaller node reads).
- **fixed vs para latency is a wash**: para looked ~15% faster at 256d but the
  ordering flips at 768d (k=10) — differences are within graph-build/run noise.
  Neither strategy pays a systematic latency cost.

## Timings (1% sample, measured)

| step | fixed | para | hardware |
|---|---|---|---|
| chunking | ~3 min | ~3 min | 16 CPU workers |
| encode (768d) | 1h 02m | 1h 04m | 8× L40S, ~1,740 chunks/s aggregate |
| matryoshka truncate | ~2 min | ~2 min | single thread, IO-bound |
| index build 256d | 23.0 min | 18.3 min | 64 threads, in-mem (single partition) |
| index build 768d | 39.2 min | 35.9 min | 64 threads, in-mem (single partition) |
| measure (2 configs) | ~2 min | ~2 min | 4 threads |

## Full-dataset estimates (553.2M docs → ~659M chunks, ×100.6)

Anchor: the production climbmix-full build (553M doc-level 768d vectors) measured
**3.2 days encode** (same 8 GPUs) and **28.7 h DiskANN build** (128 threads,
500 GB build-mem, partitioned) — used to sanity-check the linear scalings below.

| step / artifact | estimate | basis |
|---|---|---|
| chunking | ~5 h (16 workers) | linear ×100.6 |
| chunk jsonl | ~1.6 TiB | linear |
| encode | **~4.4 days** on 8× L40S | 659M chunks @ 1,740/s (anchor: 3.2 d for 553M docs ✓) |
| raw embeddings 768d | ~1.9 TiB | linear (anchor: 1.6 TB for 553M ✓) |
| index 256d total | **~0.97 TiB** | linear |
| index 768d total | **~2.4 TiB** | linear |
| index build 768d | **~34 h** | anchor ×1.19 chunks (linear 1% scaling says 65 h; the anchor is the better predictor — 128 threads, real partitioned run) |
| index build 256d | **~17–20 h** | 768d anchor × measured 256d/768d build ratio (0.5×) |

Note: full-scale builds exceed the 64 GB single-partition regime used at 1%, so
build times carry the most uncertainty; storage numbers are exact-linear.

## Takeaways

1. **Chunking strategy (fixed vs para) costs nothing either way** — storage within
   0.4%, latency differences not robust across dims. Choose on retrieval quality.
2. **Matryoshka 256d is the big lever**: 2.45× smaller index, ~10–25% faster
   search, ~2× faster index build — *if* retrieval quality holds (not measured here).
3. Full-corpus chunked pipeline is ~4.4 GPU-days + ~1 CPU-day and ~1 TiB (256d)
   or ~2.4 TiB (768d) of index — feasible on this box.

## Caveats

- Word-based token proxy (spec'd); actual tokenizer counts vary by ±20%.
- Model truncates at 512 tokens, so ~787-word chunks are embedded from roughly
  their first half — fine for storage/latency, NOT a retrieval-quality signal.
- Latency is per-query serial on an idle box; concurrency not tested here.
- Vectors are fp32 on disk (bf16 compute); diskannpy supports no fp16/bf16 —
  further shrink would come from int8 quantization or lower matryoshka dims.
