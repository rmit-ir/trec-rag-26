"""A local stdlib HTTP server that impersonates every ClimbMix backend.

Why this exists on top of the ``stub_search_tool`` fixture: that fixture patches
``tools.search_tool._DISPATCH``, so it proves the *tool* layer but skips the
retrieval clients entirely — URL construction, auth headers, the ``User-Agent``
the proxy requires, HTTP verb, request-body/query-param shape, and
response→``SearchHit`` mapping all go untested. Those are exactly the parts that
broke in production before (the stock urllib UA gets 403'd; the endpoints differ
in verb and payload shape).

So this server speaks the **real documented wire formats**, one handler per
endpoint, and the tests point the clients' env vars at
``http://127.0.0.1:<port>``. Nothing is monkeypatched: the client code runs
byte-for-byte as it does against the hosted services, over a real socket.

Endpoints (shapes taken from each client module + the track spec in
``skills/trec-rag-2026-track-guidelines/references/``):

    POST /search                    dense  (Jina-v5 DiskANN)  -> {"hits": [...]}
    POST /api/search                sparse (Anserini BM25)     -> ES-style
                                                                  {"hits": {"hits": [...]}}
    POST /search        (SSR port)  ssr    (Cottontail GCL)    -> {"results": [...]}
    GET  /v1/<index>/search         pyserini hosted BM25       -> {"candidates": [...]}
    GET  /v1/<index>/doc/<docid>    document fetch             -> {"docid", "doc"}

Dense and SSR both use ``POST /search``, so they are told apart by the port: a
server is constructed with a ``flavor`` and only answers as that backend.

The server also **records every request** (path, verb, headers, body/params) so
a test can assert what the client actually sent — the request side is half the
contract and is otherwise invisible.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# Canonical ClimbMix ids/texts, shared with tests/conftest.py's fixtures so a
# test can cross-check the dummy API against the in-process stubs.
DOCIDS = (
    "shard_00459_61697",
    "shard_01012_88420",
    "shard_00210_44018",
    "shard_00044_91812",
)
TEXTS = (
    "Congestion pricing dedicates toll revenue to the MTA capital plan.",
    "Most peak-period drivers into the zone have higher household incomes.",
    "Air-quality monitoring in the Bronx was written into the assessment.",
    "Oversight provisions require reporting capital spending against the plan.",
)


def _payload(flavor: str, query: str, k: int) -> dict[str, Any]:
    """Build a response in ``flavor``'s documented format.

    Each branch mirrors the shape its client parses — see the module docstring.
    Scores descend so rank order is unambiguous, and ``k`` is honoured so a test
    can assert the client passed it through.
    """
    n = max(0, min(k, len(DOCIDS)))
    rows = [(DOCIDS[i], round(12.5 - i, 4), i + 1, TEXTS[i]) for i in range(n)]

    if flavor == "dense":
        return {"hits": [{"docid": d, "score": s, "rank": r, "text": t}
                         for d, s, r, t in rows]}
    if flavor == "sparse":
        # Anserini index-server answers in Elasticsearch envelope form.
        return {"hits": {"hits": [
            {"_id": d, "_score": s, "_index": "climbmix-bm25",
             "_source": {"contents": t}}
            for d, s, _r, t in rows]}}
    if flavor == "ssr":
        # Cottontail exposes no numeric score; the client synthesizes 1/rank.
        return {"results": [{"docno": d, "rank": r, "snippet": t,
                             "burrow": f"burrow_{r:02d}"}
                            for d, _s, r, t in rows]}
    if flavor == "pyserini":
        return {"api": "v1", "index": "climbmix-400b",
                "query": {"text": query},
                "candidates": [{"docid": d, "rank": r, "score": s, "doc": t}
                               for d, s, r, t in rows]}
    raise ValueError(f"unknown flavor: {flavor!r}")


class DummyClimbMixAPI:
    """A threaded HTTP server impersonating one backend flavor.

    Use as a context manager; ``base_url`` is what the client's ``*_SEARCH_URL``
    env var should be set to.

        with DummyClimbMixAPI("dense") as api:
            monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
            hits = search_dense("q", k=3)
            assert api.requests[0]["path"] == "/search"
    """

    def __init__(self, flavor: str = "dense", *,
                 doc_as_object: bool = False,
                 require_auth: bool = False,
                 status: int = 200,
                 fail_times: int = 0,
                 fail_status: int = 429,
                 retry_after: str | None = None) -> None:
        self.flavor = flavor
        self.doc_as_object = doc_as_object
        self.require_auth = require_auth
        self.status = status
        # Rate-limit emulation: answer the first ``fail_times`` requests with
        # ``fail_status`` (optionally carrying ``Retry-After``), then behave
        # normally — so a test can assert the client retried rather than giving
        # up, and that it eventually got the real payload.
        self.fail_times = fail_times
        self.fail_status = fail_status
        self.retry_after = retry_after
        self.requests: list[dict[str, Any]] = []
        # The handler runs on the server thread while the test asserts on the
        # main one, so the countdown needs a lock even though the two never
        # overlap in a single-request test.
        self._fail_lock = threading.Lock()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> DummyClimbMixAPI:
        api = self

        class Handler(BaseHTTPRequestHandler):
            # Silence the default stderr access log — pytest output stays clean.
            def log_message(self, *a: Any) -> None:  # noqa: ANN401
                pass

            def _record(self, verb: str, body: Any, params: dict[str, Any]
                        ) -> None:
                api.requests.append({
                    "verb": verb,
                    "path": urllib.parse.urlparse(self.path).path,
                    "raw_path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                    "params": params,
                })

            def _send(self, obj: Any, status: int | None = None,
                      extra_headers: dict[str, str] | None = None) -> None:
                blob = json.dumps(obj).encode()
                self.send_response(status or api.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(blob)))
                for key, value in (extra_headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(blob)

            def _rate_limited(self) -> bool:
                """Burn one of the pre-programmed failures, if any remain."""
                with api._fail_lock:
                    if api.fail_times <= 0:
                        return False
                    api.fail_times -= 1
                extra = ({"Retry-After": api.retry_after}
                         if api.retry_after is not None else None)
                self._send({"error": "slow down"}, status=api.fail_status,
                           extra_headers=extra)
                return True

            def _unauthorized(self) -> bool:
                """Emulate the hosted endpoints' 401 when auth is required."""
                if not api.require_auth:
                    return False
                if self.headers.get("Authorization"):
                    return False
                self._send({"error": "unauthorized"}, status=401)
                return True

            def do_POST(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler API)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    body = {"__raw__": raw.decode("utf-8", "replace")}
                self._record("POST", body, {})
                if self._unauthorized() or self._rate_limited():
                    return
                query = str(body.get("query", ""))
                # dense/ssr use "k", the Anserini index-server uses "hits".
                k = int(body.get("k", body.get("hits", 10)))
                self._send(_payload(api.flavor, query, k))

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                params = {key: values[0] for key, values
                          in urllib.parse.parse_qs(parsed.query).items()}
                self._record("GET", None, params)
                if self._unauthorized() or self._rate_limited():
                    return
                # GET /doc/<docid> — document fetch. The two backends differ:
                # the dense service (tasks/search_serve/scripts/server.py)
                # answers {"docid", "text"}, while hosted Pyserini answers
                # {"docid", "doc"} with `doc` a string OR a text-bearing object.
                if "/doc/" in parsed.path:
                    docid = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
                    text = TEXTS[0]
                    if api.flavor == "dense":
                        self._send({"docid": docid, "text": text})
                        return
                    self._send({
                        "api": "v1", "index": "climbmix-400b", "docid": docid,
                        # Both `doc` paths are exercised via doc_as_object.
                        "doc": {"text": text} if api.doc_as_object else text,
                    })
                    return
                # GET /v1/<index>/search — hosted Pyserini BM25.
                self._send(_payload("pyserini", params.get("query", ""),
                                    int(params.get("hits", 10))))

        # Port 0 = let the OS pick a free port, so parallel tests never collide.
        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # -- accessors ----------------------------------------------------------
    @property
    def port(self) -> int:
        assert self._server is not None, "server not started"
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def last_request(self) -> dict[str, Any]:
        assert self.requests, "no request was made"
        return self.requests[-1]
