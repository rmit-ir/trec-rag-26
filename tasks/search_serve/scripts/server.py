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
from contextlib import asynccontextmanager
from pathlib import Path

import orjson
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse, Response
from pydantic import BaseModel, Field

from encoder import EncoderConfig
from errors import EngineLoadError
from search_engine import SearchEngine


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
    return SearchEngine.load(
        index_dir,
        encoder_config=cfg,
        diskann_search_threads=_env_int("DISKANN_THREADS", 4),
        docstore_lru=_env_int("DOCSTORE_LRU", 1024),
        warmup=_env_bool("WARMUP", True),
        warmup_madvise_offsets=_env_bool("WARMUP_MADVISE_OFFSETS", True),
        warmup_madvise_pq=_env_bool("WARMUP_MADVISE_PQ", False),
        print_server_details=_env_bool("PRINT_SERVER_INFO", True),
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ENGINE, SEARCH_SEM
    try:
        ENGINE = load_engine_from_env()
    except EngineLoadError as e:
        print(f"\n[server] FAILED to load engine:\n  {e}\n", file=sys.stderr)
        # Re-raise so the worker exits — better than serving 500s forever.
        raise
    SEARCH_SEM = asyncio.Semaphore(_env_int("SEARCH_INFLIGHT_PER_WORKER", 1))
    print(f"[server] in-flight cap per worker = {SEARCH_SEM._value}", flush=True)
    yield
    if ENGINE is not None:
        ENGINE.close()
        ENGINE = None
    SEARCH_SEM = None


app = FastAPI(title="trec-rag-26 search-serve",
              default_response_class=ORJSONResponse,
              lifespan=lifespan)


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


def _log_timings(endpoint: str, t) -> None:
    """One-line structured log per request — easy to grep / awk in load tests."""
    print(f"[req] {endpoint} n={t.n_queries} k={t.k} text={t.with_text} "
          f"encode={t.encode_ms:.2f}ms ann={t.ann_ms:.2f}ms "
          f"docstore={t.docstore_fetch_ms:.2f}ms total={t.total_ms:.2f}ms",
          flush=True)


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
    _log_timings(endpoint_label, result.timings)
    return {
        "query": req.query,
        "hits": [h.to_dict() for h in result.hits[0]],
        "timings": result.timings.to_dict(),
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


@app.post("/search/batch")
async def search_batch(req: BatchSearchRequest):
    eng = _require_engine()
    result = await _run_search(
        eng.search_batch, req.queries,
        k=req.k, complexity=req.complexity,
        beam_width=req.beam_width, with_text=req.with_text,
    )
    _log_timings("/search/batch", result.timings)
    return {
        "queries": req.queries,
        "results": [[h.to_dict() for h in hits] for hits in result.hits],
        "timings": result.timings.to_dict(),
    }
