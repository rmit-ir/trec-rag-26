"""Per-topic pooled judging set (PLAN §5.5).

The single most consequential design decision in the harness lives here: every
config's depth-30 hits for every query of a topic are unioned into **one**
per-topic pool, judged **once**, and every config is then scored against that
shared qrel.

Why per *topic* and not per query or per config:

- **Per config would be scientifically invalid.** Judging config X's hits alone
  and config Y's hits alone means each config is scored against a qrel built
  from its own output, so a config that retrieves fewer judged-relevant chunks
  cannot be penalised for it. Pooling is what makes the comparison fair.
- **Per topic, not per query, because the cache key is topic-level**
  (`(prompt_version, topic_id, chunk_id)`, PLAN §5.3). A topic has 3–16 keyword
  queries whose rankings overlap heavily, and the judge target is the topic
  narrative — not the keyword string — so the same (topic, chunk) pair judged for
  query A *is* the judgment for query B. That identity is the entire reuse
  economy: it is why Stage B's 4x1063 sweep costs ~15–22 k new calls instead of
  ~120 k, and why Stage A's judgments are free in Stage B.

**[measured]** union over 6 configs at depth 30 = 43.3 chunks/query vs 30 for a
single config (1.44x), extrapolating to ~1.7–2.2x (~50–65 unique chunks/query)
over the 26-cell grid — configs mostly reorder a shared candidate set. That
sublinearity is what makes pooled judging affordable at all.

Stdlib only, and no index access: this module consumes the rankings
`searcher.ChunkSearcher.run_config` already returned, which is what lets the
pooling logic be tested against scripted rankings with no JVM (PLAN §7.3).
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .extract import QueryRec, sha256_text
from .logging_setup import get_logger

log = get_logger("pool")

DEFAULT_DEPTH = 30

#: `{config_key: {qkey: [(chunk_id, score), ...]}}` — exactly what a sweep
#: accumulates from `ChunkSearcher.run_config`.
Rankings = Mapping[str, Mapping[str, Sequence[tuple[str, float]]]]


class PoolError(RuntimeError):
    """The rankings and the query set describe different experiments.

    Raised rather than warned-about: a `qkey` present in a run file but absent
    from the query set means the two artifacts came from different extractions,
    and quietly dropping it would shrink the judged pool — deflating every
    config's recall in a way no score-table reader could see.
    """


@dataclass(frozen=True)
class PoolEntry:
    """One row of `pool.jsonl` (PLAN §4.2).

    `first_seen_config` is provenance with a purpose: it answers "which grid cell
    contributed this chunk" for free, so a reader can tell a chunk the whole grid
    agrees on from one a single extreme cell dragged in. It is deterministic —
    configs are visited in the order the sweep ran them — so the file is
    byte-reproducible.

    `text_sha256` is filled in once the chunk's text has been fetched from the
    index; it pins the *exact* passage the judge was shown, which is the only way
    to detect later that a cached judgment refers to text that has since changed.
    """

    topic_id: str
    chunk_id: str
    first_seen_config: str
    text_sha256: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.topic_id, self.chunk_id)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PoolStats:
    """Pool-size numbers the run manifest records (PLAN §7.2).

    `inflation_vs_single` is the **[measured]** 1.44x-at-6-configs quantity
    extrapolated in PLAN §5.5 to 1.7–2.2x. Recording it per run turns that
    extrapolation into an observation: a value near 1.0 would mean the configs
    are not moving rankings at all (so the sweep has nothing to find), and a
    value near the config count would mean they barely overlap (so the judging
    budget estimate is wrong by the same factor).
    """

    configs: int
    queries: int
    topics: int
    unique_pairs: int
    per_query_mean: float
    per_topic_mean: float
    single_config_mean: float
    inflation_vs_single: float

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def _topic_of(queries: Sequence[QueryRec]) -> dict[str, str]:
    """`qkey -> topic_id`, rejecting a qkey that maps to two topics."""
    mapping: dict[str, str] = {}
    for rec in queries:
        known = mapping.setdefault(rec.qkey, rec.topic_id)
        if known != rec.topic_id:
            raise PoolError(
                f"qkey {rec.qkey} maps to both {known} and {rec.topic_id}")
    return mapping


def build_pool(runs: Rankings, queries: Sequence[QueryRec],
               depth: int = DEFAULT_DEPTH) -> dict[str, set[str]]:
    """`topic_id -> {chunk_id}`: the union to judge (PLAN §5.5's signature).

    The union spans **both** axes at once — every config *and* every query of the
    topic — which is the property that makes one judgment serve every config and
    every query in that topic.

    `depth` truncates each ranking before unioning. It is applied here rather
    than trusted from the searcher because a run file may legitimately hold more
    than `depth` hits (a re-used Stage-B run at a deeper `k`), and judging beyond
    depth 30 would inflate the pool — and the bill — for chunks no nDCG@10
    comparison can reward.
    """
    if depth < 1:
        raise ValueError(f"depth must be >= 1, got {depth}")
    topic_of = _topic_of(queries)
    pool: dict[str, set[str]] = defaultdict(set)
    for config, per_query in runs.items():
        for qkey, ranking in per_query.items():
            topic_id = topic_of.get(qkey)
            if topic_id is None:
                raise PoolError(
                    f"config {config} has a ranking for unknown qkey {qkey!r} "
                    "— the run files and the query set come from different "
                    "extractions; re-run extract-queries or the sweep")
            for chunk_id, _score in list(ranking)[:depth]:
                pool[topic_id].add(str(chunk_id))
    return dict(pool)


def pool_entries(runs: Rankings, queries: Sequence[QueryRec],
                 depth: int = DEFAULT_DEPTH,
                 texts: Mapping[str, str] | None = None) -> list[PoolEntry]:
    """`pool.jsonl` rows: the pool with `first_seen_config` and text digests.

    Same union as `build_pool` — deliberately re-derived from the same traversal
    rather than post-processed from its output, so the two can never disagree
    about what is in the pool — plus the provenance `build_pool`'s `set[str]`
    return type cannot carry.

    Rows are sorted by `(topic_id, chunk_id)`, not by discovery order, so the
    file diffs cleanly between runs while `first_seen_config` still records
    discovery.
    """
    topic_of = _topic_of(queries)
    first_seen: dict[tuple[str, str], str] = {}
    for config, per_query in runs.items():
        for qkey, ranking in per_query.items():
            topic_id = topic_of.get(qkey)
            if topic_id is None:
                raise PoolError(
                    f"config {config} has a ranking for unknown qkey {qkey!r}")
            for chunk_id, _score in list(ranking)[:depth]:
                first_seen.setdefault((topic_id, str(chunk_id)), config)
    entries = [
        PoolEntry(topic_id=topic_id, chunk_id=chunk_id,
                  first_seen_config=config,
                  text_sha256=(None if texts is None or chunk_id not in texts
                               else sha256_text(texts[chunk_id])))
        for (topic_id, chunk_id), config in first_seen.items()]
    entries.sort(key=lambda e: (e.topic_id, e.chunk_id))
    return entries


def pool_stats(runs: Rankings, queries: Sequence[QueryRec],
               depth: int = DEFAULT_DEPTH) -> PoolStats:
    """Pool sizes and the inflation ratio, for the manifest and the log.

    `single_config_mean` is the mean ranking length actually observed, not
    `depth`: a query whose keyword string retrieves fewer than 30 chunks would
    otherwise understate inflation, making the pool look more redundant than it
    is and the judge-cost projection optimistic.
    """
    topic_of = _topic_of(queries)
    per_query: dict[str, set[str]] = defaultdict(set)
    lengths: list[int] = []
    for config, per_config in runs.items():
        for qkey, ranking in per_config.items():
            if qkey not in topic_of:
                raise PoolError(
                    f"config {config} has a ranking for unknown qkey {qkey!r}")
            truncated = list(ranking)[:depth]
            lengths.append(len(truncated))
            per_query[qkey].update(str(cid) for cid, _ in truncated)
    pool = build_pool(runs, queries, depth=depth)
    unique_pairs = sum(len(chunks) for chunks in pool.values())
    query_mean = (sum(len(v) for v in per_query.values()) / len(per_query)
                  if per_query else 0.0)
    single_mean = sum(lengths) / len(lengths) if lengths else 0.0
    return PoolStats(
        configs=len(runs),
        queries=len(per_query),
        topics=len(pool),
        unique_pairs=unique_pairs,
        per_query_mean=query_mean,
        per_topic_mean=(unique_pairs / len(pool)) if pool else 0.0,
        single_config_mean=single_mean,
        inflation_vs_single=(query_mean / single_mean) if single_mean else 0.0,
    )


def log_pool(stats: PoolStats, pool: Mapping[str, set[str]]) -> None:
    """Emit the `[POOL]` lines PLAN §5.6 requires: total plus per-topic extremes.

    The extremes matter more than the mean: a topic whose pool is an order of
    magnitude larger than the rest is where a runaway judge bill would come from,
    and it is invisible in an average.
    """
    log.info("[POOL] %d unique (topic, chunk) pairs over %d topics from "
             "%d configs x %d queries at depth-truncated rankings",
             stats.unique_pairs, stats.topics, stats.configs, stats.queries)
    log.info("[POOL] per_query_mean=%.1f single_config_mean=%.1f "
             "inflation_vs_single=%.2fx per_topic_mean=%.1f",
             stats.per_query_mean, stats.single_config_mean,
             stats.inflation_vs_single, stats.per_topic_mean)
    if pool:
        sizes = sorted(((len(chunks), topic_id)
                        for topic_id, chunks in pool.items()))
        log.info("[POOL] smallest topic %s=%d chunks; largest %s=%d chunks",
                 sizes[0][1], sizes[0][0], sizes[-1][1], sizes[-1][0])


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def write_pool(path: Path, entries: Sequence[PoolEntry]) -> int:
    """Write `pool.jsonl` atomically (tmp + replace), returning the row count.

    Atomic because `judge-pool` reads this file to decide what to judge: a
    half-written pool would silently under-judge the run, and the resulting score
    matrix would look complete.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry.to_json(), ensure_ascii=False,
                                    sort_keys=True) + "\n")
    tmp.replace(path)
    return len(entries)


def read_pool(path: Path) -> list[PoolEntry]:
    """Read `pool.jsonl` back — the interface `judge-pool`/`score` consume.

    Reading the persisted pool rather than re-deriving it from the run files is
    what makes the judged set an artifact instead of a computation: a resumed
    `judge-pool` judges exactly the pool the sweep wrote, even if the run files
    were later re-generated.
    """
    entries: list[PoolEntry] = []
    for lineno, line in enumerate(Path(path).read_text(
            encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PoolError(f"{path}:{lineno}: not valid JSON ({exc})") from exc
        entries.append(PoolEntry(
            topic_id=row["topic_id"], chunk_id=row["chunk_id"],
            first_seen_config=row.get("first_seen_config", ""),
            text_sha256=row.get("text_sha256")))
    return entries


# ---------------------------------------------------------------------------
# TREC run files
# ---------------------------------------------------------------------------
def write_trec_run(path: Path, rankings: Mapping[str, Sequence[tuple[str, float]]],
                   tag: str, depth: int = DEFAULT_DEPTH) -> int:
    """Write one config's rankings as a TREC 6-column run file.

    `qkey Q0 chunk_id rank score tag`, rank 1-based, ranks re-derived from
    position rather than copied from the searcher — so a run file's ranks are
    always dense and 1-based even if a ranking was truncated or filtered.

    Written atomically, because `search-sweep`'s idempotence rule is "skip a
    config whose run file exists" (PLAN §5.6): a truncated file left by a crash
    would be treated as a completed config and silently sweep a short ranking.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    lines = 0
    with tmp.open("w", encoding="utf-8") as handle:
        for qkey in sorted(rankings):
            for rank, (chunk_id, score) in enumerate(
                    list(rankings[qkey])[:depth], start=1):
                handle.write(f"{qkey} Q0 {chunk_id} {rank} {score:.6f} "
                             f"{tag}\n")
                lines += 1
    tmp.replace(path)
    return lines


def read_trec_run(path: Path) -> dict[str, list[tuple[str, float]]]:
    """Parse a TREC run file back into `qkey -> [(chunk_id, score)]`.

    Needed for idempotent resumption: `search-sweep` skips a config whose run
    file exists, so the pool must be buildable from files an earlier invocation
    wrote. Rankings are re-sorted by the file's rank column rather than trusting
    line order, so a hand-edited or concatenated run file still pools correctly.
    """
    ranked: dict[str, list[tuple[int, str, float]]] = defaultdict(list)
    for lineno, line in enumerate(Path(path).read_text(
            encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            raise PoolError(
                f"{path}:{lineno}: expected a 6-column TREC run line, got "
                f"{line!r}")
        qkey, _q0, chunk_id, rank, score = parts[:5]
        try:
            ranked[qkey].append((int(rank), chunk_id, float(score)))
        except ValueError as exc:
            raise PoolError(
                f"{path}:{lineno}: rank/score are not numeric ({exc})") from exc
    return {qkey: [(chunk_id, score)
                   for _rank, chunk_id, score in sorted(rows)]
            for qkey, rows in ranked.items()}
