# 2026-07-30 — End-to-end suites for `o3_deep_research` and `claude-code-research` (#4)

Issue #4: the two systems with no test module. `feat/systems-test-harness`
covered `aus_agent`, `ali_deepresearch`, and `facet_rag`; these two were left
because neither is a normal agent loop and it wasn't obvious what a test could
assert. This session wrote both.

Suite: **944 passed, 6 deselected, ~16 s** (from 844/4 — +100 tests, +2 live).

| Module | Tests | Live |
|---|---|---|
| `tests/systems/test_o3_deep_research.py` | 58 | 1 |
| `tests/systems/test_claude_code_research.py` | 42 | 1 |

The issue's own recon was single-agent and flagged as unverified. Every claim in
it was re-checked with ephemeral probes before anything was written; all of it
held, and the probes turned up further behaviours (the `--resume` poll count, the
reconnect cursor value, `_docids_from_mcp_output`'s double-encode branch) that
became assertions.

## What each system actually lets you test

Neither is testable the way the other three are, and getting this right was most
of the work.

**`o3_deep_research` has no agent loop of ours.** OpenAI's hosted deep-research
agent plans and executes server-side; `run.py` hands it an MCP tool block and
then reconstructs a trajectory from a stream of Responses events. So the fake is
a fake **SDK**, not a fake model — there is no `scripted_provider` equivalent to
use. `FakeResponses` replays the real event sequence (`response.created` →
`output_item.added`/`.done` per item → `response.completed`) with
`SimpleNamespace` attribute bags as items. Nothing asserts agent *behaviour*;
everything asserts translation (items → steps, usage → tokens, MCP output →
docids).

**`claude-code-research` has no runner at all** — Claude Code *is* the agent,
driven by the system dir's `CLAUDE.md`, and the two scripts are all the code
there is. Nothing offline can assert what the agent did. What the scripts own is
the evidence chain:

```
corpus.py  --appends-->  scratchpad/tool_log.jsonl  --read-by-->  save_run.py
```

so every test defends one link. The load-bearing one is that `save_run.py` drops
any citation to a docid no logged call returned: the agent hand-writes
`answer_sentences.json`, so a hallucinated or mistyped docid is live on every
run and there is no retrieval step downstream to catch it.

The JSONL format between the two scripts is an **unvalidated contract** — nothing
checks it at runtime, and a drift surfaces as silently-dropped citations at the
end of a completed research session. Most tests write log records by hand (needed
for shapes that are awkward to provoke through the CLI), so they would all keep
passing through such a drift. Hence
`test_a_log_written_by_corpus_py_is_readable_by_save_run_py`, which runs both
scripts for real over a temp task dir; it is the only test that would catch it.

## Three real `src/` defects found

Writing the tests found three. Two were fixed here; the third is a design
decision and was filed.

**1. `_docids_from_mcp_output` crashes on a JSON *array* payload.** Its `except`
tuple is `(JSONDecodeError, TypeError, KeyError)`, and `payload.get` on a list
raises `AttributeError` — uncaught. The intent of the clause is plainly "degrade
to `[]`"; this is a gap in its type list. It matters because this function runs
during artifact assembly, *after* an hour-long DR run is already billed, so an
unexpected tool-output shape destroyed the whole run's artifacts. Added
`AttributeError` with a comment on why.

**2. An answerless DR run reported itself as `completed`.** Line 308 read:

```python
status = "completed" if (resp.status == "completed" and answer_text) else str(resp.status)
```

which is a no-op — when `resp.status == "completed"` and `answer_text` is empty,
the else branch yields `str("completed")`, the same value. The intent is
unmistakable (why else test `answer_text`?); the value was the slip. Consequence:
a DR run that spends its tool budget planning and returns no message item passed
`export-rag-submission.py`'s `status in ("completed", "budget_exhausted")` gate
and would have shipped `format_answer`'s `"No answer was produced."` placeholder
as our submitted answer for that topic. Now `completed_no_answer`, which the
exporter does not accept. Pinned by
`test_a_completed_response_with_no_answer_text_is_not_completed`, which asserts
against the exporter's accept-list rather than the literal string.

**3. Two systems promise hybrid RRF and run dense-only → issue #11.**
`corpus.py:86` and `ali_deepresearch/tools.py:69` both call `run_search_tool`
without `search_engine`, taking its `"semantic"` default. Six places claim
hybrid dense+sparse RRF, including `ali_deepresearch`'s artifact metadata
(`"searcher_type": "hybrid-rrf"`, i.e. affirmatively wrong). The lost leg is
sparse BM25 — exactly what dense is weakest on.

Not fixed here: there is nothing to fix at the tool layer. `_DISPATCH` has no
fused entry *by design* ("There is deliberately no fused option: the caller is
the fusion layer"); `utils.search.search` is the hybrid function. So a fix is a
choice between three designs, it is a retrieval-effectiveness change to two of
five systems, and both callers should change together and be measured. Filed as
#11 and pinned by
`test_search_is_dense_only_despite_promising_hybrid_current_behaviour`.
`ali_deepresearch`'s identical omission is not pinned yet (noted in #11).

## Two tests of mine that were wrong before they were right

Worth recording because both would have passed while proving nothing.

**The per-item timing test passed against run-bounds timing.** I asserted
`len({s["t_start"] for s in tool_steps}) > 1`, which failed — not because the
mechanism is broken but because the whole fake stream completes inside one
millisecond, so real `now_iso()` values are identical. Had the assertion been
weaker it would have passed either way. Rewritten with a monkeypatched `now_iso`
returning `t000`, `t001`, … so each bound is identifiable: `t000` is
`started_at`, so a step carrying it took its bound from the run rather than its
own event. Now asserts the exact interleaving
`[("t001","t002"), ("t005","t006"), ("t007","t008")]`.

**Two assertions were self-defeating.** `assert record["failed"] if False else
"failed" not in record` and an `assert X is False if "failed" in Y else True` —
both unfalsifiable in one branch. Grepped both new modules for `assert .* or `,
`if False`, `assert True` and rewrote them into direct assertions.

## Conventions applied

- `load_module` (from `tests/systems/conftest.py`) for the by-path imports:
  `claude-code-research/` is hyphenated so not importable, and
  `o3_deep_research/run.py` is a bare `run.py` that would collide with every
  other system's runner. Distinct names (`o3dr_run`, `ccr_corpus`,
  `ccr_save_run`) so the loader's collision guard stays satisfied.
- Shared fixtures used rather than re-rolled: `read_artifacts`,
  `stub_search_tool`, `CLIMBMIX_DOCIDS`. Two new local ones were needed —
  `stub_corpus_fetch` (patches `corpus.fetch_doc`, since the script did a
  `from utils.fetch_doc import fetch_doc` and holds its own reference) and an
  autouse `no_sleeping` in the o3 module.
- **`no_sleeping` is autouse deliberately.** Both retry paths (`_retrieve`,
  `FormatLLM.complete`) and the reconnect loop sleep up to two minutes. A test
  that forgets to patch it does not fail — it hangs for minutes, which is worse
  than a red test.
- `FormatLLM` is built with `__new__` to bypass `__init__`, which constructs a
  real `OpenAI` client. Only `complete`'s retry logic has behaviour worth
  testing.
- `cli_args()` spells out every flag `run_one` reads instead of deriving them
  from `main()`'s parser, so a *new* flag whose default changes `run_one`'s
  behaviour raises `AttributeError` here rather than being silently exercised.
- One `@pytest.mark.live` per system. The `claude-code-research` one fetches a
  docid *taken from its own live search result*, which checks the two backends
  agree on ids — something no stub can.

No `importorskip` and no `scripts/test.sh` dep-group change: `openai`, `boto3`,
`mcp`, and `dotenv` all import under the three groups already passed, and the
o3 client is injected so none of them is reached anyway. Verified before writing.

## Notes for whoever reads these tests next

- **`mcp_list_tools` is counted as a `tool_call`.** Deliberate, and pinned, but
  it means `o3_deep_research`'s `tool_call_counts` is inflated by one relative to
  its real retrieval effort — relevant to anyone comparing call counts across
  the five systems.
- **`fetch` docids come from `arguments`, not `output`.** A fetch result is
  document text with no id in it, so the request is the only record of what was
  read. Unifying the two branches to read the output is the obvious
  simplification and would silently empty `state["fetched"]` — which is what
  orders fetched docs ahead of merely-searched ones in the candidate list.
- **`render_answer_text` and `map_citations` legitimately disagree.** A docid
  that `map_citations` dropped as unretrieved still appears in the trajectory's
  `output_text`, because that string is the forensic record of what the agent
  *claimed*. `test_the_rendered_text_shows_a_dropped_docid_that_the_answer_hides`
  states this so nobody "fixes" the two into agreement.
