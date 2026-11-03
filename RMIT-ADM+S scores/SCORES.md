# RMIT-ADM+S score summary (`all` rows)

Source: the TSVs in this folder. Rubric/nugget cells are `vital_strict / all_strict`.
BT, win/tie/loss exist only for the two side-by-side (SxS) priority runs.

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

## Takeaways

- `brief-hybrid-t119` leads rubric/nugget metrics almost everywhere; `sol-research-first` is close and wins auto-nugget vital.
- `facetrag-t119` is last on every rubric/nugget metric.
- SxS point estimates flip between batches: `owa-glm5-t119` leads batch 1 (CIs do not overlap), while `sol-research-first` leads batch 2 (CIs overlap), despite `owa-glm5-t119` scoring well below it on batch-2 nuggets. These intervals alone do not establish the significance of the difference.
