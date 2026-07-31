# Inject titles and keywords into resolved RAG responses

Date: 2026-07-30

Added `tests/injection/inject_titles_keywords.py`.

The script joins resolved answers, generated titles, and generated keyword
lists by exact query text. Each `answer_text` becomes:

```text
Title: <generated title>
Keywords: <keyword 1>, <keyword 2>, ...

<original answer_text>
```

It preserves the rest of each resolved row, recomputes `response_length`, and
adds a structured `injection` record containing the inserted title and
keywords. The script also replaces `answer` with a one-sentence representation
of the injected `answer_text`; this is required because RAGDOLL's rubric grader
prefers `answer` when both fields are present. It fails on missing or
conflicting joins and writes the output atomically to
`tests/injection/answers.injected.jsonl` by default.

Validation:

```text
python -m unittest tests.injection.test_inject_titles_keywords -v
Ran 3 tests in 0.024s
OK

python tests/injection/inject_titles_keywords.py
wrote 248 injected RAG responses to tests/injection/answers.injected.jsonl
```
