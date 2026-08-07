# aus_agent_v2 bounded contract-commit correction

Date: 2026-08-06

## Outcome

This offline session fixed a runtime failure mode introduced by the executable
finish-the-claim contract. The contract asks the research model to annotate a
staged source with obligation ids and material `must_include` literals. Before
this change, one invalid annotation expired and compacted the entire full-text
batch, forcing the agent to search for the same evidence again or abandon the
claim. That made a stricter evidence pipeline less reliable than the permissive
one it is intended to replace.

The contract candidate now retains the same staged source through at most two
bounded correction turns. Only `_CoverageSupportValidationError` is
correctable; ordinary selection errors still follow the existing expiry path,
while unexpected implementation/provider failures terminate the run. A valid
correction commits and compacts the original retrieval output exactly once.
The third invalid attempt, or an attempt with fewer than two model turns left
for correction plus terminal submission, expires immediately.

No provider, search, Bedrock, OpenAI, or judge call was made. Cumulative spend
remains **$1,096.72** against the standing $300 total cap, and the verified
best complete 30-topic score remains **0.7042**. This is protocol hardening for
the ungraded `run_contract_one` candidate, not a score claim.

## State machine

```text
SEARCH -> OPEN staged batch (failures=0)
  -> valid commit
       mutate ledger -> compact search result once -> CLOSED
  -> invalid support annotation + >=2 future turns
       restore ledger -> no compaction -> failed tool result with exact errors
       -> corrected commit only (up to two correction turns)
  -> third invalid annotation or <2 future turns
       expire + compact once -> CLOSED -> submit may mark row unresolved
  -> unexpected RuntimeError/provider failure
       restore ledger -> fail run; do not disguise defect as model error
```

The correction turn is single-purpose. A simultaneous search or
`submit_answer` receives an error result and is not executed, even if the
corrected commit itself succeeds. Missing or multiple corrected commits retain
the existing loop-top expiry behavior.

## Why this is safe

The relevant order in `agent.py` is validation before `apply_commit`. On a
correctable failure the ledger snapshots for pending, committed, and rejected
state are restored, and `compact_tool_results` is not called. The original
search result therefore remains in provider history for the corrected turn.
On success, the normal ledger mutation and provider compaction execute once.

Independent offline reviews confirmed that both provider implementations
compact earlier tool results by tool-call id without rewriting signed assistant
history, and that `ContextLedger` validates selections before clearing pending
state. The reviews found three P1 issues in the first patch: retry
classification was too broad, feedback allowed same-turn actions that code did
not prohibit, and near-cap retries could leave no submission turn. The final
implementation uses a dedicated exception, refuses correction-turn concurrency,
and gates retry on `hard_round_cap - rounds >= 2`. Unexpected non-`ValueError`
exceptions are restored and re-raised.

## Frozen-artifact exposure replay

The best v2 artifacts predate the contract schema, so their direct exposure
matrix contains 30 topics, 124 pre-draft commit batches, and 1,051 selected
units, but zero `facts` or `supports` rows. It cannot provide an observed
support-validation failure rate.

The closest frozen behavior is the complete 30-topic `v2l-dev30-facts` arm.
The offline replay maps every historical fact card exactly as follows and runs
the current lexical validator helpers plus an exact check against the local
chunk text:

```text
claim        = fact["claim"]
value_scope  = fact.get("scope", "")
must_include = [fact["value"]]
```

```bash
uv run --project tasks/search_serve python worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.py --output worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.json
```

The full row, batch, and topic matrices; all 60 input artifact paths and
hashes; the exact narratives; source-unit records; docstore manifest hash; and
method provenance are in
`worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.json`. The
reproducible script is beside it as
`worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.py`, and the
raw console result is
`worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.log`.

| replay outcome | rows | share of 1,223 |
|---|---:|---:|
| valid | 164 | 13.4% |
| exact value absent from claim/scope | 1,054 | 86.2% |
| malformed | 3 | 0.25% |
| rejected as generic | 1 | 0.08% |
| in claim/scope but absent from source | 1 | 0.08% |

In addition, 321/1,223 values (26.2%) exceed the validator's 80-character
normalization limit. At batch level, 78/83 contain at least one invalid mapped
row; the only five that would not expire are empty-fact batches. Thus immediate
whole-batch expiry would discard all 164 valid anchors as collateral in this
proxy.

This is deliberately an upper-bound failure proxy, not a forecast for the new
prompt: the historical fact prompt did not require the value to occur verbatim
inside its claim/scope, while the contract prompt does. It nevertheless proves
that lexical annotation mismatch is common in the closest saved model output,
and that preserving evidence for row-specific correction is materially safer
than tying one annotation error to irreversible whole-batch deletion. The
replay used zero network/API calls and cost $0.

## Exact offline scenarios

The scripted provider and real context ledger/search serialization exercise
these exact sequences in `tests/systems/test_aus_agent_v2.py`:

1. `plan -> search(P02) -> bad source-absent literal 12% -> corrected commit
   (traffic volumes + pre-toll baseline) plus forbidden parallel search ->
   cited submit(P01,P02)`.
2. `plan -> search(P02) -> generic-only reported annotation x3 -> expiry ->
   structural submit(P01), unresolved(P02)`.
3. With `safety_max_rounds=3` and finishing grace patched to one:
   `search -> invalid -> one preserved correction -> invalid near cap ->
   immediate expiry -> terminal unresolved submit`.
4. `normalize_commit_supports` patched to raise `RuntimeError`:
   the run ends failed, the original search result remains full text, and no
   compaction/rejection is recorded.

The first sequence also proves the forbidden second search did not reach the
retrieval stub, the correction tool result includes the retained unit id, and
only one provider compaction occurs after the corrected commit.

Focused verification:

```bash
bash scripts/test.sh tests/systems/test_aus_agent_v2.py
```

Result: **21 passed**, one live test deselected.

Final full-suite verification and its raw log are recorded after the final
implementation review in
`worklogs/assets/2026-08-06-aus-agent-v2-commit-retry-full-tests.log`.

```bash
bash scripts/test.sh
```

Result: **1,697 passed, 8 live tests deselected, zero skips or failures** in
16.02 seconds. The sole warning is Starlette's existing `httpx` test-client
deprecation warning.

Architecture regeneration/open:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open
```

Result: six systems, 18 shared edges, five engines. Raw log:
`worklogs/assets/2026-08-06-aus-agent-v2-commit-retry-architecture.log`.

## Acceptance gate

The target remains a comparable all-30 mean of at least 0.8. The budget-gated
parallel runner remains mechanically blocked under the exhausted cap. Once the
operator explicitly authorizes a new absolute total ceiling and in-flight
reserve, the only decision-grade test is all 30 topics through
`run_contract_one`, followed by the same three-pass Sol rubric grade; subsets
remain diagnostics only.
