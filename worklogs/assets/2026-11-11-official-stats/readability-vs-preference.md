# Readability vs. SxS preference (exploratory)

Per-narrative differences (owa-glm5 minus sol-research-first). Spearman rho with permutation p (100k). FK grade is the primary (reported) metric; other rows are exploratory and uncorrected.

## Batch 1 (n = 17)

Mean difference in FK grade -6.44; glm5 lower (easier) on 17/17 narratives.

Holm p adjusts within each column (family of 7 metrics).

| metric (A - B) | rho vs SxS preference diff | p | Holm p | rho vs coverage all_strict diff | p | Holm p |
|---|---|---|---|---|---|---|
| fk_grade | +0.265 | 0.301 | 1.000 | +0.069 | 0.796 | 1.000 |
| reading_ease | -0.262 | 0.310 | 1.000 | -0.237 | 0.364 | 1.000 |
| ari | +0.218 | 0.402 | 1.000 | -0.046 | 0.866 | 1.000 |
| coleman_liau | +0.191 | 0.460 | 1.000 | +0.263 | 0.310 | 1.000 |
| gunning_fog | +0.395 | 0.119 | 0.831 | -0.040 | 0.887 | 1.000 |
| words_per_sentence | +0.118 | 0.654 | 1.000 | -0.151 | 0.566 | 1.000 |
| words | -0.201 | 0.436 | 1.000 | -0.178 | 0.498 | 1.000 |

Paired sign test, owa-glm5 lower than sol-research-first (two-sided exact binomial; Holm over metrics):

| metric | glm5 lower on | p | Holm p |
|---|---|---|---|
| fk_grade | 17/17 | 1.53e-05 | 1.07e-04 |
| reading_ease | 1/17 | 2.75e-04 | 8.24e-04 |
| ari | 17/17 | 1.53e-05 | 1.07e-04 |
| coleman_liau | 16/17 | 2.75e-04 | 8.24e-04 |
| gunning_fog | 17/17 | 1.53e-05 | 1.07e-04 |
| words_per_sentence | 17/17 | 1.53e-05 | 1.07e-04 |
| words | 15/17 | 2.35e-03 | 2.35e-03 |

OLS preference diff ~ dFK + dlog(words): intercept +0.030 (se 0.312), dFK -0.0091 (se 0.0364, t -0.25), dlog words -0.402 (se 0.536, t -0.75); n = 17.

