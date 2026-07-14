"""System-RAM watchdog: force-kill the whole serve when memory runs out.

Motivation: engine load is ~74 GB resident PER WORKER on the climbmix-full
index (PQ table + docids + model), so `-w 8` needs ~600 GB — launching that
on a smaller box drives the machine into swap/OOM long before the kernel's
OOM killer picks sensible victims. This watchdog polls /proc/meminfo and,
when system memory usage crosses a threshold, SIGTERMs the server's whole
process group (master + all workers), escalating to SIGKILL after a grace
period.

Usage: `start_from_env(label)` — reads env knobs and starts a daemon thread
(no-op if RAM_WATCHDOG is false). Called from both the gunicorn master
(gunicorn_conf.when_ready) and each worker/standalone-uvicorn process
(server.py import time); any one of them can pull the trigger, and killpg
takes everything down together.

Env knobs:
  RAM_WATCHDOG            default true
  RAM_KILL_FRACTION       kill threshold as fraction of MemTotal, default 0.70
  RAM_WATCHDOG_INTERVAL   poll seconds, default 2
  RAM_WATCHDOG_GRACE      SIGTERM->SIGKILL escalation seconds, default 15

Usage is measured as 1 - MemAvailable/MemTotal (page cache does not count
against us, so mmap'd index files never trip it — only real allocations do).
"""
from __future__ import annotations

import os
import signal
import threading
import time

_started = False


def mem_usage() -> tuple[float, int, int]:
    """Return (used_fraction, total_kb, available_kb) from /proc/meminfo."""
    total = avail = None
    with open("/proc/meminfo", "rt") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
            if total is not None and avail is not None:
                break
    if not total or avail is None:
        raise RuntimeError("could not parse /proc/meminfo")
    return 1.0 - avail / total, total, avail


def _kill_group(threshold: float, grace: float, label: str) -> None:
    pgid = os.getpgrp()
    usage, total, avail = mem_usage()
    print(f"[{label}] RAM {usage:.0%} >= kill threshold {threshold:.0%} "
          f"(available {avail // 2**20} GiB of {total // 2**20} GiB) — "
          f"SIGTERM to process group {pgid}, SIGKILL in {grace:.0f}s",
          flush=True)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(grace)
    # Still alive: shutdown is stuck (likely thrashing). No mercy.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        os.kill(os.getpid(), signal.SIGKILL)


def start(threshold: float = 0.70, interval: float = 2.0,
          grace: float = 15.0, label: str = "ram-watchdog") -> threading.Thread:
    def _loop() -> None:
        warn_at = max(threshold - 0.10, 0.0)
        warned = False
        while True:
            try:
                usage, _, avail = mem_usage()
            except Exception:
                time.sleep(interval)
                continue
            if usage >= threshold:
                _kill_group(threshold, grace, label)
                return
            if usage >= warn_at and not warned:
                print(f"[{label}] WARNING RAM {usage:.0%} "
                      f"(kill at {threshold:.0%}, {avail // 2**20} GiB left)",
                      flush=True)
                warned = True
            elif usage < warn_at - 0.05:
                warned = False
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name=label)
    t.start()
    return t


def start_from_env(label: str) -> threading.Thread | None:
    """Start the watchdog per env config. Idempotent per process."""
    global _started
    if _started:
        return None
    enabled = os.environ.get("RAM_WATCHDOG", "true").lower() in ("1", "true", "yes", "y")
    if not enabled:
        return None
    threshold = float(os.environ.get("RAM_KILL_FRACTION", "0.70"))
    interval = float(os.environ.get("RAM_WATCHDOG_INTERVAL", "2"))
    grace = float(os.environ.get("RAM_WATCHDOG_GRACE", "15"))
    _started = True
    usage, total, _ = mem_usage()
    print(f"[{label}] armed: kill at {threshold:.0%} of "
          f"{total // 2**20} GiB (now {usage:.0%}), poll {interval:g}s",
          flush=True)
    return start(threshold, interval, grace, label)
