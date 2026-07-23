"""SsrEngine — manage a Cottontail ``ssr-server`` subprocess and speak its
newline-delimited JSON protocol.

The paper's stack (arXiv 2607.11362) is Cottontail's annotative index +
Shortest-Substring Ranking (SSR), driven by GCL Boolean queries. Cottontail
ships ``apps/ssr-server`` which:

- binds an *automatic* loopback TCP port (port 0) and prints
  ``listening on port N`` to stderr;
- is **single-client and serial** — it accepts one connection, serves it until
  close, then accepts the next. So we hold one long-lived connection and
  serialize all requests through it under a lock;
- speaks newline JSON. Each reply line is
  ``{"query": <request>, "response": {...}, "time": <ms>}``. The useful payload
  is ``record["response"]`` with fields ``op, ok`` and, on success,
  ``qid, rank, burrow, docno, snippet`` (or ``done: true`` when a result set is
  exhausted / empty). ``document`` replies carry ``document`` instead of
  ``snippet``.

Long-term-serving / RAM notes (see README):

- The index itself (a Hazel/Simple burrow) is memory-mapped, so its RAM cost is
  page-cache, not heap — the kernel evicts cold pages under pressure. That is
  what makes a huge corpus servable.
- ssr-server keeps **every** query's result vector (≤1000 rows) in a server-side
  map with no eviction. Over a long-lived process that is an unbounded leak.
  We bound it two ways here: (1) an LRU cache of assembled top-k results keyed by
  ``(query, k)`` so repeated queries never mint a new server qid, and
  (2) a watchdog that transparently restarts the subprocess after
  ``restart_after`` *distinct* queries, dropping all server-side qid state.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
ENV = ROOT / "tasks/ssr_search/env"
DEFAULT_SERVER_BIN = ROOT / "tmp/Cottontail/bazel-bin/apps/ssr-server"

# GCL structure queries for a JSONL corpus built by Cottontail's ``jsonl`` app
# (records like {"id": "...", "contents": "..."}). ``:`` is the whole JSON
# object (the document/container), ``:contents:`` the searchable body that SSR
# ranks over, ``:id:`` the docno field.
DEFAULT_CONTAINER = ":"
DEFAULT_CONTENT = ":contents:"
DEFAULT_DOCNO = ":id:"

_PORT_RE = re.compile(r"listening on port (\d+)")


@dataclass
class SsrHit:
    rank: int
    docno: str
    snippet: str
    burrow: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "docno": self.docno,
                "snippet": self.snippet, "burrow": self.burrow}


@dataclass
class SsrEngine:
    """Owns an ``ssr-server`` subprocess + its socket. Thread-safe: every
    protocol exchange is serialized under ``_lock``."""

    burrows: list[str]
    container: str = DEFAULT_CONTAINER
    content: str = DEFAULT_CONTENT
    docno: str = DEFAULT_DOCNO
    fields: Optional[str] = None            # optional --fields for /document
    server_bin: Path = DEFAULT_SERVER_BIN
    cache_size: int = 4096                  # LRU entries (query,k) -> hits
    restart_after: int = 20000              # distinct queries before restart
    connect_timeout: float = 30.0

    _proc: Optional[subprocess.Popen] = field(default=None, init=False)
    _sock: Optional[socket.socket] = field(default=None, init=False)
    _stream: Any = field(default=None, init=False)
    _port: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _cache: "OrderedDict[str, list[SsrHit]]" = field(default_factory=OrderedDict, init=False)
    _distinct: int = field(default=0, init=False)

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            self._spawn()

    def _spawn(self) -> None:
        env = dict(os.environ)
        # ssr-server is built with the conda gcc-13 toolchain; it needs that
        # libstdc++ at runtime (system gcc-8.5 libstdc++ is too old for C++20).
        env["LD_LIBRARY_PATH"] = f"{ENV/'lib'}:" + env.get("LD_LIBRARY_PATH", "")
        args = [str(self.server_bin)]
        if self.fields:
            args += ["--fields", self.fields]
        args += [self.container, self.content, self.docno, *self.burrows]
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env=env, text=True, bufsize=1)
        # Read stderr until it announces its port (or dies).
        deadline = time.time() + self.connect_timeout
        port = 0
        assert self._proc.stderr is not None
        while time.time() < deadline:
            line = self._proc.stderr.readline()
            if line == "" and self._proc.poll() is not None:
                raise RuntimeError("ssr-server exited before listening")
            m = _PORT_RE.search(line)
            if m:
                port = int(m.group(1))
                break
        if not port:
            raise RuntimeError("ssr-server did not report a port in time")
        self._port = port
        # Drain remaining stderr in the background so the pipe never blocks.
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        s = socket.create_connection(("127.0.0.1", port), timeout=self.connect_timeout)
        self._sock = s
        self._stream = s.makefile("rwb")

    def _drain_stderr(self) -> None:
        p = self._proc
        if p is None or p.stderr is None:
            return
        for _ in p.stderr:
            pass

    def close(self) -> None:
        with self._lock:
            self._teardown()

    def _teardown(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
        except OSError:
            pass
        try:
            if self._sock is not None:
                self._sock.close()
        except OSError:
            pass
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = self._sock = self._stream = None

    @property
    def port(self) -> int:
        return self._port

    # ---- protocol --------------------------------------------------------
    def _exchange(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send one request, return the ``response`` sub-object. Caller holds
        the lock."""
        if self._stream is None:
            self._spawn()
        assert self._stream is not None
        line = json.dumps(request, separators=(",", ":")) + "\n"
        self._stream.write(line.encode("utf-8"))
        self._stream.flush()
        raw = self._stream.readline()
        if not raw:
            raise RuntimeError("ssr-server connection closed")
        record = json.loads(raw.decode("utf-8"))
        return record.get("response", {})

    # ---- public API ------------------------------------------------------
    def search(self, query: str, k: int = 10) -> list[SsrHit]:
        """Run a GCL query and return up to ``k`` ranked hits (drains the
        server's query/next pagination in one shot). LRU-cached."""
        key = f"{k}\x00{query}"
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
            if self._distinct >= self.restart_after:
                self._teardown()
                self._spawn()
                self._distinct = 0
            self._distinct += 1

            hits: list[SsrHit] = []
            resp = self._exchange({"op": "query", "query": query})
            if not resp.get("ok", False):
                raise RuntimeError(resp.get("error", "query failed"))
            qid = resp.get("qid", "")
            if not resp.get("done", False):
                hits.append(SsrHit(resp["rank"], resp["docno"], resp["snippet"],
                                   resp.get("burrow", "")))
                while len(hits) < k:
                    r = self._exchange({"op": "next", "qid": qid})
                    if not r.get("ok", False) or r.get("done", False):
                        break
                    hits.append(SsrHit(r["rank"], r["docno"], r["snippet"],
                                       r.get("burrow", "")))
            self._cache[key] = hits
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            return hits

    def document(self, docno: str) -> str:
        with self._lock:
            resp = self._exchange({"op": "document", "docno": docno})
        if not resp.get("ok", False):
            raise RuntimeError(resp.get("error", "document failed"))
        return resp.get("document", "")

    def set_optimizer(self, enabled: bool) -> bool:
        with self._lock:
            resp = self._exchange({"op": "set_optimizer", "enabled": enabled})
        return bool(resp.get("ok", False))

    def __enter__(self) -> "SsrEngine":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
