# RAGDoll graded-results dashboard

## Goal

Create a directly runnable notebook beside the aus-agent-pilot judged results
to visualize `graded.jsonl` and RAGDoll's generated score tables.

## Result

Added:

`evaluation-results/aus-agent-pilot/rubric/judged/graded_results_dashboard.ipynb`

The notebook:

- resolves the judged directory when launched either from its own folder or
  from the repository root;
- summarizes graded cells, runs, topics, criteria, and failures;
- compares run-level ternary and binary scores;
- renders a run-by-topic score heatmap;
- charts criterion verdict distributions;
- compares satisfaction rates across Research Rubric axes;
- displays category failure rates; and
- provides an editable qid/run drill-down with scores, criteria, query, and
  full answer text.

## Validation

The notebook parsed successfully as nbformat 4 JSON with 13 cells: 7 code and
6 Markdown. An initial diagnostic exposed an incompatibility with pandas 3:
`Styler.applymap` no longer exists. The drill-down table now uses `Styler.map`.
After that correction, all cells executed successfully through `nbconvert`
with a 30-second per-cell timeout.
