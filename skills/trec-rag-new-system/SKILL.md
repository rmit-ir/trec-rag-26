---
name: trec-rag-new-system
description: Use when adding, scaffolding, running, or reviewing a TREC RAG 2026 RAG system (an answer-generating agent/pipeline) under src/systems/ in this repo. Covers the required package layout, the shared ragrun/tools/utils/answer-format layers a system must use (never duplicate), the two output artifacts and their strict-vs-rich split, the run.py CLI + import-surgery convention, pluggable LLM backends, the dep-group + README + worklog requirements, a scaffolder script, and the interactive architecture visualization (docs/architecture.html) that must be regenerated and launched whenever a system is developed or run.
metadata:
  version: v0.2.0
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

## Architecture Visualization (regenerate + launch every time)

`scripts/gen_arch_viz.py` auto-derives an **interactive** diagram of the whole
systems layer and writes a single self-contained HTML file to
`docs/architecture.html` (inline SVG + vanilla JS, no server, no CDN).

**Rule: regenerate and launch it whenever a system is developed or run.** The
HTML is a committed build artifact derived from source, so it goes stale
silently. Concretely:

- **After scaffolding a new system** — regenerate so it appears at all.
- **After changing a system's wiring or stages** (new shared-layer import, edited
  `ARCH_STAGES`) — regenerate so the edges/stages match the code.
- **When running a system** — launch it deep-linked to that system, so the
  pipeline you are executing is on screen while you read its output.

This rule is **enforced**, not just documented — see *Enforcement* below.

### Commands

Regenerate (always safe, deterministic output — stable diffs):

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py                  # -> docs/architecture.html
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open           # + open the overview
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --print-model    # inspect the derived model (no write)
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --out /tmp/a.html
```

Launch straight into one existing system's pipeline (`--system` implies
`--open`; it validates the name against the derived model):

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system facet_rag
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system ali_deepresearch
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system aus_agent
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system o3_deep_research
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system claude-code-research
```

Pair it with an actual run — regenerate + launch the diagram, then run the
system:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system facet_rag
uv run --group facet-rag python src/systems/facet_rag/run.py --qid <id>
```

Deep links are plain URL fragments (`docs/architecture.html#facet_rag`), so you
can bookmark a system view or link it from a README/worklog. An unknown
`--system` exits non-zero and lists the known names.

### Enforcement (three layers)

The generator's output is **byte-deterministic**, so freshness is checkable:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check   # exit 1 if stale/missing
```

1. **Claude Code hooks** — `.claude/settings.json` runs
   `scripts/hooks/arch_viz_refresh.sh` on every `Edit|Write|MultiEdit`
   (regenerates silently, but only when the edit touched `src/systems/` or the
   generator) and again on `Stop --verify` (last-word check that self-heals, and
   blocks with instructions if it can't). So during an agent session the diagram
   stays current with no manual step.

   **`.claude/` is gitignored in this repo, so `settings.json` is NOT committed
   and must be created by hand in every clone** (the hook script itself *is*
   committed). Copy the tracked template:

   ```bash
   mkdir -p .claude
   cp scripts/hooks/claude-settings.example.json .claude/settings.json
   ```

   If you already have a `.claude/settings.json`, **merge** its `hooks` block
   into yours rather than overwriting. Restart Claude Code (or `/hooks`) to pick
   the change up, and verify with:

   ```bash
   echo '{}' | scripts/hooks/arch_viz_refresh.sh --verify && echo "hook OK"
   ```

   Without this file the other two layers still enforce freshness — you just
   lose the automatic in-session regeneration and have to run the generator
   yourself.
2. **Git pre-commit hook** — `scripts/git-hooks/pre-commit` refuses a commit
   whose *staged tree* has a stale diagram. It checks the **index**, not the
   working tree, so a locally-fixed-but-unstaged file can't sneak a stale commit
   through, and it only fires when the commit touches `src/systems/`,
   `gen_arch_viz.py`, or `docs/architecture.html`. **Git hooks are not cloned —
   run the installer once per clone:**

   ```bash
   bash scripts/git-hooks/install.sh      # sets core.hooksPath=scripts/git-hooks
   ```

   Bypass deliberately with `git commit --no-verify` or
   `SKIP_ARCH_VIZ_CHECK=1 git commit …`.
3. **CI** — `.github/workflows/architecture-diagram.yml` re-runs `--check` on
   every push to `main` and every PR, because hooks can be uninstalled or
   bypassed. The generator is stdlib-only, so CI needs no install step.

### How it works

- **Two zoom levels**: an overview wiring every `src/systems/<name>` to the
  shared layers (`ragrun`, `tools.search_tool` + its four engines,
  `utils.fetch_doc`, `answer_format`, `make_provider`) and the output artifacts
  — click a system card (or deep-link) to drill into its per-stage pipeline.
  `Esc` / the Back control returns to the overview.
- **Auto-derived, no imports.** It only `ast`-parses source (never imports the
  modules, which would touch env/network). Edges come from each system's
  `from … import …` lines, scanned recursively over the package tree — retrieval
  often lives in a `tools/` subpackage. The four engines and their blurbs are
  read from `ENGINE_INFO` in `tools/search_tool.py`. A system that owns a shared
  symbol gets no self-edge for it.
- **New systems appear for free.** The scaffolded `pipeline.py` includes an
  `ARCH_STAGES = [...]` literal (ordered `{id,label,kind,note}` stages, `kind` ∈
  `llm|no-llm|retrieval|format|artifact|loop`). `gen_arch_viz.py` reads that
  literal; if a package has none, it falls back to a hand-authored
  `STAGE_REGISTRY` keyed by system name in the script (this covers the systems
  that predate the convention). **When you add a system, edit its `ARCH_STAGES`
  to match the real control flow, then regenerate.**

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
