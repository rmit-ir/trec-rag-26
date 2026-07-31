"""Disagreement-triggered consensus qrels across judge prompts (PLAN §6.2b).

The single-judge qrel that `judge-pool` writes carries the systematic bias of
*one* prompt. The temperature sweep (`worklogs/2026-07-31-judge-temperature-
sweep.md`) measured the consequence directly: even at temperature 0 the judge
reproduces its own grade only ~84 % of the time, and a prompt that is
consistently too harsh or too lenient (e.g. `umbrela-v1`'s grade-1 collapse) is
wrong the *same* way on every resample, so resampling one prompt cannot fix it.

An ensemble of **different** prompts, each held at temperature 0, attacks both
error sources at once: each judge stays at its most reproducible setting, and
the prompts' decorrelated systematic biases cancel when combined. This module is
the pure combiner — it never calls Bedrock and never reads the index; it takes
the per-prompt grade mappings `judge-pool` already produced and folds them into
one consensus label set.

**The cascade (the operator's design, not the textbook vote).** Judging every
pair with a third prompt is wasteful: two judges on a 0–3 scale differ by one
grade constantly (adjacent-grade noise) and by two or more only rarely (genuine
conflict). So:

1. Two prompts judge the whole pool (the primary — the Stage-A judge — and one
   secondary).
2. For a pair the two agree on within `CONFLICT_DELTA - 1` grades, the consensus
   is settled here for free: the conservative rounded mean, `(a + b) // 2`, which
   for adjacent grades rounds *down* (2 and 3 → 2), never inventing relevance the
   two judges did not both see.
3. Only pairs `>= CONFLICT_DELTA` grades apart escalate: those, and only those,
   are written to a filtered tiebreak pool for a third prompt to judge. The
   third grade breaks the tie by **median of the three**.

Passing this through the existing tooling is deliberate: the escalation set is
emitted as a normal `pool.jsonl` + `pool-texts.jsonl`, so the third prompt is
judged by the same metered, cached, resumable `judge-pool` command as everything
else — this module adds no path to the model. Scoring then runs against the
published 4-column TREC qrels this module writes (`load_qrels_trec`), whose
loader does not enforce single-prompt identity precisely because the consensus
label set legitimately spans prompts.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping

#: Grades this far apart (or further) are a genuine conflict that escalates to
#: the tiebreak prompt; anything closer is adjacent-grade noise the two judges
#: are treated as agreeing on (PLAN §6.2b; operator decision 2026-07-31). A
#: 0–3 scale makes 2 the natural line: |Δ|==1 is one rubric step, |Δ|>=2 crosses
#: the relevant/not-relevant boundary the primary metric binarizes at.
CONFLICT_DELTA = 2

#: Per-pair outcome labels, for the summary counts and the manifest.
STATUS_AGREE = "agree"          # within CONFLICT_DELTA: settled by rounded mean
STATUS_RESOLVED = "resolved"    # conflict, broken by the tiebreak's median
STATUS_PENDING = "conflict_pending"  # conflict, tiebreak grade not yet available
STATUS_SINGLE = "single"        # only one judge graded it (the other skipped)

GradeMap = Mapping[str, Mapping[str, int]]


@dataclass(frozen=True)
class PairConsensus:
    """The consensus verdict for one (topic, chunk) pair.

    `grades` keeps every available judge grade in primary→secondary→tiebreak
    order so the manifest can show *why* a pair resolved the way it did — a
    consensus label with no trace of the votes behind it is unfalsifiable.
    `consensus` is `None` only for `STATUS_PENDING`: a conflict whose tiebreak
    grade does not exist yet, which is exactly the set the escalation pool holds.
    """

    topic_id: str
    chunk_id: str
    grades: tuple[int, ...]
    consensus: int | None
    status: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.topic_id, self.chunk_id)


@dataclass
class ConsensusResult:
    """Everything the CLI needs from one combine pass.

    `grades` is the resolved consensus label set in `Qrels` shape (unresolved
    conflicts are absent — they score as unjudged until the tiebreak lands,
    which keeps a half-finished cascade honest rather than fabricating a grade).
    `pending` is the escalation set: the (topic, chunk) pairs a third prompt must
    judge. `pairs` is the full audit trail, one `PairConsensus` per pair.
    """

    grades: dict[str, dict[str, int]] = field(default_factory=dict)
    pending: list[tuple[str, str]] = field(default_factory=list)
    pairs: list[PairConsensus] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)

    def n_resolved(self) -> int:
        return sum(len(v) for v in self.grades.values())

    def distribution(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for chunks in self.grades.values():
            for grade in chunks.values():
                counts[grade] = counts.get(grade, 0) + 1
        return dict(sorted(counts.items()))


def median_of_three(a: int, b: int, c: int) -> int:
    """The middle of three grades — the tiebreak rule for a genuine conflict.

    Median, not mean: with three votes on a 0–3 scale the median is always an
    actual grade one judge assigned, so it cannot land between rubric levels the
    way `round(mean)` can, and a single outlier judge cannot drag it.
    """
    return sorted((a, b, c))[1]


def _agree_grade(a: int, b: int) -> int:
    """Consensus grade for two judges within `CONFLICT_DELTA` (rounded mean).

    Floor division is a deliberate round-*down* for the adjacent-grade case
    (2 and 3 → 2, not 3): when two judges split on how relevant a passage is, the
    conservative label is the lower one — the experiment would rather understate
    relevance than credit a config for a chunk only one judge rated highly.
    """
    return (a + b) // 2


def combine_pair(topic_id: str, chunk_id: str, primary: int | None,
                 secondary: int | None,
                 tiebreak: int | None = None) -> PairConsensus:
    """Fold one pair's available judge grades into a single verdict.

    Order of the guards is the cascade: a missing judge (`None`) means that
    prompt skipped the pair (a parse failure — PLAN §5.4), which is why a
    single-judge pair falls back to the one grade it has rather than being
    dropped (dropping it would deflate `judged@10` for every config).
    """
    if primary is None and secondary is None:
        # Neither judge produced a grade; nothing to combine. Callers never pass
        # this (the pair would not be in either qrel), but be explicit.
        return PairConsensus(topic_id, chunk_id, (), None, STATUS_SINGLE)
    if primary is None or secondary is None:
        only = primary if primary is not None else secondary
        assert only is not None  # narrowing for type-checkers
        return PairConsensus(topic_id, chunk_id, (only,), only, STATUS_SINGLE)
    if abs(primary - secondary) < CONFLICT_DELTA:
        return PairConsensus(topic_id, chunk_id, (primary, secondary),
                             _agree_grade(primary, secondary), STATUS_AGREE)
    # Genuine conflict.
    if tiebreak is None:
        return PairConsensus(topic_id, chunk_id, (primary, secondary), None,
                             STATUS_PENDING)
    return PairConsensus(topic_id, chunk_id, (primary, secondary, tiebreak),
                         median_of_three(primary, secondary, tiebreak),
                         STATUS_RESOLVED)


def build_consensus(primary: GradeMap, secondary: GradeMap,
                    tiebreak: GradeMap | None = None) -> ConsensusResult:
    """Combine two (optionally three) per-prompt grade maps into one qrel.

    The union of the primary's and secondary's pairs is walked in sorted order,
    so the escalation pool and the consensus qrel are byte-reproducible. A pair
    the two judges conflict on is resolved when `tiebreak` carries its grade and
    left `pending` otherwise — so this same function drives *both* passes of the
    cascade: call it with `tiebreak=None` to discover the escalation set, then
    again with the tiebreak grades to finalize.
    """
    result = ConsensusResult()
    keys: set[tuple[str, str]] = set()
    for gmap in (primary, secondary):
        for topic_id, chunks in gmap.items():
            for chunk_id in chunks:
                keys.add((topic_id, chunk_id))
    for topic_id, chunk_id in sorted(keys):
        p = primary.get(topic_id, {}).get(chunk_id)
        s = secondary.get(topic_id, {}).get(chunk_id)
        t = None if tiebreak is None else tiebreak.get(topic_id, {}).get(chunk_id)
        pair = combine_pair(topic_id, chunk_id, p, s, t)
        result.pairs.append(pair)
        result.counts[pair.status] += 1
        if pair.consensus is not None:
            result.grades.setdefault(topic_id, {})[chunk_id] = pair.consensus
        elif pair.status == STATUS_PENDING:
            result.pending.append((topic_id, chunk_id))
    return result


def trec_qrel_lines(grades: GradeMap) -> list[str]:
    """4-column TREC qrel lines (`topic 0 chunk grade`), sorted for stable diffs.

    Matches `store.JudgmentCache.qrel_lines` so the consensus label set is the
    same publication form as a single-prompt one; `metrics.load_qrels_trec` reads
    it back without the single-prompt identity check that a `.jsonl` snapshot
    would (correctly) impose.
    """
    lines: list[str] = []
    for topic_id in sorted(grades):
        chunks = grades[topic_id]
        for chunk_id in sorted(chunks):
            lines.append(f"{topic_id} 0 {chunk_id} {chunks[chunk_id]}")
    return lines
