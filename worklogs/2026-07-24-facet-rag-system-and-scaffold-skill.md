# 2026-07-24 — New RAG system `facet_rag` + `trec-rag-new-system` scaffold skill

## Goal

Add a new RAG system following the repo's existing conventions, and (per a
follow-up) close the gap that those conventions are undocumented by adding a
skill that scaffolds one.

## What a "system" is here (reverse-engineered — was undocumented)

RAG systems live under `src/systems/<name>/` (distinct from `tasks/<task>/`,
which build/serve indexes). Each is a Python package that:

- retrieves ONLY from ClimbMix via `tools.search_tool` (+ `utils.fetch_doc`);
  every citation is a ClimbMix docid; no web search.
- emits two artifacts via `ragrun.save_run` to
  `data/outputs/<name>/<ts>.<slug>.{trajectory,output}.json`:
  - `trajectory.json` = strict, sample-compatible retrieval/training projection
    (`TrajectoryBuilder`), no timings/tokens.
  - `output.json` = organizer answer (`metadata`/`references`/`answer`) + an
    internal `trace` (timings/tokens/docids). Validated by
    `validate_rag_output` (≤3 cites/sentence, ≤1024 words, every ref cited,
    exact metadata keys).
- maps free prose → strict sentence/citation shape via
  `ali_deepresearch.answer_format.format_answer` (LLM stage + offline heuristic).
- `run.py` CLI: `--query|--qid|--all`, import-surgery header, dev topics TSV.
- ships `README.md` + a dep group in root `pyproject.toml` + `test_mock.py`.

Confirmed **not documented** in AGENTS.md/CLAUDE.md (headings: Environment /
Running Long Commands / Worklogs / Notebooks / Active Tasks / Stack quirks; no
`src/systems`/`ragrun` mention). Only the `ragrun/__init__.py` docstring and the
per-system READMEs describe it.

## Design decisions (chosen by the user)

- Strategy: **plan-then-execute (multi-facet)**.
- Backends: **pluggable (both)** — reuse `aus_agent.providers` +
  `aus_agent.agent.make_provider` (bedrock/openai), not duplicated.
- Retrieval: **all four engines** exposed to the planner (semantic/keyword/ssr/
  lucene_bool).

## `facet_rag` — what was built

`src/systems/facet_rag/`:

- `prompts.py` — `PLAN_PROMPT` (narrative → facets JSON; engine blurbs + query
  guidance injected at runtime from `tools.search_tool`), `SYNTHESIZE_PROMPT`.
- `planner.py` — `build_plan_prompt`, `parse_facets` (defensive: bad engine →
  default, `k` clamped to [1,20], empty query dropped, fenced JSON stripped),
  `fallback_facets`.
- `search.py` — `execute_plan`: one `run_search_tool` call per facet on its
  engine, passages de-duplicated by docid across facets.
- `pipeline.py` — `run_one`: plan (1 LLM turn) → execute (N searches) →
  synthesize (1 LLM turn) → `format_answer` → `save_run`. `_ProviderLLM` adapts
  the turn-based `Provider` to the `format_answer` ChatLLM `.complete` shape;
  `_usage_token_stats` mirrors `aus_agent.agent`.
- `run.py` — CLI (`--backend bedrock|openai`, `--engines`, `--min/max-facets`,
  `--max-chars`, `--no-format-llm`).
- `test_mock.py` — scripted `Provider` drives the 3 real stages against the real
  ClimbMix search; SKIPs (not FAILs) when retrieval returns nothing.
- `README.md`, dep group `facet-rag` in `pyproject.toml`
  (`boto3>=1.40`, `openai>=2.45`).

## Verification (exact inputs + results)

Narrative for all tests: `"How effective are influenza vaccines at preventing
illness?"`

1. **Import + parser robustness** (`parse_facets` on fenced JSON with a bad
   engine `"nope"` and `k=99`, plus a missing-`k` ssr facet):
   → `[('semantic', 20, 'x y'), ('ssr', 10, '(^ a b)')]` — coercion + clamp +
   default all correct; fallback engine = `semantic`; plan prompt contains
   engine blurbs. **PASS**

2. **Full pipeline, search stubbed offline** (2 facets: semantic
   "influenza vaccine effectiveness" k5, keyword "...strain match season" k5):
   → `status=completed`, `tool_call_counts={'search': 2}`,
   `retrieved_docids=['shard_00001_1','shard_00002_2']`,
   `references=['shard_00001_1']`, 2 answer sentences,
   `validate_rag_output == []`, step kinds
   `['reasoning','tool_call','tool_call','output_text']`. **PASS**

3. **`test_mock.py` against the REAL search backend**: every facet search
   returned `HTTPError: HTTP Error 401: Unauthorized` (no `SEARCH_API_KEY` /
   `.env` in this checkout — same live-retrieval dependency as
   `ali_deepresearch/test_mock.py`). Direct probe
   `python src/tools/search_tool.py "influenza vaccine effectiveness" --engine
   semantic` → `{"error": "HTTPError: HTTP Error 401: Unauthorized"}`. Test now
   reports **SKIPPED (not a code failure)**. Live pass is pending search
   credentials.

## `trec-rag-new-system` skill (answer to the follow-up question)

Adding a system was undocumented and worth automating, so added
`skills/trec-rag-new-system/`:

- `SKILL.md` — the conventions above (core rule, layout, artifact split,
  non-automated requirements, reference implementations).
- `scripts/scaffold_system.py` — generates
  `src/systems/<name>/{__init__,run,prompts,pipeline,test_mock}.py` wired to the
  shared layers; `--backends aus_agent|openai|none`; refuses to overwrite
  without `--force`. Deliberately does NOT touch `pyproject.toml`/README/worklog
  — prints them as a checklist to keep the human in the loop.

Verified: scaffolded a throwaway `scaffold_probe --backends aus_agent`, all 5
files `py_compile` OK, its `test_mock.py` ran and SKIPped on 401, `run.py
--help` parsed. Probe + its output artifacts deleted.

## Follow-ups

- Add `SEARCH_API_KEY` (+ `PYSERINI_API_TOKEN` for keyword/ssr) to `.env` to run
  `test_mock.py` live and do a real `--qid` dev-topic run.
- Consider a one-line pointer to `trec-rag-new-system` from AGENTS.md so the
  skill is discoverable.
