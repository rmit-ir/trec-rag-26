# aus-agent-pilot rubric-input preview notebook

## Goal

Provide a directly runnable notebook beside the aus-agent-pilot evaluation
artifacts for inspecting the UMBRELA-filtered evidence pool used by RAGDoll
Nuggetizer and rubric creation.

## Result

Added
`evaluation-results/aus-agent-pilot/ragdoll_rubric_input_preview.ipynb`.
The user explicitly requested this location, overriding the repository's normal
convention of placing exploratory notebooks under `tmp/`.

The notebook loads
`evaluation-results/aus-agent-pilot/rubric/create_input.jsonl` and provides:

- topic and candidate coverage;
- retained UMBRELA grade counts;
- candidates-per-topic plots;
- a configurable topic/passages browser;
- full-passage inspection; and
- the adapter regeneration command.

## Verification

The notebook was executed headlessly with the repository root `notebook`
dependency group.
