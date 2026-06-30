"""Load test the running search-serve REST API.

Issues N requests at concurrency C against /search, collects both the
server-reported per-stage timings (encode / ann / docstore / total) and the
client-side end-to-end RTT, then prints percentiles + throughput.

Example:
  uv run --project tasks/search_serve python tasks/search_serve/scripts/loadtest.py \
    --url http://127.0.0.1:8000 \
    --total 200 --concurrency 8 --k 10
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx


QUERIES_POOL = [
    "How does a transformer neural network work?",
    "What is photosynthesis?",
    "How do vaccines train the immune system?",
    "Why is the sky blue during the day?",
    "What causes earthquakes?",
    "How does GPS know my location?",
    "Best way to learn a new language as an adult",
    "How is cheese made from milk?",
    "What is the difference between viruses and bacteria?",
    "How do solar panels convert sunlight to electricity?",
    "Why do leaves change color in autumn?",
    "What is the theory of relativity?",
    "How does a refrigerator keep food cold?",
    "What is dark matter and why does it matter?",
    "How do antibiotics kill bacteria?",
    "What makes bread rise when you bake it?",
    "How does the internet route packets across continents?",
    "Why do humans need sleep?",
    "How are diamonds formed in the Earth?",
    "What is the Krebs cycle in cellular metabolism?",
]


# ---------------------------------------------------------------------------
# Collected per-request sample
# ---------------------------------------------------------------------------

@dataclass
class Sample:
    client_rtt_ms: float
    server_total_ms: float
    server_encode_ms: float
    server_ann_ms: float
    server_docstore_ms: float
    status: int


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def _do_one_request(client: httpx.AsyncClient, url: str, k: int,
                           with_text: bool, query: str) -> Sample:
    body = {"query": query, "k": k, "with_text": with_text}
    t0 = time.perf_counter()
    r = await client.post(url + "/search", json=body)
    rtt_ms = (time.perf_counter() - t0) * 1000
    if r.status_code != 200:
        return Sample(rtt_ms, 0, 0, 0, 0, r.status_code)
    t = r.json()["timings"]
    return Sample(
        client_rtt_ms=rtt_ms,
        server_total_ms=t["total_ms"],
        server_encode_ms=t["encode_ms"],
        server_ann_ms=t["ann_ms"],
        server_docstore_ms=t["docstore_fetch_ms"],
        status=200,
    )


async def _run_workers(url: str, total: int, concurrency: int,
                       k: int, with_text: bool, seed: int) -> list[Sample]:
    rng = random.Random(seed)
    queries = [rng.choice(QUERIES_POOL) for _ in range(total)]
    sem = asyncio.Semaphore(concurrency)
    results: list[Sample] = [None] * total  # type: ignore
    limits = httpx.Limits(max_connections=concurrency * 2,
                          max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=60.0, limits=limits) as client:
        async def worker(i: int):
            async with sem:
                results[i] = await _do_one_request(client, url, k, with_text,
                                                    queries[i])
        await asyncio.gather(*[worker(i) for i in range(total)])
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * (len(xs) - 1)))]


def _summarize_stage(label: str, vals: list[float]) -> str:
    if not vals:
        return f"  {label:24s}  (no samples)"
    return (f"  {label:24s}  "
            f"min={min(vals):6.2f}  p50={_pct(vals,50):6.2f}  "
            f"p95={_pct(vals,95):6.2f}  p99={_pct(vals,99):6.2f}  "
            f"max={max(vals):6.2f}  mean={statistics.fmean(vals):6.2f}  ms")


def report(samples: list[Sample], elapsed_s: float, concurrency: int, k: int) -> None:
    ok = [s for s in samples if s.status == 200]
    bad = len(samples) - len(ok)
    throughput = len(ok) / elapsed_s if elapsed_s else 0.0
    print(f"\n[loadtest] concurrency={concurrency}  k={k}  "
          f"total={len(samples)}  ok={len(ok)}  failed={bad}")
    print(f"[loadtest] wall={elapsed_s:.2f}s  throughput={throughput:.1f} req/s")
    if not ok:
        return
    print(_summarize_stage("server encode_ms",
                            [s.server_encode_ms for s in ok]))
    print(_summarize_stage("server ann_ms",
                            [s.server_ann_ms for s in ok]))
    print(_summarize_stage("server docstore_ms",
                            [s.server_docstore_ms for s in ok]))
    print(_summarize_stage("server total_ms",
                            [s.server_total_ms for s in ok]))
    print(_summarize_stage("client rtt_ms",
                            [s.client_rtt_ms for s in ok]))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Load test the search-serve REST API.")
    ap.add_argument("--url", default="http://127.0.0.1:8000",
                    help="server base URL (default http://127.0.0.1:8000)")
    ap.add_argument("--total", type=int, default=200,
                    help="total number of requests in the timed phase")
    ap.add_argument("--concurrency", type=int, action="append",
                    help="repeat to sweep multiple concurrency levels "
                         "(e.g. --concurrency 1 --concurrency 4)")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--with-text", action="store_true", default=True)
    ap.add_argument("--no-text", dest="with_text", action="store_false")
    ap.add_argument("--warmup", type=int, default=10,
                    help="untimed warm-up requests before each sweep level")
    ap.add_argument("--seed", type=int, default=0)
    return ap


async def _wait_for_ready(url: str, timeout: float = 600.0) -> None:
    """Poll /health until status==ok or timeout. Engine load can take minutes."""
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.time() < deadline:
            try:
                r = await client.get(url + "/health")
                if r.status_code == 200 and r.json().get("status") == "ok":
                    return
            except Exception:
                pass
            await asyncio.sleep(2.0)
    raise SystemExit(f"server at {url} did not become ready within {timeout}s")


async def _run_sweep(args) -> int:
    print(f"[loadtest] waiting for {args.url}/health ...", flush=True)
    await _wait_for_ready(args.url)
    print(f"[loadtest] server ready, starting sweep", flush=True)
    levels = args.concurrency or [args.concurrency or 1]
    if not levels:
        levels = [1]
    for c in levels:
        if args.warmup > 0:
            print(f"[loadtest] warm-up x{args.warmup} at concurrency={c} ...", flush=True)
            await _run_workers(args.url, args.warmup, c, args.k,
                                args.with_text, seed=args.seed)
        print(f"[loadtest] timed run: total={args.total} concurrency={c}", flush=True)
        t0 = time.perf_counter()
        samples = await _run_workers(args.url, args.total, c, args.k,
                                      args.with_text, seed=args.seed + 1)
        elapsed = time.perf_counter() - t0
        report(samples, elapsed, c, args.k)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run_sweep(args))


if __name__ == "__main__":
    sys.exit(main())
