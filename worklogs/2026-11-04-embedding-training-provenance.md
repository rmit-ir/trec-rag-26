# Recover final embedding-training documentation

The user asked to document final training details in this repository and add a
footnote to the report. They clarified that Shuai trained the model on his own
server and suggested checking Hugging Face.

## Findings and changes

- Added `docs/embedding-training.md`: final recipe, train/validation population,
  weak-label provenance, reported validation results, inference configuration,
  source links and exact remaining reproduction gaps.
- Preserved the model card and five small configs under
  `worklogs/assets/2026-11-04-embedding-training/`, with a file inventory and
  provenance manifest. No weights, datasets, credentials or tokenizers copied.
- Hugging Face model revision:
  `f990deb3ee162bade37c19f63712b1a8ac0d0205`, both
  `RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d` and
  `wshuai190/jina-v5-nano-trecrag26-agent-256d`. The card is an author-reported
  record; the training run and validation measurements were not reproduced.
- Card reports 95 training topics, 1,587 sub-queries and 3,849 positive pairs;
  24 validation topics and 410 sub-queries. In-batch negatives and a 256d InfoNCE
  objective, LoRA rank 16 / alpha 64 / dropout 0.1, lr 1e-4, four epochs, batch
  64, temperature 0.05, bf16. Full recipe and reported metric matrix are in the
  documentation and preserved source card.
- Updated sibling report `sections/retrieval.tex` with this recipe and a
  footnote to `docs/embedding-training.md`; corrected the experimental-setup
  caveat from unknown split to known 95/24 counts with unpublished topic IDs.

## Search and access scope

Before the user clarified provenance, inspected the local project and shared
data, Sunfyre project and Kun checkout
`/scratch/fast/kun/projects/trec-rag-26`, and relevant available GPU-server
directory inventories. These contained export/integration evidence but no
final Jina trainer records. A Sunfyre cached-model README read was refused as
outside connector roots; no workaround was used. After the explicit Hugging
Face request, used the HF connector for metadata and authenticated
`huggingface_hub` read-only calls for small files. No `.env` or secret file
contents were inspected. No paid inference or training was launched.

The model repositories contain only release weights/configuration/tokenizer
and the model card. Trainer scripts/state, exact split IDs, dataset hashes,
optimizer logs and the patched Tevatron revision are absent. Do not invent them
from library defaults. The document distinguishes final training counts from
the preparation export's 2,143 rows / 4,857 positive / 12,889 negative / 342
unjudged hit occurrences. It also keeps the agent-labelled pool-ranking
validation separate from official judgments and end-to-end generator holdouts.

## Verification

Inspected the complete card, inventories for both model IDs, and small model
configs. Configs confirm prefixes, 256d truncation, last-token pooling and
normalization. No source code changed; no experiment or historical dataset
recount was run. `bash scripts/test.sh` passed all 1,970 offline tests (12 live
tests deselected); `git diff --check` passed. Initial sandboxed test invocation
could not access the uv cache; rerunning with cache access completed normally.
Report compiled twice to seven pages without errors, undefined references or
overfull boxes; affected rendered pages and the linked footnote were inspected.
The user made the RMIT-ADMS card public during the session; the report links it
alongside the repository documentation.
