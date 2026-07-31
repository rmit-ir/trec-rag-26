# WP0/WP6 judge calibration — `calibrate`

- calibration sample: `/tmp/bm25-temp-sweep/t1.0/calibration/sample-280.jsonl` (280 pairs, identical across every variant)
- judge model: `openai.gpt-oss-20b-1:0` in `ap-southeast-2`
- variants scored: `umbrela-v1`, `umbrela-kw-v1`, `facet-v1`, `facet-name-v1`, `facet-rare3-v1`
- sample label mix: negative 153 (54.6%), positive 119 (42.5%), unjudged 8 (2.9%)
- pool label mix: negative 6638 (72.1%), positive 2368 (25.7%), unjudged 202 (2.2%)

> **The gate is a floor on usability, not the selection criterion.** Passing it
> makes a variant *eligible* to judge the sweep; it does not make it the winner.
> Among passing variants PLAN §3.3 picks the lowest modal share, tie-broken by
> AUC, and **the user confirms the choice before WP7 launches.**
>
> **Agent-label agreement is a smell test, not accuracy.** `committed` vs `not
> selected` is a *staging* decision made under a context budget, not a relevance
> judgment: **[measured]** 93.9 % of rejected keyword hits come from a query that
> committed something else, 76.9 % were outranked by a committed chunk from that
> same query, and on a hand-read sample **53 % of rejected passages were still
> grade >=2** (PLAN §3.3b Finding 1). So a judge scoring well above the agent's
> 23.8 % positive rate is **expected, not a red flag**. Only *anti*-correlation
> (AUC < 0.5) is suspicious; mere overlap is not disqualifying.
>
> **The band applies to the sample, which is deliberately not the pool.** §3.1
> enriches agent-positives ~1.8x so the smell test has both classes per topic, so
> every `share>=2` below is *higher* than the same judge would produce on the
> pool. The pool-reweighted column is the comparable quantity; never quote the
> two as though they were the same.


## Verdict

**PASS — recommended judge: `facet-name-v1`.**

`facet-name-v1` has the lowest modal share (0.489) among the 2 gate-passing variants (also passing: `umbrela-v1`). The gate is a floor on usability, not the selection criterion — the user confirms this choice before WP7 launches.

## Gate conditions

The four bounds, all inclusive (PLAN §3.3):

1. modal grade share <= 0.60
2. all four grades used (each >= 1 pair)
3. 0.20 <= share at grade >=2 <= 0.90
4. share at grade 3 <= 0.50

| variant | n | 0 | 1 | 2 | 3 | modal | H (bits) | share>=2 | pool-rwt >=2 | share=3 | verdict | missed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 55 | 164 | 55 | 6 | 1@0.586 | 1.493 | 0.218 | 0.189 | 0.021 | **PASS** | — |
| `umbrela-kw-v1` | 280 | 92 | 134 | 30 | 24 | 1@0.479 | 1.685 | 0.193 | 0.183 | 0.086 | FAIL | 3v |
| `facet-v1` | 280 | 42 | 18 | 177 | 43 | 2@0.632 | 1.498 | 0.786 | 0.742 | 0.154 | FAIL | 1^ |
| `facet-name-v1` | 280 | 37 | 11 | 137 | 95 | 2@0.489 | 1.603 | 0.829 | 0.801 | 0.339 | **PASS** | — |
| `facet-rare3-v1` | 280 | 45 | 51 | 169 | 15 | 2@0.604 | 1.537 | 0.657 | 0.595 | 0.054 | FAIL | 1^ |

`missed` marks the condition number and direction — `3v` = below condition 3's floor, `3^` = above its ceiling. The two are opposite problems: `v` wants a more lenient prompt, `^` a stricter one.

## Per-condition detail

### `umbrela-v1`

- PASS  modal grade share <= 0.60 — observed 0.586
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.218
- PASS  share at grade 3 <= 0.50 — observed 0.021

### `umbrela-kw-v1`

- PASS  modal grade share <= 0.60 — observed 0.479
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- FAIL  0.20 <= share at grade >=2 <= 0.90 — observed 0.193, below 0.200
- PASS  share at grade 3 <= 0.50 — observed 0.086

### `facet-v1`

- FAIL  modal grade share <= 0.60 — observed 0.632, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.786
- PASS  share at grade 3 <= 0.50 — observed 0.154

### `facet-name-v1`

- PASS  modal grade share <= 0.60 — observed 0.489
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.829
- PASS  share at grade 3 <= 0.50 — observed 0.339

### `facet-rare3-v1`

- FAIL  modal grade share <= 0.60 — observed 0.604, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.657
- PASS  share at grade 3 <= 0.50 — observed 0.054

## Agent-label agreement (smell test — see the caveat above)

| variant | AUC | mean grade: committed | rejected | unjudged | share>=2: committed | rejected | ordered? |
|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 0.659 | 1.29 (n=119) | 0.86 (n=153) | 0.75 (n=8) | 0.319 | 0.144 | yes |
| `umbrela-kw-v1` | 0.541 | 1.03 (n=119) | 0.91 (n=153) | 0.50 (n=8) | 0.235 | 0.170 | yes |
| `facet-v1` | 0.665 | 2.12 (n=119) | 1.53 (n=153) | 1.88 (n=8) | 0.924 | 0.673 | yes |
| `facet-name-v1` | 0.652 | 2.35 (n=119) | 1.80 (n=153) | 1.88 (n=8) | 0.924 | 0.758 | yes |
| `facet-rare3-v1` | 0.705 | 1.92 (n=119) | 1.26 (n=153) | 1.62 (n=8) | 0.857 | 0.497 | yes |

## Stability probe

Re-judged at temperature 0 **bypassing the cache** (a cache hit would trivially report 1.000); requires >= 90% exact match.

| variant | pairs | exact-match rate | verdict |
|---|---|---|---|
| `facet-name-v1` | 50 | 0.660 | **FAIL** |

## Cost and parse health

| variant | calls | parse failures | input tok | output tok | cost USD |
|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 0 | 255841 | 66595 | $0.0390 |
| `umbrela-kw-v1` | 282 | 2 | 231227 | 55062 | $0.0337 |
| `facet-v1` | 282 | 2 | 239557 | 74788 | $0.0404 |
| `facet-name-v1` | 281 | 1 | 246945 | 78690 | $0.0421 |
| `facet-rare3-v1` | 280 | 0 | 284962 | 74156 | $0.0435 |
| **total** | 1405 | 5 | 1258532 | 349291 | **$0.1987** |

Measured mean token counts from this run replace the priors in every later pre-flight estimate (PLAN §5.7 layer 1), so these numbers are an input to WP7's budget check, not just a receipt.

## Prompt provenance

| variant | query slot | emits facet | sha256 |
|---|---|---|---|
| `umbrela-v1` | narrative | no | `e2a8594f0175be58…` |
| `umbrela-kw-v1` | keyword | no | `e2a8594f0175be58…` |
| `facet-v1` | narrative | no | `99229ef649208a52…` |
| `facet-name-v1` | narrative | yes | `0adef718499e24aa…` |
| `facet-rare3-v1` | narrative | yes | `6c3898c45743441b…` |
