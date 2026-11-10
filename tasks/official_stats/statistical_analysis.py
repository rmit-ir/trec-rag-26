"""Statistical analysis for the official TREC RAG 2026 evaluation (implements worklogs/2026-11-10-statistical-analysis-plan.md; run: uv run --project tasks/official_stats python tasks/official_stats/statistical_analysis.py).

Part A  all-pairs comparison of our 7 systems on coverage scores (6 families: 3 collections x vital/all)
        primary:      Tukey HSD from the narrative-blocked two-way ANOVA (all 21 pairs, alpha = 0.05)
        sensitivity:  Romano-Wolf step-down on a narrative-level studentized bootstrap-t (pairs with < MIN_NONZERO
                      nonzero differences: exact sign-flip + Holm-21), label-permutation max-T, sign-flip max-T
Part B  descriptive: narratives at/above the track median with exact binomial CIs (no p-values)
Part C  side-by-side Bradley-Terry: Wald test, tipping correlation, narrative-clustered check,
        contrast design effect (Cochran Q / (N-1)), cross-batch heterogeneity
Part D  coverage vs. human preference for the two SxS runs, and a stratified B1 + B2-manual pooled analysis

All randomness comes from one seeded generator, so a full run is reproducible.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

SEED = 2026
N_BOOT = 20_000          # bootstrap / permutation draws for max-T procedures
N_MC = 200_000           # Monte Carlo sign-flip draws when exact enumeration is infeasible
EXACT_MAX_NZ = 18        # enumerate 2^n sign flips up to this many nonzero differences
MIN_NONZERO = 8          # fewer nonzero differences => exact sign-flip instead of bootstrap-t
ALPHA = 0.05
EPS = 1e-9

RUN_ORDER: tuple[str, ...] = (
    "brief-hybrid-t119",
    "brief-base-t119",
    "sol-default",
    "sol-research-first",
    "facets-t119",
    "owa-glm5-t119",
    "facetrag-t119",
)
COLLECTIONS: tuple[tuple[str, str], ...] = (
    ("b1_human", "rag-rubric-scores-batch1-human.tsv"),
    ("b2_manual", "rag-nugget-scores-batch2-manual.tsv"),
    ("b2_auto", "rag-nugget-scores-batch2-automatic.tsv"),
)
METRICS: tuple[str, ...] = ("vital_strict", "all_strict")
# Ablation contrasts (a - b). Selected after results were visible => exploratory, see plan section 3.4.
CONTRASTS: tuple[tuple[str, str], ...] = (
    ("brief-hybrid-t119", "brief-base-t119"),
    ("sol-research-first", "sol-default"),
    ("owa-glm5-t119", "brief-hybrid-t119"),
    ("facets-t119", "facetrag-t119"),
)
SXS_A, SXS_B = "owa-glm5-t119", "sol-research-first"  # SxS difference is always A - B
SXS_BATCHES = ((1, 17), (2, 25))


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def _chunks(total: int, size: int):
    done = 0
    while done < total:
        b = min(size, total - done)
        yield b
        done += b


def _tstat(num: np.ndarray, se: np.ndarray) -> np.ndarray:
    """num / se; se == 0 gives 0 for a zero numerator and +/-inf otherwise (never NaN)."""
    with np.errstate(all="ignore"):
        safe = np.where(se > 0, se, 1.0)
        inf = np.where(np.abs(num) > 1e-12, np.inf * np.sign(num), 0.0)
        return np.where(se > 0, num / safe, inf)


_SIGN_CACHE: dict[int, np.ndarray] = {}


def _signs(n: int) -> np.ndarray:
    if n not in _SIGN_CACHE:
        bits = (np.arange(2**n)[:, None] >> np.arange(n)) & 1
        _SIGN_CACHE[n] = (2.0 * bits - 1.0)
    return _SIGN_CACHE[n]


def signflip_p(d, rng: np.random.Generator, w=None) -> float:
    """Two-sided paired sign-flip p-value for the (weighted) sum of d; zeros carry no information.

    Exact enumeration when the number of nonzero differences is <= EXACT_MAX_NZ, else N_MC draws.
    """
    d = np.asarray(d, float)
    w = np.ones_like(d) if w is None else np.asarray(w, float)
    x = (w * d)[np.abs(d) > EPS]
    n = x.size
    if n == 0:
        return 1.0
    obs = abs(x.sum())
    if n <= EXACT_MAX_NZ:
        return float(np.mean(np.abs(_signs(n) @ x) >= obs - 1e-12))
    cnt = 0
    for b in _chunks(N_MC, 20_000):
        s = rng.choice((-1.0, 1.0), size=(b, n))
        cnt += int(np.sum(np.abs(s @ x) >= obs - 1e-12))
    return (cnt + 1) / (N_MC + 1)


def holm(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (len(p) - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj


def _short(run: str) -> str:
    return run.removesuffix("-t119")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_family(scores_dir: Path, fname: str, metric: str) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Narrative x run matrix for one metric, track median per narrative, and dropped narrative ids.

    For the vital metric, narratives whose field-wide vital_strict_max is 0 have a zero vital
    denominator (structurally undefined) and are dropped.
    """
    df = pd.read_csv(scores_dir / fname, sep="\t")
    df = df[(df["narrative-id"] != "all") & (df["run"].isin(RUN_ORDER))]
    Y = df.pivot(index="narrative-id", columns="run", values=metric)[list(RUN_ORDER)]
    ref = df.drop_duplicates("narrative-id").set_index("narrative-id")
    median = ref[f"{metric}_median"].reindex(Y.index)
    dropped: list[str] = []
    if metric == "vital_strict":
        zero = ref.loc[Y.index, "vital_strict_max"] <= EPS
        dropped = sorted(Y.index[zero.to_numpy()].tolist())
        Y, median = Y.loc[~zero], median.loc[~zero]
    return Y, median, dropped


# ---------------------------------------------------------------------------
# Part A: all-pairs analysis of one family
# ---------------------------------------------------------------------------
def analyze_family(Y: pd.DataFrame, rng: np.random.Generator) -> dict[str, Any]:
    runs = list(Y.columns)
    X = Y.to_numpy(float)
    N, k = X.shape
    pairs = list(itertools.combinations(range(k), 2))
    I = np.array([p[0] for p in pairs])
    J = np.array([p[1] for p in pairs])
    K = len(pairs)
    D = X[:, I] - X[:, J]
    m = D.mean(0)
    sd = D.std(0, ddof=1)
    se = sd / np.sqrt(N)
    nz = (np.abs(D) > EPS).sum(0)
    elig = nz >= MIN_NONZERO
    ei = np.flatnonzero(elig)
    t = _tstat(m, se)

    # raw per-pair sign-flip p-values (all pairs) and Holm over the family
    p_raw = np.array([signflip_p(D[:, i], rng) for i in range(K)])
    p_holm = holm(p_raw)

    p_rw = np.full(K, np.nan)
    ci_unadj = np.full((K, 2), np.nan)
    ci_sim = np.full((K, 2), np.nan)
    p_perm = np.full(K, np.nan)
    p_sf = np.full(K, np.nan)
    degenerate_frac = 0.0
    crit = float("nan")

    if ei.size:
        De = D[:, ei]
        tb_chunks = []
        deg = 0
        for b in _chunks(N_BOOT, 4000):
            idx = rng.integers(0, N, size=(b, N))
            Db = De[idx]                                   # (b, N, Ke)
            mb = Db.mean(1)
            seb = Db.std(1, ddof=1) / np.sqrt(N)
            tb_chunks.append(_tstat(mb - m[ei], seb))
            deg += int(((seb <= 0) & (np.abs(mb - m[ei]) > 1e-12)).any(1).sum())
        TB = np.vstack(tb_chunks)
        degenerate_frac = deg / N_BOOT
        A = np.abs(TB)
        tobs = np.abs(t[ei])
        order = np.argsort(-tobs)
        Mrev = np.maximum.accumulate(A[:, order][:, ::-1], axis=1)[:, ::-1]
        praw_sorted = (Mrev >= tobs[order] - 1e-12).mean(0)
        padj_sorted = np.maximum.accumulate(praw_sorted)
        tmp = np.empty(ei.size)
        tmp[order] = padj_sorted
        p_rw[ei] = tmp
        crit = float(np.quantile(A.max(1), 1 - ALPHA, method="higher"))
        ci_sim[ei, 0] = m[ei] - crit * se[ei]
        ci_sim[ei, 1] = m[ei] + crit * se[ei]
        qlo, qhi = np.quantile(TB, [ALPHA / 2, 1 - ALPHA / 2], axis=0, method="higher")
        ci_unadj[ei, 0] = m[ei] - qhi * se[ei]
        ci_unadj[ei, 1] = m[ei] - qlo * se[ei]

        # cross-checks (single-step max-T over the eligible pairs)
        perm_max, sf_max = [], []
        for b in _chunks(N_BOOT, 2000):
            perm = np.argsort(rng.random((b, N, k)), axis=2)
            Xp = np.take_along_axis(np.broadcast_to(X, (b, N, k)), perm, axis=2)
            Dp = Xp[:, :, I[ei]] - Xp[:, :, J[ei]]
            perm_max.append(np.abs(_tstat(Dp.mean(1), Dp.std(1, ddof=1) / np.sqrt(N))).max(1))
            Ds = De[None] * rng.choice((-1.0, 1.0), size=(b, N, 1))
            sf_max.append(np.abs(_tstat(Ds.mean(1), Ds.std(1, ddof=1) / np.sqrt(N))).max(1))
        perm_max = np.concatenate(perm_max)
        sf_max = np.concatenate(sf_max)
        p_perm[ei] = [(perm_max >= x - 1e-12).mean() for x in tobs]
        p_sf[ei] = [(sf_max >= x - 1e-12).mean() for x in tobs]

    # Tukey-Kramer from the two-way (narrative block) ANOVA, all pairs
    resid = X - X.mean(1, keepdims=True) - X.mean(0, keepdims=True) + X.mean()
    df_err = (N - 1) * (k - 1)
    mse = float((resid**2).sum() / df_err)
    q = np.abs(m) / math.sqrt(mse / N) if mse > 0 else np.full(K, np.inf)
    p_tukey = stats.studentized_range.sf(q, k, df_err)

    # One interval per system: Tukey-Kramer comparison intervals mean +/- (q/2) * sqrt(MSE/N), built from the
    # block-design residual MSE, so two systems differ (family-wise alpha) iff their intervals do not overlap.
    # Half-width is half the HSD: |diff| > q * sqrt(MSE/N)  <=>  non-overlap of mean +/- (q/2) * sqrt(MSE/N).
    q_crit = float(stats.studentized_range.isf(ALPHA, k, df_err))
    hw = q_crit / 2 * math.sqrt(mse / N)
    t_crit = float(stats.t.isf(ALPHA / 2, N - 1))
    sys_means = X.mean(0)
    sys_se = X.std(0, ddof=1) / math.sqrt(N)
    system_intervals = [
        {
            "run": runs[j],
            "mean": float(sys_means[j]),
            "tukey_half_width": hw,
            "tukey_ci": [float(sys_means[j] - hw), float(sys_means[j] + hw)],
            "unadjusted_t_ci": [float(sys_means[j] - t_crit * sys_se[j]), float(sys_means[j] + t_crit * sys_se[j])],
        }
        for j in range(k)
    ]

    records = []
    for i in range(K):
        d = D[:, i]
        kind = "bootstrap_t" if elig[i] else ("sparse_signflip" if nz[i] > 0 else "all_zero")
        tukey_ci = [float(m[i] - q_crit * math.sqrt(mse / N)), float(m[i] + q_crit * math.sqrt(mse / N))]
        sig = {
            "primary": bool(p_tukey[i] < ALPHA),  # Tukey HSD (narrative-blocked two-way model) is the primary test
            "romano_wolf": bool((p_rw[i] if elig[i] else p_holm[i]) < ALPHA),
            "perm_maxT": bool(p_perm[i] < ALPHA) if elig[i] else False,
            "signflip_maxT": bool(p_sf[i] < ALPHA) if elig[i] else False,
        }
        records.append(
            {
                "run_a": runs[I[i]],
                "run_b": runs[J[i]],
                "n": N,
                "mean_diff": float(m[i]),
                "d_z": float(m[i] / sd[i]) if sd[i] > 0 else None,
                "wins": int((d > EPS).sum()),
                "ties": int((np.abs(d) <= EPS).sum()),
                "losses": int((d < -EPS).sum()),
                "n_nonzero": int(nz[i]),
                "method": kind,
                "p_raw_signflip": float(p_raw[i]),
                "p_holm_21": float(p_holm[i]),
                "p_romano_wolf": None if np.isnan(p_rw[i]) else float(p_rw[i]),
                "ci95_unadjusted": None if np.isnan(ci_unadj[i, 0]) else [float(x) for x in ci_unadj[i]],
                "ci95_simultaneous": tukey_ci,  # Tukey HSD simultaneous CI (primary)
                "ci95_simultaneous_bootstrap": None if np.isnan(ci_sim[i, 0]) else [float(x) for x in ci_sim[i]],
                "p_perm_maxT": None if np.isnan(p_perm[i]) else float(p_perm[i]),
                "p_signflip_maxT": None if np.isnan(p_sf[i]) else float(p_sf[i]),
                "p_tukey_hsd": float(p_tukey[i]),
                "significant": sig,
                "methods_disagree": len(set(sig.values())) > 1,
            }
        )
    return {
        "n_narratives": N,
        "n_pairs": K,
        "n_bootstrap_eligible": int(elig.sum()),
        "n_sparse": int(((nz > 0) & ~elig).sum()),
        "n_all_zero": int((nz == 0).sum()),
        "degenerate_resample_fraction": degenerate_frac,
        "simultaneous_critical_value": crit,
        "tukey_mse": mse,
        "tukey_df": int(df_err),
        "tukey_q_critical": q_crit,
        "system_intervals": system_intervals,
        "pairs": records,
    }


def planned_contrasts(family: dict[str, Any]) -> list[dict[str, Any]]:
    """Ablation contrasts oriented as a - b, with Holm over the four and the 21-pair adjusted values."""
    by_key = {(r["run_a"], r["run_b"]): (r, 1.0) for r in family["pairs"]}
    by_key.update({(r["run_b"], r["run_a"]): (r, -1.0) for r in family["pairs"]})
    rows = []
    for a, b in CONTRASTS:
        r, sgn = by_key[(a, b)]
        ci = r["ci95_unadjusted"]
        sim = r["ci95_simultaneous"]
        rows.append(
            {
                "run_a": a,
                "run_b": b,
                "mean_diff": sgn * r["mean_diff"],
                "ci95_unadjusted": None if ci is None else sorted(sgn * x for x in ci),
                "ci95_simultaneous": None if sim is None else sorted(sgn * x for x in sim),
                "p_raw_signflip": r["p_raw_signflip"],
                "p_tukey_hsd": r["p_tukey_hsd"],
                "p_romano_wolf_21": r["p_romano_wolf"],
                "p_holm_21": r["p_holm_21"],
                "n_nonzero": r["n_nonzero"],
                "method": r["method"],
            }
        )
    holm4 = holm(np.array([x["p_raw_signflip"] for x in rows]))
    for x, h in zip(rows, holm4):
        x["p_holm_4"] = float(h)
    return rows


def run_part_a(scores_dir: Path, rng: np.random.Generator) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, fname in COLLECTIONS:
        for metric in METRICS:
            Y, _, dropped = load_family(scores_dir, fname, metric)
            fam = analyze_family(Y, rng)
            fam["dropped_zero_vital_narratives"] = dropped
            fam["planned_contrasts"] = planned_contrasts(fam)
            out[f"{key}:{metric}"] = fam
    return out


# ---------------------------------------------------------------------------
# Part B: track median, descriptive
# ---------------------------------------------------------------------------
def run_part_b(scores_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, fname in COLLECTIONS:
        for metric in METRICS:
            Y, median, _ = load_family(scores_dir, fname, metric)
            n = len(Y)
            rows = {}
            for run in RUN_ORDER:
                kk = int((Y[run] >= median - EPS).sum())
                lo, hi = stats.binomtest(kk, n).proportion_ci(0.95, method="exact")
                rows[run] = {"at_or_above_median": kk, "n": n, "prop": kk / n, "ci95_exact": [lo, hi]}
            out[f"{key}:{metric}"] = rows
    return out


# ---------------------------------------------------------------------------
# Part C: side-by-side Bradley-Terry
# ---------------------------------------------------------------------------
def _boot_t_ci_weighted(d: np.ndarray, w: np.ndarray, rng: np.random.Generator) -> dict[str, Any]:
    N = len(d)

    def se_of(dd, ww, mm):
        return np.sqrt(N / (N - 1) * ((ww * (dd - mm)) ** 2).sum(-1)) / ww.sum(-1)

    m = float((w * d).sum() / w.sum())
    se = float(se_of(d, w, m))
    idx = rng.integers(0, N, size=(N_BOOT, N))
    db, wb = d[idx], w[idx]
    mb = (wb * db).sum(1) / wb.sum(1)
    seb = se_of(db, wb, mb[:, None])
    ok = seb > 0
    tb = (mb - m)[ok] / seb[ok]
    qlo, qhi = np.quantile(tb, [ALPHA / 2, 1 - ALPHA / 2])
    return {"mean": m, "se": se, "ci95": [m - float(qhi) * se, m - float(qlo) * se], "dropped_draws": float(1 - ok.mean())}


def _load_sxs(scores_dir: Path, batch: int) -> tuple[dict[str, dict[str, float]], dict[str, np.ndarray]]:
    bt = pd.read_csv(scores_dir / f"rag-bt-scores-batch{batch}.tsv", sep="\t")
    bt = bt[bt["narrative-id"] == "all"].set_index("run")
    ratings = {
        r: {"bt": float(bt.loc[r, "bt_score"]), "lo": float(bt.loc[r, "ci_lower"]), "hi": float(bt.loc[r, "ci_upper"])}
        for r in (SXS_A, SXS_B)
    }
    cnt = pd.read_csv(scores_dir / f"rag-sxs-counts-batch{batch}.tsv", sep="\t")
    cnt = cnt[cnt["narrative-id"] != "all"]
    per = {}
    for r in (SXS_A, SXS_B):
        sub = cnt[cnt["run"] == r].set_index("narrative-id").sort_index()
        per[r] = sub[["wins", "ties", "losses"]].to_numpy(float)
        per[r + ":ids"] = np.array(sub.index)
    assert (per[SXS_A + ":ids"] == per[SXS_B + ":ids"]).all()
    return ratings, per


def contrast_deff(ca: np.ndarray, cb: np.ndarray, rng: np.random.Generator) -> dict[str, Any]:
    """Design effect of the per-narrative contrast d_t = s_A,t - s_B,t (Cochran Q / (N-1) form)."""
    mA, mB = ca.sum(1), cb.sum(1)
    sA, sB = (ca[:, 0] + 0.5 * ca[:, 1]) / mA, (cb[:, 0] + 0.5 * cb[:, 1]) / mB
    d = sA - sB
    w = 1.0 / (1.0 / mA + 1.0 / mB)
    pa, pb = ca.sum(0) / ca.sum(), cb.sum(0) / cb.sum()

    def sigma2(p, M):
        sbar = p[0] + 0.5 * p[1]
        return M * (p[0] * (1 - sbar) ** 2 + p[1] * (0.5 - sbar) ** 2 + p[2] * sbar**2) / (M - 1)

    s2a, s2b = sigma2(pa, ca.sum()), sigma2(pb, cb.sum())
    v = s2a / mA + s2b / mB

    def deff(dd, ww, vv):
        N = dd.shape[-1]
        dw = (ww * dd).sum(-1, keepdims=True) / ww.sum(-1, keepdims=True)
        return (ww * (dd - dw) ** 2).sum(-1) / (N - 1) / ((ww * vv).sum(-1) / N)

    obs = float(deff(d, w, v))
    N = len(d)
    # null: independent judgments with the pooled outcome distribution of each run
    Wa = rng.multinomial(mA.astype(int), pa, size=(N_BOOT, N))   # (B, N, 3)
    Wb = rng.multinomial(mB.astype(int), pb, size=(N_BOOT, N))
    ds = (Wa[..., 0] + 0.5 * Wa[..., 1]) / mA - (Wb[..., 0] + 0.5 * Wb[..., 1]) / mB
    null = deff(ds, np.broadcast_to(w, ds.shape), np.broadcast_to(v, ds.shape))
    idx = rng.integers(0, N, size=(N_BOOT, N))
    boot = deff(d[idx], w[idx], v[idx])
    return {
        "deff": obs,
        "p_simulated_null": float((np.sum(null >= obs) + 1) / (N_BOOT + 1)),
        "ci95_bootstrap": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "sigma2_a": float(s2a),
        "sigma2_b": float(s2b),
    }


def run_part_c(scores_dir: Path, rng: np.random.Generator) -> dict[str, Any]:
    z_crit = stats.norm.isf(ALPHA / 2)
    batches: dict[str, Any] = {}
    wald_p = []
    d_by_batch: dict[int, np.ndarray] = {}
    for batch, _ in SXS_BATCHES:
        ratings, per = _load_sxs(scores_dir, batch)
        a, b = ratings[SXS_A], ratings[SXS_B]
        se_a, se_b = (a["hi"] - a["lo"]) / 2 / z_crit, (b["hi"] - b["lo"]) / 2 / z_crit
        diff = a["bt"] - b["bt"]
        z = diff / math.hypot(se_a, se_b)
        p = float(2 * stats.norm.sf(abs(z)))
        wald_p.append(p)
        # correlation needed to reach p = ALPHA (None if it would require rho < -1)
        rho_star = (se_a**2 + se_b**2 - (diff / z_crit) ** 2) / (2 * se_a * se_b)
        var99 = se_a**2 + se_b**2 + 2 * 0.99 * se_a * se_b
        z99 = diff / math.sqrt(var99)

        # narrative-clustered nonparametric check on battle scores
        ca, cb = per[SXS_A], per[SXS_B]
        mA, mB = ca.sum(1), cb.sum(1)
        d = (ca[:, 0] + 0.5 * ca[:, 1]) / mA - (cb[:, 0] + 0.5 * cb[:, 1]) / mB
        d_by_batch[batch] = d
        w = 1.0 / (1.0 / mA + 1.0 / mB)
        unw = _boot_t_ci_weighted(d, np.ones_like(d), rng)
        wtd = _boot_t_ci_weighted(d, w, rng)
        unw["p_signflip"] = signflip_p(d, rng)
        wtd["p_signflip"] = signflip_p(d, rng, w)
        unw["wins_ties_losses_narratives"] = [int((d > EPS).sum()), int((np.abs(d) <= EPS).sum()), int((d < -EPS).sum())]

        deff = contrast_deff(ca, cb, rng)
        z_cl = z / math.sqrt(max(1.0, deff["deff"]))
        batches[f"batch{batch}"] = {
            "n_narratives": len(d),
            "rating_a": a,
            "rating_b": b,
            "se_a": se_a,
            "se_b": se_b,
            "diff_a_minus_b": diff,
            "wald_z": z,
            "wald_p": p,
            "elo_win_prob_if_400_log10_scale": 1 / (1 + 10 ** (-diff / 400)),
            "tipping_rho": None if rho_star < -1 else float(rho_star),
            "z_at_rho_minus_0.99": z99,
            "p_at_rho_minus_0.99": float(2 * stats.norm.sf(abs(z99))),
            "narrative_clustered_unweighted": unw,
            "narrative_clustered_battle_weighted": wtd,
            "contrast_design_effect": deff,
            "wald_z_deff_adjusted": z_cl,
            "wald_p_deff_adjusted": float(2 * stats.norm.sf(abs(z_cl))),
        }
    holm2 = holm(np.array(wald_p))
    for key, h in zip(("batch1", "batch2"), holm2):
        batches[key]["wald_p_holm_2"] = float(h)
    d1, d2 = batches["batch1"]["diff_a_minus_b"], batches["batch2"]["diff_a_minus_b"]
    v1 = batches["batch1"]["se_a"] ** 2 + batches["batch1"]["se_b"] ** 2
    v2 = batches["batch2"]["se_a"] ** 2 + batches["batch2"]["se_b"] ** 2
    zh = (d1 - d2) / math.sqrt(v1 + v2)
    # Primary between-batch test: two-sample permutation on the per-narrative battle-score difference. That quantity is a
    # proportion on one bounded scale in both batches, so no assumption about the relative BT scale is needed.
    narr = _two_sample_perm(d_by_batch[1], d_by_batch[2], rng)
    return {
        "batches": batches,
        "heterogeneity": {
            "primary_narrative_battle_score": {"mean_b1": float(d_by_batch[1].mean()), "mean_b2": float(d_by_batch[2].mean()),
                                               "n_b1": len(d_by_batch[1]), "n_b2": len(d_by_batch[2]), **narr},
            # Secondary, assumption-laden: assumes both separately fitted BT scales are comparable (same link/scale, no
            # protocol-dependent discrimination). Reported for transparency only; not used in the paper.
            "bt_diff_of_diffs_common_scale_assumed": {"z": zh, "p": float(2 * stats.norm.sf(abs(zh))), "diff_of_diffs": d1 - d2},
        },
    }


# ---------------------------------------------------------------------------
# Part D: coverage vs. preference, and stratified B1 + B2-manual pooling
# ---------------------------------------------------------------------------
def _two_sample_perm(x: np.ndarray, y: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    obs = x.mean() - y.mean()
    pool = np.concatenate([x, y])
    nx = len(x)
    cnt = 0
    for b in _chunks(N_MC, 20_000):
        perm = np.argsort(rng.random((b, len(pool))), axis=1)
        sh = pool[perm]
        stat = sh[:, :nx].mean(1) - sh[:, nx:].mean(1)
        cnt += int(np.sum(np.abs(stat) >= abs(obs) - 1e-12))
    return {"diff": float(obs), "p": (cnt + 1) / (N_MC + 1)}


def run_part_d(scores_dir: Path, rng: np.random.Generator) -> dict[str, Any]:
    out: dict[str, Any] = {"glm5_vs_research_first_coverage": {}, "stratified_b1_b2manual": {}}
    fname = dict(COLLECTIONS)
    for metric in METRICS:
        diffs = {}
        for key, f in COLLECTIONS:
            Y, _, _ = load_family(scores_dir, f, metric)
            diffs[key] = (Y[SXS_A] - Y[SXS_B]).to_numpy()
        rec = {
            key: {
                "n": len(v),
                "mean_a_minus_b": float(v.mean()),
                "wins_ties_losses": [int((v > EPS).sum()), int((np.abs(v) <= EPS).sum()), int((v < -EPS).sum())],
            }
            for key, v in diffs.items()
        }
        rec["interaction_b1_vs_b2manual"] = _two_sample_perm(diffs["b1_human"], diffs["b2_manual"], rng)
        out["glm5_vs_research_first_coverage"][metric] = rec

        # stratified pooled analysis over all pairs (B1 + B2 manual, equal narrative weights)
        Y1, _, _ = load_family(scores_dir, fname["b1_human"], metric)
        Y2, _, _ = load_family(scores_dir, fname["b2_manual"], metric)
        rows = []
        for a, b in itertools.combinations(RUN_ORDER, 2):
            d1, d2 = (Y1[a] - Y1[b]).to_numpy(), (Y2[a] - Y2[b]).to_numpy()
            pooled = np.concatenate([d1, d2])
            rows.append(
                {
                    "run_a": a,
                    "run_b": b,
                    "n": len(pooled),
                    "pooled_mean_diff": float(pooled.mean()),
                    "p_signflip": signflip_p(pooled, rng),
                    "interaction": _two_sample_perm(d1, d2, rng),
                }
            )
        hp = holm(np.array([r["p_signflip"] for r in rows]))
        hi = holm(np.array([r["interaction"]["p"] for r in rows]))
        for r, x, y in zip(rows, hp, hi):
            r["p_holm_21"] = float(x)
            r["interaction"]["p_holm_21"] = float(y)
        out["stratified_b1_b2manual"][metric] = rows
    return out


# ---------------------------------------------------------------------------
# Orchestration, printing, figure
# ---------------------------------------------------------------------------
def run_statistical_analysis(scores_dir: Path, seed: int = SEED) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    return {
        "settings": {
            "seed": seed,
            "n_bootstrap": N_BOOT,
            "n_monte_carlo_signflip": N_MC,
            "min_nonzero_for_bootstrap_t": MIN_NONZERO,
            "alpha": ALPHA,
        },
        "part_a_pairwise_coverage": run_part_a(scores_dir, rng),
        "part_b_track_median": run_part_b(scores_dir),
        "part_c_sxs_bradley_terry": run_part_c(scores_dir, rng),
        "part_d_coverage_vs_preference": run_part_d(scores_dir, rng),
    }


def print_summary(res: dict[str, Any]) -> None:
    print("\n=== Part A: all-pairs coverage (Tukey HSD primary; Romano-Wolf, max-T, Holm-21 are sensitivity checks) ===")
    for fam_key, fam in res["part_a_pairwise_coverage"].items():
        sig = [
            f"{_short(r['run_a'])}-{_short(r['run_b'])}({r['mean_diff']:+.3f})"
            for r in fam["pairs"]
            if r["significant"]["primary"]
        ]
        dis = sum(r["methods_disagree"] for r in fam["pairs"])
        print(
            f"  {fam_key:<22} N={fam['n_narratives']:<3} bootstrap-t pairs={fam['n_bootstrap_eligible']:<2} "
            f"sparse={fam['n_sparse']:<2} all-zero={fam['n_all_zero']:<2} degenerate-resamples={fam['degenerate_resample_fraction']:.3%} "
            f"| significant: {', '.join(sig) if sig else 'none'} | pairs where methods disagree: {dis}"
        )
        for c in fam["planned_contrasts"]:
            ci = c["ci95_unadjusted"]
            ci_s = "n/a" if ci is None else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"
            rw = c["p_romano_wolf_21"]
            print(
                f"      {_short(c['run_a'])} - {_short(c['run_b'])}: d={c['mean_diff']:+.4f} CI={ci_s} "
                f"nz={c['n_nonzero']} [{c['method']}] p_raw={c['p_raw_signflip']:.3f} "
                f"Holm4={c['p_holm_4']:.3f} Tukey={c['p_tukey_hsd']:.3f} Holm21={c['p_holm_21']:.3f} "
                f"RW21={'n/a' if rw is None else f'{rw:.3f}'}"
            )
    print("\n=== Part C: side-by-side Bradley-Terry ===")
    for key, b in res["part_c_sxs_bradley_terry"]["batches"].items():
        cl = b["narrative_clustered_unweighted"]
        de = b["contrast_design_effect"]
        print(
            f"  {key}: diff(glm5 - research-first)={b['diff_a_minus_b']:+.1f} Wald z={b['wald_z']:.2f} p={b['wald_p']:.2g} "
            f"Holm2={b['wald_p_holm_2']:.2g}; tipping rho={b['tipping_rho']}; "
            f"z@rho=-0.99={b['z_at_rho_minus_0.99']:.2f} (p={b['p_at_rho_minus_0.99']:.3g})"
        )
        print(
            f"      narrative-clustered: mean d={cl['mean']:+.3f} CI=[{cl['ci95'][0]:+.3f}, {cl['ci95'][1]:+.3f}] "
            f"p_signflip={cl['p_signflip']:.4f} (W/T/L {cl['wins_ties_losses_narratives']}); "
            f"battle-weighted p={b['narrative_clustered_battle_weighted']['p_signflip']:.4f}; "
            f"DEFF={de['deff']:.2f} CI=[{de['ci95_bootstrap'][0]:.2f}, {de['ci95_bootstrap'][1]:.2f}] "
            f"p_null={de['p_simulated_null']:.3f}; DEFF-adjusted z={b['wald_z_deff_adjusted']:.2f} (p={b['wald_p_deff_adjusted']:.3g})"
        )
    h = res["part_c_sxs_bradley_terry"]["heterogeneity"]
    n = h["primary_narrative_battle_score"]
    g = h["bt_diff_of_diffs_common_scale_assumed"]
    print(f"  between-batch (narrative battle score, permutation): B1 {n['mean_b1']:+.3f} vs B2 {n['mean_b2']:+.3f}, diff={n['diff']:+.3f}, p={n['p']:.4f}")
    print(f"  [secondary, assumes common BT scale] BT diff-of-diffs={g['diff_of_diffs']:+.1f}, z={g['z']:.2f}, p={g['p']:.2g}")
    print("\n=== Part D: owa-glm5 - sol-research-first coverage, B1 vs B2 manual interaction ===")
    for metric, rec in res["part_d_coverage_vs_preference"]["glm5_vs_research_first_coverage"].items():
        it = rec["interaction_b1_vs_b2manual"]
        print(
            f"  {metric}: B1 {rec['b1_human']['mean_a_minus_b']:+.3f} (n={rec['b1_human']['n']}), "
            f"B2 manual {rec['b2_manual']['mean_a_minus_b']:+.3f} (n={rec['b2_manual']['n']}), "
            f"B2 auto {rec['b2_auto']['mean_a_minus_b']:+.3f}; interaction diff={it['diff']:+.3f}, p={it['p']:.3f}"
        )


def plot_forest(res: dict[str, Any], out_pdf: Path, metrics: tuple[str, ...] = METRICS) -> None:
    """Forest plot of pairwise mean differences: unadjusted CI (thick) and simultaneous CI (thin)."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(metrics), 3, figsize=(13, 5.8 * len(metrics)), sharey=True, squeeze=False)
    for col, (key, _) in enumerate(COLLECTIONS):
        for row, metric in enumerate(metrics):
            ax = axes[row, col]
            fam = res["part_a_pairwise_coverage"][f"{key}:{metric}"]
            pairs = sorted(fam["pairs"], key=lambda r: r["mean_diff"])
            for y, r in enumerate(pairs):
                label_sig = r["significant"]["primary"]
                if r["ci95_simultaneous"]:
                    ax.plot(r["ci95_simultaneous"], [y, y], color="0.6", lw=1)
                if r["ci95_unadjusted"]:
                    ax.plot(r["ci95_unadjusted"], [y, y], color="C0", lw=3)
                ax.plot(
                    r["mean_diff"], y, "o", color="black" if label_sig else "C0",
                    mfc="black" if label_sig else ("white" if r["method"] != "bootstrap_t" else "C0"), ms=4,
                )
            ax.axvline(0, color="0.3", lw=0.8)
            ax.set_yticks(range(len(pairs)))
            ax.set_yticklabels([f"{_short(r['run_a'])} - {_short(r['run_b'])}" for r in pairs], fontsize=6)
            ax.set_title(f"{key} / {metric} (N={fam['n_narratives']})", fontsize=8)
            ax.tick_params(axis="x", labelsize=7)
    fig.supxlabel(
        "Mean paired difference (thick: unadjusted bootstrap-t 95% CI; thin: Tukey HSD simultaneous 95% CI; "
        "hollow: sparse pair, no unadjusted CI; black: significant by Tukey HSD at 0.05)",
        fontsize=8,
    )
    fig.tight_layout()
    fig.savefig(out_pdf)
    plt.close(fig)


def plot_system_intervals(res: dict[str, Any], out_pdf: Path, metrics: tuple[str, ...] = METRICS) -> None:
    """One multiplicity-adjusted interval per system (Tukey-Kramer comparison intervals, as statsmodels'
    ``plot_simultaneous``): non-overlapping intervals <=> significant pair at family-wise 5%.
    Thin grey: unadjusted 95% t interval of the system mean."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(metrics), 3, figsize=(12, 3.6 * len(metrics)), squeeze=False)
    for col, (key, _) in enumerate(COLLECTIONS):
        for row, metric in enumerate(metrics):
            ax = axes[row, col]
            fam = res["part_a_pairwise_coverage"][f"{key}:{metric}"]
            sysi = sorted(fam["system_intervals"], key=lambda r: r["mean"])
            for y, r in enumerate(sysi):
                ax.plot(r["unadjusted_t_ci"], [y, y], color="0.65", lw=1)
                ax.plot(r["tukey_ci"], [y, y], color="C0", lw=3)
                ax.plot(r["mean"], y, "o", color="black", ms=4)
            ax.set_yticks(range(len(sysi)))
            ax.set_yticklabels([_short(r["run"]) for r in sysi], fontsize=7)
            ax.set_title(f"{key} / {metric} (N={fam['n_narratives']})", fontsize=8)
            ax.tick_params(axis="x", labelsize=7)
    fig.supxlabel(
        "System mean (thick blue: Tukey-Kramer 95% comparison interval, non-overlap = significant pair; "
        "thin grey: unadjusted 95% t interval)",
        fontsize=8,
    )
    fig.tight_layout()
    fig.savefig(out_pdf)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Output type 1 (paper): a few selected tables + one figure, bare tabulars like the other tables/*.tex
# ---------------------------------------------------------------------------
def _fmt_p(p: float | None) -> str:
    if p is None:
        return "---"
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


def write_paper_outputs(res: dict[str, Any], tables_dir: Path, figures_dir: Path) -> None:
    """Selected results for the paper: ablation-contrast table, SxS test table, all_strict forest plot."""
    fam = res["part_a_pairwise_coverage"]
    rows = []
    for i, (a, b) in enumerate(CONTRASTS):
        cells = [rf"\texttt{{{_short(a)}}} $-$ \texttt{{{_short(b)}}}"]
        for key, _ in COLLECTIONS:
            c = fam[f"{key}:all_strict"]["planned_contrasts"][i]
            ci = c["ci95_unadjusted"]
            cell = f"${c['mean_diff']:+.3f}$"
            cells.append(cell + ("" if ci is None else f" [{ci[0]:+.3f}, {ci[1]:+.3f}]"))
            cells.append(_fmt_p(c["p_holm_4"]))
        rows.append(" & ".join(cells) + r" \\")
    tex = "\n".join(
        [
            r"\begin{tabular}{@{}lcccccc@{}}",
            r"\toprule",
            r" & \multicolumn{2}{c}{B1 Human Rubric} & \multicolumn{2}{c}{B2 Manual Nuggets} & \multicolumn{2}{c}{B2 Auto Nuggets} \\",
            r"\cmidrule(lr){2-3} \cmidrule(lr){4-5} \cmidrule(lr){6-7}",
            r"Contrast & $\Delta$ [95\% CI] & $p_{\text{Holm}}$ & $\Delta$ [95\% CI] & $p_{\text{Holm}}$ & $\Delta$ [95\% CI] & $p_{\text{Holm}}$ \\",
            r"\midrule",
            *rows,
            r"\bottomrule",
            r"\end{tabular}",
            "",
        ]
    )
    (tables_dir / "ablation-contrasts.tex").write_text(tex, encoding="utf-8")

    sx = res["part_c_sxs_bradley_terry"]["batches"]
    rows = []
    for key, label in (("batch1", "B1"), ("batch2", "B2")):
        b = sx[key]
        cl = b["narrative_clustered_unweighted"]
        w, _, l = cl["wins_ties_losses_narratives"]
        rows.append(
            f"{label} & ${b['diff_a_minus_b']:+.1f}$ & ${b['wald_z']:+.2f}$ & {_fmt_p(b['wald_p'])} & "
            f"${cl['mean']:+.3f}$ [{cl['ci95'][0]:+.3f}, {cl['ci95'][1]:+.3f}] & {w}/{l} & {_fmt_p(cl['p_signflip'])} \\\\"
        )
    nb = res["part_c_sxs_bradley_terry"]["heterogeneity"]["primary_narrative_battle_score"]
    rows += [r"\midrule", f"B1 $-$ B2 & & & & ${nb['diff']:+.3f}$ & & {_fmt_p(nb['p'])} \\\\"]
    tex = "\n".join(
        [
            r"\begin{tabular}{@{}lcccccc@{}}",
            r"\toprule",
            r" & \multicolumn{3}{c}{BT rating (Wald)} & \multicolumn{3}{c}{Per-narrative battle score} \\",
            r"\cmidrule(lr){2-4} \cmidrule(lr){5-7}",
            r"Batch & $\Delta$ rating & $z$ & $p$ & $\Delta$ [95\% CI] & Narr.\ W/L & $p$ \\",
            r"\midrule",
            *rows,
            r"\bottomrule",
            r"\end{tabular}",
            "",
        ]
    )
    (tables_dir / "sxs-tests.tex").write_text(tex, encoding="utf-8")
    # whole analysis in one table: every pair, all six families (diff and Tukey HSD p; bold = p < 0.05)
    fams = [(k, m) for k, _ in COLLECTIONS for m in METRICS]
    runs = list(RUN_ORDER)
    rows = []
    for ia, ib in itertools.combinations(range(len(runs)), 2):
        cells = [rf"\texttt{{{_short(runs[ia])}}} $-$ \texttt{{{_short(runs[ib])}}}"]
        for k, m in fams:
            r = next(x for x in fam[f"{k}:{m}"]["pairs"] if (x["run_a"], x["run_b"]) == (runs[ia], runs[ib]))
            cell = f"${r['mean_diff']:+.3f}$ ({_fmt_p(r['p_tukey_hsd'])})"
            cells.append(rf"\textbf{{{cell}}}" if r["p_tukey_hsd"] < ALPHA else cell)
        rows.append(" & ".join(cells) + r" \\")
    head = " & ".join(f"{k.replace('_', ' ')} / {m.split('_')[0]}" for k, m in fams)
    (tables_dir / "pairwise-tukey-all.tex").write_text("\n".join([
        r"\begin{tabular}{@{}l" + "c" * len(fams) + r"@{}}", r"\toprule", f"Pair & {head} \\\\", r"\midrule", *rows,
        r"\bottomrule", r"\end{tabular}", ""]), encoding="utf-8")
    plot_forest(res, figures_dir / "pairwise-forest.pdf", metrics=("all_strict",))
    plot_system_intervals(res, figures_dir / "system-intervals.pdf", metrics=("all_strict",))


# ---------------------------------------------------------------------------
# Output type 2 (review): everything, as markdown + CSV + full figure + raw JSON
# ---------------------------------------------------------------------------
def write_detailed_outputs(res: dict[str, Any], out_dir: Path) -> None:
    import json

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "statistical-analysis-results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    pair_rows = []
    for fam_key, fam in res["part_a_pairwise_coverage"].items():
        for r in fam["pairs"]:
            flat = {k: v for k, v in r.items() if k not in ("significant", "ci95_unadjusted", "ci95_simultaneous", "ci95_simultaneous_bootstrap")}
            for name, v in r["significant"].items():
                flat[f"sig_{name}"] = v
            for name in ("ci95_unadjusted", "ci95_simultaneous", "ci95_simultaneous_bootstrap"):
                lo_hi = r[name] or [None, None]
                flat[f"{name}_low"], flat[f"{name}_high"] = lo_hi
            pair_rows.append({"family": fam_key, **flat})
    pd.DataFrame(pair_rows).to_csv(out_dir / "partA_all_pairs.csv", index=False)

    b_rows = [
        {"family": fam_key, "run": run, **{k: v for k, v in rec.items() if k != "ci95_exact"},
         "ci95_low": rec["ci95_exact"][0], "ci95_high": rec["ci95_exact"][1]}
        for fam_key, runs in res["part_b_track_median"].items()
        for run, rec in runs.items()
    ]
    pd.DataFrame(b_rows).to_csv(out_dir / "partB_track_median.csv", index=False)

    c = res["part_c_sxs_bradley_terry"]
    pd.json_normalize(
        [{"batch": k, **v} for k, v in c["batches"].items()], sep="."
    ).to_csv(out_dir / "partC_sxs.csv", index=False)

    d = res["part_d_coverage_vs_preference"]
    pd.json_normalize(
        [{"metric": m, **rec} for m, rec in d["glm5_vs_research_first_coverage"].items()], sep="."
    ).to_csv(out_dir / "partD_glm5_vs_research_first.csv", index=False)
    pd.json_normalize(
        [{"metric": m, **r} for m, rows in d["stratified_b1_b2manual"].items() for r in rows], sep="."
    ).to_csv(out_dir / "partD_stratified_pooled.csv", index=False)

    L: list[str] = ["# Statistical analysis: full results", "", "Generated by `scripts/statistical_analysis.py`. "
        f"Settings: `{res['settings']}`.", "",
        "**Primary test: Tukey HSD** on the narrative-blocked two-way model (all 21 pairs, alpha = 0.05); `Tukey` column and "
        "`CI (simult.)` (Tukey simultaneous CI) are the reported results. Everything else is a sensitivity check. "
        "Method key (sensitivity): `bootstrap_t` = Romano-Wolf step-down on narrative-level studentized bootstrap-t "
        f"(pairs with >= {MIN_NONZERO} nonzero differences); `sparse_signflip` = exact sign-flip test "
        "conditional on nonzero differences, Holm over 21 pairs, no CI; `all_zero` = no differences. "
        "`p_raw` = per-pair sign-flip p-value. Cross-checks: label-permutation max-T, sign-flip max-T, "
        "Tukey-Kramer (two-way ANOVA). Differences are run A minus run B.", ""]
    L += ["## Part A: all-pairs coverage comparisons", ""]
    for fam_key, fam in res["part_a_pairwise_coverage"].items():
        L += [f"### {fam_key} (N={fam['n_narratives']})", "",
              f"- bootstrap-t pairs: {fam['n_bootstrap_eligible']}, sparse: {fam['n_sparse']}, all-zero: {fam['n_all_zero']}; "
              f"degenerate resample fraction {fam['degenerate_resample_fraction']:.4%}; "
              f"simultaneous critical value {fam['simultaneous_critical_value']:.3f}; Tukey MSE {fam['tukey_mse']:.5f}"]
        if fam["dropped_zero_vital_narratives"]:
            L.append(f"- dropped zero-vital narratives: {', '.join(fam['dropped_zero_vital_narratives'])}")
        L += ["", "Planned (ablation) contrasts:", "",
              "| a - b | diff | CI (unadj.) | nz | method | p_raw | Holm-4 | Tukey | Holm-21 | RW-21 |", "|---|---|---|---|---|---|---|---|---|---|"]
        for cc in fam["planned_contrasts"]:
            ci = cc["ci95_unadjusted"]
            rw = cc["p_romano_wolf_21"]
            L.append(
                f"| {_short(cc['run_a'])} - {_short(cc['run_b'])} | {cc['mean_diff']:+.4f} | "
                f"{'n/a' if ci is None else f'[{ci[0]:+.3f}, {ci[1]:+.3f}]'} | {cc['n_nonzero']} | {cc['method']} | "
                f"{cc['p_raw_signflip']:.4f} | {cc['p_holm_4']:.4f} | {cc['p_tukey_hsd']:.4f} | {cc['p_holm_21']:.4f} | {'n/a' if rw is None else f'{rw:.4f}'} |"
            )
        L += ["", "All 21 pairs:", "",
              "| a - b | diff | d_z | W/T/L | nz | method | p_raw | Holm-21 | RW | perm maxT | signflip maxT | Tukey | CI (unadj.) | CI (simult.) | methods disagree |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(fam["pairs"], key=lambda x: x["p_tukey_hsd"]):
            def f(v): return "n/a" if v is None else f"{v:.4f}"
            def ci(v): return "n/a" if v is None else f"[{v[0]:+.3f}, {v[1]:+.3f}]"
            L.append(
                f"| {_short(r['run_a'])} - {_short(r['run_b'])} | {r['mean_diff']:+.4f} | "
                f"{'n/a' if r['d_z'] is None else f'{r['d_z']:+.2f}'} | {r['wins']}/{r['ties']}/{r['losses']} | {r['n_nonzero']} | "
                f"{r['method']} | {f(r['p_raw_signflip'])} | {f(r['p_holm_21'])} | {f(r['p_romano_wolf'])} | "
                f"{f(r['p_perm_maxT'])} | {f(r['p_signflip_maxT'])} | {f(r['p_tukey_hsd'])} | "
                f"{ci(r['ci95_unadjusted'])} | {ci(r['ci95_simultaneous'])} | {'yes' if r['methods_disagree'] else ''} |"
            )
        L.append("")
    L += ["## Part B: narratives at or above the track median (descriptive)", "",
          "| family | run | at/above median | n | proportion | exact 95% CI |", "|---|---|---|---|---|---|"]
    for fam_key, runs in res["part_b_track_median"].items():
        for run, rec in runs.items():
            L.append(f"| {fam_key} | {_short(run)} | {rec['at_or_above_median']} | {rec['n']} | {rec['prop']:.3f} | "
                     f"[{rec['ci95_exact'][0]:.3f}, {rec['ci95_exact'][1]:.3f}] |")
    L += ["", "## Part C: side-by-side Bradley-Terry (owa-glm5 minus sol-research-first)", ""]
    for key, b in c["batches"].items():
        cl, cw, de = b["narrative_clustered_unweighted"], b["narrative_clustered_battle_weighted"], b["contrast_design_effect"]
        L += [f"### {key} ({b['n_narratives']} narratives)", "",
              f"- ratings: owa-glm5 {b['rating_a']['bt']:.1f} [{b['rating_a']['lo']:.1f}, {b['rating_a']['hi']:.1f}], "
              f"sol-research-first {b['rating_b']['bt']:.1f} [{b['rating_b']['lo']:.1f}, {b['rating_b']['hi']:.1f}]; SEs {b['se_a']:.2f}, {b['se_b']:.2f}",
              f"- Wald: diff {b['diff_a_minus_b']:+.1f}, z {b['wald_z']:+.3f}, p {b['wald_p']:.3g}, Holm-2 {b['wald_p_holm_2']:.3g}; "
              f"win probability if 400/log10 Elo scale {b['elo_win_prob_if_400_log10_scale']:.3f}",
              f"- correlation sensitivity: tipping rho {b['tipping_rho']}; at rho=-0.99 z {b['z_at_rho_minus_0.99']:+.2f} (p {b['p_at_rho_minus_0.99']:.3g})",
              f"- narrative-clustered, unweighted: mean {cl['mean']:+.4f}, SE {cl['se']:.4f}, bootstrap-t CI [{cl['ci95'][0]:+.4f}, {cl['ci95'][1]:+.4f}], "
              f"sign-flip p {cl['p_signflip']:.4f}, narratives A/tie/B {cl['wins_ties_losses_narratives']}",
              f"- narrative-clustered, battle-weighted: mean {cw['mean']:+.4f}, CI [{cw['ci95'][0]:+.4f}, {cw['ci95'][1]:+.4f}], sign-flip p {cw['p_signflip']:.4f}",
              f"- contrast design effect: {de['deff']:.3f} (bootstrap CI [{de['ci95_bootstrap'][0]:.2f}, {de['ci95_bootstrap'][1]:.2f}]), "
              f"null-simulation p {de['p_simulated_null']:.3f}; sigma^2 A {de['sigma2_a']:.4f}, B {de['sigma2_b']:.4f}; "
              f"DEFF-adjusted z {b['wald_z_deff_adjusted']:+.3f}, p {b['wald_p_deff_adjusted']:.4f}", ""]
    h = c["heterogeneity"]
    n = h["primary_narrative_battle_score"]
    g = h["bt_diff_of_diffs_common_scale_assumed"]
    L += [f"Between-batch comparison (primary, scale-free): mean per-narrative battle-score difference B1 {n['mean_b1']:+.3f} (n={n['n_b1']}) "
          f"vs B2 {n['mean_b2']:+.3f} (n={n['n_b2']}); difference {n['diff']:+.3f}, two-sample permutation p = {n['p']:.4f}.",
          f"Secondary, **assumes the two separately fitted BT scales are comparable**: difference of rating differences "
          f"{g['diff_of_diffs']:+.1f}, z {g['z']:.3f}, p {g['p']:.3g}. Not used in the paper.", "",
          "## Part D: coverage vs. preference", "", "Mean owa-glm5 minus sol-research-first, with System x Batch interaction (B1 vs B2 manual, two-sample permutation):", "",
          "| metric | B1 mean (n) | B2 manual mean (n) | B2 auto mean (n) | interaction diff | p |", "|---|---|---|---|---|---|"]
    for m, rec in d["glm5_vs_research_first_coverage"].items():
        L.append(f"| {m} | {rec['b1_human']['mean_a_minus_b']:+.4f} ({rec['b1_human']['n']}) | {rec['b2_manual']['mean_a_minus_b']:+.4f} ({rec['b2_manual']['n']}) | "
                 f"{rec['b2_auto']['mean_a_minus_b']:+.4f} ({rec['b2_auto']['n']}) | {rec['interaction_b1_vs_b2manual']['diff']:+.4f} | {rec['interaction_b1_vs_b2manual']['p']:.4f} |")
    L += ["", "Stratified pooled analysis (B1 + B2 manual): see `partD_stratified_pooled.csv`.", ""]
    (out_dir / "statistical-analysis-results.md").write_text("\n".join(L), encoding="utf-8")
    plot_forest(res, out_dir / "forest-all-families.pdf")
    plot_system_intervals(res, out_dir / "system-intervals-all-families.pdf")


def main() -> None:
    import argparse

    repo = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scores-dir", type=Path, default=repo / "RMIT-ADM+S scores")
    ap.add_argument("--out-dir", type=Path, default=repo / "worklogs/assets/2026-11-11-official-stats")
    ap.add_argument("--paper-dir", type=Path, help="also write the paper-ready tables/figures (tables/*.tex, figures/*.pdf) here")
    args = ap.parse_args()
    res = run_statistical_analysis(args.scores_dir)
    print_summary(res)
    write_detailed_outputs(res, args.out_dir)
    if args.paper_dir:
        (args.paper_dir / "tables").mkdir(parents=True, exist_ok=True)
        (args.paper_dir / "figures").mkdir(parents=True, exist_ok=True)
        write_paper_outputs(res, args.paper_dir / "tables", args.paper_dir / "figures")


if __name__ == "__main__":
    main()
