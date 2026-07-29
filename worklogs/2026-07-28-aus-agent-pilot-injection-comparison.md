# aus-agent-pilot injection support comparison

## Goal

Create a directly runnable notebook that compares citation-support judgments
for the aus-agent-pilot baseline and all four injection variants.

## Exact inputs

- `evaluation-results/aus-agent-pilot/support-bedrock-20/judgments.jsonl`
- `evaluation-results/aus-agent-pilot/support-bedrock-20_inject/judgments.jsonl`
- `evaluation-results/aus-agent-pilot/support-bedrock-20_inject_rus/judgments.jsonl`
- `evaluation-results/aus-agent-pilot/support-bedrock-20_inject_thai/judgments.jsonl`
- `evaluation-results/aus-agent-pilot/support-bedrock-20_inject_vi/judgments.jsonl`

## Result

Added
`evaluation-results/aus-agent-pilot/ragdoll_injection_support_comparison.ipynb`.
The user explicitly requested the notebook under the pilot results folder,
overriding the repository's default `tmp/` location for exploratory notebooks.

The notebook reports:

- health and coverage for each run;
- overall FS/PS/NS composition and weighted support;
- explicit matched/unmatched citation counts;
- paired score changes from baseline;
- verdict-transition matrices;
- per-topic deltas; and
- configurable inspection of statements whose support verdict changed.

Because injected text can shift sentence indices, paired comparisons use
`(run_id, qid, docid, occurrence)`, where occurrence is the ordered use of a
document within a run/topic. Unmatched rows remain visible in the alignment
report.

## Verification

The notebook was executed headlessly using the root `notebook` dependency
group, and all code cells completed without error.
