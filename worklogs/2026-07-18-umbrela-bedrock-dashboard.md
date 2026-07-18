# UMBRELA Bedrock dashboard notebook

## Goal

Create an exploratory notebook for visualizing the UMBRELA relevance judgments
at `evaluation-results/aus-agent/umbrela-bedrock/judgments.jsonl`.

## Result

Added `evaluation-results/ragdoll_umbrela_dashboard.ipynb` beside the existing
RAGDoll support dashboard, as explicitly requested, and configured it to use
the root `notebook` dependency group.

The notebook:

- tolerantly reads an in-progress JSONL file;
- reports completion, failures, malformed lines, invalid scores, and duplicate
  task IDs;
- plots the overall 0–3 judgment distribution and composition by run split;
- summarizes relevance per query;
- provides configurable passage inspection; and
- exposes failed rows and completed predictions with suspicious output formats.

## Input

The raw input is the complete JSONL artifact at
`evaluation-results/aus-agent/umbrela-bedrock/judgments.jsonl`. The notebook
loads that artifact directly rather than embedding a session-local sample.

## Verification

Validated the notebook as JSON and executed it headlessly with the root
`notebook` dependency group.
