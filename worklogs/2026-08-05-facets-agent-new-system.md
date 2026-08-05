# 2026-08-05 — facets_agent: new system, generalized the aus_agent harness

**Branch:** `facets_agent`. Designed and built a new system per the user's
request: an agentic system on `gpt-5.6-luna`, structurally like `aus_agent`
(one continuous tool-calling agent, not a scripted multi-role pipeline), but
with a minimal system prompt inspired by `facet_rag`'s process, all five
retrieval engines available, `hybrid` configured for HyDE-style queries with a
wider result count, and a document-fetch tool.

## What got built

- `src/systems/facets_agent/` — new package: `prompts.py` (the minimal
  prompt), `agent.py` (thin config over the shared harness + `ARCH_STAGES`),
  `run.py` (CLI), `README.md`.
- `tests/systems/test_facets_agent.py` — offline suite proving this system's
  own configuration reaches the shared harness correctly.
- `pyproject.toml` — new `facets-agent` dep group (same two SDKs as
  `aus-agent`/`facet-rag`: reuses `aus_agent.providers`).
- `docs/architecture.html` — regenerated; facets_agent now appears as a sixth
  system, with an entry in `SYSTEM_KIND`/`SYSTEM_BLURB`
  (`skills/trec-rag-new-system/scripts/gen_arch_viz.py`).

## The key design decision: generalize aus_agent.agent.run_agent, don't fork it

`aus_agent/agent.py`'s `run_agent` (~1,300 lines) is the staged/committed
evidence state machine, budget tracking, and final-report citation parser —
none of that is prompt-specific, all of it is exactly what a second
continuous tool-calling agent needs too. Forking it would have meant
duplicating ~1,300 lines of logic that has already been debugged through
several rounds (see `worklogs/2026-07-18-commit-cap-bump.md` and others) —
and, worse, silently diverging from it over time.

Instead `run_agent` gained three optional parameters, all defaulting to
`aus_agent`'s exact previous behavior (its own test suite — 291 cases in
`tests/systems/` — passes unchanged):

- `system_name: str = "aus_agent"` — threaded into all three `save_run(...)`
  call sites (was a hardcoded `"aus_agent"` literal) and into the default
  `run_desc` text, so a second caller's artifacts land in their own
  `data/outputs/<system_name>/` tree.
- `system_prompt: str | None = None` — when given, used verbatim instead of
  `load_system_prompt(max_committed_per_step, prompt_variant)`, so a caller
  doesn't need a file under `aus_agent/prompts/system/`.
- `default_k_by_engine: dict[str, int] | None = None` — threaded through
  `_execute_tool_calls` so a named engine's default `k` (when the model's
  call omits it) can differ from the run's general `k`. This is what lets
  `facets_agent` guarantee `hybrid` gets more results even if the model
  forgets to ask for them.

`src/systems/facets_agent/agent.py` is ~50 lines: it renders
`prompts.SYSTEM_PROMPT`, sets `engines=["semantic","keyword","hybrid","ssr",
"lucene_bool"]` (all five — "make all the tools available") and
`default_k_by_engine={"hybrid": 15}`, and calls straight into
`aus_agent.agent.run_agent`. `get_documents` and `commit_context` are already
unconditionally wired into `run_agent`'s tool list, so the "fetch documents"
requirement needed no new code.

## The prompt

`aus_agent/prompts/system/default.md` is ~270 lines, tuned over many passes.
`facets_agent/prompts.py::SYSTEM_PROMPT` is ~50 lines, stating a five-stage
process once each (decompose into facets; search each facet across
semantic/keyword/HyDE-hybrid, reaching for ssr/lucene_bool only when Boolean
precision is actually needed; curate distinct contributions over duplicates;
iterate until a facet is covered; self-check citations before finalizing) plus
the tool/citation mechanics the harness's parser requires (one sentence per
line, `[id]` markers, `commit_context` on the very next turn). It deliberately
does not re-explain aus_agent's edge-case handling (multiple commit_context
calls, no-op commits, Markdown repair, etc.) — that's harness code, not prompt
text, and stays correct regardless of what the prompt says.

## A real import-surgery bug this caught

`aus_agent/run.py` and `facet_rag/run.py` use two DIFFERENT sys.path
conventions that happen to each be self-consistent in isolation:
`aus_agent/run.py` puts `src/` on the path and imports via
`systems.aus_agent.agent` (dotted); `facet_rag/run.py` puts `src/systems/` on
the path and imports `aus_agent.agent` bare. `facets_agent/agent.py` needed a
bare `from aus_agent.agent import ...` (to match how the test suite's
`pythonpath` resolves it — tests do `from aus_agent import agent as
agent_mod` and monkeypatch that bare module), so copying aus_agent/run.py's
header verbatim broke with `ModuleNotFoundError: No module named 'aus_agent'`.
Fixed by using facet_rag/run.py's convention instead (`src/systems/` on the
path, bare imports throughout) — worth remembering if a third system reuses
`aus_agent.agent`: the two existing `run.py`s are not interchangeable
templates, and mixing them in one process would load `aus_agent.agent` twice
under different names, silently defeating any monkeypatch-based test.

## Skill gap flagged, not yet fixed

`skills/trec-rag-new-system/scripts/scaffold_system.py` only templates the
"retrieve → generate → format" single-shot pattern; it has no template for
the continuous tool-calling agent-loop pattern (`aus_agent`, now also
`facets_agent`). Per the user, `SKILL.md` should be updated to document the
`aus_agent.agent.run_agent(system_name=..., system_prompt=..., ...)` reuse
path demonstrated here as the way a new agent-loop system should be built —
tracked as follow-up, not done in this session.

## Update: ssr/lucene_bool removed

Per follow-up feedback, `ssr`/`lucene_bool` are no longer supported and were
dropped from `facets_agent` entirely (`DEFAULT_ENGINES` is now exactly
`semantic, keyword, hybrid`; `OPTIONAL_ENGINES` removed; the prompt's
Boolean-engine sentence removed; `ARCH_STAGES`'s `engines` block drops its
`optional` key). This also brings the system back in line with the original
ask ("especially the three search tools, semantic, keyword, hybrid"). The
shared `tools.search_tool.ENGINE_INFO` still lists all five — this change is
scoped to what `facets_agent` offers, not a repo-wide deprecation.

## Verification

- `bash scripts/test.sh` — 1570 passed, 1 pre-existing unrelated failure
  (`tests/bm25_tune/test_prompts.py` needs `evaluation-results/` data not
  present on this machine — confirmed pre-existing via `git stash`).
- `bash scripts/test.sh systems` — 291 passed (all five systems, unaffected
  by the `aus_agent/agent.py` generalization).
- `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check` — clean
  after regenerating.
- `uv sync --group facets-agent` and `uv run --group facets-agent python
  src/systems/facets_agent/run.py --help` — both succeed.
