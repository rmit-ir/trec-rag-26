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

## Heavy-load: gunicorn + multiple workers

One worker per GPU (CUDA box) or per NUMA node (CPU box like segsresap12):

```bash
INDEX_DIR=/scratch/fast/built-indexes/climbmix-full \
SEARCH_DEVICE=cuda \
DISKANN_THREADS=4 \
WARMUP_MADVISE_PQ=true \
  uv run --project tasks/search_serve gunicorn \
    --chdir tasks/search_serve/scripts \
    -k uvicorn.workers.UvicornWorker \
    -w 8 -b 0.0.0.0:8000 server:app
```

Index files are mmap'd, so the kernel page-caches them once across all
workers (not N times). Per-worker overhead is the SentenceTransformer model
(~600 MB), one DiskANN handle, and `DISKANN_THREADS * 1024` libaio slots.

### AIO budget rule

DiskANN reserves one libaio io_context per search thread, ~1024 events each.
Stay under `/proc/sys/fs/aio-max-nr`:

```
workers * DISKANN_THREADS * 1024 < /proc/sys/fs/aio-max-nr
```

On a host with the kernel default `aio-max-nr=65536`:
- 8 workers × 4 threads = 32 contexts → 32,768 events (50% budget) — fine
- 16 workers × 8 threads = 128 contexts → 131,072 events — **over budget**, ask sysadmin to bump

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
