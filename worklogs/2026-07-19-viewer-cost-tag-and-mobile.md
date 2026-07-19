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

Planned build: wrap our existing ClimbMix `search` + `get_document`
(`tools.search_tool.run_search_tool`, `utils.fetch_doc.fetch_doc`) as an MCP
server exposing the `search`/`fetch` interface the DR agent expects, point the
DR agent at it with web off, run the dev topics, and rubric-eval alongside
aus_agent. Blocked on: (a) confirming exact model IDs against provider docs
(several mid-2026 specifics came from secondary aggregators), (b) API
credentials, (c) which of OpenAI-DR / Gemini-DR to target first.
