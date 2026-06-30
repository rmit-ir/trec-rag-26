"""One-shot startup banner printed when the search engine is up.

Reads index metadata (encoding_meta.json, index_meta.json,
docstore/manifest.json) and writes a single clean summary block so an
operator sees the bind address, worker layout, index stats, a copy-pasteable
curl example, and the endpoint list without having to scroll through 8
workers' worth of init logs.

Used by gunicorn_conf.py:when_ready (master, once for the whole server)
and by server.py:lifespan (uvicorn-direct, once per process). Sets
``_STARTUP_BANNER_PRINTED=1`` so the second caller skips its print.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


_BOX_W = 78


def _line(s: str = "") -> None:
    print(s, flush=True)


def _hr() -> None:
    _line("=" * _BOX_W)


def _safe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _gunicorn_summary(cfg) -> dict:
    """Pluck just the launch knobs from gunicorn.config.Config that
    operators usually want to confirm at start time."""
    try:
        return {
            "bind": list(cfg.bind),
            "workers": cfg.workers,
            "worker_class": cfg.worker_class_str,
            "timeout": cfg.timeout,
        }
    except Exception:
        return {}


def _env_summary() -> dict:
    keys = (
        "INDEX_DIR", "SEARCH_DEVICE", "SEARCH_DTYPE",
        "DISKANN_THREADS", "DOCSTORE_LRU", "SEARCH_INFLIGHT_PER_WORKER",
        "DOCSTORE_PARALLEL", "DOCSTORE_PARALLEL_MIN_K",
        "WARMUP", "WARMUP_MADVISE_OFFSETS", "WARMUP_MADVISE_PQ",
        "OMP_NUM_THREADS", "MKL_NUM_THREADS",
    )
    return {k: os.environ.get(k) for k in keys}


# ---------------------------------------------------------------------------
# Disk-read estimate from static file inspection
# ---------------------------------------------------------------------------

def _filesize(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def disk_read_summary(index_dir: Path) -> dict:
    """Static analysis of how much data engine load will read from disk and
    how much of that ends up in process RAM. Returns ``files`` + totals
    (bytes). No actual reads happen here — safe to call from the master
    process before workers fork.

    "in_ram" classification:
      - True  ==> deserialised into process memory (DiskANN data structures,
                  Python lists, model weights). Shows up in process RSS.
      - False ==> mmap'd lazily or only seeded into kernel page cache via
                  madvise WILLNEED. Doesn't add to per-process RSS;
                  shared across workers.
    """
    ds_dir = index_dir / "docstore"

    fully_read_in_ram = [
        # DiskANN files that get pulled fully into aligned memory at load
        "ann_pq_compressed.bin",
        "ann_pq_pivots.bin",
        "ann_disk.index_pq_pivots.bin",
        "ann_metadata.bin",
        "ann_disk.index_medoids.bin",
        "ann_disk.index_centroids.bin",
        "ann_disk.index_max_base_norm.bin",
        "ann_sample_data.bin",
        "docids.txt",                            # deserialized to Python list
        "encoding_meta.json", "index_meta.json", # tiny
    ]
    files: list[dict] = []
    for name in fully_read_in_ram:
        sz = _filesize(index_dir / name)
        if sz:
            files.append({"name": name, "bytes": sz, "in_ram": True})

    # docstore manifest + dict (in-ram)
    files.append({"name": "docstore/zstd.dict",
                  "bytes": _filesize(ds_dir / "zstd.dict"), "in_ram": True})
    files.append({"name": "docstore/manifest.json",
                  "bytes": _filesize(ds_dir / "manifest.json"), "in_ram": True})

    # docstore offsets — madvise(WILLNEED), populates kernel page cache only
    n_off = 0
    bytes_off = 0
    for p in ds_dir.glob("*.offsets.bin"):
        sz = _filesize(p)
        if sz:
            bytes_off += sz
            n_off += 1
    if n_off:
        files.append({"name": f"{n_off:,} × docstore/*.offsets.bin "
                              f"(madvise WILLNEED)",
                      "bytes": bytes_off, "in_ram": False})

    # The graph file is mmap'd and largely lazy. DiskANN does eagerly touch
    # the "cache list" (~num_nodes_to_cache nodes) — estimated ~500 MB on a
    # cache size of 10 000. We bill that to "read but NOT held in process
    # RAM" (the cache lives in scratch buffers, but most graph pages don't
    # come into the process at all).
    graph_total = _filesize(index_dir / "ann_disk.index")
    if graph_total:
        files.append({"name": "ann_disk.index (graph; ~500 MB eager, rest "
                              "lazy mmap)",
                      "bytes": min(500 * 1024 * 1024, graph_total),
                      "in_ram": False})

    total_read = sum(f["bytes"] for f in files)
    total_in_ram = sum(f["bytes"] for f in files if f["in_ram"])
    return {
        "files": files,
        "total_bytes_read": total_read,
        "bytes_in_process_ram": total_in_ram,
        "n_offsets_files": n_off,
        "graph_total_bytes": graph_total,
    }


def process_rss_bytes() -> int:
    """Process VmRSS in bytes. Returns 0 on non-Linux or unreadable."""
    try:
        with open("/proc/self/status", "rt") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024  # KB -> bytes
    except OSError:
        return 0
    return 0


def _humansize(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def _index_summary(index_dir: Path) -> dict:
    enc = _safe_json(index_dir / "encoding_meta.json")
    idx = _safe_json(index_dir / "index_meta.json")
    ds = _safe_json(index_dir / "docstore" / "manifest.json")
    return {
        "model": enc.get("model"),
        "dim": enc.get("dim"),
        "task": enc.get("task"),
        "query_prompt": enc.get("query_prompt_name"),
        "n_docs": idx.get("n"),
        "metric": idx.get("metric"),
        "kind": idx.get("kind"),
        "graph_degree": idx.get("graph_degree"),
        "complexity": idx.get("complexity"),
        "docstore_compression": ds.get("compression"),
        "docstore_ratio": ds.get("ratio_x"),
        "n_shards": ds.get("n_shards"),
    }


def _example_curl(bind: list[str]) -> str:
    host_port = bind[0] if bind else "0.0.0.0:8000"
    # Substitute 0.0.0.0 with 127.0.0.1 for a runnable client target.
    host_port = host_port.replace("0.0.0.0", "127.0.0.1")
    return (
        f"curl -X POST http://{host_port}/search \\\n"
        f"  -H 'content-type: application/json' \\\n"
        f"  -d '{{\"query\":\"transformers explained\",\"k\":5,"
        f"\"with_text\":true}}'"
    )


def print_startup_banner(cfg=None) -> None:
    """Print the banner once. Idempotent across processes via env sentinel."""
    if os.environ.get("_STARTUP_BANNER_PRINTED") == "1":
        return
    gu = _gunicorn_summary(cfg) if cfg is not None else {}
    env = _env_summary()
    idx_dir = env.get("INDEX_DIR") or "(INDEX_DIR not set)"
    idx = _index_summary(Path(idx_dir)) if env.get("INDEX_DIR") else {}

    _hr()
    _line("[server-ready]")
    _hr()
    if gu:
        binds = ", ".join(gu.get("bind") or [])
        _line(f"  bind         : {binds}")
        _line(f"  workers      : {gu.get('workers')} "
              f"({gu.get('worker_class')}, timeout {gu.get('timeout')}s)")
    _line(f"  device       : {env.get('SEARCH_DEVICE') or 'auto'}  "
          f"dtype={env.get('SEARCH_DTYPE') or 'auto'}")
    _line(f"  diskann      : threads={env.get('DISKANN_THREADS') or '4'}  "
          f"docstore_lru={env.get('DOCSTORE_LRU') or '1024'}  "
          f"in-flight/worker={env.get('SEARCH_INFLIGHT_PER_WORKER') or '1'}")
    _line(f"  docstore par : parallel={env.get('DOCSTORE_PARALLEL') or '8'}  "
          f"min_k={env.get('DOCSTORE_PARALLEL_MIN_K') or '64'}")
    if env.get("OMP_NUM_THREADS"):
        _line(f"  threading    : OMP_NUM_THREADS={env['OMP_NUM_THREADS']}  "
              f"MKL_NUM_THREADS={env.get('MKL_NUM_THREADS') or '-'}")
    _line(f"  warmup       : enabled={env.get('WARMUP') or 'true'}  "
          f"madvise_offsets={env.get('WARMUP_MADVISE_OFFSETS') or 'true'}  "
          f"madvise_pq={env.get('WARMUP_MADVISE_PQ') or 'false'}")
    _line()
    _line(f"  index dir    : {idx_dir}")
    if idx.get("n_docs"):
        _line(f"    n_docs     : {idx['n_docs']:,}")
        _line(f"    dim        : {idx.get('dim')}  metric={idx.get('metric')}  "
              f"kind={idx.get('kind')}  R={idx.get('graph_degree')}  "
              f"L={idx.get('complexity')}")
        _line(f"    model      : {idx.get('model')}")
        _line(f"    task       : {idx.get('task')!r}  "
              f"q_prompt={idx.get('query_prompt')!r}")
    if idx.get("n_shards"):
        ratio = idx.get("docstore_ratio")
        ratio_s = f"{ratio:.2f}x" if isinstance(ratio, (int, float)) else "?"
        _line(f"    docstore   : {idx.get('docstore_compression')}  "
              f"ratio={ratio_s}  n_shards={idx['n_shards']:,}")
    if env.get("INDEX_DIR"):
        ds = disk_read_summary(Path(env["INDEX_DIR"]))
        rss = process_rss_bytes()
        _line()
        _line(f"  disk reads at startup (per worker, cold cache):")
        _line(f"    total read       : {_humansize(ds['total_bytes_read'])}")
        _line(f"    held in process RAM   : "
              f"{_humansize(ds['bytes_in_process_ram'])}")
        if rss > 0:
            _line(f"    current process RSS   : {_humansize(rss)}  "
                  f"(this banner process; workers' RSS will differ post-load)")
    _line()
    _line("  Note: workers may still be loading. Poll /health until")
    _line("        status == \"ok\" before sending real traffic.")
    _line()
    _line("  Try it:")
    for ln in _example_curl(gu.get("bind") or []).splitlines():
        _line(f"    {ln}")
    _line()
    _line("  Endpoints:")
    _line("    GET  /                    -- liveness only")
    _line("    GET  /health              -- readiness + index metadata")
    _line("    GET  /server-info         -- host introspection (cached)")
    _line("    POST /search              -- single query (JSON body)")
    _line("    GET  /search              -- single query (query params)")
    _line("    POST /search/batch        -- up to 64 queries per call")
    _line("    GET  /docs                -- Swagger UI")
    _hr()
    os.environ["_STARTUP_BANNER_PRINTED"] = "1"
