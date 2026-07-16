# pi-agent — TREC RAG 2026 research agent on the pi framework

A TypeScript RAG agent built on Mario Zechner's **pi** framework
([pi-mono](https://github.com/badlogic/pi-mono)), backed by **AWS Bedrock**
Claude models, that answers TREC RAG 2026 research topics using **only the
ClimbMix corpus** via our hosted search services (no web access). Every
citation is a ClimbMix docid (e.g. `shard_00459_61697`).

## Setup

Requires Node 20+ and pnpm. Credentials come from the **repo-root `.env`**
(`SEARCH_API_KEY`, `PYSERINI_API_TOKEN`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`; optional `DENSE_SEARCH_URL`,
`SPARSE_SEARCH_URL`, `PYSERINI_DOC_URL`/`PYSERINI_SEARCH_URL`).

```bash
cd tasks/pi-agent
pnpm install
```

## Run

```bash
# one dev topic by qid (default topics TSV: research-rubrics-topics-dev.tsv)
pnpm agent -- --qid 6847465956a0f6376a605493

# ad-hoc query
pnpm agent -- --query "Write an introduction on Markov chains ..."

# all topics in a TSV
pnpm agent -- --all --topics path/to/topics.tsv

# knobs
pnpm agent -- --qid <id> --model au.anthropic.claude-sonnet-5 --k 10 --max-rounds 12 --thinking low

# validate an output file against the track citation rules
pnpm exec tsx src/validate.ts ../../data/outputs/pi-agent/<ts>.<slug>.output.json

# typecheck
pnpm typecheck
```

Verified Bedrock model ids: `au.anthropic.claude-sonnet-5` (default),
`au.anthropic.claude-opus-4-8`, `au.anthropic.claude-haiku-4-5-20251001-v1:0`,
`au.anthropic.claude-sonnet-4-6`. (`global.*`/`us.*` are AccessDenied on our
credentials — don't use.)

## Outputs

Every run writes both artifacts to repo-root **`data/outputs/pi-agent/`** (never
under `tasks/`), mirroring the Python `ragrun` package exactly:

- `<ts>.<slug>.trajectory.json` — metadata (model, k, max_rounds,
  query_source, ...), `query_id`, `tool_call_counts` /
  `tool_call_counts_all`, `status` (`completed|failed|budget_exhausted`),
  `retrieved_docids` (sorted union over all tool calls), `result`
  (interleaved `reasoning` / `tool_call` / `output_text` items — shaped like
  `data/sample-files/run_InfoSeekQA_1000_*.json`), run-level `started_at` /
  `ended_at`, `raw_messages` (pi-native message history incl. the finalize
  turn). Each result item additionally carries optional wall-clock timing:
  `t_start` / `t_end` (Melbourne-local ISO 8601 with ms + offset, e.g.
  `2026-07-16T18:21:34.342+10:00`) and `turn` (0-based model-turn index).
  Items sharing a `turn` with overlapping `[t_start, t_end]` ran in
  PARALLEL (dashboards render them as parallel lanes); reasoning items span
  the whole model turn, tool calls span their own execution, and the
  `output_text` item spans the final strict-JSON turn. Old artifacts
  without these fields stay valid.
- `<ts>.<slug>.output.json` — the track's RAG output object:
  `{metadata: {team_id, narrative_id, narrative, run_id, run_desc},
  references, answer: [{text, citations}]}` — ≤1024 words, ≤3 citations per
  sentence, every reference cited, no extra metadata keys. Violations (if
  any) are written alongside as `*.output.violations.json`.

`<ts>` is a compact Melbourne-local stamp with UTC offset
(`20260716T163259123000+1000`, `+1100` during AEDT — mirror of Python
`ragrun.outputs.run_timestamp`); `<slug>` is the first 5 words of the query
(`write_a_blog_post_contrasting`). Artifacts from before the timezone switch
keep their old `...Z` names.

## Architecture

```
src/config.ts      dotenv from repo root; URLs, defaults, output dir
src/search.ts      TS port of src/utils/{search,search_dense,search_sparse,fetch_doc,search_types}.py
                   — HTTP Basic auth from SEARCH_API_KEY, custom User-Agent
                   (both endpoints 403 stock UAs), RRF fusion:
                   score += weight * 1/(60 + rank), per-backend depth max(k, 50)
src/tools.ts       pi AgentTool definitions: `search` (hybrid + RRF) and
                   `get_document` (Pyserini full-text; chunk ids <docid>_p<n>
                   are stripped to the parent docid)
src/model.ts       Bedrock model resolution (registry lookup or custom Model spec)
src/agent.ts       system prompt + agentic tool loop (pi-agent-core
                   runAgentLoop, --max-rounds default 12) + final strict-JSON
                   citation turn + docid→reference-index mapping
src/time.ts        Melbourne-local timestamp helpers (nowIso, runTimestamp) —
                   offset derived from the tz database via Intl.DateTimeFormat
                   (never hardcoded; +10:00 AEST / +11:00 AEDT)
src/trajectory.ts  TS port of src/ragrun/trajectory.py (TrajectoryBuilder,
                   incl. per-item t_start/t_end/turn + run started_at/ended_at)
src/outputs.ts     TS port of src/ragrun/outputs.py (timestamp/slug/build/
                   validate/save)
src/cli.ts         --query | --qid [--topics] | --all; --model --k
                   --max-rounds --thinking
src/validate.ts    standalone rag-task.md rule checker
```

Flow per topic: the model iterates `search` (varied phrasings) and
`get_document` (read promising docs in full) inside the pi agent loop; when
it stops calling tools it writes a prose report; a final strict-JSON turn
re-emits the report as one-sentence items citing docids; docids never
retrieved during the run are dropped, chunk ids map to parents, citations cap
at 3 per sentence, whole sentences are trimmed from the end to stay ≤1024
words, and `references` keeps only cited docids (first-citation order).

## Design notes: pi framework + Bedrock findings

- **Package layout (June 2026):** the pi-mono npm packages under
  `@mariozechner/` are versioned in lockstep. `@mariozechner/pi-ai` (0.73.1)
  is the unified LLM API (providers, streaming, tools-as-TypeBox-schemas,
  usage/cost tracking). `@mariozechner/pi-agent-core` (0.73.1) is the agent
  runtime (`Agent` class + low-level `agentLoop`/`runAgentLoop`, AgentTool
  with `execute()`, lifecycle events, `shouldStopAfterTurn`). Beware:
  `@mariozechner/pi-agent` on npm is a **stale 0.9.0** package pinned to
  pi-ai ^0.9.0 — the maintained one is `pi-agent-core`. `@mariozechner/pi`
  is the full coding-agent CLI (not needed here).
- **Bedrock support: YES, first-class.** pi-ai ships an `amazon-bedrock`
  provider (api `bedrock-converse-stream`) implemented on
  `@aws-sdk/client-bedrock-runtime` (ConverseStream) with the standard AWS
  credential chain — our root-`.env` `AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN`
  + `AWS_REGION=ap-southeast-2` just work; no `@anthropic-ai/bedrock-sdk`
  needed. When `AWS_REGION` is set the provider resolves the endpoint from it
  (the catalog `baseUrl` is ignored).
- **Custom model ids:** pi-ai's model catalog covers many `au.anthropic.*`
  ids but not `au.anthropic.claude-sonnet-5` / `claude-opus-4-8`.
  `src/model.ts` falls back to a custom `Model<"bedrock-converse-stream">`
  spec, which pi-ai supports natively.
- **Adaptive-thinking gotcha:** Claude ≥4.6 models (Sonnet 5, Opus 4.8)
  reject `thinking.type: "enabled"` (budget tokens) and require
  `thinking.type: "adaptive"` + `output_config.effort`. pi-ai 0.73.1 builds
  the adaptive payload but gates it behind a substring match on the model
  id/name (`opus-4-6|opus-4-7|sonnet-4-6`), which predates Sonnet 5. The
  custom-model fallback therefore embeds a `sonnet-4-6` marker in the
  (display-only) model `name` to route such ids onto the adaptive path.
  Remove once upstream pi-ai learns the new ids.
- **Parallel tool execution: YES.** pi-agent-core executes all tool calls
  from one assistant message concurrently (`Promise.all` in
  `executeToolCallsParallel`) unless `AgentLoopConfig.toolExecution` is
  `"sequential"` or any tool in the batch declares
  `executionMode: "sequential"` (one sequential tool forces the whole batch
  sequential). The loop preflights calls in order (validation +
  `tool_execution_start`), then runs `execute()` for all calls concurrently;
  `tool_execution_end` fires in completion order. Both our tools are
  stateless HTTP calls, so they declare `executionMode: "parallel"` and the
  config sets `toolExecution: "parallel"` — when the model emits several
  tool calls in one turn, their trajectory items share a `turn` and their
  `[t_start, t_end]` genuinely overlap. Whether same-turn batches actually
  occur is up to the model (Claude on Bedrock does emit multi-tool turns).
- **Tool loop:** we drive the low-level `runAgentLoop` directly (rather than
  the stateful `Agent` class) because it exposes `shouldStopAfterTurn` — the
  clean way to implement `--max-rounds` without aborting mid-turn — and an
  event sink (`tool_execution_start/end`, `message_end`) from which the
  trajectory (thinking blocks → `reasoning` items, tool calls → `tool_call`
  items with returned docids) is recorded. Thinking content arrives as
  `thinking` content blocks on assistant messages and is captured verbatim.
- **Search endpoints:** both hosted search services 403 default user agents;
  all requests send `User-Agent: trec-rag-search/1.0` like the Python
  clients. Dense `POST /search {query,k,with_text}`, sparse
  `POST /api/search {query,hits}` (ES-style `hits.hits[]._id/_score/_source.contents`),
  doc fetch `GET .../doc/{docid}` with `Authorization: Bearer`.
