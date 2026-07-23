# 2026-07-22 — Building the paper's SSR/Cottontail search stack (`tasks/ssr_search`)

Goal: build the *actual* system from *Boolean Queries Are All You Need?*
(arXiv 2607.11362) for ClimbMix — **not** an approximation over our Lucene index.
That system is Cottontail (annotative indexing) + Shortest-Substring Ranking
(SSR), driven by a GCL Boolean query language. Deliverables asked for: a search
server with **CLI + HTTP**, launched on a port, plus a Boolean tool under
`src/tools/`, with an answer to *how do we build the index, how do we search,
and how do we manage cache/RAM for long-term serving* — validated by CLI +
trajectory on real `data/` test queries.

## Outcome (all working, end-to-end)

build → index → `ssr-server` → CLI → HTTP → `src/tools/search_boolean_tool.py`,
verified against `data/.../trec_rag_2026_queries.tsv`.

## Infra facts

- Upstream Cottontail is cloned at `tmp/Cottontail` (new convention: external
  repos live under `tmp/`, indexed in `tmp/REFERENCE-REPOS.md`; recorded in
  `AGENTS.md`). It **already ships the paper's stack**: `apps/jsonl` (build a
  burrow from JSONL), `apps/ssr-server` (SSR over newline-JSON TCP),
  `apps/ssr-client.py`. We *wrap* it, not fork it. Rich agent docs in
  `tmp/Cottontail/ai/`.
- Toolchain: system g++ is 8.5 (no C++20) and there's no bazel. Fixed with an
  in-folder **mamba env** `tasks/ssr_search/env` (gcc 13.4 + bazelisk 9.2.0 +
  python fastapi/uvicorn). This is the sanctioned "task may use mamba when it
  needs a native toolchain" exception.

### Build quirks (kept out of future debugging time)

- conda-forge `bazel` maxes at 6.3 (too old for this repo's bzlmod +
  `rules_cc 0.2.16`); use **bazelisk** (fetches Bazel 9.2.0) dropped in env/bin.
- Bazel must use the conda gcc, not /usr/bin/gcc-8.5: pass
  `--repo_env=CC=... --repo_env=CXX=...` (the C++ auto-config reads CC/CXX).
- **zlib**: core lib needs `<zlib.h>` + links `-lz`. conda's `zlib` puts headers
  in `$ENV/include`, which the conda gcc's *sysroot* search does not cover, and
  Bazel rejects absolute `-I` copts as non-hermetic ("absolute path inclusion").
  Fix that stuck: **symlink `zlib.h`/`zconf.h` into the compiler sysroot**
  (`$($CXX -print-sysroot)/usr/include`, a builtin search dir) so `<zlib.h>`
  resolves as a builtin header; feed `$ENV/lib` for `-lz` via `LIBRARY_PATH`
  (link paths aren't hermeticity-checked). Both are idempotent in
  `scripts/build_cottontail.sh`.
- **rpath**: link with `-Wl,-rpath,$ENV/lib` so the binaries self-resolve conda
  libstdc++ (gcc-13) + libz at runtime — no `LD_LIBRARY_PATH` needed. Verified
  via `ldd`.
- `ssr-client`/`fluffy` need GNU readline (`<readline/history.h>`) — excluded
  from the build (we have `ssr-client.py` + our own engine). Built targets:
  `//apps:jsonl //apps:ssr-server //apps:rank`, `-c opt -O3 -march=native`.
- Two foot-guns: `foo | tee` masks `foo`'s exit code (use `set -o pipefail`);
  `/usr/bin/time` is absent on this box (use bash `$SECONDS`).

## How the index is built

`apps/jsonl --simple <shard.jsonl>` (opts `tokenizer:name:utf8 txt:json:yes
featurizer@json`) → a burrow where JSON fields become GCL features. For our
`{"id","contents"}` rows: `:contents:` = body, `:id:` = docno, `:` = the whole
JSON object. shard_00000 (86,016 docs / 259 MB) → 187 MB burrow in **25 s**
(`data/built-indexes/ssr-shard00000/json.burrow`).

- `--simple` = static SimpleWarren (used here; postings cached on heap, no
  eviction — fine per-shard).
- `--bigwig` = dynamic Bigwig→**Hazel** (immutable single-file, **mmap'd**) —
  the production/at-scale path.

## How search works

`ssr-server [--fields F] <container> <content> <docno> <burrow...>` = `: :contents: :id: <burrow>`.
It binds an automatic loopback port, speaks newline-JSON (`query`/`next`/
`document`/`set_optimizer`); a reply line is `{"query":…, "response":{op,ok,qid,
rank,docno,snippet}, "time":ms}`. `parallel_ssr` ranks `:contents:` intervals by
SSR (depth 1000) and returns a **match-centered 200-token snippet** with
`<cover>…</cover>`.

### GCL operators — GROUND TRUTH (from `tmp/Cottontail/gcl/parse.cc`)

My first pass had AND/OR **backwards**; corrected everywhere after empirical
check:

| GCL | meaning | note |
|-----|---------|------|
| `(^ a b …)` | **AND** (ALL_OF) | truthful-zero lives here |
| `(+ a b …)` | **OR** (ONE_OF) | |
| `"a b"` = `(... a b)` | ordered phrase (FOLLOWED_BY) | |
| `(>> A B)` | A CONTAINING B | |
| `(<< A B)` | A CONTAINED IN B | |
| `(# k)` | set of width-k windows | proximity = `(<< (^ a b) (# k))` |

Empirical confirmation on shard_00000 (`(^ …)` = AND):

| query | hits | reading |
|-------|-----:|---------|
| `"flu shot"` | many | phrase, snippet shows `<cover>flu shot</cover>` |
| `(^ influenza vaccine)` | many | both terms co-occur (precise) |
| `(^ influenza zxqwphantom)` | **0** | truthful zero — AND with absent term |
| `(+ grippe influenza)` | many | OR (union) |
| `(^ grippe influenza)` | **0** | AND — "grippe" absent in shard |
| `(<< (^ flu vaccine) (# 15))` | many | proximity, tight snippets |

## Cache & RAM management (the long-term-serving answer)

Two independent growth risks, each bounded:

1. **Index residency.** Build at scale as **Hazel** (mmap'd single-file shards):
   RAM cost = OS page cache of the working set, not the whole index. The kernel
   evicts cold pages under pressure — that is the cache invalidation, and it's
   what makes a 400B-token corpus servable on the 503 GB box (mmap all shards,
   let the OS manage residency). (SimpleWarren caches postings on the heap
   without eviction — deliberately used only for the single-shard smoke test.)
2. **Server-side query state.** `ssr-server` keeps *every* query's ≤1000-row
   result vector in a map with **no eviction** → an unbounded leak over a
   long-lived process. `ssr_engine.py` bounds it: (a) an **LRU** on `(query,k)`
   so repeats never mint a new server qid, and (b) a **restart watchdog** — after
   `restart_after` distinct queries it kills+respawns the subprocess, dropping
   all qid state. ssr-server is single-client/serial, so the engine holds one
   connection under a lock; the HTTP layer uses `asyncio.to_thread` so unrelated
   requests still progress.

## Trajectory (Vole-style) on a real test query

Topic `rag2026-1`: *what grief does biologically — heart, immune system, stress
hormones, inflammation.* Served from shard_00000 only (86 K docs ≈ 0.016 % of
corpus), via `search_boolean_tool` over HTTP:8099. Full matrix:

| # | GCL query | hits | judged by reading |
|---|-----------|-----:|-------------------|
| 1 | `(^ grief heart)` | 3 | mixed: grief-counseling (rel) + *heart chakra*/energy-healing noise (polysemy) |
| 2 | `(^ grief inflammation)` | 2 | **hit 1 `shard_00000_75331` on-topic**: cortisol→immunity→inflammation physiology |
| 3 | `(^ bereavement cortisol)` | **0** | truthful zero — clinical vocab absent in shard |
| 4 | `"broken heart syndrome"` | **0** | truthful zero — takotsubo term absent |
| 5 | `(^ grief (+ immune inflammation cortisol stress))` | 3 | grief+stress-physiology docs (OR broadens the 2nd facet inside the AND) |
| 6 | `(<< (^ grief cortisol) (# 60))` | **0** | proximity — grief & cortisol don't co-occur within 60 tokens here |
| 7 | `(^ grief (+ cardiovascular "heart disease" "blood pressure"))` | 3 | tangential (acupressure/hypertension, addiction+heart disease, cardio nursing) |

Full-doc read of the best lead `shard_00000_75331` confirmed genuine
stress→cortisol→immunity→cellular-inflammation content (mechanism facet; about
stress generally rather than grief specifically).

**Reading:** the loop behaves exactly as the paper intends — AND gives precise
co-occurrence, OR broadens a facet inside an AND, proximity tightens, and
**truthful zeros steer the agent away from vocabulary the corpus doesn't have**
instead of hallucinating a near-match. The visible ceiling here is **coverage**
(one shard), not method: clinical terms (bereavement/cortisol/takotsubo) simply
aren't present. Next scale step is ~1 % (≈64 shards) as merged Hazels.

## Artifacts

- Code: `tasks/ssr_search/{ssr_engine.py,cli.py,serve.py,README.md,scripts/*}`,
  `src/tools/search_boolean_tool.py`.
- Binaries: `tmp/Cottontail/bazel-bin/apps/{jsonl,ssr-server,rank}` (opt).
- Index: `data/built-indexes/ssr-shard00000/json.burrow` (187 MB).
- Logs: `/tmp/ssr-build.log`, `/tmp/ssr-index.log`, `/tmp/ssr-serve.log`.
- Trajectory probe: `worklogs/assets/2026-07-22-ssr-traj.py`.

## Next steps (not yet done)

1. Scale to ~1 % via `--bigwig` + `fiver2hazel` merge → mmap'd Hazel shards;
   re-run trajectories where coverage is real.
2. Wire `search_boolean` into the agent loop alongside the OR-BM25 `search`.
3. Optionally patch ssr-server for a bounded qid map upstream-style (vs. our
   restart watchdog).
