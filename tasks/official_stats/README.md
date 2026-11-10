# official_stats

Statistical analysis of the official TREC RAG 2026 scores (`RMIT-ADM+S scores/`). Plan, decisions and results:
`worklogs/2026-11-10-statistical-analysis-plan.md` (section 10 is final). Outputs: `worklogs/assets/2026-11-11-official-stats/`.

- `statistical_analysis.py` — Tukey HSD all-pairs (primary), sensitivity methods, planned contrasts, SxS Bradley-Terry tests, coverage-vs-preference. `--paper-dir` also writes paper tables/figures.
- `length_analysis.py` — answer length vs coverage and preference; Tukey HSD on length.
- `readability_vs_preference.py` — B1 readability vs preference (reads `worklogs/assets/2026-11-08-batch1-readability.json`).

Run with `uv run --project tasks/official_stats python tasks/official_stats/<script>.py`.
