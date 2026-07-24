"""Fan-out HTTP shim over the fork's MultiShardSearchEngine.

Exposes the SAME /search {query,k} contract that src/utils/search_ssr.py already
speaks (so the aus_agent SSR arm is unchanged), backed by the fork's
MultiShardSearchEngine over N single-burrow cottontail-jsonl-servers. The engine
owns the cp<->docno maps (one DocnoMap per shard), so hits come out docno-keyed —
directly usable for dedup/citation against qrels.

  POST /search  {"query": "<GCL>", "k": 20, "window": 200}
     -> {"results":[{"docno","rank","score","snippet"}], "total_matches", "unjudged_matches"}
  POST /doc     {"docno": "shard_00000_5"}  -> {"docno","found","text"}
  GET  /healthz -> 200 when all shards healthy

Run (from repo root):
  BASE_PORT=7000 NGROUPS=26 WINDOW=200 SHIM_PORT=8099 \
    PYTHONPATH=tmp/Cottontail-uwaterloo/isj \
    uv run --no-project --with pydantic --with httpx \
    python tasks/ssr_search/scripts/fork_shim.py
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from isj_agent.docno_map import DocnoMap
from isj_agent.engine.base import EngineError
from isj_agent.engine.http import HttpSearchEngine
from isj_agent.engine.multishard import MultiShardSearchEngine

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
OUT = ROOT / "data/built-indexes/fork-climbmix-full"
BASE_PORT = int(os.environ.get("BASE_PORT", "7000"))
NGROUPS = int(os.environ.get("NGROUPS", "26"))
WINDOW = int(os.environ.get("WINDOW", "200"))  # legacy fallback; servers run --paragraph
SHIM_PORT = int(os.environ.get("SHIM_PORT", "8099"))

# Build one shard engine per group-server; each owns its burrow's docno-cp map.
_shards = []
for g in range(NGROUPS):
    burrow = OUT / f"group_{g:04d}" / "burrow"
    dmap = DocnoMap(burrow / "docno-cp.sqlite")
    _shards.append(HttpSearchEngine(base_url=f"http://127.0.0.1:{BASE_PORT + g}",
                                    docno_map=dmap))
ENGINE = MultiShardSearchEngine(_shards)
ENGINE.healthz()  # fail fast if any shard is down
print(f"[shim] {NGROUPS} shards healthy; window={WINDOW}; listening on :{SHIM_PORT}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        if self.path == "/healthz":
            try:
                ENGINE.healthz()
                self._send(200, {"status": "ok", "shards": NGROUPS})
            except EngineError as e:
                self._send(503, {"status": "unhealthy", "error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            b = self._body()
        except Exception as e:
            return self._send(400, {"error": f"bad json: {e}"})
        if self.path == "/search":
            # Case-folding now happens SERVER-SIDE (fork jsonl_core.cc
            # emit_cover_term / stem_atom ascii_fold), matching the case-folded
            # index — no client-side .lower() needed.
            query = b.get("query", "")
            k = int(b.get("k", 10))
            window = int(b.get("window", WINDOW))
            try:
                resp = ENGINE.search(query, top_k=k, window=window)
            except EngineError as e:
                return self._send(400, {"error": str(e)})
            results = [{"docno": h.id, "rank": h.rank, "score": h.score,
                        "snippet": h.summary} for h in resp.results]
            return self._send(200, {"results": results,
                                    "total_matches": resp.total_matches,
                                    "unjudged_matches": resp.unjudged_matches})
        if self.path == "/doc":
            docno = b.get("docno", "")
            try:
                text = ENGINE.read(docno)
            except EngineError as e:
                return self._send(400, {"error": str(e)})
            return self._send(200, {"docno": docno, "found": text is not None,
                                    "text": text})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", SHIM_PORT), Handler).serve_forever()
