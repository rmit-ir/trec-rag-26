"""Ranking metrics for the k1/b sweep (PLAN §5.5, §3.3) — pure stdlib.

**Read this before quoting any absolute number out of `scores.csv`.**

Every metric here is computed against a *topic-level* pooled qrel, and the ideal
ranking is built from **all** judged (topic, chunk) grades for the topic — not
from what the query being scored actually retrieved. That is a deliberate choice
(PLAN §5.5) with one loud consequence:

    **The absolute nDCG values this module produces are deflated and are not
    comparable to any published nDCG.** A topic contributes 3-16 keyword
    queries; the ideal for every one of them is the top 10 grades of the whole
    topic's pool, which typically contains chunks *no single keyword query can
    retrieve*. So a perfect ranking for one query still scores well under 1.0.
    Only *differences between configs* are meaningful — which is the entire
    purpose of the experiment.

The upside is what makes the paired test in `stats.py` clean: the denominator is
a property of the topic, identical for every config and every one of the topic's
queries, so a per-query delta between two configs is pure numerator movement.
Had the ideal been built per-query from that query's own retrieved set, each
config would be scored against its own denominator and the deltas would mix
"ranked better" with "found a different ceiling".

The conventions, pinned by `tests/bm25_tune/test_metrics.py` because a silent
off-by-one in any one of them invalidates every number in the report:

- **Primary — nDCG@10, exponential gain `2**g - 1`, discount `1/log2(rank + 1)`,
  ranks 1-based** (the Burges convention). Chosen because the calibrated judge
  piles grades up at 2 (PLAN §3.4) and exponential gain triples the 3-vs-2
  reward (7 vs 3), preserving what discrimination the labels have.
- **Also reported — linear-gain nDCG@10** (`gain = g`, same discount), which is
  `trec_eval`'s `ndcg_cut_10`. Both columns appear in every score table; they
  are not interchangeable and the report must say which it quotes.
- **Unjudged = grade 0.** With pooled judging every chunk any swept config
  returns to depth 30 is judged, so an unjudged top-10 hit means a parse failure
  or a scoring/pooling mismatch. Because that penalization is silent, per-config
  **judged@10 coverage** is reported alongside every metric — a config whose
  coverage dips is not "worse", it is not fully judged.
- **Secondaries (pre-registered, PLAN §3.3):** nDCG@10 binarized at grade >= 2,
  Recall@10 (binarized >= 2), and MAP@30 binarized at **both** >= 1 and >= 2.
- **Secondary / exploratory, added 2026-07-31 at the user's request (PLAN §5.5):**
  `gp10` (graded precision@10) and `p10_bin2` (plain Precision@10 binarized at
  grade >= 2) — "how much relevant material is in the ten slots a user sees".
  They are computed in the *same* scoring pass as nDCG@10 and persisted in
  `scores.csv` / `scores-per-query.csv`, so re-optimizing the grid for either one
  later needs no re-judging and no re-run. They are **not** part of the
  pre-registered confirmatory family (PLAN §3.3, 3 candidate-vs-baseline
  comparisons); see `stats.py`.
- **Aggregation:** mean over queries (primary) **and** mean-of-topic-means
  (robustness — a 16-query topic would otherwise carry 5x the weight of a
  3-query one).

`Recall@10` and `MAP@30` divide by the **topic's** judged-relevant count (PLAN
§5.5), i.e. `trec_eval`'s `num_rel` rather than `min(num_rel, k)`. This deflates
them exactly as the topic-level ideal deflates nDCG, and for the same reason:
a per-config, per-query denominator would make the deltas uninterpretable.

The two **precision** measures are the one place a *flat* denominator is right:
they divide by `k` (10), not by `min(retrieved, 10)`. See `precision_at_k` for
the argument — briefly, a config that returned 4 documents genuinely gave the
user 6 empty slots, and `min(retrieved, k)` would let it beat a config that
filled all ten. (`QueryScore.coverage_at_10` uses `min(retrieved, 10)` because it
answers the opposite question — "of what was shown, how much was judged" — where
slots that do not exist cannot be unjudged.)

Where a metric is genuinely **undefined** — the topic has no judged-relevant
chunk at all, so there is nothing to recall and no non-zero ideal — the value is
`None` rather than `0.0`. Reporting 0.0 would mix "ranked nothing useful" with
"nothing useful exists", and would drag the mean down by a factor that depends on
the qrel rather than on the config. Aggregates skip `None` and report how many
queries each metric was defined on (`<metric>_n`), so the exclusion is visible.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, Sequence

#: Grades the judge is allowed to emit (PLAN §3.2's rubric is 0-3). Anything
#: outside this is a parsing bug in `judge.py`, and silently accepting it would
#: hand `2 ** g - 1` an absurd gain and quietly rescale every nDCG for the topic.
GRADE_MIN = 0
GRADE_MAX = 3

#: nDCG / Recall cutoff (PLAN §5.5) and the MAP cutoff (PLAN §3.3).
NDCG_CUTOFF = 10
MAP_CUTOFF = 30
#: The retrieval depth the sweep runs at (PLAN §5.5) — used only to warn when a
#: run file is shallower than the metrics assume.
RUN_DEPTH = 30

#: Binarization thresholds. `>= 2` is the pre-registered fallback headline
#: (PLAN §3.3); `>= 1` is reported for MAP only, as the loosest reading.
BINARY_THRESHOLD_STRICT = 2
BINARY_THRESHOLD_LOOSE = 1

#: Column / key order for every score table. `ndcg10_exp` first because it is
#: the primary (PLAN §5.5) and readers stop at column one.
PRIMARY_METRIC = "ndcg10_exp"
METRIC_NAMES: tuple[str, ...] = (
    "ndcg10_exp",
    "ndcg10_lin",
    "ndcg10_bin2",
    "gp10",
    "p10_bin2",
    "recall10_bin2",
    "map30_bin1",
    "map30_bin2",
)
METRIC_LABELS: dict[str, str] = {
    "ndcg10_exp": "nDCG@10 (exp gain, PRIMARY)",
    "ndcg10_lin": "nDCG@10 (linear gain, trec_eval ndcg_cut_10)",
    "ndcg10_bin2": "nDCG@10 (binarized >=2)",
    "gp10": "Graded P@10 (mean grade/3 over 10 slots; rank-flat, secondary)",
    "p10_bin2": "P@10 (binarized >=2; rank-flat, secondary)",
    "recall10_bin2": "Recall@10 (binarized >=2)",
    "map30_bin1": "MAP@30 (binarized >=1)",
    "map30_bin2": "MAP@30 (binarized >=2)",
}

#: The metrics PLAN §3.3 pre-registers as the confirmatory family. `gp10` and
#: `p10_bin2` are deliberately absent: they were added after the plan was written
#: (2026-07-31) and are secondary/exploratory. They are still tested by the
#: `stats` subcommand — which runs every name in `METRIC_NAMES` — because the
#: point of computing them in the same pass is that no re-run is needed later; but
#: `stats.N_COMPARISONS` stays at 3 (it counts candidate *configs*, not metrics),
#: and a p-value quoted for either of these is exploratory, not confirmatory.
PRE_REGISTERED_METRICS: tuple[str, ...] = (
    "ndcg10_exp",
    "ndcg10_lin",
    "ndcg10_bin2",
    "recall10_bin2",
    "map30_bin1",
    "map30_bin2",
)
#: Added 2026-07-31 at the user's request; see the module docstring.
EXPLORATORY_METRICS: tuple[str, ...] = ("gp10", "p10_bin2")

#: The `kind` of the cache snapshot's header line (`store.CACHE_META_KIND`).
#: Duplicated rather than imported to keep this module's import graph a leaf —
#: scoring must stay loadable without the judging stack. `test_metrics.py` pins
#: the two definitions as equal, so a rename in `store.py` fails a test instead
#: of making the header line look like a judgment with no topic_id.
CACHE_META_KIND = "cache_meta"

#: `trecruns/k1_<k1>__b_<b>.txt` (PLAN §4.2). Parsed only to sort the score
#: table by grid position and to fill the `k1`/`b` columns; a run file whose stem
#: does not match is still scored, keyed by its stem.
CONFIG_STEM_RE = re.compile(r"^k1_(?P<k1>-?\d+(?:\.\d+)?)__b_(?P<b>-?\d+(?:\.\d+)?)$")


class MetricsError(RuntimeError):
    """A qrel or run file is not in the shape PLAN §4.2 documents.

    Raised rather than tolerated: a run file whose columns shifted, or a qrels
    snapshot carrying a different `prompt_version`, would score a well-formed
    but *wrong* matrix, and nothing downstream could detect it.
    """


# ---------------------------------------------------------------------------
# Gain functions
# ---------------------------------------------------------------------------
def exp_gain(grade: int) -> float:
    """`2**g - 1` — the primary convention (Burges): 0, 1, 3, 7 for grades 0-3."""
    return float(2 ** grade - 1)


def linear_gain(grade: int) -> float:
    """`g` — `trec_eval`'s `ndcg_cut` gain: 0, 1, 2, 3."""
    return float(grade)


def binary_gain(threshold: int) -> Callable[[int], float]:
    """Gain of 1 for `grade >= threshold`, else 0.

    Used for the binarized secondaries, and for Recall/MAP's relevance test, so
    exactly one definition of "relevant" exists in this module.
    """
    def gain(grade: int) -> float:
        return 1.0 if grade >= threshold else 0.0
    return gain


def discount(rank: int) -> float:
    """`1 / log2(rank + 1)` with **1-based** ranks: 1.0, 0.6309, 0.5, ...

    The rank base is the single most common silent error in an nDCG
    implementation: 0-based ranks would make the first document's discount
    `1/log2(1) = inf`, and "fixing" that by using `1/log2(rank + 2)` shifts every
    position by one and changes every reported number by ~1-3 %.
    """
    if rank < 1:
        raise MetricsError(f"rank must be 1-based and >= 1, got {rank}")
    return 1.0 / math.log2(rank + 1)


# ---------------------------------------------------------------------------
# Core metric primitives
# ---------------------------------------------------------------------------
def dcg(grades: Sequence[int], gain: Callable[[int], float] = exp_gain) -> float:
    """Discounted cumulative gain of `grades` in the order given.

    `grades[0]` is rank 1. No cutoff is applied here — callers slice first, so
    the cutoff is visible at the call site rather than hidden in a default.
    """
    return sum(gain(g) * discount(i) for i, g in enumerate(grades, start=1))


def ideal_grades(topic_grades: Mapping[str, int], k: int = NDCG_CUTOFF) -> list[int]:
    """The top-`k` grades of the **topic's whole pool**, sorted descending.

    This is the deflation the module docstring warns about, expressed in one
    line: the ideal is a property of the topic, not of the query's ranking, so
    every config and every query of that topic is normalized by the same number.
    """
    return sorted(topic_grades.values(), reverse=True)[:k]


def ndcg_at_k(ranked_grades: Sequence[int], topic_grades: Mapping[str, int],
              k: int = NDCG_CUTOFF,
              gain: Callable[[int], float] = exp_gain) -> float | None:
    """nDCG@`k` of one ranking against the topic-level ideal.

    Returns `None` when the ideal DCG is 0 — the topic has no judged-relevant
    chunk under this gain function (every grade 0, or every grade below a
    binarization threshold), so the ratio is undefined rather than zero. See the
    module docstring for why that distinction is not pedantry.
    """
    ideal = dcg(ideal_grades(topic_grades, k), gain)
    if ideal <= 0.0:
        return None
    return dcg(list(ranked_grades)[:k], gain) / ideal


def precision_at_k(ranked_grades: Sequence[int], k: int = NDCG_CUTOFF,
                   threshold: int = BINARY_THRESHOLD_STRICT) -> float | None:
    """Precision@`k` with relevance binarized at `grade >= threshold`.

    `#{top-k grades >= threshold} / k` — **a flat `k`, not `min(retrieved, k)`.**
    That is the load-bearing choice here, so the argument in full:

    A user of this system is shown ten slots. A config that retrieved only 4
    chunks left six of them empty, and those empty slots are a property of the
    *config* (its query, its scoring), not of the evaluation. With `min(retrieved,
    k)` a config returning one relevant chunk and nothing else would score
    P@10 = 1.0 and beat a config that filled all ten slots with nine relevant
    ones (0.9) — the brief's "a query returning 4 hits must not look better or
    worse than it is" fails in the *better* direction. The flat `k` is also
    `trec_eval`'s `P_10`, so this column can be lined up against published
    numbers, unlike everything else in this module.

    (`QueryScore.coverage_at_10` uses `min(retrieved, k)` for the opposite and
    equally deliberate reason: it measures *judging* coverage of what was shown,
    and a slot that was never filled cannot be unjudged. The two denominators
    answer different questions and are not an inconsistency.)

    Returns `None` only when `k < 1`; unlike Recall/MAP there is no qrel-derived
    denominator that can vanish, so a topic with no relevant chunk yields a
    well-defined 0.0 rather than an undefined value. Note the asymmetry that
    creates in `scores.csv`: `p10_bin2_n` counts every query while
    `recall10_bin2_n` does not.
    """
    if k < 1:
        return None
    hits = sum(1 for g in list(ranked_grades)[:k] if g >= threshold)
    return hits / k


def graded_precision_at_k(ranked_grades: Sequence[int], k: int = NDCG_CUTOFF
                          ) -> float | None:
    """Graded precision@`k`: mean of `grade / GRADE_MAX` over the `k` slots.

    `sum(top-k grades) / (k * GRADE_MAX)` — i.e. "what fraction of the maximum
    possible relevance mass did the top `k` actually deliver". Same flat-`k`
    denominator as `precision_at_k`, for the same reason.

    **Why this form, and not the alternatives considered:**

    - *Binary P@10 alone* (`p10_bin2`) discards the whole point of paying for
      graded labels: a top-10 of ten grade-3 chunks and a top-10 of ten grade-2
      chunks are indistinguishable, and a top-10 of ten grade-1 chunks reads as
      exactly as bad as ten grade-0 chunks. Both are reported precisely so that
      loss is visible rather than assumed away.
    - *Mean exponential gain* (`(2**g - 1) / 7`) was rejected: it is defensible
      inside nDCG, where the same gain appears in numerator and ideal, but as a
      standalone average it makes the measure dominated by grade 3s (a grade 2
      contributes 3/7 = 0.43 of a grade 3, so ten grade-2s score 0.43 while
      "obviously partially relevant" reads as nearly half-empty). Since PLAN §3.4
      says the labels pile up at grade 2, that would compress the very region
      where all the between-config movement lives.
    - *Normalizing by the topic's best achievable top-10* (a "graded precision
      normalized") was rejected because it reintroduces exactly the deflation
      that makes nDCG's absolute values unquotable. The brief asks for a number
      whose absolute value is interpretable.

    **Properties, stated so the report cannot overclaim:**

    - bounded [0, 1] (grades are validated to `GRADE_MIN`..`GRADE_MAX`);
    - reduces to `precision_at_k` when every relevant chunk is grade
      `GRADE_MAX` and every other is 0 — so it *is* P@10, generalized;
    - **rank-indifferent within the cutoff.** Permuting the top 10 does not move
      it. That is the design goal, not a defect: nDCG@10 is already the
      rank-sensitive measure, so a rank-flat companion isolates *set quality*
      ("did the config find good material at all") from *ordering* ("did it put
      the best first"). When nDCG moves and `gp10` does not, the config only
      reshuffled; when both move, it changed what it found;
    - **not normalized by an ideal** — so, unlike every nDCG/Recall/MAP column
      here, its absolute value is directly comparable across topics and can be
      read as a percentage.

    Returns `None` only when `k < 1` (see `precision_at_k`).
    """
    if k < 1:
        return None
    total = sum(list(ranked_grades)[:k])
    return total / (k * GRADE_MAX)


def recall_at_k(ranked_grades: Sequence[int], topic_grades: Mapping[str, int],
                k: int = NDCG_CUTOFF,
                threshold: int = BINARY_THRESHOLD_STRICT) -> float | None:
    """Fraction of the **topic's** relevant chunks that appear in the top `k`.

    The denominator is the topic's judged-relevant count (PLAN §5.5), which for
    a pooled topic-level qrel is far larger than `k` — so absolute values are
    small by construction and only the config-to-config difference means
    anything. `None` when the topic has no relevant chunk at that threshold.
    """
    relevant = count_relevant(topic_grades, threshold)
    if relevant == 0:
        return None
    hits = sum(1 for g in list(ranked_grades)[:k] if g >= threshold)
    return hits / relevant


def average_precision_at_k(ranked_grades: Sequence[int],
                           topic_grades: Mapping[str, int],
                           k: int = MAP_CUTOFF,
                           threshold: int = BINARY_THRESHOLD_STRICT
                           ) -> float | None:
    """Average precision to depth `k`, `trec_eval`'s `map_cut_<k>` convention.

    Sum of `precision@i` at every relevant rank `i <= k`, divided by the
    **topic's total** relevant count — not by `min(R, k)`. That matches
    `trec_eval` and matches `recall_at_k`'s denominator, so a config cannot look
    better on MAP merely because its ranking was truncated differently.

    `None` when the topic has no relevant chunk at that threshold.
    """
    relevant = count_relevant(topic_grades, threshold)
    if relevant == 0:
        return None
    found = 0
    total = 0.0
    for rank, grade in enumerate(list(ranked_grades)[:k], start=1):
        if grade >= threshold:
            found += 1
            total += found / rank
    return total / relevant


def count_relevant(topic_grades: Mapping[str, int], threshold: int) -> int:
    """How many of the topic's judged chunks reach `threshold`."""
    return sum(1 for g in topic_grades.values() if g >= threshold)


# ---------------------------------------------------------------------------
# Qrels
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Qrels:
    """Topic-level pooled judgments: `topic_id -> chunk_id -> grade`.

    Topic-level, not query-level, because that is the judgment cache's key
    (PLAN §5.3) — one narrative is judged once against a chunk and every one of
    the topic's queries reuses it. That reuse is both the cost model (PLAN §6.2)
    and the reason the ideal is topic-shaped.
    """

    grades: Mapping[str, Mapping[str, int]]
    prompt_version: str | None = None

    def topic(self, topic_id: str) -> Mapping[str, int]:
        """Judged chunks for one topic; empty mapping if the topic is unjudged."""
        return self.grades.get(topic_id, {})

    def grade(self, topic_id: str, chunk_id: str) -> int | None:
        """The judged grade, or `None` if this (topic, chunk) was never judged."""
        return self.grades.get(topic_id, {}).get(chunk_id)

    def graded(self, topic_id: str, chunk_id: str) -> int:
        """The grade with **unjudged = 0** (PLAN §5.5's scoring rule)."""
        return self.grades.get(topic_id, {}).get(chunk_id, 0)

    @property
    def topics(self) -> list[str]:
        return sorted(self.grades)

    def n_judged(self) -> int:
        return sum(len(v) for v in self.grades.values())

    def distribution(self) -> dict[int, int]:
        """Grade histogram — the sanity check that the qrel is not degenerate."""
        counts: dict[int, int] = {}
        for chunks in self.grades.values():
            for grade in chunks.values():
                counts[grade] = counts.get(grade, 0) + 1
        return dict(sorted(counts.items()))


def _coerce_grade(value: object, where: str) -> int:
    try:
        grade = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise MetricsError(f"{where}: grade {value!r} is not an integer") from exc
    if not GRADE_MIN <= grade <= GRADE_MAX:
        raise MetricsError(
            f"{where}: grade {grade} is outside the rubric's {GRADE_MIN}-"
            f"{GRADE_MAX} range — `2 ** g - 1` would rescale the topic's ideal, "
            "so this is a judge-parsing bug, not a value to clamp")
    return grade


def _split_jkey(jkey: str, where: str) -> tuple[str, str, str]:
    """`<prompt_version>::<topic_id>::<chunk_id>` -> its three parts."""
    parts = jkey.split("::")
    if len(parts) != 3:
        raise MetricsError(
            f"{where}: jkey {jkey!r} is not "
            "'<prompt_version>::<topic_id>::<chunk_id>'")
    return parts[0], parts[1], parts[2]


def load_qrels_jsonl(path: Path, prompt_version: str | None = None) -> Qrels:
    """Read `judgments/cache/qrels-<pv>.jsonl` (PLAN §4.2/§5.3).

    Deliberately tolerant about *field names* and strict about *identity*. The
    snapshot is written by `store.py` (WP3) and this module must not be the thing
    that blocks on a field rename, so `topic_id`/`chunk_id` are taken from
    explicit fields when present and otherwise parsed out of the `jkey` — one of
    the two is always there, because `jkey` is the cache's only key format.

    Identity, by contrast, is checked hard: if `prompt_version` is given, a row
    naming a different one raises. That is the poisoning bug PLAN §5.3 exists to
    prevent — a `umbrela-v1` grade satisfying a `facet-v1` lookup produces a
    well-formed qrel for a label set that never existed.

    Rows with `grade: null` (parse failures, PLAN §5.4) are **skipped**, not
    treated as 0: they were never judged, so they belong in the judged@10
    coverage shortfall, not in the qrel.

    The snapshot's first line is a `kind: cache_meta` header (`store.py`), not a
    judgment; it is consumed for its `prompt_version` and skipped.
    """
    grades: dict[str, dict[str, int]] = defaultdict(dict)
    seen_versions: set[str] = set()
    for lineno, row in _iter_jsonl(path):
        where = f"{path}:{lineno}"
        if row.get("kind") == CACHE_META_KIND:
            version = row.get("prompt_version")
            if isinstance(version, str):
                seen_versions.add(version)
            continue
        topic_id = row.get("topic_id")
        chunk_id = row.get("chunk_id")
        version = row.get("prompt_version")
        jkey = row.get("jkey")
        if (topic_id is None or chunk_id is None) and isinstance(jkey, str):
            parsed_version, topic_id, chunk_id = _split_jkey(jkey, where)
            version = version or parsed_version
        if topic_id is None or chunk_id is None:
            raise MetricsError(
                f"{where}: need topic_id+chunk_id or a jkey; got keys "
                f"{sorted(row)}")
        if isinstance(version, str):
            seen_versions.add(version)
        if "grade" not in row:
            raise MetricsError(f"{where}: no `grade` field")
        if row["grade"] is None:
            continue
        grades[str(topic_id)][str(chunk_id)] = _coerce_grade(row["grade"], where)

    if prompt_version is not None:
        unexpected = sorted(seen_versions - {prompt_version})
        if unexpected:
            raise MetricsError(
                f"{path}: contains judgments from prompt version(s) "
                f"{unexpected} but {prompt_version!r} was requested. Scoring "
                "across prompt versions mixes two label sets into one qrel "
                "(PLAN §5.3) — re-snapshot the cache for a single version.")
    return Qrels(grades={t: dict(v) for t, v in grades.items()},
                 prompt_version=prompt_version or (
                     next(iter(seen_versions)) if len(seen_versions) == 1
                     else None))


def load_qrels_trec(path: Path, prompt_version: str | None = None) -> Qrels:
    """Read a 4-column TREC qrels file (`topic 0 chunk grade`).

    This is the *published* form (PLAN §7.4 commits `qrels-<pv>.txt`), so scoring
    must work from it as well as from the cache snapshot — otherwise the
    committed artifact cannot be used to reproduce the committed score matrix,
    which is the only reason to commit it.
    """
    grades: dict[str, dict[str, int]] = defaultdict(dict)
    for lineno, line in enumerate(Path(path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 4:
            raise MetricsError(
                f"{path}:{lineno}: expected 4 TREC qrels columns "
                f"(topic 0 chunk grade), got {len(parts)}: {line!r}")
        topic_id, _, chunk_id, raw = parts
        grades[topic_id][chunk_id] = _coerce_grade(raw, f"{path}:{lineno}")
    return Qrels(grades={t: dict(v) for t, v in grades.items()},
                 prompt_version=prompt_version)


def load_qrels(path: Path, prompt_version: str | None = None) -> Qrels:
    """Dispatch on suffix: `.jsonl` -> cache snapshot, anything else -> TREC."""
    path = Path(path)
    if not path.is_file():
        raise MetricsError(f"qrels not found: {path}")
    if path.suffix == ".jsonl":
        return load_qrels_jsonl(path, prompt_version)
    return load_qrels_trec(path, prompt_version)


def write_qrels_trec(path: Path, qrels: Qrels) -> int:
    """Write the committed 4-column TREC form; returns the line count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{topic} 0 {chunk} {grade}"
             for topic in qrels.topics
             for chunk, grade in sorted(qrels.topic(topic).items())]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""))
    tmp.replace(path)
    return len(lines)


def _iter_jsonl(path: Path) -> Iterator[tuple[int, dict]]:
    with Path(path).open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MetricsError(f"{path}:{lineno}: not valid JSON "
                                   f"({exc})") from exc
            if not isinstance(row, dict):
                raise MetricsError(f"{path}:{lineno}: expected a JSON object")
            yield lineno, row


# ---------------------------------------------------------------------------
# Run files
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RunFile:
    """One config's rankings: `qkey -> [chunk_id, ...]` in rank order."""

    config: str
    path: Path | None
    rankings: Mapping[str, Sequence[str]]
    k1: float | None = None
    b: float | None = None
    duplicates: int = 0

    @property
    def grid_key(self) -> tuple[float, float, str]:
        """Sort key placing the grid in (k1, b) order, unparsed stems last."""
        big = float("inf")
        return (self.k1 if self.k1 is not None else big,
                self.b if self.b is not None else big,
                self.config)


def parse_config_stem(stem: str) -> tuple[float | None, float | None]:
    """`k1_0.9__b_0.4` -> `(0.9, 0.4)`; anything else -> `(None, None)`.

    Tolerant on purpose: WP2 owns the writer, and a score table that refuses to
    render because a filename gained a suffix would be a worse failure than a
    table with two empty columns.
    """
    match = CONFIG_STEM_RE.match(stem)
    if match is None:
        return None, None
    return float(match.group("k1")), float(match.group("b"))


def load_trec_run(path: Path, config: str | None = None) -> RunFile:
    """Read a 6-column TREC run file (`qid Q0 docid rank score tag`).

    Rows are ordered by the file's **rank column**, not by file order: a run
    written by a concurrent or resumed sweep may interleave, and silently
    scoring a shuffled ranking would produce plausible-looking nDCG that is
    simply wrong. A `qid` repeating a `docid` keeps its best rank and the
    duplicate is counted (a fan-out bug inflates precision if left in).
    """
    path = Path(path)
    per_query: dict[str, list[tuple[int, str]]] = defaultdict(list)
    duplicates = 0
    seen: set[tuple[str, str]] = set()
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            raise MetricsError(
                f"{path}:{lineno}: expected the 6 TREC run columns "
                f"(qid Q0 docid rank score tag), got {len(parts)}: {line!r}")
        qid, _, docid, raw_rank = parts[0], parts[1], parts[2], parts[3]
        try:
            rank = int(raw_rank)
        except ValueError as exc:
            raise MetricsError(
                f"{path}:{lineno}: rank {raw_rank!r} is not an integer") from exc
        if (qid, docid) in seen:
            duplicates += 1
            continue
        seen.add((qid, docid))
        per_query[qid].append((rank, docid))

    rankings = {qid: [docid for _, docid in sorted(rows)]
                for qid, rows in per_query.items()}
    stem = config if config is not None else path.stem
    k1, b = parse_config_stem(stem)
    return RunFile(config=stem, path=path, rankings=rankings, k1=k1, b=b,
                   duplicates=duplicates)


def load_run_dir(run_dir: Path) -> list[RunFile]:
    """Load every `*.txt` under `runs/<run_id>/trecruns/`, in grid order."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise MetricsError(
            f"no trecruns dir at {run_dir} — run `search-sweep` first (WP2)")
    paths = sorted(run_dir.glob("*.txt"))
    if not paths:
        raise MetricsError(f"{run_dir} contains no *.txt run files")
    runs = [load_trec_run(path) for path in paths]
    runs.sort(key=lambda r: r.grid_key)
    return runs


def topic_of_qkey(qkey: str) -> str:
    """`rag2026-17::a1b2c3d4e5f6` -> `rag2026-17` (`extract.QueryRec.qkey`).

    The topic is recoverable from the qkey alone, which is why scoring needs no
    query file: a run file is self-describing. `score` still cross-checks against
    the persisted query set when one is available, because a qkey whose topic
    prefix is wrong would be scored against the wrong topic's qrel.
    """
    topic, sep, _ = qkey.partition("::")
    if not sep:
        raise MetricsError(
            f"qkey {qkey!r} has no '::' separator — run files must use "
            "`QueryRec.qkey` (`<topic_id>::<sha1[:12]>`) as the TREC qid, "
            "otherwise the topic-level qrel cannot be located")
    return topic


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class QueryScore:
    """Every metric for one (config, query) pair, plus its coverage evidence.

    `judged_at_10` is not decoration: unjudged chunks score 0 (PLAN §5.5), so a
    config whose top-10 is only 80 % judged is penalized by an amount that has
    nothing to do with its ranking quality. Carrying the coverage next to the
    score is what makes that visible instead of silent.
    """

    config: str
    qkey: str
    topic_id: str
    retrieved: int
    judged_at_10: int
    metrics: Mapping[str, float | None]

    @property
    def coverage_at_10(self) -> float | None:
        """Judged fraction of the top 10, or `None` if nothing was retrieved."""
        depth = min(self.retrieved, NDCG_CUTOFF)
        return self.judged_at_10 / depth if depth else None


def score_query(config: str, qkey: str, ranking: Sequence[str], qrels: Qrels,
                topic_id: str | None = None) -> QueryScore:
    """Compute every metric in `METRIC_NAMES` for one query's ranking.

    One pass, all metrics — which is the whole reason the two precision measures
    live here rather than in a follow-up script: they are derived from the same
    cached grades, so persisting them now means re-optimizing the grid for `gp10`
    or `p10_bin2` later costs nothing (no re-judging, no re-sweep).
    """
    topic = topic_id if topic_id is not None else topic_of_qkey(qkey)
    topic_grades = qrels.topic(topic)
    graded = [qrels.graded(topic, chunk) for chunk in ranking]
    judged_at_10 = sum(1 for chunk in ranking[:NDCG_CUTOFF]
                       if qrels.grade(topic, chunk) is not None)
    metrics: dict[str, float | None] = {
        "ndcg10_exp": ndcg_at_k(graded, topic_grades, NDCG_CUTOFF, exp_gain),
        "ndcg10_lin": ndcg_at_k(graded, topic_grades, NDCG_CUTOFF, linear_gain),
        "ndcg10_bin2": ndcg_at_k(graded, topic_grades, NDCG_CUTOFF,
                                 binary_gain(BINARY_THRESHOLD_STRICT)),
        "gp10": graded_precision_at_k(graded, NDCG_CUTOFF),
        "p10_bin2": precision_at_k(graded, NDCG_CUTOFF,
                                   BINARY_THRESHOLD_STRICT),
        "recall10_bin2": recall_at_k(graded, topic_grades, NDCG_CUTOFF,
                                     BINARY_THRESHOLD_STRICT),
        "map30_bin1": average_precision_at_k(graded, topic_grades, MAP_CUTOFF,
                                             BINARY_THRESHOLD_LOOSE),
        "map30_bin2": average_precision_at_k(graded, topic_grades, MAP_CUTOFF,
                                             BINARY_THRESHOLD_STRICT),
    }
    return QueryScore(config=config, qkey=qkey, topic_id=topic,
                      retrieved=len(ranking), judged_at_10=judged_at_10,
                      metrics=metrics)


def mean(values: Iterable[float]) -> float | None:
    """Arithmetic mean, or `None` for an empty sequence (never a ZeroDivision)."""
    items = list(values)
    return sum(items) / len(items) if items else None


def mean_of_topic_means(scores: Sequence[QueryScore],
                        metric: str) -> float | None:
    """Mean over topics of each topic's mean — PLAN §5.5's robustness aggregate.

    Topics contribute 3-16 queries, so the plain query mean weights a 16-query
    topic 5x a 3-query one. If the two aggregates disagree about which config
    wins, the honest report says so rather than picking the flattering one.
    """
    by_topic: dict[str, list[float]] = defaultdict(list)
    for score in scores:
        value = score.metrics.get(metric)
        if value is not None:
            by_topic[score.topic_id].append(value)
    topic_means = [m for m in (mean(v) for v in by_topic.values())
                   if m is not None]
    return mean(topic_means)


@dataclass(frozen=True)
class ConfigScore:
    """One grid cell's aggregate row in `scores.csv`."""

    config: str
    k1: float | None
    b: float | None
    n_queries: int
    n_topics: int
    judged_at_10_mean: float | None
    retrieved_mean: float | None
    duplicates: int
    #: metric -> query-level mean
    by_query: Mapping[str, float | None]
    #: metric -> mean-of-topic-means
    by_topic: Mapping[str, float | None]
    #: metric -> how many queries the metric was defined on
    defined: Mapping[str, int]
    per_query: tuple[QueryScore, ...] = field(default=(), repr=False)

    @property
    def primary(self) -> float | None:
        return self.by_query.get(PRIMARY_METRIC)

    def to_row(self) -> dict[str, object]:
        """Flatten to the `scores.csv` column layout."""
        row: dict[str, object] = {
            "config": self.config,
            "k1": self.k1 if self.k1 is not None else "",
            "b": self.b if self.b is not None else "",
            "n_queries": self.n_queries,
            "n_topics": self.n_topics,
            "judged_at_10": _fmt(self.judged_at_10_mean),
            "retrieved_mean": _fmt(self.retrieved_mean),
            "duplicate_rows": self.duplicates,
        }
        for name in METRIC_NAMES:
            row[name] = _fmt(self.by_query.get(name))
            row[f"{name}_topicmean"] = _fmt(self.by_topic.get(name))
            row[f"{name}_n"] = self.defined.get(name, 0)
        return row


CSV_COLUMNS: tuple[str, ...] = (
    ("config", "k1", "b", "n_queries", "n_topics", "judged_at_10",
     "retrieved_mean", "duplicate_rows")
    + tuple(col for name in METRIC_NAMES
            for col in (name, f"{name}_topicmean", f"{name}_n")))


def _fmt(value: float | None, places: int = 6) -> str:
    return "" if value is None else f"{value:.{places}f}"


def score_run(run: RunFile, qrels: Qrels,
              qkeys: Sequence[str] | None = None) -> ConfigScore:
    """Score one config over `qkeys` (default: every query in its run file).

    Passing `qkeys` explicitly is how Stage B's held-out analysis and the
    Stage-A/Stage-B comparison stay on identical query sets: an aggregate taken
    over "whatever this run file happened to contain" is not comparable to one
    taken over a fixed list, and the difference is invisible in the output.

    A requested qkey missing from the run file is scored as an **empty
    ranking**, not skipped — a config that failed to retrieve for a query really
    did score 0 there, and dropping it would quietly reward the failure.
    """
    keys = list(qkeys) if qkeys is not None else sorted(run.rankings)
    per_query = [score_query(run.config, qkey, run.rankings.get(qkey, ()), qrels)
                 for qkey in keys]
    coverages = [s.coverage_at_10 for s in per_query
                 if s.coverage_at_10 is not None]
    return ConfigScore(
        config=run.config, k1=run.k1, b=run.b,
        n_queries=len(per_query),
        n_topics=len({s.topic_id for s in per_query}),
        judged_at_10_mean=mean(coverages),
        retrieved_mean=mean(float(s.retrieved) for s in per_query),
        duplicates=run.duplicates,
        by_query={name: mean(v for v in (s.metrics.get(name)
                                         for s in per_query) if v is not None)
                  for name in METRIC_NAMES},
        by_topic={name: mean_of_topic_means(per_query, name)
                  for name in METRIC_NAMES},
        defined={name: sum(1 for s in per_query
                           if s.metrics.get(name) is not None)
                 for name in METRIC_NAMES},
        per_query=tuple(per_query),
    )


def score_all(runs: Sequence[RunFile], qrels: Qrels,
              qkeys: Sequence[str] | None = None) -> list[ConfigScore]:
    """Score every config over the same query set, best-primary-first.

    The **full** matrix, always (PLAN §7.4): every grid cell, both gain
    conventions, all secondaries. Reporting only the winner is how a sweep
    becomes unfalsifiable — the neighbouring cells are the evidence that the
    winner is a peak rather than noise.
    """
    if qkeys is None:
        qkeys = sorted({qkey for run in runs for qkey in run.rankings})
    scored = [score_run(run, qrels, qkeys) for run in runs]
    scored.sort(key=lambda s: (-(s.primary if s.primary is not None else -1.0),
                               s.config))
    return scored


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_scores_csv(path: Path, scores: Sequence[ConfigScore]) -> Path:
    """Write `scores.csv` — one row per grid cell, every metric."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for score in scores:
            writer.writerow(score.to_row())
    tmp.replace(path)
    return path


def write_per_query_csv(path: Path, scores: Sequence[ConfigScore]) -> Path:
    """Write the per-(config, query) values behind the aggregates.

    Not in PLAN §4.2's file list, and added deliberately: the paired tests in
    §6.4 are computed from exactly these numbers, so persisting them makes the
    statistics auditable from an artifact instead of only reproducible by
    re-running the scorer against the qrels.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["config", "qkey", "topic_id", "retrieved", "judged_at_10",
               *METRIC_NAMES]
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for score in scores:
            for q in score.per_query:
                writer.writerow([q.config, q.qkey, q.topic_id, q.retrieved,
                                 q.judged_at_10,
                                 *[_fmt(q.metrics.get(m)) for m in METRIC_NAMES]])
    tmp.replace(path)
    return path


#: Prepended verbatim to `scores.md`. The plan requires the deflation caveat to
#: travel with the numbers (PLAN §5.5) — a reader who only opens the artifact
#: must not be able to quote an absolute nDCG without seeing this.
SCORES_MD_PREAMBLE = """\
> **Absolute values are deflated; only differences between configs are
> meaningful.** The ideal DCG for every query is built from the *topic's* whole
> pooled qrel (top-10 grades), not from that query's own ranking, so the ideal
> routinely contains chunks a single keyword query cannot retrieve. This is
> deliberate (PLAN §5.5): it holds the denominator constant across configs and
> across a topic's queries, which is what makes the paired test in `stats.json`
> a test of ranking movement. Do **not** compare these numbers to a published
> nDCG. `Recall@10` / `MAP@30` divide by the topic's total judged-relevant
> count, and are deflated for the same reason.
>
> `judged@10` is the mean judged fraction of the top 10. Unjudged chunks score
> gain 0, so a value below 1.0 means part of a config's score is a coverage
> artifact rather than a ranking result.
>
> **Two exceptions to the deflation caveat:** `gp10` and `p10_bin2` are *not*
> normalized by any ideal — they divide by a flat 10 slots — so their absolute
> values are interpretable and comparable across topics. They are also
> **rank-indifferent within the top 10**: they measure the quality of the
> retrieved *set*, while nDCG@10 measures its *ordering*. A cell where nDCG moves
> but these do not merely reshuffled the same ten chunks. Both were added
> 2026-07-31 as secondary/exploratory measures and are **not** part of PLAN
> §3.3's pre-registered confirmatory family.
"""


def render_scores_md(scores: Sequence[ConfigScore], *, run_id: str,
                     prompt_version: str | None, qrels: Qrels,
                     query_set: str = "all", n_queries: int | None = None
                     ) -> str:
    """Render `scores.md`: the caveat, the qrel's shape, then the full matrix."""
    lines = [f"# BM25 k1/b score matrix — `{run_id}`", ""]
    lines.append(f"- prompt version: `{prompt_version or 'unknown'}`")
    lines.append(f"- query set: {query_set}"
                 + (f" (n={n_queries})" if n_queries is not None else ""))
    lines.append(f"- qrels: {qrels.n_judged()} judged (topic, chunk) pairs over "
                 f"{len(qrels.topics)} topics; grade distribution "
                 f"{qrels.distribution()}")
    lines.append(f"- primary metric: `{PRIMARY_METRIC}` "
                 f"({METRIC_LABELS[PRIMARY_METRIC]})")
    lines += ["", SCORES_MD_PREAMBLE, ""]

    header = ["config", "k1", "b", "n", "judged@10"]
    for name in METRIC_NAMES:
        header += [name, f"{name} (topic)"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for score in scores:
        row = [f"`{score.config}`",
               "" if score.k1 is None else f"{score.k1:g}",
               "" if score.b is None else f"{score.b:g}",
               str(score.n_queries),
               _fmt(score.judged_at_10_mean, 3)]
        for name in METRIC_NAMES:
            row += [_fmt(score.by_query.get(name), 4),
                    _fmt(score.by_topic.get(name), 4)]
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Metric key", ""]
    for name in METRIC_NAMES:
        lines.append(f"- `{name}` — {METRIC_LABELS[name]}")
    lines += ["", "`<metric> (topic)` is the mean of per-topic means "
              "(PLAN §5.5's robustness aggregate); topics contribute 3-16 "
              "queries each, so it and the query mean can disagree.", ""]
    return "\n".join(lines)


def summary_lines(scores: Sequence[ConfigScore]) -> list[str]:
    """`[NDCG]`-prefixed log lines, one per config, best first (PLAN §5.6).

    Driven off `METRIC_NAMES` rather than a hand-written f-string, so a metric
    added to the table cannot be missing from the log — the log is the live view
    of a multi-hour run, and a metric only visible in the final CSV is a metric
    nobody watches.
    """
    out = []
    for score in scores:
        fields = " ".join(f"{name}={_fmt(score.by_query.get(name), 4)}"
                          for name in METRIC_NAMES)
        out.append(f"[NDCG] {score.config} n={score.n_queries} {fields} "
                   f"judged@10={_fmt(score.judged_at_10_mean, 3)}")
    return out
