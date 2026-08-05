# 2026-08-05 — organizer RAG baselines in the outputs viewer

Imported the two organizer-published TREC RAG 2026 RAG baselines into
`data/outputs/` as a `baseline` system, and taught the viewer to render a
session that has **no trajectory** — because baselines ship as submission
records only.

## Importer — `scripts/import-official-baselines.py`

The organizers ship each baseline as ONE JSONL of 119 submission records
(`metadata` / `references` / `answer`); the viewer indexes one file per session.
The script splits them:

```
data/official/trec-rag-2026-data/trec-rag-2026/baselines/rag/*.jsonl
  → data/outputs/baseline/<ts>.<narrative_id>_<slug>.output.json   (238 files)
```

```bash
uv run python scripts/import-official-baselines.py --prune
```

Decisions worth knowing:

- **One system, two runs.** Both baselines land under `baseline`, distinguished
  by the organizers' own `run_id` — which is exactly what the viewer's per-system
  "Run" dropdown filters on, so no new UI was needed:
  `first-qwen3-8b-listwise-top100-gpt56sol-rag` and
  `piika-gpt56sol-medium-agentic-bm25-rag`.
- **No `trace` key.** The files carry the three submission fields verbatim and
  nothing else; every record was checked through `ragrun.validate_rag_output`
  on import (all 238 clean, `--strict` to make a violation fatal).
- **Synthetic timestamps.** Baselines have no per-topic run time. Every session
  of one baseline shares that JSONL's mtime as its stamp (+1s per file so the
  two runs never interleave), and the index tie-breaks equal stamps by narrative
  id — so a baseline lists `rag2026-0 … rag2026-118` instead of readdir order.
- Filenames lead with the narrative id (`…+1000.rag2026-0_i_m_on_a_hospital.output.json`)
  so they sort and grep by topic.
- `data/outputs/baseline/README.md` is generated with the provenance table.

Only the **RAG** baselines are importable. `baselines/retrieval/*.trec` are
ranked lists with no answers — nothing for an answer viewer to show.

## Viewer changes (`tasks/outputs_viewer/`)

Four small fixes; a traceless session previously rendered as if it were broken.

- `lib/server/fileIndex.ts` — sessions sharing a timestamp tie-break by
  narrative id ascending (`compareNarrativeId`). Agent runs get unique
  microsecond stamps, so this only ever fires for imported baselines.
- `components/session/Timeline.tsx` — **zero steps is not a malformed trace.**
  It used to hit the red *"Invalid trace: every generation and tool step must
  include t_start and t_end"* error path. Now: a neutral "No trace for this
  session — answer, references and citations only", and the step-type legend is
  suppressed.
- `components/session/StepTree.tsx` — the "Input" node is hidden when there is
  no `trace.input` (it could only ever open an empty pane).
- `app/systems/page.tsx` — rows lead with the narrative id, and the trace hint
  reads "answer only (no trace)" instead of a bare "no trace".

## The one real bug this surfaced: citations didn't resolve

Clicking a baseline citation 404'd. Root cause is **not** baseline-specific:
our dense and sparse doc backends are **chunk-keyed** (`<docid>_p<n>`), so a
bare docid misses both.

```
GET /doc/shard_00934_21956       dense:404  sparse:404
GET /doc/shard_00934_21956_p1    dense:200  sparse:200
```

Baselines cite bare docids exclusively (they retrieved from `climbmix-400b`,
not our chunked index) — and so does any run of ours whose trace didn't carry
`references_full`, which the viewer prefers when present. Verified against a
live `aus_agent` session: its citations 404'd too.

Fix: `lib/server/docFetch.ts` now tries the hosted Pyserini API
(`GET /v1/{index}/doc/{docid}` → `{docid, doc}`) as a third backend after
dense and sparse. It is the only one that answers a bare, unchunked docid.
The `"pyserini"` value was already in the `DocResult["source"]` union, unused.
Config was already in `lib/server/env.ts` (`pyseriniBaseUrl` / `pyseriniToken`);
tokens stay server-side.

## Verification — Playwright, both session kinds

`worklogs/assets/2026-08-05-outputs-viewer-smoke.py` (run against the dev
server on :3618 with `/opt/homebrew/bin/python3.11`, Playwright 1.60):
**34 checks, all pass, zero console/network errors.** It seeds
`localStorage.outputs_viewer_user` because `IdentityGate` blocks the app.

| area | checks |
| --- | --- |
| index API | `baseline` listed with 238 sessions; `aus_agent` still 7; two run ids; every baseline `hasTrace:false` and carries a `narrativeId`; topic order holds within each run |
| systems list | header "BASELINE — 30 OF 238 SESSIONS"; row reads `rag2026-0 · 2026-08-04 18:23:19 · <run_id> · answer only (no trace)`; Run dropdown offers both baselines |
| baseline session | "no output trace" chip; neutral timeline message; **no** "Invalid trace"; no dead Input node; task-description card; `637 / 1024 words`; citation `[1]` opens the sidebar with `source: pyserini` and real text; Sentences tab 23 rows; Config tab shows `narrative_id` |
| agent session (regression) | status/model/steps/`retrieved docids` chips; Gantt legend; Input node present; no no-trace message; step detail opens on "Turn 1 · generation"; citation resolves |

Screenshots taken during the run: `/tmp/shot-systems-baseline.png`,
`/tmp/shot-session-baseline.png`, `/tmp/shot-session-agent.png`.

`bash scripts/test.sh` — 1523 passed. `tsc --noEmit` and `eslint` clean.

## Note for later

Feedback widgets work on baseline sessions unchanged, so the baselines are
judgeable side by side with our runs on the Leaderboard / Summary pages.
