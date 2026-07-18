# Evaluation results

This directory contains reviewable evaluation artifacts owned by the parent
repository. RAGDoll itself is a Git submodule whose `results/` directory is
ignored, so completed runs are published here instead.

Raw judge events, caches, logs, and credentials are deliberately excluded.
Each published run contains its grading inputs, parsed judgments, score tables,
and a manifest recording its source directory.

Publish a completed run from the repository root:

```bash
python scripts/publish-ragdoll-results.py \
  evaluation/ragdoll/results/aus-agent/evaluation-bedrock
```
