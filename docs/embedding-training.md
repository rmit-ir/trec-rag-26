# Retrieval embedding fine-tuning

The submitted dense retriever uses
[`RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d`](https://huggingface.co/RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d).
Shuai performed the fine-tuning on his server (operator provenance supplied by
the user on 2026-11-04). The final recipe below is reported by its Hugging Face
model card, checked on 2026-11-04 at revision
`f990deb3ee162bade37c19f63712b1a8ac0d0205`. The author's repository,
`wshuai190/jina-v5-nano-trecrag26-agent-256d`, resolves to the same revision.
Both repository file inventories were checked; neither includes a trainer
script, trainer state, split manifest, or optimizer log.

The [preserved model card](../worklogs/assets/2026-11-04-embedding-training/README.md)
and [configuration snapshot](../worklogs/assets/2026-11-04-embedding-training/)
are the source record. This is documentation of the released model, not a new
training run or independent reproduction of the model-card results. The user
made the RMIT-ADMS model card public on 2026-11-04; its public link above can be
cited alongside this repository record.

## Data and supervision

GPT-5.6-Luna `aus_agent` runs answered all 119 official TREC RAG 2026 test
topics twice: one semantic-retrieval arm and one keyword/BM25 arm. Search results
were staged for an explicit evidence-retention decision. The exporter joins
each search sub-query and candidate chunk text to the commitment ledger across
that topic run:

- A chunk committed anywhere in the run, including later duplicate occurrences
  of committed evidence, is positive.
- A chunk with no commitment decision, or only an invalid-commit batch-expiry
  marker, is unjudged.
- Other non-selections are weak negative labels. They record agent selection
  behavior, rather than independently established irrelevance.

The preparation export contains **2,143 search-call rows** (1,073 semantic,
1,070 keyword), with **4,857 positive, 12,889 negative and 342 unjudged hit
occurrences**. These are exporter counts, not final training-example counts.
Its code is [build_finetune_dataset.py](../tasks/task-comparison/scripts/build_finetune_dataset.py);
the [July 29 worklog, July 30 addendum](../worklogs/2026-07-29-test119-semantic-vs-keyword-runs.md)
records the counts, duplicate/expiry handling and text-prefix caveat.

The released model card describes the final training pairs as
**search sub-query → committed chunk**, with **1,587 sub-queries / 3,849 pairs
from 95 topics**. The remaining **24 topics / 410 sub-queries** form validation.
Thus the final selected recipe uses positive pairs with in-batch negatives;
it does not say that every weak negative in the preparation export was consumed.
Mined hard negatives were among the compared alternatives, not the reported
winning configuration. Exact topic IDs and pair-selection code are not uploaded.

## Final recipe reported in the model card

| Item | Released configuration |
| --- | --- |
| Base | `jinaai/jina-embeddings-v5-text-nano`, retrieval adapter merged into EuroBERT |
| Trainer | `texttron/tevatron`, patched to truncate representations before normalization |
| Objective | InfoNCE over the first 256 dimensions; one Matryoshka target |
| Adaptation | LoRA, rank 16, alpha 64, dropout 0.1, all attention and MLP projections |
| Learning rate | `1e-4` |
| Epochs | 4 |
| Batch size | 64; per-device/global interpretation and accumulation are not specified |
| Negatives | In-batch |
| Temperature | 0.05 |
| Precision | bf16 |
| Query / document prefixes | `"Query: "` / `"Document: "` (including trailing spaces) |
| Pooling / output | Last-token pooling; 256-dimensional, L2-normalized embeddings |
| Release | Adapter merged into standalone weights; no runtime adapter or remote code |
| Versions | sentence-transformers 5.6.1, transformers 5.14.1, torch 2.13.0; patched Tevatron commit unspecified |

The small saved configs independently confirm `truncate_dim=256`, the two
prefixes, last-token pooling and a Transformer → Pooling → Normalize module
layout. The card's usage example sets `max_length=1024`; the final training
query/passage length limits are not separately specified. The card states that
other output dimensions are not guaranteed preserved.

The card reports comparison with full fine-tuning, narrative-plus-subquery
concatenation, mixed augmentation and mined hard negatives, with the released
configuration selected on validation topics. It does not upload that sweep's
full matrix.

## Reported validation results

These are **model-card results**, not rerun here. Pool ranking uses 4,071
agent-committed chunks and the 24-topic, 410-sub-query validation set at 256
dimensions. This is a restricted candidate-pool evaluation with agent-derived
labels, not full-corpus retrieval or official organizer judgments.

| Model | nDCG@10 | MRR@10 | Recall@10 | Recall@20 |
| --- | ---: | ---: | ---: | ---: |
| Base nano, merged retrieval adapter, 256d | 0.751 | 0.749 | 0.900 | 0.970 |
| Released fine-tune, 256d | 0.793 | 0.796 | 0.946 | 0.989 |

For the 209 validation sub-queries from the BM25 arm, the card reports nDCG@10
0.604 → 0.752, 129 wins / 23 losses, and a paired t-test p ≈ `7e-22`.
BM25 candidates avoid dense-model candidate selection in that arm, but the
labels remain agent decisions; this is not an independent human relevance test.
The card does not specify clustering of the test by topic, so its sub-query
p-value should not be interpreted as a topic-level significance test.

A separate [22-topic 2025 general-topic probe](../worklogs/2026-08-02-ft-full-encode-and-speedup-investigation.md)
reports nDCG@10 0.7196 versus 0.7127 for the base. That probe uses a different
protocol and does not isolate the benefit of trajectory supervision.

## Reproducibility limits and evaluation scope

The released recipe and 95/24 topic split are documented. The exact split IDs,
random seed, final dataset hashes, filtering/deduplication and prefix-stripping
choices, optimizer class/settings, schedule, warmup, weight decay, sequence
limits, device count, accumulation, exact Tevatron patch/commit, selected
checkpoint and training logs remain absent from the uploaded files. Obtaining
those from Shuai is needed for an exact reproduction; do not substitute defaults.

The embedding split is over the **official 2026 test topics**, without using
organizer relevance labels in the documented supervision. It is separate from
the later generator-development partitions (`dev20`, `confirm40`, `holdout59`
and the 15-topic comparisons). Without the embedding split IDs and an overlap
audit, these generator partitions cannot be called unseen by the retriever.
The card's held-out retrieval validation supports its stated pool-ranking
comparison; it does not establish a held-out end-to-end generator evaluation.

For release integration, corpus encoding and query-serving parity, see the
[July 31 integration record](../worklogs/2026-07-31-finetuned-model-integration.md)
and [August 2 integrity and evaluation record](../worklogs/2026-08-02-ft-full-encode-and-speedup-investigation.md).
