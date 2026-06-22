"""Progress / ETA helpers for the multi-GPU encoder.

Kept tiny on purpose: this module formats log lines and reads on-disk shard
state, nothing else. Importable from any sibling script in this directory.
"""
from __future__ import annotations

from pathlib import Path


def fmt_duration(seconds: float) -> str:
    if seconds is None or seconds != seconds or seconds == float("inf"):
        return "?"
    s = max(int(round(seconds)), 0)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    h, rem = divmod(s, 3600)
    return f"{h}h{rem // 60:02d}m"


def count_lines(path: Path) -> int:
    """Cheap upfront line count so per-shard progress can show X/total."""
    n = 0
    with open(path, "rb") as f:
        while True:
            buf = f.read(1 << 20)
            if not buf:
                break
            n += buf.count(b"\n")
    return n


def count_completed_shards(out_dir: Path) -> int:
    """Count shards whose final .fbin has been atomically committed."""
    return sum(1 for p in out_dir.glob("*.fbin") if not p.name.endswith(".tmp"))


def shard_progress_line(rank: int, name: str, seen: int, total: int, elapsed: float) -> str:
    rate = seen / max(elapsed, 1e-6)
    pct = (100.0 * seen / total) if total else 0.0
    eta = max(total - seen, 0) / rate if rate > 0 else float("inf")
    return (f"[worker {rank}] {name} {seen}/{total} ({pct:.1f}%) "
            f"({rate:.1f} docs/s)  shard_eta={fmt_duration(eta)}")


def shard_finished_line(
    rank: int,
    name: str,
    seen: int,
    total: int,
    elapsed: float,
    shard_idx: int,
    shards_in_worker: int,
    step_done: int,
    step_total: int,
    step_elapsed: float,
) -> str:
    rate = seen / max(elapsed, 1e-6)
    worker_pct = 100.0 * shard_idx / max(shards_in_worker, 1)
    step_rate = step_done / max(step_elapsed, 1e-6)
    step_pct = 100.0 * step_done / max(step_total, 1)
    step_eta = max(step_total - step_done, 0) / step_rate if step_rate > 0 else float("inf")
    return (f"[worker {rank}] FINISHED {name}: {seen}/{total} docs in {elapsed:.1f}s "
            f"({rate:.1f} docs/s) | worker shards {shard_idx}/{shards_in_worker} "
            f"({worker_pct:.1f}%) | step {step_done}/{step_total} ({step_pct:.1f}%) "
            f"step_eta={fmt_duration(step_eta)}")


def global_progress_line(done: int, total: int, step_elapsed: float, tag: str = "") -> str:
    pct = 100.0 * done / max(total, 1)
    rate = done / max(step_elapsed, 1e-6)
    eta = max(total - done, 0) / rate if rate > 0 else float("inf")
    suffix = f" — {tag}" if tag else ""
    return (f"[parent] global progress: {done}/{total} shards ({pct:.1f}%)  "
            f"elapsed={fmt_duration(step_elapsed)} step_eta={fmt_duration(eta)}{suffix}")
