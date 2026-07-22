# 2026-07-22 — append text to RAGDOLL answer sentences

Added `scripts/append-ragdoll-answer-text.py`, a JSONL transformation utility
that appends an exact caller-provided suffix to every `answer[].text` string.
It preserves citations and all other row fields, validates the expected answer
shape, refuses to overwrite its input, and reports the row and sentence counts.

Verification covered Python compilation, CLI help, and a transformation of the
first row of the existing `evaluation-results/aus-agent/answers.resolved.jsonl`
artifact into a temporary output file.
