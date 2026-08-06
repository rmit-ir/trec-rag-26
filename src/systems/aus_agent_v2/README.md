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
coverage contract:

```text
plan + independent scouts -> stable Pxx/Sxx obligation ids
  -> search(for_requirements=[...])
  -> commit_context(supports=[requirement + claim + value/scope])
  -> bounded closure status after every commit
  -> submit_answer(sentences + evidence ids + satisfied obligation ids)
  -> deterministic completeness/citation validation -> map + save
```

This is a claim-union architecture, not a completed-answer selector. Offline
three-pass verdict caches show why: a perfect whole-answer selector over the
four complete core architectures reaches only 0.7445, while their
criterion-by-criterion union reaches 0.8048 (all eight Sol-written runs reach
0.8284). The contract attempts to assemble complementary obligations before
one draft. It also fixes the old blueprint's central validation defect: every
must-answer plan row must be satisfied or explicitly unresolved, search and
commit support are tied to the same stable row, exact scout terms are checked,
and a citation is accepted for a row only when the cited committed unit was
explicitly mapped to it. The final answer is the terminal tool call itself, so
there is no second writer and no 22–35 KB fact replay.

Broad Markdown remains disabled because the author baselines almost never use
it and factual table cells complicate citation locality. When the request asks
for a series, the contract permits a safe plain label prefix on each part's
opening sentence, such as `Blog post 1 — ...`; factual content and citations
stay in that same answer item.

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
`--finish-review`, or `--answer-blueprint`. The contract candidate uses the
independent observable scout and can be launched with:

```bash
uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \
  --backend openai --model openai.gpt-5.6-sol \
  --coverage-contract --observable-scout \
  --qid 683a58c9a7e7fe4e76958498 \
  --run-id sol-aus-v2-coverage-contract-probe
```

It is intentionally not the `run_one` default until a complete comparable
30-topic generation and three-pass grade beats 0.7042.

## Tests

```bash
bash scripts/test.sh tests/systems/test_aus_agent_v2.py
bash scripts/test.sh
```

The offline system tests use the shared scripted provider and retrieval stub.
The live-marked test exercises the real search and provider path only when
explicitly requested.
