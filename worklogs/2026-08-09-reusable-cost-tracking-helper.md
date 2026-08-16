# Reusable cost tracking helper

Extracted translation cost calculation and persistent run logging from
`translate_queries.py` into
`tasks/llm_judge_robustness/scripts/cost_tracking.py`.

The public `estimate_cost_usd(billable_units, usd_per_million_units)` helper is
service-agnostic and returns an exact `Decimal`, leaving rounding and
serialization to its caller. It rejects negative quantities and rates.
`CostRunLogger` and `DEFAULT_USD_PER_MILLION_CHARACTERS` now live beside that
function, while preserving the existing `_runs.jsonl` and `_cost-total.json`
schemas and cumulative behavior.

Both `translate_queries.py` and `translate_distractors.py` now import the shared
helper rather than defining or re-exporting cost logic through the query script.

Validation:

- all three modules passed `py_compile`;
- 1,000,000 units at $15/million returned exactly `$15`;
- 3,110,701 units at $15/million returned exactly `$46.660515`;
- the related-topic/Arabic/2021 no-cost translation planning smoke test remained
  unchanged at 102 requests and 19,889 characters.
