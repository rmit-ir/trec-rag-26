# Unperturbed Arena results notebook

Date: 2026-08-04

Created `tmp/view_arena_unperturbed.ipynb` from these raw inputs:

- `evaluation-results/aus-agent/arena-unperturbed/leaderboard.csv`
- `evaluation-results/aus-agent/arena-unperturbed/pairwise.csv`
- `evaluation-results/aus-agent/arena-unperturbed/coverage.csv`
- `evaluation-results/aus-agent/arena-unperturbed/judgments.jsonl`

The run contains 233 completed pairwise battles across 21 unperturbed systems.
The notebook reports the leaderboard with descriptive preference rates,
undefeated-system warnings, comparison-graph components and degrees, pairwise
preference and topic-coverage heatmaps, verdict-position balance, latency,
tokens, and cost.

The large top Bradley-Terry score is explicitly contextualized: undefeated
systems and sparse/uneven overlap can produce separation and unstable absolute
ratings, so the notebook shows raw wins and evidence counts alongside ratings.
