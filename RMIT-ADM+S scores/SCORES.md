# RMIT-ADM+S score summary (`all` rows)

Source: the TSVs in this folder. Rubric/nugget cells are `vital_strict / all_strict`.
BT, win/tie/loss exist only for the two side-by-side (SxS) priority runs.

`vital_strict` is coverage of essential items; `all_strict` includes essential
and optional items equally. Only full support earns credit. Each score is an
equally weighted mean across narratives: 17 in B1 and 25 in B2. For example,
`0.7231` means 72.31% average coverage, not a preference win rate.
Human-authored rubrics/nuggets describe the source of the expected items;
an LLM judges whether each answer supports them. Compare runs within a column:
the collections use different criteria.

| Run | B1 human rubric (v / a) | B2 manual nuggets (v / a) | B2 auto nuggets (v / a) |
| --- | --- | --- | --- |
| brief-base-t119 | 0.8235 / 0.8616 | 0.6907 / 0.7213 | 0.6482 / 0.5552 |
| brief-hybrid-t119 | **0.8922** / **0.9087** | **0.6914** / **0.7231** | 0.6442 / **0.5648** |
| facetrag-t119 | 0.6000 / 0.6217 | 0.4596 / 0.4807 | 0.1385 / 0.1104 |
| facets-t119 | 0.8314 / 0.8413 | 0.6270 / 0.6419 | 0.3898 / 0.3328 |
| owa-glm5-t119 | 0.8529 / 0.8213 | 0.5497 / 0.6054 | 0.2879 / 0.2432 |
| sol-default | 0.7902 / 0.8606 | 0.6789 / 0.7047 | 0.6296 / 0.5632 |
| sol-research-first | **0.8922** / 0.8866 | 0.6840 / 0.7018 | **0.6487** / 0.5600 |

## Side-by-side (top-2 priority runs only)

These are human preference results. Higher Bradley–Terry (BT) ratings are better
within a batch; ratings cannot be compared across batches. W/T/L counts are wins,
ties, and losses against the assessed field, not a direct head-to-head record
between these two runs. The other five runs were not assessed for human preference.

| Run | B1 BT (95% CI) | B1 W/T/L | B2 BT (95% CI) | B2 W/T/L |
| --- | --- | --- | --- | --- |
| owa-glm5-t119 | **1212.8** (1156.3–1269.3) | 123/23/34 | 1049.0 (1006.6–1091.4) | 122/28/94 |
| sol-research-first | 1062.7 (1013.7–1111.6) | 93/30/64 | **1124.7** (1081.0–1168.4) | 135/26/68 |

## Both batches merged

Merged = narrative-weighted mean over all 42 narratives: `(17 × B1 + 25 × B2) / 42`. Cells are `vital_strict / all_strict`. B2 uses the **manual** nuggets here; the auto-nugget version follows.

| Run | B1 (17 narratives) | B2 manual (25) | Merged (42) |
| --- | --- | --- | --- |
| brief-base-t119 | 0.8235 / 0.8616 | 0.6907 / 0.7213 | 0.7445 / 0.7781 |
| brief-hybrid-t119 | **0.8922 / 0.9087** | **0.6914 / 0.7231** | **0.7727 / 0.7982** |
| facetrag-t119 | 0.6000 / 0.6217 | 0.4596 / 0.4807 | 0.5164 / 0.5378 |
| facets-t119 | 0.8314 / 0.8413 | 0.6270 / 0.6419 | 0.7097 / 0.7226 |
| owa-glm5-t119 | 0.8529 / 0.8213 | 0.5497 / 0.6054 | 0.6724 / 0.6928 |
| sol-default | 0.7902 / 0.8606 | 0.6789 / 0.7047 | 0.7240 / 0.7678 |
| sol-research-first | **0.8922** / 0.8866 | 0.6840 / 0.7018 | 0.7683 / 0.7766 |

Same, with B2 auto nuggets:

| Run | B1 (17) | B2 auto (25) | Merged (42) |
| --- | --- | --- | --- |
| brief-base-t119 | 0.8235 / 0.8616 | 0.6482 / 0.5552 | 0.7192 / 0.6792 |
| brief-hybrid-t119 | **0.8922 / 0.9087** | 0.6442 / **0.5648** | 0.7446 / **0.7040** |
| facetrag-t119 | 0.6000 / 0.6217 | 0.1385 / 0.1104 | 0.3253 / 0.3174 |
| facets-t119 | 0.8314 / 0.8413 | 0.3898 / 0.3328 | 0.5685 / 0.5386 |
| owa-glm5-t119 | 0.8529 / 0.8213 | 0.2879 / 0.2432 | 0.5166 / 0.4772 |
| sol-default | 0.7902 / 0.8606 | 0.6296 / 0.5632 | 0.6946 / 0.6836 |
| sol-research-first | **0.8922** / 0.8866 | **0.6487** / 0.5600 | **0.7473** / 0.6922 |

Side-by-side, priority runs only. W/T/L are summed over both batches. BT scores are **not** merged: each batch is a separate Bradley–Terry fit, so ratings are not comparable across batches.

| Run | B1 W/T/L | B2 W/T/L | Merged W/T/L |
| --- | --- | --- | --- |
| owa-glm5-t119 | 123/23/34 | 122/28/94 | 245/51/128 |
| sol-research-first | 93/30/64 | 135/26/68 | 228/56/132 |

### How the merged numbers were computed

- **Inputs:** the `all` rows of `rag-rubric-scores-batch1-human.tsv` (B1) and of `rag-nugget-scores-batch2-manual.tsv` or `rag-nugget-scores-batch2-automatic.tsv` (B2). No per-narrative rows were used.
- **Formula:** `merged = (17 × B1 + 25 × B2) / 42`, applied separately to `vital_strict` and `all_strict`. Each `all` row is already an equally weighted mean over its batch's narratives, so this equals the mean over all 42 narratives pooled. A plain `(B1 + B2) / 2` would give each batch equal weight regardless of narrative count and was not used.
- **Pairing:** B1 is always the human-intuition rubric. B2 is shown twice, once with manual nuggets and once with auto nuggets. B1 is never mixed with the other B2 variant.
- **Rounding:** inputs are the published 4-decimal values, so merged values are rounded to 4 decimals from rounded inputs. The last digit may differ by 1 from a calculation on unrounded scores.
- **Side-by-side counts:** wins, ties and losses are summed per run across the two batches' `all` rows.
- **BT scores:** not merged. Each batch is its own Bradley–Terry fit, so ratings sit on different scales and cannot be averaged or compared across batches.
- **Not merged:** the `_min`, `_max` and `_median` reference columns, which are per-batch statistics over all submitted runs.
- **Assumption:** both batches cover the same 7 runs. Neither batch weights narratives by item count, so a narrative with few items counts as much as one with many.

To reproduce, load the `all` rows into `{run: (vital_strict, all_strict)}` for each file and take `(17 × b1 + 25 × b2) / 42` per metric.

Bold = best in column. B1 = batch 1, B2 = batch 2, v = `vital_strict`, a = `all_strict`.

## How the scores are produced

**Vital / all strict (rubric and nugget files)**

- Batch 1: rubric items were written by assessors from the topic statement and their own world knowledge, not from documents.
- Batch 2: nuggets are document-grounded, extracted by assessors from corpus shards. The automatic variant is generated by RAGDoll's AutoNuggetizer.
- In every collection, an LLM judge decides per item whether the response fully supports it (`support` / `partial_support` / `not_support`). The judge model is OpenAI's GPT-6.1 Sol at medium reasoning, for all three collections. The grading prompt is not included in the README.

**Bradley–Terry (BT) scores and win/tie/loss counts**

- Batch 1: assessors compared the two systems' report text side by side. Rubric items are not really used in this comparison.
- Batch 2: assessors built document-grounded nuggets, then judged the report text by how well it covers them. This is a manual judgment, with no LLM alignment step as far as we know (unconfirmed).

**Open questions for NIST**

- Are the Batch 2 source documents the ones cited in the responses, or ones from retrieval runs? The README says only "corpus shards".
- What is the exact LLM grading/alignment prompt used for the `vital` / `all` assignments?
- Is the Batch 2 BT judgment really fully manual, with no LLM involved?

## Brief summary and conclusions

**`brief-hybrid-t119` leads coverage; human preferences favor different runs
across the two batches.** This table expresses `all_strict` as percentages.

| Run | B1 rubric coverage | B2 manual nugget coverage | B2 automatic nugget coverage |
| --- | --- | --- | --- |
| brief-hybrid-t119 | **90.87%** | **72.31%** | **56.48%** |
| brief-base-t119 | 86.16% | 72.13% | 55.52% |
| sol-default | 86.06% | 70.47% | 56.32% |
| sol-research-first | 88.66% | 70.18% | 56.00% |
| facets-t119 | 84.13% | 64.19% | 33.28% |
| owa-glm5-t119 | 82.13% | 60.54% | 24.32% |
| facetrag-t119 | 62.17% | 48.07% | 11.04% |

Average generation usage per topic:

| Run | Uncached input tokens | Cached input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| brief-hybrid-t119 | 293,077 | 322,397 | 7,544 |
| brief-base-t119 | 319,561 | 388,548 | 8,024 |
| sol-default | 183,681 | 203,228 | 6,129 |
| sol-research-first | 330,535 | 369,329 | 10,479 |
| facets-t119 | 138,936 | 71,421 | 5,912 |
| owa-glm5-t119 | 415,080 | 0 | 5,899 |
| facetrag-t119 | 411,653 | 0 | 49,727 |

Generation cost per topic (USD). "As billed" is what the run's provider charged or
would have charged; "Azure-equivalent" reprices the OpenAI runs at one common
rate card so they compare fairly:

| Run | Provider | As billed | Azure-equivalent |
| --- | --- | ---: | ---: |
| brief-hybrid-t119 | Azure (inferred) | $1.853 (estimated) | $1.853 |
| brief-base-t119 | Azure (inferred) | $2.033 (estimated) | $2.033 |
| sol-default | Bedrock | $1.566 (derived from AWS bill) | $1.195 |
| sol-research-first | Bedrock | $2.823 (derived from AWS bill) | $2.152 |
| facets-t119 | Azure (inferred) | $0.036 (estimated) | $0.036 |
| owa-glm5-t119 | Bedrock | $0.517 (AWS GLM-5 rate x traced tokens) | n/a (open-weight) |
| facetrag-t119 | not reconciled | about $0.09-0.14 (estimated) | n/a (open-weight) |

Token usage and costs average over all 119 test topics, excluding judging and
preflight runs. Processed tokens count uncached input and output across model
calls; cached-input reads are separate. Tokens measure accumulated generation
work, not answer length or peak context size. Averages are rounded
independently. The token breakdowns were recovered from usage traces matched to
each submitted answer. See the [input/output worklog](../worklogs/2026-11-04-input-output-usage.md)
and the [Sol recovery worklog](../worklogs/2026-11-04-sol-cost-recovery.md) for
totals and per-topic rows, and the [cost reconciliation worklog](../worklogs/2026-11-09-cost-reconciliation-aws.md)
for the AWS evidence, rates and arithmetic.

**Rate cards used (USD per 1M tokens: uncached input / cached input / output).**

- *Azure-equivalent Sol*: 5.00 / 0.50 / 30.00 (OpenAI list; Azure Global Standard
  is assumed to match, with no cache-write fee). *Luna*: 0.20 / 0.02 / 1.20.
- *Bedrock Sol, as billed (AWS Cost Explorer, Aug 7)*: input 5.50, cache read
  0.55, cache write 6.88, output 33.00. This is a **10% markup** over the
  OpenAI list rate on every line (Luna on Bedrock is likewise 1.10x list:
  0.22 / 0.022 / 1.32). Bedrock also bills the traces' "uncached input" as
  *cache writes* at 1.25x the input rate (6.88), so those tokens cost 38% more
  than on Azure.
- *Bedrock GLM-5*: 1.20 input, 3.20 output.

**Evidence and limits.** The two Sol runs were executed through Bedrock
(`bedrock-mantle`, us-east-1) and their cost is derived from billed AWS usage:
the traces' token totals match the Aug 7 bill (cache writes 61.0M vs 61.65M
billed, cache reads 68.0M vs 68.7M, output 1.97M vs 2.13M) and the rate-card
cost of the two runs, $522.29, accounts for 98% of that day's $532.77; the
remainder is preflight and failed-request usage. Sol-default figures exclude its
two failed attempts (179,386 processed tokens, roughly $0.01 per topic more).
The brief and facets runs went through Azure OpenAI by configuration and model
naming, but no Azure invoice or request log has been checked, so their costs are
rate-card estimates and the Luna rate is inferred from Bedrock. The earlier
placeholder of $5 per million processed tokens is retired. The previously
reported $0.163 for owa-glm5 is superseded: at AWS's GLM-5 rates the traced
tokens cost about $0.52 per topic (about $61.5 for the run). Facetrag's earlier
$0.178 could not be matched to billing in the AWS account examined (only
$1.80 of gpt-oss-120b on Aug 8), so it is shown as a rate-card range. All
figures are generation-only, not total system operating costs.

- **Hybrid has the strongest combined coverage-and-efficiency evidence.** It
  leads all three all-item coverage columns. Compared with brief-base, the gains
  are 4.71 percentage points in B1, 0.18 on B2 manual nuggets, and 0.96 on B2
  automatic nuggets. The report records about 8% fewer processed tokens and 14%
  fewer searches for hybrid. Its B2 coverage advantage is small, and its internal
  preference comparison with brief-base was nearly tied and position-sensitive.
- **Coverage and human preference give different rankings.** OWA leads B1 BT
  ratings, 1212.8 versus 1062.7 for research-first, despite lower coverage.
  Research-first leads B2, 1124.7 versus 1049.0. B1 confidence intervals do not
  overlap; B2 intervals overlap. These intervals alone do not establish the
  significance of the difference.
- **Extra engineering has selective benefits.** Research-first improves
  vital-only coverage over sol-default by 10.20, 0.51, and 1.91 percentage points
  across the three collections, but slightly lowers all-item coverage in both B2
  collections. It made about 31% more searches and costs about 80% more
  per topic than sol-default, both as billed on Bedrock ($2.823 vs $1.566) and
  under the common Azure-equivalent rate card ($2.152 vs $1.195). This is a
  substantial cost increase for selective coverage gains.
- **Open-weight generation remains competitive on human preference at lower
  cost.** OWA cost about $0.52 per topic as billed (versus $1.57-$2.82 for the
  Bedrock Sol runs) and trails the strongest proprietary
  runs on nugget coverage, but its B1 human preference result rules out a blanket
  conclusion that it produces worse answers under every evaluation. The report's
  fixed-evidence replay used Qwen, so its writer-level diagnosis cannot simply be
  transferred to GLM-5.
- **More searching did not guarantee greater coverage.** Facetrag is last in all
  coverage columns despite making the most searches (33.7 per topic); it also
  produced the shortest answers (about 389 words). Model and architecture changes
  are confounded, so this does not isolate facet decomposition as the cause.
- **There is no demonstrated overall winner.** Hybrid and brief-base have no
  official human preference assessment. Coverage does not establish citation
  quality; the report found References and Citation Quality to be the weakest
  axis throughout its brief-agent factor study.

Report context comes from the separate `trec-rag-26-report` repository:
`sections/system-overview.tex`, `sections/retrieval.tex`, `sections/results.tex`,
`sections/submitted-runs.tex`, and `tables/submissions.tex`. Its internal
experiments predate these official results and are distinct from them. Cost
figures there used a placeholder price and are superseded by the table above.
The $1,096.72 attributed to research-first is development expenditure, not
test-generation cost; AWS shows $1,092.97 of Sol spend on Aug 5-6.

Paired significance has not been tested here, and the underlying assignments
remain withheld. Small coverage gaps are descriptive. The combined 42-narrative
scores above pool different evaluation criteria and do not replace the per-batch
results.
