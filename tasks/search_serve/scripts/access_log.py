"""Per-process access logger for search-serve.

Writes one JSON line per search — ``{"ts", "query", "docids"}`` — to
``tasks/search_serve/logs/access-logs-<ISO8601>-pid<pid>.log``.

Under multi-worker gunicorn each worker process opens its OWN file: the ISO8601
start time identifies the run and the ``pid`` suffix keeps concurrent workers
from corrupting a shared file (JSON lines for large ``k`` exceed the atomic
append size). Each file is an independent, tail-able JSONL stream.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# tasks/search_serve/logs, regardless of the process working directory.
_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "logs"


def _iso(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


class AccessLog:
    """Append-only JSONL access log for one process. Best-effort: any I/O error
    disables logging rather than failing a request."""

    def __init__(self, log_dir: str | os.PathLike | None = None):
        self._lock = threading.Lock()
        self._fh = None
        self.path: Path | None = None
        try:
            d = Path(log_dir or os.environ.get("ACCESS_LOG_DIR", _DEFAULT_DIR))
            d.mkdir(parents=True, exist_ok=True)
            stamp = _iso(datetime.now(timezone.utc).replace(microsecond=0))
            self.path = d / f"access-logs-{stamp}-pid{os.getpid()}.log"
            self._fh = open(self.path, "a", encoding="utf-8")
        except OSError as e:  # keep serving even if logging can't open
            print(f"[access_log] disabled — could not open log: {e}", flush=True)

    def log(self, query: str, docids: Iterable[str]) -> None:
        if self._fh is None:
            return
        line = json.dumps(
            {"ts": _iso(datetime.now(timezone.utc)), "query": query,
             "docids": list(docids)},
            ensure_ascii=False)
        try:
            with self._lock:
                self._fh.write(line + "\n")
                self._fh.flush()
        except OSError as e:
            print(f"[access_log] write failed: {e}", flush=True)

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None


_access_log: AccessLog | None = None
_init_lock = threading.Lock()


def get_access_log() -> AccessLog:
    """Lazily create the per-process logger on first use (after gunicorn fork, so
    the pid/file are the worker's)."""
    global _access_log
    if _access_log is None:
        with _init_lock:
            if _access_log is None:
                _access_log = AccessLog()
    return _access_log
