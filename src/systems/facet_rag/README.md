# facet_rag — orchestrator/analyzer multi-facet RAG (TREC RAG 2026)

A corpus-grounded RAG system that splits a research narrative into
independent facets and runs each through its own two-model search loop:

```
run.py ─> make_orchestrator() / make_analyzer() ──────┐  (aus_agent.providers, both fixed to Bedrock)
                                                       │
narrative ──> PLAN (orchestrator, 1 call)  planner.build_plan_prompt
                        narrative -> {"facets": [{name, description, max_iterations}, ...]}
                                   │
              ┌────────────────────┴────────────────────┐
              │   per facet, CONCURRENT (ThreadPoolExecutor)  │
              │                                                │
              │   loop.run_facet_loop  (<=10 iterations)       │
              │                                                │
              │   orchestrator: native Bedrock tool-use turn   │
              │     -> picks engine(s), calls `search`          │
              │            │                                    │
              │   analyzer: one-shot judge                      │
              │     -> keep relevant passages + note,            │
              │        report a gap or "satisfied"                │
              │            │                                    │
              │   satisfied? / no search? / cap reached? ──stop  │
              │   else: gap fed back to orchestrator, loop again │
              └────────────────────┬────────────────────┘
                                   │  evidence, deduped by docid across facets
                                   ▼
        DRAFT (orchestrator, 1 call)    prompts.SYNTH_DRAFT_PROMPT
                        merged evidence -> cited prose
                                   │
        FACT-CHECK (analyzer, 1 call)   prompts.FACT_CHECK_PROMPT
                        patches unsupported citations
                                   │
        format_answer ────────────┘  (ali_deepresearch.answer_format, reused)
                        prose -> references[] + per-sentence citations
                                   │
        ragrun.save_run ──────────┘  data/outputs/facet_rag/<ts>.<slug>.{trajectory,output}.json
```

Retrieval is corpus-only — the orchestrator's only tool is `search`
(`tools.search_tool`, the same four ClimbMix engines every other system in
this repo uses) — no web search, no other external API. Every citation is a
ClimbMix docid the analyzer actually vetted as relevant, not just anything
retrieved.

## Two fixed roles, not a pluggable single backend

Unlike the old plan-then-execute version (single interchangeable
`--backend`), this system has two distinct roles that always run together:

- **ORCHESTRATOR** (default `openai.gpt-oss-120b-1:0`) — plans facets, drives
  the search tool (chooses engine(s), writes the query, reacts to a
  coverage-gap note by searching again), and drafts the final report.
- **ANALYZER** (default `qwen.qwen3-next-80b-a3b`) — judges each round of
  retrieved passages against the facet's need, keeps what's relevant with a
  supporting note, reports a coverage gap (or "satisfied"), and fact-checks
  the orchestrator's draft.

Both go through the shared `aus_agent.providers.bedrock.BedrockProvider`
(`aus_agent.agent.make_provider("bedrock", model, region=...)`), but as two
independent conversations — a `Provider` owns its own history, and facets run
concurrently in their own threads, so `run_one` takes `make_orchestrator` /
`make_analyzer` **factories** (zero-arg callables), not pre-built provider
instances. Every plan/facet-loop/draft/fact-check/format call gets its own
fresh instance.

**The two models commonly need different Bedrock regions under this
account** — see `## Backends` below.

## Why per-facet loops instead of one upfront search per facet

The old architecture picked one engine + query per facet at plan time and
never revisited it. That's cheap but brittle: a facet's first search can miss
(wrong engine, under-specified query) with no way to recover. Here the
orchestrator decides retrieval strategy *live*, and the analyzer's coverage
gap drives a real second (third, ...) attempt — up to 10 rounds, capped by
`planner.GLOBAL_ITERATION_CAP` regardless of what the planner requested for
that facet. A facet the planner judges simple gets a small budget
(`max_iterations`); an ambiguous or broad one gets up to the full 10.

## Layout

- `planner.py` — builds the plan prompt and parses/validates the facets JSON
  into `{name, description, max_iterations}` (no engine/query — the
  orchestrator decides that live). `max_iterations` is clamped to
  `[1, GLOBAL_ITERATION_CAP]`; an unusable plan falls back to one facet over
  the raw narrative, which gets the full iteration budget since it has no
  sibling facets to share retrieval cost with.
- `loop.py` — `run_facet_loop`: the orchestrator/analyzer search-analyze-gap
  loop for one facet. The orchestrator gets a native Bedrock tool-use
  conversation with the `search` tool (`tools.search_tool.build_search_tool`,
  `run_search_tool`); the analyzer is a fresh one-shot judge call every
  iteration (`ANALYZER_PROMPT`). Stops on whichever comes first: the analyzer
  says satisfied, the orchestrator issues no search, or the iteration cap.
  Trace events are buffered per facet (`LoopEvent`/`FacetLoopResult`) rather
  than written straight to `TrajectoryBuilder`, which is not thread-safe —
  `pipeline.py` replays them sequentially once every facet has finished.
- `prompts.py` — five prompts: `PLAN_PROMPT`, `ORCHESTRATOR_SYSTEM_PROMPT` /
  `ORCHESTRATOR_TASK_PROMPT` / `ORCHESTRATOR_GAP_PROMPT` (the facet loop),
  `ANALYZER_PROMPT` (per-iteration judgment), `SYNTH_DRAFT_PROMPT` +
  `FACT_CHECK_PROMPT` (joint synthesis).
- `pipeline.py` — orchestrates plan -> concurrent facet loops -> merge
  evidence (dedup by docid, first facet to surface it wins) -> joint
  draft + fact-check synthesis, assembles the trajectory, maps prose to the
  strict sentence/citation shape via
  `ali_deepresearch.answer_format.format_answer`, and writes both artifacts
  with `ragrun.save_run`.
- `run.py` — CLI (`--query | --qid | --all`, `--orchestrator-model` /
  `--orchestrator-region`, `--analyzer-model` / `--analyzer-region`,
  `--engines`, ...).

Tests live in `tests/systems/test_facet_rag.py` (see `## Tests` below), not
in this package.

## Backends (both fixed to Bedrock — regions commonly differ)

- `--orchestrator-model` (default `openai.gpt-oss-120b-1:0`, a bare id, no
  `au.`/`us.` inference-profile prefix) — works in both `ap-southeast-2` and
  `us-east-1`. `--orchestrator-region` defaults to `None` (falls back to
  `BEDROCK_REGION` env, or `ap-southeast-2`).
- `--analyzer-model` (default `qwen.qwen3-next-80b-a3b`) — **only reachable
  in `us-east-1`/`us-west-2` under this account**; it 400s as "invalid model
  identifier" in `ap-southeast-2`/`ap-southeast-1`, even though the
  orchestrator's default and the repo's Claude profiles work there.
  `--analyzer-region` therefore defaults to `us-east-1`, not the shared
  `BEDROCK_REGION` env. `moonshot.kimi-k2-thinking` is also verified working
  under the same `us-east-1`/`us-west-2` constraint, as an analyzer
  alternative.
- Credentials for both come from the repo `.env`: `AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`.
- Thinking (`additionalModelRequestFields`) and prompt caching (`cachePoint`)
  are Anthropic-only Converse extensions — `BedrockProvider` auto-disables
  both for any non-`anthropic.*` model id, so neither role needs to worry
  about them.

To change roles, pass `--orchestrator-model`/`--analyzer-model` (and the
matching `--*-region`) — no code change needed, `aus_agent.agent.make_provider`
handles any Bedrock model id.

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
# one dev topic by id, all four engines available to the orchestrator (default)
uv run --group facet-rag python src/systems/facet_rag/run.py \
    --qid 6847465956a0f6376a605492

# ad-hoc narrative, only semantic + ssr
uv run --group facet-rag python src/systems/facet_rag/run.py \
    --query "How effective are influenza vaccines?" \
    --engines semantic ssr

# ad-hoc narrative, moonshot Kimi as the analyzer instead of Qwen
uv run --group facet-rag python src/systems/facet_rag/run.py \
    --query "How effective are influenza vaccines?" \
    --analyzer-model moonshot.kimi-k2-thinking --analyzer-region us-east-1

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

Fully offline — no credentials, no network, nothing to skip. Two
`ScriptedProvider` factories (orchestrator, analyzer) drive the real
pipeline end to end with retrieval stubbed by the `stub_search_tool` fixture;
responders route by each prompt's unique marker text (`FACET:`, `Coverage
gap reported`, `EVIDENCE:`, `NEWLY RETRIEVED PASSAGES:`, `DRAFT:`,
`ALLOWED DOCIDS:`), which stays correct under concurrent per-facet execution.
Loop-mechanics tests (stop conditions, gap feedback, the 10-iteration cap,
evidence dedup) call `loop.run_facet_loop` directly instead of through the
full pipeline, keeping them single-threaded and deterministic.

`tests/dummy_api/test_dummy_api.py` additionally runs the whole pipeline
against local HTTP servers impersonating the ClimbMix endpoints, so the
retrieval clients themselves are exercised without credentials.

One `@pytest.mark.live` test keeps the real-endpoint path exercisable; it is
deselected by default and needs `SEARCH_API_KEY` / `PYSERINI_API_TOKEN`:

```sh
bash scripts/test.sh live tests/systems/test_facet_rag.py
```
