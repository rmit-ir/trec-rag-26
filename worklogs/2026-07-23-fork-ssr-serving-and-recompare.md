# 2026-07-23 — Fork SSR: full-corpus serving stand-up + re-run the SSR comparison arm

Goal: retire the old Hazel `ssr-server` and serve the full ClimbMix corpus from the
**UWaterloo Cottontail fork** (stemmed SimpleWarren group-burrows), then re-run the
aus_agent SSR comparison arm and diff its trajectories against the documented
`cmp-ssr` runs (`data/outputs/engine-comparison/comparison_matrix.md`).

## What was built

The fork already ships the entire serving stack (isj package, TASK-34 "Done", 170
tests green), so this was **configuration, not code**:

1. **26 docno→cp SQLite maps** — `tasks/ssr_search/scripts/build_docno_maps.py`
   calls the fork's own `isj_agent.index.build_sqlite_map` on each group's existing
   `docno-cp.tsv`. All 26 built in **50 s** (25 s each, P=13), 31 GB total. Kept the
   `.tsv` in place (the index CLI would delete it).
2. **26 single-burrow servers** — `tasks/ssr_search/scripts/launch_fork_servers.sh`
   launches one `cottontail-jsonl-server --burrow group_NNNN/burrow --port 700N
   --no-auth --threads 4 --rank-threads 2` per group (ports 7000–7025), `setsid` so
   they survive the launcher. All 26 healthy; **~12.8 GB total RSS** (~500 MB each,
   mostly page-cache-attributed mmap — page-cache-bounded as designed).
3. **Fan-out shim** — `tasks/ssr_search/scripts/fork_shim.py`, a stdlib
   `ThreadingHTTPServer` on **:8099** holding the fork's `MultiShardSearchEngine`
   over the 26 `HttpSearchEngine` shards (each owns its burrow's `DocnoMap`). Exposes
   the SAME `/search {query,k}` → `{results:[{docno,rank,score,snippet}]}` contract
   the old `ssr-server` used, so **`src/utils/search_ssr.py` is unchanged** (already
   defaults to :8099). Also `/doc {docno}` and `/healthz`. `MultiShardSearchEngine`
   merges by score across shards — exact because the cover-density ranker is
   stats-free (a doc's score is the same on its shard as on the whole corpus).

The whole chain smoke-tested clean: `(^ uranium enrichment russia)` → 5809 matches,
on-topic snippets; `/doc` returns full document text; docnos resolve via the maps.

## Two bugs found, both fixed at the serving layer

### 1. `mapfile < <(ls | sort)` / array-glob returns junk on this /scratch FS
`GROUPS=( "$OUT"/group_* )` and `mapfile -t GROUPS < <(ls -d "$OUT"/group_* | sort)`
both return **8 numeric junk values** ("1010", "10000001", …) instead of the 26 real
paths — even in a pristine `env -i` shell reading a script file — while `ls`,
`printf '%s\n'`, and `compgen -G` on the *same* pattern all return the correct 26.
Unexplained readdir/glob quirk on the parallel FS. **Fix:** the launcher builds group
paths **by index with `printf group_%04d`** and only uses `compgen -G … | wc -l` to
count. (Symptom before the fix: servers started with burrow `1010/burrow` → "could
not open burrow: Can't read configuration from: 1010/burrow/dna".)

### 2. Case-sensitive query path over a case-folded index (the big one)
The burrows were built `--stem porter`; the porter/StemmingTokenizer **lowercases
every indexed token**, but the fork's **bare-term GCL query path is case-SENSITIVE**.
So every capitalized entity the agent naturally writes zeroes out:

```
   total_matches   query
          0         (^ uranium Russia)          Russia →      0
      43368         (^ uranium russia)          russia → 43368
          0         (^ uranium Kazakhstan)      Kazakhstan →   0
       7615         (^ uranium kazakhstan)
          0         HALEU                        HALEU →        0
        254         haleu
          0         Russia                       Russia →       0
    3295378         russia
```

This — not genuine over-constraint — was inflating the fork run's zero count. Quoted
phrases already get folded (`(^ "high assay low enriched uranium")` matched), only
bare terms were affected.

**Fix:** case-fold the query in the shim (`query.lower()` in `/search`). GCL has no
case-bearing alphabetic operators (`^ + << >> # " ( )`), so lowercasing the whole
expression is safe. Standard IR practice (fold queries to match a folded index).
After the fix: `(^ uranium Russia)` → 43368, `(^ HALEU Russia China)` → 37 (was 0).

> **Upstream-proper location** is the fork's query tokenizer (would also fix the isj
> agent + any direct `cottontail-jsonl-server` user, and is PR-able). The shim fix is
> the serving-layer equivalent and unblocks the comparison now. Flagged for follow-up.

## Probe: rag2026-9 (nuclear fuel / HALEU) — before vs after case-fold

Metrics via `data/outputs/engine-comparison/extract_ssr_stats.py`
(`#search / #zero / #uniqDoc / ev_chars / maxAND`):

| run | search | zero | uniqDoc | ev_chars | maxAND |
|---|---|---|---|---|---|
| `cmp-ssr` (old Hazel) | 15 | **6** | 87 | 1278 | 9 |
| `cmp-ssr-fork` pre-fix (case-sensitive) | 23 | **10** | 108 | 920 | 5 |
| `cmp-ssr-fork` post-fix (case-folded) | 16 | **0** | 134 | 899 | 6 |

Case-folding **eliminates the zeros** (6 → 0) and **improves recall** (87 → 134
unique docs). Evidence stays cover-bound (~900 chars; the `window` param does NOT
extend the shortest-substring cover — 256/384/512/640 all return the same ~926
chars). Richer 512-token evidence would need doc-hydration (the `ssr_hydrate` path),
a separate follow-up; not blocking.

## Full 10-topic re-run — `cmp-ssr` (old Hazel) vs `cmp-ssr-fork`
gpt-5.6-luna, 500k budget, `--search-backends ssr`, all 10 completed.
`#search / #zero / #uniqDoc / ev_chars / maxAND`:

| qid | old srch/zero/uniq | old ev/AND | fork srch/zero/uniq | fork ev/AND |
|---|---|---|---|---|
| rag2026-0 | 12/**1**/108 | 1360/6 | 16/**0**/150 | 955/4 |
| rag2026-1 |  9/**0**/83 | 1263/10 |  8/**0**/68 | 855/0 |
| rag2026-2 | 14/**5**/82 | 1297/8 | 17/**1**/153 | 911/5 |
| rag2026-3 | 15/**7**/79 | 1229/10 | 16/**0**/159 | 870/5 |
| rag2026-4 |  8/**1**/54 | 1269/7 | 14/**0**/106 | 931/3 |
| rag2026-5 | 19/**11**/44 | 1265/8 | 16/**1**/113 | 907/6 |
| rag2026-6 | 10/**1**/90 | 1264/10 | 23/**6**/170 | 900/6 |
| rag2026-7 | 12/**0**/107 | 1292/9 | 20/**0**/163 | 916/3 |
| rag2026-8 | 18/**4**/106 | 1207/11 | 17/**1**/149 | 862/4 |
| rag2026-9 | 15/**6**/87 | 1278/9 | 16/**0**/137 | 905/5 |
| **TOTAL** | 132/**36**/840 | 1272 | 163/**9**/1368 | 901 |

**Headline:** zeros **36 → 9** (27% → 5.5% of searches); unique docs retrieved
**840 → 1368 (+63%)**; `maxAND` down (arity cap + broader matches mean the agent no
longer has to stack rare tokens). Every topic that previously zeroed heavily is now
clean. All 10 reports completed with 10–25 citations each.

### Trajectory changes on the previously-worst topics
- **rag2026-3 investment (7 → 0 zeros):** the cleanest demonstration. OLD zeroed on
  every `(^ Australia …)`, `(^ moneysmart …)`, `(^ ETF … Australia)` — all
  case-sensitivity misses on "Australia"/"ETF". FORK: all 16 queries return 10 hits
  (`(^ Australia invest diversify)`, `(^ superannuation salary sacrifice tax)`,
  `(^ investment tax Australia capital gain)`). A pure case-fold win.
- **rag2026-5 de-minimis (11 → 1 zeros):** OLD flailed — stacked UFLPA/Xinjiang/
  Shein/Temu/Mexico/Canada + 2025 dates into ANDs that collapsed, then kept *adding*
  rare tokens. FORK: the same entity-heavy intents now match
  (`(^ "Section 321" Mexico)` 10h, `(^ de minimis suspension China)` 10h,
  `(^ UFLPA de minimis customs)` 2h). One residual zero
  (`(^ de minimis tariff crackdowns)`).

### The one "regression" is actually correct behaviour — rag2026-6 COVID (1 → 6)
The 6 fork zeros are all genuine **multi-phrase over-constraint**, not the case bug:
`(^ COVID-19 "January 2020" outbreak WHO)`, `(^ COVID-19 "May 2023" "public health
emergency")`, `(^ COVID-19 "supply chains" inflation)`, etc. — several required
quoted phrases + specific terms co-occurring in one document. Two real subtleties:
(a) **quoted phrases are exact and UNSTEMMED**, so `"supply chains"` won't match a
doc that says "supply chain"; (b) the agent **recovered correctly** — after the
zeros it dropped to `(^ pandemic vaccine)` / `(^ pandemic economy inflation)` → all
10h (the drop-on-zero instruction working). Net report: 25 refs / 34 sentences.

### The remaining regression axis: evidence size (1272 → 901 chars)
Fork cover snippets are ~30% thinner than the old Hazel SSR's, and the `window` param
does not extend them (cover-bound). This is the only metric that got worse. Fix is
doc-hydration (fetch full doc via `/doc`, extract a ~512-token window around the
cover — the `src/utils/ssr_hydrate.py` path). Deferred; not blocking the comparison.

## Verdict
The fork stack fixes the **dominant** documented SSR weakness (over-constraint zeros:
36 → 9, and most residual zeros are truthful precision, not bugs) and materially
improves recall (+63% unique docs). The secondary weakness (thin evidence) is
unchanged and now isolated to a single, well-understood follow-up (doc-hydration).
SSR as a standalone backend is now competitive on the zero-rate axis where it was
previously self-defeating.

## 2026-07-24 — moved both fixes INTO the fork (branch `claude/query-casefold-and-paragraph-hydration`)

Per the "server-side, not client-side" principle, both the case-fold and the
evidence-window work now live in the fork C++ (the shim's `.lower()` workaround is
removed). All fork tests green (`//test:tests //test:jsonl_test
//test:jsonl_server_test`), plus two new regression tests.

### Change 1 — case-fold in the query path (`apps/jsonl_core.cc`)
Root cause: `cover_search` → `cover_rewrite` → `emit_cover_term` emitted a **bare
term as its exact surface form, unfolded** (`*out += t`), while the indexing path
and the quoted-phrase path both fold via the tokenizer. Fix: a guarded ASCII
`ascii_fold` (A–Z only, so `_` etc. are safe) applied to the bare-term branch and
inside `stem_atom` (so `word*` families fold before Porter). Verified server-side
(shim no longer lowercases): `(^ uranium Russia)` == `(^ uranium russia)` == 43368;
`Russia` == `russia` == 3.3M. Regression test `JsonlCover.BareTermIsCaseFolded`.

### Change 2 — paragraph-aware evidence band (`cover_summary_paragraph`)
New opt-in mode (default OFF, so the isj agent + existing tests are unchanged),
selected by `CoverSpec.paragraph` / server flags `--paragraph --band-min/target/max`
(defaults 200/500/700). For each cover: translate a generous ±band_max token
window, locate the cover's own text in it (byte-exact — same `translate()` source —
nearest-to-center for repeats), split on blank lines, take the cover's paragraph(s)
and grow outward **whole-paragraph-by-whole-paragraph** until the token estimate
(words×1.3, matching the pipeline chunker) reaches `[band_min, band_target]`, never
exceeding `band_max`, never cutting a paragraph. Expands from the cover's **native
token span** — no fragile string-relocation of a summary. Regression test
`JsonlCover.ParagraphBandGrowsWithinTheBand`.

> **Bug caught in review:** `addr` is signed `int64_t`, so the first cut at the
> grow loop used `(addr)SIZE_MAX` as an "unavailable neighbour" sentinel — which is
> **−1**, not huge. That made the loop pick the exhausted side, underflow `lo`, and
> either read out-of-bounds (HTTP 500) or spin forever (8 s timeouts on ~14/26
> shards). Fixed with explicit `can_prev`/`can_next` guards.

**Evidence richness, before vs after (same `(^ uranium enrichment russia)`):**
old Hazel ~1272 chars → fork cover-snippet ~900 chars → **fork paragraph band
~2200–2700 chars (~481–540 tokens)**, on clean paragraph boundaries. The "thin
evidence" weakness is now *reversed* — evidence is richer than the original Hazel
SSR, and sized to the same 200–500-token band as our paragraph-aware chunking.

Serving: `launch_fork_servers.sh` now passes `--paragraph --band-*`; the shim is
unchanged (no per-request params needed). Re-ran the 10-topic arm as `cmp-ssr-fork-v2`.

### Three-way result (`extract_ssr_stats.py cmp-ssr cmp-ssr-fork cmp-ssr-fork-v2`)

| metric (Σ 10 topics) | old Hazel | fork-v1 (shim-fold, thin) | **fork-v2 (server-fold, paragraph)** |
|---|---|---|---|
| searches | 132 | 163 | 136 |
| zero-result | **36 (27%)** | 9 | **7 (5.1%)** |
| unique docs | 840 | 1368 | 1125 |
| **evidence chars/hit** | 1272 | 901 | **3838 (3.0×)** |

Both original SSR weaknesses resolved: zeros 36→7 (server-side case-fold) and evidence
1272→3838 chars (paragraph bands). Per-hit `returned_chars` up to 5283 (multi-cover
bands); sample bands are clean paragraph prose on blank-line boundaries. All 10 reports
completed with 10–18 citations. Fewer searches (136) than fork-v1 (163) — richer evidence
per hit means more grounding per search.

## Artifacts
- Servers: `tasks/ssr_search/scripts/launch_fork_servers.sh` (start / `stop`)
- Maps: `tasks/ssr_search/scripts/build_docno_maps.py`
- Shim: `tasks/ssr_search/scripts/fork_shim.py` (:8099)
- Stats: `data/outputs/engine-comparison/extract_ssr_stats.py <run_id>…`
- Runs: `data/outputs/aus_agent/*.{output,trajectory}.json` (run_id `cmp-ssr-fork`)
