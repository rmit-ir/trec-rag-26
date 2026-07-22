# 2026-07-22 — extract RAGDOLL queries

Added `scripts/extract-ragdoll-queries.py` and used it to extract `query.qid`
and `query.text` from every row of
`evaluation-results/aus-agent/query_and_docs.jsonl` (the current name of the
relevance input). The resulting JSONL artifact is
`evaluation-results/aus-agent/queries_extracted.jsonl`.

Validation checks the source schema and confirms the extracted file has the
same number of non-empty rows as the source.
