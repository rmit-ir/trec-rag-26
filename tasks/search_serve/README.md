# tasks/search_serve

Search engine + REST API + Python library over a built-index dir (vectors +
DiskANN + docstore). Loads one path, validates every part, prints a host
introspection summary, warms up the encoder + ANN + docstore, then serves.

## File layout

```
scripts/
  errors.py         EngineLoadError + missing-parts hints
  server_info.py    timeout-bounded host introspection (CPU/GPU/RAM/disk/aio)
  encoder.py        QueryEncoder protocol + SentenceTransformerEncoder (CPU/CUDA)
  docstore.py       FlatShardDocStore — mmap'd per-shard reader
  search_engine.py  SearchEngine — load + validate + search + warm-up
  cli.py            ad-hoc CLI
  server.py         FastAPI app (uvicorn / gunicorn entry)
```

## Quickstart — Python library

```python
import sys; sys.path.insert(0, "tasks/search_serve/scripts")
from search_engine import SearchEngine
from encoder import EncoderConfig

eng = SearchEngine.load(
    "data/built-indexes/climbmix-full",
    encoder_config=EncoderConfig(device="auto", dtype="auto"),
    diskann_search_threads=4,
)
hits = eng.search("transformers explained", k=5, with_text=True)
for h in hits:
    print(h.rank, h.docid, h.score, h.text[:80])
```

## Quickstart — CLI

```bash
uv run --project tasks/search_serve python tasks/search_serve/scripts/cli.py \
  --index-dir data/built-indexes/climbmix-full \
  --query "transformers explained" \
  --k 5 --max-chars 200
```

## Quickstart — REST

```bash
INDEX_DIR=data/built-indexes/climbmix-full \
  uv run --project tasks/search_serve uvicorn \
    --app-dir tasks/search_serve/scripts \
    server:app --host 0.0.0.0 --port 8000
```

Endpoints:

- `POST /search` — JSON body `{ "query": "...", "k": 10, "with_text": true,
  "complexity": 64, "beam_width": 2 }`
- `GET  /search` — same fields as query params, e.g.
  `/search?query=transformers&k=5&with_text=true`. Use for browser /
  one-liner / non-JSON clients. Same response, same timings.
- `POST /search/batch` — `{ "queries": ["...", "..."], ... }` (only POST;
  batch query lists don't fit well in a URL).
- `GET /health` — engine state + index metadata
- `GET /server-info` — live host introspection
- `GET /docs` — OpenAPI / Swagger UI

## Deployment recipes

Two reference launches, one per realistic deployment target. Both use the
same FastAPI app; only the env vars + gunicorn workers + per-worker pinning
change.

### Recipe A — GPU server (sctsresap21 or any CUDA box)

Specs in use: 8× NVIDIA L40S, 2× Xeon Platinum 8592+ (128 phys cores),
2 TB RAM. One gunicorn worker per GPU; the `pre_fork` hook pins each.

```bash
INDEX_DIR=/mnt/raid10/e128356/projects/trec-rag-26/data/built-indexes/climbmix-full \
SEARCH_DEVICE=cuda:0 \
SEARCH_DTYPE=auto \
DISKANN_THREADS=4 \
DOCSTORE_LRU=1024 \
SEARCH_INFLIGHT_PER_WORKER=1 \
WARMUP=true \
WARMUP_MADVISE_OFFSETS=true \
WARMUP_MADVISE_PQ=false \
N_GPUS=8 \
  uv run --project tasks/search_serve gunicorn \
    --chdir /mnt/raid10/e128356/projects/trec-rag-26/tasks/search_serve/scripts \
    -c /mnt/raid10/e128356/projects/trec-rag-26/tasks/search_serve/scripts/gunicorn_conf.py \
    -k uvicorn.workers.UvicornWorker \
    -w 8 -b 0.0.0.0:8000 \
    --timeout 600 \
    server:app
```

Notes:
- `SEARCH_DEVICE=cuda:0` is correct even with 8 workers — `gunicorn_conf.py`
  sets `CUDA_VISIBLE_DEVICES=<rank>` per worker, so each worker sees only
  one device and addresses it as cuda:0.
- `--timeout 600` is mandatory: per-worker engine load takes ~3 min
  (model + 64 GB PQ mmap + warm-up). The 30 s default will SIGKILL workers
  mid-load.
- **AIO budget:** `8 workers × 4 threads × 1024 events = 32,768` of the
  default `aio-max-nr=65,536`. Safe. Don't push `DISKANN_THREADS` past 8
  on this setup without checking the cap.
- **VRAM per worker:** ~600 MB (Jina v5 nano in bf16). Trivial against
  L40S's 45 GB.
- **PQ table (64 GB):** mmap'd, kernel-shared across workers — one page-cache
  copy, not eight. `WARMUP_MADVISE_PQ=true` is optional; the natural
  warm-up dummy search already faults in the hot pages.

### Recipe B — CPU server (segsresap12 / any Sapphire-Rapids-or-newer Xeon)

Specs assumed: dual Xeon Gold 5420+ Sapphire Rapids (56 phys cores / 112
threads, 2 NUMA nodes), 503 GB RAM, AMX BF16/INT8 available, index files
on `/scratch/fast` NVMe.

```bash
INDEX_DIR=/scratch/fast/built-indexes/climbmix-full \
SEARCH_DEVICE=cpu \
SEARCH_DTYPE=bfloat16 \
DISKANN_THREADS=4 \
DOCSTORE_LRU=1024 \
SEARCH_INFLIGHT_PER_WORKER=1 \
WARMUP=true \
WARMUP_MADVISE_OFFSETS=true \
WARMUP_MADVISE_PQ=true \
OMP_NUM_THREADS=7 \
MKL_NUM_THREADS=7 \
  numactl --interleave=all \
  uv run --project tasks/search_serve gunicorn \
    --chdir /scratch/fast/trec-rag-26/tasks/search_serve/scripts \
    -k uvicorn.workers.UvicornWorker \
    -w 8 -b 0.0.0.0:8000 \
    --timeout 600 \
    server:app
```

Notes:
- **`SEARCH_DTYPE=bfloat16` is the lever** — it activates the AMX BF16
  matmul kernels on Sapphire/Emerald Rapids. Without it, encode falls back
  to fp32 AVX-512 and runs roughly 2–3× slower.
- **`OMP_NUM_THREADS=7` per worker × 8 workers = 56 cores** — matches the
  physical core count; SMT (HT) rarely helps these dense GEMM kernels and
  often hurts (cache-line contention). Tune the worker count to match:
  4 workers → `OMP_NUM_THREADS=14`, 8 workers → 7, etc.
- **`numactl --interleave=all`** spreads memory pages across both NUMA
  nodes, so any worker's encode/PQ-fetch hits balanced bandwidth. Per-worker
  NUMA pinning would be tighter but needs a custom wrapper per worker
  (gunicorn doesn't expose a clean hook for that yet).
- **`WARMUP_MADVISE_PQ=true`** is the right default here: 503 GB RAM
  comfortably holds the 64 GB PQ table resident, and the cost of preloading
  is ~30 s once. Avoids any first-request cold-start latency.
- **No GPU pinning, no `N_GPUS`, no `gunicorn_conf.py`.** Plain gunicorn is
  enough.
- **AIO budget:** same math as recipe A — `8 × 4 × 1024 = 32 K` / 65 K cap.
  Safe.
- **VRAM:** N/A. RAM: ~1.2 GB per worker (model + scratch). 8 workers =
  ~10 GB total beyond the PQ table.

### Smoke check both recipes

```bash
# in another terminal once /health returns ok
curl -s -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{"query":"transformers explained","k":3,"with_text":true}' | jq '.timings, .hits[0]'

# load test
uv run --project tasks/search_serve python tasks/search_serve/scripts/loadtest.py \
  --url http://127.0.0.1:8000 \
  --total 300 --concurrency 1 --concurrency 8 --concurrency 16 \
  --k 10 --warmup 10
```

### When to deviate from the defaults

| symptom | knob to turn |
|---|---|
| p99 cold-start latency too high after restart | `WARMUP_MADVISE_PQ=true` |
| AIO `io_setup` errors at startup | reduce `DISKANN_THREADS` or `-w`; ask admin to raise `aio-max-nr` |
| Encode dominates total — want to trade recall for QPS | reduce `complexity` per request (default 64 → 32) |
| Multiple in-flight searches needed per worker (e.g. CPU has spare cores) | bump `SEARCH_INFLIGHT_PER_WORKER` to 2 — measure carefully |
| OOM when loading on a small box | reduce `DOCSTORE_LRU` (cap on open shard mmaps) |

## Per-request tuning by `k`

The right `complexity` and `beam_width` to send on each request depend on
how deep you're retrieving. DiskANN's recall hits saturation when
`complexity` is well above `k`; setting it too low silently truncates the
result list with poor neighbours. Setting it too high wastes graph hops.

Use these as starting points and adjust based on your recall vs throughput
budget. All numbers are per-request body fields against `/search`:

| use case | `k` | recommended `complexity` | recommended `beam_width` | est. server total p50 | est. peak r/s (8-worker GPU) |
|---|---|---|---|---|---|
| eval / interactive query | 10 | 64 (default) | 2 | 36 ms (measured) | 100 r/s (measured) |
| short-list rerank input | 100 | 128 | 2 | 50–70 ms | 60–80 r/s |
| TREC RAG primary run / re-rank pool | **1000** | **1024–1500** | **4** | **110–180 ms** | **45–70 r/s** |
| deep first-stage / candidate dump | 10 000 | 2000–3000 | 4–8 | 300–500 ms | 15–25 r/s |

Three things worth knowing:

1. **`complexity` must be ≥ `k`**, in practice `≈ k` or `1.5 × k` for good
   recall on this 553 M-doc index. Below `k`, the ANN truncates internally
   and recall craters.
2. **`beam_width` raises concurrent libaio reads per search thread.** With
   our `DISKANN_THREADS=4`, going `beam_width=2 → 4` doubles aio events
   per request (8 → 16 per request, still well under the worker's 4096
   reservation). Past 4 the wins shrink and disk-queue depth starts to bite.
3. **The docstore fetch scales with `k`** (~5 µs per record), but stays
   sub-millisecond up to `k = 200` and is still under 10 ms at `k = 1000`.
   It does NOT bottleneck deep retrieval — the cost lives in ANN search.

### Sending these on the wire

```bash
# k=1000 TREC RAG-style request
curl -s -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{"query":"...","k":1000,"complexity":1024,"beam_width":4,"with_text":true}' \
  | jq '.timings'
```

The `complexity` and `beam_width` fields are already accepted by
`SearchRequest` — no engine restart needed to change retrieval depth.

## What `DISKANN_THREADS` actually does (and when raising it helps)

`StaticDiskIndex(num_threads=N)` allocates **N libaio io_contexts** at index
load. At search time, `batch_search(num_threads=N')` distributes **queries**
across up to N' of those threads — but **one query is always handled by one
thread**. Per-query parallelism comes from `beam_width` (concurrent libaio
submits per thread), not from raising threads.

So the relationship between threads, endpoint, and benefit is:

| endpoint | queries per call | threads actually doing work | latency benefit of raising `DISKANN_THREADS` |
|---|---|---|---|
| `/search` (single query) | 1 | 1 | **none** — extra threads just hold idle io_contexts |
| `/search/batch` (N queries) | N (≤ 64) | min(N, num_threads) | linear up to N |

The per-query lever for ANN latency reduction is **`beam_width`** in the
request body, not the per-worker thread count. Going `beam_width=2 → 4`
roughly halves ANN time on this index and stays within each thread's 1024-
event AIO reservation.

### When raising `DISKANN_THREADS` *does* help

1. **Heavy `/search/batch` traffic** — set `DISKANN_THREADS` to your typical
   batch size (e.g. 8 if clients send 8-query batches).
2. **`SEARCH_INFLIGHT_PER_WORKER > 1`** — multiple concurrent `/search`
   requests inside one worker need separate io_contexts.

### AIO ceiling math by `DISKANN_THREADS` (default `aio-max-nr=65,536`)

| workers | `DISKANN_THREADS` | contexts | % of cap | risk |
|---|---|---|---|---|
| 8 | 4 (current default) | 32 | 50 % | safe |
| 8 | 6 | 48 | 75 % | safe, decent middle ground |
| 8 | 8 | 64 | 100 % | exactly at cap — fragile, ask sysadmin to bump `aio-max-nr` first |
| 4 | 16 | 64 | 100 % | same risk as above |

**Recommendation for the CPU server (segsresap12) traffic patterns:**

- **If primarily `/search` single-query:** keep `DISKANN_THREADS=4`. Push
  recall/latency by sending `beam_width=4` in the request body for k≥100.
  Free, no AIO impact.
- **If you expect bursty `/search/batch` with N≥8 queries per call:** raise
  `DISKANN_THREADS=8` and drop to 6 workers so contexts × workers ≈ 48.
  You lose one worker's encode parallelism but gain batch latency.

### Throughput drop estimates on the CPU server (segsresap12)

Scale the measured GPU peak above by ~0.78 (Sapphire Rapids 5420+ vs
Emerald Rapids 8592+, per-core perf, same AMX BF16 path):

| `k` | est. peak r/s on segsresap12 (8 workers) |
|---|---|
| 10 | ~80 |
| 100 | ~50–65 |
| 1000 | ~35–55 |
| 10000 | ~12–20 |

These are estimates, not benchmarks — verify on the box before publishing
real numbers.

## Environment variables (server.py)

| var | default | meaning |
|---|---|---|
| `INDEX_DIR` | (required) | path to a built-index dir |
| `SEARCH_DEVICE` | `auto` | encoder device: `auto`, `cpu`, `cuda`, `cuda:N` |
| `SEARCH_DTYPE` | `auto` | `auto` → bf16 on CUDA / AMX-capable CPUs, else fp32 |
| `SEARCH_ENCODER_KIND` | `sentence_transformer` | encoder registry key |
| `DISKANN_THREADS` | `4` | search threads per worker |
| `DOCSTORE_LRU` | `1024` | open-mmaps cap per docstore |
| `WARMUP` | `true` | run encoder + dummy search at startup |
| `WARMUP_MADVISE_OFFSETS` | `true` | preload offsets files (~4 GB) |
| `WARMUP_MADVISE_PQ` | `false` | preload `ann_pq_compressed.bin` (~64 GB) — set on PQ-bound boxes |
| `PRINT_SERVER_INFO` | `true` | dump host introspection at startup |

## When the engine fails to load

Every required file is checked individually. Missing pieces print the exact
CLI that produces them. Example:

```
EngineLoadError: missing built-index part: data/built-indexes/<RUN>/docstore/manifest.json

The docstore was not built. Construct it with:

  uv run --project tasks/custom_index python \
    tasks/custom_index/scripts/build_docstore.py \
    --corpus <PARQUET_CORPUS_DIR> \
    --out data/built-indexes/<RUN>/docstore \
    --compression zstd-9 --dict-size 1048576 \
    --dict-sample-shards 1 --parallel 64
```

## Architecture: swapping encoders for different deploys

`encoder.py` exposes a `QueryEncoder` protocol. The only implementation today
is `SentenceTransformerEncoder` (CPU or CUDA). To add an ONNX/AMX backend
for CPU-only hosts (e.g. segsresap12 Sapphire Rapids), implement the
protocol and register in `_ENCODER_REGISTRY`. SearchEngine doesn't change.

The DiskANN backend is similarly swappable in the future (e.g. DiskANN3 Rust)
without touching the search engine or REST layer.

## Storage notes

- All index files live on the local SSD/NVMe (e.g. `/scratch/fast` on
  segsresap12). Spinning disks are not in play — DiskANN's random-read
  pattern needs the IOPS.
- The PQ table (`ann_pq_compressed.bin`, ~64 GB for ClimbMix) is mmap'd. On
  a 503 GB-RAM box, set `WARMUP_MADVISE_PQ=true` and the kernel will resident-
  ify the whole thing before the first request lands.
