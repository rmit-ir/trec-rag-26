# aus_agent — research-agent RAG harness (TREC RAG 2026)

Agentic RAG over the ClimbMix corpus with pluggable LLM backends. The model
iterates `search` (hybrid dense+sparse RRF, `utils.search`) and `get_document`
(`utils.fetch_doc`) calls, then emits a strict-JSON cited report. Both run
artifacts (`*.trajectory.json` + `*.output.json`) are written to
`data/outputs/aus_agent/` via `ragrun.save_run`. Corpus-only: no web access; every
citation is a ClimbMix docid the agent retrieved during the run.

## Layout

- `agent.py` — harness loop: system prompt, tool execution, round budget
  (`--max-rounds`, then the final answer is forced), final structured-answer
  step (strict JSON, one retry on bad JSON, docid→reference-index mapping,
  ≤1024-word enforcement with one compress round), trajectory/output assembly.
- `run.py` — CLI (see below).
- `providers/base.py` — the per-provider contract.
- `providers/bedrock.py` — boto3 `bedrock-runtime` Converse implementation
  (region `ap-southeast-2`, adaptive extended thinking, reasoning blocks
  replayed verbatim). Note: Sonnet 5 only supports `thinking.type=adaptive`
  (`enabled`+`budget_tokens` is rejected) and returns signature-only
  `reasoningContent` (empty text), so the harness also records the model's
  plain-text narration between tool calls as trajectory reasoning.

## Backend contract

Each provider owns its **native** message history; the harness never sees it
except as the opaque `raw_messages` blob stored in the trajectory. A provider
implements (see `providers/base.py` for the normalized dict shapes):

```
start(system_prompt, tools)      # Anthropic-style tool defs
add_user_message(text)
run_turn() -> ModelTurn          # {blocks, reasoning_blocks, tool_calls,
                                 #  text, stop_reason, usage, raw}
add_tool_results(results)        # [{id, content, is_error}] for ALL pending calls
raw_messages                     # JSON-serializable native history
```

`ModelTurn["blocks"]` preserves content order (reasoning / tool_call / text
interleaved), so the trajectory records reasoning and tool calls exactly as
the model emitted them.

### Adding Azure OpenAI / OpenAI Responses

1. Create `providers/azure_openai.py` (or `openai_responses.py`) subclassing
   `Provider`. Keep the native history internally (chat messages / response
   items); convert the Anthropic-style tool defs in `start()`; map the
   provider's reasoning/tool-call/text items into `ModelTurn` in `run_turn()`;
   append tool outputs natively in `add_tool_results()`.
2. Register it in `agent.make_provider` under a new `--backend` name.
3. `uv add --group aus-agent <sdk>` for its SDK.

## CLI

```sh
# one dev topic by qid
uv run --group aus-agent python src/systems/aus_agent/run.py \
  --qid 6847465956a0f6376a605492

# ad-hoc query, explicit model / budget
uv run --group aus-agent python src/systems/aus_agent/run.py \
  --query "..." --model au.anthropic.claude-sonnet-5 --k 10 --max-rounds 12

# every topic in the dev TSV (or --topics <tsv>)
uv run --group aus-agent python src/systems/aus_agent/run.py --all
```

Config: root `.env` supplies `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
`AWS_SESSION_TOKEN` and optionally `BEDROCK_MODEL_ID` / `BEDROCK_REGION`.
Verified Bedrock model ids: `au.anthropic.claude-sonnet-5` (default),
`au.anthropic.claude-opus-4-8`, `au.anthropic.claude-haiku-4-5-20251001-v1:0`,
`au.anthropic.claude-sonnet-4-6`, `au.anthropic.claude-opus-4-7`,
`au.anthropic.claude-opus-4-6-v1` (`global.*`/`us.*` profiles: AccessDenied).
