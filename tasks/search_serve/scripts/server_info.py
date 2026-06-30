"""Best-effort host introspection printed at server startup.

Every probe is guarded so a missing tool, denied permission, or unusual host
never blocks engine startup. Operators use the dump to verify the runtime
environment (CPU features, GPU presence, AIO budget, mount type) without
having to ssh in and run lscpu/nvidia-smi/findmnt themselves.
"""
from __future__ import annotations

import concurrent.futures as _cf
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable


# ---------------------------------------------------------------------------
# safe-probe helpers — every probe runs with a wall-clock timeout so a hung
# tool, slow filesystem, or stalled DNS never blocks server startup
# ---------------------------------------------------------------------------

# Daemon pool — threads die at interpreter exit even if a probe never returns.
_PROBE_POOL = _cf.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="server-info-probe",
)
# Default budget per Python-level probe. Subprocess-based probes use a shorter
# explicit timeout — subprocesses can be terminated cleanly via SIGKILL.
_DEFAULT_PROBE_TIMEOUT = 1.5


def safe(fn: Callable, default=None, timeout: float = _DEFAULT_PROBE_TIMEOUT):
    """Run ``fn`` with a wall-clock timeout; swallow any exception or timeout
    and return ``default``. The thread keeps running on timeout (Python can't
    kill threads), but it gets reaped at interpreter exit since the pool is
    daemonized."""
    try:
        fut = _PROBE_POOL.submit(fn)
        return fut.result(timeout=timeout)
    except _cf.TimeoutError:
        return default
    except Exception:
        return default


def _read_text(path: str) -> str:
    with open(path, "rt") as f:
        return f.read()


def _shell(cmd: list[str], timeout: float = 1.5) -> str:
    """Subprocess wrapper — SIGKILLs the child on timeout (subprocess can be
    terminated cleanly, unlike Python threads). Stderr is dropped."""
    return subprocess.check_output(cmd, timeout=timeout,
                                   stderr=subprocess.DEVNULL, text=True)


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------

def cpu_flags() -> set[str]:
    txt = safe(lambda: _read_text("/proc/cpuinfo"), default="") or ""
    for line in txt.splitlines():
        if line.startswith("flags") and ":" in line:
            return set(line.split(":", 1)[1].split())
    return set()


def cpu_model() -> str | None:
    txt = safe(lambda: _read_text("/proc/cpuinfo"), default="") or ""
    for line in txt.splitlines():
        if line.startswith("model name") and ":" in line:
            return line.split(":", 1)[1].strip()
    return None


def numa_topology() -> dict[int, str]:
    """Returns {node_id: cpulist} (e.g. {0: '0-27,56-83'}). Empty if unknown."""
    base = Path("/sys/devices/system/node")
    if not base.exists():
        return {}
    out: dict[int, str] = {}
    for p in sorted(base.glob("node*")):
        if p.name[4:].isdigit():
            txt = safe(lambda p=p: (p / "cpulist").read_text().strip(), default="")
            if txt:
                out[int(p.name[4:])] = txt
    return out


def _meminfo_kv() -> dict[str, str]:
    txt = safe(lambda: _read_text("/proc/meminfo"), default="") or ""
    out = {}
    for line in txt.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def memory_mb() -> dict[str, int | None]:
    info = _meminfo_kv()
    def kb_to_mb(s: str) -> int | None:
        return safe(lambda: int(s.split()[0]) // 1024)
    return {
        "total": kb_to_mb(info.get("MemTotal", "0")),
        "available": kb_to_mb(info.get("MemAvailable", "0")),
        "shmem": kb_to_mb(info.get("Shmem", "0")),
    }


def gpu_info() -> dict:
    """Prefer torch (reflects our venv), fall back to nvidia-smi."""
    try:
        import torch
        if torch.cuda.is_available():
            devs = []
            for i in range(torch.cuda.device_count()):
                p = torch.cuda.get_device_properties(i)
                devs.append({"index": i, "name": torch.cuda.get_device_name(i),
                             "total_mb": p.total_memory // (1 << 20)})
            return {"backend": "cuda", "devices": devs}
    except Exception:
        pass
    smi = safe(lambda: _shell(["nvidia-smi", "-L"]))
    if smi:
        return {"backend": "nvidia-smi",
                "devices": [{"raw": ln.strip()} for ln in smi.splitlines() if ln.strip()]}
    return {"backend": None, "devices": []}


def disk_info(path: Path) -> dict:
    """Mount, total/free, fstype, and best-effort media (rotational/model) for ONE path."""
    try:
        st = shutil.disk_usage(path)
    except Exception:
        return {"path": str(path), "error": "stat failed"}
    info: dict = {
        "path": str(path),
        "total_gb": st.total // (1 << 30),
        "free_gb": st.free // (1 << 30),
        "used_pct": round((st.used / max(st.total, 1)) * 100, 1),
    }
    mount = safe(lambda: _shell(["findmnt", "-no", "SOURCE,FSTYPE", str(path)]))
    if mount:
        parts = mount.split()
        if len(parts) >= 2:
            info["source"], info["fstype"] = parts[0], parts[1]
        src = info.get("source", "")
        out = safe(lambda: _shell(["lsblk", "-no", "ROTA,MODEL,TYPE", src]))
        if out:
            info["lsblk"] = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return info


def aio_slots() -> dict:
    used = safe(lambda: int(_read_text("/proc/sys/fs/aio-nr").strip()))
    cap = safe(lambda: int(_read_text("/proc/sys/fs/aio-max-nr").strip()))
    free = (cap - used) if (isinstance(used, int) and isinstance(cap, int)) else None
    return {"used": used, "cap": cap, "free": free}


def open_files_limit() -> dict:
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return {"soft": soft, "hard": hard}
    except Exception:
        return {}


def env_threading() -> dict[str, str | None]:
    return {k: os.environ.get(k) for k in
            ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "OPENBLAS_NUM_THREADS", "TORCH_NUM_THREADS")}


def torch_threads() -> int | None:
    return safe(lambda: __import__("torch").get_num_threads())


def _module_version(name: str) -> str | None:
    import importlib
    m = importlib.import_module(name)
    return getattr(m, "__version__", "?")


def versions() -> dict[str, str | None]:
    """Probe each module's __version__ behind a per-module timeout, so a slow
    import (e.g. torch's CUDA init on first use) can't stall startup."""
    out: dict[str, str | None] = {"python": sys.version.split()[0]}
    for mod in ("torch", "numpy", "sentence_transformers", "diskannpy",
                "zstandard", "fastapi", "uvicorn"):
        # Most imports are cached by the time we get here, but the first call
        # to torch can take a few seconds. Cap each one independently.
        out[mod] = safe(lambda m=mod: _module_version(m), timeout=3.0)
    return out


# ---------------------------------------------------------------------------
# Aggregate + print
# ---------------------------------------------------------------------------

def collect(index_path: Path | None = None) -> dict:
    """Aggregate every probe. NEVER raises — caller can serve this on /health."""
    flags = cpu_flags()
    return {
        "host": {
            "hostname": safe(socket.gethostname),
            "fqdn": safe(socket.getfqdn),
            "platform": safe(platform.platform),
            "kernel": safe(lambda: " ".join(os.uname()[:3])),
        },
        "cpu": {
            "model": cpu_model(),
            "logical_cpus": safe(os.cpu_count),
            "numa_nodes": numa_topology(),
            "supports_amx_tile": "amx_tile" in flags,
            "supports_amx_bf16": "amx_bf16" in flags,
            "supports_amx_int8": "amx_int8" in flags,
            "supports_avx512": any(f.startswith("avx512") for f in flags),
            "supports_avx512_bf16": "avx512_bf16" in flags,
            "supports_avx512_vnni": "avx512_vnni" in flags,
        },
        "memory_mb": memory_mb(),
        "gpu": gpu_info(),
        "disk": disk_info(index_path) if index_path else None,
        "aio_slots": aio_slots(),
        "open_files_limit": open_files_limit(),
        "torch_threads": torch_threads(),
        "env_threading": env_threading(),
        "versions": versions(),
    }


def _line(s: str) -> None:
    print(s, flush=True)


def _accel_summary(cpu: dict) -> str:
    flags = [k.replace("supports_", "")
             for k, v in cpu.items() if k.startswith("supports_") and v]
    return ", ".join(flags) or "(no AMX/AVX-512 detected)"


def _format_gpu_lines(gpu: dict) -> list[str]:
    if not gpu["devices"]:
        return [f"  gpu         : none detected (CPU-only inference)"]
    out = [f"  gpu         : {gpu['backend']} — {len(gpu['devices'])} device(s)"]
    for d in gpu["devices"]:
        if "name" in d:
            out.append(f"                [{d['index']}] {d['name']} ({d['total_mb']} MB)")
        else:
            out.append(f"                {d.get('raw', d)}")
    return out


def _format_disk(d: dict | None) -> str | None:
    if not d:
        return None
    rota = f"  ({d['lsblk'][0]})" if "lsblk" in d else ""
    return (f"{d.get('path')}  total={d.get('total_gb')} GB  "
            f"free={d.get('free_gb')} GB  fs={d.get('fstype')}{rota}")


def print_info(info: dict) -> None:
    """Render the dict from collect() as a human-readable block."""
    _line("=" * 78)
    _line("[server-info]")
    _line("=" * 78)
    host = info["host"]
    _line(f"  host        : {host['fqdn']}  ({host['platform']})")
    cpu = info["cpu"]
    _line(f"  cpu         : {cpu['model']}")
    _line(f"                {cpu['logical_cpus']} logical CPUs, "
          f"NUMA nodes={list(cpu['numa_nodes'].keys()) or '?'}")
    _line(f"                hw accel: {_accel_summary(cpu)}")
    mem = info["memory_mb"]
    _line(f"  memory      : {mem['total']} MB total, {mem['available']} MB available, "
          f"{mem['shmem']} MB shmem")
    for line in _format_gpu_lines(info['gpu']):
        _line(line)
    aio = info["aio_slots"]
    _line(f"  aio slots   : used={aio['used']} / cap={aio['cap']} (free={aio['free']})")
    ofl = info["open_files_limit"]
    if ofl:
        _line(f"  open files  : soft={ofl['soft']}, hard={ofl['hard']}")
    _line(f"  threading   : torch_threads={info['torch_threads']}  "
          f"env={ {k: v for k, v in info['env_threading'].items() if v} }")
    disk_line = _format_disk(info["disk"])
    if disk_line:
        _line(f"  index disk  : {disk_line}")
    v = info["versions"]
    versions_str = ", ".join(f"{k}={v[k]}" for k in
                              ("python", "torch", "numpy", "sentence_transformers",
                               "diskannpy", "zstandard", "fastapi", "uvicorn")
                              if v.get(k))
    _line(f"  versions    : {versions_str}")
    _line("=" * 78)


def print_server_info(index_path: Path | None = None) -> dict:
    """Collect + print + return the env summary. Never raises."""
    info = collect(index_path)
    try:
        print_info(info)
    except Exception as e:
        print(f"[server-info] print failed (continuing): {e!r}",
              file=sys.stderr, flush=True)
    return info
