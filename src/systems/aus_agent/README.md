# aus_agent — research-agent RAG harness (TREC RAG 2026)

Agentic RAG with pluggable LLM backends. One model and one continuously
accumulating provider conversation handle the entire run: decomposing the
request, full-text `search`, sparse `commit_context` decisions, coverage-gap
follow-ups, and the final strict-JSON cited report. There is no separate
researcher, finalizer, formatter, compressor, reconstructed context, or
phase-changing prompt.

Both run artifacts (`*.trajectory.json` + `*.output.json`) are written to
`data/outputs/aus_agent/` via `ragrun.save_run`. Every citation must be a docid
the agent explicitly committed.

Search and document results use a staged/committed context protocol:

1. Documents returned by a search turn are staged with an independent
   per-result text budget (default 4,096 approximate tokens, implemented as
   20,480 characters and cut at the preceding line break). The trace records
   docids and compact truncation metadata, never document text.
2. That batch exists for exactly the immediately following model turn.
   `commit_context` must be the first action on that turn and selects a sparse
   evidence-worthy subset. Every selection reason names the distinct evidence
   or coverage aspect being retained.
3. Selected text stays in provider history. Rejected text is replaced by
   `the agent decided this document is irrelevant: <docid>`. The rich trace
   retains docids and decisions only; the viewer fetches document text from
   its document API when requested.
4. If the model fails to commit first, the entire staged batch expires and is
   compacted before another turn. An unresolved batch never carries forward.
5. An already committed docid is never retained again. Later occurrences
   become `duplicate/already committed` tombstones. The prompt also instructs
   the model to skip semantically redundant different docids unless each adds
   materially different evidence.

This keeps long research runs tractable without destroying retrieval or
selection evidence.

## Layout

- `prompts/system.md` — the complete system contract: scope interpretation,
  internal success requirements, research workflow, staged evidence protocol,
  500K stopping policy, and final JSON schema. Runtime substitution uses the
  single distinctive `__MAX_COMMITTED_DOCS__` placeholder.
- `agent.py` — harness loop, staged-context state machine, parallel tool
  execution, current-context token budget, same-loop strict JSON
  validation/correction, docid→reference-index mapping, and trajectory/output
  assembly.
- `context.py` — context ledger, selection validation, and lossless-history
  compaction.
- `tools/search.py` — AUS full-text adapter over the shared
  `tools.search_tool` backend; retrieval logic is not duplicated.
- `tools/commit_context.py` — commit-context schema and focused ledger handler.
- `tools/__init__.py` — exports the definitions and handlers used by the
  orchestrator.
- `run.py` — CLI (see below).
- `providers/base.py` — the per-provider contract.
- `providers/bedrock.py` — boto3 `bedrock-runtime` Converse implementation
  (region `ap-southeast-2`, adaptive extended thinking, reasoning blocks
  replayed verbatim). Note: Sonnet 5 only supports `thinking.type=adaptive`
  (`enabled`+`budget_tokens` is rejected), returns signature-only
  `reasoningContent` (empty text), so the harness also records the model's
  plain-text narration between tool calls as trajectory reasoning.

The high `--safety-max-rounds` setting is only a runaway-loop backstop.
Normal research termination uses `--context-token-budget`, compared with the
provider-reported input tokens for the current generation. That value already
contains the accumulated continuous conversation, so input counts from
different generations are not summed. The trace also records the peak observed
generation input. Compaction can reduce later request sizes by replacing
unselected staged text with tombstones.

Every tool/control result ends with a compact progress line:

```text
[context budget: 82,410 / 500,000 tokens (16.5%) · elapsed: 4m 12s]
```

The same values are machine-readable on the rich trace step under
`stats.context_tokens`, `stats.context_budget_tokens`, and `stats.elapsed_ms`.
Separately, each generation records its direct model token usage under
`stats.tokens`; every later step receives a `stats.cumulative_tokens` snapshot.
Run-level processed input/output totals are stored in `trace.summary.tokens`.
These throughput totals are for usage/cost analysis and do not affect the
500K current-context budget.

## Artifact split

- `*.trajectory.json` is the strict sample-compatible artifact given to other
  team members for analysis and retrieval-model training. It contains no
  timings, token stats, structured context decisions, or viewer fields.
- `*.output.json` preserves the organizer-required answer shape and adds one
  top-level `trace` field. The v2 trace is causal: run input → generation turn
  → child tool calls → next generation turn → run output. Every provider call
  is timed, every tool step points to the generation that issued it, and
  `trace.steps` contains token stats, returned docids, and
  staged/committed/rejected context. Document text and provider-native raw
  messages are omitted from `output.json.trace`.

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

## Single-agent finalization

The final JSON schema is part of the original system prompt. When the model
emits no tool calls, that same turn is validated as the attempted final answer.
Invalid JSON, uncommitted citations, more than three citations per sentence,
or a report over 1024 words receives concise feedback in the same conversation,
and the same model corrects itself on its next turn. No separate final prompt
or compressor call is introduced.

Search is the normal evidence tool. AUS requests full backend hits and applies
its own independent per-result staging budget before returning text to the
model. The only advertised tools are `search` and `commit_context`.

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

# ad-hoc query, explicit model / current-context budget
uv run --group aus-agent python src/systems/aus_agent/run.py \
  --query "..." --model au.anthropic.claude-sonnet-5 --k 10 \
  --context-token-budget 500000 --max-committed-per-step 6

# every topic in the dev TSV (or --topics <tsv>)
uv run --group aus-agent python src/systems/aus_agent/run.py --all
```

Config: root `.env` supplies `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
`AWS_SESSION_TOKEN` and optionally `BEDROCK_MODEL_ID` / `BEDROCK_REGION`.
Verified Bedrock model ids: `au.anthropic.claude-sonnet-5` (default),
`au.anthropic.claude-opus-4-8`, `au.anthropic.claude-haiku-4-5-20251001-v1:0`,
`au.anthropic.claude-sonnet-4-6`, `au.anthropic.claude-opus-4-7`,
`au.anthropic.claude-opus-4-6-v1` (`global.*`/`us.*` profiles: AccessDenied).

## Tests

```sh
uv run --group aus-agent python -m unittest discover \
  -s src/systems/aus_agent -t src -p 'test_*.py' -v
```

The deterministic suite audits bounded text beyond 500 characters,
full→compacted provider history, one-turn staged expiry, exact-docid duplicate
suppression, committed trace transitions, continuous-loop final correction,
strict trajectory projection, selection limits, and context-budget behavior.
