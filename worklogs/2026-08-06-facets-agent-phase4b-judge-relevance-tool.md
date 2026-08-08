# 2026-08-06 — facets_agent Phase 4b: judge_relevance tool, built and wired

Follow-up to `worklogs/2026-08-06-facets-agent-phase4a-coverage-gate.md`.
User proposed a query-drift-detection component (`PLAN.md` §7.4), refined
it to "agent-initiated, cheap-model-backed (Qwen/gpt-oss), global to any
system, called on the agent's own judgment" rather than the original
automatic-statistical-prefilter sketch, then asked to build and wire it.

## What shipped

**`judge_relevance` — global tool** (`src/agent_harness/tools/judge.py`,
new file). Given a `requirement` and a batch of `document_ids`, spins up a
FRESH, single-turn conversation on a separate, cheap model
(`openai.gpt-oss-120b-1:0` on Bedrock by default — the already-verified
choice from RAGDoll's support/UMBRELA judging in this repo) and returns a
per-document `relevant` / `adjacent_not_relevant` / `irrelevant` verdict,
plus a suggested query reformulation when none are relevant. Resolves
document ids via `ledger.call_history` (kept for the whole run, unlike
`pending`), so it can check a currently-staged, already-committed, or
already-rejected id alike.

**Harness wiring** (`agent_harness/agent.py`): new `judge_tool: dict | None
= None` parameter, same opt-in discipline as `pre_final_hook` — a 4th
dispatch bucket exists in the loop regardless, but is inert unless a caller
passes the tool definition (confirmed: the full offline suite, including
every other system, is unaffected). The model decides for itself when to
call it; nothing in the harness triggers it automatically.

**facets_agent wiring** (`agent.py`, `prompts.py`): `judge_tool` defaults to
`JUDGE_RELEVANCE_TOOL` (override with `None` for an A/B run without it), and
one sentence in `prompts.py` step 2 names when to reach for it — full
mechanics stay in the tool's own description, same schema-vs-prompt split
already used for release/coverage. `ARCH_STAGES` updated (new tool in the
loop's tool list, noted as a GLOBAL agent_harness tool, not facets_agent's
own schema, unlike search/commit_context).

**Judge prompt**: NOT UMBRELA's (that's a single query-passage 0–3 scale;
this task needs a per-document 3-way verdict against a specific requirement
plus a reformulation suggestion — different shape). Drafted by asking
`gpt-5.6-luna` to optimize specifically for `openai.gpt-oss-120b-1:0` (a
smaller open-weight model, not GPT-4-class) on three things: reliably
telling `adjacent_not_relevant` apart from `relevant` (the hardest category
and the whole point of the tool), strict JSON with no markdown fences, and
staying concise since it runs on every doubtful batch. Meta-prompt and raw
output: `worklogs/assets/2026-08-06-draft-judge-prompt.py` /
`-drafted-judge-prompt.txt`.

## Tests

`tests/agent_harness_context/test_judge_tool.py` (9 cases): the handler in
isolation (missing requirement/documents short-circuit without a model
call, successful parse, markdown-fence leniency, exception degrades to an
error envelope, `_documents_by_id` resolves committed/rejected ids via
`call_history`) and the harness wiring (not advertised by default,
advertised when opted in, a scripted call round-trips through the 4th
dispatch bucket without a `KeyError`). `tests/systems/test_facets_agent.py`
(+2): advertised by default, disableable via `judge_tool=None`.

`bash scripts/test.sh`: 1616 passed, 8 deselected, 0 skips (count includes
two unrelated upstream commits pulled mid-session — see below).

## Mid-session repo sync

`git pull` while this work was in progress brought in two more arch-viz
generator commits (`12dae20`, `a268bf7`) that also touched
`docs/architecture.html` — conflicting with my own local, now-stale
regeneration of that file. Discarded my local copy (`git checkout --
docs/architecture.html`, safe: fully reproducible) before pulling, then
regenerated fresh with the updated generator script afterward. No source
work was at risk — only the generated diagram.

## Not run this session

No live exercise of `judge_relevance` — it has never been called by a real
run yet. The `facets-agent-dev30-e2708ab` measurement run (30 topics)
predates this wiring, so it's still a Phase-4a-only (coverage gate + prompt
tweak) data point; a further re-run at the new SHA would be needed to
measure Phase 4b's actual effect.
