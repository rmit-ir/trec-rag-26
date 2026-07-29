# 2026-07-28 — Chunked BM25 cutover: sparse client, viewer, doc-by-id, page-prefix debt

## What happened

The sparse (BM25) index-server was relaunched against the **chunked** index
(`data/built-indexes/climbmix-bm25-chunked/`, 921,892,634 chunks) on port 8085,
so `index-climbmix-bm25.dsync.net/api/search` now returns **chunk ids**
(`<docid>_p<page>`) with chunk-segment text — the same shape dense already
returned. Both retrieval engines are now page/chunk-format.

Launch command (user):
```
java -Xmx32g -Xms8g --add-modules=jdk.incubator.vector --enable-native-access=ALL-UNNAMED \
  -Djava.awt.headless=true -Dfile.encoding=UTF-8 \
  -Dlucene.FSDirectory.class=org.apache.lucene.store.MMapDirectory \
  -jar build/libs/index-server.jar \
  --index-path=.../data/built-indexes/climbmix-bm25-chunked \
  --preload='*.tim,*.tip' --bm25-k1 0.9 --bm25-b 0.4 --host=0.0.0.0 --port=8085
```
(Reused port 8085, so the reverse tunnel to dsync.net was untouched.)

## Code changes (this session)

### Sparse client — `src/utils/search_sparse.py`
No functional change was required (`make_hit`/`classify_id` in
`search_types.py` already derive `kind="chunk"` + parent docid from the
`_p<page>` suffix). Applied the design's post-cutover shape: chunk-keyed
docstring + `meta["granularity"]="chunk"` + `id` in the `__main__` print.
Verified through the real code path: `search_sparse("nuclear power…")` →
`id=shard_..._p2, docid=shard_...(stripped), kind=chunk, text present`.
Removed the now-applied draft `src/utils/search_sparse.chunked.py`.

### Viewer (`tasks/outputs_viewer`) — drop full-doc, get doc-by-id as-is
Per the directive "the viewer shouldn't hardcode what search backend id is
parsed as what — just get doc by id as-is, and drop the full-doc one":
- `src/lib/server/docFetch.ts`: collapsed to a single `fetchDoc(id)` that
  fetches the id **unchanged** from the docstore (dense `GET /doc/{id}`,
  chunk-keyed, first; sparse doc-by-id fallback). **Removed** `fetchFullDoc()`,
  the Pyserini whole-doc fetch, the `prefer`/`source` backend hint, and the
  `_p<page>`→parent stripping.
- `src/app/api/doc/[id]/route.ts`: dropped `?full=1` and `?source=` handling —
  now just `fetchDoc(id)`.
- `src/components/session/DocSidebar.tsx`: removed the "Full document" tab, its
  SWR fetch, the `source` prop, and the parent-fallback chip. One view: the
  retrieval unit as-is.
- `src/components/session/SessionView.tsx`: removed the `docSources` map that
  hardcoded `search_engine==="keyword" → sparse, else dense`; no longer passes
  `source` to the sidebar.

Not fully type-checked here — `tasks/outputs_viewer/node_modules` is absent;
run `npm install && npx tsc --noEmit` (or the build) to confirm. No dangling
refs remain (`grep` clean for `fetchFullDoc`/`docSources`/`?full=1`/`source=`).
`env.ts` still exports now-unused `pyseriniBaseUrl`/`pyseriniToken` (harmless
dead exports; prune later if desired).

### Judging — `tasks/task-comparison/rubric-judge/ab_judge.py`
Committed docs are now chunk ids, so the whole-doc Pyserini `fetch_doc` no
longer resolves them. Switched text fetch to the dense docstore
`GET {DENSE_SEARCH_URL}/doc/{chunk_id}` (chunk-keyed). Gotcha: that proxy 403s
the stock `Python-urllib` User-Agent — must send a non-default UA (as
`search_dense.post_json` already does).

### Prompt A/B re-run (validity fix)
The prompt A/B run (`run_prompt_ab.sh`) was mid-flight when the sparse server
switched: `promptab-default` had finished 6 topics on **whole-doc** keyword
(61 whole-doc refs, 0 chunk) while the rest would run on **chunked** — a split
id-space + retrieval-behavior confound. Killed it, moved the 6 whole-doc
outputs aside (scratchpad, non-destructive), and restarted both arms clean on
the chunked backend so the comparison is consistent.

## KNOWN ISSUE (design debt) — "Page N of document:" is baked into chunk text

The chunker was configured with `title_chunks=1`, which prefixes chunks 2+ with
a literal **`"Page N of document: <first-line-title>\n\n"`** string that is
stored *inside* the chunk's indexed/returned text. Example (dense
`/doc/shard_02125_34114_p2`):

```
Page 2 of document: An accident could result in dangerous levels of radiation …
```

Problems:
1. **It's not a real page.** "Page N" is the chunk index (1-based), not a
   physical document page — there are no "full pages"; the label reads as if
   there were, which is misleading.
2. **Layout/metadata leaked into content.** The page number + title belong in
   **metadata returned alongside the hit / doc-by-id** (e.g. `{page, title}`
   fields), not concatenated into the searchable/returned text. As-is it:
   - pollutes BM25 term stats (every chunk 2+ contains "Page", "document"),
   - pollutes embeddings and any answer that quotes the chunk verbatim,
   - can't be toggled off by consumers.

**Why it's not fixed now:** the prefix is baked, byte-identical, into BOTH the
dense docstore (`climbmix-chunked`) and the just-built chunked BM25 index
(they were deliberately aligned). Removing it requires **re-chunking**
(`chunk_corpus.py` with `title_chunks=0` or a metadata-carrying chunker) and
**re-indexing both** (dense DiskANN + Anserini BM25) — a multi-hour rebuild of
~922M chunks. Deferred.

## Chunk-native commit + `get_documents` navigation tool

Made the aus_agent commit/citation core UNIT-ID-native so it commits the exact id
the search engine returns (a chunk id `<docid>_p<page>`), unedited, and added a
`get_documents` tool for reading adjacent pages.

- `context.py`: the ledger now keys on each result's `id` (not the parent
  `docid`) — `committed_ids`/`rejected_ids`/`staged_ids`, compaction, and
  duplicate handling all operate on unit ids. A legacy `docid` key in a commit
  selection is accepted as a fallback (for an unpaginated result it equals the
  id; a bare parent docid correctly won't match a staged chunk unit).
- `commit_context.py`: the tool takes `id` (exactly as returned, keep `_p<n>`);
  distinct pages of a document are distinct units.
- `agent.py`: citations are matched against committed unit ids; `_collapse_to_docs`
  maps the unit-id references to parent docids and reindexes citations **only for
  the organizer `output.json`** (the trace/submission format is unchanged, so the
  viewer is unaffected). `references_full` now carries the committed chunk ids.
- New `tools/get_documents.py`: fetches chunks by id from the dense docstore
  (`GET /doc/{id}`, chunk-keyed; non-default UA to dodge the proxy 403) and stages
  them exactly like a search batch; out-of-range ids come back in `missing`.
  Registered in the tool set + the agent loop (mirrors the search branch).
- Prompt (`prompts/system/default.md`): commit & cite by `id` unedited, distinct
  pages are distinct units, plus a "reading more around a result" section that
  teaches constructing neighbour page ids and fetching them with `get_documents`.
- `test_context.py`: updated to the id contract + a new distinct-page-commit /
  `_collapse_to_docs` test. 47/47 pass.

**10-topic dev test (`chunknav-dev10`, chunked backend, default prompt):** all 10
completed. 88 searches, 24 commit batches, **151 committed units, 100% chunk-level
(`_pN`)**; **5/10 topics committed the same document at >1 page** as distinct units
(organically, from search results). Organizer `output.json` references collapse to
parent docids correctly (9–22 refs/topic; citation indices valid). **`get_documents`
was invoked 0 times** — search already surfaced the needed pages, and the existing
"do not call another tool merely to fetch the same document" line likely suppresses
proactive fetching. The tool is mechanically verified (staging + commit path, unit
test); exercising it in real runs may need the prompt to distinguish "read MORE /
adjacent pages" (encouraged) from "re-fetch the same result" (discouraged) more
sharply — left as a follow-up.

## Recommended fix (page-prefix), continued

**Recommended fix when we do rebuild:** stop embedding the page/title in text;
carry `page` (chunk index), `title`, and **`total_pages`** (chunk count for the
parent doc) as **structured fields** on the search hit and the `/doc/{id}`
response, and let the viewer/agent render them separately. The id already
encodes the page (`_p<N>`), so `page` is derivable without touching text at all;
`total_pages` is the new bit the id does NOT carry and is needed so the agent
(and viewer) know a document's boundary when navigating adjacent pages
(e.g. don't request `_p9` when the doc has 5 pages). See the page-navigation
work (get-documents-by-id tool + prompt guidance) that relies on this boundary.
