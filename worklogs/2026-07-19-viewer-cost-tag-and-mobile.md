# 2026-07-19 — Outputs Viewer: cost tag + mobile responsiveness; deep-research baseline survey

Three goals raised this session. Two shipped (viewer: cost chip, mobile). The
third (benchmark vs. an official deep-research assistant) is scoped below as a
plan, not yet built.

## Goal 2 — "cost" status chip

The viewer (`tasks/outputs_viewer/`, Next.js 15 + React 19 + MUI 7) shows a row
of status chips per run. Added a `cost: $X` chip alongside `processed: … tok`.

- New `src/lib/pricing.ts`: `MODEL_PRICING` (USD per 1M tokens, per model),
  `resolveModelPrice` (case- and `provider/`-prefix-tolerant), `computeCost`
  (cache-aware), `fmtUsd`.
- Wired into `SessionView.tsx`: `computeCost(meta.model, trace.summary.tokens)`,
  rendered as a green outlined chip with a tooltip breaking down
  full-price-input + cached-input + output, only when the model has a price.

### Token accounting (from a real artifact)

`data/outputs/aus_agent/20260718T215910729263+1000.write_a_series_of_blog.output.json`,
`trace.summary.tokens`:

```
input 309225, input_uncached 204777, output 8305,
cache_read 104448, cache_write 0, total 317530
```

`step.stats.cost_usd` is NOT populated by the harness (checked: 0 of N steps),
so the pre-existing per-step cost chip in `DetailPane.tsx` never rendered — cost
must be computed here from token totals × price. Cost formula (cache-aware):

```
cost = input_uncached/1e6 * input_rate
     + cache_read/1e6    * cacheRead_rate
     + cache_write/1e6   * input_rate
     + output/1e6        * output_rate
```

### Prices (per 1M tokens) — verified against provider docs 2026-07-19

Confirmed against OpenAI's official pricing page
(`developers.openai.com/api/docs/pricing`):

| model         | input | cached input | output |
|---------------|-------|--------------|--------|
| gpt-5.6-sol   | 5.00  | 0.50         | 30.00  |
| gpt-5.6-terra | 2.50  | 0.25         | 15.00  |
| gpt-5.6-luna  | 1.00  | 0.10         | 6.00   |
| gpt-5.5       | 5.00  | 0.50         | 30.00  |
| gpt-5.4       | 2.50  | 0.25         | 15.00  |

Worked example — the aus_agent run above (`gpt-5.6-luna`):

```
204777/1e6*1.00 + 104448/1e6*0.10 + 0 + 8305/1e6*6.00
= 0.204777 + 0.0104448 + 0 + 0.04983
= $0.2650  ->  chip shows "cost: $0.265"
```

### Azure note

Backend is Azure, not OpenAI-direct. Azure OpenAI **Global Standard**
deployments are priced identically to OpenAI list prices, so the table above is
correct as-is for a Global Standard backend. Azure **Regional / Data Zone**
Standard carry a premium, and **PTU** is hourly (not per-token) — for those,
override `MODEL_PRICING`. Documented in the `pricing.ts` header comment. (Azure's
own pricing page is a heavy SPA that timed out on fetch; the Global-Standard =
OpenAI-list parity is the well-established billing behaviour, worth a manual
reconfirm if a paper cites exact Azure figures.)

## Goal 3 — mobile responsiveness

App is all MUI `sx` (no CSS files, no `@media`). Fixes:

- `AppShell.tsx`: header was a single non-wrapping `Toolbar`. Added a `MobileNav`
  hamburger `Menu` shown on `xs` (`display: { xs: "flex", md: "none" }`); the
  inline nav buttons now `display: { xs: "none", md: "flex" }`. Title font-size
  responsive (`{ xs: "1rem", md: "1.25rem" }`) with ellipsis; explore icon hidden
  on `xs`; a flex spacer keeps UserBadge/ThemeToggle right-aligned on mobile.
- `Timeline.tsx`: the Gantt track has a hard `minWidth: 360`; wrapped it in an
  `overflowX: "auto"` box so it scrolls within its card instead of forcing the
  whole page to scroll sideways on phones < 360px.
- `SessionView.tsx`: the breadcrumb session-id (long monospace, e.g.
  `…+1000.write_a_series_of_blog`) got `wordBreak: "break-all"` so it wraps at
  the screen edge.
- `systems/page.tsx` (found on a follow-up mobile check — the whole `/systems`
  page scrolled sideways): the sessions-panel header was a non-wrapping
  `direction="row"` Stack holding an unshrinkable overline (`flexShrink: 0`), a
  fixed `minWidth: 200` "Run" select, and the "New search" button — their sum
  exceeded a phone width and forced the page wider than the viewport. Changed to
  `direction={{ xs: "column", sm: "row" }}` + `flexWrap: "wrap"`, dropped the
  overline's `flexShrink: 0` (→ `minWidth: 0`), and made the Run select
  `width: { xs: "100%", sm: "auto" }` / `minWidth: { xs: 0, sm: 200 }`.

### Verification

`pnpm lint` clean, `tsc --noEmit` clean. Rendered under headless Chromium
(Playwright) at 390×844 and 360×800 with `localStorage.outputs_viewer_user`
seeded to clear the identity gate. Confirmed on 390px: header fits (hamburger +
title + badge + toggle, no overflow), breadcrumb wraps, tags wrap across rows,
`cost: $0.265` chip present, timeline contained within its card (scrolls
horizontally, page does not). For `/systems`, a programmatic check confirmed
`document.documentElement.scrollWidth === window.innerWidth` (0px horizontal
overflow) at both 390 and 360; header controls stack vertically, session titles
ellipsize. Screenshots: `worklogs/assets/2026-07-19-viewer-mobile-390.png`
(session detail), `worklogs/assets/2026-07-19-viewer-systems-390.png` (list).

## Goal 1 — benchmark vs. an official deep-research assistant (PLAN, not built)

Requirement: compare our system against the *latest* (mid-2026) official
deep-research assistant, corpus-grounded on ClimbMix (not open web).

Survey (web, 2026-07-19) — the two viable frontier baselines:

- **OpenAI Deep Research** — `o3-deep-research` via the Responses API. Supports
  remote **MCP servers** + vector-store file search; can run web-search-off.
  Caveat: dedicated DR models have a **Dec 11, 2026** shutdown → `gpt-5.5-pro`.
- **Google Gemini Deep Research** — `deep-research-max-preview-04-2026`
  (Gemini 3.1 Pro, Apr 2026) via the Interactions API. Native **MCP + File
  Search** with tool restriction — most turnkey bring-your-own-corpus path.

Both let you disable open-web search and inject a custom retriever — the load-
bearing requirement for a *fair* corpus-grounded comparison. Perplexity
`sonar-deep-research` and Grok DeepSearch are web-native and cannot be corpus-
grounded → unfair baselines, excluded.

Decision (user): target **OpenAI `o3-deep-research`** first, via a direct
OpenAI key (to be provided). Viewer changes commit straight to `main` (user
preference, supersedes branch-first for this).

### Built: ClimbMix MCP server (`src/mcp/`)

`src/mcp/climbmix_server.py` — FastMCP (official `mcp` SDK), stateless
streamable-HTTP, exposing exactly the two-tool connector contract OpenAI DR
requires:

- `search(query)` → `{"results": [{id, title, text, url}]}` — hybrid
  dense+sparse RRF (`utils.search.search`; DR can't pick engines per call, so
  the engine-free hybrid is the single best default; `MCP_SEARCH_ENGINE` env
  can force `semantic`/`keyword`). `id` = ClimbMix docid; snippet 500 chars
  (`MCP_SNIPPET_CHARS`); k=10 (`MCP_SEARCH_K`).
- `fetch(id)` → full doc text via `utils.fetch_doc.fetch_doc`, plus
  `metadata.corpus = climbmix-400b`. `url` points at the Pyserini REST doc
  endpoint so citations resolve; eval keys on `id` (docid).

Optional bearer guard: set `CLIMBMIX_MCP_TOKEN` → all requests need
`Authorization: Bearer …` (for when the server is tunnelled to a public URL so
OpenAI's servers can reach it). New root dep group `mcp` (`mcp>=1.10`,
`uvicorn>=0.30`); run `uv run --group mcp python src/mcp/climbmix_server.py`
(default `0.0.0.0:8720/mcp`).

`src/mcp/test_smoke.py` — boots the server as a subprocess (token ON) and
drives it with the official MCP client. Result 2026-07-19, real backends:

```
[ok] unauthenticated request rejected
[ok] tools/list -> ['fetch', 'search']
[ok] search('index fund investing strategies') -> 10 results;
     top: shard_05995_80420  «Why Index Funds Should Be the Cornerstone of Your Investment»
[ok] fetch('shard_05995_80420') -> 3464 chars, metadata={'corpus': 'climbmix-400b'}
SMOKE OK
```

### Runner + end-to-end probe (same day, continued)

User provided `OPENAI_DEEP_RESEARCH_API_KEY` (direct platform key; verified
access to `o3-deep-research`, `o4-mini-deep-research`, `gpt-5.6-luna`).
Restructure per user: no standalone `mcp` uv group — deps live in the
`o3-deep-research` system group; MCP code stays in `src/mcp/`.

Built `src/systems/o3_deep_research/run.py`: Responses-API runner (background
mode), MCP tool attached (`server_url` = tunnel, bearer header), **no web
search**, `reasoning.summary=auto`; maps Responses output items → ragrun
trajectory (mcp_call → tool_call with docids, reasoning summaries → reasoning
steps); `format_answer` reuse (formatter `gpt-5.6-luna`); `--resume
<response_id>`; `save_run` artifacts. Sanity: base_url pinned to
api.openai.com (repo `.env` has Azure `OPENAI_BASE_URL` the SDK would grab).

**Tunnel debugging (half a day of it):**

- `421 Misdirected Request` on every tunnelled POST, both cloudflared quick
  tunnels AND ngrok, while curl GETs passed → NOT the tunnels: the MCP python
  SDK's own **DNS-rebinding protection** rejects non-localhost `Host` headers
  (`transport_security.py:120`). Fix: `TransportSecuritySettings(
  enable_dns_rebinding_protection=False)` (bearer token still guards).
- RMIT network was ALSO blocking cloudflared (user switched to phone hotspot);
  explains ngrok heartbeat timeouts and DNS flakiness mid-debug.
- After both fixes: full MCP handshake + search + fetch over the public
  tunnel verified with the SDK client.

**OpenAI-side read-back bug (open):** with `o4-mini-deep-research` +
remote-MCP + background mode, the run itself works — our server logged
OpenAI's `CallToolRequest`s (23.102.141.x / 4.151.71.x, 31 POSTs) and the
agent did on-topic searches/fetches (probe query: benefits/risks of index
fund investing; `max_tool_calls=8`). But **reading the response back fails**:

- `responses.retrieve` → persistent 500 (req ids `req_c63457ef31a7424a…`,
  `req_5caeffb37c5049d2…`, `req_8e33eaa91bb44cab…`), across two separate
  response ids, while a plain non-DR background response retrieves fine.
- streaming (`background=True, stream=True`) delivered 16 items live
  (list_tools, 3 searches, 3 fetches, reasoning) then died at seq ~834 right
  after an `mcp_call_arguments.done`; stream-replay from ≤834 re-dies at the
  same spot (poisoned event, wf id `wfr_019f782a241a73cf…`); replay from
  ≥840 connects clean and idles (so skip-past-poison works as a fallback).

Runner hardening from this: `_retrieve` retry w/ backoff, stream reconnect
cap (12, exponential, visible error text), `--resume` for paid-run recovery.
Probe response `resp_028a37c30f2aa9e9006a5c33be9ae08190aa981c8ef27de7db`
still in_progress ~30 min in (final-generation phase or zombied — watcher
armed; will cancel if it never terminates).

**Root cause found (reproduced 3/3): `max_tool_calls` + MCP.** The
poll-500s / poisoned-stream failures all struck immediately after the run's
8th tool call — exactly the `max_tool_calls=8` probe cap. Sub-experiments:
sync stream + summaries died after call 8 (seq 714); sync stream without
`reasoning.summary` died after call 8 too (summaries exonerated); **uncapped**
sync stream ran 35 tool calls to completion. Conclusion: OpenAI's DR
orchestrator crashes when a remote-MCP run hits `max_tool_calls` instead of
gracefully forcing the answer. Run UNCAPPED, `--no-background` sync
streaming. ("Cannot cancel a failed response" on the first probe id confirmed
the runs had failed server-side while both read paths hid it.)

Validation probe (o4-mini, uncapped, sync): **completed** — 84 items,
5 search + 30 fetch, 27 cited sentences, 5 refs, no violations, 39.6K/14.4K
tok = **$0.19**. Artifacts:
`data/outputs/o3_deep_research/20260719T133002946828+1000.what_are_the_main_benefits.*`.

### The real run: o3-deep-research on investing + rubric eval

Run `o3-dr-investing` (`o3-deep-research`, uncapped, sync stream, summaries
on, ClimbMix MCP only): **completed, no violations** — 58 items, 8 search +
18 fetch, 47 sentences / 679 words, 7 refs, 42.6K in / 29.6K out =
**$1.61**, ~6.5 min.
`data/outputs/o3_deep_research/20260719T133726753816+1000.write_a_series_of_blog.*`.

Rubric eval, same protocol as the 2026-07-18 sat-go batch (strict
1.0/0.5/0.0 per criterion, answer text only, attainment =
Σ(w·s)/Σ(w⁺) with penalty semantics). Judgments:
`worklogs/assets/2026-07-19-rubric-eval-o3dr/683a58c9a7e7fe4e76958498.json`
(31/31 criteria). Σ(w·s)=28.5 (incl. −3.0 triggered jargon penalty),
Σ(w⁺)=84.0 → **33.9%**.

| investing topic (qid …98) | o3-deep-research | aus_agent (sat-go, luna) |
|---|---|---|
| rubric attainment | **33.9%** | **35.1%** |
| refs / sentences / words | 7 / 47 / 679 | 6 / 39 / 874 |
| tool calls | 26 (8 search, 18 fetch) | 4 (3 search, 1 commit) |
| latency | ~6.5 min | 21 s |
| cost (list price) | $1.61 | $0.06 |

**Headline: on its worst topic, our 21-second/$0.06 aus_agent statistically
ties the frontier DR agent (35.1 vs 33.9) at 1/27th the cost and ~1/18th
the wall-clock.** Single topic — not generalizable without the batch.

Why both bottom out — and the eval-fairness caveats:

- Both lose the same structural criteria: the rubric wants an actual blog
  series (i=0/i=1, w=4 each), comparison tables (i=4/i=18), named indices
  (i=24: S&P 500/Dow/Nasdaq), ETFs, brokers, tickers.
- **o3's RAW report was a genuine 3-post, 6,358-word blog series with
  headings** — our `format_answer` stage compressed it ~10× into the track's
  flat cited-sentence format, destroying the structural criteria. That's a
  pipeline artifact, not an o3 failure (aus_agent natively writes in track
  format, so it wasn't equivalently penalized).
- But the **named-specifics gaps are real**: grep of the raw 6,358-word
  report finds zero mentions of S&P/Nasdaq/ETF/Vanguard/Fidelity/tickers —
  o3 never surfaced them from ClimbMix. Those misses (~12+ weight) stand
  regardless of formatting.
- Judge caveat: different judge instance than the sat-go batch (same
  protocol/strictness, and the sat-go per-criterion file for this qid exists
  for spot-comparison).

Follow-ups worth considering: (a) preserve report structure through
`format_answer` (or judge raw reports for both systems as a secondary
number); (b) the full 30-topic o3 batch (~$48 at this rate) for a real
distribution; (c) file the max_tool_calls+MCP crash with OpenAI (request ids
in this log).
