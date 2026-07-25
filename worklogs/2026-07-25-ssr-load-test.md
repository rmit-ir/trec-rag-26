# 2026-07-25 — SSR fleet load test (k6, breaking point)

**Goal:** load-test the live SSR serving stack with k6, ramping until p95 > 10 s, using
real queries.

**Setup**
- k6 v0.55.0 (downloaded static binary). Reusable test tooling lives under the task:
  `tasks/ssr_search/scripts/ssr_loadtest.sh` (ramp runner), `ssr_loadtest.js` (k6
  script), `ssr_loadtest_queries.json` (the 460 harvested queries; `--harvest` rebuilds).
- Target: the fan-out shim `POST http://127.0.0.1:8099/search` (k=10) — the realistic
  hosted path (`fork_shim.py` → 26 `cottontail-jsonl-server`). Backends launched with
  the fork memory-fix binary, `--cache-budget-mb 2048`, `THREADS=4 RANK_THREADS=2`.
- Queries: **460 unique real SSR GCL queries** harvested from all
  `data/outputs/aus_agent/*.output.json` ssr search steps (each iteration picks one at
  random).
- Ramp: `--vus {2,4,8,16,32,64,128,256} --duration 30s` each; stop when p95 > 10 s.

**Results**

| VUs | rps | p50 | p95 | max | err% |
|--:|--:|--:|--:|--:|--:|
| 2 | 8.6 | 185 ms | 670 ms | 1.4 s | 2.7% |
| 4 | 13.9 | 267 ms | 471 ms | 2.9 s | 2.1% |
| 8 | 12.2 | 236 ms | 545 ms | 21.8 s | 0.5% |
| 16 | 11.2 | 238 ms | 783 ms | 37.8 s | 0.9% |
| **32** | 8.9 | 213 ms | **32.2 s** | 37.1 s | 1.2% |
| 64 | 9.3 | 1.5 s | 28.8 s | 32.7 s | 1.7% |
| 128 | 8.9 | 6.4 s | 14.5 s | 58.9 s | 0.7% |
| 256 | 9.8 | 15.5 s | 20.6 s | 27.7 s | 21.3% |

- **Breaking point (p95 > 10 s): ~32 concurrent users.**
- **Throughput ceiling: ~9–14 req/s, FLAT across the whole ramp** (2→256 VUs). RPS never
  scales with concurrency — a saturated-concurrency signature. Beyond ~16 VUs, added
  clients only queue (p95 783 ms → 32 s).
- Single-query latency is healthy (p50 ~185–267 ms up to VU16).

**Memory under load (validates the fix):** fleet climbed 21 GB → ~60–67 GB and
**plateaued**, max **~2.5–2.8 GB/server** (2 GB budget + base). Bounded and stable under
sustained load; shim stayed healthy throughout.

**Diagnosis** (fan-out is parallel — I initially guessed serial, wrong):
- `MultiShardSearchEngine.search` fans out to all 26 shards via
  `ThreadPoolExecutor(max_workers=26)` (isj `engine/multishard.py:55`); shim is
  `ThreadingHTTPServer`.
- Because **every** client request touches **all 26** servers and each server runs only
  `THREADS=4`, the concurrent-client ceiling is ~4 (every request needs a slot on every
  server). That + per-request pool churn (26 threads spun up/down per request) + the
  Python GIL in the shim caps throughput at ~10 rps regardless of clients.
- The high `max` even at low VUs (21–37 s at VU8–16) = a tail of expensive GCL queries
  that hold a backend thread; under concurrency they head-of-line block.
- The C++ SSR engines are **not** the bottleneck — they're lightly loaded (memory grew
  but latency is low); the Python fan-out layer + backend thread budget is the ceiling.

**Error note:** ~1–3% baseline errors are malformed GCL in the harvested set (the shim
returns 400 on EngineError) — a query-set property, not a server fault. The 21% at 256
VUs is overload/timeouts.

**Levers to raise the ceiling (cheapest first, not yet done):**
1. Bump backend `THREADS` (launcher default 4 → 8/16) — directly raises the concurrent-
   client cap since every request touches every server. Quick A/B.
2. Reuse a persistent thread pool in `fork_shim.py` instead of a new `ThreadPoolExecutor`
   per request.
3. Replace the stdlib `ThreadingHTTPServer` with async (uvicorn + httpx async fan-out) to
   shed GIL/thread overhead.
4. Multiple shim processes behind a balancer (backends shared, so #1 still gates).
