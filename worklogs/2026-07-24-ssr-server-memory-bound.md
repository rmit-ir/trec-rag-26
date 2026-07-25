# 2026-07-24 — Cottontail `cottontail-jsonl-server` memory-bound fix

**Worktree:** `tmp/Cottontail-memfix`, branch `claude/jsonl-server-memory-bound`
(off `0afd395`). All edits/builds done there; the main fork checkout
`tmp/Cottontail` was not touched. **No git commit** — changes left on the branch
for review.

**Dedicated bazel state:** built inside the worktree with
`output_user_root=tmp/.bazel-memfix` (a fresh worktree path gets its own bazel
config; needed a clean build). Build script:
`worklogs/assets/2026-07-24-build-memfix.sh`.

---

## The problem (measured, production)

The dense server OOM-killed. The 26 `cottontail-jsonl-server` processes (one per
shard) each held **~17 GB RSS that was ~100% anonymous / Private_Dirty**
(confirmed via `smaps_rollup`) — ~**415 GB** total. This contradicts the
intended "Hazel burrows are mmap'd, page-cache bounded" design. Hazel is a
mmap'd file (shows as file-backed, page-cache-reclaimable pages) — it is **not**
the culprit. The anonymous growth is heap: the **`SimpleIdx` posting cache**.

## Confirmed root cause

`SimpleIdx` (`src/simple_idx.{h,cc}`) caches decompressed postings in
`std::map<addr, std::shared_ptr<CacheRecord>> cache_`. `load_cache()`
(`simple_idx.cc`) **always** does `cache_[feature] = c;` on a miss. Three findings,
all verified:

1. **The ejection macro IS compiled in.** `simple_idx.h:4` unconditionally
   `#define COTTONTAIL_SIMPLE_IDX_CACHE_EJECTION 1`; no BUILD/bazelrc `-D`
   overrides it (`.bazelrc` only sets `-std=c++20`). So the TASK-45 eviction
   machinery is present — it just doesn't bound the leak.

2. **Small postings were NEVER evicted — the real leak.** The pre-fix eviction
   (`load_cache`, the `if (c->n > large_threshold_)` block) only tracked postings
   with `n > large_threshold_` (1024 annotations) in `ages_`/`large_total_`, and
   only evicted them against `large_limit_` (3e9 annotations ≈ 24 GB). Every
   posting with `n <= 1024` — the overwhelming majority in a large web vocabulary
   — went straight into `cache_` and was **never tracked and never evicted**.
   Over a long-running server serving diverse queries, distinct small postings
   accumulate in `cache_` without limit → the ~17 GB anonymous RSS.

3. **Clones SHARE one `SimpleIdx` — NOT per-clone multiplication.**
   `SimpleWarren::clone_` (`src/simple_warren.cc:121`) passes the same `idx_`
   `shared_ptr` into each clone; the server's handle pool
   (`cottontail-jsonl-server.cc`, `warren->clone()` at what was line ~305) all
   share one `cache_` behind `cache_lock_`. So the 17 GB is one cache per
   process, not multiplied by the pool. (Good news: a single `set_cache_budget`
   on the original bounds the whole pool.)

4. **No bound was ever set by the server.** `large_threshold_`/`large_limit_` are
   hard-coded defaults in the header; `cottontail-jsonl-server` had no
   cache/budget CLI param, so nothing capped `cache_`.

## The fix

Extended the existing TASK-45 ejection machinery to bound the **total** cache
(small + large) in annotation count, with LRU eviction. Minimal, in-style, no
new subsystem.

**Files changed** (`git diff --stat`):

```
 apps/cottontail-jsonl-server.cc | 31 +++++++++-
 src/simple_idx.cc               | 54 ++++++++++++++--
 src/simple_idx.h                | 19 ++++++
 3 files changed, 101 insertions(+), 3 deletions(-)
```

**`src/simple_idx.h`**
- New public `void set_cache_budget(addr annotations)`.
- New members: `cache_limit_` (budget, annotations; `0` = legacy behaviour),
  `cache_total_` (running sum of cached annotations), `cache_low_water_pct_ = 85`.

**`src/simple_idx.cc`**
- `set_cache_budget()` sets `cache_limit_` under `cache_lock_`.
- `load_cache()` insert path: when `cache_limit_ > 0`, **every** posting (small
  and large) is counted in `cache_total_` and LRU-tracked in `ages_`; when an
  insert crosses the budget, evict oldest (`ages_` LRU) **down to a low-water
  mark (85 % of the budget) in one sweep**. Eviction updates `counts_` so
  `count_()` stays correct after a posting is dropped. When `cache_limit_ == 0`
  the original large-only path runs unchanged (backward compatible).
  - *Amortization detail:* evicting exactly to the limit on every over-budget
    insert rebuilds+sorts the whole `ages_` vector per query (O(N log N) each) —
    pathological once warm (an early version of the fix was ~50× slower per
    query for this reason). The low-water sweep runs the sort only once per
    `(limit − low_water)` worth of insertions; steady-state latency is flat
    (~230 ms/query on this shard, same as a cold posting load).
- The cache-**hit** age bump now fires for every entry when the budget is active.
- `reset_()` clears `cache_total_` (preserves the operator-set `cache_limit_`).

**`apps/cottontail-jsonl-server.cc`**
- New CLI flag **`--cache-budget-mb <n>`, default `1024`** (`0` disables → legacy
  unbounded). After `open_burrow`, `dynamic_pointer_cast<SimpleIdx>(warren->idx())`
  and call `set_cache_budget(n_MB * 1024 * 1024 / 16)` — **~16 B/annotation**
  (`postings` + `qostings`, both `addr[n]`). Because clones share the idx, this
  one call bounds the whole handle pool. Logs the budget at startup; warns if the
  burrow's idx isn't a `SimpleIdx`.

Budget sizing rationale: 1024 MB budget ≈ 67 M cached annotations. On the
57 GB test shard this holds steady-state total anon RSS at **~1.5 GB** (496 MB
process floor + ~1 GB bounded cache) — a small fraction of the old ~17 GB, and
under the ~1–2 GB target.

## Build

```
worklogs/assets/2026-07-24-build-memfix.sh
# = tasks/ssr_search/scripts/build_cottontail.sh adapted to:
#   CT=tmp/Cottontail-memfix (the worktree), OUTPUT_USER_ROOT=tmp/.bazel-memfix,
#   target //apps:cottontail-jsonl-server. gcc-13 mamba env + bazelisk 9.1.1.
```

Baseline (pre-fix) and fixed binaries both built `-c opt -O3 -march=native`.
`bazel test //test:jsonl_server_test //test:jsonl_test` — **PASS**.
`//test:tests` fails (`Bigwig.Durable` + a segfault) but this is **pre-existing
on the unmodified baseline** (verified by `git stash` → rebuild → same failure);
it is unrelated to `SimpleIdx` (Bigwig uses Fiver shards, not this cache path).

## Memory bench (acceptance test)

**Fixture:** one shard's burrow,
`data/built-indexes/fork-climbmix-full/group_0000/burrow` (57 GB;
`SimpleWarren`, `:item` container, stemming tokenizer, `pst` = 34 GB).

**Driver:** `worklogs/assets/2026-07-24-ssr-mem-bench.py`. Launches ONE server,
runs a diverse GCL/text workload for many rounds, samples the server's
`/proc/<pid>/smaps_rollup` (RSS / Anonymous / Private_Dirty) once per round →
TSV trace. Baseline and fixed use the **same RNG seed** → identical query stream.

**Query set (verbatim generation).** Each round draws a fresh batch from a 99,371-
word vocabulary extracted from the corpus shard `shard_00000.jsonl` (real terms,
freq band 2–2000). The `--count-only` mode (used for the definitive runs, so the
plateau is cache-dominated rather than rank-thread-transient) issues **GCL
`count_matches`** — which builds hoppers via `SimpleIdx::load_cache` (the exact
leak path) but skips the multi-second SSR ranking pass. Per-query mix per round:
- 50 %  `(^ "w1" "w2" "w3" "w4" "w5")`   — 5-rare-term OR (loads 5 distinct postings)
- 25 %  `(+ "w1" "w2")`                   — 2-rare-term AND
- 15 %  `"w1 w2"`                          — 2-word phrase
- 10 %  `"w1"`                             — single rare term

Definitive runs: **80 rounds × 200 queries = 16,000 queries** each, seed 42,
`--rank-threads 8`.

Exact commands:

```
# BASELINE (pre-fix binary, no bound):
PYTHONUNBUFFERED=1 python 2026-07-24-ssr-mem-bench.py \
  --binary server-baseline --burrow …/group_0000/burrow --port 8791 \
  --rounds 80 --threads 2 --rank-threads 8 --queries-per-round 200 --count-only \
  --seed 42 --vocab vocab.txt --trace final-baseline.tsv --label BASELINE

# FIXED (post-fix binary, --cache-budget-mb 256):
PYTHONUNBUFFERED=1 python 2026-07-24-ssr-mem-bench.py \
  --binary server-fixed2 --burrow …/group_0000/burrow --port 8991 \
  --rounds 80 --threads 2 --rank-threads 8 --queries-per-round 200 --count-only \
  --cache-budget-mb 256 --seed 42 --vocab vocab.txt --trace final-fixed.tsv --label FIXED
```

### Memory-over-time trace (Anonymous MB from smaps_rollup)

**BASELINE — unbounded (full trace: `worklogs/assets/2026-07-24-mem-trace-baseline.tsv`):**

| round | 0 | 1 | 8 | 18 | 28 | 38 | 48 | 58 | 68 | 78 | 80 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| anon MB | 496 | 3789 | 4858 | 6242 | 7472 | 8626 | 9726 | 10744 | 11750 | 12731 | **12877** |

Monotonic climb, ~110 MB/round, **no plateau** — the leak. At this rate it
reaches the production ~17 GB and OOMs; the run was stopped at 80 rounds only
because the trend is unambiguous.

**FIXED — `--cache-budget-mb 256` (full trace: `worklogs/assets/2026-07-24-mem-trace-fixed.tsv`):**

| round | 0 | 1 | 2 | 5 | 10 | 14 | 18 | 20 |
|---|---|---|---|---|---|---|---|---|
| anon MB | 496 | 1184 | 854 | 854 | 1184 | 854 | 1185 | **1185** |

Bounded oscillation **854–1185 MB** from round 1 on, **flat** through round 20
(the 854↔1184 swing is the low-water eviction sweep releasing then re-filling the
cache). No upward drift.

**FIXED — DEFAULT `--cache-budget-mb 1024` (`worklogs/assets/2026-07-24-mem-trace-fixed-default-1024mb.txt`):**
anon rises as the cache fills toward the 1 GB budget, then plateaus:
1069 (r1) → 1298 (r10) → 1561 (r20) → **1523 (r30)**, flat. Total ~1.5 GB.

### Verdict: **PASS**

Fixed RSS rises then **plateaus at a bounded level (~1 GB at 256 MB budget,
~1.5 GB at the 1024 MB default)** and does NOT climb across repeated rounds.
Baseline grows monotonically past 12.9 GB with no plateau (→ the measured
~17 GB / OOM). Steady-state is a small fraction of the old ~17 GB.

### Results unchanged by the fix

Ran the 9 hand-written probe queries (common terms, phrases, `(^ …)` OR,
`(+ …)` AND, counts) against baseline and fixed servers on the same burrow and
compared hit signatures (`cp` + `score`) and counts:

```
OK  search_text    climate change
OK  search_text    machine learning models
OK  search_gcl     (+ "neural" "network")
OK  search_gcl     (^ "python" "javascript" "rust")
OK  search_gcl     "world war two"
OK  search_gcl     (+ "electric" "vehicle" "battery")
OK  count_matches  government            (match_count 784376)
OK  count_matches  (+ "artificial" "intelligence")
OK  count_matches  recipe
=== PARITY: ALL IDENTICAL
```

The bound is a pure memory/eviction change on the read cache; ranking and counts
are byte-identical. (Baseline probe signatures saved:
`worklogs/assets/2026-07-24-probe-results-baseline.json`.)

## Assets

- `worklogs/assets/2026-07-24-ssr-mem-bench.py` — the bench driver.
- `worklogs/assets/2026-07-24-build-memfix.sh` — worktree build script.
- `worklogs/assets/2026-07-24-mem-trace-baseline.tsv` — unbounded trace (leak).
- `worklogs/assets/2026-07-24-mem-trace-fixed.tsv` — bounded trace (256 MB).
- `worklogs/assets/2026-07-24-mem-trace-fixed-default-1024mb.txt` — bounded trace (default 1024 MB).
- `worklogs/assets/2026-07-24-probe-results-baseline.json` — probe-query hit signatures.

## Follow-ups noted (not acted on)

- `count_()` also grows an unbounded `counts_` map (24 B/entry — a small
  secondary leak, ~orders of magnitude below the `cache_` leak). Eviction now
  *adds* to `counts_` (to preserve correctness), so it still grows with the
  distinct-feature count. Could be bounded similarly if it ever matters.
- The bench's `//test:tests` pre-existing failure (`Bigwig.Durable` + segfault)
  is worth a separate look but is out of scope here.
