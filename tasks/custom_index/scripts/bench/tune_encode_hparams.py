#!/usr/bin/env python3
"""Find the best batch size for an embedding model via ternary search.

Runs on **one GPU**. The encoder pipeline uses one process per GPU, so the
per-GPU throughput here is what each worker will get under the multi-GPU run.

Algorithm
---------
For each --seq-len value, do **ternary search on log(batch)**, integer-rounded:

  while log(hi) - log(lo) > eps:
      m1 = exp(log(lo) + (log(hi)-log(lo)) / 3)     # at 1/3
      m2 = exp(log(hi) - (log(hi)-log(lo)) / 3)     # at 2/3
      probe int(round(m1)) and int(round(m2))
      if f(m1) >  f(m2):  hi <- m2
      else:               lo <- m1

This works for any integer batch in [min_batch, max_batch] — not just powers
of two — and converges in ~log_3(range) probes for the (empirically
unimodal) throughput-vs-batch curve. On OOM at the top of the range, the
search rolls hi down until the call succeeds before starting.

Resource monitoring
-------------------
Per probe we capture: docs/s, peak GPU VRAM, peak host RAM RSS (background
sampler reading /proc/self/status @ 100 ms).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


def load_texts(shard: Path, n: int, seed: int = 0) -> list[str]:
    """Read the first ~3n records, then shuffle and keep n — stays
    representative even after prepare_corpus.sh starts pre-sorting by length."""
    import random
    pool: list[str] = []
    cap = max(3 * n, n + 100)
    with open(shard, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            pool.append(json.loads(line)["contents"])
            if len(pool) >= cap:
                break
    random.Random(seed).shuffle(pool)
    return pool[:n]


def read_rss_mb() -> float:
    """Resident set size (MB) from /proc/self/status (Linux, no deps)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


class RamPeak:
    """Background thread recording peak RSS during a `with` block."""
    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "RamPeak":
        self.peak_mb = read_rss_mb()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            cur = read_rss_mb()
            if cur > self.peak_mb:
                self.peak_mb = cur


@dataclass
class Probe:
    seq_len: int
    batch: int
    docs_per_s: float
    peak_vram_mb: float
    peak_ram_mb: float
    elapsed_s: float
    oom: bool
    err: str | None = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True, type=Path,
                    help="corpus-jsonl shard file to sample texts from")
    ap.add_argument("--model", required=True)
    ap.add_argument("--min-batch", type=int, required=True)
    ap.add_argument("--max-batch", type=int, required=True)
    ap.add_argument("--seq-lens", type=int, nargs="+", required=True,
                    help="run a separate ternary search at each of these seq_lens")
    ap.add_argument("--n-docs", type=int, default=2_000)
    ap.add_argument("--gpu", type=int, default=0,
                    help="CUDA device to pin via CUDA_VISIBLE_DEVICES")
    ap.add_argument("--task", default="retrieval")
    ap.add_argument("--prompt-name", default="document")
    ap.add_argument("--trust-remote-code", action="store_true", default=True)
    ap.add_argument("--dtype", default="bfloat16",
                    choices=["float32", "float16", "bfloat16"])
    ap.add_argument("--max-probes", type=int, default=10,
                    help="cap probes per seq_len (ternary normally converges in 5-7)")
    args = ap.parse_args()

    if args.min_batch < 1 or args.max_batch < args.min_batch:
        print("[tune] need 1 <= min_batch <= max_batch", file=sys.stderr)
        return 2

    # Pin to one GPU before importing torch.
    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)

    import torch
    from sentence_transformers import SentenceTransformer

    if not torch.cuda.is_available():
        print("[tune] no CUDA available — aborting", file=sys.stderr)
        return 2

    dtype = {"float32": torch.float32, "float16": torch.float16,
             "bfloat16": torch.bfloat16}[args.dtype]

    print(f"[tune] gpu={args.gpu} model={args.model} dtype={dtype} n_docs={args.n_docs}",
          flush=True)
    model = SentenceTransformer(
        args.model,
        device="cuda",
        trust_remote_code=args.trust_remote_code,
        model_kwargs={"dtype": dtype},
    )

    encode_kwargs: dict = {}
    if args.task:
        encode_kwargs["task"] = args.task
    if args.prompt_name:
        encode_kwargs["prompt_name"] = args.prompt_name

    texts = load_texts(args.shard, args.n_docs)
    print(f"[tune] loaded {len(texts)} texts from {args.shard.name}", flush=True)
    print(f"[tune] baseline host RSS = {read_rss_mb():.0f} MB", flush=True)

    # Warmup at the smallest seq_len so kernel JIT doesn't taint probe 1.
    model.max_seq_length = min(args.seq_lens)
    print(f"[tune] warmup at seq_len={model.max_seq_length} batch=8 ...", flush=True)
    model.encode(texts[:32], batch_size=8, convert_to_numpy=True,
                 normalize_embeddings=True, show_progress_bar=False,
                 **encode_kwargs)
    torch.cuda.synchronize()

    probes: dict[tuple[int, int], Probe] = {}

    def run(seq_len: int, batch: int) -> Probe:
        if (seq_len, batch) in probes:
            return probes[(seq_len, batch)]
        model.max_seq_length = seq_len
        torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        try:
            with RamPeak(interval=0.1) as ram:
                model.encode(texts, batch_size=batch, convert_to_numpy=True,
                             normalize_embeddings=True, show_progress_bar=False,
                             **encode_kwargs)
                torch.cuda.synchronize()
            elapsed = time.time() - t0
            rate = len(texts) / elapsed
            vram = torch.cuda.max_memory_allocated() / 1024**2
            p = Probe(seq_len, batch, rate, vram, ram.peak_mb, elapsed, oom=False)
            print(f"  seq_len={seq_len:>5} batch={batch:>4}  {rate:>9.1f} docs/s  "
                  f"vram={vram:>5.0f}MB  ram={ram.peak_mb:>6.0f}MB  ({elapsed:.1f}s)",
                  flush=True)
        except RuntimeError as e:
            elapsed = time.time() - t0
            msg = str(e).splitlines()[0][:80]
            is_oom = "out of memory" in str(e).lower()
            p = Probe(seq_len, batch, 0.0, 0.0, 0.0, elapsed, oom=is_oom, err=msg)
            print(f"  seq_len={seq_len:>5} batch={batch:>4}  "
                  f"{'OOM' if is_oom else 'ERR'}: {msg}", flush=True)
            if is_oom:
                torch.cuda.empty_cache()
        probes[(seq_len, batch)] = p
        return p

    def ternary_search(seq_len: int) -> Probe | None:
        lo, hi = args.min_batch, args.max_batch
        print(f"\n=== seq_len={seq_len}: ternary search batch ∈ [{lo}, {hi}] ===",
              flush=True)

        # Probe hi first so we can roll it down on OOM before the search starts.
        while hi > lo:
            p = run(seq_len, hi)
            if not p.oom:
                break
            new_hi = max(lo, hi // 2)
            print(f"  OOM at batch={hi}; rolling hi -> {new_hi}", flush=True)
            if new_hi == hi:
                break
            hi = new_hi
        run(seq_len, lo)

        steps_left = args.max_probes - 2
        while steps_left > 0:
            if hi <= lo + 1:
                break
            # Geometric thirds on log scale, round to integers.
            log_lo, log_hi = math.log(lo), math.log(hi)
            m1 = max(lo + 1, min(hi - 1, int(round(math.exp(log_lo + (log_hi - log_lo) / 3)))))
            m2 = max(lo + 1, min(hi - 1, int(round(math.exp(log_hi - (log_hi - log_lo) / 3)))))
            if m1 >= m2:
                # Range too tight to split into three; probe the middle and stop.
                run(seq_len, (lo + hi) // 2)
                break
            f1 = run(seq_len, m1); steps_left -= 1
            if steps_left <= 0:
                break
            f2 = run(seq_len, m2); steps_left -= 1
            # Narrow toward the better side.
            if f1.oom and f2.oom:
                hi = m1 - 1
                continue
            if f2.oom:
                hi = m2 - 1
                continue
            if f1.oom or f2.docs_per_s > f1.docs_per_s:
                lo = m1
            else:
                hi = m2

        # Best at this seq_len.
        succ = [p for (s, _), p in probes.items() if s == seq_len and not p.oom and p.docs_per_s > 0]
        if not succ:
            return None
        return max(succ, key=lambda p: p.docs_per_s)

    winners: list[Probe] = []
    for s in args.seq_lens:
        w = ternary_search(s)
        if w is not None:
            winners.append(w)
            print(f"  ► seq_len={s} winner: batch={w.batch}  {w.docs_per_s:.1f} docs/s  "
                  f"(vram={w.peak_vram_mb:.0f}MB ram={w.peak_ram_mb:.0f}MB)", flush=True)

    # --- Summary table ----------------------------------------------------
    print("\nall probes (rows = seq_len, sorted by batch within each row):")
    print(f"{'seq_len':>8} {'batch':>6} {'docs/s':>10} {'vram_MB':>9} {'ram_MB':>9}")
    print("-" * 50)
    for s in sorted(set(s for (s, _) in probes)):
        for (ss, b) in sorted(probes):
            if ss != s:
                continue
            p = probes[(ss, b)]
            if p.oom:
                cell = f"{p.docs_per_s:>10}".replace(str(p.docs_per_s), "OOM").rjust(10)
                print(f"{s:>8} {b:>6} {'OOM':>10} {'':>9} {'':>9}")
            else:
                print(f"{s:>8} {b:>6} {p.docs_per_s:>10.1f} "
                      f"{p.peak_vram_mb:>9.0f} {p.peak_ram_mb:>9.0f}")

    if winners:
        best = max(winners, key=lambda p: p.docs_per_s)
        print(f"\nbest overall: seq_len={best.seq_len} batch={best.batch}  "
              f"{best.docs_per_s:.1f} docs/s  vram={best.peak_vram_mb:.0f}MB  "
              f"ram={best.peak_ram_mb:.0f}MB")
        print(f"total probes: {len(probes)} (across {len(args.seq_lens)} seq_lens)")
        print(f"\n→ set in index_pipeline.sh:  BATCH={best.batch}  "
              f"(and adjust --max-seq-len to {best.seq_len})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
