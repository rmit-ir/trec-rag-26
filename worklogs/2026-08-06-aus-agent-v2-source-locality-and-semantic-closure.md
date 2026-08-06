# aus_agent_v2 source locality and semantic-closure audit

Date: 2026-08-06

Implementation baseline: `5972ac3b76b5391cfb28d0cc5c1d9b8f64419bd2`

Frozen evaluated run: `sol-aus-v2-research-first-pre-repair-dev30-20260806`

Verified score before this work: `0.704159` on all 30 development topics

Incremental provider/search/judge calls: `0 / 0 / 0`

Incremental cost: `$0.00`

Recorded cumulative cost remains: `$1,096.72`

## Question

The commit-time fact extractor had produced hundreds of facts without changing
answers or rubric score. This session tested whether the executable coverage
contract actually forces a saved fact to become a locally supported, complete
claim, and whether cheap deterministic proxies could safely establish that an
answer sentence semantically closes a requirement.

No paid experiment was authorized: cumulative spend already exceeds the new
`$300` total ceiling. All evidence below comes from frozen local artifacts and
the hermetic test harness.

## Exact offline inputs

The complete replay program, every derived row, all source/output paths and
SHA-256 hashes, the full result matrix, and the console log are preserved as:

- `worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.py`
- `worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.json`
- `worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.log`

The program reads the exact committed implementation at `5972ac3b`, the 30
frozen outputs for run
`sol-aus-v2-research-first-pre-repair-dev30-20260806`, the fixed development
rubrics, and all three frozen Sol verdict repeats. It does not import a
provider, retrieval client, grader, or network client.

The exact synthetic false-closure strings were:

```text
Generic tagged prose
Unrelated closure evidence
```

For a structural row, the harness tagged `Generic tagged prose` as satisfying
that row. For a research row, it created a source-present anchor whose exact
claim and source text were `Unrelated closure evidence`, then tagged answer
prose containing that anchor plus only any literal `must_mention` terms. The
lexical-echo probe used the complete requirement text plus the same unrelated
anchor for research rows. The count probe submitted the following exact item
three times against `MIN=3`:

```json
{"kind":"prose","text":"Generic tagged prose.","evidence_ids":[],"satisfies":["P01"]}
```

The exact reproduction command is embedded in the script header:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src/systems:src \
  uv run --group aus-agent-v2 python \
  worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.py \
  --output worklogs/assets/2026-08-06-aus-agent-v2-semantic-closure-risk.json
```

## Full result matrix summary

The JSON asset contains every topic, planner/scout row, replay arguments,
validator errors/stats, requirement tokens, answer items, rubric criterion,
three raw verdicts, and every threshold outcome. The aggregate matrix was:

| Cohort / check | Result |
| --- | ---: |
| Planner/scout assert answer rows replayed | 540 |
| Structural generic closures accepted | 77 / 77 |
| Research closures with unrelated source-valid anchor accepted | 463 / 463 |
| All generic/unrelated closures accepted | 540 / 540 |
| Accepted with zero requirement-content tokens | 392 / 540 |
| Requirement-parroting closures accepted | 540 / 540 |
| Three identical items accepted for `MIN=3` | yes |
| Positive criteria satisfied by all three frozen judges | 345 |
| Distinct-item lexical gate rejects at recall `0.05` | 39 / 345 |
| Distinct-item lexical gate rejects at recall `0.10` | 68 / 345 |
| Distinct-item lexical gate rejects at recall `0.15` | 145 / 345 |
| Distinct-item lexical gate rejects at recall `0.20` | 192 / 345 |
| Distinct-item lexical gate rejects at recall `0.25` | 233 / 345 |
| Distinct-item lexical gate rejects at recall `0.30` | 287 / 345 |
| Distinct-item lexical gate rejects at recall `0.40` | 319 / 345 |
| Distinct-item lexical gate rejects at recall `0.50` | 333 / 345 |
| Rubric-aligned planner/scout proxy rows | 29 across 19 topics |
| Proxy rows rejected by one-item gate at `0.10` | 4 / 29 |
| Proxy rows rejected by one-item gate at `0.20` | 19 / 29 |

Outcomes were judged in two ways. False closure used the actual committed
`validate_submission` return value. False-rejection risk used only positive,
unwaived rubric criteria that all three frozen Sol repeats judged `satisfied`;
lexical overlap was the tested gate, not the ground truth. A conservative proxy
subset also required at least half of a criterion's content tokens to occur in
one frozen planner/scout row.

## Interpretation

The old contract established routing, citation eligibility, literal survival,
and array length, but not claim-to-requirement meaning. Requirement overlap is
not a safe repair: a model can parrot the row and still close all 540 replays,
while even a 0.10 one-item overlap gate rejects 60 of 345 judge-unanimous
positive criteria. A one-row-per-sentence hard rule has the same conceptual
problem and unnecessarily duplicates valid synthesis.

The deterministic layer can nevertheless close real implementation defects:
it can bind a claim to one local source span, keep one citation set from
covering multiple sentences, require genuine distinctness for requested
counts, and prevent the planner from marking factual evidence as
request-grounded.

## Implementation

The candidate path under `src/systems/aus_agent_v2/` now has these additional
invariants:

1. Every committed support or dynamic promotion supplies a bounded
   `source_quote` copied from one contiguous source span.
2. `claim` is extractive: it must occur verbatim inside `source_quote`.
3. Non-empty `value_scope` and every `must_include` term must occur inside the
   same quote; the complete quote must occur contiguously in the staged source.
4. Terminal handoff replays one full local quote per research row, rather than
   four potentially 600-character alternatives, to bound recency context.
5. Each submitted prose item may contain only one sentence/line, keeping its
   citations local. One sentence may still close multiple overlapping rows.
6. `minimum_count` counts distinct case/whitespace/final-punctuation-normalized
   item text rather than raw array length.
7. Atomic planner rows of factual kinds cannot set `must_research=false`, and
   two-item serial lists such as `cost, safety and efficacy` are rejected as
   compound.
8. Dynamic promotions receive the same visible compound-row checks.
9. The first terminal preview is fully validated before the evidence handoff
   opens; an invalid rehearsal receives errors without seeing the handoff.

Adversarial regressions cover number laundering, a claim outside a real quote,
quotes stitched across distant spans, missing/oversized quotes, multi-sentence
citation laundering, duplicate count items, scholarly abbreviations, planner
research-flag abuse, and two-item serial bundling.

## Verification

Focused command:

```bash
bash scripts/test.sh tests/aus_agent_v2/test_coverage_contract.py tests/aus_agent_v2/test_atomic_plan.py tests/systems/test_aus_agent_v2.py
```

Result: `93 passed, 1 live test deselected`.

Full required command:

```bash
bash scripts/test.sh
```

Result: `1,745 passed, 8 live tests deselected, 1 deprecation warning` in
`18.45s`. No test skipped.

Architecture regeneration and launch:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system aus_agent_v2
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check
```

Result: `docs/architecture.html` is current; the system view was launched.

The offline audit was rerun from its preserved script to a temporary output;
`cmp` confirmed the 3,450,277-byte JSON matrix is byte-identical. Both copies
have SHA-256
`be73b341165bf1513bd897b0f408966bc8bdaa51e45892b1a99d8b0f7082b2f9`.

## Score status and next experiment

This is an ungraded candidate, not a score claim. The highest verified all-30
score remains `0.704159`; the `0.8` objective is not yet achieved.

The audit says the next method change should be a fresh, isolated, reject-only
semantic verifier over row-local packets:

```text
requirement + candidate sentence + cited source_quote(s)
```

It should return typed pass/fail diagnostics, never rewrite prose, run only
after deterministic validation, and allow one bounded correction. It needs
calibration because lexical proxies have high false-rejection rates. A paid
full-30 candidate run remains held behind explicit authorization to raise the
absolute budget ceiling and reserve enough spend for generation plus three
judge repeats.
