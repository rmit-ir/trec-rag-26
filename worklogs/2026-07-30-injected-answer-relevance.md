# Injected-answer relevance evaluation

Date: 2026-07-30

## Goal

Evaluate `tests/injection/answers.injected.jsonl` with RAGDOLL's UMBRELA
query-passage relevance judge.

## Input interpretation

The repository's general `scripts/ragdoll-answers-to-umbrela.py` converts each
answer's cited source documents into candidates. That would not evaluate the
modified `answer_text`, so this experiment uses a dedicated adapter:

- UMBRELA query: the row's original `query`.
- UMBRELA candidate passage: the complete injected `answer_text`, including
  its generated title and keyword prefix.
- Candidate docid: `injected-answer`.
- Task identity: `<run_id>::<qid>`.

The adapter is `tests/injection/prepare_relevance_requests.py` and writes
`tests/injection/ragdoll-relevance/requests.jsonl`.
