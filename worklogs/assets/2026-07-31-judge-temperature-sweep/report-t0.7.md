# WP0/WP6 judge calibration — `calibrate`

- calibration sample: `/tmp/bm25-temp-sweep/t0.7/calibration/sample-280.jsonl` (280 pairs, identical across every variant)
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

`facet-name-v1` has the lowest modal share (0.464) among the 2 gate-passing variants (also passing: `facet-rare3-v1`). The gate is a floor on usability, not the selection criterion — the user confirms this choice before WP7 launches.

## Gate conditions

The four bounds, all inclusive (PLAN §3.3):

1. modal grade share <= 0.60
2. all four grades used (each >= 1 pair)
3. 0.20 <= share at grade >=2 <= 0.90
4. share at grade 3 <= 0.50

| variant | n | 0 | 1 | 2 | 3 | modal | H (bits) | share>=2 | pool-rwt >=2 | share=3 | verdict | missed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 49 | 190 | 38 | 3 | 1@0.679 | 1.281 | 0.146 | 0.128 | 0.011 | FAIL | 1^, 3v |
| `umbrela-kw-v1` | 280 | 97 | 138 | 18 | 27 | 1@0.493 | 1.613 | 0.161 | 0.161 | 0.096 | FAIL | 3v |
| `facet-v1` | 280 | 41 | 21 | 176 | 42 | 2@0.629 | 1.518 | 0.779 | 0.744 | 0.150 | FAIL | 1^ |
| `facet-name-v1` | 280 | 39 | 6 | 130 | 105 | 2@0.464 | 1.559 | 0.839 | 0.805 | 0.375 | **PASS** | — |
| `facet-rare3-v1` | 280 | 44 | 47 | 166 | 23 | 2@0.593 | 1.595 | 0.675 | 0.628 | 0.082 | **PASS** | — |

`missed` marks the condition number and direction — `3v` = below condition 3's floor, `3^` = above its ceiling. The two are opposite problems: `v` wants a more lenient prompt, `^` a stricter one.

## Per-condition detail

### `umbrela-v1`

- FAIL  modal grade share <= 0.60 — observed 0.679, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- FAIL  0.20 <= share at grade >=2 <= 0.90 — observed 0.146, below 0.200
- PASS  share at grade 3 <= 0.50 — observed 0.011

### `umbrela-kw-v1`

- PASS  modal grade share <= 0.60 — observed 0.493
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- FAIL  0.20 <= share at grade >=2 <= 0.90 — observed 0.161, below 0.200
- PASS  share at grade 3 <= 0.50 — observed 0.096

### `facet-v1`

- FAIL  modal grade share <= 0.60 — observed 0.629, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.779
- PASS  share at grade 3 <= 0.50 — observed 0.150

### `facet-name-v1`

- PASS  modal grade share <= 0.60 — observed 0.464
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.839
- PASS  share at grade 3 <= 0.50 — observed 0.375

### `facet-rare3-v1`

- PASS  modal grade share <= 0.60 — observed 0.593
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.675
- PASS  share at grade 3 <= 0.50 — observed 0.082

## Agent-label agreement (smell test — see the caveat above)

| variant | AUC | mean grade: committed | rejected | unjudged | share>=2: committed | rejected | ordered? |
|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 0.632 | 1.16 (n=119) | 0.84 (n=153) | 1.12 (n=8) | 0.202 | 0.098 | yes |
| `umbrela-kw-v1` | 0.543 | 0.99 (n=119) | 0.85 (n=153) | 0.88 (n=8) | 0.168 | 0.163 | yes |
| `facet-v1` | 0.634 | 2.08 (n=119) | 1.57 (n=153) | 1.38 (n=8) | 0.899 | 0.693 | yes |
| `facet-name-v1` | 0.641 | 2.38 (n=119) | 1.83 (n=153) | 2.25 (n=8) | 0.950 | 0.752 | yes |
| `facet-rare3-v1` | 0.656 | 1.90 (n=119) | 1.36 (n=153) | 1.75 (n=8) | 0.832 | 0.556 | yes |

## Stability probe

Re-judged at temperature 0 **bypassing the cache** (a cache hit would trivially report 1.000); requires >= 90% exact match.

| variant | pairs | exact-match rate | verdict |
|---|---|---|---|
| `facet-name-v1` | 50 | 0.760 | **FAIL** |

## Cost and parse health

| variant | calls | parse failures | input tok | output tok | cost USD |
|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 0 | 255841 | 64406 | $0.0383 |
| `umbrela-kw-v1` | 280 | 0 | 229696 | 50837 | $0.0323 |
| `facet-v1` | 283 | 3 | 240619 | 70196 | $0.0390 |
| `facet-name-v1` | 280 | 0 | 246042 | 76230 | $0.0413 |
| `facet-rare3-v1` | 280 | 0 | 284962 | 70828 | $0.0424 |
| **total** | 1403 | 3 | 1257160 | 332497 | **$0.1934** |

Measured mean token counts from this run replace the priors in every later pre-flight estimate (PLAN §5.7 layer 1), so these numbers are an input to WP7's budget check, not just a receipt.

## Prompt provenance

| variant | query slot | emits facet | sha256 |
|---|---|---|---|
| `umbrela-v1` | narrative | no | `e2a8594f0175be58…` |
| `umbrela-kw-v1` | keyword | no | `e2a8594f0175be58…` |
| `facet-v1` | narrative | no | `99229ef649208a52…` |
| `facet-name-v1` | narrative | yes | `0adef718499e24aa…` |
| `facet-rare3-v1` | narrative | yes | `6c3898c45743441b…` |
