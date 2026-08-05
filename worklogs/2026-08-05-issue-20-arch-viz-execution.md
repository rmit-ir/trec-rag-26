# Execution — issue #20 (arch-viz: detail panel, agentic/code split, loop grouping)

Implements the plan in `worklogs/2026-08-05-issue-20-arch-viz-plan.md` on
branch `feat/arch-viz-detail-panel-issue-20`.

## What changed

`skills/trec-rag-new-system/scripts/gen_arch_viz.py`:

- **Ref resolvers** (`_split_ref`, `_module_value_soft`/`_module_value`,
  `_symbol_exists`, `_code_ref`, `_prompt_text`) — AST-only, no imports,
  matching the file's existing "never import the modules" constraint. Every
  `prompt`/`code`/`tools`/`engines` ref declared in `STAGE_REGISTRY` is
  verified against real source at generation time; a rename/removal raises
  `SystemExit` instead of showing stale detail.
- **New optional `STAGE_REGISTRY` keys**: `prompt`, `code`, `tools`,
  `engines`, `tools_note`, `parallel_over`. Filled in for all stages across
  `facet_rag`, `aus_agent`, `ali_deepresearch`, `o3_deep_research` with real
  refs (verified to resolve — see the plan's per-system tables for the exact
  values, corrected in a few places from the plan's draft where the real
  symbol name differed, e.g. `aus_agent.agent::run_agent` not `run_one`,
  `ReactAgent` not `ReActAgent`).
- **`build_model()`** normalizes those keys via `_normalize_stage`: prompt
  text is deduped into a top-level `model["prompts"]` dict (refs, not
  inlined text, stay on the stage); `tools`/`engines` merge into one
  `stage["tools"]` list of `{name, ref, desc, group}`; `stage["run"]` is
  derived (`llm`/`code`/`llm+code`) from whether `prompt`/`code` are present
  — never hand-authored, so the badge and the detail panel can't disagree.
- **`_arch_stages_override`** no longer stringifies every field
  (`{k: str(v) ...}`) — a scaffolded system's `ARCH_STAGES` can now declare
  the same list/dict-valued keys as `STAGE_REGISTRY` without corruption.
- **JS/CSS**: run-class badge on each stage box (`.runbadge`, independent of
  the existing per-kind fill color); a click-to-open `#detail` side panel
  (`showDetail`) showing note/prompt-text/code-refs/tools, including tools
  inherited from a stage's enclosing loop (`findEnclosingLoop`); a labeled
  dashed bounding rect around a loop's `back_to..back_from` span replacing
  the old standalone loop marker box, with a 3-layer ghost stack when
  `parallel_over` is set; the back-edge arrow moved below the row so it
  doesn't collide with the rect's label; `Escape` closes the panel before
  falling back to the existing overview-navigation behavior; drill-in legend
  now explains `LLM`/`CODE`/`LLM+CODE` and the loop/concurrency markers.

`tests/arch_viz/` (new): `conftest.py` (sys.path wiring for the
non-`src/` generator script, mirroring `tests/bm25_tune/conftest.py`) +
`test_gen_arch_viz.py`, 11 tests mapping each of the issue's test cases to an
in-memory assertion on `build_model()`/`render_html()` (no browser harness in
this repo). Needs no new dep group — the generator is stdlib-only.

`skills/trec-rag-new-system/SKILL.md` and `scripts/scaffold_system.py` —
documented the new optional `ARCH_STAGES` fields so a scaffolded system can
opt in.

`docs/architecture.html` — regenerated (`--check` passes).

## Decisions carried from the plan (see the plan doc for full justification)

1. **Agentic/code split is derived, not hand-authored.** A stage is `llm` iff
   it declares `prompt`, `code` iff it declares `code`, `llm+code` if both.
   This makes `FORMAT` come out `llm+code` for facet_rag and
   ali_deepresearch — a deliberate deviation from the issue's literal test
   case 2 expectation (`FORMAT` as code-only), because `format_answer` really
   does call `FORMAT_ANSWER_PROMPT` when `format_llm=True`, which is
   facet_rag's default (`pipeline.py::run_one`, `format_llm: bool = True`).
   Verified live in the browser: facet_rag's FORMAT box shows `LLM+CODE`.
2. **Concurrency is drawn as depth, not a second arrow.** `facet_loop`
   declares `parallel_over: "facet"`; its bounding rect gets two ghost copies
   behind it and the label reads `FACET LOOP × facet (concurrent)`.
   `aus_agent`'s `TURN LOOP` and `ali_deepresearch`'s `ReAct LOOP` get a flat
   rect, no ghosts — confirmed by comparison in the browser.

## Verification

- `bash scripts/test.sh tests/arch_viz` — 11/11 pass.
- `bash scripts/test.sh` (full suite) — 1534 passed, 0 skipped, 0 failed.
- **Manual browser pass** (claude-in-chrome, served the regenerated HTML over
  a scratch `python -m http.server` since the extension can't navigate to
  `file://`): confirmed live —
  - `#facet_rag`: `FACET LOOP` rect encloses exactly SEARCH/ANALYZE/CURATE,
    label reads `FACET LOOP × facet (concurrent)`, ghost stack visible at
    zoom; clicking CURATE shows the real `CURATOR_PROMPT` text including
    "MOST to LEAST useful"; clicking SEARCH shows all 5 engines split
    `mandatory engine`/`optional engine` with real blurbs.
  - `#aus_agent`: `TURN LOOP` rect (flat, no ghosts) encloses
    SEARCH/STAGE/REASON-COMMIT; SEARCH's panel shows "available in TURN
    LOOP:" with `search`/`get_documents`/`commit_context`, `search`'s schema
    correctly flagged "built at runtime" (it's a function call, not a
    literal) while the other two show their real descriptions.
  - `#ali_deepresearch`: `ReAct LOOP` rect encloses THINK/TOOL_CALL — the
    grouping generalizes across all three loop-shaped systems as required.
  - `#claude-code-research` (no `ARCH_STAGES`/`STAGE_REGISTRY` detail at
    all): panel opens gracefully with just note + kind, no crash.
  - Overview page unaffected; `Escape` closes the panel on first press,
    falls back to overview navigation on a second press.

Run: `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open` to
re-view; `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check`
to confirm freshness.
