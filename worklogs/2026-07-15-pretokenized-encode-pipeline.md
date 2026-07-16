# Worklog — Pre-tokenized encode pipeline (climbmix-chunked @ 1024)

**Date:** 2026-07-15
**Task dir:** `tasks/custom_index/`
**Goal:** Decouple tokenization from GPU encode to fix GPU under-utilization, and
raise the encoder window from 512 → 1024 tokens (the old 512 was silently
clipping ~30% of chunks). The token store is also reused for later embedding
fine-tuning.

---

## 1. Problem: GPUs only ~70% utilized during encode

Observed on the running 512-token encode (8× L40S, one worker per GPU):

- GPU util 64–72%, **VRAM only ~1.4 GB / 46 GB** per GPU → GPUs starved, not
  compute-bound, not memory-bound.
- Increasing `batch_size` made throughput **worse** (already knew from
  `how-to-build-index.md`: "BATCH=10 is the winner from the streaming bench at
  seq=512").

### Diagnosis (measured)
- `ps -eLo pid,%cpu` showed each encode worker pegged at **94% of a single
  core**, all its other threads idle; box load ~28 on 256 threads (~97% CPU
  idle).
- Root cause: jina v5's custom EuroBERT path tokenizes **single-threaded per
  process**. The 140 M model finishes each GPU batch faster than one CPU core
  can tokenize the next → GPU waits. Bigger batches finish even faster relative
  to tokenization and add padding waste on variable-length input → throughput
  drops. So **batch=10 was the real optimum for the text path**.

### Why pre-tokenize
Move all tokenization off the GPU critical path into a separate CPU-parallel
stage (all 128 cores), store token IDs on disk, then encode GPU-bound with big
length-sorted batches. Bonus: the token store is the input for later
fine-tuning, so the one-time cost is amortized.

---

## 2. Key measurements

Tokenizer / model (`jinaai/jina-embeddings-v5-text-nano`):
- **vocab_size = 128,000** → token IDs need **int32** (int16 can't hold them).
- **`max_position_embeddings = 8192`** (RoPE, theta 1e6) — model supports 8192.
- Prompts: `{'query': 'Query: ', 'document': 'Document: '}`;
  `default_prompt_name = 'document'`.
- **Pooling = last-token** (not mean): `custom_st.py forward()` does
  `seq_len = mask.sum(1)-1; pooled = hidden[arange, seq_len]`, then L2-normalize.
  ⇒ padding amount is irrelevant to the output vector.

True (untruncated) token-length distribution, 12k chunks over 3 shards, with
the `"Document: "` prefix:

| stat | value |
|---|---|
| mean | 486 |
| p50 / p90 / p99 | 472 / 599 / 969 |
| p99.9 / max | 1646 / 3791 |

Fraction of chunks clipped at each cap:

| cap | chunks clipped | tokens lost |
|---|---|---|
| **512 (old run)** | **29.7%** | 6.8% |
| 768 | 3.3% | 1.7% |
| **1024 (chosen)** | **0.78%** | **0.68%** |
| 2048 | 0.09% | 0.26% |

Disk: **14 TB free of 28 TB** on `/mnt/raid10` (=`/scratch/e128356`, symlink,
same pool).

---

## 3. The 512-truncation finding (important correction)

Earlier I said "the model auto-truncates to 512" — **wrong**. Proof from jina's
own `custom_st.py`:

```python
# default when max_seq_length not passed:
self.max_seq_length = max_seq_length or self.config.max_position_embeddings  # -> 8192
def tokenize(self, texts, padding=True):
    return self.tokenizer(texts, max_length=self.max_seq_length,
                          truncation=True, padding=padding, return_tensors="pt")
```

- `truncation=True` is **always on**, but truncates to `max_seq_length`, which
  **defaults to 8192** (no `sentence_bert_config.json` in the repo to override).
- **The 512 was OUR setting** (`--max-seq-len 512`), which silently clipped ~30%
  of chunks. Fixed by using 1024 explicitly.
- Online refs to verify:
  - custom_st.py: https://huggingface.co/jinaai/jina-embeddings-v5-text-nano/blob/main/custom_st.py
  - config.json (max_position_embeddings 8192): https://huggingface.co/jinaai/jina-embeddings-v5-text-nano/blob/main/config.json

---

## 4. Decisions

1. **Encoder window = 1024 tokens.** Covers 99.2% of chunks fully; the rare
   long tail (>1024, 0.78%) is arguably mis-chunked for a "one focused idea"
   embedding, so clipping it at 1024 is consistent with the design. Pass
   `--max-seq-len 1024` **everywhere** (Stage A, Stage B, and query side).
2. **Ragged on-disk storage** (not fixed `[N,1024]` padded). Mean chunk is
   ~486 tokens, so fixed-width padding to 1024 would ~double the store for
   nothing. Ragged costs `sum(real lengths)` regardless of cap ⇒ cap is free.
3. **Discard all 512 work** (chunk corpus stays valid; only the encode changes).

### Ragged store format (per shard, in `.../tokens/`)
| file | dtype | content |
|---|---|---|
| `shard_NNNNN.ids.u32` | int32 | all chunks' token ids concatenated (`sum(len)`) |
| `shard_NNNNN.len.i16` | int16 | `[N]` per-chunk length (cap 1024 < 32767) |
| `shard_NNNNN.docids.txt` | text | one chunk id per line, row order |
| `shard_NNNNN.meta.json` | — | `{n, seq_len, total_tokens, pad_id, prompt, mean_len,...}` |
| `shard_NNNNN.ready` | — | completion marker (resumable) |

Load: `ids = memmap(ids.u32, int32)`, `lens = fromfile(len.i16)`,
`off = concat([0], cumsum(lens))`, chunk k = `ids[off[k]:off[k+1]]`.
Encode reads it **length-sorted** (in-memory argsort, no disk reorder);
fine-tuning reads it **shuffled** — same file, different access order.

Estimated store size: 921.9M chunks × ~486 tok × 4 B ≈ **1.6–1.8 TB**.

---

## 5. Scripts created

- `tasks/custom_index/scripts/tokenize_corpus.py` — **Stage A**. ProcessPool
  over shards (default 128 workers), reproduces jina preprocessing exactly
  (`"Document: " + contents`, `max_length=L, truncation=True`), writes ragged
  store, atomic `.tmp`+rename, per-shard resumable via `.ready`.
- `tasks/custom_index/scripts/encode_pretokenized.py` — **Stage B**. Parent
  splits token shards round-robin across GPUs, one pinned worker subprocess per
  GPU (no watch mode — all tokens exist up front). Worker: load shard, argsort
  by length desc, big dynamic-padded batches, `module.forward({input_ids,
  attention_mask}, task="retrieval")["sentence_embedding"]`. Output
  `.fbin`/`.docids.txt`/`.meta.json` **byte-compatible** with
  `encode_documents.py` so `truncate_vectors.py` + `build_diskann_index.py` are
  unchanged.
- `tasks/custom_index/scripts/verify_pretok.py` — **correctness gate**. Compares
  the pre-tokenized forward path against reference `model.encode(...)`.

## 6. Verification gates (all passed)

- **Equivalence gate** (`verify_pretok.py`, 256 chunks, CPU fp32):
  `cosine min=1.000000 mean=1.000000` — pre-tokenized tokenize+forward is
  bit-identical to `model.encode(prompt_name="document", task="retrieval")`.
- **Ragged round-trip**: reconstructed chunk ids from the store == direct
  tokenization, docids aligned — PASS.
- **Stage B end-to-end** (`verify_fbin.py`, GPU bf16, 300 chunks vs reference,
  matched by docid): `cosine min=0.999892 mean=0.999954` — **PASS**. The
  <1e-3 gap is bf16 batching/padding noise. Full pretokenized path (argsort +
  ragged slice + dynamic pad + forward + fbin write) reproduces model.encode.
- Stage B smoke timing: shard_01000, 141,177 chunks / 575 s = **245 ch/s/GPU**,
  GPU **100% util / 18.6 GB**.

**768-vs-1024 timed comparison: cancelled** — 1024 is decided (completeness),
no need to measure the alternative.

---

## 7. Commands run

```bash
# --- stopped the obsolete 512 pipeline (discard all its work) ---
kill -TERM -1762024 -1762441          # pipeline pgids (chain bash + encode subtree)
# search_serve on :8000 was ALREADY down before this (its PIDs gone; log stops
# after a SIGWINCH at 11:41:36 with no crash trace — cause indeterminate).

# --- Stage A: tokenize all shards -> ragged store @ 1024 (128 cores, ~2h) ---
uv run --project tasks/custom_index python tasks/custom_index/scripts/tokenize_corpus.py \
  --corpus-dir tasks/custom_index/work/climbmix-chunked/corpus \
  --out-dir    tasks/custom_index/work/climbmix-chunked/tokens \
  --model jinaai/jina-embeddings-v5-text-nano \
  --max-seq-len 1024 --workers 128 \
  2>&1 | tee /tmp/climbmix-chunked.tokenize.log

# --- Stage B (planned, after Stage A): GPU-bound encode ---
uv run --project tasks/custom_index python tasks/custom_index/scripts/encode_pretokenized.py \
  --tokens-dir tasks/custom_index/work/climbmix-chunked/tokens \
  --out-dir    tasks/custom_index/work/climbmix-chunked/encoded \
  --model jinaai/jina-embeddings-v5-text-nano \
  --max-seq-len 1024 --batch-size 256 --dtype auto \
  2>&1 | tee /tmp/climbmix-chunked.encode.log
```

---

## 8. Full pipeline plan (4 stages after chunking)

1. ✅ Stop obsolete 512 encode.
2. ✅ **Stage A tokenize** → `work/climbmix-chunked/tokens/`. DONE in **1.66 h**:
   6543 shards, **921,892,634 chunks**, 0.1% truncated @1024, store **1.4 TB**.
3. 🔄 **Stage B encode** (`encode_pretokenized.py`) → `.../encoded/` @ 1024.
   LAUNCHED (task bd5vtxk1j), chained → truncate → build. **All 8 GPUs at 100%
   util / 18.6 GB**, ~245 ch/s/GPU → ~1,960 ch/s aggregate → **ETA ~5–5.5 days**.
4. ⏳ **Truncate 256d** (`truncate_vectors.py`) → `.../encoded-256d/` (~2 h).
5. ⏳ **DiskANN build** (`build_diskann_index.py`) → `data/built-indexes/climbmix-chunked/` (~20–24 h).
6. ✅ **Query side**: `encoder.py` + `search.py` now pin `model.max_seq_length`
   from `encoding_meta["max_seq_len"]` (build_diskann_index.py:142 already
   carries it from the shard meta, which encode_pretokenized.py writes).

### Cleanup
- ✅ Removed stale 512 encodes at `work/climbmix-chunked/encoded/`
  (598 G, 1468 `.fbin`, `max_seq_len=512`) — had to go before Stage B or its
  resume check would wrongly skip those shards.
- `work/climbmix-chunked/corpus/` (1.6 T chunk jsonl) — keep until Stage A done
  (it's the tokenize input), then droppable.

---

## 8b. Throughput measurement (Stage B smoke, 1 GPU)

Smoke: `encode_pretokenized.py` on 1 token shard (shard_01000, 141,177 chunks,
mean_len 385), 1× L40S, batch 256, seq ≤ 1024, bf16.

- **GPU util 100%, VRAM 18.6 GB / 46 GB** (vs old text path: 70% util, 1.4 GB).
  ⇒ the pretokenized path is now GPU-bound, not tokenization-bound. Goal met.
- Rate varies across the shard because we **sort by length descending** (longest,
  most expensive batches first):
  - longest-chunk region (first ~50k): **176 chunks/s**
  - shorter-chunk region (~84k in): **256 chunks/s**
  - shard avg lands ~**220–260 ch/s/GPU** → ~**1,800–2,100 ch/s across 8 GPUs**.
- VRAM headroom to ~46 GB means batch could go to ~384, but at 100% util it's
  already compute-bound, so 256 is fine.

### The seq-len caveat (important — chunks/s is not apples-to-apples)
Old text path: **~230 ch/s/GPU at 70% util, seq 512** (clips 30% of chunks).
New path: ~220–260 ch/s/GPU at 100% util, **seq 1024** (clips 0.78%).

chunks/s looks only ~flat because we **doubled the window (512→1024)** — the
~30% of chunks previously clipped now run their full length (up to 2× compute).
The real work metric is **tokens/s**:

| path | seq | util | ch/s/GPU | ~tok/s/GPU |
|---|---|---|---|---|
| old text | 512 | 70% | 230 | ~107 k |
| pretok (current) | 1024 | 100% | ~240 | ~180 k |

⇒ **~1.6× more actual work/sec** (the saturation win), but spent on the longer
sequences we deliberately stopped clipping rather than on raw chunks/s.

### Speed/quality lever (chosen: 1024)
- **1024** (chosen): clips 0.78%, best completeness, ~3.5–5 day full run.
- **768**: clips 3.3% (p99 is 969) — trims the expensive long tail, meaningfully
  more chunks/s.
- **512**: fastest (pretok @512 would be GPU-bound ~350+ ch/s/GPU) but clips 30%.

Decision: **hold at 1024** for retrieval quality; the trade is now explicit and
measured, not a surprise at day 4. Full-run wall time to be confirmed from the
real 8-GPU launch (1-GPU extrapolation is imperfect).

## 8c. Docstore (chunk_id → text), built in parallel with encode

Decision (architecture): the docstore is the index's **complement** — it maps
the *same id the vector index stores* to text. Our index rows are chunk ids, so
the docstore is `chunk_id → chunk text`. No re-chunk-at-serve, no dependency on
the doc docstore. chunk_id + text exist the moment chunking finishes (before the
encode's internal length-sort), so the docstore build is a **sibling of encode**,
run concurrently on CPU.

The existing `build_docstore.py` is positional (docid `<stem>_<row>` == row-th
record) and parquet-sourced — chunk ids aren't row-addressable and the encode
reorders rows, so serve must resolve by the chunk-id *string*. New script:

- **`build_chunk_docstore.py`** — reads chunk jsonl, writes per shard
  `.bin` (zstd-9 frames) + `.offsets.bin` (uint64[N+1]) + **`.ids.bin`**
  (chunk ids in row order) + manifest (`keyed_by=chunk_id`,
  `shard_of_rule=chunk_id.rsplit('_p',1)[0].rsplit('_',1)[0]`). Superset of the
  existing format so the serve `FlatShardDocStore` extends cleanly later
  (add: derive shard from id, load `.ids.bin` → `{id:row}` dict, then positional
  read). Reader extension deferred to the serve-endpoint work.
- **Verified**: round-trip PASS — `chunk_id → zstd-decompress` == corpus text,
  incl. deep rows and multi-page docs (`..._p1..p6`). zstd-9 ratio 2.91×.
- **Running**: task bhdltlzj1, 48 CPU workers, ~640 kr/s, ETA ~23 min, output
  straight into final `data/built-indexes/climbmix-chunked/docstore/` (~575 GB:
  `.bin` ~550 G + `.ids.bin` ~19 G + offsets ~7 G).

## 8d. Space cleanup + README

- **Deleted (3.2 TB freed, 13→16 TB free):** `work/climbmix-full/` (old
  unchunked run intermediates; its built index at `data/built-indexes/climbmix-full`
  is untouched) + `work/{smoke,climbmix-smoke}/`.
- **Kept:** `work/climbmix-chunked/corpus/` (1.6 T — chunk-text source for the
  docstore; deletable *after* docstore validated), `tokens/` (1.4 T — encode
  input + FT asset), parquet (559 G — true source).
- **Later:** `data/built-indexes/climbmix-full/` (2.3 T incl 503 G doc docstore)
  once the chunked index is live.
- **Projected peak add for the rebuild:** ~4.5 TB (encoded ~2.8 T + 256d ~0.94 T
  + built index ~1.1 T). Comfortable against 16 TB free.
- **README:** added a pipeline diagram (stages + input/output shapes + the
  parallel encode ∥ docstore branches) to `how-to-build-index.md`.

## 9. Open items / notes
- The token store bakes in `"Document: "` prefix + max_len 1024. Correct for
  retrieval FT with the same model; a different scheme would need re-tokenize
  (~2h, cheap).
- The fat tail (max 3791 tokens) means the chunker occasionally fails to split
  a giant paragraph — worth a look later; 0.78% is rare and clipping handles it.
- search_serve (old climbmix-full index) is currently DOWN — restart if the old
  index needs to be queryable during the rebuild.
