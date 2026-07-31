# Judge temperature sweep — does the prompt recommendation change with temperature?

**2026-07-31.** Task: `tasks/bm25_tune/`. Branch `feat/bm25-tune`.

## Question

The bm25_tune judge (`gpt-oss-20b` on Bedrock) runs at a deliberately non-default
`temperature=0.0` (PLAN §5.4, for reproducible qrels). The user asked: run the
WP6 calibration at temperatures **0.0, 0.5, 0.7, 0.9, 1.0** and see whether the
gate's recommended prompt variant changes.

## Method

- Added a `--temperature` flag to `calibrate` (default `0.0`, so production and
  the whole test suite are unchanged), threaded into both the per-variant judge
  and the stability probe's `BedrockJudge`.
- **Ran each temperature in its own throwaway `BM25_TUNE_DATA_DIR`**
  (`/tmp/bm25-temp-sweep/t<T>/`), seeded with byte-identical copies of the
  read-only `inputs/` + `queries/`. This is mandatory: the cache/log key is
  `prompt_version::topic_id::chunk_id` with **no temperature component**, so
  grades from two temperatures are indistinguishable on disk — running temp>0 in
  the real `data/bm25-tune/` would silently corrupt the canonical qrels. The real
  data dir was never touched. Verified the 280-pair sample (`sha256`) is
  identical across all five runs.
- Each run: 5 variants × 280 pairs + 50-pair stability probe on the winner.
- Exact per-run command (T substituted):
  ```
  BM25_TUNE_DATA_DIR=/tmp/bm25-temp-sweep/t<T> BM25_TUNE_BUDGET_USD=50.0 \
    AWS_REGION=ap-southeast-2 \
    uv run --project tasks/bm25_tune python -m bm25tune calibrate --temperature <T>
  ```
- Runner script: `worklogs/assets/2026-07-31-judge-temperature-sweep/` (reports
  copied there; `/tmp` is ephemeral). Full result matrix: `.../MATRIX.txt`.

## Cost

**$1.0098 total** — five runs at ~$0.20 each (1400 calib + ~50 probe calls per
run, `basis=measured`). All five exited 0, none tripped the $50 cap.

## Result — the recommendation does NOT change

**`facet-name-v1` is the gate winner at every temperature 0.0 → 1.0.** It is the
only variant that passes all four gate conditions at *all five* temperatures.

| T | winner | passing (gate PASS) |
|---|---|---|
| 0.0 | **facet-name-v1** | facet-name-v1 |
| 0.5 | **facet-name-v1** | facet-name-v1, facet-rare3-v1 |
| 0.7 | **facet-name-v1** | facet-name-v1, facet-rare3-v1 |
| 0.9 | **facet-name-v1** | facet-name-v1, facet-v1, umbrela-v1 |
| 1.0 | **facet-name-v1** | facet-name-v1, umbrela-v1 |

The *runner-up* set is unstable across temperature (facet-rare3-v1, facet-v1,
umbrela-v1 flip PASS/FAIL as their modal share jitters across the 0.60 line),
but the winner never does. facet-name-v1's grade distribution stays balanced
across all four grades at every temperature (dist `{0,1,2,3}` ≈ `{37,8,127,105}`,
modal share 0.42–0.49, share≥2 ≈ 0.83–0.86, always comfortably inside the gate
band).

## The more important finding — gpt-oss-20b is NOT deterministic at temp 0

The single most decision-relevant number here is the **stability probe on the
winner**, which re-judges 50 pairs cache-bypassing and reports the exact-match
rate:

| T | facet-name-v1 stability match rate |
|---|---|
| **0.0** | **0.840** |
| 0.5 | 0.660 |
| 0.7 | 0.760 |
| 0.9 | 0.640 |
| 1.0 | 0.660 |

Two things follow:

1. **Even at temperature 0, the judge only reproduces its own grade 84% of the
   time.** gpt-oss-20b is an MoE model and Bedrock batches requests
   non-deterministically, so "temperature 0" is not "deterministic" here. This
   is corroborated by the winner-passing set: at T=0.0 in *this* sweep only
   facet-name-v1 passed, whereas the earlier real calibration (also T=0.0, same
   seed/sample) had *both* facet-name-v1 and facet-v1 passing — i.e. two runs at
   identical settings gave different gate outcomes for the borderline variants.
2. **Raising temperature makes reproducibility strictly worse** (0.84 → ~0.65)
   without changing the winner. There is no upside to a higher temperature for a
   grading task, and a measurable downside.

## Recommendation

- **Keep `temperature=0.0`.** It is the most reproducible setting available
  (highest stability match rate) and yields the same winner as every other
  temperature. Raising it only degrades reproducibility.
- **Keep `facet-name-v1` as the judge prompt** — robust across the full
  temperature range and the only always-passing variant.
- **Caveat to carry into WP7:** the ~84% temp-0 stability means the winner's
  grades are noisy at the pair level. The gate is a coarse floor (it survives
  this noise — the winner passes every time), but the *runner-up* rankings are
  within-noise and should not be over-read. The stability caveat already in
  `calibration.py`'s report preamble understates this: the probe was designed
  assuming ≥90% at temp 0, and we observe 0.84. Worth noting in the WP7 sweep
  writeup that a single (k1,b) cell's nDCG carries judge noise of this order.

## Code left in place

`--temperature` flag on `calibrate` (default 0.0), `CALIBRATION_JUDGE_TEMPERATURE`
constant, a `[CALIB]` warning when temperature ≠ 0.0. All offline tests still
green (523 in the bm25_tune subset; default unchanged). No change to the real
`data/bm25-tune/` qrels.
