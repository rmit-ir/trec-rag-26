# facet_rag — plan-then-execute multi-facet RAG (TREC RAG 2026)

A corpus-grounded RAG system that answers a research narrative in three
deterministic stages instead of an open-ended agent loop:

```
run.py ─> make_provider(backend) ──────────────────────────┐  (aus_agent.providers)
                                                            │
narrative ─┬─> PLAN      (1 LLM call)  planner.build_plan_prompt
           │              narrative -> {"facets": [{name, engine, query, k}, ...]}
           │              engine blurbs + query guidance injected from tools.search_tool
           │
           ├─> EXECUTE   (no LLM)      search.execute_plan
           │              one ClimbMix search per facet, on the facet's engine;
           │              passages de-duplicated by docid across facets
           │
           └─> SYNTHESIZE(1 LLM call)  prompts.SYNTHESIZE_PROMPT
                          retrieved passages -> grounded prose with inline [docid]
                                   │
        format_answer ────────────┘  (ali_deepresearch.answer_format, reused)
                          prose -> references[] + per-sentence citations
                                   │
        ragrun.save_run ──────────┘  data/outputs/facet_rag/<ts>.<slug>.{trajectory,output}.json
```

Retrieval is corpus-only — no web search — and every citation is a ClimbMix
docid. The system is a middle ground between a single-pass baseline and the
iterative agents (`ali_deepresearch`, `aus_agent`): it plans once, so the
per-facet queries can each target the engine best suited to that facet, but it
never loops, so a run is cheap and predictable (two LLM calls + N searches).

## Why "plan-then-execute"

The four ClimbMix engines rank very differently (`tools/search_tool.py`):
`semantic`/`keyword` want natural language, `ssr` wants a GCL Boolean, and
`lucene_bool` wants Lucene syntax. A single query can't exploit all of them.
By decomposing the narrative into independent **facets** up front and pinning
each to one engine, the planner can (e.g.) send a conceptual facet to
`semantic`, a rare-proper-name facet to `keyword`, and a precise co-occurrence
facet to `ssr` — each in that engine's native language. The query-writing
guidance the planner sees is the *same* text `tools.search_tool` hands the
interactive agents, so it always matches the enabled engines (single source of
truth; nothing is restated in this system's prompts).

## Layout

- `planner.py` — builds the plan prompt (engine blurbs + query guidance injected
  from `tools.search_tool`) and parses/validates the facets JSON. Defensive:
  a disabled engine is coerced to the default, `k` is clamped, empty queries are
  dropped, and an unusable response falls back to one semantic facet over the
  raw narrative so a run always retrieves something.
- `search.py` — thin adapter over `tools.search_tool.run_search_tool`; runs one
  search per facet and de-duplicates passages by docid across facets. Retrieval
  logic is not duplicated here.
- `prompts.py` — the two prompts (`PLAN_PROMPT`, `SYNTHESIZE_PROMPT`). The
  engine list/guidance and the strict citation shape are produced elsewhere, so
  the prompts stay small.
- `pipeline.py` — orchestrates plan -> execute -> synthesize, assembles the
  trajectory (`TrajectoryBuilder`) and output object, maps prose to the strict
  sentence/citation shape via `ali_deepresearch.answer_format.format_answer`,
  and writes both artifacts with `ragrun.save_run`.
- `run.py` — CLI (`--query | --qid | --all`, `--backend`, `--engines`, ...).
Tests live in `tests/systems/test_facet_rag.py` (see `## Tests` below), not in
this package.

## Backends (pluggable — reused, not duplicated)

Backends come straight from `aus_agent.providers` via `aus_agent.agent.make_provider`:

- `--backend bedrock` (default) — AWS Bedrock Claude (region `ap-southeast-2`).
  Config from the repo `.env`: `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
  `AWS_SESSION_TOKEN`, and optionally `BEDROCK_MODEL_ID` / `BEDROCK_REGION`.
  Default model `au.anthropic.claude-sonnet-5`.
- `--backend openai` — OpenAI Responses API. Config: `OPENAI_API_KEY`, and
  optionally `OPENAI_MODEL_ID`.

Each LLM stage is a fresh, tool-less turn, so the provider's turn API is used
single-shot. To add a backend, add a provider under `aus_agent/providers/` and
register it in `aus_agent.agent.make_provider` — this system picks it up for free.

## Retrieval config (`SEARCH_API_KEY`, etc.)

The search backends need credentials in the repo `.env` (see `.env.example`):

```
SEARCH_API_KEY=user:pass                 # dense + sparse ClimbMix services
PYSERINI_API_TOKEN=...                    # hosted Pyserini BM25 (keyword engine)
```

Without them the hosted search endpoints return `401 Unauthorized`. The test
suite needs neither key — retrieval is stubbed offline — so a 401 only affects
real runs and the `live`-marked tests.

## CLI

```sh
# one dev topic by id, all four engines available to the planner (default)
uv run --group facet-rag python src/systems/facet_rag/run.py \
    --qid 6847465956a0f6376a605492

# ad-hoc narrative, OpenAI backend, only semantic + ssr
uv run --group facet-rag python src/systems/facet_rag/run.py \
    --query "How effective are influenza vaccines?" \
    --backend openai --engines semantic ssr

# every dev topic; wider facet budget; offline (heuristic) answer formatter
uv run --group facet-rag python src/systems/facet_rag/run.py --all \
    --min-facets 4 --max-facets 8 --no-format-llm
```

Artifacts land in `data/outputs/facet_rag/<ts>.<slug>.{trajectory,output}.json`
(a `.output.violations.json` appears only if the answer breaks a track rule).

## Tests

```sh
bash scripts/test.sh tests/systems/test_facet_rag.py
```

Fully offline — no credentials, no network, nothing to skip. A `ScriptedProvider`
drives `plan -> execute -> synthesize -> format` through the real pipeline with
retrieval stubbed by the `stub_search_tool` fixture, then asserts both JSONs are
written with no violations, `tool_call_counts == {search: 2}`, a non-empty
`retrieved_docids`, valid per-sentence citations, and the correct strict/rich
artifact split. The planner's JSON parsing (fenced output, disabled engines, `k`
clamping, malformed input → fallback facets) is covered case by case.

`tests/dummy_api/test_dummy_api.py` additionally runs the whole pipeline against
a local HTTP server impersonating the ClimbMix endpoints, so the retrieval
clients themselves are exercised without credentials.

One `@pytest.mark.live` test keeps the real-endpoint path exercisable; it is
deselected by default and needs `SEARCH_API_KEY` / `PYSERINI_API_TOKEN`:

```sh
bash scripts/test.sh live tests/systems/test_facet_rag.py
```
```
