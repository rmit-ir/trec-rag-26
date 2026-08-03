"""FastAPI search server over a built-index dir.

Single-worker dev launch:
  INDEX_DIR=/scratch/fast/built-indexes/climbmix-full \
    uv run --project tasks/search_serve uvicorn \
      --app-dir tasks/search_serve/scripts \
      server:app --host 0.0.0.0 --port 8000

Heavy-load production launch (one worker per GPU on a CUDA box, or per NUMA
node on a CPU-only box like segsresap12):
  INDEX_DIR=/scratch/fast/built-indexes/climbmix-full \
  SEARCH_DEVICE=cuda                                  \
    uv run --project tasks/search_serve gunicorn \
      --chdir tasks/search_serve/scripts \
      -k uvicorn.workers.UvicornWorker \
      -w 8 -b 0.0.0.0:8000 server:app

Each worker holds its own SentenceTransformer + DiskANN handle. The index
files are mmap'd, so the kernel page-caches them once across workers.
"""
from __future__ import annotations

# === preamble (runs before any torch import) =================================
#
# 1. Hide CUDA from the process when the operator has explicitly asked for
#    CPU. Otherwise our server_info.gpu_info() probe (and any incidental
#    torch.cuda call) initialises a ~440 MB CUDA driver context per visible
#    GPU, even though no kernels ever run there.
# 2. Bump RLIMIT_NOFILE soft -> hard so the per-worker docstore mmaps don't
#    trip "Too many open files" under concurrent load. With DOCSTORE_LRU=1024
#    we keep ~2050 shard fds open per worker + DiskANN + sockets + Python.
#    The kernel hard cap is usually fine; only the conservative soft cap
#    needs raising. No-op when the hard cap is already at our soft.
#
# Keep both at the very top of the module so they run before any other import.
import os as _os
import resource as _resource

# Source HF_TOKEN from the repo .env before anything loads the (possibly
# private) query-encoder model. huggingface_hub reads HF_TOKEN from the env;
# doing this in the preamble covers both direct-uvicorn and per-gunicorn-worker
# imports. No-op for public models or when HF_TOKEN is already set.
from env_util import load_repo_env as _load_repo_env
_load_repo_env()

if _os.environ.get("SEARCH_DEVICE", "").lower().startswith("cpu"):
    _os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

try:
    _soft, _hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
    if _soft < _hard:
        _resource.setrlimit(_resource.RLIMIT_NOFILE, (_hard, _hard))
        print(f"[preamble] raised RLIMIT_NOFILE soft {_soft} -> {_hard}",
              flush=True)
except (OSError, ValueError) as _e:
    print(f"[preamble] could not raise RLIMIT_NOFILE: {_e!r}", flush=True)

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field

from access_log import get_access_log
from encoder import EncoderConfig
from errors import EngineLoadError
from request_logging import install as _install_request_logging
from search_engine import SearchEngine
from startup_banner import print_startup_banner

# Enrich uvicorn's opaque "Invalid HTTP request received." warning with the
# client address + raw payload, so scanner/TLS-to-plaintext noise is
# identifiable instead of anonymous. No-op if uvicorn internals move.
_install_request_logging()

# RAM watchdog (RAM_WATCHDOG / RAM_KILL_FRACTION, default kill at 70%):
# engine load is ~74 GB resident per worker on climbmix-full, so an
# oversized -w melts smaller boxes. Armed per worker here (and in the
# gunicorn master via gunicorn_conf.on_starting); whichever process sees
# the threshold first SIGTERMs the whole process group, then SIGKILLs.
from ram_watchdog import start_from_env as _start_ram_watchdog
_start_ram_watchdog(f"ram-watchdog pid={os.getpid()}")


# ---------------------------------------------------------------------------
# config — env vars only; no CLI args at the worker level
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.lower() in ("1", "true", "yes", "y")


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return default if v in (None, "") else int(v)


def load_engine_from_env() -> SearchEngine:
    index_dir = os.environ.get("INDEX_DIR")
    if not index_dir:
        raise EngineLoadError(
            "INDEX_DIR env var is required (path to a built-index dir)."
        )
    cfg = EncoderConfig(
        kind=os.environ.get("SEARCH_ENCODER_KIND", "sentence_transformer"),
        device=os.environ.get("SEARCH_DEVICE", "auto"),
        dtype=os.environ.get("SEARCH_DTYPE", "auto"),
    )
    # If the gunicorn master already printed server-info (sentinel set in
    # gunicorn_conf.py:on_starting), skip the per-worker repeat.
    print_server_details = (
        _env_bool("PRINT_SERVER_INFO", True)
        and not os.environ.get("_SERVER_INFO_PRINTED")
    )
    return SearchEngine.load(
        index_dir,
        encoder_config=cfg,
        diskann_search_threads=_env_int("DISKANN_THREADS", 4),
        docstore_lru=_env_int("DOCSTORE_LRU", 1024),
        docstore_parallel=_env_int("DOCSTORE_PARALLEL", 1),
        docstore_parallel_min_k=_env_int("DOCSTORE_PARALLEL_MIN_K", 64),
        warmup=_env_bool("WARMUP", True),
        warmup_madvise_offsets=_env_bool("WARMUP_MADVISE_OFFSETS", True),
        warmup_madvise_pq=_env_bool("WARMUP_MADVISE_PQ", False),
        print_server_details=print_server_details,
    )


# ---------------------------------------------------------------------------
# request / response models
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The natural-language query.")
    # k=10000 covers the deepest first-stage retrieval use case in the README.
    k: int = Field(10, ge=1, le=10000)
    # complexity must be >= k for recall to hold; deep retrieval needs
    # complexity in the low thousands (see README tuning guide).
    complexity: int = Field(64, ge=1, le=4096)
    beam_width: int = Field(2, ge=1, le=16)
    with_text: bool = True


class BatchSearchRequest(BaseModel):
    queries: list[str] = Field(..., min_length=1, max_length=64)
    k: int = Field(10, ge=1, le=10000)
    complexity: int = Field(64, ge=1, le=4096)
    beam_width: int = Field(2, ge=1, le=16)
    with_text: bool = True


class DocsRequest(BaseModel):
    docids: list[str] = Field(..., min_length=1, max_length=4096,
                              description="docids like `shard_00042_1337`.")


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------

ENGINE: SearchEngine | None = None
# Per-worker cap on concurrent in-flight searches. Encode is the bottleneck
# and serialises on the GIL / GPU stream within one process, so the right
# default is 1 (parallelism comes from running multiple gunicorn workers,
# not from running multiple concurrent encodes inside one). Override via
# SEARCH_INFLIGHT_PER_WORKER for benchmarking.
SEARCH_SEM: asyncio.Semaphore | None = None
# Separate cap for docstore-only endpoints (/doc, /docs) so doc fetches
# neither queue behind GPU encodes nor fan into unbounded threads. Docstore
# reads are mmap+zstd (thread-safe via threading.local decoders) and release
# the GIL during decompress, so a small >1 cap is safe and useful.
DOC_SEM: asyncio.Semaphore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ENGINE, SEARCH_SEM, DOC_SEM
    try:
        ENGINE = load_engine_from_env()
    except EngineLoadError as e:
        print(f"\n[server] FAILED to load engine:\n  {e}\n", file=sys.stderr)
        # Re-raise so the worker exits — better than serving 500s forever.
        raise
    SEARCH_SEM = asyncio.Semaphore(_env_int("SEARCH_INFLIGHT_PER_WORKER", 1))
    DOC_SEM = asyncio.Semaphore(_env_int("DOC_INFLIGHT_PER_WORKER", 4))
    print(f"[server] in-flight cap per worker = {SEARCH_SEM._value} "
          f"(search) / {DOC_SEM._value} (doc fetch)", flush=True)
    # If gunicorn's when_ready hook already printed the master banner,
    # print_startup_banner is a no-op (env-sentinel guard). Otherwise this
    # is a direct-uvicorn launch and the per-process print is what the
    # operator gets.
    print_startup_banner()
    yield
    if ENGINE is not None:
        ENGINE.close()
        ENGINE = None
    SEARCH_SEM = None
    DOC_SEM = None


app = FastAPI(title="trec-rag-26 search-serve", lifespan=lifespan)


def _require_engine() -> SearchEngine:
    if ENGINE is None:
        raise HTTPException(status_code=503, detail="engine not loaded yet")
    return ENGINE


@app.get("/", include_in_schema=False)
def root():
    return {"ok": True, "service": "trec-rag-26 search-serve"}


@app.get("/health")
def health():
    eng = ENGINE
    if eng is None:
        return ORJSONResponse({"status": "loading"}, status_code=503)
    return {
        "status": "ok",
        "index_dir": str(eng.index_dir),
        "n_docs": len(eng.docids),
        "encoding_meta": eng.encoding_meta,
        "index_meta": eng.index_meta,
        "docstore_manifest": {k: v for k, v in eng.stats.docstore_manifest.items()
                              if k != "dict_size_bytes"},
        "aio_at_load": eng.stats.aio_after_load,
    }


@app.get("/server-info")
def server_info():
    """Re-collect host introspection on demand (cheap, fully timeout-bounded)."""
    from server_info import collect
    return collect(index_path=ENGINE.index_dir if ENGINE else None)


def _log_timings(endpoint: str, result) -> None:
    """One-line structured log per request — easy to grep / awk in load tests."""
    t, m = result.timings, result.metadata
    base = (f"[req] {endpoint} n={m.n_queries} k={m.k} text={m.with_text} "
            f"encode={t.encode_ms:.2f}ms ann={t.ann_ms:.2f}ms "
            f"docstore={t.docstore_fetch_ms:.2f}ms total={t.total_ms:.2f}ms")
    if t.docstore is not None and m.docstore is not None:
        dt, ds = t.docstore, m.docstore
        base += (f"  [ds open={dt.open_ms:.1f} read={dt.read_ms:.1f} "
                 f"decompress={dt.decompress_ms:.1f} decode={dt.decode_ms:.1f} "
                 f"shards={ds.n_unique_shards} new_mmaps={ds.n_mmap_opens}]")
    print(base, flush=True)


async def _run_search(fn, *args, **kwargs):
    """Run a blocking engine call in a thread, gated by the per-worker
    semaphore. The async def + to_thread combo keeps the event loop free to
    accept new requests while one is mid-encode; the semaphore prevents
    multiple threads from contending on the GIL inside the same worker."""
    assert SEARCH_SEM is not None, "engine not loaded yet"
    async with SEARCH_SEM:
        return await asyncio.to_thread(fn, *args, **kwargs)


async def _do_search(req: SearchRequest, endpoint_label: str) -> dict:
    """Shared body for GET /search and POST /search. Pydantic does the same
    validation in both paths because the GET wrapper builds a SearchRequest
    from query params."""
    eng = _require_engine()
    result = await _run_search(
        eng.search, req.query,
        k=req.k, complexity=req.complexity,
        beam_width=req.beam_width, with_text=req.with_text,
    )
    _log_timings(endpoint_label, result)
    hits = result.hits[0]
    get_access_log().log(req.query, [h.docid for h in hits])
    return {
        "query": req.query,
        "hits": [h.to_dict() for h in hits],
        "timings": result.timings.to_dict(),
        "metadata": result.metadata.to_dict(),
    }


@app.post("/search")
async def search_post(req: SearchRequest):
    return await _do_search(req, "POST /search")


@app.get("/search")
async def search_get(
    query: str = Query(..., min_length=1,
                        description="Natural-language query."),
    k: int = Query(10, ge=1, le=1000),
    complexity: int = Query(64, ge=1, le=4096,
                             description="DiskANN search list size. Must be >= k."),
    beam_width: int = Query(2, ge=1, le=16,
                             description="Concurrent in-flight reads per search thread."),
    with_text: bool = Query(True,
                             description="If true, fetch raw text from the docstore."),
):
    """Same behaviour as POST /search; fields go in the query string."""
    return await _do_search(
        SearchRequest(query=query, k=k, complexity=complexity,
                      beam_width=beam_width, with_text=with_text),
        "GET /search",
    )


# ---------------------------------------------------------------------------
# doc-by-id endpoints — docstore only, no encode / ANN involved
# ---------------------------------------------------------------------------

def _require_docstore():
    eng = _require_engine()
    if eng.docstore is None:
        raise HTTPException(status_code=503,
                            detail="engine loaded without a docstore")
    return eng.docstore


def _fetch_docs(docstore, docids: list[str]) -> tuple[list[str | None], list[str]]:
    """Fetch each docid, tolerating bad ones. Returns (texts aligned to
    input order with None for misses, list of missing/invalid docids).
    Runs inside a worker thread — everything here may block."""
    texts: list[str | None] = []
    missing: list[str] = []
    for did in docids:
        try:
            texts.append(docstore.get_text(did))
        except Exception:
            # malformed docid (ValueError), unknown shard (EngineLoadError),
            # row out of range (struct.error) — all "not found" to callers.
            texts.append(None)
            missing.append(did)
    return texts, missing


@app.get("/doc/{docid}")
async def get_doc(docid: str):
    """Fetch one document's text by docid (e.g. `shard_00042_1337`)."""
    ds = _require_docstore()
    assert DOC_SEM is not None
    t0 = time.perf_counter()
    async with DOC_SEM:
        texts, missing = await asyncio.to_thread(_fetch_docs, ds, [docid])
    if missing:
        raise HTTPException(status_code=404, detail=f"docid {docid!r} not found")
    print(f"[req] GET /doc n=1 total={(time.perf_counter()-t0)*1000:.2f}ms",
          flush=True)
    return {"docid": docid, "text": texts[0]}


@app.post("/doc/batch")
async def get_docs(req: DocsRequest):
    """Batch fetch documents by docid. Response `docs` is aligned to the
    request order; unknown/invalid docids get `text: null` and are listed
    in `missing` (the endpoint never 404s for partial misses).
    (Named /doc/batch, not /docs — GET /docs is FastAPI's Swagger UI.)"""
    ds = _require_docstore()
    assert DOC_SEM is not None
    t0 = time.perf_counter()
    async with DOC_SEM:
        texts, missing = await asyncio.to_thread(_fetch_docs, ds, req.docids)
    total_ms = (time.perf_counter() - t0) * 1000
    print(f"[req] POST /doc/batch n={len(req.docids)} missing={len(missing)} "
          f"total={total_ms:.2f}ms", flush=True)
    return {
        "docs": [{"docid": d, "text": t} for d, t in zip(req.docids, texts)],
        "found": len(req.docids) - len(missing),
        "missing": missing,
    }


@app.post("/search/batch")
async def search_batch(req: BatchSearchRequest):
    eng = _require_engine()
    result = await _run_search(
        eng.search_batch, req.queries,
        k=req.k, complexity=req.complexity,
        beam_width=req.beam_width, with_text=req.with_text,
    )
    _log_timings("/search/batch", result)
    alog = get_access_log()
    for q, hits in zip(req.queries, result.hits):
        alog.log(q, [h.docid for h in hits])
    return {
        "queries": req.queries,
        "results": [[h.to_dict() for h in hits] for hits in result.hits],
        "timings": result.timings.to_dict(),
        "metadata": result.metadata.to_dict(),
    }
