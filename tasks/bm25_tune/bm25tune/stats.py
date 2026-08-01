"""Paired significance tests, effect sizes and bootstrap CIs (PLAN §6.4) — pure stdlib.

No numpy, no scipy — deliberately (PLAN §4.1). The largest vector this module
ever sees is 1063 floats, so a pure-Python t-distribution tail costs microseconds
and the root test env needs no new dependency group. The price is that the two
distribution tails (`t` and `normal`) are implemented here, so both are pinned
against known answers in `tests/bm25_tune/test_stats.py`.

**Why this module carries as much weight as `metrics.py`.** PLAN §3.4 and R1 say
it outright: the judge's grades pile up at 2, so neighbouring grid cells will
differ by a hair. The point estimate alone cannot distinguish "k1=0.7 is better"
from "k1=0.7 got a luckier query sample", and the whole experiment's conclusion
therefore rests on:

- a **paired** test (each query is its own control — same narrative, same qrel,
  same topic-level ideal, so the only thing that changed is the ranking);
- **Bonferroni across the 3 candidate-vs-baseline comparisons**
  (per-comparison alpha = 0.0167), because the candidates were *chosen* on
  Stage A, and testing three of them at 0.05 each buys a ~14 % chance of at
  least one false winner;
- the confirmatory tests running on the **825 held-out queries** (1063 - 238,
  PLAN §5.1 as corrected by WP1) so selection bias is not merely acknowledged
  but excluded — with the full-1063 estimates reported and labeled *descriptive*;
- **effect sizes and CIs, not just p-values** — mean delta, Cohen's d_z, and a
  95 % percentile bootstrap CI (10,000 resamples, seed 13);
- a **topic-level** paired test on per-topic mean deltas (n = 119). Queries
  within a topic share a narrative and a qrel and are therefore correlated; the
  query-level test's n = 825 overstates the independent sample size. PLAN §6.4 is
  explicit that if significance vanishes at topic level, **the topic-level result
  is the honest headline**, and `TestResult.headline_note` is generated to say so
  in the artifact rather than in a reviewer's memory.

Every p-value here is **two-sided**. A one-sided test would be indefensible: the
grid brackets the baseline on both axes and a candidate genuinely worse than the
baseline is a real, reportable outcome.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

#: PLAN §6.4: family-wise alpha and the number of candidate-vs-baseline tests.
#: **This counts candidate CONFIGS, not metrics** — the family is the 3
#: pre-registered candidate-vs-baseline comparisons, and adding a metric column
#: (e.g. the exploratory `gp10`/`p10_bin2`, PLAN §5.5) does not enlarge it. Those
#: metrics are secondary/exploratory by construction, so their p-values are not
#: confirmatory claims and correcting for them would understate the power of the
#: comparisons that are.
FAMILY_ALPHA = 0.05
N_COMPARISONS = 3
#: The per-comparison threshold. Computed, not hardcoded to the plan's rounded
#: 0.0167: the *comparison* is `p <= alpha/m`, and rounding the threshold up
#: would make a p of 0.01668 "significant" when it is not.
BONFERRONI_ALPHA = FAMILY_ALPHA / N_COMPARISONS

#: PLAN §6.4 fixes both: 10,000 resamples, seed 13.
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 13
BOOTSTRAP_CI = 0.95

#: Above this n the Wilcoxon normal approximation is the intended method
#: (PLAN §6.4 says "normal approximation, n > 100"). Below it the approximation
#: is still computed but flagged, because the exact distribution differs
#: materially in small samples and a silently-approximate p-value in a report is
#: worse than a caveated one.
WILCOXON_APPROX_MIN_N = 20


class StatsError(RuntimeError):
    """The inputs cannot support the requested test.

    Raised rather than returning a NaN: a paired test on mismatched query sets,
    or on fewer than two queries, must stop the `stats` subcommand instead of
    writing a well-formed `stats.json` full of nulls that a reader would take at
    face value.
    """


# ---------------------------------------------------------------------------
# Distribution tails (the two functions scipy would otherwise provide)
# ---------------------------------------------------------------------------
def normal_sf(z: float) -> float:
    """Upper tail of the standard normal, `P(Z > z)`, via `math.erfc`.

    `erfc` rather than `1 - cdf` because the latter loses all precision in the
    far tail — exactly where a significant result lives.
    """
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _betacf(a: float, b: float, x: float, *, max_iter: int = 300,
            eps: float = 3e-16) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    raise StatsError(
        f"incomplete beta did not converge for a={a}, b={b}, x={x}")


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta `I_x(a, b)` — the t-distribution's CDF core."""
    if not 0.0 <= x <= 1.0:
        raise StatsError(f"betainc: x must be in [0, 1], got {x}")
    if x in (0.0, 1.0):
        return x
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """Upper tail of Student's t: `P(T > t)` with `df` degrees of freedom.

    Via `I_x(df/2, 1/2)`, which is the closed form scipy uses; pinned against
    `scipy.stats.t` in the tests to 12 decimals.
    """
    if df <= 0:
        raise StatsError(f"t_sf needs df > 0, got {df}")
    half = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return half if t > 0 else 1.0 - half


def t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value for a t statistic."""
    if math.isnan(t):
        raise StatsError("t statistic is NaN")
    return min(1.0, betainc(df / 2.0, 0.5, df / (df + t * t)))


# ---------------------------------------------------------------------------
# Descriptives
# ---------------------------------------------------------------------------
def mean(values: Sequence[float]) -> float:
    if not values:
        raise StatsError("mean of an empty sequence")
    return math.fsum(values) / len(values)


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (ddof=1) — the denominator a paired t needs."""
    n = len(values)
    if n < 2:
        raise StatsError(f"stdev needs n >= 2, got {n}")
    mu = mean(values)
    return math.sqrt(math.fsum((v - mu) ** 2 for v in values) / (n - 1))


def median(values: Sequence[float]) -> float:
    if not values:
        raise StatsError("median of an empty sequence")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def cohens_d(deltas: Sequence[float]) -> float | None:
    """Cohen's `d_z` for paired data: `mean(delta) / sd(delta)`.

    The *paired* d, not the two-sample one: the pairing is the design (PLAN
    §6.4), and using the pooled two-sample sd would understate the effect by
    exactly the between-query correlation the pairing removes — which on this
    data is most of the variance.

    `None` when every delta is identical (sd = 0): the effect is either exactly
    zero or infinite, and neither is a number worth printing.
    """
    if len(deltas) < 2:
        return None
    sd = stdev(deltas)
    if sd == 0.0:
        return None
    return mean(deltas) / sd


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def paired_t_test(deltas: Sequence[float]) -> tuple[float, float, int]:
    """Two-sided one-sample t-test on paired differences.

    Returns `(t, p, df)`. The all-zero case returns `(0.0, 1.0, n-1)` rather
    than raising: two configs that produced identical rankings on every query is
    a real and informative outcome on this data (mode-dominated grades tie
    neighbouring cells), and it must reach the report as "p = 1", not as a crash.
    """
    n = len(deltas)
    if n < 2:
        raise StatsError(f"paired t-test needs n >= 2 pairs, got {n}")
    sd = stdev(deltas)
    df = n - 1
    if sd == 0.0:
        return (0.0, 1.0, df)
    t = mean(deltas) / (sd / math.sqrt(n))
    return (t, t_two_sided_p(t, df), df)


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Ranks 1..n with tied values sharing their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j + 2) / 2.0  # mean of the 1-based ranks i+1..j+1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


@dataclass(frozen=True)
class WilcoxonResult:
    """Wilcoxon signed-rank via the normal approximation (PLAN §6.4)."""

    statistic: float
    z: float
    p_value: float
    n_nonzero: int
    n_zero: int
    tie_correction: float
    approximation_valid: bool

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def wilcoxon_signed_rank(deltas: Sequence[float]) -> WilcoxonResult:
    """Distribution-free companion to the paired t (PLAN §6.4).

    Zero differences are **dropped** before ranking (`trec_eval`-adjacent
    practice and scipy's `zero_method="wilcox"` default), and `n_zero` is
    reported: on mode-dominated grades a large share of queries can tie exactly,
    and a test whose effective n is a third of the query count must say so.

    Ties among the non-zero `|delta|` get average ranks and the variance is
    tie-corrected by `sum(t**3 - t) / 48`. Without that correction the p-value is
    conservative in a way that scales with the tie rate — and the tie rate here
    is high by construction.

    `statistic` is `min(W+, W-)`, matching scipy's `wilcoxon(...)`, so the number
    in `stats.json` is directly checkable against a scipy re-run.
    """
    nonzero = [d for d in deltas if d != 0.0]
    n_zero = len(deltas) - len(nonzero)
    n = len(nonzero)
    if n == 0:
        # Every pair tied: no evidence of a difference in either direction.
        return WilcoxonResult(statistic=0.0, z=0.0, p_value=1.0, n_nonzero=0,
                              n_zero=n_zero, tie_correction=0.0,
                              approximation_valid=False)
    ranks = _average_ranks([abs(d) for d in nonzero])
    w_plus = math.fsum(r for r, d in zip(ranks, nonzero) if d > 0)
    w_minus = math.fsum(r for r, d in zip(ranks, nonzero) if d < 0)
    statistic = min(w_plus, w_minus)

    expected = n * (n + 1) / 4.0
    counts: dict[float, int] = {}
    for rank in ranks:
        counts[rank] = counts.get(rank, 0) + 1
    tie_correction = math.fsum(c ** 3 - c for c in counts.values()) / 48.0
    variance = n * (n + 1) * (2 * n + 1) / 24.0 - tie_correction
    if variance <= 0.0:
        return WilcoxonResult(statistic=statistic, z=0.0, p_value=1.0,
                              n_nonzero=n, n_zero=n_zero,
                              tie_correction=tie_correction,
                              approximation_valid=False)
    z = (statistic - expected) / math.sqrt(variance)
    return WilcoxonResult(statistic=statistic, z=z,
                          p_value=min(1.0, 2.0 * normal_sf(abs(z))),
                          n_nonzero=n, n_zero=n_zero,
                          tie_correction=tie_correction,
                          approximation_valid=n >= WILCOXON_APPROX_MIN_N)


def bootstrap_ci(deltas: Sequence[float], *,
                 resamples: int = BOOTSTRAP_RESAMPLES,
                 seed: int = BOOTSTRAP_SEED,
                 confidence: float = BOOTSTRAP_CI
                 ) -> tuple[float, float, float]:
    """Percentile bootstrap CI of the **mean delta**. Returns `(lo, hi, level)`.

    Resampling is over *queries* (PLAN §6.4) with `random.Random(seed)`, so the
    interval in a committed `stats.json` is reproducible bit-for-bit — which
    matters because a CI that moves between runs cannot be cited.

    A percentile interval rather than BCa: with n >= 825 and a mean statistic the
    bias correction is negligible, and BCa would add an acceleration estimate
    that is far harder to pin in a test than "same seed, same numbers".

    Note this resamples *queries independently*, so like the query-level t-test
    it ignores within-topic correlation. The topic-level test is the companion
    that does not.
    """
    n = len(deltas)
    if n < 2:
        raise StatsError(f"bootstrap needs n >= 2, got {n}")
    if resamples < 1:
        raise StatsError(f"resamples must be >= 1, got {resamples}")
    rng = random.Random(seed)
    values = list(deltas)
    means = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    tail = (1.0 - confidence) / 2.0
    lo = means[_percentile_index(resamples, tail)]
    hi = means[_percentile_index(resamples, 1.0 - tail)]
    return (lo, hi, confidence)


def _percentile_index(n: int, q: float) -> int:
    """Index into a sorted length-`n` list for quantile `q`, clamped in range."""
    return min(n - 1, max(0, int(math.floor(q * n))))


# ---------------------------------------------------------------------------
# One candidate-vs-baseline comparison
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TestResult:
    """Everything PLAN §6.4 requires for one (candidate, baseline, metric) triple.

    Deliberately one flat record: the report needs the p-value, the corrected
    threshold, the effect size, the CI, and the topic-level check *together* —
    quoting any one of them alone is how a mode-dominated null gets written up as
    a win.
    """

    metric: str
    candidate: str
    baseline: str
    query_set: str
    n: int
    candidate_mean: float
    baseline_mean: float
    mean_delta: float
    median_delta: float
    wins: int
    losses: int
    ties: int
    t_statistic: float
    df: int
    p_value: float
    p_bonferroni: float
    alpha_bonferroni: float
    significant: bool
    cohens_d: float | None
    ci_low: float
    ci_high: float
    ci_level: float
    bootstrap_resamples: int
    bootstrap_seed: int
    wilcoxon: WilcoxonResult
    #: Topic-level paired t on per-topic mean deltas (PLAN §6.4's clustering
    #: robustness line). `None` only when fewer than 2 topics are present.
    topic_n: int | None = None
    topic_t_statistic: float | None = None
    topic_p_value: float | None = None
    topic_p_bonferroni: float | None = None
    topic_significant: bool | None = None
    topic_mean_delta: float | None = None
    headline_note: str = ""
    confirmatory: bool = True

    def to_json(self) -> dict[str, object]:
        data = asdict(self)
        data["wilcoxon"] = self.wilcoxon.to_json()
        return data


def bonferroni(p_value: float, comparisons: int = N_COMPARISONS) -> float:
    """Bonferroni-adjusted p: `min(1, p * m)`.

    Adjusting the p-value rather than only the threshold so `stats.json` carries
    a number a reader can compare to 0.05 directly. `significant` is still
    decided by `p <= alpha / m`, which is the identical test.
    """
    return min(1.0, p_value * comparisons)


def _headline_note(significant: bool, topic_significant: bool | None) -> str:
    """PLAN §6.4's clustering rule, written into the artifact.

    The rule ("if query-level significance vanishes at topic level, the
    topic-level result is the honest headline") is a *finding-time* instruction
    that would otherwise live only in the plan. Emitting it next to the numbers
    means the artifact cannot be read without it.
    """
    if topic_significant is None:
        return ("no topic-level test (fewer than 2 topics); the query-level "
                "result is not corrected for within-topic correlation")
    if significant and not topic_significant:
        return ("query-level significant but topic-level NOT — queries within a "
                "topic are correlated, so the topic-level null is the honest "
                "headline (PLAN §6.4)")
    if significant and topic_significant:
        return "significant at both query and topic level"
    if not significant and topic_significant:
        return ("topic-level significant while query-level is not — report both; "
                "the query-level test is the more conservative one here")
    return "no significant difference at either query or topic level"


def compare(candidate_scores: Mapping[str, float],
            baseline_scores: Mapping[str, float], *,
            metric: str, candidate: str, baseline: str,
            query_set: str = "held-out",
            topics: Mapping[str, str] | None = None,
            comparisons: int = N_COMPARISONS,
            resamples: int = BOOTSTRAP_RESAMPLES,
            seed: int = BOOTSTRAP_SEED,
            confidence: float = BOOTSTRAP_CI,
            confirmatory: bool = True) -> TestResult:
    """Run the full PLAN §6.4 battery for one candidate against the baseline.

    Both mappings are `qkey -> metric value` for the *same* query set. A qkey
    present in one and not the other raises: silently intersecting would make
    the reported `n` depend on which config happened to fail on which query, and
    the paired test would no longer be paired.

    `topics` maps `qkey -> topic_id` for the clustering-robustness test; when it
    is omitted the topic is derived from the qkey prefix (`<topic_id>::<hash>`),
    which is `extract.QueryRec.qkey`'s format.
    """
    missing_from_candidate = sorted(set(baseline_scores) - set(candidate_scores))
    missing_from_baseline = sorted(set(candidate_scores) - set(baseline_scores))
    if missing_from_candidate or missing_from_baseline:
        raise StatsError(
            f"{candidate} vs {baseline} on {metric}: the two query sets differ "
            f"({len(missing_from_candidate)} missing from the candidate, "
            f"{len(missing_from_baseline)} from the baseline; e.g. "
            f"{(missing_from_candidate + missing_from_baseline)[:3]}). A paired "
            "test requires identical keys — intersecting them silently would "
            "make n depend on which config failed where.")
    qkeys = sorted(candidate_scores)
    if len(qkeys) < 2:
        raise StatsError(
            f"{candidate} vs {baseline} on {metric}: need >= 2 paired queries, "
            f"got {len(qkeys)}")

    cand = [candidate_scores[k] for k in qkeys]
    base = [baseline_scores[k] for k in qkeys]
    deltas = [c - b for c, b in zip(cand, base)]

    t_stat, p_value, df = paired_t_test(deltas)
    lo, hi, level = bootstrap_ci(deltas, resamples=resamples, seed=seed,
                                 confidence=confidence)
    alpha = FAMILY_ALPHA / comparisons

    topic_of = dict(topics) if topics is not None else {
        k: k.partition("::")[0] for k in qkeys}
    by_topic: dict[str, list[float]] = {}
    for qkey, delta in zip(qkeys, deltas):
        by_topic.setdefault(topic_of.get(qkey, qkey), []).append(delta)
    topic_deltas = [mean(v) for _, v in sorted(by_topic.items())]
    if len(topic_deltas) >= 2:
        topic_t, topic_p, _ = paired_t_test(topic_deltas)
        topic_p_bonf = bonferroni(topic_p, comparisons)
        topic_sig: bool | None = topic_p <= alpha
        topic_mean: float | None = mean(topic_deltas)
        topic_n: int | None = len(topic_deltas)
    else:
        topic_t = topic_p = topic_p_bonf = None  # type: ignore[assignment]
        topic_sig = None
        topic_mean = None
        topic_n = len(topic_deltas) or None

    significant = p_value <= alpha
    return TestResult(
        metric=metric, candidate=candidate, baseline=baseline,
        query_set=query_set, n=len(qkeys),
        candidate_mean=mean(cand), baseline_mean=mean(base),
        mean_delta=mean(deltas), median_delta=median(deltas),
        wins=sum(1 for d in deltas if d > 0),
        losses=sum(1 for d in deltas if d < 0),
        ties=sum(1 for d in deltas if d == 0),
        t_statistic=t_stat, df=df, p_value=p_value,
        p_bonferroni=bonferroni(p_value, comparisons),
        alpha_bonferroni=alpha, significant=significant,
        cohens_d=cohens_d(deltas),
        ci_low=lo, ci_high=hi, ci_level=level,
        bootstrap_resamples=resamples, bootstrap_seed=seed,
        wilcoxon=wilcoxon_signed_rank(deltas),
        topic_n=topic_n, topic_t_statistic=topic_t, topic_p_value=topic_p,
        topic_p_bonferroni=topic_p_bonf,
        topic_significant=topic_sig, topic_mean_delta=topic_mean,
        headline_note=_headline_note(significant, topic_sig),
        confirmatory=confirmatory)


# ---------------------------------------------------------------------------
# The held-out query set (PLAN §6.4)
# ---------------------------------------------------------------------------
def held_out_qkeys(all_qkeys: Sequence[str],
                   subsample_qkeys: Sequence[str]) -> list[str]:
    """The Stage-B confirmatory set: the full set **minus the persisted subsample**.

    Set difference against the *file*, never a re-run of the sampler (PLAN §6.4,
    emphatically). Re-deriving from `seed=13` would silently change the held-out
    set the day `stratified_subsample`'s tie-breaking, sort order, or `per_topic`
    default changes — turning the confirmatory analysis back into the selection
    analysis with no visible symptom.

    Raises if the subsample is not a subset: that means the two files describe
    different query populations, and the "held-out" label would be a lie.
    """
    full = set(all_qkeys)
    sub = set(subsample_qkeys)
    stray = sorted(sub - full)
    if stray:
        raise StatsError(
            f"{len(stray)} subsample qkeys are absent from the full query set "
            f"(e.g. {stray[:3]}) — the two files describe different query "
            "populations, so nothing here is genuinely held out")
    return sorted(full - sub)


def load_qkeys(path: Path) -> list[str]:
    """Read the `qkey` column out of a `queries/*.jsonl` file (PLAN §4.2)."""
    import json

    keys: list[str] = []
    for lineno, line in enumerate(Path(path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StatsError(f"{path}:{lineno}: not valid JSON ({exc})") from exc
        qkey = row.get("qkey")
        if not qkey:
            raise StatsError(f"{path}:{lineno}: no `qkey` field")
        keys.append(str(qkey))
    if not keys:
        raise StatsError(f"{path}: no query rows")
    return keys


# ---------------------------------------------------------------------------
# stats.json
# ---------------------------------------------------------------------------
@dataclass
class StatsReport:
    """The whole `stats.json` payload (PLAN §4.2/§6.4)."""

    run_id: str
    baseline: str
    candidates: list[str]
    metrics: list[str]
    prompt_version: str | None
    family_alpha: float
    n_comparisons: int
    alpha_bonferroni: float
    bootstrap_resamples: int
    bootstrap_seed: int
    query_sets: dict[str, int]
    #: The confirmatory tests (held-out queries) — the ones that carry inference.
    confirmatory: list[TestResult] = field(default_factory=list)
    #: Full-1063 point estimates. Reported, and labeled descriptive, because the
    #: candidates were selected on a subset of these very queries (PLAN §6.4).
    descriptive: list[TestResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        data = asdict(self)
        data["confirmatory"] = [r.to_json() for r in self.confirmatory]
        data["descriptive"] = [r.to_json() for r in self.descriptive]
        return data


#: Goes into every `stats.json` so the interpretation rules travel with the
#: numbers instead of living only in PLAN §6.4.
STANDING_NOTES: tuple[str, ...] = (
    "p-values are two-sided paired t-tests on per-query metric deltas "
    "(candidate - baseline); `significant` is `p <= family_alpha / "
    "n_comparisons` (Bonferroni across the candidate-vs-baseline comparisons).",
    "`confirmatory` uses the held-out queries only — the candidates were "
    "SELECTED on the Stage-A subsample, so tests on those queries are biased "
    "upward. `descriptive` covers the full query set and must be labeled "
    "descriptive wherever it is quoted (PLAN §6.4).",
    "The held-out set is the full query file MINUS the persisted subsample "
    "file, by set difference — never recomputed from the seed.",
    "Metric values are deflated by the topic-level ideal DCG (see metrics.py); "
    "only differences between configs are interpretable, which is what these "
    "paired tests measure.",
    "Queries within a topic share a narrative and a qrel and are correlated. "
    "Where `significant` and `topic_significant` disagree, PLAN §6.4 makes the "
    "topic-level result the honest headline; `headline_note` states which case "
    "each comparison is in.",
    "`gp10` and `p10_bin2` (added 2026-07-31, PLAN §5.5) are "
    "SECONDARY/EXPLORATORY: they are not in PLAN §3.3's pre-registered family, "
    "so a p-value quoted for either is exploratory and must say so. They are "
    "tested here only so that re-optimizing the grid for them later needs no "
    "re-judging and no re-run. `n_comparisons` counts candidate CONFIGS, not "
    "metrics, so the Bonferroni divisor is unaffected by their presence.",
)


def build_report(*, run_id: str, baseline: str, candidates: Sequence[str],
                 metrics: Sequence[str], prompt_version: str | None,
                 per_config: Mapping[str, Mapping[str, Mapping[str, float]]],
                 held_out: Sequence[str], full: Sequence[str],
                 topics: Mapping[str, str] | None = None,
                 resamples: int = BOOTSTRAP_RESAMPLES,
                 seed: int = BOOTSTRAP_SEED) -> StatsReport:
    """Assemble the full report: every candidate x metric, held-out and full.

    `per_config[config][metric][qkey] -> value` — the shape `metrics.score_all`
    produces. Queries whose metric is `None` (undefined for the topic, see
    `metrics.py`) must already be excluded by the caller; a comparison drops any
    qkey missing from *either* config for that metric, and records the resulting
    `n` in the result, so the exclusion is auditable.
    """
    if baseline not in per_config:
        raise StatsError(
            f"baseline config {baseline!r} has no scores; available: "
            f"{sorted(per_config)}")
    missing = [c for c in candidates if c not in per_config]
    if missing:
        raise StatsError(f"candidate config(s) {missing} have no scores")

    comparisons = max(1, len(candidates))
    report = StatsReport(
        run_id=run_id, baseline=baseline, candidates=list(candidates),
        metrics=list(metrics), prompt_version=prompt_version,
        family_alpha=FAMILY_ALPHA, n_comparisons=comparisons,
        alpha_bonferroni=FAMILY_ALPHA / comparisons,
        bootstrap_resamples=resamples, bootstrap_seed=seed,
        query_sets={"held_out": len(held_out), "full": len(full)},
        notes=list(STANDING_NOTES))

    for label, qkeys, confirmatory in (("held-out", held_out, True),
                                       ("full", full, False)):
        if len(qkeys) < 2:
            continue
        for metric in metrics:
            base_all = per_config[baseline].get(metric, {})
            for candidate in candidates:
                cand_all = per_config[candidate].get(metric, {})
                keys = [k for k in qkeys if k in base_all and k in cand_all]
                if len(keys) < 2:
                    continue
                result = compare(
                    {k: cand_all[k] for k in keys},
                    {k: base_all[k] for k in keys},
                    metric=metric, candidate=candidate, baseline=baseline,
                    query_set=label, topics=topics, comparisons=comparisons,
                    resamples=resamples, seed=seed, confirmatory=confirmatory)
                (report.confirmatory if confirmatory
                 else report.descriptive).append(result)
    return report


def summary_lines(report: StatsReport, metric: str | None = None) -> list[str]:
    """`[SUMMARY]`-prefixed log lines for the confirmatory tests (PLAN §5.6)."""
    lines = [f"[SUMMARY] stats run_id={report.run_id} baseline={report.baseline} "
             f"alpha_bonferroni={report.alpha_bonferroni:.4f} "
             f"held_out_n={report.query_sets.get('held_out')} "
             f"full_n={report.query_sets.get('full')}"]
    for result in report.confirmatory:
        if metric is not None and result.metric != metric:
            continue
        lines.append(
            f"[SUMMARY] {result.metric} {result.candidate} vs "
            f"{result.baseline} ({result.query_set}, n={result.n}): "
            f"delta={result.mean_delta:+.4f} "
            f"CI=[{result.ci_low:+.4f}, {result.ci_high:+.4f}] "
            f"p={result.p_value:.4g} p_bonf={result.p_bonferroni:.4g} "
            f"d={'na' if result.cohens_d is None else f'{result.cohens_d:+.3f}'} "
            f"wilcoxon_p={result.wilcoxon.p_value:.4g} "
            f"topic_p={'na' if result.topic_p_value is None else f'{result.topic_p_value:.4g}'} "
            f"{'SIGNIFICANT' if result.significant else 'ns'}")
    return lines
