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
`--finish-review`, or `--answer-blueprint`.

## Tests

```bash
bash scripts/test.sh tests/systems/test_aus_agent_v2.py
bash scripts/test.sh
```

The offline system tests use the shared scripted provider and retrieval stub.
The live-marked test exercises the real search and provider path only when
explicitly requested.
