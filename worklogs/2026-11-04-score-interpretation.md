# Score interpretation and report context

Updated `RMIT-ADM+S scores/SCORES.md` following the score analysis in chat and
review of the sibling `trec-rag-26-report` repository. Linked the summary from
the supplied score README. No raw scores or scoring code changed.

The summary now defines coverage fractions and percentages, separates human
preference from LLM-assigned coverage, explains the assessed-field W/T/L counts,
and presents the all-strict percentages alongside conclusions. It connects the
official results to the report's retrieval, orchestration, search-volume, and
cost observations while distinguishing internal experiments from official scores.

Report sources: `sections/system-overview.tex`, `sections/retrieval.tex`,
`sections/results.tex`, `sections/submitted-runs.tex`, and
`tables/submissions.tex`. The report predates the released scores. In particular,
OWA's B1 human preference lead qualifies broad open-weight inferiority claims;
the Qwen fixed-evidence replay does not establish the cause of GLM-5's coverage
gap. No significance or citation-quality claim follows from coverage alone.

Validation: all 21 displayed coverage percentages and six reported coverage
differences match the source TSVs in a Decimal-based check; `git diff --check`
passes. `UV_CACHE_DIR=/tmp/trec-rag-uv-cache bash scripts/test.sh` passed all
1,970 offline tests (12 live tests deselected; one existing deprecation warning)
outside the sandbox. The first attempt passed 1,944 tests but could not bind
loopback ports for 26 dummy API tests.
No new judgments, generation runs, or experiments were run.
