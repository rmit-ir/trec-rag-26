# 2026-07-27 — Interactive architecture visualization for `src/systems/`

## Goal

Follow-up to the `trec-rag-new-system` scaffold skill (see
`worklogs/2026-07-24-facet-rag-system-and-scaffold-skill.md`): the systems layer
was documented only as hand-drawn ASCII diagrams inside each system's
`README.md`, which drift and can't be explored. Add an **interactive**
visualization of the architecture that stays in sync with the source.

## Decisions (chosen by the user)

- **Scope: both levels** — a systems-layer overview that drills into each
  system's per-stage pipeline.
- **Delivery: standalone HTML** — one self-contained file (inline SVG + vanilla
  JS + CSS, no server, no CDN), committed.
- **Data: auto-derived from source** — a generator introspects the tree.

Process note: the user asked for plan → Fable review → default-model execution.
**Fable was unavailable in this environment** (`400 data retention mode
'default' is not available for this model`), so the plan-refinement pass was
done by the default model against the live codebase instead. Plan file:
`tmp/arch-viz-plan.md`.

## Design decisions resolved during the refinement pass

1. **Stage-flow derivation: `ARCH_STAGES` literal + registry fallback.**
   - `gen_arch_viz.py` AST-scans each package for a module-level
     `ARCH_STAGES = [...]` list literal; if found it wins.
   - Otherwise a hand-authored `STAGE_REGISTRY` in the script supplies the flow
     (covers the 5 pre-existing systems — their source was deliberately *not*
     retro-edited).
   - `scaffold_system.py` now emits `ARCH_STAGES` in the generated
     `pipeline.py`, so new systems self-describe and appear for free.
   - **Rejected**: parsing the README ASCII (mixed arrow glyphs `->` / `─>` /
     `→` / `├─` across the three READMEs — too fragile).
2. **Never import the system modules** — pure `ast.parse` on file text. Importing
   would pull in `ragrun`/`tools` and touch env/network.
3. **Output: `docs/architecture.html`.** `docs/` already exists and holds
   architecture docs (`output-trace-schema.md`, `chunking-1pct-findings.md`).
   Not under `data/` (large artifacts only) and not in a `tasks/` code dir —
   CLAUDE.md-clean.
4. **One script, inlined HTML template** (a template-string constant) — no
   separate `.tmpl` file to drift.
5. **Engines are live-read** from `ENGINE_INFO` in `src/tools/search_tool.py`, so
   the engine leaves and their "when to use" blurbs never go stale.
6. **Palette/a11y** per the `dataviz` skill: brand-neutral, `prefers-color-scheme`
   light+dark, edge types carry a legend + hover labels (never color-only),
   deterministic layout (no RNG) so regeneration yields stable diffs.

## What was built

### `skills/trec-rag-new-system/scripts/gen_arch_viz.py` (new)

Derives a model dict then writes the HTML.

- **Nodes**: each `src/systems/<name>` (name, kind, modules, blurb, stages),
  the shared layers (`make_provider`, `answer_format`, `search_tool`,
  `fetch_doc`, `ragrun`, `artifacts`), and the four engines.
- **Edge extraction** — classified from `from X import …` per module, scanned
  **recursively** over the package tree:
  | import | edge |
  | --- | --- |
  | `ragrun` / `ragrun.*` | `artifacts` |
  | `tools.search_tool` | `retrieval` |
  | `utils.fetch_doc` | `fetch-doc` |
  | `ali_deepresearch.answer_format` (foreign) | `answer-format` |
  | `aus_agent.agent` / `.providers` (foreign) | `provider` |
  Same-owner imports are internal → no self-edge (`OWNERS` map), so
  `ali_deepresearch` gets no `answer_format` edge and `aus_agent` no
  `make_provider` edge.
- **Rendering**: overview = left→right layers (systems · shared layers ·
  engines) with bezier edges colored by type; hovering a system card dims all
  other edges; cards are `tabindex`/`role=button` with Enter/Space activation.
  Drill-in = the system's linear stage chain, each stage colored by `kind`
  (`llm|no-llm|retrieval|format|artifact|loop`), with a dashed "repeat until
  answer" loop-back arrow for agent systems. `Esc` / a Back button returns.
- CLI: `--out` (default `docs/architecture.html`), `--print-model`, `--open`,
  `--system NAME`.
- **Deep linking** (added in round 2): the view is driven by the URL fragment via
  a `route()` function + `hashchange` listener, so `docs/architecture.html#facet_rag`
  opens that system's pipeline directly. Card clicks set `location.hash` (so
  browser back/forward work), and `Esc`/Back clears it.

### Stage flows authored for the 5 existing systems

- `facet_rag` (pipeline): PLAN(llm) → EXECUTE(retrieval) → SYNTHESIZE(llm) →
  FORMAT(format) → SAVE(artifact)
- `ali_deepresearch` (agent): ReAct LOOP → THINK(llm) → TOOL_CALL(retrieval) →
  ANSWER(llm) → FORMAT → SAVE
- `aus_agent` (agent): TURN LOOP → SEARCH(retrieval) → STAGE(no-llm) →
  REASON/COMMIT(llm) → FINAL PROSE(llm) → MAP CITES(format) → SAVE
- `o3_deep_research` (single-file): DEEP RESEARCH(llm) → FORMAT → SAVE
- `claude-code-research` (manual): WORKFLOW (no python pipeline package)

### Modified

- `scaffold_system.py` — emits the `ARCH_STAGES` literal in `pipeline.py`; the
  NEXT STEPS checklist gained a step 5 ("edit ARCH_STAGES, regenerate") and the
  worklog step renumbered to 6.
- `SKILL.md` — new **Architecture Visualization** section (what it derives, the
  no-import rule, how to regenerate, the `ARCH_STAGES` convention).

## Verification (exact commands + results)

1. `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --print-model`
   — first run exposed a real bug: `aus_agent` showed only a `ragrun` edge
   despite doing retrieval, because the scan globbed the package **root** only
   and both `aus_agent` and `ali_deepresearch` keep retrieval in a `tools/`
   subpackage (`tools/search.py` → `from tools.search_tool import …`). Fixed by
   switching to `pkg.rglob("*.py")` (skipping `__pycache__`). Final model:

   | system | kind | edges |
   | --- | --- | --- |
   | `ali_deepresearch` | agent | ragrun/artifacts, fetch_doc, search_tool |
   | `aus_agent` | agent | ragrun/artifacts, search_tool |
   | `claude-code-research` | manual | ragrun/artifacts, fetch_doc, search_tool (from `scripts/`) |
   | `facet_rag` | pipeline | search_tool, make_provider, answer_format, ragrun |
   | `o3_deep_research` | single-file | ragrun/artifacts, answer_format |

   engines: `semantic, keyword, ssr, lucene_bool`. **PASS** — ownership
   self-edges correctly absent; facet_rag exercises all five edge types.

2. `python skills/trec-rag-new-system/scripts/gen_arch_viz.py`
   → `wrote docs/architecture.html (5 systems, 14 edges, 4 engines)`, 18.6 KB.
   Re-extracted the embedded `<script id="arch-model">` JSON and re-parsed it:
   systems/shared/engine ids all present; `drawOverview`, `drawSystem`,
   `prefers-color-scheme` all present. **PASS**

3. Opened in a browser (`open docs/architecture.html`) — renders. **PASS**

4. `python -m py_compile` on both skill scripts → **PASS**

5. **`ARCH_STAGES` override, end-to-end**: scaffolded a throwaway
   `python skills/trec-rag-new-system/scripts/scaffold_system.py arch_probe
   --backends none`, then `--print-model` reported
   `arch_probe stages: ['RETRIEVE','GENERATE','FORMAT','SAVE']` and
   `edges: [answer_format/answer-format, ragrun/artifacts, search_tool/retrieval]`
   — a brand-new system self-describes and is auto-wired with zero edits to the
   generator. **PASS**. Probe deleted (`rm -rf src/systems/arch_probe`).

## Round 2 — make it launchable + document the workflow rule

Follow-up ask: *"the visualization should be created and launched anytime a new
system is developed or run; also add commands for existing systems."* That
required a code change as well as docs — there was no way to launch it from the
CLI, and no way to point it at one system.

### Code

- `gen_arch_viz.py` gained `--open` (writes then opens in the default browser via
  `webbrowser.open` on a `file://` URI) and `--system NAME` (implies `--open`,
  deep-links to `#NAME`, validated against the derived model — unknown names exit
  non-zero and list the known ones).
- Renderer: replaced the unconditional `drawOverview()` boot with hash routing
  (`route()` + `hashchange`), so the fragment is the source of truth for which
  view is showing. Card activation now sets `location.hash` instead of calling
  `drawSystem` directly, which makes browser back/forward work.

### Docs

- `SKILL.md` — the section is now **"Architecture Visualization (regenerate +
  launch every time)"**, stating the rule and *why* (the HTML is a committed
  artifact derived from source, so it goes stale silently), with three explicit
  triggers (after scaffolding / after changing wiring or stages / when running a
  system), a Commands block, a copy-paste `--system` line for **each of the five
  existing systems**, and a paired regenerate-then-run example.
- `SKILL.md` frontmatter — `description` now mentions running a system and the
  visualization requirement (otherwise the skill would not be selected for
  "run a system" asks); version `v0.1.0` → `v0.2.0`.
- `scaffold_system.py` — checklist step 5 now prints
  `gen_arch_viz.py --system <name>`; module docstring notes the `ARCH_STAGES`
  literal and the regenerate command.

### Round 2 verification

1. `python -m py_compile skills/trec-rag-new-system/scripts/*.py` → **PASS**
2. `gen_arch_viz.py --system nope` →
   `unknown system 'nope'; known: ali_deepresearch, aus_agent,
   claude-code-research, facet_rag, o3_deep_research`, `exit=1`. **PASS**
3. `gen_arch_viz.py --system facet_rag` → wrote the HTML and printed
   `launched file:///Users/e103037/repos/trec-rag-26/docs/architecture.html#facet_rag`;
   browser opened on the facet_rag pipeline view. **PASS**
4. `grep -c "hashchange\|function route" docs/architecture.html` → `2`. **PASS**
5. **Full scaffold→viz loop**: scaffolded `doc_probe --backends none`; its
   checklist step 5 printed the correct `--system doc_probe` command;
   `--print-model` then listed `doc_probe` among the systems. Deleted the probe
   and regenerated → back to the 5 real systems. **PASS**

## Follow-ups

- Regenerate `docs/architecture.html` whenever a system is added or its wiring
  changes (it is a committed build artifact — a pre-commit hook or CI check
  could enforce freshness).
- `claude-code-research` has no python pipeline package; its card is a `manual`
  placeholder. If it grows a real pipeline, give it `ARCH_STAGES`.
- Consider a one-line pointer to `docs/architecture.html` from AGENTS.md /
  CLAUDE.md so the diagram is discoverable.
