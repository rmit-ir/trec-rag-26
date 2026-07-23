# 2026-07-22 — aus-agent-pilot support dashboard

Copied `evaluation-results/ragdoll_support_dashboard.ipynb` to
`evaluation-results/ragdoll_support_dashboard_aus_agent_pilot.ipynb` and
retargeted it to read
`evaluation-results/aus-agent-pilot/support-bedrock-20/judgments.jsonl`
directly. The loader normalizes judgment metadata and derives the detailed and
run-summary tables in memory, so no intermediate CSV files are required.

The copied notebook was executed headlessly with the repository-root notebook
dependency group so its stored tables and plots reflect the pilot judgments.
Execution loaded 102 judgments across two runs and four topics; all 12 cells
completed with no stored errors.
