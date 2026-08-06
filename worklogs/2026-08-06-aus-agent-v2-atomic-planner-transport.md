# AUS agent v2 atomic planner transport hardening

## Outcome

The ungraded `run_lean_contract_one` candidate now obtains its 10--24 atomic
coverage rows through a native `submit_atomic_plan` tool and a bounded
three-attempt correction protocol. The runtime no longer accepts raw JSON,
JSON encoded inside tool arguments, legacy mode-specific tool rows, prose next
to a tool call, or duplicate requirement text. Every accepted or rejected
planner call receives a provider tool result and appears in trajectory action
counts.

This is architecture hardening, not a score result. The best verified all-30
development score remains **0.704159**; the requested **0.8** target is not yet
verified. No provider, retrieval, or grader call was made in this session, so
added spend is **$0** and tracked cumulative paid cost remains **$1,096.72**.
Paid execution remains stopped under the standing $300 cap.

## Why this was necessary

The first atomic-planner implementation asked the model for free-text JSON and
failed the topic if any row violated the contract. A transport correction then
added a tool but initially left several paths that could make the method appear
ineffective or unreliable:

- valid raw JSON could cross the boundary without using the tool;
- a string containing encoded JSON could be parsed again inside tool arguments;
- legacy rows missing common-schema fields could still normalize;
- prose beside an otherwise-valid tool call was ignored;
- duplicate requirement wording was silently dropped even when anchors, kind,
  or count differed;
- accepted and third-failed native calls were archived without matching tool
  results;
- failed planning runs omitted the planner prompt, schema, request, and earlier
  diagnostics from root trace input;
- planner tool attempts were absent from tool-call counts.

The final implementation closes each path rather than relying on provider-side
JSON Schema enforcement. Local validation remains authoritative because the
common schema cannot express all mode-dependent invariants uniformly across
both providers.

## Implemented behavior

`src/systems/aus_agent_v2/atomic_plan.py` now defines the native tool schema
and two deliberately separate compatibility boundaries:

- `normalize_atomic_plan_value` accepts only the common native-tool object
  shape and returns actionable all-or-nothing diagnostics;
- `normalize_atomic_plan` remains only for parsing frozen pre-tool audit inputs
  in the old mode-specific JSON representation.

`src/systems/aus_agent_v2/agent.py` now:

1. starts the isolated planner with only `submit_atomic_plan`;
2. requires exactly one call with no companion prose;
3. validates every row without truncating or silently deleting it;
4. returns all diagnostics to the same isolated planning context;
5. permits at most three complete-inventory attempts;
6. answers every native call, including success and the final failed attempt;
7. records each call as a child of its generation span, with failed/successful
   counts separated;
8. preserves the prompt, request, tool schema, attempt count, and accumulated
   diagnostics even when planning terminates the topic.

The architecture model and README now expose the planner tool and correction
boundary. The verified `pipeline.run_one` control was not changed: its AST SHA
is still
`3e3a234232d8aec43d7a194492af8a1d395bc8e7c4213602b32fcb75c5c6cb7b`,
identical to `HEAD` before this work.

## Hermetic behavior matrix

- One valid common-shape tool call: accepted, answered, counted, and compiled.
- Free-text raw JSON, then an invalid row, then a valid tool call: two precise
  corrections followed by success on attempt three.
- JSON text nested in tool arguments: rejected without a second parse.
- Valid arguments plus companion prose: rejected.
- Legacy mode-specific arguments missing common fields: every row rejected.
- Duplicate requirement wording: the complete inventory is rejected with both
  row positions instead of dropping one row.
- Three invalid native calls: all three receive error results; the topic fails
  with all diagnostics and the full planner contract in its trace.
- Valid planning through retrieval promotion and mandatory terminal evidence
  handoff: completes with the planner result balanced in archived history.

## Verification

Focused candidate tests:

```bash
bash scripts/test.sh tests/aus_agent_v2/test_atomic_plan.py tests/systems/test_aus_agent_v2.py
```

Result: **43 passed, 1 live test deselected**.

Required full hermetic suite:

```bash
bash scripts/test.sh
```

Result: **1,733 passed, 8 live tests deselected, 1 existing deprecation
warning**, in 18.99 seconds.

Architecture regeneration and launch:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open
```

Result: `docs/architecture.html` regenerated with 6 systems, 18 edges, and 5
engines, then launched locally. Its v2 planning stage now includes
`submit_atomic_plan`.

No experiment or test process was left running. Broad Markdown remains
disabled, and the model-visible candidate system prompt continues to identify
the model only as a **research agent**, without an Australian locale cue.

## Next score gate

The method remains an ungraded candidate until it is generated and judged on
all 30 development topics. That run must use the resumable full-30 harness; a
subset is not comparable. It cannot be launched under the current paid cap
because tracked spend already exceeds it. A new explicit absolute total ceiling
above $1,096.72, plus an in-flight reserve, is required before any paid worker
starts.
