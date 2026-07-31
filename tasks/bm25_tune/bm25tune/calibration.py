"""WP6's gate and report — the mandatory decision layer before any sweep spend (PLAN §3.3).

This module is deliberately **pure**: it takes grade counts and per-pair records
and returns verdicts and markdown. Nothing here calls Bedrock, reads a config, or
touches the network. That split is the point — the gate is the one piece of the
harness whose *decision* must be reproducible from the numbers alone, so a
reviewer can re-derive "should the sweep have launched?" from
`calibration/report.md` without re-spending $0.23, and so every bound can be
driven by a synthetic distribution in a test.

**The gate is a floor on usability, not the selection criterion.** Several
variants can pass; among those that do, §3.3's decision rule picks the lowest
modal share, tie-broken by AUC. A gate pass does not make a variant the winner
and the user confirms the choice before WP7 launches.

Two traps this module exists to avoid:

- **The one-sided gate (fixed 2026-07-31).** The original three conditions
  admitted `{0:1, 1:1, 2:50, 3:48}` — 98 % of pairs relevant — because nothing
  bounded leniency. Conditions 3 and 4 are two-sided now, and
  `test_calibration.py` pins that exact distribution as a FAIL.
- **Reading agent-label agreement as accuracy.** It is a *staging* decision:
  **[measured]** 93.9 % of rejected keyword hits come from a query that committed
  something else, and 53 % of hand-read rejected passages were still grade >=2
  (PLAN §3.3b). `agent_agreement` therefore reports ordering and AUC and the
  report prints the caveat next to them, because a judge scoring well above the
  agent's 23.8 % positive rate is *expected*, not a red flag.

Every bound is **inclusive** — `facet-v1`'s measured modal share is exactly
0.600, so a strict `<` would flip the going-in candidate on a rounding convention
rather than on evidence.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from . import prompts
from .metrics import GRADE_MAX, GRADE_MIN

# ---------------------------------------------------------------------------
# Gate constants (PLAN §3.3's "gate constants are code, not prose" contract).
# Defined once here and imported everywhere; `calibrate` must never re-key them.
# ---------------------------------------------------------------------------
#: A judge that puts more than this share on one grade is mode-dominated.
#: Relaxed from 0.50 — neither measured variant meets that and a flat
#: distribution is not realistic.
GATE_MAX_MODAL_SHARE = 0.60
#: Below this share at grade >=2 there are too few relevant chunks to separate
#: configs (`umbrela-v1`'s measured 0.10 fails here).
GATE_MIN_SHARE_GE2 = 0.20
#: Above this, IDCG converges on DCG and nDCG@10 -> 1 for every config. Widened
#: from 0.65 on 2026-07-31: a hand-read of 22 real hits reweighted to the pool
#: gives 0.653, and a gate that rejects a careful human reading of the data is
#: measuring its own assumptions (PLAN §3.3b Finding 2).
GATE_MAX_SHARE_GE2 = 0.90
#: Grade 3 should stay uncommon. Widened from 0.25 for the same reason (the
#: hand-read gives 0.250, exactly on the old bound).
GATE_MAX_SHARE_EQ3 = 0.50
#: A judge that never uses a grade has an effectively smaller scale.
GATE_REQUIRE_ALL_GRADES = True

#: Stability probe: re-judge this many pairs of the winner and require this
#: exact-match rate (PLAN §3.3). The probe MUST bypass the cache or it trivially
#: reports 1.00.
STABILITY_PROBE_PAIRS = 50
STABILITY_MIN_MATCH_RATE = 0.90

#: Observed label mix over all 8580 (topic, chunk) pairs — the basis for
#: reweighting a sample share back onto the pool. **[measured]**
POOL_LABEL_MIX: dict[str, int] = {"positive": 2368, "negative": 6638,
                                  "unjudged": 202}

#: Condition ids, in report order. Stable strings because the report, the log
#: lines, and the tests all key off them.
COND_MODAL = "modal_share"
COND_ALL_GRADES = "all_grades_used"
COND_SHARE_GE2 = "share_ge2"
COND_SHARE_EQ3 = "share_eq3"
CONDITION_ORDER = (COND_MODAL, COND_ALL_GRADES, COND_SHARE_GE2, COND_SHARE_EQ3)

#: Human-readable statement of each bound, for the report and failure messages.
CONDITION_LABELS: dict[str, str] = {
    COND_MODAL: f"modal grade share <= {GATE_MAX_MODAL_SHARE:.2f}",
    COND_ALL_GRADES: "all four grades used (each >= 1 pair)",
    COND_SHARE_GE2: (f"{GATE_MIN_SHARE_GE2:.2f} <= share at grade >=2 "
                     f"<= {GATE_MAX_SHARE_GE2:.2f}"),
    COND_SHARE_EQ3: f"share at grade 3 <= {GATE_MAX_SHARE_EQ3:.2f}",
}

GRADES: tuple[int, ...] = tuple(range(GRADE_MIN, GRADE_MAX + 1))


class CalibrationError(RuntimeError):
    """Raised for a malformed distribution or an empty calibration set.

    Hard failure rather than a default: silently treating an empty count map as
    "all zeros" would render a report whose every condition reads FAIL for a run
    that simply never judged anything, and the operator would go hunting the
    prompt instead of the driver.
    """


def _normalize_counts(counts: Mapping[int, int]) -> dict[int, int]:
    """Validate and fill a grade histogram to all four grades."""
    out = {g: 0 for g in GRADES}
    for grade, count in counts.items():
        try:
            g = int(grade)
        except (TypeError, ValueError):
            raise CalibrationError(f"non-integer grade key {grade!r}") from None
        if g not in out:
            raise CalibrationError(
                f"grade {g} outside {GRADE_MIN}-{GRADE_MAX}")
        if count < 0:
            raise CalibrationError(f"negative count for grade {g}: {count}")
        out[g] += int(count)
    if sum(out.values()) == 0:
        raise CalibrationError(
            "empty grade distribution — nothing was judged, so the gate would "
            "report four spurious failures")
    return out


@dataclass(frozen=True)
class Condition:
    """One gate condition's verdict, with the number and the bound it met or missed.

    `direction` is the whole reason this is a dataclass rather than a bool:
    "gated" does not tell an operator whether to reach for a stricter or a looser
    prompt, and those are opposite actions.
    """

    name: str
    passed: bool
    observed: float
    #: `"low"` if the observed value fell below a floor, `"high"` if it exceeded a
    #: ceiling, `None` when the condition passed.
    direction: str | None = None
    bound: float | None = None

    @property
    def label(self) -> str:
        return CONDITION_LABELS[self.name]

    def describe(self) -> str:
        """One-line verdict for the report and the `[GATE]` log lines."""
        verdict = "PASS" if self.passed else "FAIL"
        text = f"{verdict}  {self.label} — observed {self.observed:.3f}"
        if not self.passed and self.bound is not None:
            text += (f", {'below' if self.direction == 'low' else 'above'} "
                     f"{self.bound:.3f}")
        return text


@dataclass(frozen=True)
class GateResult:
    """Per-condition verdicts plus the derived shares, for one prompt variant."""

    counts: dict[int, int]
    conditions: tuple[Condition, ...]
    n: int
    modal_grade: int
    modal_share: float
    share_ge2: float
    share_eq3: float
    entropy: float

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.conditions)

    @property
    def failures(self) -> tuple[Condition, ...]:
        return tuple(c for c in self.conditions if not c.passed)

    def failed_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.failures)

    def distance_from_band(self) -> float:
        """How far outside condition 3's band the variant fell, 0.0 if inside.

        PLAN §3.3's fallback ranking: when *no* variant passes, the report must
        name the least-bad candidate rather than just declaring "no pass", and
        this is the primary key for that (lowest modal share breaks ties).
        """
        if self.share_ge2 < GATE_MIN_SHARE_GE2:
            return GATE_MIN_SHARE_GE2 - self.share_ge2
        if self.share_ge2 > GATE_MAX_SHARE_GE2:
            return self.share_ge2 - GATE_MAX_SHARE_GE2
        return 0.0


def grade_entropy(counts: Mapping[int, int]) -> float:
    """Shannon entropy of the grade distribution, in bits (max 2.0 over 4 grades).

    Reported alongside modal share because the two catch different degeneracies:
    `{0:50, 3:50}` has a healthy 0.50 modal share but uses only half the scale,
    and a judge that never distinguishes 1 from 2 is not measuring what nDCG's
    exponential gain assumes.
    """
    filled = _normalize_counts(counts)
    total = sum(filled.values())
    out = 0.0
    for count in filled.values():
        if count:
            p = count / total
            out -= p * math.log2(p)
    return out


def evaluate_gate(counts: Mapping[int, int]) -> GateResult:
    """Apply PLAN §3.3's four conditions to one variant's grade histogram.

    All bounds inclusive. Returns per-condition verdicts rather than a bool so
    the report can say *which* bound was missed and in which direction.
    """
    filled = _normalize_counts(counts)
    n = sum(filled.values())
    modal_grade = max(GRADES, key=lambda g: (filled[g], -g))
    modal_share = filled[modal_grade] / n
    share_ge2 = (filled[2] + filled[3]) / n
    share_eq3 = filled[3] / n

    conditions = (
        Condition(COND_MODAL, modal_share <= GATE_MAX_MODAL_SHARE, modal_share,
                  None if modal_share <= GATE_MAX_MODAL_SHARE else "high",
                  GATE_MAX_MODAL_SHARE),
        Condition(
            COND_ALL_GRADES,
            (not GATE_REQUIRE_ALL_GRADES
             or all(filled[g] > 0 for g in GRADES)),
            float(sum(1 for g in GRADES if filled[g] > 0)),
            None if all(filled[g] > 0 for g in GRADES) else "low",
            float(len(GRADES)),
        ),
        _band_condition(COND_SHARE_GE2, share_ge2, GATE_MIN_SHARE_GE2,
                        GATE_MAX_SHARE_GE2),
        Condition(COND_SHARE_EQ3, share_eq3 <= GATE_MAX_SHARE_EQ3, share_eq3,
                  None if share_eq3 <= GATE_MAX_SHARE_EQ3 else "high",
                  GATE_MAX_SHARE_EQ3),
    )
    return GateResult(counts=filled, conditions=conditions, n=n,
                      modal_grade=modal_grade, modal_share=modal_share,
                      share_ge2=share_ge2, share_eq3=share_eq3,
                      entropy=grade_entropy(filled))


def _band_condition(name: str, observed: float, low: float,
                    high: float) -> Condition:
    """A two-sided condition, recording WHICH side was violated."""
    if observed < low:
        return Condition(name, False, observed, "low", low)
    if observed > high:
        return Condition(name, False, observed, "high", high)
    return Condition(name, True, observed)


def reweight_to_pool(counts_by_class: Mapping[str, Mapping[int, int]],
                     pool_mix: Mapping[str, int] | None = None
                     ) -> dict[int, float]:
    """Project a class-stratified grade distribution back onto the pool's mix.

    §3.1 enriches agent-positives ~1.8x so the agreement smell test has both
    classes per topic, which means **any share-at->=2 read off the 280 pairs is
    higher than the same judge would produce on the pool.** The gate band is
    defined on the sample, but the report must show both, or a reader compares
    two different quantities and concludes the judge is lenient when it is the
    sampling that is.

    Classes absent from `counts_by_class` are dropped and the remaining weights
    renormalized, so a run that judged no `unjudged` pairs still reports a
    coherent estimate instead of silently under-weighting the rest.
    """
    mix = dict(pool_mix or POOL_LABEL_MIX)
    usable = {cls: w for cls, w in mix.items()
              if w > 0 and sum(counts_by_class.get(cls, {}).values() or [0]) > 0}
    if not usable:
        raise CalibrationError(
            "no class in the sample overlaps the pool mix — cannot reweight")
    total_weight = sum(usable.values())
    out = {g: 0.0 for g in GRADES}
    for cls, weight in usable.items():
        counts = _normalize_counts(counts_by_class[cls])
        n = sum(counts.values())
        for g in GRADES:
            out[g] += (weight / total_weight) * counts[g] / n
    return out


def roc_auc(positive_grades: Sequence[int],
            negative_grades: Sequence[int]) -> float | None:
    """AUC of grade separating agent-positive from agent-negative pairs.

    Computed by the rank-sum identity with explicit **half-credit for ties**,
    which matters more here than usual: grades take four values over hundreds of
    pairs, so ties are the common case and a tie-blind implementation would
    silently report ~0.5 for a judge that separates the classes perfectly at
    coarse granularity.

    Returns `None` when either class is empty — the smell test is undefined, not
    0.5, and reporting a number there would invent a finding.

    **This is a smell test, not an accuracy measure** (PLAN §3.3b Finding 1): the
    agent's label is a staging decision, so a mid-range AUC is expected. Only
    anti-correlation (AUC < 0.5) is suspicious.
    """
    if not positive_grades or not negative_grades:
        return None
    wins = 0.0
    for p in positive_grades:
        for n in negative_grades:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positive_grades) * len(negative_grades))


@dataclass(frozen=True)
class AgentAgreement:
    """The secondary smell test: does the judge order the agent's classes correctly?"""

    auc: float | None
    mean_by_class: dict[str, float]
    n_by_class: dict[str, int]
    share_ge2_by_class: dict[str, float]

    @property
    def ordered(self) -> bool:
        """True when committed pairs mean strictly above rejected ones."""
        pos = self.mean_by_class.get("positive")
        neg = self.mean_by_class.get("negative")
        return pos is not None and neg is not None and pos > neg

    @property
    def anti_correlated(self) -> bool:
        """The one genuinely suspicious outcome (PLAN §3.3)."""
        return self.auc is not None and self.auc < 0.5


def agent_agreement(grades_by_class: Mapping[str, Sequence[int]]
                    ) -> AgentAgreement:
    """Mean grade, share >=2, and AUC per agent label class."""
    mean_by_class: dict[str, float] = {}
    n_by_class: dict[str, int] = {}
    share_ge2: dict[str, float] = {}
    for cls, grades in grades_by_class.items():
        n_by_class[cls] = len(grades)
        if grades:
            mean_by_class[cls] = sum(grades) / len(grades)
            share_ge2[cls] = sum(1 for g in grades if g >= 2) / len(grades)
    return AgentAgreement(
        auc=roc_auc(list(grades_by_class.get("positive", ())),
                    list(grades_by_class.get("negative", ()))),
        mean_by_class=mean_by_class, n_by_class=n_by_class,
        share_ge2_by_class=share_ge2)


@dataclass(frozen=True)
class VariantResult:
    """Everything WP6 measured about one prompt variant on the 280 pairs."""

    prompt_version: str
    gate: GateResult
    agreement: AgentAgreement
    counts_by_class: dict[str, dict[int, int]] = field(default_factory=dict)
    parse_failures: int = 0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    #: Winner only: exact-match rate of the cache-bypassing re-judge probe.
    stability_match_rate: float | None = None
    stability_pairs: int = 0

    @property
    def pool_reweighted(self) -> dict[int, float] | None:
        """Grade shares projected onto the pool mix, or None if not computable."""
        try:
            return reweight_to_pool(self.counts_by_class)
        except CalibrationError:
            return None

    @property
    def pool_share_ge2(self) -> float | None:
        est = self.pool_reweighted
        return None if est is None else est[2] + est[3]

    @property
    def stability_ok(self) -> bool | None:
        if self.stability_match_rate is None:
            return None
        return self.stability_match_rate >= STABILITY_MIN_MATCH_RATE


@dataclass(frozen=True)
class Decision:
    """WP6's outcome: which variant (if any) may judge the sweep, and why."""

    #: Gate-passing variant chosen by §3.3's rule, else None.
    winner: str | None
    #: Least-bad variant when nothing passed — for the operator, NOT auto-used.
    best_effort: str | None
    passing: tuple[str, ...]
    ranked: tuple[str, ...]
    rationale: str

    @property
    def gated(self) -> bool:
        """True when no variant passed, i.e. `calibrate` must exit 6."""
        return self.winner is None


def decide(results: Sequence[VariantResult]) -> Decision:
    """PLAN §3.3's decision rule, plus the no-pass fallback ranking.

    Among gate-passing variants: **lowest modal share, tie-broken by higher
    AUC.** Deliberately *not* "highest AUC" — the agent's label is a staging
    decision (§3.3b Finding 1), so optimizing AUC would select the variant that
    best mimics a context-budget heuristic. Modal share is the property the
    experiment actually needs, because a mode-dominated judge ties neighbouring
    grid cells.

    When nothing passes, `winner` is None (the caller exits 6) and `best_effort`
    names the closest variant — smallest distance outside condition 3's band,
    tie-broken by lowest modal share — so the escalation to the user carries a
    recommendation rather than only a refusal.
    """
    if not results:
        raise CalibrationError("no variant results to decide between")

    def pass_key(r: VariantResult) -> tuple[float, float, str]:
        # -auc so higher AUC sorts first; version id last for total determinism.
        return (r.gate.modal_share, -(r.agreement.auc or 0.0), r.prompt_version)

    def fail_key(r: VariantResult) -> tuple[float, float, str]:
        return (r.gate.distance_from_band(), r.gate.modal_share,
                r.prompt_version)

    passing = sorted((r for r in results if r.gate.passed), key=pass_key)
    if passing:
        winner = passing[0]
        others = [r.prompt_version for r in passing[1:]]
        rationale = (
            f"`{winner.prompt_version}` has the lowest modal share "
            f"({winner.gate.modal_share:.3f}) among the "
            f"{len(passing)} gate-passing variant"
            f"{'s' if len(passing) != 1 else ''}"
            + (f" (also passing: {', '.join('`' + v + '`' for v in others)})"
               if others else "")
            + ". The gate is a floor on usability, not the selection criterion "
              "— the user confirms this choice before WP7 launches.")
        return Decision(winner=winner.prompt_version, best_effort=None,
                        passing=tuple(r.prompt_version for r in passing),
                        ranked=tuple(r.prompt_version
                                     for r in sorted(results, key=pass_key)),
                        rationale=rationale)

    ranked = sorted(results, key=fail_key)
    least_bad = ranked[0]
    missed = ", ".join(CONDITION_LABELS[c.name]
                       for c in least_bad.gate.failures)
    return Decision(
        winner=None, best_effort=least_bad.prompt_version, passing=(),
        ranked=tuple(r.prompt_version for r in ranked),
        rationale=(
            f"No variant passed the gate. Closest is "
            f"`{least_bad.prompt_version}` (share>=2 {least_bad.gate.share_ge2:.3f}, "
            f"modal {least_bad.gate.modal_share:.3f}), missing: {missed}. "
            f"Per PLAN §3.3 the sweep must NOT launch on this; `calibrate` exits "
            f"6 so the user decides, and proceeding demotes graded nDCG@10 in "
            f"favour of the pre-registered binarized headline."))


def gate_log_lines(result: VariantResult) -> list[str]:
    """`[GATE]`-prefixed lines for the live log, one per condition.

    Greppable per PLAN §5.6, and emitted per condition rather than as one summary
    so a multi-variant calibration says which bound moved without reopening the
    report.
    """
    v = result.prompt_version
    out = [f"[GATE] {v} n={result.gate.n} "
           f"dist={result.gate.counts} "
           f"modal={result.gate.modal_grade}@{result.gate.modal_share:.3f} "
           f"ge2={result.gate.share_ge2:.3f} eq3={result.gate.share_eq3:.3f} "
           f"H={result.gate.entropy:.3f} "
           f"verdict={'PASS' if result.gate.passed else 'FAIL'}"]
    for cond in result.gate.conditions:
        out.append(f"[GATE] {v}   {cond.describe()}")
    return out


#: Prepended to `report.md`. The §3.3b caveats must travel with the numbers — a
#: reader who opens only this artifact must not be able to read the agent-label
#: cross-tab as an accuracy measure, nor compare the sample share to the pool.
REPORT_PREAMBLE = """\
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
"""


def render_report_md(results: Sequence[VariantResult], decision: Decision, *,
                     run_id: str, sample_path: str, n_pairs: int,
                     sample_label_mix: Mapping[str, int] | None = None,
                     model_id: str | None = None, region: str | None = None
                     ) -> str:
    """Render `calibration/report.md` — the artifact the user reviews.

    Ordered so the decision is legible before the evidence: verdict first, then
    per-variant distributions with the bound each was checked against, then the
    smell test, then stability and cost.
    """
    if not results:
        raise CalibrationError("cannot render a report with no variant results")

    lines = [f"# WP0/WP6 judge calibration — `{run_id}`", ""]
    lines.append(f"- calibration sample: `{sample_path}` ({n_pairs} pairs, "
                 f"identical across every variant)")
    if model_id:
        lines.append(f"- judge model: `{model_id}`"
                     + (f" in `{region}`" if region else ""))
    lines.append(f"- variants scored: "
                 + ", ".join(f"`{r.prompt_version}`" for r in results))
    if sample_label_mix:
        lines.append("- sample label mix: " + _mix_str(sample_label_mix))
    lines.append("- pool label mix: " + _mix_str(POOL_LABEL_MIX))
    lines += ["", REPORT_PREAMBLE, ""]

    lines += ["## Verdict", ""]
    if decision.winner:
        lines.append(f"**PASS — recommended judge: `{decision.winner}`.**")
    else:
        lines.append(f"**GATED (exit 6) — no variant passed.** Least-bad: "
                     f"`{decision.best_effort}`.")
    lines += ["", decision.rationale, ""]

    lines += ["## Gate conditions", "",
              "The four bounds, all inclusive (PLAN §3.3):", ""]
    for name in CONDITION_ORDER:
        lines.append(f"{CONDITION_ORDER.index(name) + 1}. {CONDITION_LABELS[name]}")
    lines += ["", "| variant | n | 0 | 1 | 2 | 3 | modal | H (bits) | "
              "share>=2 | pool-rwt >=2 | share=3 | verdict | missed |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        g = r.gate
        pool = r.pool_share_ge2
        missed = ", ".join(
            f"{CONDITION_ORDER.index(c.name) + 1}{'v' if c.direction == 'low' else '^'}"
            for c in g.failures) or "—"
        lines.append(
            f"| `{r.prompt_version}` | {g.n} | "
            + " | ".join(str(g.counts[x]) for x in GRADES)
            + f" | {g.modal_grade}@{g.modal_share:.3f} | {g.entropy:.3f} "
              f"| {g.share_ge2:.3f} | "
            + (f"{pool:.3f}" if pool is not None else "—")
            + f" | {g.share_eq3:.3f} | "
              f"{'**PASS**' if g.passed else 'FAIL'} | {missed} |")
    lines += ["", "`missed` marks the condition number and direction — "
              "`3v` = below condition 3's floor, `3^` = above its ceiling. "
              "The two are opposite problems: `v` wants a more lenient prompt, "
              "`^` a stricter one.", ""]

    lines += ["## Per-condition detail", ""]
    for r in results:
        lines.append(f"### `{r.prompt_version}`")
        lines.append("")
        for cond in r.gate.conditions:
            lines.append(f"- {cond.describe()}")
        lines.append("")

    lines += ["## Agent-label agreement (smell test — see the caveat above)", "",
              "| variant | AUC | mean grade: committed | rejected | unjudged | "
              "share>=2: committed | rejected | ordered? |",
              "|---|---|---|---|---|---|---|---|"]
    for r in results:
        a = r.agreement
        lines.append(
            f"| `{r.prompt_version}` | "
            + (f"{a.auc:.3f}" if a.auc is not None else "—") + " | "
            + " | ".join(_fmt_class(a.mean_by_class.get(c), a.n_by_class.get(c))
                         for c in ("positive", "negative", "unjudged"))
            + " | "
            + " | ".join(_fmt_share(a.share_ge2_by_class.get(c))
                         for c in ("positive", "negative"))
            + " | " + ("yes" if a.ordered else "**NO**")
            + (" ⚠ anti-correlated" if a.anti_correlated else "") + " |")
    lines.append("")

    probed = [r for r in results if r.stability_match_rate is not None]
    lines += ["## Stability probe", ""]
    if probed:
        lines.append(f"Re-judged at temperature 0 **bypassing the cache** (a "
                     f"cache hit would trivially report 1.000); requires "
                     f">= {STABILITY_MIN_MATCH_RATE:.0%} exact match.")
        lines += ["", "| variant | pairs | exact-match rate | verdict |",
                  "|---|---|---|---|"]
        for r in probed:
            lines.append(f"| `{r.prompt_version}` | {r.stability_pairs} | "
                         f"{r.stability_match_rate:.3f} | "
                         f"{'PASS' if r.stability_ok else '**FAIL**'} |")
    else:
        lines.append("Not run (the probe covers the gate-passing winner only).")
    lines.append("")

    lines += ["## Cost and parse health", "",
              "| variant | calls | parse failures | input tok | output tok | "
              "cost USD |", "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| `{r.prompt_version}` | {r.calls} | {r.parse_failures} "
                     f"| {r.input_tokens} | {r.output_tokens} | "
                     f"${r.cost_usd:.4f} |")
    total = sum(r.cost_usd for r in results)
    lines.append(f"| **total** | {sum(r.calls for r in results)} | "
                 f"{sum(r.parse_failures for r in results)} | "
                 f"{sum(r.input_tokens for r in results)} | "
                 f"{sum(r.output_tokens for r in results)} | "
                 f"**${total:.4f}** |")
    lines += ["", "Measured mean token counts from this run replace the priors "
              "in every later pre-flight estimate (PLAN §5.7 layer 1), so these "
              "numbers are an input to WP7's budget check, not just a receipt.",
              ""]

    lines += ["## Prompt provenance", "",
              "| variant | query slot | emits facet | sha256 |",
              "|---|---|---|---|"]
    for r in results:
        try:
            spec = prompts.get_prompt(r.prompt_version)
        except prompts.UnknownPromptVersion:
            lines.append(f"| `{r.prompt_version}` | ? | ? | "
                         "**unknown variant** |")
            continue
        lines.append(f"| `{r.prompt_version}` | {spec.query_slot} | "
                     f"{'yes' if spec.emits_facet else 'no'} | "
                     f"`{spec.template_sha256[:16]}…` |")
    lines.append("")
    return "\n".join(lines)


def _mix_str(mix: Mapping[str, int]) -> str:
    total = sum(mix.values()) or 1
    return ", ".join(f"{cls} {count} ({count / total:.1%})"
                     for cls, count in sorted(mix.items()))


def _fmt_class(value: float | None, n: int | None) -> str:
    if value is None:
        return f"— (n={n or 0})"
    return f"{value:.2f} (n={n})"


def _fmt_share(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def counts_from_grades(grades: Iterable[int]) -> dict[int, int]:
    """Grade histogram over all four grades, zeros included.

    Used by the driver and by tests. Fills absent grades so `evaluate_gate`'s
    all-grades-used condition sees a real zero rather than a missing key.
    """
    out = {g: 0 for g in GRADES}
    for grade in grades:
        g = int(grade)
        if g not in out:
            raise CalibrationError(f"grade {g} outside {GRADE_MIN}-{GRADE_MAX}")
        out[g] += 1
    return out
