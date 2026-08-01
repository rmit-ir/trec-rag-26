# Wire the promised hybrid retriever into both research systems (#11)

Issue #11 identified a runtime/documentation mismatch in
`claude-code-research` and `ali_deepresearch`: both described their corpus
search as dense+sparse RRF, but called `run_search_tool` without a
`search_engine`, so the shared tool silently used its `semantic` default. The
result was dense-only retrieval with hybrid provenance in prompts and saved
run metadata.

This work is on `fix/hybrid-retrieval`, created directly from `origin/main` at
`2ba3eda`. It does not depend on PR #12 (`feat/submission-hardening`) and does
not touch the RAGDoll/evaluation or BM25-tuning areas owned by other team
members.

## Design

The shared search tool deliberately exposes only model-selectable individual
engines. `utils.search.search` is already the caller-owned hybrid composition:
it runs semantic and keyword retrieval concurrently at depth `max(k, 50)`,
fuses them with RRF, and returns the top `k` results. The fix therefore keeps
`hybrid` out of `ENGINE_INFO` and `_DISPATCH` and wires both systems directly to
that composition.

`tools.search_tool.run_search_backend` was extracted from the existing
single-engine execution path so caller-owned compositions retain the same JSON
envelope, text truncation, score rounding, and agent-visible error handling.
`run_search_tool` delegates to it, preserving its public behavior.

Both systems now record `search_engine: hybrid-rrf` at the actual tool-call
boundary. `ali_deepresearch` also includes it in each search trajectory item;
its existing run-level `searcher_type: hybrid-rrf` metadata is now accurate.

## Tests and documentation

The hermetic `stub_search_tool` fixture now stubs the dense and sparse clients
below the real `utils.search.search` layer. System tests therefore retain real
concurrency and RRF logic while avoiding credentials and network access.

The regression coverage asserts:

- both dense and sparse legs receive the same model-written query;
- both use the default fusion depth of 50 when the requested result count is
  smaller;
- the visible result order is RRF output, not either backend's order or list
  concatenation;
- hybrid provenance is present in tool logs and trajectory items;
- a backend exception remains an agent-visible error envelope;
- budget, repaired-tool-call, and no-search paths route both or neither leg as
  appropriate.

The architecture generator now models `utils.search.search` as a shared hybrid
retrieval layer connected to the semantic and keyword engines. The generated
diagram was refreshed and launched for both affected systems:

```bash
python3 skills/trec-rag-new-system/scripts/gen_arch_viz.py --system ali_deepresearch
python3 skills/trec-rag-new-system/scripts/gen_arch_viz.py --system claude-code-research
python3 skills/trec-rag-new-system/scripts/gen_arch_viz.py --check
```

The check reported `docs/architecture.html is up to date (5 systems)`.

Targeted offline tests:

```bash
bash scripts/test.sh tests/shared/test_search_tool.py tests/shared/test_fusion.py tests/systems/test_claude_code_research.py tests/systems/test_ali_deepresearch.py
```

Result: **163 passed, 2 deselected in 1.21s**. The deselected cases are the two
credentialed live-system tests.

Full offline suite:

```bash
bash scripts/test.sh
```

Result: **944 passed, 6 deselected, 1 warning in 11.75s**. The warning is the
pre-existing Starlette `httpx` test-client deprecation warning.

Live retrieval and retrieval-effectiveness evaluation were not run in this
session. The offline regressions verify routing, fusion, serialization, and
provenance. Comparing answer/retrieval metrics is separate follow-up work after
BM25 tuning and should use the evaluation workflow owned by those tasks.

## Review follow-ups (2026-07-31, code review of PR #13)

`run_search_backend` had no direct test: coverage reached it only through
`run_search_tool` and the two systems. Since it is now the single execution path
for all five systems' retrieval, and since a caller passing an arbitrary
`backend` reaches contracts no `_DISPATCH` engine exercises, it is pinned
directly in `tests/shared/test_search_tool.py`:

- `test_backend_is_called_with_k_as_a_keyword` — pins the `k=k` fix in `8bb25c1`.
  Verified to bite: reverting that line to positional `k` fails this test and
  only this test.
- `test_envelope_labels_the_engine_the_caller_names` — the `engine` label is the
  caller's string, and `hybrid-rrf` is deliberately absent from `ENGINE_INFO`.
- `test_a_composition_failure_is_an_error_envelope_too` — a raising composition
  still reaches the agent as `{"error": ...}`.

`test_react_run_search_routed_with_the_scripted_query` asserted the two legs'
complete kwargs dicts, including `timeout: 30.0` — `utils.search.search`'s own
default, so a timeout tune would have failed two system tests for no
behavioural reason. Narrowed to query/depth plus the dense leg's `with_text`.

Full offline suite after these additions: **947 passed, 6 deselected, 1 warning
in 12.55s**.

Two issues found in review are **not** fixed here, because both change retrieval
behaviour rather than tests and deserve their own measurement:

- **Either-leg failure sinks the whole search.** `utils.search.search` calls
  `f_dense.result()`/`f_sparse.result()` bare, so one leg raising fails the call.
  Confirmed by probe: a raising sparse leg yields
  `{"error": "RuntimeError: sparse leg down"}`. Before this PR a `keyword`
  outage was invisible to these two systems; now it zeroes their search, so
  failure exposure roughly doubles. A partial-result fallback (return the
  surviving leg, mark the degradation in `meta`) is the likely fix.
- **`meta` is dropped from the envelope, discarding RRF provenance.**
  `run_search_backend` projects six fields and omits `meta`, so the fused
  `meta["sources"][name] = {rank, score}` — what `tests/shared/test_fusion.py`
  calls "the provenance the analysis/worklog layer reads" — never reaches the
  tool log. Both systems now record only the fused RRF score (~0.03), so nothing
  downstream can tell whether a hit came from one leg or both. That is the main
  analytical payoff of going hybrid.
