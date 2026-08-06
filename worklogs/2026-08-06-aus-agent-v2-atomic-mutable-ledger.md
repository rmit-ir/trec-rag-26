# Atomic mutable coverage ledger and terminal evidence handoff

**Goal:** move the separate `aus_agent_v2` candidate toward a verified mean
rubric score of at least 0.80 on all 30 development topics by fixing the
planning, evidence-retention, and final-answer transitions that prevented
already-found content from reaching the answer.

**Outcome of this session:** implemented and hermetically verified a new
ungraded candidate architecture. No provider, retrieval, grader, or other paid
API call ran. The best verified comparable full-30 score therefore remains
**0.7042**. The tracked historical paid total remains **$1,096.72**, above the
standing $300 ceiling, so full-30 generation remains fail-closed pending an
explicitly revised absolute budget and in-flight reserve.

The confirmed `pipeline.run_one` model inputs and the original `aus_agent`
remain unchanged. All new behavior is selected only by
`run_lean_contract_one` or the three explicit candidate flags under
`src/systems/aus_agent_v2/`.

An AST comparison of `pipeline.run_one` against `HEAD` returned equality with
SHA-256 `3e3a234232d8aec43d7a194492af8a1d395bc8e7c4213602b32fcb75c5c6cb7b`
for both versions.

## Frozen inputs and audit provenance

The offline analyses used the current committed implementation
`e89fbe982ac9edf6ee2f30731e120102eff52388`, the exact 30-topic candidate
artifacts and three-repeat Sol rubric caches already on disk, and no network.

The four complete generation run ids used for the criterion union were:

| Alias | Exact run id |
|---|---|
| B | `v2-dev30-default` |
| P | `sol-aus-v2-research-first-pre-repair-dev30-20260806` |
| R | `sol-aus-v2-research-first-dev30-20260806` |
| A | `sol-aus-v2-adaptive-dev30-20260806` |

The rubric input was
`data/task-comparison/dev-rubrics-fixed.jsonl`; generation artifacts came from
`data/outputs/{aus_agent,aus_agent_v2}/*.output.json`; judge repeats came from
`data/task-comparison/rubric-eval/gpt-5.6-sol/`; the scored-run ledger was
`docs/auto-optimize/rubric-results.jsonl`.

Every exact query, planner row, rubric criterion, three raw verdicts, candidate
answer-item locator, artifact path, and hash is preserved in these assets:

- [atomicity script](assets/2026-08-06-aus-agent-v2-atomicity-audit.py),
  [complete JSON](assets/2026-08-06-aus-agent-v2-atomicity-audit.json), and
  [complete readable matrix](assets/2026-08-06-aus-agent-v2-atomicity-audit.log);
- [criterion-reachability script](assets/2026-08-06-aus-agent-v2-criterion-union-reachability.py),
  [complete 702-criterion matrix](assets/2026-08-06-aus-agent-v2-criterion-union-reachability.json),
  and [execution log](assets/2026-08-06-aus-agent-v2-criterion-union-reachability.log);
- [commit-anchor replay](assets/2026-08-06-aus-agent-v2-claim-closure-replay.json),
  [raw replay log](assets/2026-08-06-aus-agent-v2-claim-closure-replay.log),
  [summary script](assets/2026-08-06-aus-agent-v2-claim-closure-summary.py),
  [summary JSON](assets/2026-08-06-aus-agent-v2-claim-closure-summary.json),
  and [summary log](assets/2026-08-06-aus-agent-v2-claim-closure-summary.log);
- [complete commit-pinned terminal-context audit](assets/2026-08-06-aus-agent-v2-terminal-handoff-audit.md).

The principal offline commands were:

```bash
PYTHONPATH=src/systems:src uv run --group aus-agent-v2 python \
  worklogs/assets/2026-08-06-aus-agent-v2-atomicity-audit.py \
  --format json

PYTHONPATH=src/systems:src uv run --group aus-agent-v2 python \
  worklogs/assets/2026-08-06-aus-agent-v2-atomicity-audit.py \
  --format log

PYTHONPATH=src/systems:src uv run --group aus-agent-v2 python \
  worklogs/assets/2026-08-06-aus-agent-v2-criterion-union-reachability.py \
  --output worklogs/assets/2026-08-06-aus-agent-v2-criterion-union-reachability.json

uv run --project tasks/search_serve python \
  worklogs/assets/2026-08-06-aus-agent-v2-anchor-strict-replay.py \
  --output worklogs/assets/2026-08-06-aus-agent-v2-claim-closure-replay.json

uv run --no-project python \
  worklogs/assets/2026-08-06-aus-agent-v2-claim-closure-summary.py \
  --output worklogs/assets/2026-08-06-aus-agent-v2-claim-closure-summary.json
```

The terminal-context asset records its additional exact `git archive`, JSON
inspection, tokenizer, and aggregation commands verbatim. The new atomic
planner prompt was not sent to any model in this session; its exact untested
candidate text is versioned in `atomic_plan.py`.

## What the frozen evidence proves

### 1. The old plan rows were not executable atoms

Across all 30 promoted topics, the primary planner emitted 341 rows. A
transparent conservative clause/list heuristic flagged 310/341 (**90.9%**) as
compound, with 583 strict clause units and 2,643 likely obligation units. The
complete per-topic matrix is in the atomicity log; its aggregate is:

| Topics | Planner rows | Compound | Strict clause units | Likely units |
|---:|---:|---:|---:|---:|
| 30 | 341 | 310 | 583 | 2,643 |

The exact `e89fbe98` reproducer also showed that one Alpha anchor could close a
row requiring Alpha and Beta, a supported row could be discarded as
`unresolved`, a structural row could be discarded as `unresolved`, and exact
support found during a P01 search could not be mapped to P02.

Requiring every anchor was rejected as the fix: multiple anchors under one old
row are often alternatives or corroboration, and forcing all of them conflicts
with the three-citation/item and 1,024-word bounds. An atomic planner makes one
complete anchor choice meaningful without requiring every source.

### 2. The fixed ledger cannot reach the criterion union

Three-repeat Sol judgments, not lexical matching, determine every score below.
Lexical matching only diagnoses whether judged content has a route through a
row. The complete 702-criterion matrix is in the reachability JSON.

| Frozen ceiling | Mean |
|---|---:|
| Promoted P actual | 0.7042 |
| Current atomic-row preservation gate | 0.7070 |
| Current fixed row inventory, 0.5 representation gate | 0.7336 |
| All frozen planner/scout inventories | 0.7457 |
| Unlimited content-only oracle asymptote | 0.7935 |
| Four-core criterion union | 0.8048 |

There are 152 oracle-improved criteria: 143 rewards and 9 penalties, worth
195.5 signed numerator points. Their diagnosed preservation gaps overlap:

| Gap | Signed numerator gain implicated |
|---|---:|
| Planner/scout inventory omission | 136.67 |
| Criterion literals not fully declared | 91.17 |
| Count/list semantics not validated | 63.00 |
| Criterion scattered without one atomic row | 53.33 |
| Penalty rows not terminally enforced | 17.50 |
| Terminal form not authorized | 3.00 |

Under the deliberately optimistic assumption that each added row perfectly
selects one missing judged criterion, six typed dynamic rows from atomic rows
reach **0.8002**; five from the whole current inventory reach **0.8016**. These
are architecture-capacity upper bounds, not a model forecast or achieved score.
They establish that fixed content rows alone are insufficient and motivate a
bounded typed mutable ledger.

### 3. “Finish the claim” was not actually enforced

The old validator accepted a support card claiming “Traffic volumes fell by
12% ... in 2025” even when `must_include` omitted both `12%` and `2025`; the
end-to-end test source contained neither value. Thus final prose could satisfy
the contract while dropping the value/scope—or while the declared value had
never appeared in the source.

The frozen 1,223-card replay gives this exact transition matrix:

| Old outcome | New outcome | Rows |
|---|---|---:|
| malformed | malformed | 3 |
| out of claim/scope | out of claim/scope | 734 |
| oversized term | oversized term | 321 |
| source missing | scope not carried | 1 |
| valid | quantitative/date literal not carried | 19 |
| valid | scope not carried | 123 |
| valid | valid | 22 |

Only 22/164 formerly “valid” cards formed a complete executable invariant.
This replay is counterfactual over cards produced by the old schema, so it is
not a score forecast. It does prove that extracted facts and the old
finish-the-claim validator were different objects.

### 4. The final evidence transition was missing

The exact current path validates a direct `submit_answer` immediately. The
existing status recap shows only two anchors per row and stops at 6,000
characters; invalid-submission feedback previously replayed only errors. In the
30-topic control proxy, mean first-draft input was about 76,363 tokens and the
pre-draft peak about 109,482, so facts present somewhere in long history were
not a useful recency handoff. The fact-card proxy carried an exact value in only
92/1,223 cards (7.5%). Full per-topic input sizes, staged/compacted bytes, and
anchor-recap omissions are in the terminal audit.

## Implemented candidate architecture

### Structured atomic planning

`atomic_plan.py` adds an isolated JSON planner used only by the lean contract
candidate. It requires 10--24 rows, one binary obligation each, at most four
typed `avoid` rows, explicit `minimum_count`, request-derived research flags,
and all-or-nothing normalization. It rejects multi-sentence/semicolon rows,
obvious serial lists or coordinated directives, overlong strings, excess
terms, malformed JSON, duplicate-inflated inventories, and unknown fields.

The planner explicitly does **not** authorize Markdown, headings, tables,
bullets, numbering, labels, or code. Broad Markdown remains disabled in line
with the author-baseline audit. Only the existing untouched-request gates for a
literal blog-post series and explicit Python request can create typed form
items. The research prompt receives the compiled executable contract once;
the old duplicate prose-plan handoff is omitted on this candidate path.

### Typed mutable rows

`ContractItem` now carries `mode`, `minimum_count`, and `must_avoid`:

- `assert` rows require the declared number of distinct tagged answer items;
- `avoid` rows are global constraints, cannot be tagged or unresolved, and
  reject their exact forbidden terms;
- `form` remains owned by the deterministic untouched-request gate.

When enabled, `commit_context` must also decide a `promotions` array. It may add
at most two rows from one batch and six per topic. Each Dxx row must be one
bounded request-material obligation tied to a selected staged source and a
complete source-verbatim claim/scope anchor. Invalid promotion batches are
rejected intact for the existing bounded correction loop. The assigned Dxx ids
are returned in the commit result and immediately join later search, handoff,
validation, and trace state.

The search `for_requirements` list is now an auditable purpose record rather
than an evidence ACL. A selected page can support another known row only when
every exact anchor literal occurs in that page. This preserves source grounding
while retaining useful cross-row facts discovered by a differently purposed
query.

### Correct claim closure

Every numeric/date literal in a declared commit claim or scope must also occur
inside `must_include`, and every nonempty scope must contribute at least one
exact final-answer invariant. The existing route check then requires every
selected invariant in the staged source, and terminal validation requires all
invariants from one mapped anchor in the same cited answer item. Supported
research rows and structural rows can no longer escape through `unresolved`.

### Mandatory terminal evidence handoff

The first protocol-valid `submit_answer` call no longer becomes the final
answer on the candidate path. It returns a non-error tool result containing
every answer row, its minimum count and required literals, all avoidance rows,
open/search state, and up to four complete anchor choices per supported row.
The draft arguments from that first call are not evaluated. The same evidence-
owning researcher then submits the actual answer on the following turn. Failed
later submissions receive the same handoff alongside exact validation errors.

This adds one same-context generation turn, not a fresh writer or selector.
The finishing grace already reserves ten turns, and an end-to-end scripted
test proves a retrieved fact can be promoted as D01, replayed in the mandatory
handoff, and required in the accepted terminal answer.

## Verification

Focused command and result:

```bash
bash scripts/test.sh tests/aus_agent_v2/test_atomic_plan.py \
  tests/aus_agent_v2/test_coverage_contract.py \
  tests/systems/test_aus_agent_v2.py
# 73 passed, 1 deselected in 0.28s
```

Full hermetic command and result:

```bash
bash scripts/test.sh
# 1725 passed, 8 live tests deselected, 1 warning in 16.62s
```

The compact preserved log is
[here](assets/2026-08-06-aus-agent-v2-atomic-mutable-ledger-tests.log).

Architecture refresh:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open
# wrote docs/architecture.html (6 systems, 18 edges, 5 engines)
```

The refresh log is
[here](assets/2026-08-06-aus-agent-v2-atomic-mutable-ledger-arch-viz.log).

No experiment process remains. The pre-existing `tasks/search_serve` gunicorn
service was not started or modified by this work.

## Decision gate

The exact full-30 runner now selects all three candidate switches:

```text
--atomic-contract-plan --dynamic-contract-rows --terminal-evidence-handoff
```

It remains resumable and parallel by topic, but refuses paid execution unless
all 30 topics are in scope and the operator explicitly supplies
`RUN_PAID_EXPERIMENT=YES`, a new absolute
`AUTHORIZED_TOTAL_BUDGET_USD` above the tracked historical total, and a
positive `IN_FLIGHT_RESERVE_USD`. The only evidence that can verify the goal is
a complete 30-topic generation followed by three rubric-judge repeats. No
subset or oracle ceiling will be reported as the achieved score.
