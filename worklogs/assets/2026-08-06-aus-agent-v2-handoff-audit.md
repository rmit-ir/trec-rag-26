# Offline plan → evidence → answer handoff audit

Target run:
`sol-aus-v2-research-first-pre-repair-dev30-20260806`

No provider or network call was made. The audit used the exact fixed rubric rows
in `data/task-comparison/dev-rubrics-fixed.jsonl`, three completed cached Sol
verdicts per topic under
`data/task-comparison/rubric-eval/gpt-5.6-sol/sol-aus-v2-research-first-pre-repair-dev30-20260806/`,
and the saved v2 output/trajectory artifacts selected by that exact run id.
Every trajectory was cut at its first valid draft; verifier-repair searches and
commits were excluded.

## Judgment population

- 268 unmet positive/reward criteria.
- 20 incurred penalty criteria.
- Weighted desired-state loss: 526.00 positive + 49.67 penalty.
- Explicit + implicit criteria account for 373.83/526.00 (71.1%) of positive
  loss.

## Conservative lexical trace

For each unmet criterion, parenthetical/examples text was stripped. A stage was
counted present when token recall against the remaining criterion text was at
least 0.5. Sensitivity thresholds 0.4 and 0.6 were also evaluated. This is a
diagnostic locator, not a semantic grade; the authoritative satisfaction state
is the three-repeat rubric cache.

| Failure stage | Criteria | Weighted loss |
|---|---:|---:|
| Plan/discovery omission | 91 | 171.33 |
| Present in answer but underfulfilled | 71 | 137.83 |
| Retrieved but not committed | 44 | 78.67 |
| Committed but absent from answer | 35 | 68.50 |
| Planned but not retrieved | 18 | 43.50 |
| Planned answer-form execution gap | 6 | 16.50 |
| Unplanned answer-form gap | 3 | 9.67 |

Stage presence among the 268 unmet rewards:

| Stage | Present | Rate |
|---|---:|---:|
| Initial coverage plan | 91 | 34.0% |
| Blind plan critic | 36 | 13.4% |
| Merged plan | 101 | 37.7% |
| Pre-draft retrieved evidence | 141 | 52.6% |
| Pre-draft committed evidence | 80 | 29.9% |
| Final answer | 71 | 26.5% |

The run retrieved 393.4 search-result units per topic on average and committed
35.0. More retrieval alone is therefore not the highest-leverage intervention.

| Failure | Explicit n/loss | Implicit n/loss |
|---|---:|---:|
| Plan/discovery omission | 19 / 45.17 | 37 / 63.50 |
| Planned → retrieval | 2 / 9.00 | 14 / 30.50 |
| Retrieved → commit | 11 / 21.50 | 24 / 40.83 |
| Committed → answer | 11 / 21.67 | 18 / 33.33 |
| Answer underfulfilled | 13 / 34.50 | 41 / 73.83 |

Threshold sensitivity at 0.4 / 0.5 / 0.6:

| Stage | 0.4 | 0.5 | 0.6 |
|---|---:|---:|---:|
| Retrieved presence | 74.6% | 52.6% | 30.2% |
| Committed presence | 48.9% | 29.9% | 15.7% |
| Answer presence | 42.9% | 26.5% | 10.4% |

## Finance blog (`683a58c9a7e7fe4e76958498`)

Score 0.2716; 20 unmet rewards (18 stable zero), two penalties, weighted loss
59.0.

| Failure group | Criteria | Loss |
|---|---|---:|
| Intentional structure conflict | c00,c01,c02,c04,c18 | 15 |
| Jurisdiction-neutral plan vs US catalog | c14,c15,c23–c28,c30 | 28 |
| Planned audience promise omitted | c05 | 4 |
| Securities mechanics/details incomplete | c12,c17,c20–c22 | 8 |
| Undefined jargon + one-repeat outdated-info penalty | c03,c08 | 4 |

The plan literally said not to add visible headings/tables and avoided
jurisdiction-specific accounts. Pre-draft term flow:

| Term | Retrieved | Committed | Answer |
|---|---|---|---|
| 401(k), IRA | yes | yes | no |
| S&P 500, Dow, Nasdaq | yes | yes | no |
| Vanguard, Schwab, AGG | yes | yes | no |
| Fidelity, Robinhood, SPY, VEA | yes | no | no |
| preferred stock | yes | no | no |
| common stock, secondary market, Russell 2000, FXAIX, VTSAX, QQQ | no | no | no |

Exact output:
`data/outputs/aus_agent_v2/20260807T001556840883+1000.pre_repair_counterfactual.output.json`.

## Mahabharata (`6847465956a0f6376a60542d`)

Score 0.4583; 16 unmet rewards (four stable zero, 12 partial), weighted loss
28.167.

| Failure group | Criteria | Loss |
|---|---|---:|
| Absent as atomic plan obligations | c05,c06,c08,c10 | 10.00 |
| Committed evidence compressed/incompletely synthesized | c00,c02,c03,c09,c12,c16,c19,c21 | 13.33 |
| Comparison/causal framing not explicit | c07,c11,c17 | 3.83 |
| Bibliographic specificity | c15 | 1.00 |

Pre-draft exemplar flow:

| Item | Retrieved | Committed | Answer |
|---|---|---|---|
| Bharata | yes | yes | generic lineage only, not the required early choice |
| Ramayana, Trigarta, Avanti, Parikshit | yes | yes | no |
| Shantanu, Pragjyotisha, Ashvamedha, poisoned Bhima, swayamvara, Pashupatastra | yes | no | no |
| Kamboja, Kekaya, lacquer house, kavacha | no | no | no |

Exact output:
`data/outputs/aus_agent_v2/20260807T002544115019+1000.pre_repair_counterfactual.output.json`.

## Mechanism conclusion

The dominant defect is a missing executable relationship across stages, not a
lack of search volume. The implementation target is an atomic obligation
ledger in which search, commit support, and final sentences carry the same
stable ids; drafting cannot silently omit a must-answer row; exact scout terms
are checked; and a compact selected-anchor status—not every extracted
fact—is placed at the context tail.
