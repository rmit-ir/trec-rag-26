# aus_agent_v2 post-handoff row-semantic verifier

Date: 2026-08-06

Objective: move the best verified complete development score from `0.704159`
toward `>=0.8` by fixing a demonstrated pipeline defect: evidence and exact
terms can reach the final context while a tagged sentence still does not answer
the requirement or overstates its cited source.

Incremental paid cost: **$0.00**

Recorded cumulative cost at the end of this session: **$1,096.72**
(`$961.77` generation + `$134.95` judging). The operator's absolute `$300`
ceiling is already exceeded, so no Bedrock/OpenAI, search, or grading request
was issued. `goal_status.py --budget 300` returned `BUDGET EXCEEDED` and the
full-30 runner remains fail-closed.

Verified score status: **not changed**. The best complete 30-topic result
remains `0.7042`; this architecture is implemented and hermetically verified
but has not been generated or graded on the development set.

## Evidence and hypothesis

The preceding frozen full-30 semantic-risk audit is preserved at
`worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.json` and
documented in
`worklogs/2026-08-06-aus-agent-v2-source-locality-and-semantic-closure.md`.
Its complete matrix showed:

- generic or unrelated content passed all `540/540` old closure rows;
- requirement parroting also passed `540/540`;
- `392/540` accepted generic rows contained no requirement content token;
- a `0.10` lexical gate falsely rejected `68/345` unanimously satisfied
  criteria, and `0.20` falsely rejected `192/345`.

Therefore another overlap threshold is contraindicated. The intervention is a
fresh, conservative model judgment over the exact post-handoff final answer,
one aggregate packet per contract row, with no answer-writing authority.

## Architecture implemented

The separate candidate is `pipeline.run_semantic_contract_one`; the verified
`run_one`, `run_contract_one`, and `run_lean_contract_one` defaults remain
unchanged.

```text
atomic plan -> research/search/commit -> source-local evidence ledger
  -> valid preview opens mandatory terminal evidence handoff
  -> same researcher submits the actual final typed answer
  -> deterministic validation
  -> fresh row-semantic verifier
       pass: accept
       abstain or malformed/provider failure: fail open
       clear reject: return diagnosis to the same researcher
         -> exactly one submit_answer-only correction
         -> deterministic revalidation + fresh semantic recheck
            pass: accept correction
            abstain: accept preservation-safe correction, unverified
            reject/malformed/invalid correction: retain original valid baseline
  -> citation mapping + save
```

The verifier runs after the real post-handoff submission. Checking the preview
would be incorrect because the subsequent final submission could change
without being audited.

One record is built per asserted row, not per sentence-row pair:

- `row_item` for one ordinary candidate item;
- `row_aggregate` for multiple tagged items or `minimum_count > 1`;
- `answer_global` for audience and broad deliverable rows.

The packet contains the original request once, the complete typed answer once,
candidate item indices per row, and only mapped contiguous source quotes whose
document is cited by that item and whose exact carry-through terms occur in
the item. Form and avoidance rows remain deterministic; legitimately unresolved
research rows have no asserted answer relationship to audit.

The typed labels separate three questions:

- closure: `complete|partial|unrelated|meta_only|unclear`;
- support: `direct_entailment|joint_entailment|supported_synthesis|partial|`
  `unsupported|contradicted|not_applicable|unclear`;
- count: `met_distinct|not_met|semantic_duplicates|not_applicable|unclear`.

Only `reject` is actionable. Ambiguity must be `abstain`. Output is
all-or-nothing: an unknown, missing, or duplicate row id, companion prose,
wrong tool, inconsistent label set, out-of-scope answer index, or out-of-scope
evidence id makes the whole audit indeterminate and preserves a valid answer.

The correction path is destructive-rewrite resistant. The correction must
retain the same answer-item count/order and unresolved inventory, and every
unflagged answer item must be byte-for-byte equal to the baseline. There is one
main-writer correction turn and at most two fresh verifier calls per topic.
Persistent rejection retains the complete baseline; it never triggers a third
rewrite.

The verifier system/tool are recorded in `trace.input`. Summary fields record
checks, attempts, failures, abstentions, parse errors, packet/raw character
counts, correction count, fallback, final verification, and complete audit
history. Native verifier tool calls are parent-linked in the trajectory so
their provider usage and cost are not hidden.

## Exact offline scenario inputs and full outcomes

All exact provider turns and typed tool arguments persist verbatim in
`tests/systems/test_aus_agent_v2.py`; no ad-hoc prompt or transcript is needed
to reproduce them.

Common request:

```text
How effective is congestion pricing at reducing traffic?
```

Exact source quote and invariants:

```text
early reporting showed traffic volumes below the pre-toll baseline.
USE EXACT: traffic volumes; pre-toll baseline
SCOPE: pre-toll baseline
```

Exact flawed final item:

```text
For a general reader, traffic volumes fell below the pre-toll baseline, proving pricing permanently eliminates congestion.
```

Exact corrected item:

```text
For a general reader, early reporting showed traffic volumes below the pre-toll baseline.
```

Exact hard-reject diagnosis:

```text
The quote supports the observed baseline comparison, not permanent elimination of congestion.
```

| Offline end-to-end arm | Verifier sequence | Main correction turns | Saved first item | Outcome |
|---|---:|---:|---|---|
| clear overclaim repaired | `repair -> pass` | 1 | corrected item above | pass, `final_verified=true` |
| persistent hard rejection | `repair -> repair` | 1 | original flawed but deterministic-valid baseline | bounded fallback, no third turn |
| malformed verifier prose (`pass`) | `indeterminate` | 0 | original deterministic-valid baseline | fail open, no loop |

The second arm intentionally scripts a repeated rejection even after the
correction. It tests bounded safety, not the semantic merit of retaining the
known overclaim. In a real call, the high-precision prompt should pass the
narrowed correction; calibration is still required before claiming that.

The complete 16-test unit matrix also passed:

| Unit boundary | Result |
|---|---|
| typed answer projection/order/bounds | pass |
| multi-item row aggregation and distinct count state | pass |
| one shared sentence projected independently to two rows | pass |
| unrelated mapped quote excluded from row evidence | pass |
| mixed pass/reject/abstain inventory normalized in row order | pass |
| research pass with invalid support label rejected | pass |
| uncertain hard reject rejected in favor of abstention | pass |
| abstention with repair targets rejected | pass |
| missing row id invalidates full response | pass |
| duplicate row id invalidates full response | pass |
| unknown row id invalidates full response | pass |
| only flagged answer item may change | pass |
| answer item count/order remains stable | pass |
| unresolved inventory remains stable | pass |
| complete compact packet and 60,000-character hard bound | pass |
| prompt/tool expose the strict bounded no-rewrite protocol | pass |

## Verification commands and results

```bash
bash scripts/test.sh tests/systems/test_aus_agent_v2.py -k 'semantic or full30_runner or run_script_imports'
# 6 passed, 27 deselected

bash scripts/test.sh tests/aus_agent_v2 tests/systems/test_aus_agent_v2.py
# 197 passed, 1 deselected

bash scripts/test.sh
# 1766 passed, 8 live deselected, 1 warning

python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open
# wrote docs/architecture.html (6 systems, 18 edges, 5 engines)

python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check
# docs/architecture.html is up to date (6 systems)
```

All tests were hermetic: scripted providers, fake retrieval, no credentials,
network, search service, or paid model.

## Exact paid evaluation gate (prepared, not executed)

The resumable runner now selects run id
`sol-aus-v2-semantic-contract-dev30` and supplies
`--semantic-closure-verify`. It refuses any topic count other than 30, monitors
historical token-priced generation plus judge spend, stops before the
operator-provided in-flight reserve, and terminates exact worker process groups
at the limit.

```bash
RUN_PAID_EXPERIMENT=YES \
AUTHORIZED_TOTAL_BUDGET_USD=<explicit-new-absolute-total-cap> \
IN_FLIGHT_RESERVE_USD=<explicit-reserve> \
CONCURRENCY=6 \
tasks/task-comparison/scripts/run_aus_agent_v2_parallel.sh
```

This command was not executed because `$1,096.72 >= $300`. A comparable score
claim requires generation and grading on all 30 topics; a subset is not
comparable and no score is inferred from these offline tests.

## Remaining calibration gate

Before treating the verifier as a generally safe production gate, its reject
precision should be measured on a topic-disjoint holdout containing confirmed
positive rows, generic and requirement-parroting negatives, scope/number/
contradiction cases, joint support, supported synthesis, multi-source
comparisons, multi-row sentences, semantic duplicate counts, normative
synthesis, and incomplete packets. The proposed activation thresholds are:

- `>=95%` reject precision;
- no false rejection in explicit safeguard cases;
- `<=2%` false rejection on manually confirmed positives;
- `>=90%` rejection of generic/meta negatives;
- `>=80%` rejection of partial/overclaim negatives.

Those are future paid measurements, not achieved results.
