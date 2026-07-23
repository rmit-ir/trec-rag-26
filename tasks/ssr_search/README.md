# ssr_search — Boolean (SSR) search over ClimbMix

The paper's stack from *Boolean Queries Are All You Need?* (arXiv 2607.11362),
built for our corpus: a **Cottontail** annotative index ranked by
**Shortest-Substring Ranking (SSR)**, driven by a **GCL Boolean query language**,
served over HTTP + CLI, and exposed to agents via `src/tools/search_boolean_tool.py`.

Upstream reference lives at `tmp/Cottontail` (see `tmp/REFERENCE-REPOS.md`).
This task **wraps** it, it does not fork it.

## Why this exists (vs. our Lucene BM25)

Our hosted BM25 index-server is OR-only (its `BagOfWordsQueryGenerator` drops
operators). SSR executes *true* Boolean structure — AND / OR / phrase /
proximity / containment — and ranks by the shortest substring that satisfies the
query (`score = Σ 1/(C + len)`, C=42). The payoff is the **truthful zero**: a
required term that is absent yields an empty set instead of a confidently-wrong
near-match, which is exactly what you want for rare entities and co-occurrence
constraints.

## Toolchain (mamba, not uv)

This task needs a native C++20 toolchain + Bazel, which uv can't provide, so it
uses an in-folder mamba env (`tasks/ssr_search/env`: gcc 13.4, bazelisk, plus
Python `fastapi`/`uvicorn` for the wrapper). See root `AGENTS.md`.

## How the index is built

`apps/jsonl` ingests our ClimbMix JSONL shards (`{"id": ..., "contents": ...}`)
into a Cottontail **burrow** with `tokenizer:name:utf8 txt:json:yes
featurizer@json`. Field values become GCL features: `:contents:` (body),
`:id:` (docno); `:` is the whole JSON object (the document/container).

```bash
scripts/build_index.sh --simple shard00000 \
  data/climbmix-bm25-collection/shard_00000.jsonl
# -> data/built-indexes/ssr-shard00000/json.burrow
```

- `--simple` → a static `SimpleWarren` burrow: fast to build, good for smoke
  tests. Postings are cached in RAM as queried (grows with the query set).
- `--bigwig` → a dynamic Bigwig of Fiver shards, which merge to **Hazel** —
  the immutable single-file, **memory-mapped** shard format. Hazel is the
  production/long-term-serving path: its RAM cost is OS page-cache, not heap.

## How search works

`apps/ssr-server [--fields F] <container> <content> <docno> <burrow...>` opens
each burrow as a `Warren`, binds a loopback TCP port, and speaks newline-JSON.
For our corpus: `container=":"`, `content=":contents:"`, `docno=":id:"`. A
`query` runs `parallel_ssr` over `:contents:` (depth 1000), maps each ranked
content interval back to its containing document via `container`/`docno`, and
returns a **match-centered 200-token snippet** with `<cover>…</cover>` around the
shortest substring. `next` paginates; `document` fetches a full doc by docno.

GCL cheat-sheet (verified against `gcl/parse.cc`): `(^ a b)` **AND** (all_of) ·
`(+ a b)` **OR** (one_of) · `"a b"` = `(... a b)` ordered phrase (followed_by) ·
`(>> A B)` A-contains-B · `(<< A B)` A-in-B · `(# k)` = the set of width-k
windows, so proximity "a AND b within k tokens" is `(<< (^ a b) (# k))`. Nests
freely. Terms are Porter-stemmed, case-insensitive.

## Cache & RAM management (long-term serving)

Two layers, because there are two different growth risks:

1. **The index** — served from a memory-mapped Hazel burrow. The kernel page
   cache holds hot pages and evicts cold ones under pressure, so the RAM
   footprint is the *working set*, not the whole index. This is what makes a
   400B-token corpus servable on a 503 GB box: build it as sharded Hazels, mmap
   them all, let the OS manage residency. (SimpleWarren, by contrast, caches
   postings on the heap without eviction — fine for a shard, not for the full
   corpus; use Hazel at scale.)

2. **The server's per-query state** — `ssr-server` stores *every* query's result
   vector (≤1000 rows) in a map with **no eviction**; over a long-lived process
   that is an unbounded leak. `ssr_engine.py` bounds it two ways:
   - an **LRU result cache** keyed by `(query, k)` so repeated queries never mint
     a new server qid (they return from our RAM), and
   - a **restart watchdog**: after `restart_after` *distinct* queries the engine
     transparently kills and re-spawns the subprocess, dropping all qid state.
   `ssr-server` is also single-client/serial, so the engine holds one connection
   and serializes requests under a lock; the HTTP layer dispatches via
   `asyncio.to_thread` so unrelated requests still progress.

## Run it

```bash
# 0. one-time: build the binaries (production -O3 -march=native)
scripts/build_cottontail.sh

# 1. build an index
scripts/build_index.sh --simple shard00000 \
  data/climbmix-bm25-collection/shard_00000.jsonl

# 2a. CLI (spawns its own ssr-server)
env/bin/python cli.py --burrow ../../data/built-indexes/ssr-shard00000/json.burrow \
  '(^ influenza vaccine)' -k 5
env/bin/python cli.py --burrow <burrow> --repl

# 2b. HTTP service on a fixed port
SSR_BURROWS=../../data/built-indexes/ssr-shard00000/json.burrow \
  env/bin/uvicorn serve:app --host 127.0.0.1 --port 8099
# then: curl -s localhost:8099/search -d '{"query":"(+ flu vaccine)","k":5}' \
#            -H 'content-type: application/json'

# 3. agent tool (talks to the HTTP service)
SSR_SEARCH_URL=http://127.0.0.1:8099 \
  python ../../src/tools/search_boolean_tool.py '(^ influenza vaccine)' --k 5
```

## Files

- `scripts/build_cottontail.sh` — build the SSR binaries with the mamba gcc-13 +
  bazelisk (handles the conda/zlib/rpath quirks).
- `scripts/build_index.sh` — JSONL shard(s) → burrow.
- `ssr_engine.py` — manage the ssr-server subprocess + protocol + cache/restart.
- `cli.py` — interactive/one-shot GCL search CLI.
- `serve.py` — FastAPI HTTP service (stable port).
- `../../src/tools/search_boolean_tool.py` — agent tool.
