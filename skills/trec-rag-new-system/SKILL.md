---
name: trec-rag-new-system
description: Use when adding, scaffolding, or reviewing a new TREC RAG 2026 RAG system (an answer-generating agent/pipeline) under src/systems/ in this repo. Covers the required package layout, the shared ragrun/tools/utils/answer-format layers a system must use (never duplicate), the two output artifacts and their strict-vs-rich split, the run.py CLI + import-surgery convention, pluggable LLM backends, the dep-group + README + worklog requirements, and a scaffolder script.
metadata:
  version: v0.1.0
---

# Adding a New TREC RAG 2026 System

Use this skill when the user wants to build a **new RAG system** — an
answer-generating agent or pipeline that retrieves from ClimbMix and emits a
TREC RAG 2026 run — in this repo. It encodes the conventions the existing
systems (`ali_deepresearch`, `aus_agent`, `o3_deep_research`, `facet_rag`)
follow, which are otherwise only discoverable by reading their source.

A system is NOT a `tasks/<task>/` build (those build indexes / serve search).
Systems live under `src/systems/<name>/` and consume the shared retrieval + run
layers.

## Core Rule

Retrieve ONLY from ClimbMix, and reuse the shared layers — never reimplement
them:

- **Retrieval** → `tools.search_tool.run_search_tool` / `build_search_tool`
  (engines: `semantic`, `keyword`, `ssr`, `lucene_bool`) and
  `utils.fetch_doc.fetch_doc(docid)` for full text. No web search. Every cited
  id is a ClimbMix docid.
- **Artifacts** → `ragrun` (`TrajectoryBuilder`, `build_rag_output`,
  `save_run`, `validate_rag_output`).
- **Answer shaping** → `ali_deepresearch.answer_format.format_answer(draft,
  docids, llm=...)` turns free prose into the strict
  `references[]` + per-sentence `citations` shape (LLM stage + deterministic
  offline fallback). Do not hand-roll sentence/citation logic.
- **Pluggable LLM backends** (optional) → `aus_agent.providers` +
  `aus_agent.agent.make_provider(backend, model)` (`bedrock` / `openai`).

## Scaffold a New System

Generate the standard skeleton, then fill it in:

```bash
# reuse the pluggable providers (Bedrock + OpenAI)
python skills/trec-rag-new-system/scripts/scaffold_system.py my_system \
    --backends aus_agent

# or a self-contained OpenAI baseline / no LLM wiring
python skills/trec-rag-new-system/scripts/scaffold_system.py my_baseline --backends openai
python skills/trec-rag-new-system/scripts/scaffold_system.py my_thing   --backends none
```

The script writes `src/systems/<name>/{__init__,run,prompts,pipeline,test_mock}.py`
and prints a checklist for the steps it deliberately does NOT automate
(pyproject dep group, README, worklog). It refuses to overwrite existing files
without `--force`.

## Required Package Layout

Every system is a Python package `src/systems/<name>/`:

- `__init__.py` — small public surface (docstring states corpus-only + docids).
- `run.py` — CLI with a `--query | --qid | --all` mutually-exclusive group,
  the **import-surgery header** (put `src/systems` on `sys.path`, drop the
  package dir, `load_dotenv()`), reads dev topics from the
  `research-rubrics-topics-dev.tsv`, and calls the pipeline per narrative.
- `prompts.py` — prompt strings only; keep engine guidance and citation shape
  out (they come from the shared layers).
- the pipeline/agent module — control flow, trajectory assembly, artifact write.
- `test_mock.py` — offline end-to-end test: a scripted LLM/provider drives the
  **real** pipeline and the **real** ClimbMix search tools. It reports `SKIPPED`
  (not FAIL) when search returns nothing because credentials are unset.
- `README.md` — design diagram, upstream mapping (if a port), CLI, tests.

## The Two Artifacts (strict vs. rich)

`save_run(system_name, query, trajectory=..., output=...)` writes both to
`data/outputs/<system_name>/<ts>.<slug>.{trajectory,output}.json`:

- `*.trajectory.json` — **strict**, sample-compatible retrieval/training
  projection (built by `TrajectoryBuilder`). No timings, tokens, or viewer
  fields. Schema-compatible with
  `data/sample-files/run_InfoSeekQA_1000_*.json`.
- `*.output.json` — the **organizer answer** (`metadata` / `references` /
  `answer`) plus an internal top-level `trace` (timings, tokens, docids,
  context decisions). The submission exporter strips `trace`.

Answer rules enforced by `validate_rag_output` (a `.output.violations.json`
appears if broken): `references` is a docid list, every reference is cited, each
sentence has ≤3 citation indices, the whole answer ≤1024 words, `metadata` has
exactly `{team_id, narrative_id, narrative, run_id, run_desc}`.

## Non-Automated Requirements (do these by hand)

1. **Dep group** in the root `pyproject.toml` `[dependency-groups]` (default
   `uv sync` installs none). Run as `uv run --group <name> python
   src/systems/<name>/run.py …`. Each system gets its own group.
2. **README.md** documenting the design + CLI + tests.
3. **Worklog** `worklogs/YYYY-MM-DD-<name>.md`, committed with the code.

## Credentials

Retrieval needs the repo `.env` (see `.env.example`): `SEARCH_API_KEY`
(dense+sparse), `PYSERINI_API_TOKEN` (keyword/Pyserini). LLM backends need
their own keys (`AWS_*` / `BEDROCK_*` for Bedrock, `OPENAI_API_KEY` /
`OPENAI_MODEL_ID` for OpenAI). Never print or commit tokens.

## Reference Implementations

- `src/systems/facet_rag` — plan-then-execute, pluggable backends, all four
  engines. The cleanest end-to-end example of these conventions.
- `src/systems/ali_deepresearch` — ReAct agent port; `answer_format` lives here.
- `src/systems/aus_agent` — staged-context agent; the pluggable `providers/`.
- `src/systems/o3_deep_research` — minimal single-file runner (hosted DR + MCP).

For track/submission format details use the `trec-rag-2026-track-guidelines`
skill; for hosted retrieval use `pyserini-rest-api`.
