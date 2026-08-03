# Fine-tune full re-encode: completion, integrity, and the "why is it 2.8× faster?" investigation (2026-08-02)

## What ran
Full re-encode of the ClimbMix chunk corpus with the fine-tuned model
`RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d`, reusing the existing pre-tokenized
store (`work/climbmix-chunked/tokens/`), all 8× L40S, batch 256, seq ≤1024, bf16.
Driver: `tasks/custom_index/scripts/run_ft_index.sh` (Phase 0 preflight → Phase 1
encode → Phase 2 DiskANN disk build). Output vectors:
`work/climbmix-chunked/encoded-ft/`; index: `data/built-indexes/climbmix-chunked-ft/`.

Phase 1 finished in **~44–48 h wall-clock (~2 days)** at **~666 ch/s/GPU shard-average**.

## The concern
The prior *base-model* full encode took **~4–5 days** at **~220–260 ch/s/GPU**
(worklog `2026-07-15-pretokenized-encode-pipeline.md`), with an **identical** config
(batch 256, seq 1024, bf16, 8× L40S). This run is ~2.7× faster with the same config.
User asked: is the fast run legit, and why is it fast?

## Part 1 — the output is legit (not "fast because it skipped/degraded work")
Integrity sweep over the finished `encoded-ft/` (pure file inspection, no model):
- **6543 / 6543 shards present**, total **921,892,634 vectors**.
- Every sampled shard's `fbin` header count **== the token-store per-shard chunk
  count** (exact match on 9 shards incl. shard_00000: 141,807).
- File size == `8 + n*dim*4` for every shard (no truncation); **dim = 256**.
- All rows **finite**, **zero** all-zero rows.
- L2 norms: mean **1.00002**, std **0.0019**, min 0.996 / max 1.004, **100% within
  1e-2** of unit — i.e. correctly normalized to bf16 precision. (A first pass
  flagged "only 29% within 1e-3", which was just a tolerance tighter than bf16
  rounding, not a defect.)
- Code path already verified equal to `model.encode()` to cosine **1.0**
  (`verify_pretok.py`, see 2026-07-31 worklog). The full run uses that exact
  `st_embed.embed_features` path.
Conclusion: complete, correctly-shaped, correctly-normalized vectors. Nothing skipped.

The `global 6540/6009` log line is a cosmetic accounting quirk, not skipped work:
denominator = `len(todo)` (6543 − 534 already-done = 6009 this-run shards),
numerator = `len(glob('*.fbin'))` counts **all** fbins incl. the 534 kept, so it
overshoots. `todo_stems()` only skips a shard when all of `.fbin`+`.docids.txt`+
`.meta.json` exist.

## Part 2 — why 2.8× faster: base runs a runtime LoRA adapter; the fine-tune merged it
Head-to-head on ONE L40S, identical worst-case batch (256 seqs × seq 1024, all-ones
mask, bf16), timing the same forward each model actually uses
(`scratchpad/{model,base}_probe.py`):

| | base `jinaai/jina-embeddings-v5-text-nano` | fine-tune `…-agent-256d` |
|---|---|---|
| ST modules | 1 (jina custom single-module) | 3 (Transformer→Pooling→Normalize) |
| underlying model | `JinaEmbeddingsV5Model` wrapping `EuroBertModel` | `EuroBertModel` (standard HF) |
| attn_implementation | **sdpa** | **sdpa** |
| hidden layers | 12 | 12 |
| **LoRA submodules** | **1512** (`retrieval`, `text-matching`, … via **PEFT at runtime**) | **0 (merged)** |
| params | 238.9 M | 211.8 M |
| peak VRAM (this fwd) | 13.2 GB | 6.9 GB |
| **throughput** (seq1024/batch256/bf16) | **92 ch/s/GPU** | **260 ch/s/GPU** |
| microbench wall-clock: 2560 seqs @ seq1024 | 27.69 s | 9.83 s |
| **full 922M-vector encode, 8× L40S** | **~5 days**¹ (prior base run, ~245 ch/s/GPU avg) | **~48 h ≈ 2.0 days**² |

¹ Prior base full encode was ~4–5 days (worklog `2026-07-15`, ETA-consistent with
its measured ~245 ch/s/GPU avg → 6543 shards × ~576 s ÷ 8 = ~5.4 days).
² Measured this run: the relaunch encoded 6009 shards in **44.24 h**; continuous
full 6543 shards = 6543 × ~212 s ÷ 8 GPUs = **~48 h**. Shard-average ~666 ch/s/GPU
(vs base's ~245) = **~2.7×**, matching the controlled microbench's 2.83×.

**260 / 92 = 2.83×**, matching the run's ~2.7× (666 vs ~245 ch/s). Same backbone,
same SDPA attention, same layer count — so it is **not** an attention-kernel or
"less work / fewer tokens" effect.

Root cause: the base applies its **retrieval LoRA adapter at inference via PEFT** —
1512 adapter submodules across every layer's attn + FFN projections. Each adapted
linear runs the extra low-rank path (`x → dropout → A → B → scale → add`) **plus**
PEFT per-module dispatch, every forward. The base also carries *multiple* task
adapters (retrieval, text-matching, …) → the 238.9 M vs 211.8 M param gap (unused
adapters add params but not forward compute; only the active one costs time).

The fine-tune has the retrieval adapter **merged into the weights** (`W' = W + BA`),
so the forward is a plain dense `EuroBertModel`: no adapter matmuls, no PEFT
dispatch, ~half the VRAM. Merging LoRA is the standard production optimization for
exactly this overhead. So the fine-tune is faster because it is **more efficient
per forward**, doing the same math folded into the weights — legitimate, expected.

(The 256-d vs 768-d output is not a factor: truncation is one slice after pooling.)

## Takeaways
- The `~2.8×` is genuine and fully explained; the prior 4–5-day base run paid the
  runtime-LoRA tax, this one doesn't.
- Serving parity: the query encoder loads the SAME merged fine-tune, so query-side
  encode inherits the same ~2.8× speedup + halved VRAM vs the old base server.

## Index build (Phase 2) — succeeded despite a non-zero exit
DiskANN disk build ran ~25 h (`elapsed_seconds=90470`, ~1.84 B replicated points
across 7 sub-shards) and **completed**: `build_diskann_index.py` wrote every
artifact, wrote `index_meta.json`, printed `[index] built`, and `main()` returned
0. The process then exited **non-zero with no traceback** — diskannpy's C++
objects crashing during interpreter *teardown* on the 269 GB index — which tripped
`run_ft_index.sh`'s `|| fail` and left `.pipeline_status=FAIL`. **False alarm.**
- Verified good by loading the disk index + live CPU-encoded queries: 10 hits,
  real docids across many shards, clean descending MIPS scores (0.520→0.492);
  PQ load reports `#points: 921892634`. Flipped status → `DONE`.
- Hardened `run_ft_index.sh` Phase 2: verify the expected artifacts exist/non-empty
  and only `fail` on a missing one; a teardown-only crash with all artifacts
  present is logged as such, not treated as a build failure.
- Index: `data/built-indexes/climbmix-chunked-ft/` (disk, mips, n=921,892,634,
  dim=256). Reclaimable: `vectors.fbin` (944 GB concat input, per-shard fbins still exist).

## Eval — general-topic performance vs base (does the agent-query fine-tune regress generality?)
`tasks/custom_index/scripts/eval_ft_vs_base.sh` (CPU encode, k=2000/L=2000/depth=1000):
FT = local `climbmix-chunked-ft`; BASE = old base model served at
`index-climbmix-jina-v5-nano.dsync.net` (same chunks/corpus, only the model differs).
22 RAG25 dev topics, chunk→parent max-pool, vs the ClimbMix UMBRELA qrels.
Judged-coverage@10 is low (FT 0.159 / base 0.177) → **condensed** (unjudged-dropped)
metrics are the fair lens; raw are pool-biased low.

Condensed, mean across the 3 judge variants:

| metric | base | fine-tuned | Δ (ft−base) |
|---|---|---|---|
| nDCG@10 | 0.7127 | **0.7196** | +0.007 |
| MAP | 0.1032 | **0.1125** | +0.009 |
| recall@100 | 0.0752 | **0.0798** | +0.005 |
| recall@1000 | 0.1056 | **0.1155** | +0.010 |

Per-judge condensed nDCG@10: codex-gpt5.5 base 0.6570 / **ft 0.6357** (−0.021);
ministral base 0.7825 / **ft 0.8124** (+0.030); qwen base 0.6986 / **ft 0.7106**
(+0.012). So nDCG@10 is **on par** (behind on codex only, ahead on the other two,
net +0.007), and MAP + recall are **consistently higher** for the fine-tune on all
three judges. With 22 topics ±0.01–0.03 is noise → honest read: **no general-quality
regression; slight edge to the fine-tune on MAP/recall** — before counting the
agent-query specialization it was trained for. Runs/metrics:
`tasks/custom_index/work/eval-ft-vs-base/` ; log `tasks/custom_index/logs/eval_ft_vs_base.log`.

Aside — remote base server reported `encode_ms≈80` for a single query (base model,
their hardware): a data point for the CPU-serving speedup discussion (merged FT
should encode cheaper; measure directly on the serve box when free).

## Artifacts
- Probes: `scratchpad/model_probe.py`, `scratchpad/base_probe.py`
  (copied to `worklogs/assets/2026-08-02-{model,base}_probe.py`).
- Vectors: `work/climbmix-chunked/encoded-ft/` (6543 fbins, 921,892,634 × 256-d).
- Index build in progress: `data/built-indexes/climbmix-chunked-ft/` (Phase 2 DiskANN).
- Eval staged (post-build): `tasks/custom_index/scripts/eval_ft_vs_base.sh`.
