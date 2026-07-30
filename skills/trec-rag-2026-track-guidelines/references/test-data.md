# TREC RAG 2026 Test Narratives

Sources checked July 17, 2026:

- Release announcement: https://x.com/TREC_RAG/status/2074513634043064419
- Track homepage: https://trec-rag.github.io/
- Data repository: https://github.com/TREC-RAG/trec-rag-data
- Official narrative file: https://github.com/TREC-RAG/trec-rag-data/blob/main/trec-rag-2026/test-data/trec_rag_2026_queries.tsv

## Summary

The official TREC RAG 2026 test narratives have been released. The same test-data file is the input for both the Retrieval (`R`) and Retrieval-Augmented Generation (`RAG`) tasks.

Use the official file from the [`TREC-RAG/trec-rag-data`](https://github.com/TREC-RAG/trec-rag-data) repository:

```text
trec-rag-2026/test-data/trec_rag_2026_queries.tsv
```

The file is named:

```text
trec_rag_2026_queries.tsv
```

## Contents and Schema

The released file contains 119 narratives, with narrative identifiers from `rag2026-0` through `rag2026-118`. It has no header row.

Each line contains exactly two tab-separated fields:

```text
narrative_id<TAB>narrative
```

For example:

```tsv
rag2026-37	I work for a New York City council member whose district has a lot of transit riders but also some small businesses worried about delivery costs. Can you help me understand whether congestion pricing is a credible and fair way to fund the MTA? What should we weigh about the revenue promise, who pays, who benefits, environmental tradeoffs in places like the Bronx and New Jersey, and whether the MTA and Albany can be held accountable for actually spending the money on reliable service instead of repeating past mistakes?
```

- `narrative_id`: the official identifier. Preserve it exactly in every task output.
- `narrative`: the official long-form description of the information need. Preserve it exactly when a task output requires the narrative.

Parse the file as TSV, not as arbitrary whitespace-separated text. Narratives contain many spaces and may contain punctuation, Unicode apostrophes, numbers, or formatting requests.

## Use by Task

For Retrieval (`R`):

- Produce ranked ClimbMix document IDs for each narrative.
- Put the exact narrative ID in the `topic_id` field of every TREC run-file row.

For Retrieval-Augmented Generation (`RAG`):

- Use the exact narrative ID as `metadata.narrative_id`.
- Copy the corresponding `narrative` exactly into `metadata.narrative`.
- Retrieve and cite ClimbMix evidence before producing the answer.

Use the task-specific references for all remaining output and validation requirements.

## Test Data Versus Development Data

These are the official test narratives, not practice data. Do not substitute narratives or prompts from the development-data directory when preparing a complete official run.

The released development nuggets, rubrics, and projected UMBRELA qrels are diagnostics for their corresponding development data. They are not labels for the 2026 test narratives and must not be joined to test narratives by row position or assumed semantic similarity.

No official test-narrative qrels, answer nuggets, or gold answers are included in the released test-data directory as of the source check above. Do not present development scores as estimates of official test-set performance without clearly labeling the methodology and its limitations.

## Handling and Validation

- Download or copy the narrative file from the official `TREC-RAG/trec-rag-data` repository.
- Keep the source narrative file unchanged; write system outputs to separate files.
- Expect 119 data rows and no header.
- Verify that all narrative IDs are unique.
- Preserve narrative IDs, narratives, row contents, and UTF-8 characters exactly.
- Unless a subset run was explicitly requested, produce output for all 119 narratives.
- Do not reorder, renumber, or normalize narrative identifiers.
- For reproducible experiments, record the source repository revision or a checksum of the downloaded narrative file.

The SHA-256 checksum of the raw narrative file checked July 17, 2026 is:

```text
72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c
```

Before submission-critical work, check the official data repository and track homepage for corrections or replacement files. If the official narrative file changes, follow the newer release and record which revision was used.
