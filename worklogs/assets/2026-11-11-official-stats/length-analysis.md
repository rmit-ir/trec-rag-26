# Exploratory answer-length analysis

Hypothesis-generating only (n = 17 and 25 narratives; one judge; unknown SxS opponents).

## Descriptives (119 narratives)

| run                |   ('words', 'mean') |   ('words', 'median') |   ('sentences', 'mean') |   ('sentences', 'median') |   ('references', 'mean') |   ('references', 'median') |
|:-------------------|--------------------:|----------------------:|------------------------:|--------------------------:|-------------------------:|---------------------------:|
| brief-base-t119    |               830.2 |                   843 |                    21.8 |                        21 |                     25.8 |                         26 |
| brief-hybrid-t119  |               834.3 |                   842 |                    22.1 |                        22 |                     24.7 |                         25 |
| facetrag-t119      |               388.9 |                   362 |                    18.5 |                        18 |                     13.9 |                         14 |
| facets-t119        |               613   |                   585 |                    19.9 |                        17 |                     13.6 |                         14 |
| owa-glm5-t119      |               754   |                   768 |                    16.8 |                        11 |                     15.9 |                         16 |
| sol-default        |               882.5 |                   899 |                    26.7 |                        27 |                     27.9 |                         28 |
| sol-research-first |               936.5 |                   951 |                    24.4 |                        24 |                     27.7 |                         29 |

Median words owa-glm5-t119 / sol-research-first: 0.824; owa-glm5-t119 shorter on 105 of 119 narratives.

## owa-glm5-t119 minus sol-research-first: per-narrative differences vs. log(words ratio)

| batch | outcome | n | Spearman rho | permutation p | Holm p (4 outcomes per batch) | OLS slope on log ratio | intercept (A ahead at equal length?) 95% bootstrap CI |
|---|---|---|---|---|---|---|---|
| B1 | SxS battle-score diff | 17 | -0.152 | 0.561 | 1.000 | -0.307 | +0.105 [-0.042, +0.238] |
| B1 | coverage vital_strict diff | 17 | -0.251 | 0.337 | 1.000 | -0.224 | -0.078 [-0.250, +0.090] |
| B1 | coverage all_strict diff | 17 | -0.171 | 0.513 | 1.000 | -0.196 | -0.099 [-0.248, -0.001] |
| B2 | SxS battle-score diff | 25 | +0.278 | 0.178 | 0.215 | +0.262 | -0.005 [-0.116, +0.110] |
| B2 | coverage vital_strict diff | 23 | +0.370 | 0.084 | 0.215 | +0.248 | -0.055 [-0.162, +0.031] |
| B2 | coverage all_strict diff | 25 | +0.368 | 0.072 | 0.215 | +0.258 | -0.010 [-0.098, +0.060] |

## All runs: within-narrative Spearman between words and coverage

Mean over narratives of the rank correlation across the runs available in that collection; p from permuting run labels of the length vector within each narrative (stat = mean within-narrative Spearman).

| collection | metric | runs | narratives | mean within-narrative rho | permutation p | Holm p (all rows) |
|---|---|---|---|---|---|---|
| b1_human | vital_strict | 7 | 17 | +0.356 | 0.0032 | 0.0032 |
| b1_human | all_strict | 7 | 17 | +0.419 | 0.0002 | 0.0012 |
| b2_manual | vital_strict | 7 | 23 | +0.556 | 0.0002 | 0.0012 |
| b2_manual | all_strict | 7 | 25 | +0.524 | 0.0002 | 0.0012 |
| b2_auto | vital_strict | 7 | 25 | +0.705 | 0.0002 | 0.0012 |
| b2_auto | all_strict | 7 | 25 | +0.720 | 0.0002 | 0.0012 |

## Run level (n = 7 runs, descriptive)

| run | mean words | B1 all | B2 manual all | B2 auto all |
|---|---|---|---|---|
| brief-hybrid-t119 | 834 | 0.909 | 0.723 | 0.565 |
| brief-base-t119 | 830 | 0.862 | 0.721 | 0.555 |
| sol-default | 882 | 0.861 | 0.705 | 0.563 |
| sol-research-first | 937 | 0.887 | 0.702 | 0.560 |
| facets-t119 | 613 | 0.841 | 0.642 | 0.333 |
| owa-glm5-t119 | 754 | 0.821 | 0.605 | 0.243 |
| facetrag-t119 | 389 | 0.622 | 0.481 | 0.110 |

Spearman(mean words, b1_human all_strict) over 7 runs = +0.786

Spearman(mean words, b2_manual all_strict) over 7 runs = +0.643

Spearman(mean words, b2_auto all_strict) over 7 runs = +0.821

## All-pairs length differences (Tukey HSD, narrative blocks)

Two-way ANOVA (run + narrative), balanced, so Tukey HSD with MSE df = (k-1)(N-1); log(words) used so differences are ratios. Pairs listed with adjusted p < 0.05 only.

| run A | run B | ratio of mean words (geometric) | Tukey p |
|---|---|---|---|
| brief-hybrid-t119 | sol-research-first | 0.89 | 0.0058 |
| brief-hybrid-t119 | facets-t119 | 1.41 | 0.0000 |
| brief-hybrid-t119 | owa-glm5-t119 | 1.17 | 0.0001 |
| brief-hybrid-t119 | facetrag-t119 | 2.26 | 0.0000 |
| brief-base-t119 | sol-research-first | 0.88 | 0.0033 |
| brief-base-t119 | facets-t119 | 1.40 | 0.0000 |
| brief-base-t119 | owa-glm5-t119 | 1.16 | 0.0002 |
| brief-base-t119 | facetrag-t119 | 2.25 | 0.0000 |
| sol-default | facets-t119 | 1.49 | 0.0000 |
| sol-default | owa-glm5-t119 | 1.23 | 0.0000 |
| sol-default | facetrag-t119 | 2.39 | 0.0000 |
| sol-research-first | facets-t119 | 1.59 | 0.0000 |
| sol-research-first | owa-glm5-t119 | 1.32 | 0.0000 |
| sol-research-first | facetrag-t119 | 2.55 | 0.0000 |
| facets-t119 | owa-glm5-t119 | 0.83 | 0.0000 |
| facets-t119 | facetrag-t119 | 1.60 | 0.0000 |
| owa-glm5-t119 | facetrag-t119 | 1.94 | 0.0000 |

17 of 21 pairs significant at 0.05 (Tukey).
