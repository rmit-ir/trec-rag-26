# facet_rag §3.1 verification: --max-chars 2000→20000

2026-08-05, same session as `2026-08-05-facet-rag-honest-rebaseline.md`.
PLAN.md §3.1 predicted raising `--max-chars` toward aus_agent's ~20,480-char
stage depth was "the biggest effect, one-line change" fix for the
content-starvation problem (A1/A2). Changed the default in `run.py`
(commit `50f8f5d`), re-ran the same 5 aus_agent-comparison topics, and judged
them the same way as the `opus_plan_5topic` baseline. Result: the prediction
did not land — read below before spending more Bedrock budget on this lever
alone.

## Run

```sh
for q in 6847465956a0f6376a605404 6847465956a0f6376a60542a 683a58c9a7e7fe4e76958498 \
         684397d188c1deceb49af32d 6847465956a0f6376a60547e; do
  uv run --group facet-rag python src/systems/facet_rag/run.py --qid "$q" \
    --run-id facet_rag.maxchars20k_5topic \
    --run-desc "PLAN.md §3.1 verification: --max-chars 2000->20000, same 5 aus_agent-comparison topics"
done
```

All 5 `status=completed`. `--max-chars` was the CLI default (20000, unset
explicitly) — the flag itself was not passed, confirming the new default is
what's exercised by a plain `run.py` invocation.

## Resolve — API was flaky this session

`scripts/resolve-rag-output-references.py` (same `--doc-url` /
`--trajectory-dir /tmp/no-trajectories-2` invocation as the baseline) hit
`HTTP 429 Service temporarily overloaded` from the Pyserini doc API on the
first 7 attempts, at `--workers` 16, 4, 2, and 1 — not a concurrency problem
on our side (a standalone `curl` to the same endpoint succeeded twice
mid-failure). Succeeded on the 8th attempt (30s backoff between attempts, no
code change — the script has no built-in retry, that's a real gap in
`scripts/resolve-rag-output-references.py` worth fixing if this recurs, but
out of scope here). Once resolved: `n=68, median=4194, mean=13538.3, pinned
at 2000: 0` — same full-doc resolve as the baseline, as expected (the resolve
script always fetches the *full* document regardless of `--max-chars`;
`--max-chars` only bounds what `facet_rag` itself saw during synthesis, not
what the judge scores).

## UMBRELA

```sh
python3 scripts/ragdoll-answers-to-umbrela.py \
    evaluation-results/facet_rag/maxchars20k_5topic/answers.resolved.jsonl \
    --output evaluation-results/facet_rag/maxchars20k_5topic/umbrela.input.jsonl
cd evaluation/ragdoll && uv run ragdoll umbrela judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file ../../evaluation-results/facet_rag/maxchars20k_5topic/umbrela.input.jsonl \
    --output-file ../../evaluation-results/facet_rag/maxchars20k_5topic/umbrela-bedrock-120/judgments.jsonl
# processed=68
```

## Support judge

```sh
cd evaluation/ragdoll && uv run ragdoll support judge \
    --provider amazon-bedrock --model openai.gpt-oss-120b-1:0 \
    --input-file  ../../evaluation-results/facet_rag/maxchars20k_5topic/answers.resolved.jsonl \
    --output-file ../../evaluation-results/facet_rag/maxchars20k_5topic/support-bedrock-120/judgments.jsonl \
    --raw-events-dir ../../evaluation-results/facet_rag/maxchars20k_5topic/support-bedrock-120/raw-events
# processed=161

python3 scripts/ragdoll-support-to-csv.py \
    evaluation-results/facet_rag/maxchars20k_5topic/support-bedrock-120/judgments.jsonl \
    --output evaluation-results/facet_rag/maxchars20k_5topic/support-bedrock-120/judgments.csv \
    --summary-output evaluation-results/facet_rag/maxchars20k_5topic/support-bedrock-120/judgments.summary.csv
```

Aggregate: `total=161, full_support=67, partial_support=66, no_support=25,
judge_errors=3, full_support_rate=0.416149, partial_or_full_rate=0.826087`
vs baseline (`opus_plan_5topic`, 2000-char): `total=149, full_support=66,
partial_support=57, no_support=18, judge_errors=8, full_support_rate=0.442953,
partial_or_full_rate=0.825503`.

## Full result matrix

Answer shape, from each run's `*.output.json`:

```
topic       words(2k)  words(20k)  cited%(2k)  cited%(20k)  refs(2k)  refs(20k)
CSGO           365         317         100%         94%        14        11
SCALING        460         591         100%         94%        15        15
RETIRE         734         437         100%        100%        12        12
PRESCHOOL      437         613          94%        100%        14        15
SWARM          363         346          90%        100%        15        15
mean           471.8       460.8
```

UMBRELA mean judgment (0-3), n = judged citations per topic:

```
topic       n(2k)  mean(2k)  n(20k)  mean(20k)
CSGO          14     1.643      11     1.636
SCALING       15     1.067      15     1.133
RETIRE        12     1.417      12     1.500
PRESCHOOL     14     0.857      15     0.800
SWARM         15     1.200      15     0.800
```

Support `partial_or_full` per topic:

```
topic       n(2k)  p_o_f(2k)  n(20k)  p_o_f(20k)
CSGO          21      0.857      17      0.941
SCALING       39      0.744      45      0.689
RETIRE        41      0.829      37      0.919
PRESCHOOL     30      0.867      46      0.826
SWARM         18      0.889      16      0.875
```

## Verdict

No consistent improvement on any of the three tracked signals (words,
UMBRELA, support). SWARM's UMBRELA dropped the most (1.200→0.800, -0.40).
Single trial each side — within the noise band §1.2 warned about — so this is
a direction check, not proof the lever is worthless. But it clearly is not
the "biggest effect, one-line fix" the plan predicted on its own.

Reading §3.1's own three-cause list again: cause 1 (the `facets ×
DEFAULT_TOP_N` reference cap, still 3 per facet) and cause 3 (the formatter's
no-length-floor rewrite) are both untouched. The reference count barely moved
(11-15 vs 12-15) — the analyzer/curator pipeline is still discarding most of
the extra text `--max-chars` now makes available, and the formatter is still
free to compress whatever survives. `--max-chars` was necessary (it fixes the
UMBRELA measurement confound in §1.1 regardless) but not sufficient on its
own for A1/A2. Next step per the plan's own logic: `DEFAULT_TOP_N` (curator.py:40)
and the `FORMAT_ANSWER_PROMPT` length floor, not more tuning of `--max-chars`.

## Artifacts

- `data/outputs/facet_rag/20260805T13{14,17,19,23,27}*.{output,trajectory}.json`
  (gitignored, local only)
- `evaluation-results/facet_rag/maxchars20k_5topic/answers.resolved.jsonl`
- `evaluation-results/facet_rag/maxchars20k_5topic/umbrela-bedrock-120/judgments.jsonl`
- `evaluation-results/facet_rag/maxchars20k_5topic/support-bedrock-120/judgments.{jsonl,summary.csv}`
