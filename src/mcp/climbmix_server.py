"""ClimbMix MCP server — corpus `search` / `fetch` for external DR agents.

Exposes our ClimbMix retrieval stack over the Model Context Protocol so a
hosted deep-research agent (OpenAI `o3-deep-research` via the Responses API's
remote-MCP tool) can ground itself on the fixed corpus instead of the open web.

The tool surface is exactly the two-tool contract OpenAI Deep Research expects
from a connector MCP server:

- ``search(query)`` -> ``{"results": [{"id", "title", "text", "url"}]}``
  Hybrid dense+sparse RRF over ClimbMix (``utils.search.search``) — the
  engine-free best single default, since a DR agent cannot pick engines
  per call the way aus_agent's tool schema allows. ``id`` is the ClimbMix
  docid; ``text`` is a snippet.
- ``fetch(id)`` -> ``{"id", "title", "text", "url", "metadata"}``
  Full document text by docid, from a configured local full ClimbMix docstore
  or the hosted ``utils.fetch_doc.fetch_doc`` fallback.

Transport is stateless streamable-HTTP (OpenAI's recommendation for DR
connectors). If ``CLIMBMIX_MCP_TOKEN`` is set, every request must carry
``Authorization: Bearer <token>`` — set it when tunnelling the server to a
public URL for OpenAI's crawlers to reach.

Run (repo root; deps live in the o3-deep-research system group):

    uv run --group o3-deep-research python src/mcp/climbmix_server.py   # :8720/mcp
    MCP_PORT=9000 uv run --group o3-deep-research python src/mcp/climbmix_server.py

Env:

    MCP_HOST / MCP_PORT      bind address (default 0.0.0.0:8720)
    CLIMBMIX_MCP_TOKEN       optional bearer token guard
    MCP_SEARCH_K             results per search (default 10)
    MCP_SNIPPET_CHARS        search snippet length (default 500)
    MCP_SEARCH_ENGINE        hybrid | semantic | keyword (default hybrid)
    MCP_TRANSPORT            set to ``stdio`` for local CLI-agent subprocesses
    CLIMBMIX_MCP_LOG         optional per-run JSONL tool log path
    CLIMBMIX_LOCAL_DOCSTORE  optional local full-docstore directory for fetch
    MCP_FETCH_LOCK_PATH / MCP_FETCH_MIN_INTERVAL  paced remote-fetch fallback
    + the retrieval env the utils already read (SEARCH_API_KEY,
      DENSE_SEARCH_URL, SPARSE_SEARCH_URL, PYSERINI_DOC_URL,
      PYSERINI_API_TOKEN), auto-loaded from the repo .env.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # env from repo .env, same pattern as the systems' runners
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from utils.fetch_doc import DEFAULT_DOC_URL, fetch_doc
from utils.local_docstore import FullClimbMixDocStore
from utils.search import search as hybrid_search
from utils.search_dense import search_dense
from utils.search_sparse import search_sparse

SEARCH_K = int(os.environ.get("MCP_SEARCH_K", "10"))
SNIPPET_CHARS = int(os.environ.get("MCP_SNIPPET_CHARS", "500"))
SEARCH_ENGINE = os.environ.get("MCP_SEARCH_ENGINE", "hybrid")
TOOL_LOG = os.environ.get("CLIMBMIX_MCP_LOG")
FETCH_LOCK_PATH = os.environ.get("MCP_FETCH_LOCK_PATH")
FETCH_MIN_INTERVAL = max(0.0, float(os.environ.get("MCP_FETCH_MIN_INTERVAL", "0")))
LOCAL_DOCSTORE_PATH = os.environ.get("CLIMBMIX_LOCAL_DOCSTORE")
_LOG_LOCK = threading.Lock()
_LOCAL_STORE_LOCK = threading.Lock()
_LOCAL_STORE: FullClimbMixDocStore | None = None
_wall_time = time.time
_sleep = time.sleep
_ENGINES = ("hybrid", "semantic", "keyword")
if SEARCH_ENGINE not in _ENGINES:
    # Still falls back to hybrid rather than refusing to start — but silently
    # doing so meant a typo'd engine name ran a whole experiment on the wrong
    # retriever with nothing in the logs to say so.
    print(f"[warn] MCP_SEARCH_ENGINE={SEARCH_ENGINE!r} is not one of "
          f"{_ENGINES}; falling back to 'hybrid'", file=sys.stderr, flush=True)

# Documents render at the Pyserini REST endpoint, so citations get a real URL
# while `id` stays the ClimbMix docid the eval pipeline keys on.
_DOC_BASE = (os.environ.get("PYSERINI_DOC_URL", DEFAULT_DOC_URL)).rstrip("/")

# The SDK's DNS-rebinding protection 421s any Host not in a localhost
# allowlist — but this server is *meant* to be reached through a public
# tunnel hostname (OpenAI's servers call it), and the bearer guard already
# gates access. Disable it or every tunnelled POST dies with 421.
mcp = FastMCP("climbmix", stateless_http=True, json_response=True,
              transport_security=TransportSecuritySettings(
                  enable_dns_rebinding_protection=False))


def _title(text: str) -> str:
    """First line-ish of a document as a human-readable title."""
    head = " ".join((text or "").split())
    return head[:100] + ("…" if len(head) > 100 else "")


def _run_search(query: str, k: int) -> list[dict[str, Any]]:
    if SEARCH_ENGINE == "semantic":
        return search_dense(query, k, with_text=True)
    if SEARCH_ENGINE == "keyword":
        return search_sparse(query, k)
    return hybrid_search(query, k, with_text=True)


def _now_iso() -> str:
    """UTC tool timestamp that cannot inject a geographic locale into a run."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _append_tool_log(record: dict[str, Any]) -> None:
    """Append one MCP call when a per-run log path was explicitly configured."""
    if not TOOL_LOG:
        return
    path = Path(TOOL_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _fetch_with_shared_pacing(docid: str) -> dict[str, str]:
    """Serialize CLI-agent fetches across MCP processes when configured.

    Coding agents can issue dozens of fetches back-to-back. A modest model
    worker pool therefore produces a much higher request rate than ordinary
    agents that reason between calls, and the shared Pyserini endpoint responds
    with persistent 429s even though every individual worker is synchronous.
    An advisory file lock makes the optional pacing boundary host-wide rather
    than process-local. The lock is held through retries; a crashed process
    releases it in the kernel.
    """
    if not FETCH_LOCK_PATH:
        return fetch_doc(docid)

    import fcntl

    path = Path(FETCH_LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as state:
        fcntl.flock(state.fileno(), fcntl.LOCK_EX)
        state.seek(0)
        try:
            last_finished = float(state.read().strip() or "0")
        except ValueError:
            last_finished = 0.0
        remaining = FETCH_MIN_INTERVAL - (_wall_time() - last_finished)
        if remaining > 0:
            _sleep(remaining)
        try:
            return fetch_doc(docid)
        finally:
            state.seek(0)
            state.truncate()
            state.write(str(_wall_time()))
            state.flush()
            fcntl.flock(state.fileno(), fcntl.LOCK_UN)


def _fetch_evidence_document(docid: str) -> dict[str, str]:
    """Use the local full corpus when configured; retain remote fallback."""
    global _LOCAL_STORE
    if not LOCAL_DOCSTORE_PATH:
        return _fetch_with_shared_pacing(docid)
    if _LOCAL_STORE is None:
        with _LOCAL_STORE_LOCK:
            if _LOCAL_STORE is None:
                _LOCAL_STORE = FullClimbMixDocStore(LOCAL_DOCSTORE_PATH)
    return {"docid": docid, "text": _LOCAL_STORE.get_text(docid)}


@mcp.tool()
def search(query: str) -> dict[str, Any]:
    """Search the ClimbMix corpus. Returns the top matching documents with a
    short text snippet each. Use `fetch` with a result's `id` to read the
    full document before citing it."""
    started = _now_iso()
    try:
        hits = _run_search(query, SEARCH_K)
        results = []
        for h in hits:
            text = h.get("text") or ""
            results.append({
                "id": h["docid"],
                "title": _title(text) or h["docid"],
                "text": text[:SNIPPET_CHARS],
                "url": f"{_DOC_BASE}/{h['docid']}",
            })
    except Exception as exc:
        _append_tool_log({
            "t_start": started,
            "t_end": _now_iso(),
            "type": "tool_call",
            "tool_name": "search",
            "arguments": {"query": query},
            "failed": True,
            "error": f"{type(exc).__name__}: {exc}",
        })
        raise
    payload = {"results": results}
    _append_tool_log({
        "t_start": started,
        "t_end": _now_iso(),
        "type": "tool_call",
        "tool_name": "search",
        "arguments": {"query": query},
        "returned": [{"docid": h["docid"], "score": h.get("score")}
                     for h in hits],
        "output_head": json.dumps(payload, ensure_ascii=False)[:200],
    })
    return payload


@mcp.tool()
def fetch(id: str) -> dict[str, Any]:
    """Fetch the full text of one ClimbMix document by its `id` (docid), as
    returned by `search`. Always fetch a document before citing it."""
    started = _now_iso()
    try:
        doc = _fetch_evidence_document(id)
        text = doc.get("text") or ""
        docid = doc.get("docid", id)
    except Exception as exc:
        _append_tool_log({
            "t_start": started,
            "t_end": _now_iso(),
            "type": "tool_call",
            "tool_name": "fetch",
            "arguments": {"id": id},
            "failed": True,
            "error": f"{type(exc).__name__}: {exc}",
        })
        raise
    payload = {
        "id": docid,
        "title": _title(text) or id,
        "text": text,
        "url": f"{_DOC_BASE}/{docid}",
        "metadata": {"corpus": "climbmix-400b"},
    }
    _append_tool_log({
        "t_start": started,
        "t_end": _now_iso(),
        "type": "tool_call",
        "tool_name": "fetch",
        "arguments": {"id": id},
        "returned": [{"docid": docid}],
        "output_head": text[:200],
    })
    return payload


def build_app():
    """Streamable-HTTP ASGI app, with an optional bearer-token guard."""
    app = mcp.streamable_http_app()
    token = os.environ.get("CLIMBMIX_MCP_TOKEN")
    if token:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        class _Bearer(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if request.headers.get("authorization") != f"Bearer {token}":
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                return await call_next(request)

        app.add_middleware(_Bearer)
    return app


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT") == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        host = os.environ.get("MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("MCP_PORT", "8720"))
        uvicorn.run(build_app(), host=host, port=port, log_level="info")
