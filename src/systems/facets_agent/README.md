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

## The prompt

Unlike `aus_agent/prompts/system/default.md` (~270 lines, heavily tuned
across many prompt-engineering passes), `facets_agent/prompts.py` is a single
~50-line prompt. It states the five-stage process once, plainly — decompose
into facets; search each facet on `semantic` + `keyword` + a HyDE-style
`hybrid` query; curate distinct contributions rather than duplicates; iterate
until a facet is covered; self-check citations before finalizing — and states the
tool/citation mechanics (`search` / `get_documents` / `commit_context`, the
one-sentence-per-line `[id]`-cited final report) once each, trusting the model
to fill in the judgment calls that `aus_agent`'s prompt spells out at length.

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
omitted `k` on a `hybrid` call widens to `DEFAULT_HYBRID_K`; and
`get_documents` is wired in. The loop mechanics themselves (staged/committed
evidence, citation parsing, budget/backstop behavior) are already covered by
`tests/systems/test_aus_agent.py` against the same shared code and are not
re-tested here.
