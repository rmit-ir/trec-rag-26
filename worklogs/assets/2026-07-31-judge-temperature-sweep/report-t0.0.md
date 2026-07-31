# WP0/WP6 judge calibration — `calibrate`

- calibration sample: `/tmp/bm25-temp-sweep/t0.0/calibration/sample-280.jsonl` (280 pairs, identical across every variant)
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

`facet-name-v1` has the lowest modal share (0.421) among the 1 gate-passing variant. The gate is a floor on usability, not the selection criterion — the user confirms this choice before WP7 launches.

## Gate conditions

The four bounds, all inclusive (PLAN §3.3):

1. modal grade share <= 0.60
2. all four grades used (each >= 1 pair)
3. 0.20 <= share at grade >=2 <= 0.90
4. share at grade 3 <= 0.50

| variant | n | 0 | 1 | 2 | 3 | modal | H (bits) | share>=2 | pool-rwt >=2 | share=3 | verdict | missed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 48 | 204 | 24 | 4 | 1@0.729 | 1.160 | 0.100 | 0.086 | 0.014 | FAIL | 1^, 3v |
| `umbrela-kw-v1` | 280 | 95 | 144 | 19 | 22 | 1@0.514 | 1.574 | 0.146 | 0.147 | 0.079 | FAIL | 3v |
| `facet-v1` | 280 | 51 | 18 | 171 | 40 | 2@0.611 | 1.538 | 0.754 | 0.711 | 0.143 | FAIL | 1^ |
| `facet-name-v1` | 280 | 37 | 8 | 118 | 117 | 2@0.421 | 1.584 | 0.839 | 0.799 | 0.418 | **PASS** | — |
| `facet-rare3-v1` | 280 | 48 | 37 | 178 | 17 | 2@0.636 | 1.483 | 0.696 | 0.646 | 0.061 | FAIL | 1^ |

`missed` marks the condition number and direction — `3v` = below condition 3's floor, `3^` = above its ceiling. The two are opposite problems: `v` wants a more lenient prompt, `^` a stricter one.

## Per-condition detail

### `umbrela-v1`

- FAIL  modal grade share <= 0.60 — observed 0.729, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- FAIL  0.20 <= share at grade >=2 <= 0.90 — observed 0.100, below 0.200
- PASS  share at grade 3 <= 0.50 — observed 0.014

### `umbrela-kw-v1`

- PASS  modal grade share <= 0.60 — observed 0.514
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- FAIL  0.20 <= share at grade >=2 <= 0.90 — observed 0.146, below 0.200
- PASS  share at grade 3 <= 0.50 — observed 0.079

### `facet-v1`

- FAIL  modal grade share <= 0.60 — observed 0.611, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.754
- PASS  share at grade 3 <= 0.50 — observed 0.143

### `facet-name-v1`

- PASS  modal grade share <= 0.60 — observed 0.421
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.839
- PASS  share at grade 3 <= 0.50 — observed 0.418

### `facet-rare3-v1`

- FAIL  modal grade share <= 0.60 — observed 0.636, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.696
- PASS  share at grade 3 <= 0.50 — observed 0.061

## Agent-label agreement (smell test — see the caveat above)

| variant | AUC | mean grade: committed | rejected | unjudged | share>=2: committed | rejected | ordered? |
|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 0.630 | 1.12 (n=119) | 0.82 (n=153) | 0.75 (n=8) | 0.151 | 0.065 | yes |
| `umbrela-kw-v1` | 0.521 | 0.92 (n=119) | 0.87 (n=153) | 0.62 (n=8) | 0.151 | 0.150 | yes |
| `facet-v1` | 0.658 | 2.06 (n=119) | 1.46 (n=153) | 1.50 (n=8) | 0.899 | 0.647 | yes |
| `facet-name-v1` | 0.661 | 2.51 (n=119) | 1.85 (n=153) | 1.62 (n=8) | 0.983 | 0.739 | yes |
| `facet-rare3-v1` | 0.660 | 1.89 (n=119) | 1.36 (n=153) | 1.38 (n=8) | 0.866 | 0.569 | yes |

## Stability probe

Re-judged at temperature 0 **bypassing the cache** (a cache hit would trivially report 1.000); requires >= 90% exact match.

| variant | pairs | exact-match rate | verdict |
|---|---|---|---|
| `facet-name-v1` | 50 | 0.840 | **FAIL** |

## Cost and parse health

| variant | calls | parse failures | input tok | output tok | cost USD |
|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 0 | 255841 | 70059 | $0.0401 |
| `umbrela-kw-v1` | 280 | 0 | 229696 | 41892 | $0.0295 |
| `facet-v1` | 280 | 0 | 238202 | 71045 | $0.0391 |
| `facet-name-v1` | 280 | 0 | 246042 | 78293 | $0.0419 |
| `facet-rare3-v1` | 280 | 0 | 284962 | 71061 | $0.0425 |
| **total** | 1400 | 0 | 1254743 | 332350 | **$0.1932** |

Measured mean token counts from this run replace the priors in every later pre-flight estimate (PLAN §5.7 layer 1), so these numbers are an input to WP7's budget check, not just a receipt.

## Prompt provenance

| variant | query slot | emits facet | sha256 |
|---|---|---|---|
| `umbrela-v1` | narrative | no | `e2a8594f0175be58…` |
| `umbrela-kw-v1` | keyword | no | `e2a8594f0175be58…` |
| `facet-v1` | narrative | no | `99229ef649208a52…` |
| `facet-name-v1` | narrative | yes | `0adef718499e24aa…` |
| `facet-rare3-v1` | narrative | yes | `6c3898c45743441b…` |
