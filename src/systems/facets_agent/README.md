# facets_agent — minimal-prompt facet_rag-style agent (TREC RAG 2026)

A single continuous tool-calling agent, running `gpt-5.6-luna` (OpenAI
Responses backend), given a **much shorter prompt than `aus_agent`'s** but
asked to run `facet_rag`'s process itself: decompose the request into
independent facets, search each facet across complementary engines, curate
evidence rather than collect it, iterate on gaps, and self-check citations
before writing the report.

## Design

`facet_rag` gets this process by scripting it across separate model calls (a
planner, then a per-facet orchestrator/analyzer/curator loop, then a
draft/fact-check pass). `facets_agent` is the opposite bet: hand ONE agent a
short prompt describing that same process and its whole tool set, and let the
model run all five process stages itself inside one conversation, the way
`aus_agent` already runs search/commit/report as one continuous loop. The two
systems
exist to compare a scripted multi-call pipeline against a single agent
following the same process from a terser prompt.

Concretely, `facets_agent` is **thin configuration over the shared
`aus_agent.agent.run_agent` harness**, not a fork of it — the staged/committed
evidence protocol, the budget tracking, the final-report citation parsing, and
the pluggable Bedrock/OpenAI providers are all reused unchanged
(`src/systems/aus_agent/agent.py`, `context.py`, `tools/`, `providers/`).
`aus_agent.agent.run_agent` was generalized (`system_name`, `system_prompt`,
`default_k_by_engine` parameters) so a second system could configure it
without copying ~1,300 lines of tested loop logic or writing artifacts into
`aus_agent`'s own output tree. `src/systems/facets_agent/agent.py` supplies
only what makes this system distinct:

- `prompts.SYSTEM_PROMPT` — the short facet_rag-inspired prompt (see below).
- `DEFAULT_ENGINES` — the three natural-language retrieval backends enabled by
  default (`semantic`, `keyword`, `hybrid`), not `aus_agent`'s
  `semantic,keyword` pair. `ssr`/`lucene_bool` are no longer supported and are
  not offered.
- `DEFAULT_HYBRID_K` (15) — `hybrid` calls that omit `k` get a wider net than
  the other engines, mirroring `facet_rag`'s `HYBRID_K` (its `hybrid` query is
  a HyDE-style hypothetical passage, which benefits from more candidates).
- `system_name="facets_agent"` — artifacts land in `data/outputs/facets_agent/`,
  never mixed with `aus_agent`'s own runs.
- `tools.COMMIT_CONTEXT_TOOL` — extends aus_agent's shared tool with a
  `release` property, and `commit_context_tool=` passes it to `run_agent`
  instead of aus_agent's plain one. See "Minimal evidence per facet" below.

## The prompt

Unlike `aus_agent/prompts/system/default.md` (~270 lines, heavily tuned
across many prompt-engineering passes), `facets_agent/prompts.py` is a single
~65-line prompt. It states the five-stage process once, plainly — decompose
into facets and solve each independently; search each facet on `semantic` +
`keyword` + a HyDE-style `hybrid` query; keep each facet's committed evidence
minimal, releasing a document a better one supersedes; iterate until a facet
is covered; self-check citations before finalizing — and states the
tool/citation mechanics (`search` / `get_documents` / `commit_context`, the
one-sentence-per-line `[id]`-cited final report) once each, trusting the model
to fill in the judgment calls that `aus_agent`'s prompt spells out at length.

## Minimal evidence per facet: releasing a superseded document

Each facet is meant to end up with the SMALLEST set of committed documents
that actually covers it, not every document that was ever useful along the
way. `commit_context`'s ordinary `documents` selection only ever grows that
set — nothing in the base protocol lets an already-committed document's full
text leave the conversation once it is in, because that text now lives
verbatim in the model's OWN history. Making "commit the better one, drop the
one it replaces" possible needed a real harness capability, not just prompt
wording:

- `aus_agent.context.ContextLedger.release_committed` — drops a unit
  committed on ANY earlier turn (not just the currently staged batch) by
  recomputing that turn's tool-result compaction from scratch (original
  output + current `committed_ids` membership), so it needs no way to read
  the provider's current, possibly-already-compacted history back out.
- `aus_agent.tools.commit_context.apply_commit` reads an optional `release`
  argument off any `commit_context` call and routes it there, regardless of
  which system's tool schema advertised the field — so this is dead code for
  `aus_agent` itself (whose prompt and tool definition never mention
  `release`) and live for `facets_agent`.
- `facets_agent.tools.COMMIT_CONTEXT_TOOL` is the schema that actually tells
  the model the field exists: aus_agent's own tool definition is untouched.

The result: `commit_context(documents=[{id: "z", reason: "..."}],
release=[{id: "a", reason: "z states this more precisely"}])` commits `z` and
retroactively compacts whichever earlier turn rendered `a` in full, replacing
it with a tombstone the model can tell apart from an ordinary rejection or
duplicate (`RELEASE_PREFIX`, `aus_agent/context.py`).

## CLI

```sh
# one dev topic by qid, all three engines, gpt-5.6-luna
uv run --group facets-agent python src/systems/facets_agent/run.py \
  --qid 6847465956a0f6376a605492

# ad-hoc query, explicit model / narrower engine set
uv run --group facets-agent python src/systems/facets_agent/run.py \
  --query "..." --model gpt-5.6-luna --engines semantic,hybrid

# every topic in the dev TSV
uv run --group facets-agent python src/systems/facets_agent/run.py --all
```

Config: root `.env` supplies `OPENAI_API_KEY` (default backend). Pass
`--backend bedrock` to use `aus_agent`'s Bedrock provider instead (needs
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`).

## Tests

```sh
uv run --group dev --group aus-agent pytest tests/systems/test_facets_agent.py
uv run --group dev --group aus-agent pytest tests/systems/test_facets_agent.py -m live
```

The offline suite drives the real harness (scripted provider + stubbed
retrieval) and checks what's specific to this system: artifacts land under
`facets_agent`, not `aus_agent`; the search tool advertises the three
natural-language engines (not `ssr`/`lucene_bool`, no longer supported); an
omitted `k` on a `hybrid` call widens to `DEFAULT_HYBRID_K`; `get_documents`
is wired in; the `commit_context` tool advertises `release`; and a full
commit -> supersede -> release -> cite-only-the-better-one run reaches the
final answer with the superseded document's text actually gone from
history. The loop mechanics themselves (staged/committed evidence, citation
parsing, budget/backstop behavior) are already covered by
`tests/systems/test_aus_agent.py` against the same shared code and are not
re-tested here; `ContextLedger.release_committed` and `apply_commit`'s
`release` handling have their own unit suites in
`tests/aus_agent_context/test_ledger_release.py` and
`test_commit_tool.py`.
