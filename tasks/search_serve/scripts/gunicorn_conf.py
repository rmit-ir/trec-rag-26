"""Gunicorn config that pins each worker to a distinct CUDA device.

Each worker process gets ``CUDA_VISIBLE_DEVICES`` set to its rank-modulo-N
in ``pre_fork`` (which runs in the master, before that worker is forked).
The mutation is made on the master's os.environ and inherited by the child
at fork-time; the next ``pre_fork`` invocation overwrites it for the next
worker. With this setup every worker sees its assigned GPU as ``cuda:0``,
so the engine config can stay ``SEARCH_DEVICE=cuda:0`` regardless of how
many workers run.

Env knobs read here:
  N_GPUS   number of visible CUDA devices to round-robin across (default 8)

Usage:
  INDEX_DIR=... SEARCH_DEVICE=cuda:0 \\
    uv run --project tasks/search_serve gunicorn \\
      --chdir tasks/search_serve/scripts \\
      -c gunicorn_conf.py \\
      -k uvicorn.workers.UvicornWorker \\
      -w 8 -b 127.0.0.1:8000 \\
      --timeout 600 server:app
"""
from __future__ import annotations

import itertools
import os
import sys


_rank_counter = itertools.count()
_N_GPUS = int(os.environ.get("N_GPUS", "8"))
_IS_CPU_MODE = os.environ.get("SEARCH_DEVICE", "").lower().startswith("cpu")


def on_starting(server):
    """Runs once in the master, before any worker fork. Print server-info
    here so workers don't each spew a redundant copy of the same dump.
    Sets a sentinel env var so worker-side `SearchEngine.load()` knows to
    skip its own print."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from pathlib import Path
        from server_info import print_server_info
        idx = os.environ.get("INDEX_DIR")
        print_server_info(index_path=Path(idx) if idx else None)
    except Exception as e:
        server.log.warning(f"[gunicorn] server-info print failed: {e!r}")
    os.environ["_SERVER_INFO_PRINTED"] = "1"


def pre_fork(server, worker):
    """Assign this worker its CPU/GPU pinning before fork. The os.environ
    mutation is inherited by the child at fork time; the next pre_fork
    invocation overwrites it for the next worker."""
    rank = next(_rank_counter)
    if _IS_CPU_MODE:
        # CPU mode: hide CUDA entirely so torch never allocates a driver
        # context. Mirrors server.py's preamble.
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        server.log.info(
            f"[gunicorn] worker rank={rank} -> CUDA_VISIBLE_DEVICES=\"\" (CPU mode)"
        )
    else:
        gpu = rank % _N_GPUS
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
        server.log.info(
            f"[gunicorn] worker rank={rank} -> CUDA_VISIBLE_DEVICES={gpu}"
        )


def when_ready(server):
    """Runs once in the master after the listening socket is bound and all
    workers have been launched. Print a single startup banner here so the
    operator gets one clean summary instead of N per-worker pieces."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from startup_banner import print_startup_banner
        print_startup_banner(server.cfg)
    except Exception as e:
        server.log.warning(f"[gunicorn] startup banner failed: {e!r}")
    os.environ["_STARTUP_BANNER_PRINTED"] = "1"
