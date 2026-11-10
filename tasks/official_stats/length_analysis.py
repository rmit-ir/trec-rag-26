"""Exploratory answer-length analysis (hypothesis generating; not part of the paper's confirmatory tests).

Question: does answer length help explain why humans preferred ``owa-glm5`` over ``sol-research-first`` in
Batch 1 while LLM-judged coverage favors ``sol-research-first`` in both batches, and does length track
coverage across all seven runs?

Raw answers are NOT stored in this repo. Pass one submission JSONL per run (``--run tag=path``); the script
writes only per-narrative counts (words, sentences, references) to ``<out-dir>/length-per-narrative.csv`` and
the results to ``<out-dir>/length-analysis.md``. Word count = whitespace tokens in the ``answer`` sentences.

Usage:
  python3 scripts/length_analysis.py --run brief-base-t119=/path/rag_output_trec_rag_2026.jsonl ... \
      [--scores-dir <code-repo>/'RMIT-ADM+S scores']
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import statistical_analysis as sa

SEED = 2026
N_PERM = 100_000


def load_counts(runs: dict[str, Path]) -> pd.DataFrame:
    rows = []
    for tag, path in runs.items():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                text = " ".join(s["text"] for s in rec["answer"])
                rows.append(
                    {
                        "run": tag,
                        "narrative-id": rec["metadata"]["narrative_id"],
                        "words": len(text.split()),
                        "sentences": len(rec["answer"]),
                        "references": len(rec["references"]),
                    }
                )
    df = pd.DataFrame(rows)
    assert df.groupby("run")["narrative-id"].nunique().eq(119).all(), "each run must cover 119 narratives"
    return df


def perm_spearman(x: np.ndarray, y: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    rho = float(stats.spearmanr(x, y).statistic)
    ry = stats.rankdata(y)
    rx = stats.rankdata(x)
    cnt = 0
    for _ in range(N_PERM // 10_000):
        perm = np.argsort(rng.random((10_000, len(y))), axis=1)
        r_perm = np.array([np.corrcoef(rx, ry[p])[0, 1] for p in perm])
        cnt += int(np.sum(np.abs(r_perm) >= abs(rho) - 1e-12))
    return {"rho": rho, "p_perm": (cnt + 1) / (N_PERM + 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", type=Path, help="reuse <out-dir>/length-per-narrative.csv instead of raw submissions")
    ap.add_argument("--run", action="append", default=[], help="tag=path/to/rag_output_trec_rag_2026.jsonl")
    ap.add_argument("--scores-dir", type=Path, default=Path(__file__).resolve().parents[2] / "RMIT-ADM+S scores")
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parents[2] / "worklogs/assets/2026-11-11-official-stats")
    ap.add_argument("--tables-dir", type=Path, default=None, help="default: <out-dir>/tables")
    args = ap.parse_args()
    runs = {r.split("=", 1)[0]: Path(r.split("=", 1)[1]) for r in args.run}
    rng = np.random.default_rng(SEED)
    df = pd.read_csv(args.counts) if args.counts else load_counts(runs)
    if args.counts:
        runs = {t: None for t in df.run.unique()}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out_dir / "length-per-narrative.csv", index=False)
    L: list[str] = ["# Exploratory answer-length analysis", "",
                    "Hypothesis-generating only (n = 17 and 25 narratives; one judge; unknown SxS opponents).", ""]

    # 1. descriptives
    desc = df.groupby("run")[["words", "sentences", "references"]].agg(["mean", "median"]).round(1)
    L += ["## Descriptives (119 narratives)", "", desc.to_markdown(), ""]

    wide_w = df.pivot(index="narrative-id", columns="run", values="words")
    A, B = sa.SXS_A, sa.SXS_B
    ratio = np.log(wide_w[A] / wide_w[B])
    L += [f"Median words {A} / {B}: {float(np.exp(ratio.median())):.3f}; "
          f"{A} shorter on {int((ratio < 0).sum())} of 119 narratives.", ""]

    # 2. SxS two runs: per-narrative preference and coverage differences vs log length ratio
    L += [f"## {A} minus {B}: per-narrative differences vs. log(words ratio)", "",
          "| batch | outcome | n | Spearman rho | permutation p | Holm p (4 outcomes per batch) | OLS slope on log ratio | intercept (A ahead at equal length?) 95% bootstrap CI |",
          "|---|---|---|---|---|---|---|---|"]
    records = []
    for batch, key, cov_file in ((1, "b1_human", "rag-rubric-scores-batch1-human.tsv"), (2, "b2_manual", "rag-nugget-scores-batch2-manual.tsv")):
        _, per = sa._load_sxs(args.scores_dir, batch)
        ids = per[A + ":ids"]
        ca, cb = per[A], per[B]
        pref = (ca[:, 0] + 0.5 * ca[:, 1]) / ca.sum(1) - (cb[:, 0] + 0.5 * cb[:, 1]) / cb.sum(1)
        x = ratio.reindex(ids).to_numpy()
        outcomes = {"SxS battle-score diff": pref}
        batch_rows = []
        for metric in sa.METRICS:
            Y, _, _ = sa.load_family(args.scores_dir, cov_file, metric)
            outcomes[f"coverage {metric} diff"] = (Y[A] - Y[B]).reindex(ids).to_numpy()
        for name, y in outcomes.items():
            ok = ~np.isnan(y) & ~np.isnan(x)
            xx, yy = x[ok], y[ok]
            sp = perm_spearman(xx, yy, rng)
            slope, icpt = np.polyfit(xx, yy, 1)
            boots = []
            for _ in range(5000):
                i = rng.integers(0, len(xx), len(xx))
                if np.ptp(xx[i]) > 0:
                    boots.append(np.polyfit(xx[i], yy[i], 1)[1])
            lo, hi = np.quantile(boots, [0.025, 0.975])
            batch_rows.append((name, len(xx), sp, slope, icpt, lo, hi))
        hp = sa.holm(np.array([r[2]["p_perm"] for r in batch_rows]))  # Holm within the batch's family of outcomes
        for (name, n, sp, slope, icpt, lo, hi), h in zip(batch_rows, hp):
            L.append(f"| B{batch} | {name} | {n} | {sp['rho']:+.3f} | {sp['p_perm']:.3f} | {h:.3f} | {slope:+.3f} | {icpt:+.3f} [{lo:+.3f}, {hi:+.3f}] |")
            records.append({"batch": batch, "outcome": name, "n": n, **sp, "p_holm": h, "slope": slope, "intercept": icpt})
    L.append("")

    # 3. all runs: within-narrative association of length and coverage
    L += ["## All runs: within-narrative Spearman between words and coverage", "",
          "Mean over narratives of the rank correlation across the runs available in that collection; p from permuting run labels of "
          "the length vector within each narrative (stat = mean within-narrative Spearman).", "",
          "| collection | metric | runs | narratives | mean within-narrative rho | permutation p | Holm p (all rows) |", "|---|---|---|---|---|---|---|"]
    sec3 = []
    tags = [t for t in sa.RUN_ORDER if t in runs]
    for key, fname in sa.COLLECTIONS:
        for metric in sa.METRICS:
            Y, _, _ = sa.load_family(args.scores_dir, fname, metric)
            ids = Y.index
            W = wide_w.loc[ids, tags].to_numpy(float)
            C = Y[tags].to_numpy(float)

            def stat(Wm: np.ndarray) -> float:
                rs = [stats.spearmanr(Wm[i], C[i]).statistic for i in range(len(ids)) if np.ptp(C[i]) > 0 and np.ptp(Wm[i]) > 0]
                return float(np.mean(rs))

            obs = stat(W)
            cnt = 0
            n_perm = 5000
            for _ in range(n_perm):
                Wp = np.array([rng.permutation(w) for w in W])
                cnt += abs(stat(Wp)) >= abs(obs) - 1e-12
            sec3.append((key, metric, len(ids), obs, (cnt + 1) / (n_perm + 1)))
    hp = sa.holm(np.array([r[4] for r in sec3]))
    for (key, metric, n, obs, pv), h in zip(sec3, hp):
        L.append(f"| {key} | {metric} | {len(tags)} | {n} | {obs:+.3f} | {pv:.4f} | {h:.4f} |")
    L.append("")

    # 4. run level
    L += ["## Run level (n = 7 runs, descriptive)", "", "| run | mean words | B1 all | B2 manual all | B2 auto all |", "|---|---|---|---|---|"]
    cov = {}
    for key, fname in sa.COLLECTIONS:
        Y, _, _ = sa.load_family(args.scores_dir, fname, "all_strict")
        cov[key] = Y.mean()
    for t in tags:
        L.append(f"| {t} | {df[df.run == t].words.mean():.0f} | {cov['b1_human'][t]:.3f} | {cov['b2_manual'][t]:.3f} | {cov['b2_auto'][t]:.3f} |")
    mw = df.groupby("run").words.mean().reindex(tags)
    for key in cov:
        L.append("")
        L.append(f"Spearman(mean words, {key} all_strict) over {len(tags)} runs = {stats.spearmanr(mw, cov[key][tags]).statistic:+.3f}")
    # paper table: mean words and all_strict coverage per run; last row = within-narrative Spearman (Holm p over 6 rows)
    from statistical_analysis import _short
    rho = {(k, m): (o, h) for (k, m, n, o, pv), h in zip(sec3, sa.holm(np.array([r[4] for r in sec3])))}
    order = sorted(tags, key=lambda t: -mw[t])
    rows = [f"\\texttt{{{_short(t)}}} & {mw[t]:.0f} & {cov['b1_human'][t]:.3f} & {cov['b2_manual'][t]:.3f} & {cov['b2_auto'][t]:.3f} \\\\" for t in order]
    def cell(k):
        o, h = rho[(k, "all_strict")]
        return f"${o:+.2f}$ ({'$<$0.001' if h < 0.001 else f'{h:.3f}'})"
    rows += [r"\midrule", f"Within-narrative $\\rho$ (Holm $p$) & & {cell('b1_human')} & {cell('b2_manual')} & {cell('b2_auto')} \\\\"]
    args.tables_dir = args.tables_dir or args.out_dir / "tables"
    args.tables_dir.mkdir(parents=True, exist_ok=True)
    (args.tables_dir / "length-coverage.tex").write_text("\n".join([
        r"\begin{tabular}{@{}lrccc@{}}", r"\toprule",
        r"Run & Mean words & B1 all\_strict & B2 manual all\_strict & B2 auto all\_strict \\", r"\midrule",
        *rows, r"\bottomrule", r"\end{tabular}", ""]), encoding="utf-8")

    # 5. all-pairs differences in length across runs: Tukey HSD from the narrative-blocked two-way ANOVA
    L += ["", "## All-pairs length differences (Tukey HSD, narrative blocks)", "",
          "Two-way ANOVA (run + narrative), balanced, so Tukey HSD with MSE df = (k-1)(N-1); log(words) used so differences are ratios. "
          "Pairs listed with adjusted p < 0.05 only.", ""]
    from scipy.stats import studentized_range
    lw = np.log(wide_w[tags].to_numpy(float))
    N_, k_ = lw.shape
    resid = lw - lw.mean(1, keepdims=True) - lw.mean(0, keepdims=True) + lw.mean()
    mse = float((resid ** 2).sum() / ((k_ - 1) * (N_ - 1)))
    se = np.sqrt(mse / N_)
    L += ["| run A | run B | ratio of mean words (geometric) | Tukey p |", "|---|---|---|---|"]
    n_sig = 0
    for i in range(k_):
        for j in range(i + 1, k_):
            d = lw[:, i].mean() - lw[:, j].mean()
            pv = float(studentized_range.sf(abs(d) / se, k_, (k_ - 1) * (N_ - 1)))
            if pv < 0.05:
                n_sig += 1
                L.append(f"| {tags[i]} | {tags[j]} | {np.exp(d):.2f} | {pv:.4f} |")
    L += ["", f"{n_sig} of {k_ * (k_ - 1) // 2} pairs significant at 0.05 (Tukey)."]
    (args.out_dir / "length-analysis.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
