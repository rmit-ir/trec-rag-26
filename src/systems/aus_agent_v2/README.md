# Research agent v2

`aus_agent_v2` is a separate experimental system built around the stable
`aus_agent` research loop. It retrieves only from ClimbMix and writes its own
artifacts under `data/outputs/aus_agent_v2/`.

## Design

```text
request
  -> isolated coverage plan
  -> atomic obligation scout -> exact terms + crossed evidence requirements
  -> staged-context search / commit loop
       search returns each top hit plus adjacent document pages
  -> complete cited research draft
  -> deterministic citation mapping
  -> trajectory.json + output.json
```

This promoted default scored **0.7042 on all 30 development topics**, compared
with 0.6508 for the Sol baseline. The obligation scout deliberately sees only
the request, not the first plan, and may add at most eight atomic checks. Named
laws, standards, mechanisms, tools, and metrics are carried into the original
evidence-owning context; that same context researches and writes the answer, so
evidence relationships are not fragmented across workers or lost in a final
handoff.

The package retains several experimental stages behind explicit flags:
observable-unit scouting, priority reconciliation, post-draft coverage
verification/research repair, citation-local line patching, and the
commit-fact-backed answer blueprint. These are off by default because none beat
the lean architecture on a complete 30-topic run. The blueprint did demonstrate
that commit-time facts can reach final prose—184 of 191 planned claims carried
through on its eight-topic mechanism test—but its effect depended strongly on
request shape and its routed full-30 confirmation was stopped at 22 topics by
the experiment budget cap.

The next candidate replaces that permissive blueprint with a harness-owned
atomic, mutable coverage contract:

```text
structured atomic plan + independent scouts -> stable Pxx/Sxx obligation ids
  -> search(for_requirements=[...])
  -> commit_context(supports=[requirement + extractive claim/source quote
                               + scope + exact literals])
       optionally promotes at most six evidence-backed Dxx obligations
  -> bounded closure status after every commit
  -> first submit opens a harness-owned terminal evidence replay
  -> submit_answer(typed answer items + evidence ids + satisfied ids)
  -> deterministic distinct-count/avoid/form/syntax/source-locality/citation
     validation
  -> optional fresh semantic row audit of the post-handoff final submission
       clear reject -> one submit-only correction by the same researcher
       pass/abstain/provider fault -> bounded terminal decision, never a loop
  -> map + save
```

This is a claim-union architecture, not a completed-answer selector. Offline
three-pass verdict caches show why: a perfect whole-answer selector over the
four complete core architectures reaches only 0.7445, while their
criterion-by-criterion union reaches 0.8048 (all eight Sol-written runs reach
0.8284). The contract attempts to assemble complementary obligations before
one draft. An offline audit of the exact promoted 30-topic planner outputs
found that 310/341 rows (90.9%) bundled multiple likely checks, so the
candidate-specific planner now returns 10--24 structured atomic rows instead
of prose bundles. Retrieval may add at most two request-material rows per
commit and six per topic, giving genuinely post-plan facts an executable route
into the answer rather than leaving them as inert commit metadata.

The planner inventory is transported through a dedicated
`submit_atomic_plan` tool rather than parsed from free text. Runtime validation
is all-or-nothing and returns row-specific diagnostics; the same isolated
planner gets at most three attempts to replace the complete inventory. Raw JSON
and partial patches are rejected, so provider formatting cannot silently erase
an obligation before research begins.

It also fixes the old blueprint's central validation defect: every
must-answer plan row must be satisfied or explicitly unresolved, search and
commit support are tied to the same stable row, exact scout terms are checked,
and a citation is accepted for a row only when the cited committed unit was
explicitly mapped to it. Each anchor claim is copied verbatim inside one
contiguous source quote, and claim, scope, and exact carry-through terms must
all occur in that same local span. The final answer is the terminal tool call
itself, so there is no second writer. The first otherwise-valid submission is
deliberately intercepted: the harness replays every answer row, count,
avoidance constraint, and one complete local source quote per row, and the same
researcher submits the real answer on the next turn. This closes the missing
commit-to-answer state transition without restoring the old undifferentiated
22--35 KB fact dump.

Frozen three-repeat rubric verdicts quantify why these changes are structural,
not prompt decoration. The fixed current row inventory has an optimistic
0.7336 ceiling and all frozen planner/scout inventories together reach 0.7457.
Content-only rows asymptote at 0.7935. An ideal typed mutable ledger reaches
0.8002 with six added rows (0.8016 with five when reusing the full inventory).
Those figures are oracle upper bounds, not an achieved candidate score; the
best verified complete 30-topic run remains 0.7042 until this exact pipeline is
generated and graded on all 30 topics.

Broad Markdown remains disabled because the author baselines almost never use
it and factual table cells complicate citation locality. The untouched request
can authorize only two narrow typed forms: a literal blog-post series receives
distinct uncited labels such as `Blog post 1 — ...`, with cited factual prose
in adjacent items; an explicit Python-code request receives raw multiline code
that bypasses prose cleanup and must compile before acceptance. Every selected
finish-the-claim literal is boundary-matched in the declared claim/scope, the
staged source, and the final cited prose.

Anchor strings are accepted exactly or rejected; the harness never turns a
long value into a different invariant by silently slicing it. Claims, scopes,
term counts, and term lengths are bounded in both the advertised tool schema
and runtime validation. A mixed valid/invalid term list rejects the whole
support row for bounded correction, while exact negative findings such as
"no evidence" remain material when they occur in claim, source, and answer.
Every numeric/date literal stated in a commit claim or scope must be one of the
final-answer invariants, and a nonempty scope must contribute an exact
invariant. Submitted prose items are restricted to one sentence so one
citation set cannot launder an unsupported second claim, while one sentence
may still close overlapping rows. Requested minimum counts use distinct
normalized item text rather than raw array length. A source-valid page may
support any known row regardless of the
query purpose that happened to find it; purpose ids remain an audit/search
record, not an evidence ACL.

If only the contract support annotation is invalid, the full staged evidence
is not destroyed immediately. The harness returns the exact validation errors
and permits two correction turns using the same batch; a valid correction
compacts it exactly once, while a third invalid attempt or insufficient
submit-answer headroom expires it. Searches and submission are refused on a
correction turn, and unexpected implementation/provider errors remain fatal.

The `run_lean_contract_one` candidate removes a separate pipeline defect: the
legacy 2,541-word research prompt told the model to plan again and end in free
prose even after isolated planning and a typed `submit_answer` contract had
already been installed. Its 417-word replacement states the research outcome
and evidence invariants once; the executable contract and tool schemas own the
detailed row, correction, and terminal mechanics. This is a separate ungraded
candidate, not a change to the 0.7042 `run_one` control. The candidate selects
the atomic planner, bounded dynamic rows, and mandatory terminal handoff
together.

`run_semantic_contract_one` adds the missing meaning check without adding a
second answer writer. After the same researcher receives the terminal source
replay and submits the actual final answer, a fresh provider sees only the
original request, typed answer items, one aggregate packet per asserted row,
and the exact local quotes mapped to that row. It judges closure, source
support, scope, evidence type, and semantic distinctness for `MIN > 1`. The
typed verifier cannot request research, edit prose, or impose Markdown. Only a
clear material rejection is actionable; uncertainty abstains and malformed or
provider failures fail open.

A rejection returns row and answer-item diagnostics to the evidence-owning
conversation for exactly one correction. Every unflagged item and the
unresolved inventory must remain byte-for-byte unchanged. The corrected
submission is deterministically revalidated and semantically rechecked;
persistent rejection or an invalid repair retains the complete pre-repair
baseline instead of triggering a destructive rewrite loop. This candidate is
still ungraded and does not replace the verified `run_one`.

The system reuses `aus_agent.context`, `aus_agent.providers`, and
`aus_agent.tools`. Planning, evidence-card construction, patch validation,
orchestration, output namespace, and tests are owned here.

## Run

From the repository root:

```bash
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --backend openai --model openai.gpt-5.6-sol \
  --qid 683a58c9a7e7fe4e76958498 \
  --run-id sol-aus-v2-probe
```

Coverage planning and the atomic expectation scout are enabled by default; all
post-draft editors and the additional scouts are off. Retrieval returns 20
ranked units per search and the runaway-loop safety ceiling is 40 turns, matching
the confirmed full-30 run. Use
`--no-coverage-plan` or `--no-coverage-scout` for the two default-stage
ablations. Experimental stages are enabled individually with
`--observable-scout`, `--plan-reconcile`, `--coverage-verify`,
`--finish-review`, or `--answer-blueprint`. The lean contract candidate uses
the independent observable scout and can be launched with:

```bash
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --backend openai --model openai.gpt-5.6-sol \
  --coverage-contract --observable-scout \
  --atomic-contract-plan --dynamic-contract-rows \
  --terminal-evidence-handoff \
  --prompt-variant contract-lean \
  --qid 683a58c9a7e7fe4e76958498 \
  --run-id sol-aus-v2-lean-contract-probe
```

Add `--semantic-closure-verify` to run the post-handoff semantic candidate, or
call `pipeline.run_semantic_contract_one`. The flag requires the terminal
handoff and is deliberately off for the verified default and lean candidates.

It is intentionally not the `run_one` default until a complete comparable
30-topic generation and three-pass grade beats 0.7042.

The full-30 candidate has a separate resumable parallel runner. It still
evaluates all 30 topics; `CONCURRENCY=6` means six independent topics are in
flight, not that a six-topic subset is scored. Paid execution is fail-closed:
the runner requires explicit total-budget and in-flight-reserve authorization,
and the standing $300 cap currently blocks it before any worker launches.

```bash
RUN_PAID_EXPERIMENT=YES \
AUTHORIZED_TOTAL_BUDGET_USD=<explicit-new-total-cap> \
IN_FLIGHT_RESERVE_USD=<explicit-reserve> \
CONCURRENCY=6 \
tasks/task-comparison/scripts/run_aus_agent_v2_parallel.sh
```

## Tests

```bash
bash scripts/test.sh tests/systems/test_aus_agent_v2.py
bash scripts/test.sh
```

The offline system tests use the shared scripted provider and retrieval stub.
The live-marked test exercises the real search and provider path only when
explicitly requested.
