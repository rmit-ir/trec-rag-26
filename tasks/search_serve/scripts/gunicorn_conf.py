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


_rank_counter = itertools.count()
_N_GPUS = int(os.environ.get("N_GPUS", "8"))


def pre_fork(server, worker):
    rank = next(_rank_counter)
    gpu = rank % _N_GPUS
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    server.log.info(
        f"[gunicorn] worker rank={rank} -> CUDA_VISIBLE_DEVICES={gpu}"
    )
