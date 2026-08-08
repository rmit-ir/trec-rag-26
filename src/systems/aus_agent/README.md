# aus_agent — research-agent RAG harness (TREC RAG 2026)

Agentic RAG with pluggable LLM backends. One model and one continuously
accumulating provider conversation handle the entire run: decomposing the
request, full-text `search`, sparse `commit_context` decisions, coverage-gap
follow-ups, and the final cited prose report (one sentence per line with
inline `[docid]` markers, parsed by the harness into the organizer JSON).
There is no separate researcher, finalizer, formatter, compressor,
reconstructed context, or phase-changing prompt.

Both run artifacts (`*.trajectory.json` + `*.output.json`) are written to
`data/outputs/aus_agent/` via `ragrun.save_run`. Every citation must be a docid
the agent explicitly committed.

The loop itself (`run_agent`), `ContextLedger`, the Bedrock/OpenAI providers,
and the search/commit_context/get_documents tool builders live in the shared
`agent_harness` package (a sibling of `ragrun`/`tools`/`utils`), not here —
this package now holds only what is genuinely aus_agent-specific: its own
`prompts/system/*.md` variants and the loader that resolves one. facets_agent
runs the same shared loop with its own prompt/tools; see `agent_harness`'s
own docstrings for the harness contract.

Search and document results use a staged/committed context protocol:

1. Documents returned by a search turn are staged with an independent
   per-result text budget (default 4,096 approximate tokens, implemented as
   20,480 characters and cut at the preceding line break). The trace records
   docids and compact truncation metadata, never document text.
2. That batch exists for exactly the immediately following model turn.
   `commit_context` must be called on that turn — its position among the
   turn's actions does not matter, since commits are applied before the same
   turn's searches — and selects a sparse evidence-worthy subset. Every
   selection reason names the distinct evidence or coverage aspect retained.
3. Selected text stays in provider history. Rejected text is replaced by
   `the agent decided this document is irrelevant: <docid>`. The rich trace
   retains docids and decisions only; the viewer fetches document text from
   its document API when requested.
4. If the model fails to commit first, the entire staged batch expires and is
   compacted before another turn. An unresolved batch never carries forward.
5. An already committed docid is never retained again. Later occurrences
   become `duplicate/already committed` tombstones. Beyond that exact-id rule,
   selection **adjudicates rather than de-duplicates**: several results bearing
   on one claim is the batch working (especially when a lead was searched on
   more than one engine), so the model keeps the complementary ones — or the
   single best where they genuinely coincide — against stated criteria
   (concrete figure/date/named finding over categorical description, worked
   example over generalisation, primary over a report of it, the more precise
   statement of the same point). A result is rejected because another beat it,
   never because it looked similar. The earlier "skip semantically redundant"
   rule silently cancelled dual-engine retrieval and was removed from the tool
   description and every prompt variant together.

This keeps long research runs tractable without destroying retrieval or
selection evidence.

## Layout

- `prompts/system/` — one full system prompt per file, selected by
  `--prompt-variant <stem>`. `default.md` is the live baseline (the complete
  system contract: scope interpretation, internal success requirements,
  research workflow, staged evidence protocol, 500K stopping policy, and the
  final prose-report contract); the others are single-variable arms branched
  from it, and the chosen variant is recorded in the run metadata + `run_desc`.
  Runtime substitution uses the single distinctive `__MAX_COMMITTED_DOCS__`
  placeholder.

  | variant | the one thing it changes |
  |---|---|
  | `default` | — (control) |
  | `firsthand` | favours first-hand / original sources |
  | `paired-lead` | a lead is not ready to judge until *both* engines have answered it (volume-neutral: fewer leads per round, covered properly) |
  | `done-condition` | a lead ledger (resolved / refuted / needs-depth) plus marginal-yield termination, replacing the coverage-area stopping rule |
  | `evidence-dense` | answer-side only: cite every world-asserting sentence or cut it, carry the specific figure out of the committed passage, no unrequested localization |

  Because each is a full copy, a parametrized test
  (`test_every_variant_keeps_the_shared_harness_contract`) asserts every file
  still carries the clauses the harness enforces — a variant that dropped one
  would fail as a run, and the cause would be invisible in the scores.
  Variants are generated from `default.md` by anchored replacement of only the
  section being changed, so a score difference is attributable.
- `agent.py` — harness loop, staged-context state machine, parallel tool
  execution, current-context token budget, same-loop final-report
  parsing/validation/correction, docid→reference-index mapping, and
  trajectory/output assembly.
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
  replayed verbatim, prompt caching via `cachePoint`). Note: Sonnet 5 only
  supports `thinking.type=adaptive` (`enabled`+`budget_tokens` is rejected),
  returns signature-only `reasoningContent` (empty text), so the harness also
  records the model's plain-text narration between tool calls as trajectory
  reasoning.

## Prompt caching

Claude on Bedrock has **no automatic caching** (unlike Nova) — every cached
prefix needs an explicit `{"cachePoint": {"type": "default"}}` block. Bedrock
chains `tools` → `system` → `messages` and measures the per-checkpoint token
minimum against their cumulative total, so stable content must precede volatile
content. Two of the four checkpoints Claude allows are used:

1. a **static** one at the end of `system`, covering tools + system; and
2. a **rolling** one at the end of the last *settled* user message.

"Settled" rests on an invariant of the staged-context protocol: compaction only
ever rewrites the one batch held in the ledger's `pending` list, and the commit
that triggers it clears `pending`, so each tool result is compacted exactly
once. By the time `compact_tool_results` returns, every message then in history
has reached its final bytes — hence `_settled_count = len(self._messages)`.
The freshly staged batch appended afterwards sits *outside* the breakpoint: it
is about to be rewritten, so caching it would buy an entry the next turn
invalidates. The rolling point is anchored on a **user** message so that signed
`reasoningContent` assistant messages are never touched.

Anthropic models on Bedrock support simplified cache management — one
checkpoint at the end of the static content, and the service looks back ~20
content blocks for the longest matching prefix — so a single rolling checkpoint
suffices and old breakpoints need not be retained. Measured across the dev
topics, a turn adds 2–13 content blocks, comfortably inside that window.

Cache entries are **prefixes, not segments**: every entry starts at byte zero,
so moving the breakpoint forward writes a superset of the previous entry rather
than evicting the front. Measured on one dev topic: 40.7% fewer effective input
units (~35% cheaper end to end). Note that with caching on, `usage.inputTokens`
counts only non-cached input; the true context size is
`inputTokens + cacheReadInputTokens + cacheWriteInputTokens`, which is what
`_usage_token_stats` reports and what the 500K budget is compared against.

Caveat: the default TTL is 5 minutes, refreshed on every hit. Typical turns are
~20 s, but a single very long generation can let the cache lapse and force a
re-write. AWS documents the 1-hour TTL only for Opus 4.5 / Haiku 4.5 /
Sonnet 4.5. Pass `caching=False` to `BedrockProvider` to disable.

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

The final-report contract is part of the original system prompt: plain prose,
one sentence per line, citations as inline `[docid]` markers on the supporting
sentence's line, targeting ~950 words against the organizer's hard 1024-word
limit. The model writes at its natural register instead of serializing JSON;
the harness parses the lines, strips the markers (they must never act as words
in a sentence), and maps docids to reference indices for the organizer schema.
When the model emits no tool calls, that same turn is parsed as the attempted
final answer.

The parser **repairs rather than rejects** wherever the intent is unambiguous,
because every rejection costs a full correction turn at full context size.
Repaired silently and recorded in `trace.summary.report_repairs`:

- a citation-only line — the model routinely puts a sentence's markers on the
  line below it, so they fold into the preceding sentence (this alone was 78%
  of all observed correction problems);
- Markdown — fences and headings are dropped (neither carries a citable claim,
  and the schema cannot represent them), while list/quote markers and emphasis
  are unwrapped in place, keeping the sentence;
- more than three citations on one sentence — the extras are dropped; and
- a docid that was never committed — that citation is dropped.

Only what the model itself must resolve is bounced back for a same-conversation
correction: an empty response, a report with no sentences, a report that cites
nothing while committed evidence exists, and an over-length report (truncating
that one would cut the conclusion, so the model re-prioritizes instead). No
separate final prompt or compressor call is introduced.

Search is the normal evidence tool. AUS requests full backend hits and applies
its own independent per-result staging budget before returning text to the
model. The advertised tools are `search`, `get_documents`, and `commit_context`.

`search_engine` is **required on every search call**, including in a
single-engine run: the model names the backend it wrote the query for, and an
omitted engine comes back as an error envelope naming the run's enabled set
rather than being routed to a harness-chosen default. That keeps engine
attribution in the trajectory honest — the per-subquery labels feed retriever
fine-tuning, and a hit filed under an engine nothing selected is label noise.
The default enabled set is the dense+sparse pair `semantic,keyword`
(`--search-backends`).

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
