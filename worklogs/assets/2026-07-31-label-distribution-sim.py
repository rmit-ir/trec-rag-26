#!/usr/bin/env python3
"""Does the judge's grade distribution cost the experiment discriminative power?

Written to check a claim this plan had already committed: that a lenient
("saturated") judge compresses nDCG@10's dynamic range and therefore hides
differences between BM25 configs. Three probes, run in this order, because each
one falsified the previous framing:

  probe 1 `mean_abs_delta(rank_corr=False)` — the ORIGINAL simulation. Grades
      assigned to pool candidates at RANDOM, independent of retrieval rank. Shows
      mean |dnDCG@10| falling monotonically as labels get more lenient, which is
      the result the plan cited.

  probe 2 `mean_abs_delta(rank_corr=True)` — the same thing with grades
      CORRELATED to rank (candidates are sorted by grade plus noise, i.e. a real
      retrieval system). The ordering REVERSES: the harshest distribution
      (umbrela-v1-like) now shows the LARGEST mean |d|. Diagnosis: mean |d| is a
      spread statistic, so it rises with label variance whether or not that
      variance carries signal. It is the wrong quantity.

  probe 3 `power()` — what the experiment actually needs: how often a paired
      t-test at the plan's Bonferroni alpha detects a config that is GENUINELY
      better (ranks by true relevance with less noise than its rival). Run at
      both scales the plan uses. This is the probe the conclusion rests on.

Conclusion (PLAN §3.3b Finding 3): the label distribution is not the binding
constraint on power -- sample size and effect size are. The gate's leniency
ceiling is justified only by the degenerate corner (~98 % relevant), where IDCG
converges on DCG and nDCG@10 approaches 1 for every config.

Run from the repo root:
    uv run --no-project python worklogs/assets/2026-07-31-label-distribution-sim.py
"""
from __future__ import annotations

import math
import random
import statistics

#: Every distribution the plan makes a claim about. Values are shares per grade.
CASES = {
    "umbrela-v1 measured {18,72,5,5}": {0: .175, 1: .725, 2: .050, 3: .050},
    "base-rate-like {45,30,20,5}": {0: .45, 1: .30, 2: .20, 3: .05},
    "on-target {32,28,29,11}": {0: .32, 1: .28, 2: .29, 3: .107},
    "hand-read, pool-wt {14,20,40,25}": {0: .144, 1: .203, 2: .402, 3: .250},
    "facet-v1 measured {12,13,60,15}": {0: .117, 1: .133, 2: .600, 3: .150},
    "hand-read, sample-wt {11,16,40,33}": {0: .109, 1: .160, 2: .403, 3: .328},
    "saturated {1,1,50,48}": {0: .01, 1: .01, 2: .50, 3: .48},
}

#: PLAN §3.3's Bonferroni correction is 0.05/3 (three candidate CONFIGS); the
#: two-sided critical t at that alpha is ~2.79 at these degrees of freedom.
T_CRIT = 2.79


def ndcg10(grades: list[int]) -> float | None:
    """Exponential-gain nDCG@10, matching `bm25tune.metrics`. None if IDCG == 0."""
    dcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades[:10]))
    ideal = sorted(grades, reverse=True)[:10]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else None


def _bag(dist: dict[int, float]) -> list[int]:
    bag: list[int] = []
    for grade, share in dist.items():
        bag += [grade] * int(round(share * 1000))
    return bag


def mean_abs_delta(dist, seed, *, rank_corr, ntopic=400, pool=30, overlap=0.8):
    """Probes 1 and 2: mean |dnDCG@10| between two configs over a shared pool.

    `rank_corr=False` is the original framing (grades independent of rank);
    `rank_corr=True` is the realistic one (better documents rank higher, with
    noise). The two disagree in DIRECTION, which is the point.
    """
    rng = random.Random(seed)
    bag = _bag(dist)
    deltas = []
    for _ in range(ntopic):
        grades = [rng.choice(bag) for _ in range(pool)]
        if rank_corr:
            order = sorted(range(pool),
                           key=lambda i: -(grades[i] + rng.gauss(0, 1.4)))
        else:
            order = list(range(pool))
            rng.shuffle(order)
        a = order[:10]
        keep = int(round(overlap * 10))
        b = a[:keep] + [i for i in order[10:] if i not in a][:10 - keep]
        rng.shuffle(b)
        na, nb = ndcg10([grades[i] for i in a]), ndcg10([grades[i] for i in b])
        if na is not None and nb is not None:
            deltas.append(abs(na - nb))
    return statistics.mean(deltas)


def power(dist, seed, *, ntopic, quality, nsim):
    """Probe 3: P(detect a genuinely better ranker) at the plan's alpha.

    Config A ranks by true relevance with noise sd 1.0; config B with sd
    1.0+`quality`, so A is really better and any failure to detect is a Type II
    error. Returns (power, mean Cohen's d, mean share of usable topics) — the
    last because a degenerate label set can make IDCG zero and drop topics.
    """
    rng = random.Random(seed)
    bag = _bag(dist)
    wins = 0
    effects, usable = [], []
    for _ in range(nsim):
        deltas = []
        for _ in range(ntopic):
            grades = [rng.choice(bag) for _ in range(30)]
            oa = sorted(range(30),
                        key=lambda i: -(grades[i] + rng.gauss(0, 1.0)))[:10]
            ob = sorted(range(30),
                        key=lambda i: -(grades[i] + rng.gauss(0, 1.0 + quality))
                        )[:10]
            na = ndcg10([grades[i] for i in oa])
            nb = ndcg10([grades[i] for i in ob])
            if na is None or nb is None:
                continue
            deltas.append(na - nb)
        usable.append(len(deltas) / ntopic)
        if len(deltas) < 3:
            continue
        mean, sd = statistics.mean(deltas), statistics.stdev(deltas)
        effects.append(mean / sd if sd else 0.0)
        if sd and abs(mean / (sd / math.sqrt(len(deltas)))) > T_CRIT:
            wins += 1
    return wins / nsim, statistics.mean(effects), statistics.mean(usable)


def main() -> None:
    print("PROBES 1+2 — mean |dnDCG@10|, two configs sharing 80 % of their top-10")
    print(f"{'distribution':38s} {'>=2':>5} {'=3':>5} | "
          f"{'rank-corr':>9} {'random':>8}")
    for name, dist in CASES.items():
        corr = mean_abs_delta(dist, 7, rank_corr=True)
        rand = mean_abs_delta(dist, 7, rank_corr=False)
        print(f"{name:38s} {dist[2] + dist[3]:5.2f} {dist[3]:5.2f} | "
              f"{corr:9.4f} {rand:8.4f}")
    print("  ^ the two columns rank the distributions in OPPOSITE orders, so "
          "mean |d| is\n    measuring label variance, not discriminative power.")

    print("\nPROBE 3 — power to detect a genuinely better ranker, alpha = 0.05/3")
    for scale, (ntopic, quality, nsim) in {
            "WP8 full run, LARGE effect (n=825, gap 0.30)": (825, 0.30, 120),
            "pilot scale, SMALL effect (n=119, gap 0.06)": (119, 0.06, 200),
    }.items():
        print(f"\n  {scale}")
        print(f"  {'distribution':38s} {'>=2':>5} | {'power':>6} "
              f"{'Cohen d':>8} {'usable':>7}")
        for name, dist in CASES.items():
            p, d, u = power(dist, 11, ntopic=ntopic, quality=quality, nsim=nsim)
            print(f"  {name:38s} {dist[2] + dist[3]:5.2f} | {p:6.2f} "
                  f"{d:8.3f} {u:6.1%}")
    print("\n  ^ power is ~1.00 for EVERY distribution at the large effect and "
          "<=0.03 for\n    every one at the small effect. Sample size and effect "
          "size bind; the label\n    distribution does not.")


if __name__ == "__main__":
    main()
