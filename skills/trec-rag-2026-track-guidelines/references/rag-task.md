# Retrieval-Augmented Generation Task (`RAG`)

Use this reference when building, explaining, or validating the TREC RAG 2026 Retrieval-Augmented Generation task.

## Task Summary

- **Given**: a list of narratives and access to ClimbMix retrieval results and document contents.
- **Task**: retrieve relevant evidence and return a summarized answer grounded in that evidence for each narrative.
- **Notes**: this task best matches an industrial RAG setup that combines retrieval, evidence selection, and generation. The answer should be evaluated as both an answer and a grounded, cited use of retrieved material.

Unlike the removed `AG` task, the 2026 `RAG` task does not assume a fixed provided evidence set. The system is responsible for retrieval. Use the Pyserini REST baseline retriever when focusing on answer generation.

## Input Format: Narratives

Use the official shared test-narrative file described in [test-data.md](test-data.md). Each input line in `trec_rag_2026_queries.tsv` contains two tab-separated fields: narrative ID and narrative. Preserve the narrative ID exactly in `metadata.narrative_id` and copy the narrative exactly into `metadata.narrative`.

Example:

```tsv
rag2026-37	I work for a New York City council member whose district has a lot of transit riders but also some small businesses worried about delivery costs. Can you help me understand whether congestion pricing is a credible and fair way to fund the MTA? What should we weigh about the revenue promise, who pays, who benefits, environmental tradeoffs in places like the Bronx and New Jersey, and whether the MTA and Albany can be held accountable for actually spending the money on reliable service instead of repeating past mistakes?
```

## Input Format: Documents

Use ClimbMix documents returned by retrieval as the evidence source. Search returns candidate objects with `docid`, `rank`, `score`, and `doc`; document fetch returns a wrapper with `docid` and `doc`.

```json
{
  "docid": "shard_00459_61697",
  "rank": 1,
  "score": 12.483799934387207,
  "doc": "..."
}
```

A RAG system may:

- Use the document text from `doc` returned directly in search results.
- Fetch full document contents with `GET /v1/climbmix-400b/doc/{docid}`.
- Apply its own chunking or passage selection internally.

The Pyserini REST API schema allows `doc` to be a string, object, array, number, boolean, or null depending on index contents and `parse` behavior. Current ClimbMix search responses commonly return `doc` as a string containing the document text. If `doc` is an object, extract its text-bearing field such as `text` or `contents`; if it is a string, use the string directly.

Use the ClimbMix `docid` as the evidence identifier in final RAG `references`. Use the document text as evidence for writing cited answer sentences. Keep `references` as a list of document IDs rather than full document payloads; ranks, scores, snippets, retrieval settings, and other participant-defined information may be recorded as additional metadata when useful.

The `references` list may include retrieved documents that are not cited by any answer sentence. Uncited entries do not hurt the score. Systems may therefore preserve a larger retrieved evidence set in `references`, although keeping only useful documents can make submissions easier to inspect.

If a system chunks documents internally, keep final `references` tied to ClimbMix document IDs.

## Output Format: RAG Output

For official submissions, provide JSONL in `rag_output_trec_rag_2026.jsonl`, with one JSON object per narrative.

```json
{
  "metadata": {
    "team_id": "my-team",
    "narrative_id": "rag2026-37",
    "narrative": "I work for a New York City council member whose district has a lot of transit riders but also some small businesses worried about delivery costs. Can you help me understand whether congestion pricing is a credible and fair way to fund the MTA? What should we weigh about the revenue promise, who pays, who benefits, environmental tradeoffs in places like the Bronx and New Jersey, and whether the MTA and Albany can be held accountable for actually spending the money on reliable service instead of repeating past mistakes?",
    "run_id": "my-rag-run",
    "run_desc": "BM25 top-100 ClimbMix retrieval with agent-written evidence-grounded sentence answers.",
    "generator": "example-model",
    "retrieval_depth": 100
  },
  "references": [
    "shard_00459_61697",
    "shard_01012_88420",
    "shard_00210_44018"
  ],
  "answer": [
    {
      "text": "Congestion pricing should be assessed by whether it can provide reliable dedicated revenue for transit improvements while managing the distribution of costs across drivers, riders, and affected neighborhoods.",
      "citations": [0, 1]
    },
    {
      "text": "A credible plan should also explain how environmental impacts, delivery concerns, and MTA spending accountability will be monitored after implementation.",
      "citations": [1, 2]
    }
  ]
}
```

The example above uses zero-based reference positions. The same citations may instead name the supporting document IDs directly:

```json
{
  "answer": [
    {
      "text": "Congestion pricing should be assessed by whether it can provide reliable dedicated revenue for transit improvements while managing the distribution of costs across drivers, riders, and affected neighborhoods.",
      "citations": ["shard_00459_61697", "shard_01012_88420"]
    },
    {
      "text": "A credible plan should also explain how environmental impacts, delivery concerns, and MTA spending accountability will be monitored after implementation.",
      "citations": ["shard_01012_88420", "shard_00210_44018"]
    }
  ]
}
```

Required fields:

- `metadata.team_id`: team identifier.
- `metadata.narrative_id`: narrative ID from the first column of `trec_rag_2026_queries.tsv`.
- `metadata.narrative`: narrative from the second column of `trec_rag_2026_queries.tsv`, copied exactly.
- `metadata.run_id`: run identifier.
- `metadata.run_desc`: short description of the submitted system or run.
- `metadata`: may also contain any additional participant-defined fields.
- `references`: ordered list of retrieved ClimbMix document IDs. It may include documents that are not cited by the answer; uncited references do not hurt the score.
- `answer`: array of sentence-level answer objects. The full response may be up to 1,024 words per narrative.
- `answer[].text`: answer sentence.

“Sentence-level” describes the intended citation granularity. Validators should treat `answer[].text` as an opaque, non-empty text string and should not attempt grammatical sentence detection. Markdown formatting, including standalone section headings, is permitted. Such formatting must still satisfy the normal citation and word-limit requirements.

For the 1,024-word limit, “word” is defined in Python parlance using `str.split()` with no separator. Count each answer object's text with `len(text.split())` and sum those counts across the `answer` array. Equivalently, compute `sum(len(item["text"].split()) for item in answer)`.

- `answer[].citations`: array of zero to three citations for that answer object. An empty array (`[]`) is valid. Each citation may be either a zero-based integer position into `references` or the corresponding ClimbMix `docid` string written directly.

Additional metadata is welcome. A system may use participant-defined metadata fields to document prompts, generation type, retrieval configuration, diagnostics, or other useful run information, as long as the required metadata fields remain present and valid.

## Evaluation

The TREC RAG organizers will evaluate submitted RAG responses using system-by-system battles. For each narrative, responses from two submitted systems will be paired for side-by-side comparison, with system identities hidden and presentation order randomized. The evaluator will choose which response is better, or may indicate that the responses are tied when neither is clearly preferable.

Each submitted response will also receive individualized nugget rubric scoring in the style of AutoNuggetizer. This evaluates each response independently against narrative-specific nugget criteria rather than only through pairwise comparison.

Evidence support is scored in two complementary dimensions:

- **Weighted citation precision** measures the weighted proportion of supplied citations that support their associated answer sentence or object. It evaluates only answer objects with one or more citations and asks whether those citations are correct.
- **Weighted citation recall** measures the weighted proportion of answer sentences or objects that are supported by their cited passages. An answer object with no citations receives a support score of 0 for weighted recall.

An answer object with no citations is omitted from citation-precision scoring and receives a support score of 0 for weighted recall. Therefore, any scoring penalty for choosing zero citations is applied through citation recall, not citation precision.

For additional background on this support-evaluation methodology, see Thakur et al., [*Assessing Support for the TREC 2024 RAG Track: A Large-Scale Comparative Study of LLM and Human Evaluations*](https://dl.acm.org/doi/pdf/10.1145/3726302.3730165).

These evaluation procedures are organizer-run and are not produced by participant agents or included in the submitted RAG JSONL output. Participants should focus on producing accurate, well-grounded, cited answers; the evaluation will be applied after submission by the organizers.

## Answer Rules

- Break prose into sentence-level answer objects. Standalone Markdown elements, including section headings, labels, and table rows, may occupy their own answer objects.
- Keep the full response at or below 1,024 words per narrative using the word-count definition above.
- Ground each sentence in retrieved evidence.
- Use zero to three citations per answer object. An empty `citations` array is permitted.
- Encode each citation either as a valid zero-based integer position into `references` or as the exact ClimbMix `docid` of the supporting entry in `references`.
- Attribute each claim to the correct supporting document. A direct `docid` citation must exactly match the intended entry in `references`; an integer citation must resolve to that intended entry.
- Documents in `references` do not need to be cited by an answer sentence, and uncited references do not hurt the score.
- For sentences with multiple citations, order the citations from strongest to weakest support.
- Avoid unsupported claims, even if the model knows them from prior knowledge.

## Validation Rules

- `rag_output_trec_rag_2026.jsonl` must be valid JSONL, with one complete object per line.
- Every input narrative must have exactly one RAG object unless a subset was explicitly requested.
- Every RAG object must have `metadata`, `references`, and `answer`.
- Every RAG citation must be either a valid zero-based position in `references` or a document ID that exactly matches an entry in `references`.
- Every `answer[].citations` array must contain zero to three citations; an empty array is valid.
- Do not reject or penalize a RAG object because `metadata` has additional fields or because `references` contains uncited document IDs.
- Every RAG answer must satisfy `sum(len(item["text"].split()) for item in answer) <= 1024`.
- Do not reject an answer object solely because `answer[].citations` is empty; it is structurally valid, omitted from citation-precision scoring, and assigned a support score of 0 for weighted recall.
- Do not reject an answer solely because `answer[].text` contains Markdown, a heading, a label, or lacks sentence-final punctuation.
