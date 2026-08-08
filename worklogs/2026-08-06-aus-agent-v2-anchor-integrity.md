# aus_agent_v2 exact anchor integrity

Date: 2026-08-06

## Outcome

This offline session fixed two correctness defects in the ungraded
aus_agent_v2.run_contract_one finish-the-claim path:

1. A must_include value longer than 80 normalized characters was silently
   sliced and the prefix could become the enforced final-answer invariant.
2. When one must_include list mixed valid and invalid terms, the invalid terms
   were silently dropped and the row was accepted with different semantics.

The contract now accepts an anchor string exactly or rejects the whole support
row for the bounded correction path. The JSON tool schema and runtime both
bound claim, scope, term count, and term length. Runtime errors report the
actual normalized length and ask for a shorter complete source-verbatim
fragment. Exact negative findings such as "no evidence" are material when the
whole phrase occurs in the declared claim/scope, routed source, and final cited
answer.

No provider, search service, Bedrock, OpenAI, or grader call was made. Spend
remains $1,096.72 against the $300 ceiling, and the best verified complete
30-topic score remains 0.7042. This is an ungraded candidate correction, not a
score claim.

## Why this is part of finish-the-claim

The final answer validator promises to preserve model-selected names, values,
dates, populations, and scopes from source to prose. Silently changing a
selected string violates that promise even when the resulting prefix happens
to match. Silently deleting one member of a mixed list is the same class of
error: trace state says the model requested several invariants, while the
ledger enforces fewer.

The runtime now has one atomic rule:

~~~text
every supplied support row is valid
  -> record exactly its normalized, unsliced literals
any supplied literal is invalid
  -> record none of the row; preserve staged evidence for bounded correction
~~~

The 80-character term bound remains deliberate. A finish-the-claim anchor is a
short exact fact component, not a copied paragraph. The defect was silent
prefix acceptance, not the existence of a bound.

## Exact frozen input and mapping

The input is the complete prior 30-topic, 83-batch, 1,223-row fact-card matrix:

worklogs/assets/2026-08-06-aus-agent-v2-commit-validator-replay.json

Every row is mapped verbatim to one valid replay route:

~~~text
requirement_id = "P01"
claim          = fact["claim"]
value_scope    = fact.get("scope", "")
must_include   = [fact["value"]]
~~~

The current public normalize_commit_supports and validate_support_routes
functions are then run against the exact local chunk text from
data/built-indexes/climbmix-chunked/docstore.

Exact command:

~~~bash
uv run --project tasks/search_serve python worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.py --output worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.json
~~~

The reproducible script is
worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.py. The complete
row, batch, and 30-topic matrices, every exact narrative and fact card, source
and artifact hashes, errors, and normalized anchors are in
worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.json. Raw console
output is in
worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.log.

## Complete replay result

| current outcome | rows | share |
|---|---:|---:|
| valid | 164 | 13.4% |
| exact value outside claim/scope | 734 | 60.0% |
| explicit oversize rejection | 321 | 26.2% |
| malformed | 3 | 0.25% |
| exact value absent from source | 1 | 0.08% |

The old-to-new exhaustive transition matrix is:

| previous outcome | current outcome | rows |
|---|---|---:|
| generic | valid | 1 |
| malformed | malformed | 3 |
| outside claim/scope | outside claim/scope | 734 |
| outside claim/scope | oversize | 320 |
| source missing | source missing | 1 |
| valid | oversize | 1 |
| valid | valid | 163 |

The generic-to-valid row is the substantive conclusion "no evidence" from a
global Facebook/wellbeing study. The previously valid-to-oversize row is a
148-character list of investment-fraud warning signs. Before this fix, the
validator silently enforced only its first 80 characters. It now asks the
model to select short complete exact fragments instead.

As before, 78/83 historical batches contain an invalid counterfactual row. This
is why this strict behavior depends on the bounded evidence-preserving
correction state committed immediately before it. The five nominally committing
batches contain no fact rows. The proxy is not a forecast for the new prompt:
historical fact extraction did not request short verbatim claim overlap, while
the current tool schema does.

## Model-specific prompt decision

The live OpenAI GPT-5.6 model guidance was checked because this is a model-facing
tool change:

https://developers.openai.com/api/docs/guides/latest-model

Its prompt guidance recommends lean prompts, one statement of each instruction,
task-relevant tools, and concise precise tool descriptions. It also says to
preserve explicit structured-output and tool contracts. The implementation
therefore changes only the support field schema and its single description; it
does not add another system-prompt section or repeat the invariant elsewhere.
The provider already uses the Responses API and replays encrypted reasoning
items for stateless multi-turn tool use.

## Implementation and verification

- coverage_contract.py advertises and enforces 500 claim characters, 300 scope
  characters, four terms, and 80 characters per term.
- Oversize claims, scopes, support arrays, and term arrays are rejected instead
  of sliced.
- Any invalid member rejects its full support row.
- Source-verbatim multi-token negative findings remain material.
- README.md documents the exact-or-reject behavior.
- pipeline.py and docs/architecture.html show the unsliced-anchor commit stage.
- Tests pin schema/runtime parity, mixed-term atomic rejection, the Facebook
  negative finding, oversize rejection, and the existing end-to-end correction
  state.

Focused command:

~~~bash
bash scripts/test.sh tests/aus_agent_v2/test_coverage_contract.py tests/systems/test_aus_agent_v2.py
~~~

Result: 50 passed, one live test deselected.

The final full-suite result and raw log are recorded after final review in:

worklogs/assets/2026-08-06-aus-agent-v2-anchor-integrity-full-tests.log

Final result: 1,700 passed, eight live tests deselected, zero skips or
failures, and one existing Starlette/httpx deprecation warning in 16.85
seconds.

Architecture command:

~~~bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system aus_agent_v2
~~~

Result: six systems, 18 shared edges, five engines; the deep-linked v2 diagram
was launched. Raw log:
worklogs/assets/2026-08-06-aus-agent-v2-anchor-integrity-architecture.log.

## Acceptance gate

The target remains a comparable complete 30-topic mean of at least 0.8. The
contract candidate still requires a paid all-30 run and the same three-pass Sol
rubric grade. That execution remains prohibited until the operator establishes
a new absolute total ceiling above already-recorded spend plus an in-flight
reserve.
