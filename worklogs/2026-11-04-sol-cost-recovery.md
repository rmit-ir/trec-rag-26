# Recovering the two Sol runs' token costs on Sunfyre

Used the DevSpace Sunfyre plugin to inspect the project checkout, shared data,
and Kun's project. No external model/API calls, billing queries, or generation
runs were made. No raw trace assets were downloaded or modified.

## Sources and selection

- Project: `/home/el7/E103037/repos/trec-rag-26`.
- Shared directory: `/research/remote/petabyte/users/oleg/trec_rag_26_data`;
  the project's `data/outputs` points at its `outputs`. Its `aus_agent_v2`
  directory held 15 development outputs, rather than the production run.
- Kun's checkout: `/scratch/fast/kun/projects/trec-rag-26`.
- Rich outputs: Kun's `data/outputs/{aus_agent,aus_agent_v2}/20260807*.output.json`.
- Production logs: Kun's `tasks/task-comparison/logs/<run_id>.log`.
- Archived log copies: this project's
  `worklogs/assets/2026-08-07-sol-aus-default-test119.log` and
  `worklogs/assets/2026-08-07-sol-aus-v2-research-first-test119.log`.
- Organizer exports: Kun's `data/outputs/submissions/<run_id>/rag_output_trec_rag_2026.jsonl`.

Selected exact `metadata.run_id` values and required completed answers and
references to match the exported submission for each narrative. There were
119 unique matching topics per run, `rag2026-0` through `rag2026-118`.
Preflight runs have different run IDs and were excluded. August 10 files were
excluded rather than accidentally counting later ensemble traces mentioning the
original run IDs. Two failed default attempts were counted separately.

## Result matrix

| Field | sol-default | sol-research-first |
| --- | ---: | ---: |
| Exact run ID | sol-aus-default-test119-20260807 | sol-aus-v2-research-first-test119-20260807 |
| Submitted successful topics | 119 | 119 |
| Successful uncached input tokens | 21,683,003 | 39,333,645 |
| Successful output tokens | 725,051 | 1,246,976 |
| Successful cached input tokens | 24,080,679 | 43,950,115 |
| Successful processed tokens (uncached input + output) | 22,408,054 | 40,580,621 |
| Mean successful processed tokens/topic | 188,302.974790 | 341,013.621849 |
| Failed attempts | 2 | 0 |
| Failed-attempt processed tokens | 179,386 | 0 |
| Production processed tokens including failed attempts | 22,587,440 | 40,580,621 |
| Mean processed tokens/topic including failed attempts | 189,810.420168 | 341,013.621849 |
| Estimated USD/topic, successful attempts only | 0.941515 | 1.705068 |
| Estimated USD/topic, including failed attempts | 0.949052 | 1.705068 |
| Successful priced calls | 0 | 0 |
| Successful unpriced calls | 1,084 | 1,420 |

Default's failed attempts were `rag2026-55` (110,711 processed tokens) and
`rag2026-112` (68,675). Both have successful replacements included in the 119
submitted outputs. Their failed requests' unreturned usage cannot be recovered;
the failed-attempt totals cover recorded successful calls before those failures.

## Calculation and validation

Reused the report's hypothetical uniform rate of USD 5 per million processed
tokens. Estimate = `processed_tokens * 5 / 1_000_000 / 119`. The documentation
uses retry-inclusive default cost, $0.949/topic, and research-first cost,
$1.705/topic. Research-first is 79.66% more expensive under this assumption.

All 238 per-topic processed-token totals match both Kun's production log and the
archived log. Each equals trace uncached input plus output. Export hashes match
the original production worklog:

- default: `d6fcf2c14bb48dfc3f7476032ecf79c6d2704664434266efabe383dcace10fc5`;
- research-first: `744c2d0624a1b834b94ad87fbc50548b1957f22a09beb1903230da72fe4986d8`.

Exact read-only probe: [assets/2026-11-04-sol-cost-recovery.py](assets/2026-11-04-sol-cost-recovery.py).
It ran on Sunfyre as `uv run --offline --no-project python -c '<probe contents>'`.
Its assertions check topic completeness, duplicate selection, submission identity,
log-copy equality, and token accounting. The full per-topic result matrix,
failed-attempt details, source paths and SHA-256 values are preserved in
[assets/2026-11-04-sol-cost-recovery.json](assets/2026-11-04-sol-cost-recovery.json).

The costs are estimates, not observed billing: the trace `cost.usd=0` means
unpriced, not free. This placeholder omits cached-input charges and distinct
input/output rates. It excludes preflight, development, judging, retrieval
infrastructure, and unreturned usage from failed API requests. No current price
card was substituted for the historical placeholder. Only documentation and
analysis evidence changed; no application code changed.

## Documentation completion

Added average processed tokens per topic for all seven systems beside their
costs in `RMIT-ADM+S scores/SCORES.md`, and linked usage/cost information from
the score README. The other five token averages were copied from the report's
`tables/submissions.tex`: brief-hybrid 300,621; brief-base 327,585; facets
144,847; OWA 420,979; facetrag 461,381. Sol-default's rounded 189,810 includes
recorded failed-attempt usage, matching its retry-inclusive cost; research-first
rounds to 341,014. The token definition excludes cached reads and includes cache
writes (zero for the two Sol runs).

Validation before commit:

- All seven documented token averages and costs match their sources. A local
  Decimal-based check recomputed the two Sol costs and token averages from the
  saved matrix, checked all 238 topic totals against archived logs, and checked
  the five remaining rows against the report's LaTeX table.
- Recovery probe syntax compiles; its assertions passed on Sunfyre during
  recovery. Saved totals equal their per-topic sums.
- `git diff --check` passes.
- `UV_CACHE_DIR=/tmp/trec-rag-uv-cache bash scripts/test.sh`: 1,970 passed,
  12 live tests deselected, no skips; one existing Starlette deprecation warning.
