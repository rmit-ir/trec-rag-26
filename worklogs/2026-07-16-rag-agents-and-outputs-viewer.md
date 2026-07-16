# 2026-07-16 — RAG agent systems + outputs viewer dashboard

Built the first four RAG agent systems for TREC RAG 2026 (all retrieving
exclusively from the ClimbMix corpus via our own search utils), a shared
run-output layer, and a Next.js dashboard to preview and judge run outputs.

## Shared run-output core — `src/ragrun/`

Every agent run produces exactly two JSON artifacts, written by `ragrun.save_run`
to `data/outputs/<system-name>/<ISO8601>.<query-first-5-words>.{trajectory,output}.json`:

- `*.trajectory.json` — full agent trace (`reasoning` / `tool_call` /
  `output_text` items, `tool_call_counts`, sorted `retrieved_docids`,
  `raw_messages`), format modeled on
  `data/sample-files/run_InfoSeekQA_1000_*.json` (itself a Tongyi-DeepResearch
  run).
- `*.output.json` — one TREC RAG 2026 output object (`metadata` / `references`
  / sentence-level `answer` with citation indices), validated against the
  track rules (≤1024 words, ≤3 citations/sentence, every reference cited);
  violations are written alongside as `*.output.violations.json` rather than
  failing the run.

Also added `src/utils/fetch_doc.py` (`get_document` by docid via the Pyserini
hosted API) to complement the existing hybrid `utils.search`.

## Bedrock access (probed + saved to memory)

- The shell's default AWS profile has no Bedrock permissions; the working creds
  are in the repo-root `.env` (RMIT SSO role, account 507363615341), region
  `ap-southeast-2`.
- Only `au.*` inference profiles are invokable — `global.*`/`us.*` are
  AccessDenied. Verified live: `au.anthropic.claude-sonnet-5` (project
  default), `au.anthropic.claude-opus-4-8`, `opus-4-7`, `opus-4-6-v1`,
  `sonnet-4-6`, `haiku-4-5`.
- Sonnet 5 on Bedrock only accepts `thinking.type=adaptive` and returns
  signature-only `reasoningContent` (no text) — providers must also record the
  model's between-tool-call narration as trajectory reasoning.

## Agent systems (hard rule: corpus-only retrieval, citations are ClimbMix docids)

1. **`src/systems/aus_agent/`** — research harness with pluggable LLM
   backends: minimal per-provider contract (each provider owns its native
   message history; the harness only sees normalized events), Bedrock Converse
   backend today, Azure OpenAI / OpenAI Responses to slot in later. Dep group
   `aus-agent`. Live-verified on a dev topic: 21 searches + 10 fetches,
   207 docids, output validation clean.
2. **`src/systems/ali_deepresearch/`** — faithful port of Alibaba-NLP
   Tongyi DeepResearch's ReAct loop (`<think>/<tool_call>/<tool_response>/<answer>`
   protocol, sampling 0.85/0.95/1.1) with its web tools replaced by our
   corpus `search`/`get_document`. OpenAI-compatible endpoint via
   `ALI_DR_BASE_URL/API_KEY/MODEL` (vLLM/OpenRouter later; no endpoint yet).
   Dep group `ali-deepresearch`. Verified end-to-end against a scripted mock
   driving the real search plumbing (12/12 checks).
3. **`tasks/pi-agent/`** (pnpm/TS) — pi framework agent. `@mariozechner/pi-ai`
   has first-class Bedrock (`amazon-bedrock` ConverseStream) — beware the stale
   `@mariozechner/pi-agent` npm package; the maintained runtime is
   `pi-agent-core` (0.73.x lockstep). `src/search.ts`/`trajectory.ts`/`outputs.ts`
   are exact TS ports of the Python counterparts. Live-verified (Markov-chains
   topic, 988-word 31-sentence answer, artifacts re-validated with the Python
   validator).
4. **`src/systems/claude-code-research/`** — reworked from web research to
   corpus-only: web tools forbidden in AGENTS.md; research goes through
   `scripts/corpus.py` (search/fetch with faithful per-call JSONL logging into
   the task folder) and `scripts/save_run.py` assembles the two artifacts from
   the tool log + an answer-sentences JSON.
   ⚠ Incident: the worker force-deleted `data/claude-code-research/` during
   test cleanup; almost certainly only its own test files (the dir convention
   was new that day) but unprovable since `data/` was gitignored at the time.

## Outputs viewer dashboard — `tasks/outputs_viewer/`

Next.js 15 (App Router) + TS + pnpm, MUI 7 + DataGrid + Charts + SWR.
Dev server: `pnpm dev` → http://localhost:3618.

- Username gate (normalized: lowercase, strip non-alphanumerics; localStorage).
- Session view (PostHog-trace style, single unified view): stat chips + an
  always-visible sequence timeline on top (markers select steps); below, a
  master-detail layout — filterable step tree on the left (trajectory steps +
  a distinct Answer node, selected by default) and a tabbed detail pane
  (Answer / Sentences / Raw / Feedback for the answer; Details / Raw for
  steps). Citation/docid chips open a doc sidebar as a third column; the doc
  route tries the dense endpoint's `GET /doc/{docid}` (docid-keyed only —
  chunk ids fall back to the parent doc, flagged in the UI), then Pyserini.
  URL state: `?step=&dtab=&doc=` (legacy `?tab=` migrated).
- Feedback: 👍/👎 + comment + tags on answer / paragraph / citation;
  tag autocomplete backed by `data/output_feedbacks/tags.json` (new tags
  auto-added); append-only JSONL per system+session under
  `data/output_feedbacks/`, edit = supersede (latest wins).
- Pages: my/all feedback (linking back to sessions), summary charts,
  leaderboard (per-system rating aggregates + dynamic per-tag columns) with a
  custom ColumnPicker (checkbox visibility + native-drag reorder with live
  preview — pattern adapted from cn-consoles; no DataGrid Pro).
- All view state persisted to URL; outputs index re-stats per request so new
  artifact files appear on refresh without restart.

## Timings, parallel tool execution, and the time-axis timeline (evening)

- Trajectory contract extended (additive, old artifacts stay valid): per-item
  `t_start`/`t_end`/`turn` (same turn + overlapping times = ran in parallel)
  and run-level `started_at`/`ended_at`.
- All timestamps are **Melbourne local** (`Australia/Melbourne`, tz-database
  offset — `+10:00`/`+11:00` auto): timing fields like
  `2026-07-16T18:30:44.415+10:00`, artifact filenames like
  `20260716T183318467530+1000.<slug>...` (the `+` needs `%2B` in URLs; the
  dashboard encodes/decodes throughout). Pre-existing `…Z` artifacts kept.
- **aus_agent** now executes same-turn tool calls in parallel
  (ThreadPoolExecutor, model order preserved) — live run showed 11 turns with
  genuinely overlapping calls. **pi-agent**: pi-agent-core supports parallel
  natively; our config was forcing sequential in two places (agent
  `toolExecution` + per-tool `executionMode`) — flipped to parallel, live run
  confirmed 4 overlapping turns. ali_deepresearch (strictly sequential loop)
  and ccr scripts record real per-call bounds.
- Dashboard timeline is now a PostHog-style Gantt when timings exist: time
  axis with nice ticks + total duration, turn-span row, steps positioned by
  wall-clock and stacked into parallel lanes on overlap (greedy lane packing
  per turn); per-step duration chips in tree + detail header; sessions
  without timings keep the sequence-marker strip.

## Repo housekeeping

- Output location fixed to `data/outputs/<system>/` (was `data/<system>/`);
  all writers, docs, and existing artifacts migrated.
- `.gitignore`: `data/outputs/` and `data/output_feedbacks/` are now
  deliberately tracked (exceptions under `data/*`).
- AGENTS.md: documented the one-off-script pattern
  `uv run --no-project --with <pkgs> python - <<'EOF' … EOF`.
- Root pyproject: added `ragrun` package and per-system dependency groups
  (`aus-agent`, `ali-deepresearch`) — default `uv sync` installs none of them.

## Follow-ups

- Point `ali_deepresearch` at a real endpoint (vLLM or hosted) and live-test.
- Add Azure OpenAI / OpenAI Responses providers to `aus_agent`.
- Batch-run dev topics across systems and compare in the dashboard.
- Consider committing `data/outputs/` + feedback data (now un-ignored).
