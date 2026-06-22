# How to build the ClimbMix custom index

End-to-end instructions for going from a fresh clone to a fully built DiskANN
index over the ~563M-doc ClimbMix-400B-shuffle corpus.

> All paths below are relative to the repo root unless stated. The task lives
> under `tasks/custom_index/`. Run every Python tool via the **task's own**
> uv env (`uv run --project tasks/custom_index ...`); never reuse the repo
> root env.

## What this builds

A DiskANN disk-resident ANN index whose vectors are 768-d `bfloat16`
embeddings of every ClimbMix doc, produced by
`jinaai/jina-embeddings-v5-text-nano` with `task="retrieval"` and
`prompt_name="document"`. The on-disk index is what the Rust serve task
(separate task) will load.

Final artifacts land at `data/built-indexes/<RUN_NAME>/`:

```
ann_disk.index        # DiskANN graph + layout
ann_pq_pivots.bin     # PQ codebook for the in-RAM nav table
ann_pq_compressed.bin
ann_disk.index_*.bin  # additional internal files
vectors.fbin          # concatenated raw vectors (DiskANN fbin format)
docids.txt            # one docid per line, parallel to vectors.fbin
concat_manifest.json  # which shard fbins were concatenated, in order
encoding_meta.json    # model, dim, task, prompt names (used by search.py)
index_meta.json       # diskann build args + elapsed time
```

## 0. One-time setup

### 0.1 Sync the task uv env

```bash
uv sync --project tasks/custom_index
```

This pins Python 3.11, PyTorch 2.x (cu124 wheels), sentence-transformers,
diskannpy, einops + peft (for Jina v5's trust_remote_code path).

### 0.2 Download the ClimbMix corpus

The download script is in `tasks/custom_index/scripts/download_climbmix.sh`.
Pulls all 6543 parquet shards (~559 GB) into
`data/climbmix-400b-shuffle/`. Resumable; safe to re-run.

```bash
HF_XET_HIGH_PERFORMANCE=1 ./tasks/custom_index/scripts/download_climbmix.sh \
  2>&1 | tee /tmp/climbmix-download.log
```

Verify when done:

```bash
ls data/climbmix-400b-shuffle/shard_*.parquet | wc -l   # should be 6543
```

## 1. Smoke run (16 shards, ~5 minutes)

Sanity-check the full pipeline end-to-end on a tiny subset before committing
to the multi-day full run. Uses an in-memory DiskANN index (the disk kind
needs lots of RAM and time and isn't useful at 16 shards).

```bash
RUN_NAME=climbmix-smoke \
NSHARDS=16 \
INDEX_KIND=memory \
  ./tasks/custom_index/scripts/index_pipeline.sh \
  2>&1 | tee /tmp/climbmix-smoke.log
```

All knobs not given on the command line will be prompted (TTY) or fall back
to the suggested defaults baked into `index_pipeline.sh`. After the run,
the script does a sample search at the end so you can eyeball the hits.

## 2. Full run (all 6543 shards, ~3–4 days)

```bash
RUN_NAME=climbmix-full \
NSHARDS=0 \
MODEL=jinaai/jina-embeddings-v5-text-nano \
BATCH=10 \
NUM_WORKERS=0 \
DEVICE=auto \
INDEX_KIND=disk \
METRIC=mips \
SORT=desc \
GRAPH_DEGREE=64 \
COMPLEXITY=100 \
BUILD_MEM_GB=500 \
SEARCH_MEM_GB=64 \
PQ_DISK_BYTES=32 \
INDEX_THREADS=128 \
  ./tasks/custom_index/scripts/index_pipeline.sh \
  2>&1 | tee /tmp/climbmix-full.log
```

Launch as a tracked background task (the project's running-long-commands
rule). Monitor:

```bash
tail -f /tmp/climbmix-full.log
# or the script's own log:
tail -f tasks/custom_index/logs/index_pipeline.climbmix-full.log
```

## 3. The pipeline in detail

### 3.1 Steps

1. **`uv sync`** — fail fast on dep issues.
2. **prepare ↔ encode (overlapped)**
   - `prepare_corpus.sh` walks the parquet shards in sorted order. For each
     shard it writes `shard_NNNNN.jsonl` (atomically) and then touches
     `shard_NNNNN.jsonl.ready`. After the last shard it touches
     `.prepare_done`. On any error it touches `.prepare_fail`.
   - `encode_documents.py --watch` spawns one worker per visible GPU. Each
     worker polls the corpus dir for `*.jsonl.ready` files whose
     `sorted-index %% N == rank` and whose `.fbin` doesn't yet exist; encodes
     one, repeats. On idle, checks `.prepare_fail` (exit 1) or
     `.prepare_done` (re-glob; exit 0 if drained).
3. **`build_diskann_index.py`** — concatenates per-shard `.fbin` files into
   one `vectors.fbin` (and `docids.txt`), then calls `diskannpy.build_disk_index`.
4. **`search.py`** — runs two sample queries and prints top-k for a sanity check.

### 3.2 Pipeline knobs

`index_pipeline.sh` has **no built-in defaults** for these — set as env
vars on the command line, or run interactively and it will prompt. If a
required value is missing and stdin is not a TTY, the script aborts with
the verbatim command line you need.

| knob | meaning |
|---|---|
| `RUN_NAME` | name for `work/<RUN>/` and `data/built-indexes/<RUN>/`. Use distinct names per attempt |
| `NSHARDS` | `>0` = leading N shards (smoke); `<=0` = all shards available |
| `MODEL` | HF model id; default `jinaai/jina-embeddings-v5-text-nano` |
| `BATCH` | model.encode GPU batch size. 10 is the winner from the streaming bench at seq=512 |
| `NUM_WORKERS` | encoder parent: `0` = auto (one worker per visible CUDA device) |
| `DEVICE` | `auto` / `cuda` / `cpu`. `auto` picks `cuda` if visible |
| `INDEX_KIND` | `disk` (full corpus, CPU+SSD serve) or `memory` (smoke only) |
| `METRIC` | `mips` for normalized Jina embeddings (equivalent to cosine here) |
| `SORT` | corpus sort by length. `desc` gives ~+18% encode throughput |
| `GRAPH_DEGREE` | DiskANN Vamana R; 64 is a fine default |
| `COMPLEXITY` | DiskANN build L; 100 is a fine default |
| `BUILD_MEM_GB` | **shared-box ceiling**. 500 is the safe cap on this 2 TB host — a 2× internal overshoot still leaves >=1 TB free for other users |
| `SEARCH_MEM_GB` | serve-time cache budget the Rust serve task will use (64 GB) |
| `PQ_DISK_BYTES` | per-vector PQ for the in-RAM nav table; 32 → ~18 GB resident for 563M vectors |
| `INDEX_THREADS` | DiskANN build parallelism. 128 = physical cores on this box (no SMT) |

## 4. Resumption

The pipeline is per-shard resumable. After a kill/crash, re-run the **same**
command verbatim:

- **prepare** skips any shard with both `shard_NNNNN.jsonl` (non-empty) and
  `shard_NNNNN.jsonl.ready` present. Partial shards (jsonl without ready)
  are deleted and redone.
- **encode** skips any shard with `shard_NNNNN.fbin` (and `.docids.txt` and
  `.meta.json`) present.
- **build** is a single Python call; it always re-runs from
  `vectors.fbin` + the assembled `docids.txt`. The concat step skips nothing
  but is cheap on already-correct inputs.

On startup, `prepare_corpus.sh` clears stale `.prepare_done` / `.prepare_fail`
markers, so resumed runs start clean.

## 5. Output locations

| path | what |
|---|---|
| `data/climbmix-400b-shuffle/` | downloaded parquet shards (~559 GB) |
| `tasks/custom_index/work/<RUN>/corpus/` | per-shard JSONL (intermediate; ~1.68 TB at peak) |
| `tasks/custom_index/work/<RUN>/encoded/` | per-shard `.fbin` + `.docids.txt` + `.meta.json` (~1.73 TB) |
| `data/built-indexes/<RUN>/` | concat `vectors.fbin` + final DiskANN index files |
| `tasks/custom_index/logs/` | pipeline / prepare / encode logs (all gitignored) |

All intermediate dirs are gitignored (see `tasks/custom_index/.gitignore`).

## 6. Expected wall time on this box

8× L40S, 2× Xeon 8592+ (128 physical cores), 2 TB RAM:

| stage | full corpus |
|---|---|
| prepare (sequential, single-process) | ~7 h |
| encode (overlapped with prepare; 8 GPUs, 218 docs/s/GPU sorted-desc) | ~90 h dominant |
| concat per-shard fbin → `vectors.fbin` | ~30 min |
| DiskANN disk build (500 GB cap, 128 threads, ~5–6 partitions) | ~8–12 h |
| sample search | seconds |

**Total ≈ 4 days** end-to-end. Prepare runs concurrently with encode in
watch mode, so the only effective wall-time stages are encode + build.

## 7. Disk footprint

Peak (during build, before per-shard fbins are deleted):

| artifact | size |
|---|---|
| parquet (already on disk) | ~580 GB |
| corpus JSONL | ~1.68 TB |
| per-shard `.fbin` | ~1.73 TB |
| concatenated `vectors.fbin` | ~1.73 TB |
| DiskANN disk index files | ~0.2–0.4 TB |
| **peak** | **~6 TB** |

`/mnt/raid10` has 16 TB free, so ~10 TB headroom at the worst moment.

## 8. Common issues

- **OOM during encode.** Drop `BATCH` (try 8). The per-GPU memory budget
  fits batch=10 at seq=512 with margin on L40S; longer max_seq_len needs a
  smaller batch.
- **Prepare looks frozen, no encode progress.** Check
  `tasks/custom_index/logs/prepare.*.out.log`. If prepare logs a row error
  for a shard, it touches `.prepare_fail`; the encoder will exit after the
  in-flight shard.
- **Worker reports "no shards assigned" or hangs waiting.** Make sure
  prepare and encode share the same `--corpus-dir` (`work/<RUN>/corpus`).
- **Resumed encode skips everything immediately.** It found
  `.prepare_done` already on disk and a fully drained queue. Means a prior
  run completed; pick a new `RUN_NAME` or delete the marker if you want to
  redo.
