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

- `POST /search` — `{ "query": "...", "k": 10, "with_text": true }`
- `POST /search/batch` — `{ "queries": ["...", "..."], ... }`
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
