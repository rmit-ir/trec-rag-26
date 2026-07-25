# ssr_search — Boolean (SSR) search over ClimbMix

The *Boolean Queries Are All You Need?* (arXiv 2607.11362) approach, built for
our corpus on the **UWaterlooIR Cottontail fork** (`tmp/Cottontail`, remote
`rmit-ir/Cottontail`): an annotative index ranked by **Shortest-Substring
Ranking (SSR)**, driven by a **GCL Boolean query language**. The fork ships a
`cottontail-jsonl-{index,query,server}` app trio (StemmingTokenizer +
HashingFeaturizer + configurable-window jsonl server) that we build, index our
ClimbMix shards with, and serve as a fan-out fleet.

The upstream paper repo `tmp/Cottontail-claclark` remains only as a **read
reference** (see `tmp/REFERENCE-REPOS.md`); we no longer build it.

## Why this exists (vs. our Lucene BM25)

Our hosted BM25 index-server is OR-only (its `BagOfWordsQueryGenerator` drops
operators). SSR executes *true* Boolean structure — AND / OR / phrase /
proximity / containment — and ranks by the shortest substring that satisfies the
query. The payoff is the **truthful zero**: a required term that is absent yields
an empty set instead of a confidently-wrong near-match, which is exactly what you
want for rare entities and co-occurrence constraints.

GCL cheat-sheet: `(^ a b)` **AND** (all_of) · `(+ a b)` **OR** (one_of) ·
`"a b"` ordered phrase (followed_by) · `(>> A B)` A-contains-B · `(<< A B)`
A-in-B · `(# k)` = the set of width-k windows, so proximity "a AND b within k
tokens" is `(<< (^ a b) (# k))`. Nests freely. Terms are Porter-stemmed,
case-insensitive.

## Toolchain (mamba, not uv)

This task needs a native C++20 toolchain + Bazel, which uv can't provide, so it
uses an in-folder mamba env (`tasks/ssr_search/env`: gcc 13 + bazelisk). See root
`AGENTS.md`.

## Serving architecture

The corpus is built as **26 group-burrows** (each a stemmed `SimpleWarren`).
SimpleWarren has no merge and the fork server is single-burrow, so a group is the
unit for BOTH parallel build AND serving:

```
26 single-burrow cottontail-jsonl-servers (loopback :7000..:7025)
   <- fork_shim.py  MultiShardSearchEngine fan-out (:8099)
   <- SSH reverse tunnel -> HTTPS index-climbmix-ssr.dsync.net (Basic auth)
```

`fork_shim.py` owns the per-shard `docno-cp` maps, so hits come out docno-keyed
(directly usable for dedup/citation against qrels) and `/doc` routes to the
owning shard.

## Memory bound

Each `cottontail-jsonl-server` caps its SimpleIdx posting cache via
`--cache-budget-mb` (default **2048 MB**). The cache is anonymous /
non-reclaimable but hard-capped by LRU eviction, so each server plateaus at
~1.5–2 GB RSS (was unbounded ~17 GB); fleet total ≈ 26× that.

## Run it

```bash
# 0. one-time: build the fork binaries (production -O3 -march=native)
scripts/build_cottontail.sh
#    -> tmp/Cottontail/bazel-bin/apps/cottontail-jsonl-{index,query,server}

# 1. build the 26 group-burrows from the ClimbMix shards, in parallel
scripts/build_fork_index.sh
#    -> data/built-indexes/fork-climbmix-full/group_%04d/burrow

# 2. build the per-shard docno maps (<burrow>/docno-cp.sqlite)
uv run --no-project python scripts/build_docno_maps.py

# 3. launch the fleet (one server per group-burrow, ports 7000..7025)
scripts/launch_fork_servers.sh          # --paragraph bands, --cache-budget-mb 2048
scripts/launch_fork_servers.sh stop     # kill them

# 4. fan-out shim on :8099
BASE_PORT=7000 NGROUPS=26 SHIM_PORT=8099 \
  PYTHONPATH=tmp/Cottontail/isj \
  uv run --no-project --with pydantic --with httpx \
  python tasks/ssr_search/scripts/fork_shim.py

# query it
curl -s localhost:8099/search \
  -H 'content-type: application/json' \
  -d '{"query":"(^ influenza vaccine)","k":5}'
curl -s localhost:8099/doc -d '{"docno":"shard_00000_5"}' -H 'content-type: application/json'
curl -s localhost:8099/healthz
```

## Files

- `scripts/build_cottontail.sh` — build the fork's `cottontail-jsonl-*` binaries
  with the mamba gcc-13 + bazelisk toolchain (handles the conda/zlib/rpath
  quirks); output root `tmp/.bazel-fork`.
- `scripts/build_fork_index.sh` — ClimbMix shards → 26 group-burrows (parallel).
- `scripts/build_docno_maps.py` — build the per-shard `docno-cp.sqlite` maps.
- `scripts/launch_fork_servers.sh` — launch/stop the single-burrow server fleet
  (`--paragraph` evidence bands, `--cache-budget-mb` posting-cache bound).
- `scripts/fork_shim.py` — stdlib HTTP fan-out shim (`POST /search`, `/doc`;
  `GET /healthz`) over `MultiShardSearchEngine`.
