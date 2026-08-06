# 2026-08-06 — extract `agent_harness`: stop facets_agent/facet_rag importing from aus_agent

## Why

Asking about a missing `facets_agent` → `tools.search_tool` edge in
`docs/architecture.html` surfaced the real cause: `facets_agent` and
`facet_rag` were importing directly from `src/systems/aus_agent/` — one RAG
system reaching into another system's package to reuse its agent loop, tool
builders, and provider factory. The user called this out as bad practice:
every other cross-system-reusable thing in this repo (`ragrun`, `tools`,
`utils`) lives in a real shared top-level package, not inside one system's
directory. This session promotes the same pattern for the agent-loop harness.

## What moved

New top-level package `src/agent_harness/`, sibling to `ragrun`/`tools`/`utils`,
added to `pyproject.toml`'s `[tool.hatch.build.targets.wheel]` packages list so
it installs editable like the others:

- `agent.py` — `run_agent` (the ~1,300-line staged-context tool-calling loop),
  `make_provider`, `_execute_tool_calls`, `_map_citations`, citation-parsing
  regexes, budget/turn-stat helpers, `TASK_PROMPT`, `now_full`,
  `DEFAULT_ENGINES`, `DEFAULT_CONTEXT_TOKEN_BUDGET`,
  `PARTIAL_SAVE_MIN_INTERVAL_S`, `DEFAULT_SAFETY_MAX_ROUNDS`,
  `FINISHING_ROUNDS_GRACE`, `DEFAULT_MAX_COMMITTED_PER_STEP` — all of it
  already generic and parameterized (`run_agent`'s own docstring already
  called itself "the shared staged-context harness" before this move).
- `context.py` — `ContextLedger`, verbatim.
- `providers/` — `base.py`, `bedrock.py`, `openai.py`, verbatim.
- `tools/` — `commit_context.py`, `get_documents.py`, `search.py`, verbatim.

`src/systems/aus_agent/agent.py` shrank to what's genuinely aus_agent-specific:
`SYSTEM_PROMPTS_DIR`, `DEFAULT_PROMPT_VARIANT`, `MAX_COMMITTED_PLACEHOLDER`,
and `load_system_prompt()` (loads `prompts/system/*.md`), re-importing
`run_agent`/`make_provider`/etc. from `agent_harness.agent` for its own use.

## One real behavior change: `system_prompt` is now required

`run_agent` used to fall back to `load_system_prompt(max_committed_per_step,
prompt_variant)` internally when a caller omitted `system_prompt` — i.e. the
"shared harness" quietly reached back into aus_agent's own prompt-file loader
as a default. That's exactly the kind of hidden coupling this move was
supposed to remove, so it's gone: `system_prompt: str` is now a required
keyword-only argument. `aus_agent/run.py` now resolves
`load_system_prompt(...)` itself before calling `run_agent(...,
system_prompt=system_prompt)`. facets_agent was unaffected — it already always
built and passed its own `system_prompt`.

## Naming collision caught mid-move

The plan called for renaming `tests/aus_agent_context/` to
`tests/agent_harness/` to match the new package name. That would have shadow-
collided with the real `src/agent_harness/` package: pytest's `pythonpath =
["src", "src/systems", "tests"]` puts both `src/` and `tests/` on the import
path, so a bare `import agent_harness` would resolve to whichever came first
(src), silently breaking `tests/agent_harness/`'s own `fakes.py` sibling
import. Renamed to `tests/agent_harness_context/` instead (same
`<subject>_context` pattern as the old name) — no collision.

## The `make_provider`-monkeypatch trap (same bug in 4 places)

Several tests did `monkeypatch.setattr(aus_agent_mod, "make_provider", ...)`
where `aus_agent_mod = aus_agent.agent`. That patches the NAME in
`aus_agent.agent`'s namespace — but `run_agent` (now defined in
`agent_harness/agent.py`) resolves its own bare `make_provider(...)` call
against `agent_harness.agent`'s module globals, not whatever module re-exports
the function. Patching the wrong module silently no-ops the patch and the test
would try to hit a real backend. Found and fixed the same pattern in:

- `tests/systems/test_aus_agent.py` (`make_provider`)
- `tests/agent_harness_context/test_incremental_save.py` (`make_provider`,
  `PARTIAL_SAVE_MIN_INTERVAL_S` — same closure-globals issue)
- `tests/agent_harness_context/conftest.py`'s `run_agent_capture` fixture
  (`make_provider`, `save_run`)
- `tests/agent_harness_context/test_agent_context_integration.py`
  (`execute_get_documents`)
- `tests/systems/test_facets_agent.py` (`make_provider`)

All now patch `agent_harness.agent` (or `agent_harness.<submodule>`) directly.
`tests/agent_harness_context/test_budget_and_prompt.py` needed two aliases
side by side (`agent` = `aus_agent.agent` for `load_system_prompt`/
`SYSTEM_PROMPTS_DIR`/`MAX_COMMITTED_PLACEHOLDER`; `harness_agent` =
`agent_harness.agent` for `DEFAULT_CONTEXT_TOKEN_BUDGET`/
`_budget_status_line`/`_usage_token_stats`/`_parse_final_prose`/`_word_count`)
since that one file's tests genuinely span both modules.

Every direct `run_agent(...)` call site not already passing `system_prompt`
(the `_drive`/`run_to_disk`/`run_agent_capture` fixtures, one inline call in
`test_aus_agent.py`) got a trivial literal `system_prompt=` — none of those
tests assert on prompt content, so a placeholder string is correct and keeps
the fixture decoupled from aus_agent's prompt files (`load_system_prompt` was
used instead in `test_aus_agent.py`'s `_drive`, matching that file's explicit
framing as testing aus_agent's real path).

## Diagram (`gen_arch_viz.py` / `docs/architecture.html`)

- `_edges_for_system`'s AST-level classifier only sees the imported *module*
  string, not which names were imported — so `agent_harness.agent` can't be
  told apart between "wants the whole loop" (facets_agent, aus_agent) and
  "wants just `make_provider`" (facet_rag) at that granularity. This was
  already true before the move (both cases collapsed to one `aus_agent.agent`
  → `make_provider` edge) — kept the same precision level rather than
  inventing edge granularity the AST pass can't actually back up: collapsed
  to one `agent_harness` shared node/edge covering the whole package
  (loop + providers + tools), dropped the separate `make_provider` node.
- Dropped `"make_provider": "aus_agent"` from `OWNERS` — that dict exists to
  suppress a self-import edge for a symbol still physically hosted inside one
  system's package (like `answer_format` in `ali_deepresearch`, untouched,
  out of scope). `agent_harness` isn't owned by any system, so every importer
  — aus_agent included — now draws a genuine edge, no suppression needed.
- Added a `harness` edge type/color (rose: `#be185d` light / `#f472b6` dark)
  and legend entry; removed the now-unused `provider` edge type (the
  `--e-provider` CSS var stays — still used for the drill-in view's `.k-llm`
  stage color, unrelated to this edge).
- `STAGE_REGISTRY["aus_agent"]`'s hand-authored `code`/`tools`/`prompt` path
  strings updated from `systems/aus_agent/...` to `agent_harness/...`
  wherever the code actually moved (prompt file paths under
  `systems/aus_agent/prompts/system/` are unchanged — those stayed put).
- facets_agent's own `ARCH_STAGES` literal (in `src/systems/facets_agent/agent.py`)
  got the same path updates, plus its docstrings.

Regenerated with `python skills/trec-rag-new-system/scripts/gen_arch_viz.py`;
`--check` passes. Result — `facets_agent`'s overview edges went from
`['make_provider', 'ragrun']` to `['agent_harness', 'ragrun']`; `aus_agent`
from `['ragrun']` (previously suppressed by the `OWNERS` self-import guard) to
`['agent_harness', 'ragrun']`; `facet_rag` gained `'agent_harness'` alongside
its existing `search_tool`/`answer_format`/`ragrun`.

## Docs touched (current/prescriptive, not historical)

- `skills/trec-rag-new-system/SKILL.md` — the "reuse the aus_agent agent-loop
  harness directly" section rewritten for `agent_harness`; documented
  `system_prompt` now being required; removed the import-surgery-trap
  paragraph for this specific case (no longer applies — `agent_harness`
  resolves via editable install like `ragrun`/`tools`/`utils`, so it can't be
  loaded twice under different names the way a second `src/systems/<name>/`
  package could).
- `src/systems/facets_agent/README.md`, `src/systems/facet_rag/README.md` and
  `__init__.py`, `src/systems/aus_agent/README.md` (one-paragraph note),
  `src/utils/http_retry.py` — updated code-location claims
  (`aus_agent.context`/`.tools`/`.providers` → `agent_harness.*`); left prose
  comparisons to aus_agent-the-system (its prompt length, its own output
  tree, etc.) unchanged since those are still accurate.
- `worklogs/*.md` and `src/systems/facets_agent/PLAN.md` — NOT touched
  (historical, describe the state at the time they were written).

## Verification

- `bash scripts/test.sh` — 1594 passed, 8 deselected (live-marked), 0 skips,
  0 failures.
- `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check` passes.
- `grep -rn "from aus_agent" src/systems/facets_agent/ src/systems/facet_rag/`
  — empty.
- Manual check of the regenerated `docs/architecture.html`'s embedded model
  (`arch-model` JSON) confirmed the edge lists above.

## Explicitly out of scope

- `ali_deepresearch.answer_format` / `OWNERS["answer_format"]` — same category
  of issue (`o3_deep_research` reuses another system's module) but not what
  was asked.
- Renaming the `--group aus-agent` uv dependency group or the `aus-agent`
  shorthand keyword in `scripts/test.sh` — only the directory it points at
  moved (`tests/agent_harness_context`); the group name is still accurate
  (boto3, needed for the Bedrock provider now in `agent_harness`).
