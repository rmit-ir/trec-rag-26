# Semantic-gate enforcement and complete-answer candidate union

Date: 2026-08-06

Objective: reach a verified mean rubric score of at least `0.80` on all 30
development topics by fixing the research pipeline, not by treating earlier
fact and finish-the-claim experiments as method nulls.

Verified score entering and leaving this session: `0.704159` (`0.7042` rounded)
on all 30 topics. The code in this session is an ungraded candidate; it does
not establish that the objective is met.

Incremental provider/search/judge calls: `0 / 0 / 0`.

Incremental paid cost: `$0.00`. The mechanically tracked cumulative cost remains
`$1,096.72` (`$961.77` generation + `$134.95` judging), above the standing
absolute `$300` ceiling. No live worker was started.

## Evidence for the architecture choices

The exact frozen full-30 answer/criterion oracle is executable at
`worklogs/assets/2026-08-06-aus-agent-v2-oracle-analysis.py`. Re-running it
offline showed:

| candidate set | answer-level oracle | criterion-level union |
| --- | ---: | ---: |
| four complete core architectures | 0.7445 | **0.8048** |
| all eight Sol-written complete architectures | 0.7508 | 0.8284 |

Thus whole-answer routing cannot close the gap, but complementary answer
content already present across complete runs is sufficient in the criterion
oracle. This is an upper bound, not a runnable score.

The frozen plan-to-answer audit at
`worklogs/assets/2026-08-06-aus-agent-v2-handoff-audit.md` independently located
the loss:

| frozen best-run failure stage | criteria | weighted positive loss |
| --- | ---: | ---: |
| retrieved but not committed | 44 | 78.67 |
| committed but absent from answer | 35 | 68.50 |
| combined post-retrieval omission | **79 / 268** | **147.17 / 526.00** |
| present in answer but underfulfilled | 71 | 137.83 |

The run retrieved 393.4 units and committed 35.0 per topic on average. More
retrieval is therefore not the primary lever; stable evidence-to-answer
closure and complementary-content preservation are.

## Semantic verifier correctness audit

The post-handoff verifier added in `bed1b17a` had real enforcement bugs:

1. `PACKET_INCOMPLETE` was a reject failure code even though the prompt said
   incomplete context must abstain. An all-pass label set plus that arbitrary
   code normalized to a repair.
2. A flagged writer item could change `evidence_ids` and `satisfies`; the
   preservation check skipped the complete object for repairable items.
3. Persistent clear rejection restored the known-rejected baseline and still
   returned `accepted: true` with `trace.status=completed`.
4. A sentence satisfying two rows exposed only the current row's anchors, so
   the verifier could mistake the other valid clause for unsupported prose.
5. `answer_global` checks saw the complete answer but could target only items
   already tagged to the global row.
6. The correction feedback discarded verifier-named evidence ids and quotes.

The corrected protocol now:

- removes `PACKET_INCOMPLETE`; incomplete context is an abstention with an
  applicable `unclear` dimension and no failure targets;
- requires every reject label to expose a real failing closure/support/count
  dimension and requires matching failure-code groups;
- keeps nonresearch support and non-count rows at `not_applicable`;
- permits flagged items to change only `text`; kind, evidence ids, satisfies
  ids, array order, and unresolved rows remain immutable;
- gives each check row-owned evidence plus bounded `context_evidence` for other
  clauses in the same multi-row item;
- exposes available parent id, retrieval kind, and source/query/publisher
  metadata without inventing provenance;
- makes every typed answer item repairable for an `answer_global` check;
- replays verifier-named exact quotes in the sole correction turn;
- records a persistent clear rejection or invalid correction as
  `semantic_rejected`, which neither resume nor export treats as completed;
- retains a deterministic-valid corrected answer on a malformed second audit
  for diagnosis but marks it `semantic_unverified`, never completed;
- restricts rejected `evidence_ids` to the row-owned evidence rather than
  neighboring context evidence, publishes the failure-code mapping, and reports
  any bounded evidence projection omissions;
- records the audit corresponding to the actually saved answer, makes every
  noncompleted semantic status a CLI failure, and requires the batch runner to
  recount exactly 30 completed artifacts before announcing success.

No semantic-accuracy threshold is claimed from frozen data. Those outputs
predate the source-local typed packets and contain no cached verifier
predictions. The tests prove packet/control-flow behavior only; activation
still requires manually adjudicated production-shaped packets and cached raw
tool arguments.

## Extractive complete-answer union

`candidate_union.py` implements the criterion-union hypothesis without a new
writer:

1. Accept two to eight completed, valid artifacts for the same exact qid and
   full request.
2. Replace run names by qid-shuffled anonymous `Cxx:Ixx` ids in model-visible
   context.
3. Resolve each original citation index/string to its immutable document id.
4. Ask one fresh typed selector for ordered item ids and an audit coverage map.
5. Copy selected text and citations exactly; the model cannot write answer
   prose.
6. Require at most 1,024 words, no duplicated ids/text, every selected item in
   an audit row, at least one non-anchor item, original relative order within
   every contributing source, at least 60% of anchor items, and at least 65% of
   anchor words. Every dropped anchor item must name selected non-anchor
   replacements.
7. On either bounded protocol failure, return the complete anchor byte-for-byte,
   including unused reference entries.

This differs from the existing `ensemble_select.py`: that stage chooses one
whole answer, whose empirical oracle ceiling is 0.7445. The new stage selects
immutable cited items across complete answers, targeting the 0.8284 criterion
union while avoiding the coverage loss observed from fresh whole-answer
rewrites.

The runnable `pipeline.run_candidate_union_one` saves a strict organizer output
plus full packet, raw provider histories, per-attempt errors, source run ids,
and normalized token counters so the cross-system cost monitor sees every
call. It uses `TrajectoryBuilder`, so the trajectory remains strict and the
rich trace stays in `output.json`. `union_run.py` loads exactly one completed
artifact for every source run/topic and checks the authoritative spend before
provider construction for every topic.

## Exact offline inputs and full matrix

The exact query set is the organizer TSV:

`data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv`

The eight source runs supplied to the qid-hashed anonymous ordering were:

1. `sol-aus-v2-research-first-pre-repair-dev30-20260806` (anchor)
2. `v2-dev30-default`
3. `sol-aus-v2-research-first-dev30-20260806`
4. `sol-aus-v2-adaptive-dev30-20260806`
5. `v2-dev30-minimal`
6. `sol-dev30-effort-max`
7. `sol-dev30-tools`
8. `sol-dev30-finish-the-claim`

Every exact model-visible packet, source artifact path, query, immutable item,
document id, item word count, and per-topic measurement is preserved in:

`worklogs/assets/2026-08-06-aus-agent-v2-candidate-union-dev30.jsonl`

SHA-256: `e62a6fe7caee9489a96ab2308ce6055840cc291bfd160b9274f873d44a9c85f4`
(`2,330,320` bytes, 30 JSONL rows).

The complete 30-topic console matrix is:

`worklogs/assets/2026-08-06-aus-agent-v2-candidate-union-prepare.log`

SHA-256: `d00112d9aedad158eb27d588bfed09044e0d912ec10b97e7ffa299c632ec4401`.

Aggregate packet preflight:

| quantity | min | mean | max | total |
| --- | ---: | ---: | ---: | ---: |
| model request characters | 57,917 | 74,231.7 | 83,531 | 2,226,950 |
| immutable candidate items | 142 | 219.8 | 287 | 6,593 |
| anchor words | 752 | 912.9 | 1,022 | — |

All 30 topics resolved exactly eight unique completed artifacts (240 total);
every packet was below the 140,000-character bound. No model-visible packet
contains the token `AUS` or a source run id. Candidate answers may legitimately
mention
Australian evidence; this is source prose, not locale injection or a prompt
identity.

Exact preparation command:

```bash
set -o pipefail; PYTHONPATH=src:src/systems \
  uv run --frozen --offline --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py --all --prepare-only \
  --packet-output \
  worklogs/assets/2026-08-06-aus-agent-v2-candidate-union-dev30.jsonl \
  2>&1 | tee /tmp/aus-v2-candidate-union-prepare.log
```

## Budget enforcement probe

Exact command:

```bash
set -o pipefail; uv run --group aus-agent-v2 python \
  src/systems/aus_agent_v2/union_run.py \
  --qid 683a58c9a7e7fe4e7695846f \
  --budget-cap 300 --per-topic-reserve-usd 10 \
  2>&1 | tee /tmp/aus-v2-candidate-union-budget-gate.log
```

Exact result (`exit 1`), preserved at
`worklogs/assets/2026-08-06-aus-agent-v2-candidate-union-budget-gate.log`:

```text
budget gate: $1096.72 tracked + $10.00 reserve exceeds $300.00 cap; no provider call made
```

## Verification

Focused semantic enforcement verification:

```bash
bash -n tasks/task-comparison/scripts/run_aus_agent_v2_parallel.sh && \
  bash scripts/test.sh tests/aus_agent_v2/test_semantic_closure.py \
  tests/systems/test_aus_agent_v2.py
```

Result: `59 passed, 1 live test deselected`.

Focused union verification:

```bash
bash scripts/test.sh tests/aus_agent_v2/test_candidate_union.py
```

Result: `11 passed`.

Final full repository suite:

```bash
set -o pipefail; bash scripts/test.sh 2>&1 | \
  tee /tmp/aus-v2-semantic-union-full-tests-final.log
```

Result: `1,787 passed, 8 live tests deselected, 0 skipped` in `17.35s`.
The complete log is preserved at
`worklogs/assets/2026-08-06-aus-agent-v2-semantic-union-full-tests.log`
(`7,867` bytes; SHA-256
`509a83862b1ba30ef4a97cfb9328cfb92ff330da6f16e8876445dae76b00ebd7`).

Architecture regeneration and freshness check:

```bash
python skills/trec-rag-new-system/scripts/gen_arch_viz.py \
  --open --system aus_agent_v2
python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check
```

Result: `docs/architecture.html` contains 6 systems, 18 edges, and 5 engines;
the deep link was launched and the byte-freshness check passed.

## Score and next paid experiment

The highest verified complete score remains `0.704159`; the requested `0.80`
goal is unproven. The best next experiment is a full 30-topic selector-only
union over the eight already-paid artifacts, followed by the same three-pass
rubric grade. Its idealized cached-criterion ceiling is `0.8284`, not a forecast:
it ignores word competition, sentence dependencies, contradictions, negative
criteria, and selector error. The source set was also chosen on dev30, so any
dev30 result is developmental rather than held-out.

If that selector misses, the second option is the semantic contract pipeline:
it directly tests the observed commit-to-answer failure and makes
finish-the-claim an enforcing state transition, but needs a new full generation
and its semantic verifier still lacks calibrated production accuracy. The
third option is the lean atomic mutable-ledger pipeline, which fixes evidence
transport before drafting but costs a complete research run. More retrieval,
reasoning effort, broad Markdown, or another whole-answer writer are not the
best next spend given the frozen evidence.

Any future Bedrock execution must remain under an explicitly authorized
`$300` total. Since the mechanically tracked cumulative spend is already
`$1,096.72`, the committed runners refuse before provider creation; a renewed
API key alone is insufficient authorization.
