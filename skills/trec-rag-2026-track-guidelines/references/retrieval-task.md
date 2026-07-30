# Retrieval Task (`R`)

Use this reference when building, explaining, or validating the TREC RAG 2026 Retrieval task.

## Task Summary

- **Given**: a list of narratives and access to the ClimbMix collection through the Pyserini REST API or a custom retrieval system.
- **Task**: return a ranked list containing all and only the ClimbMix documents the system predicts are relevant to the narrative and useful as evidence for answer generation.
- **Depth**: choose the submitted depth `k` separately for each narrative. There is no organizer-supplied fixed cutoff to fill.

## Input Format: Narratives

Use the official shared test-narrative file described in [test-data.md](test-data.md). Narratives are provided as TSV in `trec_rag_2026_queries.tsv`. Each line contains the narrative ID and narrative, separated by a tab.

```tsv
rag2026-37	I work for a New York City council member whose district has a lot of transit riders but also some small businesses worried about delivery costs. Can you help me understand whether congestion pricing is a credible and fair way to fund the MTA? What should we weigh about the revenue promise, who pays, who benefits, environmental tradeoffs in places like the Bronx and New Jersey, and whether the MTA and Albany can be held accountable for actually spending the money on reliable service instead of repeating past mistakes?
```

Required fields:

- First column: narrative identifier. Preserve this exactly in all outputs.
- Second column: narrative, usually a two- to three-sentence description of the information need. Use it as the default initial retrieval query unless the system intentionally performs query rewriting or decomposition internally. For `RAG` output, copy this value exactly into `metadata.narrative`.

## Input Format: Documents

For baseline systems, retrieve ClimbMix documents from the Pyserini REST API. The configured index name is:

```text
climbmix-400b
```

Search returns a response with a `candidates` array. Each candidate represents one retrieved ClimbMix document:

```json
{
  "api": "v1",
  "index": "climbmix-400b",
  "query": { "text": "congestion pricing MTA funding accountability" },
  "candidates": [
    {
      "docid": "shard_00459_61697",
      "rank": 1,
      "score": 12.483799934387207,
      "doc": "..."
    }
  ]
}
```

Document fetch by ClimbMix document ID returns one document wrapper:

```json
{
  "api": "v1",
  "index": "climbmix-400b",
  "docid": "shard_00459_61697",
  "doc": "..."
}
```

Document field rules:

- `docid`: ClimbMix document ID to use in submissions.
- `rank`: returned rank for a search candidate.
- `score`: retrieval score for a search candidate.
- `doc`: ClimbMix document contents. The Pyserini REST API schema allows this payload to be a string, object, array, number, boolean, or null depending on index contents and `parse` behavior. Current ClimbMix search responses commonly return `doc` as a string containing the document text.

Use `docid` as the external identifier in Retrieval run files and RAG `references`. Use the document text from `doc` as evidence content. Do not put full `doc` payloads, raw snippets, `rank`, or `score` in official Retrieval or RAG outputs unless official instructions explicitly require them.

When a system needs full document contents for generation, fetch by `docid` through the document endpoint. If `doc` is an object, extract its text-bearing field such as `text` or `contents`; if it is a string, use the string directly as the document text. If the API returns raw stored JSON instead of parsed content, parse it according to the `pyserini-rest-api` skill before extracting the document text.

## Variable-Depth Retrieval Rule

For each narrative, participants must choose how many documents to submit. Call that narrative-specific number `k`.

The intended target is **all and only** documents that the system predicts satisfy both of these conditions:

1. The document is relevant to the narrative.
2. The document is useful evidence for producing a high-quality answer to the narrative.

Submit those `k` documents in predicted usefulness order, with the most useful document at rank 1. The value of `k` may differ across narratives because some information needs require more supporting evidence than others.

There is no fixed submission depth that participants should pad to. In particular:

- Do not add documents merely to reach a conventional cutoff such as 10, 100, or 1000.
- Do not treat a larger submitted set as inherently better.

This rule applies to the final submitted Retrieval (`R`) run, not to internal candidate generation. A system may retrieve a large fixed-depth candidate pool, perform query decomposition, fuse multiple searches, or rerank many candidates internally. It should then select and submit only its final narrative-specific `k` useful documents in the Retrieval run.

For example, if a system predicts that 7 documents are useful for one narrative and 23 are useful for another, it should submit 7 and 23 respectively. It should not expand both lists to 100 merely because it retrieved 100 internal candidates.

## Output Format: Ranked Results

For official submissions, provide a standard TREC runfile in `r_output_trec_rag_2026.tsv`. Each line contains six whitespace-separated fields:

```text
topic_id Q0 docid rank score run_id
```

Example:

```text
rag2026-37 Q0 shard_00459_61697 1 12.4838 my-run
rag2026-37 Q0 shard_01012_88420 2 11.9721 my-run
rag2026-37 Q0 shard_00210_44018 3 10.5542 my-run
rag2026-38 Q0 shard_00044_91812 1 10.8114 my-run
```

**Note:** The different list lengths are intentional. Each narrative has its own `k`: this example submits `k = 3` documents for `rag2026-37` and `k = 1` document for `rag2026-38`. Participants should submit the selected `k` documents for each narrative rather than use one fixed depth across the run.

Field rules:

- `topic_id`: narrative identifier from `trec_rag_2026_queries.tsv`; `topic_id` is the standard TREC run-file field name.
- `Q0`: fixed string.
- `docid`: ClimbMix document ID.
- `rank`: rank of the retrieved document for that narrative, starting at 1.
- `score`: numeric score used to rank documents.
- `run_id`: stable identifier for the submitted run.

## Validation Rules

- There is no fixed required number of rows per narrative and no fixed maximum submission depth.
- The number of submitted rows `k` is selected independently for each narrative and may vary across narratives.
- Submit exactly the documents the system predicts are relevant and useful for answer generation; do not pad a narrative to a fixed depth.
- Sort each narrative's rows by rank ascending.
- Keep scores non-increasing within each narrative.
- `r_output_trec_rag_2026.tsv` must have exactly six whitespace-separated columns per line.
- Retrieval ranks must restart at 1 for each narrative.
- Every Retrieval `docid` must be a ClimbMix document ID returned by the retriever or custom index.
- Do not emit MS MARCO segment IDs unless official 2026 instructions explicitly require a mapping step.
