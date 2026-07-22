# 2026-07-22 — append text to RAGDOLL relevance candidates

Extended the locally renamed `scripts/inject_ragdoll_malicious.py` utility to
accept both RAGDOLL support-answer rows and UMBRELA relevance rows. Schema is
detected per row: support input appends the requested suffix to every
`answer[].text`, while relevance input appends it to every
`candidates[].doc.segment`. Query text, document IDs, citations, metadata, and
all other fields remain unchanged.

Verification compiled the script and transformed the complete
`evaluation-results/aus-agent/relevance.jsonl` file into a temporary artifact.
Every candidate segment received the test suffix.
