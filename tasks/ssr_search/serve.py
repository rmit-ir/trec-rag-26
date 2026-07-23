"""ssr-search HTTP service — a thin, stable HTTP front for Cottontail SSR.

Wraps one ``SsrEngine`` (which owns the ``ssr-server`` subprocess + socket) and
exposes it on a fixed port so an LLM agent / the ``src/tools`` Boolean tool can
drive SSR retrieval over HTTP. The underlying ssr-server is single-client and
serial, so every request is dispatched through ``asyncio.to_thread`` onto the
engine's internal lock — unrelated HTTP requests still progress on the loop
while one SSR query runs (SSR can take >1s).

Run (from the mamba env):
    SSR_BURROWS=data/built-indexes/ssr-shard00000/json.burrow \\
        tasks/ssr_search/env/bin/uvicorn serve:app --host 127.0.0.1 --port 8099

Config (env):
    SSR_BURROWS      comma-separated burrow dirs (required)
    SSR_CONTAINER    GCL container query   (default ":")
    SSR_CONTENT      GCL content query     (default ":contents:")
    SSR_DOCNO        GCL docno query       (default ":id:")
    SSR_FIELDS       optional --fields for /document
    SSR_SERVER_BIN   path to ssr-server binary
    SSR_CACHE_SIZE   LRU entries (default 4096)
    SSR_RESTART_AFTER distinct queries before subprocess restart (default 20000)
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ssr_engine import (DEFAULT_CONTAINER, DEFAULT_CONTENT, DEFAULT_DOCNO,
                        DEFAULT_SERVER_BIN, SsrEngine)

_engine: SsrEngine | None = None


def _build_engine() -> SsrEngine:
    burrows_env = os.environ.get("SSR_BURROWS", "").strip()
    if not burrows_env:
        raise RuntimeError("SSR_BURROWS is required (comma-separated burrows)")
    burrows = [str(Path(b.strip()).resolve()) for b in burrows_env.split(",") if b.strip()]
    return SsrEngine(
        burrows=burrows,
        container=os.environ.get("SSR_CONTAINER", DEFAULT_CONTAINER),
        content=os.environ.get("SSR_CONTENT", DEFAULT_CONTENT),
        docno=os.environ.get("SSR_DOCNO", DEFAULT_DOCNO),
        fields=os.environ.get("SSR_FIELDS") or None,
        server_bin=Path(os.environ.get("SSR_SERVER_BIN", str(DEFAULT_SERVER_BIN))),
        cache_size=int(os.environ.get("SSR_CACHE_SIZE", "4096")),
        restart_after=int(os.environ.get("SSR_RESTART_AFTER", "20000")),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    _engine = _build_engine()
    await asyncio.to_thread(_engine.start)
    try:
        yield
    finally:
        if _engine is not None:
            await asyncio.to_thread(_engine.close)
            _engine = None


app = FastAPI(title="ssr-search", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str
    k: int = 10


class OptimizerRequest(BaseModel):
    enabled: bool


@app.get("/health")
async def health() -> dict:
    ok = _engine is not None
    return {"ok": ok, "port": _engine.port if _engine else 0,
            "burrows": _engine.burrows if _engine else []}


@app.post("/search")
async def search(req: SearchRequest) -> dict:
    if _engine is None:
        raise HTTPException(503, "engine not ready")
    if not req.query.strip():
        raise HTTPException(400, "empty query")
    try:
        hits = await asyncio.to_thread(_engine.search, req.query, req.k)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    return {"query": req.query, "k": req.k,
            "results": [h.to_dict() for h in hits]}


@app.get("/document")
async def document(docno: str) -> dict:
    if _engine is None:
        raise HTTPException(503, "engine not ready")
    try:
        text = await asyncio.to_thread(_engine.document, docno)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"{type(e).__name__}: {e}")
    return {"docno": docno, "document": text}


@app.post("/set_optimizer")
async def set_optimizer(req: OptimizerRequest) -> dict:
    if _engine is None:
        raise HTTPException(503, "engine not ready")
    ok = await asyncio.to_thread(_engine.set_optimizer, req.enabled)
    return {"ok": ok, "enabled": req.enabled}
