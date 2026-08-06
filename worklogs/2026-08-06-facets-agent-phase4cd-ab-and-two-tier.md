# 2026-08-06 — facets_agent Phase 4c A/B result + Phase 4d two-tier prototype

Follow-up to `worklogs/2026-08-06-facets-agent-phase4a-coverage-gate.md` and
the Phase 4c plan (`worklogs/assets/2026-08-06-prefilter-plan-v2.md`,
reviewed by gpt-5.6-terra). Two things this session: the Phase 4c A/B
experiment actually ran, and a new Phase 4d prototype (piika-inspired
two-tier retrieval) got built. Full design/status: `PLAN.md` §7's Sequencing
section.

## Phase 4c: minimize vs rank, 15-topic random sample

Sample: 15 of 30 research-rubrics dev topics, `random.seed(20260806)`,
`data/... /research-rubrics-topics-dev.tsv`. Generated facets_agent twice
(`facets-agent-sample15-minimize`, `facets-agent-sample15-rank`), aus_agent
side reused from the existing `aus-agent-dev30-20260806` (unaffected,
subset to the same 15 qids automatically by the arena script's qid
intersection).

New script: `tasks/task-comparison/scripts/arena_facets_agent_self_ab.py` —
a same-system, different-run-id self-arena (both arms read
`data/outputs/facets_agent/`), reusing every judging/parsing function from
`arena_aus_agent_vs_facets_agent_rubric.py` via import rather than
duplicating it.

**Rubric arena results** (judge=gpt-5.6-terra):

| comparison | result |
|---|---|
| minimize vs rank (direct) | rank 53.3%, minimize 46.7%, order_consistency=0.6 |
| minimize vs aus_agent(15) | aus_agent 76.7% |
| rank vs aus_agent(15) | aus_agent 73.3% |

Near coin flip head-to-head at weak order-consistency — not a confident
result at n=15/side. Both configs read somewhat better against aus_agent
than the no-filter dev30 baseline (80% aus pref), but on a smaller,
different topic sample, so not a clean comparison. **Neither config ships
as facets_agent's default.**

**Support-judge comparison did not complete**: both runs hit
`ExpiredTokenException` (AWS session token expired mid-run) — 100% judge
errors, 0 usable rows. Needs a re-run with fresh credentials before the
citation-support half of this picture exists.

Full result files: `evaluation-results/arena/facets_agent-minimize-vs-rank-sample15/`,
`evaluation-results/arena/aus_agent-vs-facets_agent-sample15-{minimize,rank}/`.

## Phase 4d: piika-inspired two-tier retrieval (prototype, not yet measured)

User pointed at https://github.com/nourj98/piika (`src/pi-search/`) for how
it structures search. Fetched `agent_prompt.ts`, `tool_interface.ts`,
`tool_types.ts`, `tool_handlers.ts` via `gh api`. Key structural finding:
piika separates BROWSING (`search` → server-cached pool of up to 1000
hits, shown as short id/score/title/snippet previews, 5 at a time,
paginated further via `read_search_results`) from READING (`read_document`,
paginated by line, the only path to full text). This repo's `get_documents`
already plays `read_document`'s role well (fetch full text by known id,
already staged/citable) — the actual gap was that `search` currently
returns near-full text immediately AND auto-stages it, collapsing the two
tiers into one.

**Why this is structurally different from Phase 4b/4c**: no judge model, no
semantic suppression — nothing is ever dropped. It sidesteps every one of
gpt-5.6-terra's recall objections by construction, because the PRIMARY
model (not a smaller judge) decides what's worth reading in full; it just
sees less by default.

**Built**: `search_preview_chars: int | None = None` and
`stage_search_results: bool = True` on `agent_harness.agent.run_agent`
(both default to today's exact behavior). When active: every search
result's text is truncated to `search_preview_chars` regardless of what
the model requests, and search results skip `ledger.stage(...)` entirely
— `get_documents` is unaffected, still stages full text normally.
facets_agent wires both via `run.py --two-tier-search
--two-tier-preview-chars` (default 400), and appends
`prompts.TWO_TIER_SEARCH_ADDENDUM` to the system prompt only when active,
explaining the changed contract (preview → not citable; `get_documents` →
citable).

**Tests**: `tests/agent_harness_context/test_two_tier_search.py` (4 cases:
byte-identical defaults, preview truncation applied to every result,
committing a preview id directly is a no-op [same "nothing staged"
behavior the harness already has] then `get_documents` promotes it to
committable, `get_documents` stages normally when search doesn't).
`tests/systems/test_facets_agent.py` (+2: addendum absent by default,
present when enabled). `get_documents` fetches over real HTTP
(`_fetch_one`), a separate path from the shared `fake_engine`
search-dispatch fixture — patched directly in the two tests that exercise
it rather than adding a new shared fixture for this alone.

`bash scripts/test.sh`: 1636 passed, 8 deselected, 0 skips.
`gen_arch_viz.py --check`: passes (no new tool added, `get_documents`
already existed).

**Not done this session**: no live run of two-tier retrieval yet, and
worth carrying over from piika regardless of this prototype's outcome —
it requires a `reason` argument on every tool call (search,
read_search_results, read_document alike), while facets_agent's own
`requirement` field currently only covers `search`.
