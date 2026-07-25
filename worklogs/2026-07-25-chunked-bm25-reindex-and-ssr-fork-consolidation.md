# 2026-07-25 — Chunked BM25 re-index, SSR fork consolidation, repo/output reorg

Session covering four threads. The two deep-dives have their own worklogs and are
only summarized here: SSR posting-cache memory fix →
[2026-07-24-ssr-server-memory-bound.md](2026-07-24-ssr-server-memory-bound.md);
the backend-comparison study →
[2026-07-24-engine-comparison-rubric-judge.md](2026-07-24-engine-comparison-rubric-judge.md).

## 1. Chunked BM25 re-index (sparse now chunk-aligned with dense)

**Why.** The BM25 (Anserini) index was whole-document while the dense index is
chunked (`<docid>_p<page>`). Re-indexed BM25 over the *same* chunk corpus so
sparse and dense cite/dedup on identical chunk ids.

**Precursor.** The chunk JSONL corpus (`tasks/custom_index/work/climbmix-full/corpus`)
had been deleted; it was re-pulled from stormfly (`rsync`, ~1.6 TB, 6543 shards)
into `tasks/custom_index/work/climbmix-chunked/corpus`. Chunker config (must match
dense): `band`, tpw 1.3, `target_min=200 target_max=500 hard_max=700
split_over_target=1 title_chunks=1`.

**Build.** Anserini 2.2.0 `IndexCollection` (JsonCollection, `-storePositions
-storeContents`, 56 threads), JDK 24.0.2. Input was a hard-linked
`corpus-index-input/` dir containing **only** `shard_*.jsonl` (excludes
`chunking_meta.json` + `.ready` markers, which JsonCollection would mis-read).
Command:
```
INPUT=…/climbmix-chunked/corpus-index-input \
INDEX=data/built-indexes/climbmix-bm25-chunked THREADS=56 \
bash tasks/bm25_index/scripts/build_index.sh
```
**Result:** `921,892,634 documents indexed` — **exactly** the dense docstore
manifest chunk count — 0 unindexable / 0 empty / 0 errors, 1.4 TB, in 01:16:58.

**Lesson (cost: a wasted 5-min partial build).** The first attempt was launched
while the corpus rsync was still live; rsync's rename-over-inode pulled the
hard-linked shards out mid-index → 51 M/922 M docs then `FileNotFound`. **Gate the
build on rsync completion.** (Also: `build_index.sh` needs JDK on PATH —
`JAVA_HOME=/scratch/fast/kun/.local/lib/local-jdk/jdk-24.0.2`.)

**Validation (in-repo BoolSearch, no server).** `+uranium +enrichment` and
`"nuclear reactor"` on the chunked index return chunk-keyed ids
(`shard_05401_74111_p1`, `shard_05294_31777_p5`), the `title_chunks=1` prefix
(`"Page N of document: …"`) matches the dense docstore text, and top hits share
the same parent docid as the whole-doc index. Parent recoverable via
`rsplit("_p")`.

**Cutover: pending (user-driven).** Chosen path = parallel `:8086` → A/B vs live
`:8085` → swap. Client code needs no change (`make_hit`/`classify_id` already
derive chunk/parent from `_pN`). Old whole-doc index preserved.

## 2. Repo / output policy (committed separately by user)

- `data/outputs/` is no longer tracked in git — outputs got big and now sync
  server-to-server via `rsync`. `.gitignore` drops the `!data/outputs/` negation;
  files stay on disk. `data/output_feedbacks/` (small, curated) stays tracked.
- The backend-comparison analysis was moved out of the now-ignored outputs tree to
  a tracked `data/task-comparison/` (`!data/task-comparison/`), with its large
  generated intermediates (`rubric-judge/out/{judgments/,pool.json,provenance.json,
  retrieved_raw.json}`, `*.bak`) git-ignored — code + result docs tracked.
- `evaluation-results/` (275 MB, plain blobs — **not** LFS; the only `.gitattributes`
  LFS rule is the now-dead `data/outputs/**/*.json`) deferred to next week.
- Note on the delete-on-pull footgun: untracking a committed dir means a `git pull`
  deletes it from other clones' working trees — back up (rsync) before pulling.

## 3. SSR memory fix — deployed to the fork

Root cause + bench in the linked worklog. Deployment this session:
- Committed to `rmit-ir/Cottontail` `main` and pushed (`4a45afb`). Adds
  `--cache-budget-mb` (default 1024) bounding the SimpleIdx posting cache.
- Rebuilt the fork binary via `build_cottontail.sh` (**correct** script — see §4);
  verified `tmp/Cottontail/bazel-bin/apps/cottontail-jsonl-server` carries the flag.
- `launch_fork_servers.sh` now passes `--cache-budget-mb 2048` (`CACHE_BUDGET_MB`
  env-overridable) → ~2 GB RSS/server, **~52 GB fleet** (was unbounded → 415 GB,
  which OOM-killed dense). The cache is anonymous/non-reclaimable but hard-capped by
  LRU eviction, so fleet sizing (`26 × budget`) is the operator's responsibility.

## 4. Fork consolidation — "our code works with our fork, anywhere"

There were two app stacks and a footgun: `build_cottontail.sh` silently built the
**upstream reference** `tmp/Cottontail-claclark` (paper stack: `ssr-server`,
`jsonl`, `bigwig`), while `build_cottontail_fork.sh` built **our fork**
(`cottontail-jsonl-{index,query,server}`). This caused a wrong-binary rebuild.

Removed the paper stack (archived to `/scratch/large/trec-rag-26/_removed-paper-stack/`
first): `ssr_engine.py`, `serve.py`, `cli.py`, and scripts `build_index.sh`,
`build_full_index.sh`, `calibrate_bigwig.sh`, `build_cottontail.sh` (claclark).
Renamed `build_cottontail_fork.sh` → **`build_cottontail.sh`** (the canonical build
now builds the fork). Refreshed `tasks/ssr_search/README.md` + the CLAUDE.md
ssr_search entry to fork-only. The fork path (`fork_shim.py` → `isj_agent`
`MultiShardSearchEngine`) is independent of everything removed.
`tmp/Cottontail-claclark` stays only as a read reference.

**Serving (unchanged):** 26 `cottontail-jsonl-server` (loopback :7000–:7025) ←
`fork_shim.py` fan-out (:8099) ← SSH reverse tunnel → `index-climbmix-ssr.dsync.net`.
Start = `launch_fork_servers.sh` then `fork_shim.py`.

## 5. Commit-email history fix

The fork's two of-our commits carried the auto-guessed server identity
`Kun Ran <e128356@segsresap12.int.its.rmit.edu.au>`. Rewrote both (rebase --exec
amend) to `Kun Ran <rankun203@gmail.com>`, force-pushed (`7670672…4a45afb`), and set
global `user.name`. Removed the merged `Cottontail-memfix` worktree/branch. The main
project's history was left as-is (rewrite would force-push the shared `rmit-ir`
remote) — its config is fixed so future commits are correct.

## 6. Archive

Stormfly intermediates → `/scratch/large/trec-rag-26/` (~10.2 TB manifest;
`ARCHIVE-MANIFEST-2026-07-24.md`, logs under `_archive-logs/`). Running in the
background, resumable (`--partial`). Policy: large intermediates are archived to the
big `/scratch/large` volume, never deleted from the small SSD project root.
