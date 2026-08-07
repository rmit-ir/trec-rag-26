# AUS agent: from buried facts to a multi-stage evidence pipeline

**Date:** 2026-08-06  
**Goal:** move the 30-topic Sol rubric score from 0.6508 toward 0.80+ through
method and architecture changes, not a model or timezone change.  
**Status:** pipeline implemented and live-smoked; full paired rubric grading is
not yet authorized, so no score improvement is claimed.

## Why the prior nulls did not close the ideas

Two prior experiments had tested prompts/schema, not end-to-end mechanisms:

- `solo-finish-the-claim.md` added a final-prompt preference for fewer complete
  points, but no component inspected a draft, matched its claims to evidence,
  or protected coverage.
- `facts[]` added optional annotations to `commit_context`, but the handler did
  not persist them as first-class state and no later stage consumed them. They
  survived only inside historical assistant function-call arguments.

The corrected saved-run audit is
[`worklogs/assets/2026-08-06-finish-facts-pipeline-audit.py`](assets/2026-08-06-finish-facts-pipeline-audit.py),
with the complete per-topic and per-criterion result matrix in
[`worklogs/assets/2026-08-06-finish-facts-pipeline-audit.log`](assets/2026-08-06-finish-facts-pipeline-audit.log).

Exact command:

```bash
UV_CACHE_DIR=/tmp/trec-rag-uv-cache uv run --no-project python worklogs/assets/2026-08-06-finish-facts-pipeline-audit.py 2>&1 | tee worklogs/assets/2026-08-06-finish-facts-pipeline-audit.log
```

### Finish-the-claim changed behavior, but traded coverage away

The matrix below is 90 paired topic-gradings (30 topics × 3 independent judge
repeats), comparing `v2-dev30-default` with
`sol-dev30-finish-the-claim`. Cells are criterion counts.

| Prior verdict → new verdict | missing | partial | satisfied |
|---|---:|---:|---:|
| missing | 349 | 73 | 28 |
| partial | 67 | 225 | 95 |
| satisfied | 37 | 115 | 850 |

It converted 95/387 partially satisfied criteria (24.5%) to satisfied, so the
instruction did act on the intended defect. It also regressed 67/387 partial
criteria to missing and downgraded 152 previously satisfied criteria. Mean
answer length fell 879.8 → 852.1 words and references fell 25.7 → 24.1, while
digits rose 17.38 → 21.70 per 1,000 words and vague markers fell 1.59 → 0.96.
The method sharpened claims but recreated a breadth tradeoff.

### Optional facts were selected but mostly not synthesized

The corresponding 90-grade matrix for `v2l-dev30-default` →
`v2l-dev30-facts` is:

| Prior verdict → new verdict | missing | partial | satisfied |
|---|---:|---:|---:|
| missing | 438 | 73 | 34 |
| partial | 89 | 258 | 91 |
| satisfied | 51 | 99 | 706 |

The fact arm converted 91/438 partial criteria (20.8%) and regressed 89/438
(20.3%); words and references were flat. The corrected chunk→parent citation
normalization shows:

| Fact carry-through measure | Result |
|---|---:|
| fact cards extracted | 1,223 |
| cards from a parent document cited in the answer | 1,103 (90.2%) |
| exact normalized value present in answer | 92 (7.5%) |
| claim/value lexical match ≥ 60% | 581 (47.5%) |
| numeric values carried | 109/191 (57.1%) |

Evidence selection was therefore usually sound. The missing link was the
synthesis handoff.

## Organizer-baseline formatting check

Before changing output form, the frozen official baselines were measured at:

- `data/task-comparison/test119-eval/base-agentic-bm25.jsonl`
- `data/task-comparison/test119-eval/base-singlepass.jsonl`

| Baseline | Topics | Heading topics | Table topics | Bullet topics | Numbered-list topics |
|---|---:|---:|---:|---:|---:|
| base-agentic-bm25 | 119 | 0 | 1 (`rag2026-28`) | 0 | 0 |
| base-singlepass | 119 | 2 (`rag2026-28`, `rag2026-115`) | 1 (`rag2026-28`) | 0 | 0 |

`rag2026-28` explicitly requests a literature-review grading table. Every
structured object in both baselines had a citation. Broad Markdown enablement
was therefore rejected: plain prose remains the default, and requested
structure must be explicit and independently citable.

## Implemented architecture

The new path is opt-in. `--coverage-plan --finish-review` runs four distinct
model contexts:

1. **Coverage planner:** original request → bounded requirements/evidence plan.
2. **Research agent:** plan + request → tool-using staged-context research and a
   contract-valid cited draft.
3. **Coverage verifier:** request + plan + draft → omissions only, no rewriting
   and no evidence adjudication.
4. **Evidence writer:** request + plan + draft + omission audit + citation-local
   source cards → one final revision.

The source cards are built deterministically from the committed text. Every
card binds one draft claim to excerpts from exactly the evidence unit it cites.
For an uncited draft point, the harness may suggest the single best-matching
committed unit only when lexical overlap clears a threshold; this adds evidence
instead of repeating the failed `cite-or-cut` intervention.

The evidence writer is guarded by an architectural invariant: if a valid draft
under 1,024 words is revised below 85% of its original length, the harness keeps
the research draft and records `coverage_fallback=true`. This protects against
the measured breadth loss rather than trusting another instruction to do so.

Optional `facts` no longer gates the architecture. If an experiment enables
them they are retained and included in cards, but raw committed source excerpts
make the pipeline work when Sol emits no optional annotations.

### Exact planner prompt

```text
You are the planning stage of a research system. Analyze the request before any
search happens. Produce a concise coverage plan for a separate research agent
and evidence writer; do not answer the request and do not invent facts.

The plan must identify:
- the exact deliverable form and number of parts the user requested;
- the audience, assumed prior knowledge, and terms or acronyms that need plain
  definitions;
- every explicit topic, comparison, example, decision, or constraint;
- standard alternatives, institutions, instruments, dimensions, risks, or
  failure modes a knowledgeable reader would reasonably expect even when the
  request does not name them;
- the concrete evidence searches needed to support those points;
- any time-sensitive or jurisdiction-sensitive details that must not be guessed.

Use 6 to 14 numbered items, ordered by importance. Each item must be one or two
sentences and label itself as DELIVERABLE, AUDIENCE, EXPLICIT, IMPLIED,
DEFINITION, EXAMPLE, EVIDENCE, or SAFETY. Stay under 500 words. Return only the
plan.
```

### Exact coverage-verifier prompt

```text
You are the coverage verifier between a research draft and its final evidence
editor. Compare the draft with the original request and the pre-research plan.
Do not rewrite the report and do not assess citation support. List only material
omissions or format/audience failures that the final editor must repair.

Prioritize the requested deliverable form, number of parts, audience and assumed
knowledge, every explicit comparison or example, and distinct high-value items
in the plan. Do not demand every optional idea when the draft already answers
the request well. Return 1 to 12 short numbered findings, or exactly NO MATERIAL
COVERAGE GAPS. Stay under 350 words and return only the audit.
```

### Exact evidence-writer prompt

```text
You are the final evidence editor for a research report. You receive the
original request, a complete cited draft, and an evidence card for each draft
claim. Revise once, preserving every accurate supported point and the draft's
coverage while making incomplete claims precise and correcting or removing
details that their cited evidence does not support.

Do not summarize or compress the draft. Retain every distinct supported
theorem, technique, worked example, definition, comparison, and practical
implication; remove material only when its evidence card exposes it as wrong,
unsupported, or duplicative. Unless the draft exceeds the hard limit, keep the
revision between 90% and 105% of its word count. Expand an acronym at first use
and define specialized terms for the audience named in the request.

Use only the exact evidence-unit ids printed in the packet. Every factual
sentence must end with one or more citations in the form [unit_id]. Put each
sentence in its own paragraph. Default to plain prose; use a heading, list, or
table only when the request explicitly requires that structure, and cite every
independently checkable item within it. Do not add a references section, discuss
the editing process, mention the packet, or exceed 1,024 words. Return only the
complete revised cited report.
```

The unchanged full research system prompt and the exact timestamped user
messages are persisted verbatim in each trajectory's `trace.input`; the live
artifact paths are listed below.

## Live smoke inputs and complete result matrix

### Topic A — geometry

Exact research request:

```text
Write a blog post contrasting Euclidean geometry used in high school math competitions such as the AMC, AIME, or Olympiads to geometry taught in the standard American high school math curriculums. This post is written for people with knowledge of geometry from standard high school classes, but with no math experience in competitive math. Your post must include clear examples of problem solving techniques and theorems that are commonly used in high school math competitions, but not typically taught in a high school math class.
```

### Topic B — retirement and large purchases

Exact research request:

```text
Write a series of blog posts discussing ways people can invest their money for retirement and large purchases. The posts should be understandable and applicable for all adults, regardless of their prior experience in investing.
```

The latter was deliberately selected because its saved Sol baseline score was
the lowest of the 30-topic set: 0.2675.

| Run | Architecture | Topic | Research draft → final words | Key stage result | Cost |
|---|---|---|---:|---|---:|
| `sol-smoke-finish-review-20260806` | optional commit facts + same-context review | A | first draft accepted | Sol emitted 0 facts for 18 committed docs; no revision request | not used as candidate |
| `sol-smoke-fresh-finish-review-20260806` | fresh evidence writer, no plan/verifier | A | 838 → 685 | 23 cards / 17 docs; exposed a new compression failure | $0.9827 |
| `sol-smoke-multistage-20260806` | plan + research + evidence writer | B | 981 → 973 | 455-word plan; 48 cards; six labeled posts | $1.4613 |
| `sol-smoke-multistage-v2-20260806` | plan + research + verifier + evidence writer | B | 873 → 880 | 448-word plan; 121-word audit; 40 cards; six labeled posts | $1.6530 |

Live raw logs:

- [`2026-08-06-finish-review-optional-facts-live.log`](assets/2026-08-06-finish-review-optional-facts-live.log)
- [`2026-08-06-fresh-finish-review-live.log`](assets/2026-08-06-fresh-finish-review-live.log)
- [`2026-08-06-multistage-no-verifier-live.log`](assets/2026-08-06-multistage-no-verifier-live.log)
- [`2026-08-06-multistage-verifier-live.log`](assets/2026-08-06-multistage-verifier-live.log)

Persisted artifacts:

| Run | Output | Trajectory |
|---|---|---|
| optional-facts smoke | `data/outputs/aus_agent/20260806T183941447858+1000.write_a_blog_post_contrasting.output.json` | sibling `.trajectory.json` |
| fresh-writer smoke | `data/outputs/aus_agent/20260806T184729668029+1000.write_a_blog_post_contrasting.output.json` | sibling `.trajectory.json` |
| multistage without verifier | `data/outputs/aus_agent/20260806T185717787919+1000.write_a_series_of_blog.output.json` | sibling `.trajectory.json` |
| multistage with verifier | `data/outputs/aus_agent/20260806T190333075422+1000.write_a_series_of_blog.output.json` | sibling `.trajectory.json` |

The last verifier found four exact gaps: the sections read as notes rather than
publication-ready posts; life-stage examples were weak; employment/family/
accessibility applicability was sparse; and several novice terms were
undefined. The final writer repaired some but not all. This is useful evidence
that the stage is doing a distinct job, and also a reason not to claim a score
win before paired grading.

## Grading status

The prepared paired grader is
[`worklogs/assets/2026-08-06-fresh-finish-smoke-grade.py`](assets/2026-08-06-fresh-finish-smoke-grade.py).
It would send the exact persisted draft and revision to the configured external
rubric judge for three repeated grades each and print the full criterion matrix.

Execution was rejected by the environment because the user had not explicitly
approved sending the generated texts to that separate judge endpoint. No
grading call was made and no workaround was attempted. The next experiment
requires explicit approval for that data transfer before a 30-topic arm is
responsible.

## Files changed for this pipeline

- `src/systems/aus_agent/coverage_plan.py` — planner prompt and bounded handoff.
- `src/systems/aus_agent/finish_review.py` — verifier, source-card construction,
  legacy fact-card capture, and evidence-writer prompt.
- `src/systems/aus_agent/agent.py` — fresh context phase transitions, persistent
  committed-document state, trace summaries, raw-message phase boundaries, and
  the 85% coverage fallback.
- `src/systems/aus_agent/run.py` — `--coverage-plan` and `--finish-review` CLI.
- `src/systems/aus_agent/tools/commit_context.py` — explicit schema-field
  overrides while preserving experiment toggles.
- `tests/aus_agent_context/test_{coverage_plan,finish_review}.py`,
  `tests/aus_agent_context/test_commit_tool.py`, and
  `tests/systems/test_aus_agent.py` — phase, citation-locality, missing-fact,
  payload-bound, and fallback invariants.
- `skills/trec-rag-new-system/scripts/gen_arch_viz.py`,
  `tests/arch_viz/test_gen_arch_viz.py`, and `docs/architecture.html` — the
  actual multi-stage path in the architecture view.

## Verification

Focused pipeline suite:

```bash
UV_CACHE_DIR=/tmp/trec-rag-uv-cache bash scripts/test.sh tests/aus_agent_context/test_coverage_plan.py tests/aus_agent_context/test_finish_review.py tests/aus_agent_context/test_commit_tool.py tests/systems/test_aus_agent.py
```

Result: **115 passed, 1 live test deselected**.

Full suite (rerun with loopback permission because the default sandbox caused
all 26 dummy-API tests to fail and hang):

```bash
UV_CACHE_DIR=/tmp/trec-rag-uv-cache bash scripts/test.sh
```

Result: **1,621 passed, 7 live tests deselected, 1 existing deprecation warning,
13.84 seconds**. The isolated dummy-API confirmation was 26/26 passed.

Architecture verification:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system aus_agent --open
UV_CACHE_DIR=/tmp/trec-rag-uv-cache bash scripts/test.sh tests/arch_viz
```

Result: diagram regenerated/launched at `docs/architecture.html#aus_agent`; 11
architecture tests passed.

Durable raw test logs are under `worklogs/assets/2026-08-06-multistage-*tests.log`.

## Neighbor-page retrieval status

The prior worklog initially said neighboring-page retrieval was never built,
but a late uncommitted change in the same session did add
`AUS_AGENT_NEIGHBOUR_PAGES` to `tools/search.py`. It attaches adjacent pages for
the top three search hits. It remains environment-only, lacks dedicated tests
and a named CLI configuration, and has never been run as an evaluated arm. It
was preserved, not counted as a completed method, and not mixed into the live
multi-stage smokes above.

## Next decision

1. Obtain explicit approval to send the two persisted generated texts to the
   configured rubric judge.
2. Grade draft vs final within the same trajectory first; if the verifier/editor
   does not improve that paired comparison, fix the handoff before any batch.
3. If the local pair is positive, run a small stratified set including the worst
   baseline topics before a full 30-topic confirmation.
4. Only then combine the architecture with neighbor-page retrieval; evidence
   delivery and synthesis should be measured separately before stacking.
