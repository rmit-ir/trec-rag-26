# Inert passage perturbation formatter

Date: 2026-07-30

Added `scripts/build-inert-passage-perturbations.py`, a small JSONL formatter
for controlled, non-instruction evaluation perturbations.

For every `segments` entry in a resolved RAG answer row, it emits:

```text
Title: <query>

<passage>. [CONTROL: <marker>]
```

The caller supplies `--marker`, restricted to a 1–64 character identifier
containing letters, digits, underscore, dot, or hyphen. Free-form instructions
are intentionally unsupported. Output rows retain `qid`, `docid`, `query`, and
the marker alongside the formatted `text`.
