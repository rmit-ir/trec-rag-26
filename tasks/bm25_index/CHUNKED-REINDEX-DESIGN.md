# Chunked BM25 re-index — design & runbook

> Status: **DESIGN / NOT-YET-APPLIED.** Nothing here has been executed. The
> heavy steps (chunk-JSONL regen + Anserini build) and the server relaunch are
> the user's to trigger after review. No code has been committed.

## TL;DR (headline)

- **The chunk JSONL corpus that the dense index was built from NO LONGER EXISTS
  on disk.** `tasks/custom_index/work/climbmix-chunked/corpus/` (referenced in
  `chunking_meta.json`) is gone — `tasks/custom_index/work/` does not exist. The
  chunk *text* now lives only inside the compressed docstore
  (`data/built-indexes/climbmix-chunked/docstore/`, zstd-9 + trained dict).
  So **chunking-the-corpus is a required precursor** to the BM25 re-index. We
  can regenerate it deterministically because the whole-doc source JSONL and the
  chunker config both survive (see below).
- Everything else lines up: the client `SearchHit` layer is **already
  chunk-aware** (`make_hit`→`classify_id` derives `kind`/`docid` from the
  `_p<page>` suffix), so once the sparse server returns chunk ids the clients
  need essentially **zero** code change. The real work is the index rebuild +
  server relaunch.

## 1. Current state (discovered, read-only)

### 1a. Whole-doc BM25 index (LIVE)
- Build script: `tasks/bm25_index/scripts/build_index.sh` — Anserini 2.2.0
  (`io.anserini.index.IndexCollection`), `JsonCollection`,
  `DefaultLuceneDocumentGenerator`, `-storePositions -storeContents`, 56 threads.
  Fatjar at `tasks/bm25_index/jars/anserini-2.2.0-fatjar.jar`.
- Input corpus: `data/climbmix-bm25-collection/` — **6543** shards
  `shard_NNNNN.jsonl`, each line `{"id":"shard_NNNNN_<row>","contents":"..."}`,
  **1.6 TB** total. Produced from `data/climbmix-400b-shuffle/` (raw parquet,
  6544 files, 559 GB) by `tasks/bm25_index/scripts/parquet_to_jsonl.py`.
- On-disk index: `data/built-indexes/climbmix-bm25/` — **1.4 TB**, **single
  segment** (`_3r3.*`), **553,240,576 docs**, positions present
  (`.pos` 267 GB), stored contents (`.fdt` 1.0 TB). This is the whole-doc index.
- (`data/built-indexes/climbmix-bm25-manysegs/` is an earlier multi-segment
  build; ignore.)

### 1b. Dense (chunked) index — the alignment target
- `data/built-indexes/climbmix-chunked/` — DiskANN + docstore, **NOT** BM25.
- `chunking_meta.json`: strategy `band`, `tokens_per_word=1.3`, params
  `{target_min:200, target_max:500, hard_max:700, split_over_target:1,
  title_chunks:1}`, id scheme `<docid>_p<page>` (page from 1).
  **`source_corpus: tasks/custom_index/work/climbmix-full/corpus` — GONE.**
- `docstore/manifest.json`: `keyed_by:"chunk_id"`, **n_records = 921,892,634**
  chunks (from 6543 shards), `raw_bytes = 1.684 TB` (uncompressed chunk text),
  `written_bytes = 580 GB` (zstd-9), `shard_of_rule:
  chunk_id.rsplit('_p',1)[0].rsplit('_',1)[0]`.
- **`title_chunks:1` matters:** chunks 2+ are prefixed
  `"Page N of document: <first-line-title>\n\n"` (see `chunkers.run_strategy`).
  To keep BM25 text byte-identical to what the dense docstore holds, the BM25
  re-chunk MUST use the same params **including `title_chunks=1`**.

### 1c. How the chunk JSONL is produced (the tool we re-run)
- `tasks/custom_index/scripts/chunk_corpus.py` reads whole-doc
  `shard_NNNNN.jsonl` (`{"id","contents"}`), applies
  `tasks/chunking-strategy/scripts/chunkers.py::run_strategy`, and writes
  `shard_NNNNN.jsonl` with lines `{"id":"<docid>_p<page>","contents":"<chunk>"}`
  — **exactly the JsonCollection shape Anserini wants.** Per-shard resumable,
  atomic, writes `chunking_meta.json`. Whole-doc source
  `data/climbmix-bm25-collection/` is a valid `--corpus-dir` (same id scheme the
  dense side used). Note: `chunk_corpus.py` doesn't pass `title_chunks` — it only
  forwards `--param`, and `run_strategy` reads `title_chunks` from params, so
  `--param title_chunks=1` works.

### 1d. How the sparse searcher is served (LIVE)
- Process (running, pid seen `1180387`): `rmit-ir/index-server` fatjar at
  `/home/eh6/E128356/projects/index-server/build/libs/index-server.jar`,
  launched pointing at `--index-path=.../climbmix-bm25` on `--port=8085`,
  `--bm25-k1 0.9 --bm25-b 0.4`, `MMapDirectory`, `--preload=*.tim,*.tip`.
  OR-only (`BagOfWordsQueryGenerator` strips all operators).
- Convenience launcher: `/home/eh6/E128356/projects/index-server/run-production.sh
  --index-path <dir> [--host] [--port]` (auto-sizes JVM heap from RAM; note it
  preloads more files and uses a bigger heap than the currently-running pid, but
  is the sanctioned way to start it).
- Public exposure: an autossh-style reverse tunnel
  `ssh -R 0.0.0.0:28085:127.0.0.1:8085 ec2-user@52.62.48.70` (pid `3792898`)
  fronts `https://index-climbmix-bm25.dsync.net`. **The tunnel targets local
  port 8085**, so if the new server reuses port 8085 the tunnel needs no change.
- Boolean/phrase path: `tasks/bm25_index/boolsearch/bs.sh` → `BoolSearch`
  (per-call JVM, mmap-opens the index dir). `BoolSearch` takes the **index dir as
  argv[0]**, and `bs.sh` hardcodes `IDX=.../climbmix-bm25` — so switching it to
  the chunked index is a one-line `IDX=` edit (no recompile; `.class` already
  built, analyzer/similarity unchanged).

### 1e. Client layer (already chunk-ready)
- `src/utils/search_types.py`: `SearchHit` carries `id` (unit id), `docid`
  (parent, `_p<page>`-stripped), `kind` (`document`|`chunk`). `make_hit` +
  `classify_id` auto-derive `kind`/`docid` from the id's `_p<page>` suffix.
- `src/utils/search_sparse.py`: hits built via `make_hit(h["_id"], ...,
  text=source.get("contents"))`. When `_id` becomes a chunk id it AUTOMATICALLY
  classifies as a chunk and derives the parent docid. **No code change strictly
  required.**
- `src/utils/search_dense.py` (parity target): `make_hit(h["docid"], ...,
  text=h.get("text"))` — same shape. Dense already returns chunk ids + chunk
  text.
- `src/utils/search_lucene_bool.py`: parses `bs.sh` stdout lines
  `[rank] <id> score=..` → `make_hit(docid=<id>, ...)`. Also auto-classifies
  once the index holds chunk ids.
- `src/tools/search_tool.py`: surfaces `id`/`docid`/`kind`/`text` straight from
  `SearchHit`. No change.
- `src/utils/search_pyserini.py`: hosted Waterloo `climbmix-400b` (whole-doc,
  external). Independent of our index — to be **deprecated** (user: "pyserini
  one is not that important").

## 2. Proposed architecture (1 paragraph)

Re-chunk `data/climbmix-bm25-collection/` (whole-doc JSONL) with the **exact**
dense chunker config (`band`, tpw 1.3, target 200/500/hard 700,
`split_over_target=1`, `title_chunks=1`) into a new chunk-JSONL corpus, then run
the existing Anserini machinery over it into a new index dir. Each Lucene
document's id is the **chunk id** `shard_NNNNN_<row>_p<page>`; stored `contents`
is the **chunk segment text** (byte-identical to the dense docstore entry so
citations/dedup line up 1:1 across engines); parent docid is derivable via
`chunk_id.rsplit("_p",1)[0]` exactly as `classify_id` already does. New index
dir: **`data/built-indexes/climbmix-bm25-chunked/`**; new chunk-JSONL corpus:
**`data/climbmix-bm25-chunked-collection/`**. **Keep the old whole-doc index and
its live server up throughout** — cut over only when the new index is built and a
new/relaunched server points at it; the client needs no edit to follow.

### Cutover ordering (STRICT)
1. Regenerate chunk JSONL (`chunk_corpus.py`) — *heavy, ~hours*.
2. Build chunked Anserini index → `climbmix-bm25-chunked/` — *heavy, many hours*.
3. Relaunch the `index-server` (and repoint `bs.sh`) at the chunked index.
4. **Only then** is the sparse path chunk-keyed. No client code edit needed;
   optionally add a defensive `kind`/`meta` note (see §5). Do NOT switch clients
   before step 3, or they'd mislabel whole-doc ids as documents while the live
   server is still whole-doc (they already do that correctly today — the point is
   just: nothing to change until the server flips).

## 3. Re-index plan (HEAVY — run later, under user confirmation)

### Step 1 — regenerate the chunk JSONL corpus
```bash
cd /scratch/fast/kun/projects/trec-rag-26
uv run --project tasks/custom_index python \
  tasks/custom_index/scripts/chunk_corpus.py \
  --corpus-dir data/climbmix-bm25-collection \
  --out-dir    data/climbmix-bm25-chunked-collection \
  --strategy band \
  --tokens-per-word 1.3 \
  --param target_min=200 --param target_max=500 --param hard_max=700 \
  --param split_over_target=1 --param title_chunks=1 \
  --workers 48
```
- Reads 6543 whole-doc shards, writes 6543 chunk shards + `chunking_meta.json`
  + `.prepare_done`. Resumable (existing outputs skipped).
- **Verify config parity** afterwards: diff the emitted
  `data/climbmix-bm25-chunked-collection/chunking_meta.json` params against
  `data/built-indexes/climbmix-chunked/chunking_meta.json` — they must match
  (band / 1.3 / 200 / 500 / 700 / split=1 / title=1). Spot-check that a chunk id
  present in the docstore `ids.bin` also appears in the new JSONL with identical
  text (byte-for-byte). If they differ, the sparse index will NOT be
  chunk-aligned with dense.

### Step 2 — build the chunked Anserini index
```bash
cd /scratch/fast/kun/projects/trec-rag-26
INPUT=data/climbmix-bm25-chunked-collection \
INDEX=data/built-indexes/climbmix-bm25-chunked \
THREADS=56 \
  bash tasks/bm25_index/scripts/build_index.sh
```
- `build_index.sh` already parameterizes `INPUT`/`INDEX`/`THREADS` via env; no
  script edit needed. Same generator + `-storePositions -storeContents`. Leave
  `OPTIMIZE` off (multi-segment fine; the server reads all segments). Set it as a
  tracked background job with `tee` to a log per CLAUDE.md.

### Compute / disk / time estimate
| quantity | whole-doc (actual) | chunked (estimate) |
|---|---|---|
| docs | 553 M | **922 M** (1.67×, from docstore n_records) |
| stored text (`.fdt`) | 1.0 TB | **~1.7 TB** (raw chunk text = 1.684 TB from docstore `raw_bytes`; title-prefix adds a little) |
| chunk JSONL corpus | 1.6 TB (whole-doc) | **~1.8 TB** (1.68 TB text + JSON/id overhead over 922 M rows) |
| total index dir | 1.4 TB | **~1.9–2.2 TB** (larger `.fdt`; postings/positions similar order — same tokens, more doc boundaries) |
| index build wall time | (whole-doc built in one pass) | **plan for a long multi-hour run**; 1.67× the docs at similar total tokens → similar-to-somewhat-longer than the whole-doc build. |
| chunking wall time | — | hours (CPU, 48 workers; the dense side chunked 553 M docs → 922 M chunks; scale from that run's log if available). |
- **Peak disk during cutover** (all coexisting): old index 1.4 TB + chunk JSONL
  ~1.8 TB + new index ~2.1 TB ≈ **~5.3 TB**. Free on `/scratch/fast`:
  **28 TB** — ample. The chunk JSONL can be deleted after the index builds (it's
  reproducible), reclaiming ~1.8 TB.
- These are estimates from artifact sizes, not a dry run. Treat the build as the
  heavy gated step.

## 4. Kill + relaunch recipe (server) — run later, user-triggered

Currently live: `index-server` pid on `:8085` (index-path=`climbmix-bm25`) +
reverse tunnel pid on local `:8085`. Two options:

### Option A — in-place swap (reuse :8085, tunnel untouched) — RECOMMENDED
```bash
# 1. Find the running index-server jvm (whole-doc, :8085)
ps aux | grep '[i]ndex-server.jar' | grep 8085          # note the PID
# 2. Stop it (do NOT touch the ssh -R tunnel; it stays pointing at :8085)
kill <PID>                                               # graceful; kill -9 if stuck
# 3. Relaunch pointed at the CHUNKED index, same port 8085
cd /home/eh6/E128356/projects/index-server
nohup ./run-production.sh \
  --index-path /scratch/fast/kun/projects/trec-rag-26/data/built-indexes/climbmix-bm25-chunked \
  --host 0.0.0.0 --port 8085 \
  > /tmp/index-server-chunked.log 2>&1 &
tail -f /tmp/index-server-chunked.log                    # wait for "started"/preload
# 4. The dsync tunnel (ssh -R 0.0.0.0:28085:127.0.0.1:8085 ec2-user@52.62.48.70)
#    already forwards to :8085 -> nothing to restart; the public
#    https://index-climbmix-bm25.dsync.net now serves the chunked index.
```
- The currently-running pid used a **manual** invocation (`-Xmx32g`,
  `--preload=*.tim,*.tip`), not `run-production.sh`. To reproduce that exact
  lighter footprint instead of the heavy auto-sized `run-production.sh`, launch
  the jar directly with the same flags but `--index-path=...climbmix-bm25-chunked`.
  Pick whichever heap fits alongside the dense + SSR servers.
- **`bm25-k1`/`bm25-b`:** the live server uses `--bm25-k1 0.9 --bm25-b 0.4`.
  Carry those flags to the relaunch for scoring continuity (note: `BoolSearch`
  uses Lucene defaults 1.2/0.75 — a pre-existing mismatch, out of scope here).

### Option B — parallel instance (new port, A/B) — for validation before cutover
```bash
# Bring up the chunked index on a NEW port (e.g. 8086) while :8085 stays whole-doc
cd /home/eh6/E128356/projects/index-server
nohup ./run-production.sh \
  --index-path /scratch/fast/kun/projects/trec-rag-26/data/built-indexes/climbmix-bm25-chunked \
  --host 0.0.0.0 --port 8086 > /tmp/index-server-chunked-8086.log 2>&1 &
# Point a client at it ad hoc: search_sparse(q, url="http://127.0.0.1:8086")
# When validated, tear down :8086 and do Option A (or add a second tunnel).
```
This mirrors the SSR serving pattern (jar/binary + HTTP + reverse ssh tunnel).

### BoolSearch / lucene_bool repoint (one line, no recompile)
```bash
# tasks/bm25_index/boolsearch/bs.sh  — change only the IDX line:
#   IDX=/scratch/fast/kun/projects/trec-rag-26/data/built-indexes/climbmix-bm25
#   IDX=/scratch/fast/kun/projects/trec-rag-26/data/built-indexes/climbmix-bm25-chunked
```
`BoolSearch.class` already reads the index dir from argv[0]; analyzer
(`DefaultEnglishAnalyzer`, Porter) and `BM25Similarity(1.2,0.75)` are unchanged
and still match the chunked build's analysis. Do this at cutover (with the
server swap) so the Boolean path is chunk-keyed too.

## 5. Client migration design (parity to dense)

**Core finding: the clients are already chunk-shaped.** `make_hit`/`classify_id`
turn any `_p<page>` id into `kind="chunk"` with the parent docid stripped. So the
"migration" is mostly *the server change*, not client code. Parity mapping:

| field | dense (`search_dense`) | sparse today (whole-doc) | sparse after cutover (chunked) |
|---|---|---|---|
| `id` | chunk id `..._pN` | doc id `shard_x_y` | **chunk id `..._pN`** (from `_id`) |
| `docid` | parent (stripped) | == id (doc) | **parent** (auto-stripped) |
| `kind` | `chunk` | `document` | **`chunk`** (auto) |
| `text` | chunk segment | whole doc | **chunk segment** (server `_source.contents`) |
| `score` | inner-product | BM25 | BM25 |

### `search_sparse.py`
- **Required change: none** for correctness — it already reads `_id` and
  `_source.contents` through `make_hit`.
- **Recommended (small, safe) touch-ups** to make parity explicit and match the
  dense doc-comments:
  - Update the module docstring: it now returns **chunk**-keyed hits
    (`docid`=chunk id, parent derivable) — not whole docs.
  - Tag `meta={"source":"sparse", "granularity":"chunk", ...}` so downstream
    fusion can see the unit granularity without re-deriving.
  - (Optional) if the chunked `index-server` ever omits stored contents, add a
    text-hydration fallback via the docstore (see §6). Not needed while
    `-storeContents` is on.
  A draft of these edits is in `search_sparse.chunked.py` (below), clearly marked
  NOT-applied.

### `search_lucene_bool.py`
- Moves to chunked **at cutover** by the `bs.sh` `IDX=` repoint (§4). No Python
  change — it already `make_hit`s the parsed id, which becomes a chunk id.
  Update its docstring line that says "over the same on-disk Anserini index" to
  note the index is now chunk-keyed. Snippet text becomes the chunk snippet.

### `search_pyserini.py`
- **Deprecate.** It hits the external Waterloo `climbmix-400b` whole-doc index,
  which we do not control and cannot chunk-align. Options (design-only):
  - Leave the file but add a deprecation note in the docstring ("whole-doc,
    external, not chunk-aligned with our dense/sparse; prefer `search_sparse`").
  - It is not registered in `src/tools/search_tool.py`'s `_DISPATCH` (only
    `semantic`/`keyword`/`ssr`/`lucene_bool`), so no tool wiring to remove.
- No functional change required; just the deprecation note.

### `search_tool.py`
- No change. It already surfaces `id`/`docid`/`kind`. The `keyword` blurb can
  optionally note results are chunk passages (cosmetic).

## 6. Optional: text-hydration parity via the shared docstore
If we ever build the chunked BM25 **without** `-storeContents` (to shrink the
1.7 TB `.fdt`), the chunk text can be rehydrated from the existing dense docstore
(`data/built-indexes/climbmix-chunked/docstore/`, keyed by chunk_id) using
`tasks/search_serve/scripts/docstore.py::FlatShardDocStore` — the same store the
dense server uses. That would make sparse and dense share ONE source of chunk
text (perfect parity, no duplicate 1.7 TB). **Not proposed for the first
cutover** (keep `-storeContents` for a self-contained index + working
`/doc`/`_source`), but noted as the clean long-term shape.

## 7. Draft code (NOT applied)
- `tasks/bm25_index/CHUNKED-REINDEX-DESIGN.md` — this doc.
- `src/utils/search_sparse.chunked.py` — proposed docstring + `meta` touch-ups
  for `search_sparse`, clearly marked pending cutover. Does **not** replace the
  live `search_sparse.py`.

## 8. What NOT to do yet (guardrails)
- Do not run Step 1/Step 2 (heavy) or the kill/relaunch until the user confirms.
- Do not edit the live `search_sparse.py` / `bs.sh` before the server flips — the
  clients already behave correctly against the whole-doc server today.
- Do not delete the old `climbmix-bm25` index until the chunked server is
  validated (keep it as instant rollback: just relaunch `:8085` at the old dir).
