# 2026-07-19 — GPT reasoning summaries + viewer markdown reasoning + full-docid prompt rule

Follow-on session (branched from the viewer/DR session earlier today).

## 1. aus_agent openai backend: request reasoning summaries

User noticed generation steps showed `"reasoning": []` for gpt-5.6 runs.
Diagnosis: GPT reasoning models never return raw chain-of-thought; the
Responses API returns (a) encrypted reasoning blobs for multi-turn replay —
which we already requested via `include=["reasoning.encrypted_content"]` — and
(b) human-readable summaries, but **only when requested** with
`reasoning={"summary": "auto"}`. We never passed that, so every reasoning item
arrived with an empty `summary` list even though the provider
(`src/systems/aus_agent/providers/openai.py`) was already wired to read
`item.summary`.

Fix: one line in `openai.py` — add `reasoning={"summary": "auto"}` to
`responses.create`.

Verification (raw inputs, exact):

- Standalone probe, Q = `In one sentence, which is larger: 17^3 or 3^17?
  Think briefly.` against **both** Azure (`.env` OPENAI_BASE_URL) and direct
  OpenAI (`api.openai.com`), models `gpt-5.6-luna`, summary `auto` and
  `detailed`: all four returned non-empty summaries (e.g. `**Comparing
  exponential values** I need to provide a concise answer…`).
- Same through the real `OpenAIProvider.run_turn()` with a tool attached:
  `reasoning_blocks: ['**Calculating powers** …']`.
- Full agent probes, Q = `What is an index fund?`, `--backend openai`,
  run-ids `reasoning-summary-probe` (×2):
  - run 1 (12:15): generations `[0,0,0]` summaries — all empty;
  - run 2 (12:17): `[0,1,0]` — turn 2 carried `**Deciding on document
    action** I need to choose the right document…`.
  Conclusion: with `auto` the model emits summaries only for turns where it
  actually deliberated; trivial tool-dispatch turns yield none. Not a bug.
  Artifacts: `data/outputs/aus_agent/20260719T121519327470+1000.*` and
  `20260719T121751242239+1000.*`.

## 2. Viewer: GENERATION REASONING section, markdown-rendered

Summaries are markdown (`**bold**` headings etc.) and were only visible inside
the raw JSON blob of "Generation output". Added:

- `tasks/outputs_viewer/src/components/session/Markdown.tsx` — compact
  renderer, new deps `react-markdown` + `remark-gfm` (MUI-styled headings,
  lists, inline/pre code, tables, blockquotes; `wordBreak: break-word`).
- `DetailPane.tsx` — generation steps with non-empty `output.reasoning[]` get
  a **Generation reasoning** section between "Generation input" and
  "Generation output" (one markdown block per summary); standalone
  `reasoning`-type steps (ali_deepresearch / o3-DR traces) also render
  markdown instead of plain text. Raw JSON output untouched.

Verified in headless Chromium and user's own browser on session
`20260719T121751242239+1000.what_is_an_index_fund?step=3`: bold "Deciding on
document action" heading + prose paragraph render correctly. (Same screenshot
also confirmed the cost chip on a terra run: `cost: $0.036`.)

## 3. aus_agent prompt: full-docid rule

The rendered reasoning exposed the model referring to documents as
`document 01851` / `056` — bare **shard numbers**, not docids
(`shard_01851_76734`). Shard-number shorthand is shared across unrelated
documents and is one step from a wrong/invalid citation. Added a bullet to
`src/systems/aus_agent/prompts/system.md` (commit_context rules, after "Never
recommit an already committed docid"):

> Refer to every document by its full docid exactly as returned (e.g.
> `shard_01851_76734`) — in selection reasons, working notes, and citations
> alike. Never abbreviate to a fragment such as `01851`: that is only the
> shard number, shared by many unrelated documents, and shorthand ids lead to
> wrong or invalid citations.

Plus a second bullet (user request): `_p<n>` marks a page — `
shard_01851_76734_p2` is page 2 of `shard_01851_76734`; keep the suffix when
it is part of the returned id so recalls stay page-precise.

Probe `docid-style-probe` (12:27, artifact
`20260719T122725154903+1000.*`): emitted no reasoning summaries (auto skips
on trivial queries) so the prose style couldn't be observed; commit arguments
used full docids (they always did — the shorthand only ever appeared in
reasoning prose). Effect to be observed on the next real research run.

## 4. Page-precise references in the trace + full-doc viewer tab

Organizers require final-output citations at **doc level** (no `_p<n>`); for
review precision the trace should still record which page actually supported
each reference.

Backend (aus_agent):

- `context.py` `ContextLedger.committed_full_ids: dict[docid, full unit id]`,
  populated in `commit()` from each committed document's `id` (the staged
  documents have carried both `id` and `docid` all along — `SearchHit` splits
  them; the full id was simply dropped before the trace).
- `agent.py`: `trace.output` now carries `references_full` (parallel to
  `references`, same indexing) = `committed_full_ids[docid]` per reference.
  Strict `output.json.references` unchanged (doc-level, organizer format).
- Note: probed the hosted dense API directly — it currently returns plain
  doc-level ids (`id == docid`), so today `references_full == references`;
  when the chunked index (`_p<n>` ids) goes live the full ids flow through
  automatically (`make_hit` passes server ids through untouched).
- 45/45 `test_context.py` tests pass. Probe `refs-full-probe` (12:39,
  artifact `20260719T123909740724+1000.*`): `trace.output.references_full`
  present; strict references unchanged.

Viewer:

- `AnswerView` accepts `fullRefs` (from `trace.output.references_full`);
  citation chips + reference list open/highlight the page-precise id.
- `DocSidebar`: two tabs — **Retrieved** and **Full document** (lazy-fetched
  on tab open; header keeps the full id).
- **Source-faithful fetching** (user correction): a doc must be viewed from
  the engine that retrieved it — keyword hits from the sparse side, semantic
  hits from the dense endpoint — because the next dense index will be
  page-only (no doc-level entries at all). `SessionView` derives a
  docid→engine map from the trace (search-step `arguments.search_engine ==
  "keyword"` → sparse; both `returned_docids` and per-result full `id`s are
  mapped) and passes it to the sidebar → `/api/doc/[id]?source=sparse|dense` →
  `fetchDoc(id, prefer)` source order `sparse → pyserini → dense` (sparse
  hits never silently served from dense) vs default `dense → pyserini`.
- **Full document** = doc-level indexes only: `fetchFullDoc` tries the sparse
  BM25 server's doc-by-id, then the Pyserini REST API; never dense.
- **Infra gap found by probing** (2026-07-19): the BM25 dsync server
  (Spring proxy, `POST /api/search` only) has **no doc-by-id route** — every
  `/doc` variant 404s, and the search proxy can't query by id
  (`docid:`/`_id:` queries return 0 hits). Until the proxy ships one, sparse
  fetches fall through to the Pyserini REST API. The viewer defaults the
  future route to `https://index-climbmix-bm25.dsync.net/api/doc/{docid}`,
  overridable via `SPARSE_DOC_URL` (repo `.env`), and parses
  `{text}|{doc}|{contents}|ES {_source:{contents}}` shapes tolerantly.
- Verified: keyword-retrieved `shard_00828_67124` (session
  `20260719T123909740724+1000`) now shows `source: pyserini` (sparse-side
  fallback) instead of the previous wrong `source: dense endpoint`.
- `DetailPane` + `DocSidebar` tab bars: `variant="scrollable"
  scrollButtons="auto" allowScrollButtonsMobile` — the Final-answer tab row no
  longer clips ("Fee…") on narrow widths.

Verified in headless Chromium: Full-document tab renders the pyserini article
with `source: pyserini` chip on session `20260719T121751242239+1000`.

Late corrections (user):

- The sidebar source chip renders `source: ${data.source}` verbatim — no
  display-side mapping of backend names.
- The sparse server DOES have a doc-by-id route the earlier probe missed:
  **`GET /api/search/doc/{docId}`** (plus `GET /api/search/health`,
  `/api/search/stats`, and GET-style `/api/search?q=`). Verified 200 with an
  ES-style hit body (`_source.contents`, full doc text). Viewer default
  `SPARSE_DOC_URL` updated to `…/api/search/doc` — sparse-routed Retrieved
  fetches and the Full-document tab now hit our BM25 server first, Pyserini
  REST only as fallback.

## 5. Experiment: Pyserini REST API vs our BM25 server — alignment

Question: do `api.castorini.uwaterloo.ca/v1/climbmix-400b/search` (official)
and `index-climbmix-bm25.dsync.net/api/search` (ours) return the same
results?

Method: 10 queries, top-10 from each, compared on overlap@5/@10, Jaccard@10,
top-1 agreement, mean rank displacement over shared docids, and per-rank
score deltas. Probe script: `worklogs/assets/2026-07-19-bm25-align-probe.py`;
raw hit lists + matrix: `worklogs/assets/2026-07-19-bm25-align-results.json`.

Exact queries (k=10 each):

1. `index fund definition tracks market index`
2. `Albert Einstein`
3. `how to change default program macos`
4. `Markov chain stationary distribution`
5. `photosynthesis light reactions`
6. `history of the silk road trade`
7. `python garbage collection reference counting`
8. `climate change sea level rise projections`
9. `homebrew python 3 default`
10. `combinatorics pigeonhole principle example`

Result matrix (identical for every query):

| metric | value (all 10 queries) |
|---|---|
| overlap@10 | 10/10 |
| overlap@5 | 5/5 |
| Jaccard@10 | 1.000 |
| top-1 agreement | 10/10 |
| mean rank displacement | 0.00 |
| max per-rank score delta | ≤ 5.0e-5 |

Top-1 scores agree to 4 decimals on every query (e.g. `index fund definition
tracks market index`: 19.6753 vs 19.6753; `combinatorics pigeonhole principle
example`: 21.8925 vs 21.8925). Score deltas are float32/float64 serialization
noise.

Conclusion: **the two backends are the same BM25 ranking in practice** — same
docid sets, same order, same scores to ~1e-5. Our server is a faithful stand-
in for the official Pyserini REST API on climbmix-400b (and vice versa for
fallback purposes in the viewer).

Latency (same 10 queries × 3 reps, warm connections, k=10, measured from the
dev laptop on a phone-hotspot network — absolute values include that hop;
castorini is plain HTTP from Waterloo, ours TLS via dsync):

| | pyserini (castorini) | ours (dsync) |
|---|---|---|
| median | 285 ms | 179 ms |
| mean | 348 ms | 210 ms |
| min | 271 ms | 112 ms |
| p90 | 776 ms | 496 ms |
| max | 921 ms | 499 ms |

Per-query cost is content-driven on both backends (`climate change sea level
rise projections` ≈ 500–800 ms everywhere; `Albert Einstein` ≈ 115 ms on
ours). Ours ≈ 1.6× faster overall with tighter tails → better default for our
pipelines; castorini stays the compatibility fallback.

### Follow-up: 12 new, unseen queries (cache-skeptical re-test)

The first set had been queried 4× (alignment + 3 latency reps), so results
and latency could have been cache-flattered. Re-ran with 12 never-before-sent
queries (rare entities, deliberate typos, long natural-language, numeric,
niche topics), measuring alignment plus cold (first-ever call) vs warm
(immediate repeat) latency. Raw:
`worklogs/assets/2026-07-19-bm25-align-unseen-results.json`.

Exact queries:

1. `Stefan cel Mare battle of Vaslui 1475`
2. `pyhton dictionar comprehension exmaple` (deliberate typos)
3. `why does bread dough rise faster in a warm kitchen than in a cold one`
4. `convert 3.7 kilopascals to mmHg formula`
5. `segfault dereferencing null pointer strcpy`
6. `comparison between vim and emacs keybindings learning curve`
7. `restoring cast iron skillet electrolysis tank setup`
8. `smallest landlocked country in Africa by area`
9. `contango backwardation crude oil futures storage costs`
10. `medieval manuscript marginalia snail knight combat`
11. `duckworth lewis method rain interrupted cricket calculation`
12. `tritone substitution dominant seventh jazz voicing`

Alignment: mean overlap@10 **9.92**, overlap@5 **5.00**, top-1 **12/12**,
mean rank displacement 0.02, max score delta 4.8e-5. The single non-perfect
query (`Stefan cel Mare…`) agrees exactly on ranks 1–9; rank 10 differs
because two different docs score 25.92820 vs 25.92823 (Δ=3e-5) — a float-
precision tie at the k=10 boundary, not a ranking difference.

Latency (median / mean / max ms):

| | cold | warm |
|---|---|---|
| pyserini | 541 / 698 / 1886 | 307 / 384 / 625 |
| ours | 176 / 229 / 678 | 132 / 182 / 559 |

Cold-vs-warm confirms pyserini benefits heavily from result caching (1886 ms
cold → 521 ms repeat on the long NL query); ours is ~3× faster cold and ~2.3×
faster warm. Same caveat: phone-hotspot network, HTTP (castorini) vs TLS
(ours).

### Follow-up: concurrency sweep (C = 1 / 4 / 8 / 16)

64 unique never-sent queries (8 topics × 8 angles, e.g. `kalman filter state
estimation common failure modes`), 16 requests per concurrency level, one
ThreadPoolExecutor per level, per-thread HTTP sessions, backends swept one
after the other (not simultaneously); each backend saw every query cold (the
query list was reversed between backends). Raw:
`worklogs/assets/2026-07-19-bm25-concurrency-results.json`.

| C | ours req/s | ours med/p90/max ms | pyserini req/s | pyserini med/p90/max ms |
|---|---|---|---|---|
| 1 | 5.3 | 171 / 206 / 331 | 1.1 | 896 / 1418 / 1465 |
| 4 | 13.2 | 233 / 386 / 439 | 3.7 | 870 / 1284 / 1454 |
| 8 | **16.6** | 425 / 691 / 850 | 5.8 | 1199 / 1613 / 1769 |
| 16 | 10.1 | 1343 / 1506 / 1564 | **6.9** | 1543 / 1794 / 2305 |

Zero errors anywhere. Readings:

- **Ours peaks ≈ 16.6 req/s at C=8**, then C=16 *regresses* (10.1 req/s,
  median 1.3 s) — clear queueing/saturation; treat **C≈8 as the sweet spot**
  for batched retrieval against our server.
- **Pyserini scales slowly but monotonically** (1.1 → 6.9 req/s at C=16) with
  uniformly high latency; peak throughput ≈ 2.4× lower than ours.
- Caveats: only 16 requests per level (single wave at C=16), phone-hotspot
  network adds shared-uplink variance, all-cold queries. Directionally solid,
  not load-test-grade — `tasks/loadtest` has the k6 rig for that.
