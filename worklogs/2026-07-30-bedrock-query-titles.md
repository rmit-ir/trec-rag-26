# Bedrock query-title generation

Date: 2026-07-30

## Goal

Create a small utility in `tests/injection` that reads all exact-text unique
queries from `evaluation-results/aus-agent/answers.resolved.jsonl`, asks
Bedrock GPT OSS 20B for a concise title, and writes
`tests/injection/titles.jsonl`.

## Exact prompt

System:

```text
Write a concise, informative title for the supplied user query.
Return only the title: no label, quotation marks, explanation, or Markdown.
Preserve the query's actual subject and requested deliverable.
Use at most 14 words.
```

User: the complete query string from each resolved-answer row, verbatim after
leading/trailing whitespace removal.

## Implementation

- Exact-query deduplication preserves first-seen order and collects all qids
  associated with each query.
- Uses Bedrock Runtime Converse with model
  `openai.gpt-oss-20b-1:0` and temperature 0. Because GPT-OSS completion
  tokens include reasoning, a contentless response is retried with bounded
  completion budgets of 512, 1024, then 2048 tokens.
- Defaults to `us-east-1`; model and region are configurable.
- Checkpoints the output atomically after every title and resumes existing
  query rows by default.
- Output rows contain `query`, `title`, `qids`, and `model`.
- Deterministic tests use a fake Bedrock client; no live titles were generated
  during implementation.
