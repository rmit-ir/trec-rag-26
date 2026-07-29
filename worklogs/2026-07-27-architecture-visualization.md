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
- **Loop-back arrow fix** (PR #1 review, @rankun203): the arrow's span was
  inferred from array position — tail at `stages.length - 2`, head at stage 1.
  That is only ever right by accident. For `aus_agent` it drew the tail on
  `MAP CITES` and for `ali_deepresearch` on `FORMAT`, i.e. it claimed the cycle
  repeats one-shot formatting steps, and (Kun's point) it did not start from
  `REASON/COMMIT`, which is the turn that actually decides search-again vs
  write-the-report. The span is now **declared** on the `loop` stage
  (`back_to` / `back_from` stage ids + optional `back_label`), so it is checked
  against real control flow rather than guessed:

  | system | loop span (fixed) | runs once, after the loop | old buggy span |
  | --- | --- | --- | --- |
  | `aus_agent` | `SEARCH → STAGE → REASON/COMMIT` | `FINAL PROSE`, `MAP CITES`, `SAVE` | `SEARCH … MAP CITES` |
  | `ali_deepresearch` | `THINK → TOOL_CALL` | `ANSWER`, `FORMAT`, `SAVE` | `THINK … FORMAT` |

  Verified against the sources: `aus_agent/agent.py`'s single `while True:` turn
  loop breaks once `_parse_final_prose` accepts a report, and
  `ali_deepresearch/react_agent.py`'s `while calls_left > 0:` breaks on
  `<answer>`. Unknown/missing `back_from` now draws **no** arrow — a wrong arrow
  is worse than a missing one. Labels are per-system too
  (`repeat until report` / `repeat until <answer>`).
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

## Round 3 — enforce the rule (hooks + CI)

Follow-up ask: *"Yes, add it to be enforced."* Round 2's rule was documented
convention only. Enforcement needs a freshness *check*, then layers that run it.

### `--check` and the determinism bug it exposed

Added `gen_arch_viz.py --check`: re-renders in memory, compares to the file on
disk, exits 1 with the fix command if stale/missing (writes nothing).

First run of `--check` reported **stale on a file generated seconds earlier**.
Root cause: `_imported_modules()` returns a `set`, and edge order came from set
iteration — which varies between processes under string hash randomization. So
the HTML was **not byte-deterministic**, contradicting the round-1 claim of
"deterministic layout / stable diffs" (that claim only covered *coordinates*, not
edge ordering). Without this fix `--check` would have been useless and every
regeneration a noisy diff.

Fix: `sorted()` on both the file list and the module set in `_edges_for_system`.
Verified by generating 5 times and comparing hashes → **1 distinct sha**.

That test also surfaced a second bug: the documented `--out /tmp/arch.html` usage
crashed with `ValueError: '/tmp/det1.html' is not in the subpath of …` from
`Path.relative_to` in the success message. Added a `_rel()` helper that falls
back to the absolute path. Now works, and is covered by the determinism test
(which writes to `/tmp`).

### Layer 1 — Claude Code hooks (`.claude/settings.json`, new file)

`scripts/hooks/arch_viz_refresh.sh`:
- **`PostToolUse` (`Edit|Write|MultiEdit`)** — parses the event's `file_path` and
  returns immediately unless it is under `src/systems/` or is `gen_arch_viz.py`;
  otherwise regenerates silently (stderr/stdout suppressed so a mid-edit broken
  tree can't spam the session).
- **`Stop --verify`** — last-word check: if stale, tries once to regenerate, and
  only if that still fails exits 2 with instructions (exit 2 feeds stderr back to
  the model as a blocking reason).

### Layer 2 — git pre-commit hook

`scripts/git-hooks/pre-commit` + `scripts/git-hooks/install.sh`.
- Fires **only** when the commit touches `src/systems/`, `gen_arch_viz.py`, or
  `docs/architecture.html`.
- Checks the **staged tree**, not the working tree: it materializes the index
  into a temp dir via `git checkout-index --all --prefix=` and runs `--check`
  there, so a stale-in-index/fixed-in-worktree state cannot slip through.
- Installed via `core.hooksPath=scripts/git-hooks` (not copying into
  `.git/hooks`), so the hook stays version-controlled and edits take effect with
  no re-install. **Git hooks aren't cloned**, hence the installer + the new
  AGENTS.md section.
- Bypass: `git commit --no-verify` or `SKIP_ARCH_VIZ_CHECK=1`.

### Layer 3 — CI backstop

`.github/workflows/architecture-diagram.yml` (first workflow in this repo) runs
`--check` on pushes to `main` and all PRs, since hooks can be uninstalled or
bypassed. No install step — the generator is stdlib-only (verified with
`python3 -I`).

### Docs

- `SKILL.md` — new **Enforcement (three layers)** subsection (the `--check`
  command, what each layer does, the once-per-clone installer, the bypasses); the
  rule statement now ends "This rule is **enforced**, not just documented".
- `AGENTS.md` (note: `CLAUDE.md` is a symlink → `AGENTS.md`; edit the target) —
  new **Git Hooks (run once per clone)** section and a **RAG Systems
  (`src/systems/`)** pointer to the skill + `docs/architecture.html`, which
  closes the round-1 follow-up about discoverability.

### Round 3 verification

Determinism / CLI:
1. 5× generate to `/tmp` → **1 distinct sha**. `--out` outside the repo no longer
   crashes. **PASS**
2. `--check` on a fresh file → `up to date`, exit 0. **PASS**
3. `python3 -I … --check` (isolated mode, no site-packages) → exit 0, confirming
   stdlib-only for CI. **PASS**

Git hook — run in a **throwaway clone** (`git clone --no-hardlinks` into a
tempdir) so no test could touch the real tree:
| test | expected | result |
| --- | --- | --- |
| commit an unrelated file | hook no-ops | PASS (exit 0) |
| stage a new system, diagram stale | **blocked** | PASS (rejected + fix message) |
| regenerate + `git add`, recommit | accepted | PASS |
| `git commit --no-verify` | bypassed | PASS |
| `SKIP_ARCH_VIZ_CHECK=1 git commit` | bypassed | PASS |

Claude Code hook (piping synthetic JSON events on stdin):
| test | expected | result |
| --- | --- | --- |
| `file_path` = `README.md` | no-op | PASS (exit 0) |
| `file_path` = `src/systems/facet_rag/pipeline.py` | regenerates | PASS |
| `--verify` when fresh | exit 0 | PASS |
| `--verify` after `echo STALE > docs/architecture.html` | self-heals | PASS (exit 0, `--check` clean after) |

CI: workflow YAML parsed with `pyyaml` — `on: {push: {branches:[main]},
pull_request: None}`, job `check-freshness`, 3 steps. **PASS**

### Process mistake worth recording

My first attempt at the git-hook tests ran against the **real working tree** and
used `git reset --hard` for cleanup. That destroyed the uncommitted round-3 edits
to `gen_arch_viz.py` (`--check`, the determinism fix, `_rel()`) — rounds 1–2 were
already committed (`7a12ab3`, `1c85b5a`) and so survived. I re-applied the three
edits and re-ran everything in a disposable clone instead. **Lesson: never test a
commit-blocking hook in the live worktree; clone first.**

## Round 4 — document the manual `.claude/settings.json` step

`.claude/` is gitignored in this repo (`.gitignore:32`, grouped with the editor
dirs `.vscode/` / `.idea/`), so the file that wires up enforcement layer 1 could
not ship with commit `e97262a`. That layer silently did not exist in any other
clone. Rather than loosen the ignore rule (it affects more than this feature —
that is the user's call), made the step explicit and copy-pasteable:

- **`scripts/hooks/claude-settings.example.json`** (new, tracked) — the exact
  config, with a `_comment` array carrying the recreate instructions inside the
  file itself. Claude Code ignores unknown top-level keys, so the comment is
  harmless if left in place. Says to **merge** the `hooks` block if a
  `settings.json` already exists, rather than overwrite.
- **`SKILL.md`** — enforcement layer 1 now states that `.claude/` is gitignored,
  gives the `mkdir -p .claude && cp …` recreate commands, the restart/`/hooks`
  note, a one-line verify (`echo '{}' | scripts/hooks/arch_viz_refresh.sh
  --verify`), and what is lost without it (in-session auto-regeneration only —
  layers 2 and 3 still enforce).
- **`AGENTS.md`** — the *Git Hooks* section became **"Per-Clone Setup (two manual
  steps — nothing else is automatic)"** listing both `install.sh` and the
  settings copy, since they are the same class of un-committable setup.
- **`scripts/git-hooks/install.sh`** — prints a NOTE pointing at the template
  when `.claude/settings.json` is absent, so step 2 is discovered while doing
  step 1.

### Round 4 verification

1. Template's `hooks` block vs. the live `.claude/settings.json` (after dropping
   `_comment`) → `True` (byte-equal after JSON parse), so the docs cannot drift
   from the config that was actually tested in round 3. **PASS**
2. `git check-ignore scripts/hooks/claude-settings.example.json` → not ignored,
   so the template really is committable. **PASS**
3. Installer with `.claude/settings.json` present → no NOTE; with it moved away →
   NOTE printed. Live file restored afterwards. **PASS**
4. Documented recreate path (`cp` template → strip `_comment`) reproduces the
   live config exactly; documented verify command
   (`echo '{}' | scripts/hooks/arch_viz_refresh.sh --verify`) → `hook OK`. **PASS**

## Follow-ups

- ~~Regenerate the diagram whenever a system changes; a pre-commit hook or CI
  check could enforce freshness.~~ **Done in round 3** (Claude Code hooks + git
  pre-commit + CI).
- ~~Pointer to the diagram from AGENTS.md/CLAUDE.md for discoverability.~~
  **Done in round 3** (new *RAG Systems* + *Git Hooks* sections in `AGENTS.md`).
- **Every clone must run the two per-clone setup steps** (`bash
  scripts/git-hooks/install.sh`, then copy
  `scripts/hooks/claude-settings.example.json` → `.claude/settings.json`) —
  otherwise only the CI layer protects that checkout. Documented in `AGENTS.md`
  → *Per-Clone Setup*.
- **Open decision:** `.claude/settings.json` stays un-committable while `.claude/`
  is gitignored. If the team would rather share it, un-ignore that one path
  (`!.claude/settings.json`, keeping `settings.local.json` ignored) and delete the
  manual step — that loosens an ignore rule affecting more than this feature, so
  it was left to the user.
- `claude-code-research` has no python pipeline package; its card is a `manual`
  placeholder. If it grows a real pipeline, give it `ARCH_STAGES`.
- The `Stop` hook regenerates `docs/architecture.html` as a side effect, so a
  session that only *reads* systems code can still leave the file modified if it
  was stale on entry. That is intentional (it self-heals), but it means a dirty
  working tree may appear without an explicit edit.

## Round 5 — fix drill-in clipping on narrow viewports (PR #1 review)

A reviewer screenshot of the `aus_agent` drill-in showed the last pipeline
stage (SAVE) clipped at the right edge. Root cause: `drawSystem()` laid out
against `W = svg.clientWidth` with fixed box/gap sizes (`bw=150, gap=34`) and
`x0 = max(40, (W - totalW)/2)`, so a 7-stage pipeline needs
`totalW = 7*150 + 6*34 = 1254` px plus margins (~1334) — wider than the
reviewer's ~1250 px viewport, and there was no scale-down or scroll.

### Fix (`skills/trec-rag-new-system/scripts/gen_arch_viz.py`, drawSystem)

Compute `needW = totalW + 80`; when `needW > clientWidth`, set
`viewBox="0 0 <needW> <H>"` on the svg (default `preserveAspectRatio`
letterboxes, keeping aspect) and lay out against `needW`, so the whole row
scales down to fit instead of clipping. When it fits, remove any viewBox.
Because overview and drill-in reuse the **same** `<svg>` element and
`clear(svg)` only removes children (not attributes), `drawOverview()` also
removes a lingering `viewBox` so a wide drill-in can't distort the overview
after Back.

Overview sanity check at ~1250 px: rightmost content is the engine boxes at
`colGap*3.85 + 150 = W*0.77 + 150` → 1112.5 px at W=1250 — proportional
layout, no clipping, no change needed.

### Verification (exact commands + results)

```bash
python3 skills/trec-rag-new-system/scripts/gen_arch_viz.py
# wrote docs/architecture.html (5 systems, 14 edges, 4 engines)
python3 skills/trec-rag-new-system/scripts/gen_arch_viz.py --check
# docs/architecture.html is up to date (5 systems)   (exit 0)
```

Headless-browser check at the reviewer's width (playwright chromium
headless-shell, viewport 1250x700; conda-forge libs via
`LD_LIBRARY_PATH=/tmp/pw-libs/lib` since the EL8 host lacks libatk et al.).
Probe script: `worklogs/assets/2026-07-28-arch-viz-viewbox-check.py`. Results:

- `#aus_agent` fresh load → `viewBox="0 0 1334 604"`, 7 stage boxes, SAVE box
  fully visible, dashed loop arrow REASON/COMMIT → SEARCH labeled
  "repeat until report".
- Click "Back to overview" on the same svg → `viewBox=None` (no leak),
  overview renders identically to a fresh no-fragment load.
- Drill into `facet_rag` (5 stages, fits) → `viewBox=None` (narrow path
  keeps the old pixel-space behavior).
- Fresh overview load → `viewBox=None`, engines column ends at x=1112.5
  inside the 1250 px svg.

Screenshots (committed evidence):
[assets/2026-07-28-arch-viz-aus-agent-1250x700.png](assets/2026-07-28-arch-viz-aus-agent-1250x700.png),
[assets/2026-07-28-arch-viz-overview-after-back-1250x700.png](assets/2026-07-28-arch-viz-overview-after-back-1250x700.png),
[assets/2026-07-28-arch-viz-overview-fresh-1250x700.png](assets/2026-07-28-arch-viz-overview-fresh-1250x700.png).
