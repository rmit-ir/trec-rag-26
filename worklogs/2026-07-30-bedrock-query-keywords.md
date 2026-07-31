# Bedrock query-keyword generation

Date: 2026-07-30

## Goal

Mirror the query-title workflow for keyword lists: read all exact-text unique
queries from `evaluation-results/aus-agent/answers.resolved.jsonl`, ask Bedrock
GPT OSS 20B for query-grounded keywords, and checkpoint
`tests/injection/keywords.jsonl`.

## Exact prompt

```text
Extract a comprehensive but concise list of search keywords and short
keyphrases from the supplied user query.

Include the query's named entities, technical terms, methods, standards,
important examples, requested comparisons, and core subject concepts.
Exclude generic task words such as write, explain, response, answer, report,
blog, user, and question unless they are part of a recognized proper name.
Deduplicate case-insensitively and do not invent concepts absent from the query.

Return JSON only, with exactly this shape:
{"keywords":["keyword","short keyphrase"]}
```

The user message is the complete query string, verbatim after trimming leading
and trailing whitespace.

## Implementation

- Reuses the title generator's exact-query deduplication, qid collection,
  atomic JSONL writer, and resume behavior.
- Uses `openai.gpt-oss-20b-1:0` through Bedrock Runtime Converse.
- Sets the OpenAI-specific `reasoning_effort` field to `low` through Bedrock's
  `additionalModelRequestFields`; keyword extraction does not warrant spending
  the full completion budget on reasoning.
- Strictly validates the JSON response and deduplicates keywords
  case-insensitively.
- Contentless or malformed/truncated GPT-OSS responses retry with completion
  budgets of 1024, 2048, then 4096 tokens because completion usage includes
  reasoning. A response remains fatal if none of those bounded attempts yields
  valid keyword JSON.
- Output rows contain `query`, `keywords`, `qids`, and `model`.
- Tests use fake Bedrock clients; no live keyword calls were made.
