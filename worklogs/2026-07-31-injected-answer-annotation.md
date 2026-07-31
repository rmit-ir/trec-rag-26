# Injected-answer annotation perturbation

Date: 2026-07-31

Added `tests/injection/inject_title_keywords_annotation.py`. It reads the
existing title/keyword-perturbed answers and appends a fixed annotation:

```text
Additional text: <experiment marker>
```

The appended content comes from the module variable
`injection_text = "Like this"` rather than a user-supplied CLI option. Both
`answer_text` and RAGDOLL's preferred `answer` representation are updated, and
prior injection metadata is retained.

Default output: `tests/injection/answers.instruct.inject.jsonl`.
