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

## Update: release a superseded committed document (real harness capability)

Follow-up ask: each facet should end up with the MINIMAL set of committed
documents that covers it — when a better document is found for something
already committed, drop the redundant one rather than accumulating both.

This is NOT achievable by prompt wording alone. Once a document is committed,
its full text lives verbatim in the model's OWN conversation history; nothing
short of a tool action can make that text go away again, and the existing
`commit_context` tool can only select from the batch staged THIS turn — it
has no way to reach back and touch something committed on an earlier turn.
Asked the user to confirm scope (prompt-only guidance vs. a real capability)
before building it; they chose the real capability.

Added, all additive/opt-in (existing `aus_agent` behavior is byte-identical
when the new fields are absent, confirmed by the full existing test suite
passing unchanged):

- `ContextLedger.release_committed(released)` (`aus_agent/context.py`) — drops
  a unit committed on ANY earlier turn by recomputing that turn's ORIGINAL
  tool-result compaction from scratch (kept forever in a new `call_history`
  dict, since `pending` clears every commit) against the ledger's CURRENT
  `committed_ids` membership. Recompute-from-scratch means it never needs to
  read the provider's current (possibly already partially compacted) history
  back out — `_compact_output` is idempotent given (original output, current
  keep-set). A new `committed_call_id: dict[unit_id, call_id]` tracks which
  call currently renders each committed unit in full, set inside `commit()`'s
  existing `keep_here` loop, cleared on release. `RELEASE_PREFIX` is a THIRD
  tombstone wording distinct from `REJECTION_PREFIX` ("you judged this
  irrelevant") and `DUPLICATE_PREFIX` ("a full copy lives elsewhere") — a
  released document was neither; the model held it and chose to let it go.
- `ContextDecision` (i.e. `CommitDecision`) is deliberately NOT touched —
  `test_ledger_core.py::test_commit_decision_context_is_the_trace_projection`
  asserts its `.context` property's exact key set, so release info goes
  through a SEPARATE `ReleaseDecision` dataclass instead, and gets folded
  into a merged dict only at the call site in `agent.py` (not inside either
  dataclass) when building the trace's `context=` argument.
  `apply_commit`/`CommitHandlerResult` similarly only add a `released` payload
  key / `.release` field when the call actually carries one (guarded by
  `test_apply_commit_returns_the_decision_and_the_models_payload`'s equally
  strict `set(handled.payload) == {"committed", "rejected"}` assertion for the
  no-release case).
- `aus_agent.agent.run_agent` gained a fourth generalization parameter,
  `commit_context_tool: dict[str, Any] | None = None` — the tool actually
  advertised to the model, defaulting to aus_agent's own. Needed because
  `apply_commit` reading `arguments.get("release")` is harmless-by-omission
  but useless unless the model's tool SCHEMA documents the field exists.
- `facets_agent/tools.py::COMMIT_CONTEXT_TOOL` — facets_agent's own copy,
  extending aus_agent's with the `release` schema property and description.
  aus_agent's own tool definition is completely untouched.
- `facets_agent/prompts.py` — step 3 rewritten to state the minimal-evidence
  goal and the release mechanic directly; step 1 now says explicitly to solve
  facets independently (was implicit before).

Test coverage added: `tests/aus_agent_context/test_ledger_release.py` (11
cases: cross-turn recompaction, sibling units left alone, recompute-from-
original not from a prior compaction, validation errors, re-committing a
released id later), `test_commit_tool.py` (5 cases: no-op when absent,
combined commit+release in one call, validation-error propagation), and
`tests/systems/test_facets_agent.py` (the tool schema advertises `release`;
a full commit -> supersede -> release -> cite-only-the-better-one run reaches
`run_agent` end to end and the superseded document's text is actually gone
from provider history, not just from the final citations).

## Verification

- `bash scripts/test.sh` — 1587 passed (up from 1570 after the release
  feature's new tests), 1 pre-existing unrelated failure
  (`tests/bm25_tune/test_prompts.py` needs `evaluation-results/` data not
  present on this machine — confirmed pre-existing via `git stash`).
- `bash scripts/test.sh systems` — 293 passed (all five systems, unaffected
  by the `aus_agent/agent.py` generalizations).
- `bash scripts/test.sh tests/aus_agent_context` — 166 passed (151 pre-
  existing, unchanged, + 15 new for `release_committed`/`apply_commit`).
- `python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check` — clean
  after regenerating.
- `uv sync --group facets-agent` and `uv run --group facets-agent python
  src/systems/facets_agent/run.py --help` — both succeed.
