# 2026-07-22 — `UWaterlooIR/Cottontail` fork vs `claclark/Cottontail` upstream

## Why

`tmp/UWaterlooIR-Cottontail` was added alongside the existing `tmp/Cottontail`
checkout. Both are "Cottontail", so before `tasks/ssr_search/` builds against
either one we needed to know exactly how they differ and which is the right
base.

## Repos compared

| | path | remote | HEAD (at time of writing) |
|---|---|---|---|
| upstream | `tmp/Cottontail` | https://github.com/claclark/Cottontail | `cfd8c40` 2026-07-22 "Add text and code ingestion to Meadowlark" |
| fork | `tmp/UWaterlooIR-Cottontail` (branch `main`) | https://github.com/UWaterlooIR/Cottontail | `82fc70b` 2026-07-15 "Merge PR #24 … simple-idx-cache-ejection" |

## Divergence

Merge base: **`04b711a` 2026-07-04 "Improve hopper memoization and add query
optimization"**.

```
git -C tmp/UWaterlooIR-Cottontail fetch ../Cottontail
git rev-list --left-right --count 04b711a...HEAD        # 0  342   fork ahead
git rev-list --left-right --count 04b711a...FETCH_HEAD  # 0   10   upstream ahead
```

They have diverged in **both** directions. The fork is 342 commits ahead of the
base; upstream is 10 commits ahead of the same base and **has not been merged
into the fork**. Note the merge base is *after* upstream's SSR work
(`ccc2b59` "Shortest substring ranking client/server support"), so the fork
does carry the full SSR stack.

Diff fork-HEAD vs base: **699 files changed, 86,533 insertions, 2,418 deletions.**

## What the fork adds

### 1. JSONL search stack (`apps/`, `scripts/`) — ~3.6k new lines

New apps not present upstream:

| file | lines |
|---|---|
| `apps/jsonl_core.cc` / `.h` | 1366 / 242 |
| `apps/cottontail-jsonl-server.cc` | 534 |
| `apps/climbmix-poc.cc` | 329 |
| `apps/cottontail-jsonl-query.cc` | 252 |
| `apps/jsonl_json.cc` / `.h` | 223 / 39 |
| `apps/cottontail-jsonl-index.cc` | 108 |
| `apps/mt-compile.cc` | 76 |

Plus operational shell scripts, i.e. the exact ClimbMix sharded-serving workflow
`tasks/ssr_search/` is reproducing by hand:

- `scripts/build-climbmix-burrow.sh`, `build-climbmix-all-porter.sh`
- `scripts/build-test-shards.sh`, `build-full-shards.sh`
- `scripts/launch-test-shard-servers.sh`, `launch-full-shard-servers.sh`

### 2. Core engine changes (`src/`, `gcl/`)

| file | change |
|---|---|
| `src/content_index.{h,cc}` | new (65 + 57 lines) |
| `src/stemming_tokenizer.{h,cc}` | new — Porter stemming tokenizer (63 + 139) |
| `src/tokenizer.cc` | +7 (hook for the above) |
| `src/simple_idx.h` | +5/-2 — posting-cache **ejection** to bound server memory (`727c7a7`, TASK-45) |
| `gcl/parse.cc` | +10 |

New tests: `test/jsonl.cc` (1675), `test/jsonl_server.cc` (525),
`test/jsonl_cli.cc` (355), `test/stemming_tokenizer.cc` (163),
`test/content_index.cc` (131), `test/gcl.cc` (+82), fixtures under `test/jsonl/`.

### 3. `isj/` — agentic ISJ system (Python)

Self-described in `isj/README.md` as *"a TREC RAG 2026 primary-system
deliverable, not an example or demo"* — an agentic Interactive Searching and
Judging investigation planner:

- `isj_agent/agents/` — analyst, searcher (cover), tiered_searcher,
  mt_tiered_searcher, **lucindri_searcher**, judger, search_coach
- `isj_agent/engine/` — pluggable `SearchEngine`: `http`, `lucindri`,
  `multishard`, scripted fake
- `isj_agent/` — orchestrator (Analyst → per-intent Controller), controller loop
  with context compaction, run-output writer with live `activity.log`
- `isj/scripts/run_topics.py` (batch N searcher arms over a topics TSV,
  per-topic server cycling), `traceview.py`
- own `pyproject.toml` + `uv.lock`, `config.example.toml`, pytest suite

### 4. Process / docs scaffolding (not upstream)

- `backlog/tasks/` — 49 TASK-nn files
- `docs/design/reference-specs/` — `hazel-format.md`, `indexing.md`,
  `stemming.md`, `cottontail-jsonl-cli-spec.md`,
  `cottontail-search-server-spec.md`, `cottontail-server-threadpool-spec.md`,
  `running-the-search-stack.md` (the README points here as the single
  copy-paste-runnable guide)
- `docs/design/phrase-search-performance-and-proposal.md`,
  `phrase-followedby-repro/`, `search-coach.md`, `docs/papers/`, `docs/trec4/`
- `isj/scouting/` — 402 files of prompt-variant experiments
- `CLAUDE.md`, `TASKS.md`, `memory/`, `archive/example-agent/`

## What the fork is MISSING from upstream (the 10 commits)

```
cfd8c40 2026-07-22 Add text and code ingestion to Meadowlark
2ed5b9e 2026-07-22 Add source provenance segments to Meadowlark appends
05205fc 2026-07-21 Make Meadowlark TSV ingestion self-describing
2800d28 2026-07-21 Move Meadowlark JSON appends onto Warren
5ee0f99 2026-07-20 Move forager JSON handling into metadata module
8d0d9bc 2026-07-20 Rescue stranded Fiver
377e251 2026-07-12 Remove internal JSON structural encoding from ssr-server responses
77b67bd 2026-07-11 More planning
6f5b083 2026-07-11 Clean up notes and documentation
dcc53df 2026-07-11 App to finish merging dynamic indices
```

Mostly Meadowlark ingestion work, plus `apps/finish-merging.cc` (missing from
the fork's `apps/`).

**⚠️ `377e251` "Remove internal JSON structural encoding from ssr-server
responses" changes the `ssr-server` wire format.** The fork predates it, so a
client written against one repo's `ssr-server` may not parse the other's
responses. Anything in `tasks/ssr_search/` or `src/tools/` that parses SSR
output must be pinned to a known repo/commit.

## Conclusion / recommendation for `tasks/ssr_search/`

- The **fork** is the closer match to what we're building: it already scripts the
  ClimbMix JSONL → Hazel burrow → sharded HTTP server pipeline, adds Porter
  stemming, and bounds server memory via posting-cache ejection. It also ships an
  ISJ agent explicitly aimed at TREC RAG 2026.
- **Upstream** remains the cleaner reference for SSR/Meadowlark semantics and is
  where the newest protocol changes land.
- Keep both checkouts. Decide per-component which to build from, and record the
  commit; do not assume `ssr-server` responses are interchangeable.

## Reproducing this comparison

```bash
cd tmp/UWaterlooIR-Cottontail
git fetch ../Cottontail
git merge-base HEAD FETCH_HEAD                     # -> 04b711a
git rev-list --left-right --count 04b711a...HEAD
git rev-list --left-right --count 04b711a...FETCH_HEAD
git diff --stat 04b711a HEAD -- src/ apps/ gcl/ test/ scripts/
git diff --name-only 04b711a HEAD | awk -F/ '{print $1"/"$2}' | sort | uniq -c | sort -rn
```
