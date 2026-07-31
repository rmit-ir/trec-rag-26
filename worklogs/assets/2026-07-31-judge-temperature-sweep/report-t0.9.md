# WP0/WP6 judge calibration — `calibrate`

- calibration sample: `/tmp/bm25-temp-sweep/t0.9/calibration/sample-280.jsonl` (280 pairs, identical across every variant)
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

`facet-name-v1` has the lowest modal share (0.475) among the 3 gate-passing variants (also passing: `facet-v1`, `umbrela-v1`). The gate is a floor on usability, not the selection criterion — the user confirms this choice before WP7 launches.

## Gate conditions

The four bounds, all inclusive (PLAN §3.3):

1. modal grade share <= 0.60
2. all four grades used (each >= 1 pair)
3. 0.20 <= share at grade >=2 <= 0.90
4. share at grade 3 <= 0.50

| variant | n | 0 | 1 | 2 | 3 | modal | H (bits) | share>=2 | pool-rwt >=2 | share=3 | verdict | missed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 53 | 165 | 56 | 6 | 1@0.589 | 1.487 | 0.221 | 0.193 | 0.021 | **PASS** | — |
| `umbrela-kw-v1` | 280 | 101 | 124 | 30 | 25 | 1@0.443 | 1.707 | 0.196 | 0.188 | 0.089 | FAIL | 3v |
| `facet-v1` | 280 | 38 | 33 | 162 | 47 | 2@0.579 | 1.644 | 0.746 | 0.700 | 0.168 | **PASS** | — |
| `facet-name-v1` | 280 | 35 | 5 | 133 | 107 | 2@0.475 | 1.519 | 0.857 | 0.824 | 0.382 | **PASS** | — |
| `facet-rare3-v1` | 280 | 44 | 44 | 169 | 23 | 2@0.604 | 1.575 | 0.686 | 0.628 | 0.082 | FAIL | 1^ |

`missed` marks the condition number and direction — `3v` = below condition 3's floor, `3^` = above its ceiling. The two are opposite problems: `v` wants a more lenient prompt, `^` a stricter one.

## Per-condition detail

### `umbrela-v1`

- PASS  modal grade share <= 0.60 — observed 0.589
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.221
- PASS  share at grade 3 <= 0.50 — observed 0.021

### `umbrela-kw-v1`

- PASS  modal grade share <= 0.60 — observed 0.443
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- FAIL  0.20 <= share at grade >=2 <= 0.90 — observed 0.196, below 0.200
- PASS  share at grade 3 <= 0.50 — observed 0.089

### `facet-v1`

- PASS  modal grade share <= 0.60 — observed 0.579
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.746
- PASS  share at grade 3 <= 0.50 — observed 0.168

### `facet-name-v1`

- PASS  modal grade share <= 0.60 — observed 0.475
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.857
- PASS  share at grade 3 <= 0.50 — observed 0.382

### `facet-rare3-v1`

- FAIL  modal grade share <= 0.60 — observed 0.604, above 0.600
- PASS  all four grades used (each >= 1 pair) — observed 4.000
- PASS  0.20 <= share at grade >=2 <= 0.90 — observed 0.686
- PASS  share at grade 3 <= 0.50 — observed 0.082

## Agent-label agreement (smell test — see the caveat above)

| variant | AUC | mean grade: committed | rejected | unjudged | share>=2: committed | rejected | ordered? |
|---|---|---|---|---|---|---|---|
| `umbrela-v1` | 0.645 | 1.29 (n=119) | 0.90 (n=153) | 0.50 (n=8) | 0.328 | 0.150 | yes |
| `umbrela-kw-v1` | 0.526 | 1.02 (n=119) | 0.88 (n=153) | 0.50 (n=8) | 0.235 | 0.176 | yes |
| `facet-v1` | 0.670 | 2.13 (n=119) | 1.52 (n=153) | 1.62 (n=8) | 0.899 | 0.627 | yes |
| `facet-name-v1` | 0.654 | 2.45 (n=119) | 1.86 (n=153) | 1.88 (n=8) | 0.966 | 0.771 | yes |
| `facet-rare3-v1` | 0.687 | 1.95 (n=119) | 1.33 (n=153) | 1.88 (n=8) | 0.874 | 0.536 | yes |

## Stability probe

Re-judged at temperature 0 **bypassing the cache** (a cache hit would trivially report 1.000); requires >= 90% exact match.

| variant | pairs | exact-match rate | verdict |
|---|---|---|---|
| `facet-name-v1` | 50 | 0.640 | **FAIL** |

## Cost and parse health

| variant | calls | parse failures | input tok | output tok | cost USD |
|---|---|---|---|---|---|
| `umbrela-v1` | 280 | 0 | 255841 | 64683 | $0.0384 |
| `umbrela-kw-v1` | 280 | 0 | 229696 | 55000 | $0.0336 |
| `facet-v1` | 284 | 4 | 241954 | 76190 | $0.0410 |
| `facet-name-v1` | 280 | 0 | 246042 | 77769 | $0.0418 |
| `facet-rare3-v1` | 280 | 0 | 284962 | 74691 | $0.0436 |
| **total** | 1404 | 4 | 1258495 | 348333 | **$0.1984** |

Measured mean token counts from this run replace the priors in every later pre-flight estimate (PLAN §5.7 layer 1), so these numbers are an input to WP7's budget check, not just a receipt.

## Prompt provenance

| variant | query slot | emits facet | sha256 |
|---|---|---|---|
| `umbrela-v1` | narrative | no | `e2a8594f0175be58…` |
| `umbrela-kw-v1` | keyword | no | `e2a8594f0175be58…` |
| `facet-v1` | narrative | no | `99229ef649208a52…` |
| `facet-name-v1` | narrative | yes | `0adef718499e24aa…` |
| `facet-rare3-v1` | narrative | yes | `6c3898c45743441b…` |
