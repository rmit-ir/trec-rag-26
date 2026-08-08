# Architecture diagram: explicit system branches

Date: 2026-08-06

## Goal

Make `docs/architecture.html#aus_agent_v2` describe the actual runnable
alternatives instead of presenting every implemented stage as one sequential
superset. Keep labels readable at laptop width and remove existing text
collisions in both the drill-in and overview views.

## Source-of-truth change

`src/systems/aus_agent_v2/pipeline.py` now declares an `ARCH_VARIANTS` literal
alongside its existing `ARCH_STAGES` catalog. The declaration records four
mutually exclusive entrypoints:

| Variant | Status shown | Entrypoint | Input |
| --- | --- | --- | --- |
| Verified research-first control | `VERIFIED · dev30 0.704159` | `run_one` | original request |
| Lean atomic ledger | `IMPLEMENTED · UNGRADED` | `run_lean_contract_one` | original request |
| Semantic finish-the-claim | `IMPLEMENTED · UNGRADED` | `run_semantic_contract_one` | original request |
| Extractive candidate union | `UNGRADED · dev criterion ceiling 0.8284 (not a score)` | `run_candidate_union_one` | eight completed cited answers |

The verified branch shows the exact promoted path: prose coverage plan, one
atomic obligation scout, request-form gate, integrated search/commit loop,
direct final cited prose, citation mapping, and save. It does not inherit the
typed contract, terminal-submit, semantic-gate, or candidate-union stages.
The candidate branches show those stages only where their corresponding
entrypoints execute them.

## Generator changes

`gen_arch_viz.py` now AST-reads and validates `ARCH_VARIANTS` without importing
system modules. A variant path must use known, non-duplicated stage ids; stage
overrides cannot alter structural flow keys; entrypoint/code/prompt/tool refs
are resolved against source; and visual tones are restricted to verified,
candidate, or oracle.

The default variant opens as a focused explanation; an explicit comparison
control renders one lane per entrypoint. Each comparison lane has its own input,
status, stage sequence, and loop boundary. Long pipelines keep a fixed font and
box size and use horizontal scrolling instead of an SVG `viewBox` that shrinks
text. A shared SVG word-wrapper caps labels at two lines with an ellipsis, run
badges moved to the bottom metadata row, and long variant status text wraps
within its card. The overview uses wider, wrapped system cards and now leaves
explicit clearance between column headers and the first row.

The architecture skill documents the new literal and the reason to use it:
alternative entrypoints should be branches, not a misleading flat superset.

## Validation

- `bash scripts/test.sh tests/arch_viz/test_gen_arch_viz.py`: 15 passed.
- `bash scripts/test.sh`: 1,811 passed, 9 live tests deselected; no skips.
- `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check`: current.
- Headless Chromium visual inspection at 2400×1000: all four complete lanes
  readable; no stage-label, badge, or status collisions.
- Headless Chromium visual inspection at 1366×900: fixed-size text remains
  readable and the long execution path scrolls horizontally.
- Overview visual inspection at 1366×900: system names remain inside their
  cards and column headings clear the first row.
- No model, retrieval, or grading API was called; cost was $0.
