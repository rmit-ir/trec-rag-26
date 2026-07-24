# 2026-07-22 — SSR full-corpus build, 4-way engine comparison, and SSR optimization

Running log for the SSR/Cottontail optimization arc: build the full-corpus SSR
index, wire it into the `aus_agent` deep-research harness alongside the other
retrieval backends, run a controlled comparison, and then improve SSR based on
what the comparison exposed. This file is the source of truth for state +
decisions; update it as we go.

## TL;DR / current state (as of this entry)

- ✅ **Full-corpus SSR index built**: 409 Hazel burrows, **3.5 TB**, 563 M docs,
  at `data/built-indexes/ssr-climbmix-full/` (GROUP_SIZE=16). Built in 2h37m.
- ✅ **4 retrieval backends wired into `aus_agent`** and toggleable via
  `--search-backends` (alias `--engines`): `semantic` (dense Jina-v5),
  `keyword` (hosted BM25 OR), `ssr` (Cottontail GCL Boolean), `lucene_bool`
  (Lucene query-parser over the BM25 index).
- ✅ **10-topic × 4-backend comparison complete** (40 runs, `gpt-5.6-luna`,
  full 500k budget). Report: `data/outputs/engine-comparison/comparison_matrix.md`.
- ✅ **Tool-instruction fix applied** to the SSR query guidance (arity cap +
  drop-on-zero). Un-validated until re-run.
- 🔬 **Root-cause discoveries**: the SSR index is **UNSTEMMED**; its RAM is
  **all anonymous heap** (~460 MiB × #burrows); at 409 burrows `ssr-server`
  requests **818 threads** (2×collections) → oversubscribes 112 cores.
- ⏸️ **Re-index to 26 burrows (GROUP_SIZE=256) started then STOPPED** — pivoting
  after discovering the Waterloo fork (see Decisions).
- ⛳ **PENDING DECISION**: adopt the UWaterlooIR Cottontail fork (StemmingTokenizer
  + HashingFeaturizer + configurable-window server) for the SSR stack.

## Servers / infra state

- **SSR serve** (`serve.py` :8099) — currently **DOWN** (stopped to free 187 GiB
  for the re-index). Old 409-burrow index intact on disk.
- **Dense** (`search_serve` gunicorn :8088) — **UP, 1 worker** (`-w 1`, ~114 GiB
  anon). The user restarted it after its ram-watchdog self-killed at 71%.
- **Hosted BM25** (`index-climbmix-bm25.dsync.net`) — up (used by `keyword`).
- **Hosted dense** (`index-climbmix-jina-v5-nano.dsync.net`) — was **502** during
  the run; local :8088 is the working dense endpoint (set `DENSE_SEARCH_URL`).
- **LLM**: OpenAI via Azure endpoint in root `.env`
  (`OPENAI_BASE_URL=…trec-rag-2026-llm-resource.openai.azure.com`,
  `OPENAI_API_KEY`). Models reachable: `gpt-5.6-luna` (default), `gpt-5.6-sol`.

## Code changes made (all UNCOMMITTED — user commits)

- `src/utils/search_ssr.py` (NEW) — SSR client → `serve.py` :8099.
- `src/utils/search_lucene_bool.py` (NEW) — Lucene client → `bs.sh` subprocess
  (~0.4 s/call; JVM heap capped via `bs.sh -Xmx${BS_XMX:-4g}`).
- `src/tools/search_tool.py` — 4-engine dispatch + `build_search_tool(engines)`
  engine-aware tool factory (NL vs GCL vs Lucene query guidance). **Applied the
  SSR instruction fix here** (see below).
- `src/tools/search_boolean_tool.py` — synced GCL guidance.
- `src/systems/aus_agent/tools/search.py` — `build_search_tool_def(engines)` +
  `default_engine` threading so a single-engine run pins its backend.
- `src/systems/aus_agent/tools/__init__.py` — export `build_search_tool_def`.
- `src/systems/aus_agent/agent.py` — `run_agent(engines=…)`, records `engines`
  in metadata, threads `default_engine` to `_execute_tool_calls`.
- `src/systems/aus_agent/run.py` — `--search-backends` (alias `--engines`,
  env `RUN_AUS_AGENT_SEARCH_BACKENDS`, default `semantic,keyword`).
- `tasks/ssr_search/scripts/build_full_index.sh` — parameterized `OUT_NAME`;
  probe-group RAM measurement → parallelism; resumable.
- `tasks/ssr_search/scripts/calibrate_bigwig.sh` (NEW) — timed bigwig→hazel calib.
- `tmp/Cottontail/apps/jsonl.cc` — `CT_STEMMER` env → `parameters:stemmer:<name>`
  (SEGFAULTS on bigwig; see Discoveries). **Moot if we adopt the fork.**
- `tmp/Cottontail/apps/ssr-server.cc` — `WINDOW_TOKENS` → env-tunable
  `window_tokens()` (default **512**, was 200); via `SSR_WINDOW_TOKENS`.
  **Moot if we adopt the fork** (their server already has `window` config).

## How the full index was built

`build_full_index.sh` → 409 contiguous 16-shard groups, each
`jsonl --bigwig` → `finish-merging` → one mmap-named Hazel. 14-way parallel
(probe measured ~4 GB peak RSS/worker), ~22 s/group aggregate, 2h37m total,
409/409 converged, 0 failures. Serving confirmed across all shards; the
grief-biology "truthful zeros" from the single-shard era now return real hits.

**Key correction from earlier worklog**: SSR serving is NOT page-cache-bounded.
`ssr-server` RSS is **100 % anonymous** (`RssAnon=186.8 GiB, RssFile=0`),
scaling ~linearly with burrow count (measured **~360–460 MiB/burrow**; 30-burrow
test = 11.3 GiB). The Hazel files are read into heap, not mmap-served. This is
the RAM problem.

## The 4-way comparison

- Topics: 10 diverse TREC-RAG-2026 test narratives (rag2026-0..9),
  `data/outputs/engine-comparison/topics10.tsv`.
- Method: same `aus_agent` loop, one backend per run via `--search-backends`,
  distinct run-ids `cmp-{dense,keyword,ssr,lucene}`, `gpt-5.6-luna`, full budget.
- Analysis: 10 parallel sub-agents (one per topic) graded each topic's 4 runs
  from actual queries + committed docs + final answer.
- Output: `data/outputs/engine-comparison/comparison_matrix.md` (findings +
  per-topic tables with engines-as-columns + numeric matrix + full trajectories).
  `analyze.py` regenerates the numeric matrix + trajectories from the run JSONs.

**Winner tally: dense ~5, keyword ~3, lucene ~2, SSR 0.**

**SSR's two weaknesses (the actionable output):**
1. **Over-constraint → truthful zeros.** Unstemmed exact-token AND: agents
   stacked 4–7 required terms → empty sets on 7/10 topics. Worst: rag2026-5
   (de-minimis) **11 zeros / 19 searches**; rag2026-3 6/15; rag2026-9 6/15.
   Agents kept *adding* rare tokens instead of dropping — the wrong recovery.
2. **Thin evidence windows.** Even when ANDs didn't zero (rag2026-7), SSR's
   ~200-tok shortest-substring snippets are shallower than BM25/dense full-doc
   passages → more uncited answer sentences.

**SSR's real niche**: precision/co-occurrence/disambiguation + truthful zeros,
not broad-recall synthesis.

### Operator ground-truth (re-confirmed; one sub-agent got it backwards)

`(^ …)` = **AND** (all_of), `(+ …)` = **OR** (one_of). Proven again here: a
6-term `(^ …)` returning 0 is only possible under AND. (`gcl/parse.cc`.)

## Tool-instruction fix (applied, `src/tools/search_tool.py` `_GCL_GUIDANCE`)

Changes vs. the old "2–4 terms, don't be shy" guidance, all backed by the sweep:
- **Hard-cap AND arity at ~3**, led by the single rarest/most-distinctive term.
- **On empty, DROP the weakest term — NEVER add another.** If a 2–3-term AND is
  still empty, switch/move on; don't pile on qualifiers.
- One `(^ …)` per facet; disambiguate a polysemous term with ONE context term;
  widen with OR **inside** the AND, not by lengthening it.
- Framing: "precision/co-occurrence instrument — not for broad-topic recall;
  widen with keyword/semantic." (Also synced into `search_boolean_tool.py`.)
- **Un-validated** — needs a re-run of `cmp-ssr` to measure zero-rate drop.

## Discoveries (evidence)

### 1. The SSR index is UNSTEMMED (root cause of zeros)

`utf8` tokenizer stores literal lowercased tokens; no stemming. Empirical probe
(2 burrows) — different inflections return DIFFERENT top docs:
```
(^ reactor)     -> shard_00011_46081   (nuclear reactor)
(^ reactors)    -> shard_00023_27855   (ammonia reactors)      <- different!
(^ enrichment)  -> shard_00023_41995
(^ enrich)      -> shard_00020_57253                            <- different!
(^ enriched)    -> shard_00021_74399                            <- different!
```
So `(^ Medicaid expansion …)` can't match "expansions/expanding" → over-constraint
zeros. **The user's "stem words" instinct is correct — fix belongs in the index.**

### 2. RAM = anonymous heap ∝ burrow count

`ssr-server` `RssAnon=186.8 GiB, RssFile=0` for 409 burrows; ~360–460 MiB/burrow.
Grows with a per-burrow vocabulary dictionary (the `json`/utf8 featurizer path).

### 3. Thread oversubscription at 409 burrows

`ssr-server.cc thread_budget()` gives each burrow ≥2 threads (`base = 2 ×
collections`). 409 burrows → **818 threads** requested on 112 cores (224 HT) →
oversubscription. Fewer burrows (≤~56) fixes both RAM and threads. Box: 2 sockets
× 28 cores × 2 HT = 112 logical / 224 threads, 2 NUMA nodes, 503 GB RAM.

### 4. Dense also loads to anon; RAM coexistence

`search_serve` worker `RssAnon≈114 GiB` (PQ is `StaticMemoryIndex`, in-RAM, not
mmap — despite the code comment). Its `ram-watchdog` SIGTERMs the process group
at ≥70 % used. SSR(187) + dense(114 ×N workers) collide. **Coexistence recipe:
dense `-w 1`, SSR reduced.** With dense 1-worker + SSR 187, box sat at 61 % used
(193 GiB avail) — stable.

### 5. Stemming in original Cottontail SEGFAULTS

`jsonl --bigwig` with `parameters:stemmer:porter` parses but **segfaults**
(rc=139) during stemmed indexing — matches `ai/log.md`'s note on a
stemmer/immutable-Hazel conflict. `--simple` rejects the `parameters:` option.

## THE FORK: `tmp/Cottontail-uwaterloo` (UWaterlooIR/Cottontail)

Cloned (recorded in `tmp/REFERENCE-REPOS.md`). The corpus authors' own fork —
solves all three SSR problems cleanly:
- **`StemmingTokenizer`** (tokenizer name `"stemming"`): decorator wrapping a base
  tokenizer + stemmer; emits BOTH exact and stemmed features **co-located** at the
  same address, so exact queries still work AND inflections match. Recipe:
  `[ tokenizer:[name:"ascii",recipe:"noxml"], stemmer:[name:"porter",recipe:""] ]`.
  Clean, no segfault.
- **`HashingFeaturizer`** (their DEFAULT featurizer, name `"hashing"`): fixed
  feature space, no growing vocab dict → likely fixes the 187 GiB anon RAM
  *regardless of burrow count* (may make the GROUP_SIZE reduction unnecessary).
- **`cottontail-jsonl-server.cc`**: `window` / `snippet_chars` are config fields
  + bearer-token auth — the 512-token window is just a setting.
- **`climbmix-poc.cc`**: their ClimbMix build uses `hashing` featurizer +
  `ascii noxml` tokenizer + `SimpleBuilder`; corpus at
  `/share/corpora/climbmix-400b-corpus-jsonl`, shards `shard_%05d.jsonl.gz`.

## DECISION (user, this session): adopt the Waterloo fork; RETIRE our SSR stack

- **Retire `tasks/ssr_search`** (our Hazel-based `serve.py`/`ssr_engine.py` wrapper
  + the 3.5 TB Hazel index). The fork explicitly cautions against the Hazel path
  ("builds no features on Hazel — prefer SimpleWarren/Bigwig").
- **Standardize on the fork's stack**: `cottontail-jsonl-index` (SimpleWarren +
  `--stem porter` + hashing featurizer) → `cottontail-jsonl-server` (configurable
  `window`/`snippet_chars`, bearer auth) → `isj/` ISJ Searcher agent. Run guide:
  `tmp/Cottontail-uwaterloo/docs/design/reference-specs/running-the-search-stack.md`.
- **Working copy**: `tmp/Cottontail-uwaterloo`, git remotes `upstream`=UWaterlooIR
  (our base; already latest, 0 behind), `original`=claclark (reference only;
  Waterloo is 342 ahead, claclark's 11 unsynced commits are Meadowlark/misc —
  NOT merged). Branch `trec-rag-paragraph` for our minimal changes.
- **Fork conventions to honor**: plan-before-change, feature-branch + PR (never
  commit `main`), Backlog.md workflow, repo-boundary rule (user OK'd crossing it
  to index the outer `data/` ClimbMix and write under outer `data/built-indexes/`).
- Fork build script: `tasks/ssr_search/scripts/build_cottontail_fork.sh`
  (mamba gcc-13 + bazelisk; builds `cottontail-jsonl-{index,query,server}`).

### Fork VALIDATED (2-shard test, `data/built-indexes/fork-stemtest`)

Built with `cottontail-jsonl-index --input <2 shards> --burrow … --docno-field id
--stem porter` (utf8 + porter StemmingTokenizer + default hashing featurizer);
172,032 docs, 68 s, 483 MB. All three problems solved:
- **Stemming works**: `--count` exact vs `--stem` — `reactor` 217/`reactors` 155
  (exact, differ) → both **306** with `--stem`; `enrichment` 450/`enriched` 488 →
  both **1813**. Inflections collapse → over-constraint zeros fixed at the root.
- **RAM tiny + mmap-bounded**: `cottontail-jsonl-server` after 12 warmed queries =
  **VmRSS 43 MiB (anon 38, file 5)** for the 2-shard/483 MB burrow. SimpleWarren
  mmaps the burrow → serving RAM = reclaimable page-cache working set, NOT the
  187 GiB anon of the old Hazel path. The RAM problem is gone.
- **Thread budget**: server auto-budgets `--threads × --rank-threads ≤ hardware`
  (no 2×collections explosion).
- **Query works**: `POST /tools/search_gcl {"query":"(^ reactor enrichment)",
  "stem":true}` → best-passage snippets, ranker ssr, 14 ms.
- API: `GET /healthz|/describe`, `POST /tools/{search_text,search_gcl,cover_search,
  tiered_query_search,get_document}`; tools take `stem`, `top_k`, `full_text`.
- **Note**: current `best_passage` is the tight cover (~3 words) → confirms we want
  method (b) paragraph windows for evidence depth.

### SUPERSEDED: method (b) fork paragraph annotations → docstore-hydration instead

User's better idea: do NOT modify the fork's index/query at all. SSR returns only
metadata (docid + cover text); we fetch the full doc from the **dense server's
docstore** (`GET /doc/{docid}`, byte-identical to raw corpus, verified) and cut a
**match-centered SLIDING WINDOW** at get-time. Keeps the fork pristine (upstream
tracking), one Python place for text shaping, no re-index, no C++ port.

- Helper: `src/utils/ssr_hydrate.py` — `windowed_evidence(text, cover,
  window_tokens=512)` → `{title, text (window), tokens_before, tokens_after}`.
  Title = first line if short else first sentence (corpus has no title field).
  Token estimate = words×1.3 (matches the corpus pipeline). Tested live vs
  `:8088` docstore — clean titles + correct before/after token counts.
- **Prereq for wiring**: the fork server returns `cp` (address), not docid;
  building `docno-cp.sqlite` (from the `docno-cp.tsv` the indexer dumps) makes
  cp↔docno translation work so SSR results carry the docid (to cite + to fetch
  from the docstore). Run guide: `…/running-the-search-stack.md`.
- Remaining wiring: (1) build `docno-cp.sqlite`; (2) point `search_ssr.py` at the
  fork server + hydrate each hit via `ssr_hydrate` against the docstore.

### (retired) Method (b) paragraph annotations — was to implement on the fork

Insertion points found:
- **Index** `src/content_index.cc ContentIndexer::add_document`: today it does
  `builder_->add_text(whole contents)` → `[p,q]` → `add_annotation(":item",p,q)`.
  Whole-text tokenization means paragraph spans need per-paragraph token counts
  (tokenize each blank-line paragraph, cumulate) — touches ContentIndexer (+ maybe
  a tokenizer handle from Builder). Add `:paragraph:` per paragraph; `:item` stays.
- **Query** `apps/jsonl_core.cc` cover-summary builder (~L348, "window of max(W,
  cover_length) tokens centered on the cover"): return the smallest `:paragraph:`
  containing the cover instead of the token window; fall back to window if none.

Minimal additive diff on `trec-rag-paragraph`, gated behind a `--paragraphs` flag:
1. Index side (`apps/jsonl_core.cc`, where each doc gets its `:item` annotation):
   also emit a `:paragraph:` annotation per paragraph (blank-line split, same rule
   as `tasks/chunking-strategy/scripts/chunkers.py`). `:item` + existing queries
   untouched.
2. Snippet side (the `(>> :item match)` path, ~`jsonl_core.cc:1352`): return the
   smallest `:paragraph:` containing the cover via `(>> :paragraph: match)`
   instead of a fixed token window; fall back to the window if no paragraph.

## Decisions / next steps

1. **DECIDED (user): adopt the Waterloo fork.** Validating small, then full re-index.
   aligned design fixes zeros + RAM + window; authors' ClimbMix-proven).
2. If yes → **validate small first**: build fork binaries + a 2-shard
   `stemming`+`hashing` index; confirm `(^ reactor)`≡`(^ reactors)` AND measure
   per-burrow RAM (does hashing collapse the 460 MiB/burrow?). Then decide
   burrow count and do the full re-index once, with stemming + hashing + wide
   window.
3. **Then run the ablation** on the new index (SSR-only, vs unstemmed baseline):
   stemmed vs unstemmed × window 200 vs 512 × luna vs sol × old vs new
   instruction. Metric: zero-rate, unique docs, commits, graded trajectory.
   (Burrow count doesn't confound zero-rate — it's corpus-wide.)
4. **Commit the `cmp-*` runs** so they surface in the dsync viewer (the viewer
   serves published/committed runs; ours are untracked in `data/outputs/aus_agent/`).
5. Optional dense improvement: `StaticMemoryIndex` → `StaticDiskIndex` (mmap,
   shared across workers, reclaimable) if higher concurrent QPS is ever needed;
   for the current 1-agent workload, 1 worker is right.

## Artifacts

- Index: `data/built-indexes/ssr-climbmix-full/` (409 burrows, 3.5 TB).
- Comparison: `data/outputs/engine-comparison/{comparison_matrix.md,analyze.py,topics10.tsv}`.
- Runs: `data/outputs/aus_agent/*.{output,trajectory}.json`, run-ids `cmp-*`.
- Fork: `tmp/Cottontail-uwaterloo/` (+ row in `tmp/REFERENCE-REPOS.md`).
- Probe logs: `/tmp/ssr-*.log`, `/tmp/cmp-cmp-*.log`.
