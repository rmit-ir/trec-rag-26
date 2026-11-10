"""Exploratory: does per-narrative readability (Batch-1 audit JSON) explain the SxS preference between owa-glm5 and sol-research-first?

Uses the already-computed per-report readability values in worklogs/assets/2026-11-08-batch1-readability.json (no raw answers needed).
Primary pre-stated metric: Flesch-Kincaid grade (the one reported in the paper); other formulas are exploratory.
Outcome per narrative: SxS battle-score difference (owa-glm5 minus sol-research-first), plus coverage differences.
Batch 1 only: its preference was holistic, whereas Batch 2 assessors compared answers via nuggets, so readability is
not expected to drive B2. Writes readability-vs-preference.md under worklogs/assets/2026-11-11-official-stats/.
"""
import json
from pathlib import Path

import numpy as np
from scipy import stats

import statistical_analysis as sa
from length_analysis import perm_spearman

REPO = Path(__file__).resolve().parents[2]
SCORES = REPO / "RMIT-ADM+S scores"
OUT = REPO / "worklogs/assets/2026-11-11-official-stats"
audit = json.load(open(REPO / "worklogs/assets/2026-11-08-batch1-readability.json"))
rows = audit["per_topic"]
rng = np.random.default_rng(sa.SEED)
A, B = "owa-glm5", "sol-research-first"
METRICS = ["fk_grade", "reading_ease", "ari", "coleman_liau", "gunning_fog", "words_per_sentence", "words"]
L = ["# Readability vs. SxS preference (exploratory)", "",
     "Per-narrative differences (owa-glm5 minus sol-research-first). Spearman rho with permutation p (100k). "
     "FK grade is the primary (reported) metric; other rows are exploratory and uncorrected.", ""]
for batch, cov_file in (("1", "rag-rubric-scores-batch1-human.tsv"),):  # B1 only: holistic human preference; B2 was nugget-driven
    b = int(batch)
    _, per = sa._load_sxs(SCORES, b)
    ids = [str(x) for x in per[sa.SXS_A + ":ids"]]
    ca, cb = per[sa.SXS_A], per[sa.SXS_B]
    pref = (ca[:, 0] + .5 * ca[:, 1]) / ca.sum(1) - (cb[:, 0] + .5 * cb[:, 1]) / cb.sum(1)
    Y, _, _ = sa.load_family(SCORES, cov_file, "all_strict")
    cov = (Y[sa.SXS_A] - Y[sa.SXS_B]).reindex(ids).to_numpy()
    by = {(r["run"], r["qid"]): r for r in rows if r["batch"] == b}
    avail = [m for m in METRICS if all(by[(r, q)].get(m) is not None for r in (A, B) for q in ids)]
    dm = {m: np.array([by[(A, q)][m] - by[(B, q)][m] for q in ids], float) for m in avail}
    L += [f"## Batch {batch} (n = {len(ids)})", "",
          f"Mean difference in FK grade {dm['fk_grade'].mean():+.2f}; glm5 lower (easier) on {(dm['fk_grade'] < 0).sum()}/{len(ids)} narratives.",
          "", "Holm p adjusts within each column (family of 7 metrics).", "",
          "| metric (A - B) | rho vs SxS preference diff | p | Holm p | rho vs coverage all_strict diff | p | Holm p |", "|---|---|---|---|---|---|---|"]
    ok = ~np.isnan(cov)
    r1 = [perm_spearman(dm[m], pref, rng) for m in avail]
    r2 = [perm_spearman(dm[m][ok], cov[ok], rng) for m in avail]
    h1 = sa.holm(np.array([r["p_perm"] for r in r1]))
    h2 = sa.holm(np.array([r["p_perm"] for r in r2]))
    for m, s1, s2, a, c in zip(avail, r1, r2, h1, h2):
        L.append(f"| {m} | {s1['rho']:+.3f} | {s1['p_perm']:.3f} | {a:.3f} | {s2['rho']:+.3f} | {s2['p_perm']:.3f} | {c:.3f} |")
    # paired sign test: is glm5 easier/shorter on the narratives? (two-sided exact binomial on nonzero differences; Holm over metrics)
    sg = []
    for m in avail:
        d = dm[m][dm[m] != 0]
        sg.append((m, int((d < 0).sum()), len(d), stats.binomtest(int((d < 0).sum()), len(d), 0.5).pvalue))
    hs = sa.holm(np.array([x[3] for x in sg]))
    L += ["", "Paired sign test, owa-glm5 lower than sol-research-first (two-sided exact binomial; Holm over metrics):", "",
          "| metric | glm5 lower on | p | Holm p |", "|---|---|---|---|"]
    L += [f"| {m} | {k}/{n} | {pv:.2e} | {h:.2e} |" for (m, k, n, pv), h in zip(sg, hs)]
    # does FK add anything beyond length? OLS pref ~ dFK + dlog(words)
    X = np.column_stack([np.ones(len(ids)), dm["fk_grade"], np.log(np.array([by[(A, q)]["words"] for q in ids]) / np.array([by[(B, q)]["words"] for q in ids]))])
    beta, *_ = np.linalg.lstsq(X, pref, rcond=None)
    res = pref - X @ beta
    se = np.sqrt(np.diag(res @ res / (len(ids) - 3) * np.linalg.inv(X.T @ X)))
    L += ["", f"OLS preference diff ~ dFK + dlog(words): intercept {beta[0]:+.3f} (se {se[0]:.3f}), dFK {beta[1]:+.4f} (se {se[1]:.4f}, t {beta[1]/se[1]:+.2f}), "
          f"dlog words {beta[2]:+.3f} (se {se[2]:.3f}, t {beta[2]/se[2]:+.2f}); n = {len(ids)}.", ""]
(OUT / "readability-vs-preference.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
