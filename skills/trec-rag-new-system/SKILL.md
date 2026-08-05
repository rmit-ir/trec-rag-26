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

The script writes `src/systems/<name>/{__init__,run,prompts,pipeline}.py` plus a
pytest module at `tests/systems/test_<name>.py`, and prints a checklist for the
steps it deliberately does NOT automate (pyproject dep group, README, worklog).
It refuses to overwrite existing files without `--force`.

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
- `README.md` — design diagram, upstream mapping (if a port), CLI, tests.

Tests do **not** live in the package — they live in the collected suite under
`tests/` (see the Test Harness section below).

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

## Test Harness

All tests live under `tests/`, collected by pytest (config in the root
`pyproject.toml`). Nothing under `src/` is a test file.

Run them through `scripts/test.sh`, which passes the dep groups and fails on a
skip. Two modes — everything, or just what you name:

```bash
bash scripts/test.sh                    # EVERYTHING (~7s) — before every commit
bash scripts/test.sh systems            # one area: contract shared systems dummy-api aus-agent
bash scripts/test.sh tests/systems/test_<name>.py     # or any pytest target / -k expr
bash scripts/test.sh live               # ONLY the live tests (needs creds)
```

**Run the full suite whenever you touch a shared layer** — `src/utils/`,
`src/tools/`, `src/ragrun/` — or any system. All five systems sit on those
layers, so a per-system run cannot clear a change to them. Selective runs print
that reminder. By hand:

```bash
DEP_GROUPS="--group dev --group o3-deep-research --group aus-agent"
uv run $DEP_GROUPS pytest -m 'live or not live'   # offline + live together
```

**Pass all three dep groups.** Two test modules `importorskip` an SDK that lives
in a per-system group (`mcp.server.fastmcp` for `src/mcp`, `boto3` for
`aus_agent`); with `--group dev` alone they *skip*, and the run is green having
proven nothing. The suite is skip-free by design, so `scripts/test.sh` and CI both
fail on any skip. If you add an `importorskip`, add its group to
`scripts/test.sh`, `.github/workflows/tests.yml`, and
`scripts/git-hooks/pre-commit`. (Not `GROUPS` — bash reserves that name for your
numeric group ids and silently ignores assignments to it.)

**Hermetic by default.** Bare `pytest` deselects the `live` marker, and
`tests/conftest.py` enforces the guarantee rather than trusting it:

- `no_network` (autouse) fails any unmarked test that reaches
  `urllib.request.urlopen` or `socket.create_connection`, naming the URL it
  tried. A test that needs retrieval stubs it; a test that wants the real
  endpoint is marked `@pytest.mark.live`.
- `isolated_data_dir` (autouse) repoints `RAGRUN_DATA_DIR` at a tmp dir, so
  `save_run` never writes into the real `data/outputs/` tree.
- `no_ambient_creds` (autouse) strips `SEARCH_API_KEY`, `OPENAI_API_KEY`, the
  AWS vars, etc. for offline tests — otherwise a "hermetic" test can pass on
  your machine only because it silently authenticated somewhere.

**Shared fixtures** (`tests/conftest.py` — read it before writing tests):

| fixture | what it gives you |
| --- | --- |
| `stub_search_tool` | patches `tools.search_tool._DISPATCH` for every engine; returns a `calls` dict so you can assert engine routing and query text. The real serialization / truncation / error-envelope logic stays under test — only the transport is faked. |
| `scripted_provider` | the `ScriptedProvider` class implementing the full `providers.base.Provider` contract. Script it with a list of `ModelTurn`s, or a `responder(pending_text, turn_index)` callable for stage-dependent turns. Records the conversation; raises when the script is exhausted. |
| `fake_hits` / `fake_search_response` | canonical ClimbMix payloads in the exact shapes the spec documents. |
| `read_artifacts(paths)` | loads what a `save_run` wrote → `{trajectory, output, violations}`, with `violations` defaulting to `[]`. |

Module-level helpers: `from conftest import model_turn, tool_call,
CLIMBMIX_DOCIDS`.

**Marker discipline.** Every system should have both: offline tests that prove
the pipeline with stubbed retrieval, and at least one `@pytest.mark.live` test
that keeps the real path exercisable. `--strict-markers` means a typo'd marker
is an error, not a silent no-op. A third marker, `local_socket`, means "real
loopback HTTP to the dummy server, no creds" — those run in CI, so do **not**
mark them `live`.

**Deeper than the stubs: `tests/dummy_api/`.** `stub_search_tool` patches
`_DISPATCH`, which skips the retrieval clients entirely — URL construction, auth
headers, the required `User-Agent`, HTTP verb, request-body shape, and
response→`SearchHit` mapping. `DummyClimbMixAPI` is a local `HTTPServer` speaking
each backend's documented wire format; tests point a client's env var at
`api.base_url`, patch nothing else, and can assert what the client *sent*
(`api.last_request`) as well as what it parsed. Reach for it when you add or
change a client.

**Docstrings are required, and the bar is content.** Every test carries a
docstring that says something its *name* does not: why the behaviour matters, or
what breaks if it regresses. A prose restatement of the name adds lines and no
information. Put the layer-level explanation in the module docstring so the
per-test ones stay short. A test that pins a known `src/` defect is named
`*_current_behaviour` and says so, so a later fix announces itself by failing
rather than passing silently.

**Format conformance** (`tests/contract/`) tests our artifacts against
`skills/trec-rag-2026-track-guidelines/references/{rag,retrieval}-task.md`:
topics-TSV input parsing, ClimbMix document input shapes, the `rag_output`
JSONL object, the strict-vs-rich trajectory split, and the six-column runfile.
Treat those spec files as the source of truth when a test and the code
disagree.

**Enforcement.** `.github/workflows/tests.yml` runs the offline suite on every
PR and push to `main`, and fails the job if any test skipped. The `pre-commit`
hook also runs it when a commit touches `src/`, `tests/`, or `pyproject.toml`
(bypass with `SKIP_TEST_CHECK=1`).

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
  `llm|no-llm|retrieval|format|artifact|loop`). A cyclic system leads with a
  `loop` stage that **declares the repeated span** — `back_to` / `back_from`
  (stage ids) and optional `back_label`; the arrow is never inferred from stage
  position, and a `loop` stage missing `back_from` draws no arrow at all.
  `gen_arch_viz.py` reads that
  literal; if a package has none, it falls back to a hand-authored
  `STAGE_REGISTRY` keyed by system name in the script (this covers the systems
  that predate the convention). **When you add a system, edit its `ARCH_STAGES`
  to match the real control flow, then regenerate.**
- **Per-stage detail (issue #20).** A stage can optionally declare `prompt`
  (list of `<path-relative-to-src>[::CONST]` refs to its prompt template(s)),
  `code` (same ref shape, to the function/class implementing it), `tools`
  (native tool-calling: `[{"name", "ref"}]`), `engines` (facet_rag-style
  engine blurbs: `{"mandatory": ref, "optional": ref}` to a tuple/list
  constant), `tools_note` (one-line why/how), and, on a `loop` stage,
  `parallel_over` (e.g. `"facet"`, when the loop's iterations also run
  concurrently across something, not just sequentially). All refs are
  verified against the actual source at generation time — a renamed or
  removed symbol fails `gen_arch_viz.py` loudly rather than showing stale
  detail. `run` (`llm`/`code`/`llm+code`) is *derived*, not authored: a stage
  is agentic iff it declares `prompt`, code iff it declares `code`. Clicking
  a stage in the drill-in view opens a detail panel showing all of this,
  including tools/engines inherited from its enclosing loop.

## Non-Automated Requirements (do these by hand)

1. **Dep group** in the root `pyproject.toml` `[dependency-groups]` (default
   `uv sync` installs none). Run as `uv run --group <name> python
   src/systems/<name>/run.py …`. Each system gets its own group.
2. **README.md** documenting the design + CLI + tests.
3. **Fill in the generated test** at `tests/systems/test_<name>.py` — the
   scaffold leaves a TODO for the scripted provider. An unfilled scaffold test
   proves nothing; the offline test must actually drive your pipeline.
4. **Worklog** `worklogs/YYYY-MM-DD-<name>.md`, committed with the code.

## Credentials

Retrieval needs the repo `.env` (see `.env.example`): `SEARCH_API_KEY`
(dense+sparse), `PYSERINI_API_TOKEN` (keyword/Pyserini). LLM backends need
their own keys (`AWS_*` / `BEDROCK_*` for Bedrock, `OPENAI_API_KEY` /
`OPENAI_MODEL_ID` for OpenAI). Never print or commit tokens.

None of these are needed to run the offline test suite — that is the point of
the hermeticism guards above. They are needed only for `pytest -m live` and for
real runs.

## Reference Implementations

- `src/systems/facet_rag` — plan-then-execute, pluggable backends, all four
  engines. The cleanest end-to-end example of these conventions.
- `src/systems/ali_deepresearch` — ReAct agent port; `answer_format` lives here.
- `src/systems/aus_agent` — staged-context agent; the pluggable `providers/`.
- `src/systems/o3_deep_research` — minimal single-file runner (hosted DR + MCP).

For track/submission format details use the `trec-rag-2026-track-guidelines`
skill; for hosted retrieval use `pyserini-rest-api`.
