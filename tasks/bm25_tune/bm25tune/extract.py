"""Labeled search log -> query set, observed hits, and the judge's passage text
(PLAN §2.1, §5.1).

This module owns **the exact text the judge sees** and **the exact query set the
sweep runs**. Both are silent-corruption surfaces:

- If `strip_page_prefix` gets it wrong, every judgment for the affected chunk is
  made on a passage prefixed by a leaked `"Page N of document: <title>"` header
  — a header that contains topical words and would inflate grades in a way no
  downstream metric could detect. Hence: strip by the recorded `prefix_chars`
  when we have it, by regex when we don't, and **pass through unmodified and
  count it** when neither applies (PLAN §5.1 / R4), so the miss is visible in the
  `[PREFIX-MISS]` log line and the manifest rather than silent.
- If the query set drifts, the sweep and the published qrels describe different
  experiments. So `load_keyword_queries` filters, dedupes, and *sorts*
  deterministically, and every derived set (the Stage-A subsample, the
  calibration sample) is persisted to disk so a re-run is byte-reproducible
  rather than merely "same seed, probably".

Counts this module is expected to produce from the committed input (PLAN §2.1;
asserted by `cli.py verify-inputs`, not just documented): 2143 rows total, 1070
`engine == "keyword"`, 119 topics, **1063 unique (topic, query) pairs**, 9208
keyword hits, 8551 unique chunk ids, 8580 unique (topic, chunk) pairs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from .logging_setup import get_logger

log = get_logger("extract")

#: The leaked chunk header aus_agent's search layer prepends to pages > 1.
#: `[measured]` all 3890 keyword hits with `prefix_chars > 0` match it and the
#: match length equals `prefix_chars` exactly — but the plan records 31 outliers
#: across the wider corpus, so the passthrough branch stays and stays counted.
PAGE_PREFIX_RE = re.compile(r"Page \d+ of document: [^\n]*\n\n")

KEYWORD_ENGINE = "keyword"
#: PLAN §2.1: agent labels are selection outcomes, not relevance. Mapped to
#: calibration strata (PLAN §3.1) and nothing else.
POSITIVE_LABELS = frozenset({"positive"})
NEGATIVE_LABELS = frozenset({"negative"})
UNJUDGED_LABELS = frozenset({"unjudged"})


class ExtractError(RuntimeError):
    """The input file does not match the schema PLAN §2.1 describes."""


def _sha1_12(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def sha256_text(text: str) -> str:
    """`sha256` hex of a string — the digest recorded for narratives/passages."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parent_docid(chunk_id: str) -> str:
    """`shard_00122_5199_p1` -> `shard_00122_5199` (PLAN §1).

    Unambiguous because the trailing component is pure digits, so a `_p` inside
    a shard name could not be mistaken for the page separator.
    """
    return chunk_id.rsplit("_p", 1)[0]


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class QueryRec:
    """One (topic, keyword-query) pair the sweep will run.

    `qkey` is the run-file / ranking-dict identity: `topic_id::sha1(query)[:12]`.
    It is derived from the query *text*, not from the row's position in the input,
    so the same pair keeps the same tag across re-extractions, across stages, and
    in the TREC run files — which is what lets Stage B reuse Stage A's artifacts.

    `k_orig` is the `k` aus_agent originally requested. Recorded for provenance
    only: the sweep always retrieves at depth 30 (PLAN §5.5). Where duplicate
    rows of the same pair disagree on `k` (**[measured]** 6 pairs do), the
    maximum is kept — the deeper request is the one whose hits the labeled file
    actually contains.
    """

    topic_id: str
    topic: str
    query: str
    qkey: str
    k_orig: int

    @classmethod
    def make(cls, topic_id: str, topic: str, query: str,
             k_orig: int) -> "QueryRec":
        return cls(topic_id=topic_id, topic=topic, query=query,
                   qkey=f"{topic_id}::{_sha1_12(query)}", k_orig=k_orig)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ObservedHit:
    """One hit aus_agent actually saw, with its text already stripped.

    "Observed" is the operative word: these are the 9208 keyword hits present in
    the labeled file, used for calibration sampling (PLAN §3.1) and the
    agent-label agreement smell test (PLAN §3.4). They are **not** the sweep's
    pool — that comes from the live index — so `text` here is the historical
    text, kept because it is free and lets calibration run with zero index
    access.

    `prefix_stripped` records whether the header removal actually fired and
    `prefix_anomaly` names any disagreement between the recorded `prefix_chars`
    and the text, so the `[PREFIX-MISS]` count in the manifest is derived from
    data rather than re-inferred — and so a specific pair can be inspected
    rather than only counted.
    """

    topic_id: str
    topic: str
    query: str
    chunk_id: str
    parent_docid: str
    rank: int
    score: float
    label: str
    reason: str
    text: str
    prefix_stripped: bool
    prefix_anomaly: str | None = None

    @property
    def agent_class(self) -> str:
        """`"positive" | "negative" | "unjudged"` — the calibration stratum.

        Named `agent_class`, not `relevance`, on purpose: PLAN §2.1 is emphatic
        that these are agent *selection* outcomes (non-duplication, context
        budget) and never ground truth.
        """
        if self.label in POSITIVE_LABELS:
            return "positive"
        if self.label in NEGATIVE_LABELS:
            return "negative"
        return "unjudged"

    def to_json(self) -> dict[str, object]:
        data = asdict(self)
        data["agent_class"] = self.agent_class
        data["text_sha256"] = sha256_text(self.text)
        return data


# ---------------------------------------------------------------------------
# Passage text
# ---------------------------------------------------------------------------
def strip_page_prefix(text: str,
                      prefix_chars: int | None) -> tuple[str, bool]:
    """Remove the leaked `"Page N of document: <title>\\n\\n"` header.

    Three branches, in priority order (PLAN §5.1):

    1. **`prefix_chars` known and corroborated** (labeled hits): slice
       `text[n:]`. **[measured]** all 3890 keyword hits with `prefix_chars > 0`
       have it equal to a `PAGE_PREFIX_RE` match length exactly, so this is the
       branch that fires on the real input.
    2. **Otherwise, regex** (pool chunks fetched fresh from the index, which
       carry no `prefix_chars` at all): strip a match at position 0.
    3. **Neither applies**: return the text unmodified with `False`. The caller
       counts these and logs `[PREFIX-MISS]`; PLAN R4 puts the worst case at
       ~0.3 % of judged texts, and the point is that it is *visible* noise.

    Returns `(text, stripped)`.

    **A resolved contradiction in the plan.** §5.1 says branch 1 trusts
    `prefix_chars` unconditionally, while §2.1/R4 say the 31 known outliers
    "land here" in the passthrough branch and are counted under
    `[PREFIX-MISS]`. Both cannot hold: an unconditional slice would consume
    those outliers silently and the miss counter would always read zero. We
    follow **R4**, so `prefix_chars` is used only when a header actually starts
    the text, because the two failure modes are not symmetric:

    - leaving a header in is the documented, bounded, *visible* R4 outcome;
    - slicing on a wrong `prefix_chars` amputates real evidence from the middle
      of a passage, changing what the judge reads with nothing downstream able
      to detect it.

    On the committed input the two readings are behaviourally identical (every
    `prefix_chars` is corroborated), so no measured fact changes.
    """
    if prefix_chars:
        match = PAGE_PREFIX_RE.match(text)
        if (match is not None and match.end() == prefix_chars
                and prefix_chars < len(text)):
            return text[prefix_chars:], True
    match = PAGE_PREFIX_RE.match(text)
    if match is not None and match.end() < len(text):
        return text[match.end():], True
    return text, False


def prefix_anomaly(text: str, prefix_chars: int | None) -> str | None:
    """Name the way a hit's `prefix_chars` disagrees with its text, or `None`.

    `strip_page_prefix` trusts `prefix_chars` (branch 1) because it is what the
    agent's own layer prepended — but a *wrong* `prefix_chars` would then
    amputate real evidence from the passage, and nothing downstream could tell.
    This is the detector for that, and it is the substance behind the
    `[PREFIX-MISS]` count in the manifest (PLAN R4): without it, "0 misses"
    would only mean "no slice ran off the end of a string", which is vacuous.

    **[measured]** every one of the 3890 keyword hits with `prefix_chars > 0`
    slices exactly a `PAGE_PREFIX_RE` match, so the real input reports zero
    anomalies — which is why `verify-inputs` can assert it. PLAN §2.1 records 31
    outliers against a pattern it does not spell out; if a future export
    reintroduces them, this is what surfaces them by name instead of silently
    trimming 30 characters off a passage.

    Returns one of `"out_of_range"`, `"not_a_header"`, `"residual_header"`, or
    `None`.
    """
    if prefix_chars:
        if prefix_chars >= len(text):
            return "out_of_range"
        match = PAGE_PREFIX_RE.match(text)
        if match is None or match.end() != prefix_chars:
            return "not_a_header"
    stripped, _ = strip_page_prefix(text, prefix_chars)
    if PAGE_PREFIX_RE.match(stripped) is not None:
        return "residual_header"
    return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def iter_rows(path: Path) -> Iterator[dict]:
    """Stream the labeled JSONL, raising on a malformed line with its number.

    The file is ~47 MB; streaming keeps `verify-inputs` cheap. A malformed line
    is fatal rather than skipped: a partial query set that *looks* fine is worse
    than a hard stop, because the row counts in `verify-inputs` are how we
    detect exactly this.
    """
    with Path(path).open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExtractError(
                    f"{path}:{lineno}: not valid JSON ({exc})") from exc


def load_keyword_queries(path: Path) -> list[QueryRec]:
    """The 1063 unique keyword (topic, query) pairs, deterministically ordered.

    Filters `engine == "keyword"` (dropping the 1073 semantic rows), dedupes on
    `(query_id, search_query)`, and sorts by `(topic index, query text)` —
    numeric topic order, so `rag2026-2` precedes `rag2026-10` in every artifact
    a human reads.

    Raises `ExtractError` if a topic id carries two different narratives:
    `topic` is the judge target, so one topic meaning two things would make the
    topic-level cache key (PLAN §5.3) unsound.
    """
    narratives: dict[str, str] = {}
    best_k: dict[tuple[str, str], int] = {}
    for row in iter_rows(path):
        if row.get("engine") != KEYWORD_ENGINE:
            continue
        topic_id = row["query_id"]
        topic = row["topic"]
        query = row["search_query"]
        known = narratives.setdefault(topic_id, topic)
        if known != topic:
            raise ExtractError(
                f"{topic_id} carries two different narratives — the topic is "
                "the judge target, so this would make the topic-level cache "
                "key ambiguous")
        key = (topic_id, query)
        k = int(row.get("k") or 0)
        best_k[key] = max(best_k.get(key, 0), k)

    recs = [QueryRec.make(topic_id, narratives[topic_id], query, k)
            for (topic_id, query), k in best_k.items()]
    recs.sort(key=lambda r: (_topic_sort_key(r.topic_id), r.query))
    return recs


#: Column names `load_plain_queries` accepts for each `QueryRec` field, in
#: priority order. Deliberately generous: the point of the bring-your-own-queries
#: path is that an operator with a TREC topics file, a CSV export, or a hand-typed
#: list does not have to write a converter first — and every one of these spellings
#: appeared in a real file we were handed.
QUERY_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "query": ("query", "text", "title", "keywords", "keyword_query",
              "search_query", "question"),
    "topic_id": ("topic_id", "qid", "query_id", "topic", "id", "number"),
    "topic": ("topic", "narrative", "description", "desc", "topic_text"),
}


def load_plain_queries(path: Path, *,
                       default_topic_prefix: str = "q") -> list[QueryRec]:
    """Read a plain query file — JSONL, TSV/CSV, or one query per line.

    This is the **corpus-independent** input path: `load_keyword_queries` parses
    one specific aus_agent search log, but tuning BM25 needs only `(topic, query)`
    pairs, so anything that can name those is enough.

    Recognised shapes, in the order they are tried per file:

    1. **JSONL** — one object per line; keys matched by `QUERY_FIELD_ALIASES`.
    2. **TSV / CSV** — 1 column = the query; 2 = `topic_id, query`;
       3+ = `topic_id, query, topic`. A header row is detected and used for
       aliasing rather than being read as data.
    3. **Plain text** — one query per line.

    Two fields need care, because getting either wrong is silent:

    - **`topic_id` groups queries that share a relevance judgement.** The judgment
      cache is keyed `prompt::topic_id::chunk_id` (PLAN §5.3) and ideal DCG is
      computed per *topic*, so two queries sharing a `topic_id` share their qrels.
      When the file gives no topic id, each query becomes its own topic
      (`<prefix>-<n>`) — the safe reading, since it never merges judgements
      across queries that might not deserve it.
    - **`topic` is the judge's target** (PLAN §0): the narrative the prompt asks
      "is this passage useful for". Absent one, the query text is used, which is
      correct for keyword queries and *weak* for short ones — a judge shown only
      `"soil moisture"` grades topical similarity, not usefulness. Supply a
      narrative when you have one.
    """
    path = Path(path)
    rows = _read_query_rows(path)
    if not rows:
        raise ExtractError(f"{path} contains no queries")
    recs: list[QueryRec] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows, start=1):
        query = _first_field(row, QUERY_FIELD_ALIASES["query"])
        if not query:
            raise ExtractError(
                f"{path}: row {index} has no query text — expected one of "
                f"{list(QUERY_FIELD_ALIASES['query'])}, got {sorted(row)}")
        topic_id = (_first_field(row, QUERY_FIELD_ALIASES["topic_id"])
                    or f"{default_topic_prefix}-{index}")
        # A `topic` alias that merely repeats the query is not a narrative;
        # keeping it would make the fallback invisible in the artifact.
        narrative = _first_field(row, QUERY_FIELD_ALIASES["topic"]) or query
        if narrative == topic_id:
            narrative = query
        key = (topic_id, query)
        if key in seen:
            # Same (topic, query) twice is the aus_agent loader's dedup rule too:
            # `qkey` is derived from the text, so a duplicate would collide and
            # the second run-file row would overwrite the first.
            continue
        seen.add(key)
        recs.append(QueryRec.make(topic_id, narrative, query, 0))
    recs.sort(key=lambda r: (_topic_sort_key(r.topic_id), r.query))
    return recs


def _first_field(row: Mapping[str, object], names: Sequence[str]) -> str:
    """First non-empty value among `names`, stripped; `""` if none match.

    Case- and separator-insensitive on the key (`Topic ID` matches `topic_id`),
    because a header row typed by a human is not normalised.
    """
    normalised = {str(k).strip().lower().replace(" ", "_").replace("-", "_"): v
                  for k, v in row.items()}
    for name in names:
        value = normalised.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _read_query_rows(path: Path) -> list[dict[str, object]]:
    """Dispatch on content, not on the extension.

    Extensions lie — we have been handed `.txt` holding JSONL and `.jsonl`
    holding TSV. Sniffing the first non-blank character is both more reliable and
    what makes a wrong guess loud (a JSON parse error names the line) rather than
    quiet (a whole JSON object read as one query string).
    """
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    if lines[0].lstrip().startswith("{"):
        return [dict(row) for row in iter_rows(path)]

    delimiter = "\t" if "\t" in lines[0] else ("," if "," in lines[0] else None)
    if delimiter is None:
        return [{"query": line.strip()} for line in lines]

    reader = list(csv.reader(lines, delimiter=delimiter))
    header = [cell.strip() for cell in reader[0]]
    # A header is a row whose cells all match a known alias: any other first row
    # is data, and consuming it as a header would silently drop a query.
    known = {alias for names in QUERY_FIELD_ALIASES.values() for alias in names}
    normalised_header = [c.lower().replace(" ", "_").replace("-", "_")
                         for c in header]
    if header and all(cell in known for cell in normalised_header):
        return [dict(zip(normalised_header, (c.strip() for c in cells)))
                for cells in reader[1:] if any(c.strip() for c in cells)]

    positional = ("topic_id", "query", "topic")
    rows: list[dict[str, object]] = []
    for cells in reader:
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if len(cells) == 1:
            rows.append({"query": cells[0]})
        else:
            rows.append(dict(zip(positional, cells[:3])))
    return rows


def _topic_sort_key(topic_id: str) -> tuple[int, str]:
    """Sort `rag2026-N` numerically, anything else lexically after it."""
    _, _, tail = topic_id.rpartition("-")
    return (int(tail), "") if tail.isdigit() else (10**9, topic_id)


def load_observed_hits(path: Path) -> list[ObservedHit]:
    """Every keyword hit in the labeled file, text already prefix-stripped.

    Deduped on `(topic_id, chunk_id)` — **[measured]** 9208 hits collapse to
    8580 pairs, because a topic's several keyword queries retrieve overlapping
    chunks. The topic-level key is deliberate: it is the same key the judgment
    cache uses (PLAN §5.3), so a calibration sample drawn from this list maps
    1:1 onto cache entries. The best-ranked occurrence wins, so `rank`/`score`
    describe the pair's strongest appearance.
    """
    best: dict[tuple[str, str], ObservedHit] = {}
    for row in iter_rows(path):
        if row.get("engine") != KEYWORD_ENGINE:
            continue
        topic_id = row["query_id"]
        for hit in row.get("results") or []:
            chunk_id = hit["id"]
            raw_text = hit.get("text") or ""
            prefix_chars = hit.get("prefix_chars")
            text, stripped = strip_page_prefix(raw_text, prefix_chars)
            rec = ObservedHit(
                topic_id=topic_id,
                topic=row["topic"],
                query=row["search_query"],
                chunk_id=chunk_id,
                parent_docid=hit.get("docid") or parent_docid(chunk_id),
                rank=int(hit.get("rank") or 0),
                score=float(hit.get("score") or 0.0),
                label=str(hit.get("label") or ""),
                reason=str(hit.get("reason") or ""),
                text=text,
                prefix_stripped=stripped,
                prefix_anomaly=prefix_anomaly(raw_text, prefix_chars),
            )
            key = (topic_id, chunk_id)
            previous = best.get(key)
            if previous is None or rec.rank < previous.rank:
                best[key] = rec
    hits = list(best.values())
    hits.sort(key=lambda h: (_topic_sort_key(h.topic_id), h.chunk_id))
    return hits


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def stratified_subsample(qs: Sequence[QueryRec], per_topic: int = 2,
                         seed: int = 13) -> list[QueryRec]:
    """Stage A's ~250-query subsample: `per_topic` queries from each topic.

    Stratifying by topic rather than sampling 250 queries uniformly is what
    keeps Stage A's nDCG comparable to Stage B's: the topic-level ideal DCG
    (PLAN §5.5) is shared across a topic's queries, so a subsample that dropped
    whole topics would change the metric's denominator, not just its variance.

    Determinism is structural, not incidental: topics are visited in sorted
    order and each topic's candidates are sorted by query text before sampling,
    so the result depends on `seed` alone and not on dict ordering or on the
    input file's row order. Topics with fewer than `per_topic` queries
    contribute all of them (**[measured]** min 3/topic, so none do here — the
    branch exists so a filtered subset can't crash).
    """
    if per_topic < 1:
        raise ValueError(f"per_topic must be >= 1, got {per_topic}")
    by_topic: dict[str, list[QueryRec]] = defaultdict(list)
    for rec in qs:
        by_topic[rec.topic_id].append(rec)
    rng = random.Random(seed)
    picked: list[QueryRec] = []
    for topic_id in sorted(by_topic, key=_topic_sort_key):
        candidates = sorted(by_topic[topic_id], key=lambda r: r.query)
        if len(candidates) <= per_topic:
            picked.extend(candidates)
        else:
            picked.extend(rng.sample(candidates, per_topic))
    picked.sort(key=lambda r: (_topic_sort_key(r.topic_id), r.query))
    return picked


def calibration_sample(hits: Sequence[ObservedHit], n: int = 280,
                       seed: int = 7) -> list[ObservedHit]:
    """WP0's calibration pairs: ~2-3 per topic, stratified by agent label.

    Both classes are wanted at every topic where they exist, because the
    agreement smell test (PLAN §3.3) compares agent-positive against
    agent-negative *within* the label set — a sample that happened to draw only
    negatives at half the topics would make that comparison a between-topic
    artifact. Global class proportions (**[measured]** 2368 / 6638 / 202) set the
    per-topic quota; the round-robin fill then tops the sample up to `n` without
    letting one class monopolize a topic.

    Every registered variant judges this same persisted list, which is the point:
    a
    grade-distribution comparison across prompts is only meaningful on identical
    pairs.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    # Class visit order: globally most frequent first, so the dominant class is
    # represented at every topic before the rare one competes for slots. Ties
    # broken by name so the order does not depend on Counter insertion order.
    counts = Counter(hit.agent_class for hit in hits)
    class_order = [cls for _, cls in
                   sorted(((-c, cls) for cls, c in counts.items()))]

    rng = random.Random(seed)
    # One shuffled queue per (topic, class). Sorted before shuffling so the
    # draw depends on `seed` alone, never on input row order.
    buckets: dict[tuple[str, str], list[ObservedHit]] = defaultdict(list)
    for hit in hits:
        buckets[(hit.topic_id, hit.agent_class)].append(hit)
    topic_ids = sorted({hit.topic_id for hit in hits}, key=_topic_sort_key)
    queues: dict[tuple[str, str], list[ObservedHit]] = {}
    for topic_id in topic_ids:
        for cls in class_order:
            pool = sorted(buckets.get((topic_id, cls), []),
                          key=lambda h: h.chunk_id)
            rng.shuffle(pool)
            queues[(topic_id, cls)] = pool

    picked: list[ObservedHit] = []
    # Round r takes one hit of class `class_order[r % len]` from every topic
    # that still has one. Rounds cycle through the classes, so per-topic counts
    # stay uniform to within one and the class mix tracks the global mix.
    rounds = max((len(q) for q in queues.values()), default=0) * \
        max(len(class_order), 1)
    for round_index in range(rounds):
        if len(picked) >= n:
            break
        cls = class_order[round_index % len(class_order)]
        for topic_id in topic_ids:
            if len(picked) >= n:
                break
            queue = queues[(topic_id, cls)]
            if queue:
                picked.append(queue.pop())
    picked.sort(key=lambda h: (_topic_sort_key(h.topic_id), h.chunk_id))
    return picked[:n]


def pool_calibration_sample(entries: Sequence[object],
                            texts: Mapping[str, str],
                            queries: Sequence[QueryRec],
                            n: int = 280,
                            seed: int = 7) -> list[ObservedHit]:
    """Draw a calibration sample from a **sweep pool** instead of a labeled log.

    The corpus-independent counterpart to `calibration_sample`. The judge gate
    (PLAN §3.3) is mandatory before any sweep spend, but `calibration_sample`
    reads `ObservedHit`s out of one specific aus_agent search log — so on any
    other index the gate would be unrunnable and the operator's only options
    would be to skip it (spending on an unvalidated judge) or to fabricate a log.
    Neither is acceptable, so the same gate runs off `pool.jsonl` +
    `pool-texts.jsonl`, which every sweep produces.

    Two consequences the caller must carry through to the report, because both
    change what the gate's numbers mean:

    - **There are no agent labels**, so every hit's `agent_class` is
      `"unjudged"`. The agreement smell test (AUC, mean-by-class) is then
      undefined — correctly reported as `—` rather than as 0.5 — and the gate
      rests entirely on the grade-distribution conditions. That is the intended
      degradation: those four conditions are the ones that decide whether a judge
      can separate grid cells at all, and the smell test was always secondary.
    - **The sample is retrieval-biased.** These are top-30 BM25 hits, so they are
      enriched for relevance relative to any wider notion of the corpus, in the
      same direction (not the same magnitude) as §3.1's positive enrichment.
      A share-at->=2 read here is an upper bound.

    Stratified per topic and shuffled from a seed, like `calibration_sample`, so
    the draw is a pure function of `seed` and every prompt variant judges
    byte-identical pairs. `entries` is a `pool.PoolEntry` sequence (duck-typed to
    keep this module free of a `pool` import, which imports this one).
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    topic_of_query = {rec.topic_id: rec for rec in queries}
    rng = random.Random(seed)

    by_topic: dict[str, list[ObservedHit]] = defaultdict(list)
    missing_text = 0
    for entry in entries:
        topic_id = str(getattr(entry, "topic_id"))
        chunk_id = str(getattr(entry, "chunk_id"))
        text = texts.get(chunk_id) or ""
        if not text:
            # Silently dropping would be wrong to hide, but fatal here would be
            # wrong too: `judge-pool` has its own coverage floor for that, and a
            # calibration sample only needs `n` usable pairs out of thousands.
            missing_text += 1
            continue
        rec = topic_of_query.get(topic_id)
        if rec is None:
            continue
        by_topic[topic_id].append(ObservedHit(
            topic_id=topic_id, topic=rec.topic, query=rec.query,
            chunk_id=chunk_id, parent_docid=parent_docid(chunk_id),
            rank=0, score=0.0,
            # No agent label exists on a foreign corpus; `""` maps to
            # `agent_class == "unjudged"`, which is the honest stratum.
            label="", reason="pooled (no agent label)", text=text,
            prefix_stripped=False))
    if not by_topic:
        raise ExtractError(
            "no pooled pair had both a passage and a topic narrative — nothing "
            "to calibrate on. Check that the sweep ran without --no-fetch-texts "
            "and that the query file matches the run's pool.")
    if missing_text:
        log.warning("[CALIB] %d pooled chunk(s) had no passage text and were "
                    "skipped when drawing the calibration sample", missing_text)

    topic_ids = sorted(by_topic, key=_topic_sort_key)
    queues: dict[str, list[ObservedHit]] = {}
    for topic_id in topic_ids:
        pool = sorted(by_topic[topic_id], key=lambda h: h.chunk_id)
        rng.shuffle(pool)
        queues[topic_id] = pool

    picked: list[ObservedHit] = []
    # Round-robin one hit per topic per round, so per-topic counts stay uniform
    # to within one — the same shape `calibration_sample` produces, which is what
    # keeps a gate reading comparable between the two sources.
    while len(picked) < n and any(queues[t] for t in topic_ids):
        for topic_id in topic_ids:
            if len(picked) >= n:
                break
            if queues[topic_id]:
                picked.append(queues[topic_id].pop())
    picked.sort(key=lambda h: (_topic_sort_key(h.topic_id), h.chunk_id))
    return picked[:n]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    """Write JSONL atomically (tmp + `os.replace`), returning the row count.

    Atomic because these files *are* the experiment's reproducibility claim: a
    half-written `subsample-250.jsonl` that a later stage happily reads would
    silently change which queries Stage A swept. `sort_keys` keeps the bytes
    stable so `git diff` / `sha256sum` are meaningful across re-extractions.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
            count += 1
    tmp.replace(path)
    return count


def write_query_file(path: Path, recs: Sequence[QueryRec]) -> int:
    """Persist a `QueryRec` list as `{topic_id, topic, query, qkey, k_orig}`."""
    return write_jsonl(path, (rec.to_json() for rec in recs))


def read_query_file(path: Path) -> list[QueryRec]:
    """Read back a query file written by `write_query_file`.

    Every later stage loads the *persisted* set rather than re-deriving it from
    the labeled input, so a subsample is byte-reproducible by construction: what
    Stage A swept is what is on disk, not what re-running the sampler would
    produce.
    """
    recs: list[QueryRec] = []
    for row in iter_rows(Path(path)):
        rec = QueryRec.make(row["topic_id"], row["topic"], row["query"],
                            int(row.get("k_orig") or 0))
        stored = row.get("qkey")
        if stored and stored != rec.qkey:
            raise ExtractError(
                f"{path}: stored qkey {stored!r} != recomputed {rec.qkey!r} — "
                "the query text and its tag disagree, so run files would be "
                "attributed to the wrong query")
        recs.append(rec)
    return recs


# ---------------------------------------------------------------------------
# Summaries (used by `verify-inputs` and the manifest)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InputSummary:
    """Counts `verify-inputs` asserts against PLAN §2.1.

    Kept as a dataclass rather than printed inline so the same numbers can be
    embedded in `manifest.json` without a second, divergent implementation.
    """

    total_rows: int
    keyword_rows: int
    engines: dict[str, int]
    run_ids: dict[str, int]
    topics: int
    unique_pairs: int
    keyword_hits: int
    unique_chunk_ids: int
    unique_topic_chunk_pairs: int
    prefix_chars_positive: int
    prefix_miss: int
    prefix_anomalies: dict[str, int]
    agent_labels: dict[str, int]
    agent_reasons: dict[str, int]

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def summarize_input(path: Path) -> InputSummary:
    """One streaming pass producing every count PLAN §2.1 pins.

    One pass, not several, because the file is 47 MB and `verify-inputs` runs
    before *every* stage (PLAN R8) — a slow check is a check that gets skipped.
    """
    engines: Counter[str] = Counter()
    run_ids: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    anomalies: Counter[str] = Counter()
    topics: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    chunk_ids: set[str] = set()
    topic_chunks: set[tuple[str, str]] = set()
    total_rows = 0
    keyword_rows = 0
    keyword_hits = 0
    prefix_positive = 0
    prefix_miss = 0

    for row in iter_rows(path):
        total_rows += 1
        engine = str(row.get("engine"))
        engines[engine] += 1
        if engine != KEYWORD_ENGINE:
            continue
        keyword_rows += 1
        run_ids[str(row.get("run_id"))] += 1
        topic_id = row["query_id"]
        topics.add(topic_id)
        pairs.add((topic_id, row["search_query"]))
        for hit in row.get("results") or []:
            keyword_hits += 1
            chunk_id = hit["id"]
            chunk_ids.add(chunk_id)
            topic_chunks.add((topic_id, chunk_id))
            labels[str(hit.get("label"))] += 1
            reasons[str(hit.get("reason"))] += 1
            prefix_chars = hit.get("prefix_chars")
            text = hit.get("text") or ""
            if prefix_chars:
                prefix_positive += 1
            anomaly = prefix_anomaly(text, prefix_chars)
            if anomaly is not None:
                anomalies[anomaly] += 1
                prefix_miss += 1

    return InputSummary(
        total_rows=total_rows,
        keyword_rows=keyword_rows,
        engines=dict(sorted(engines.items())),
        run_ids=dict(sorted(run_ids.items())),
        topics=len(topics),
        unique_pairs=len(pairs),
        keyword_hits=keyword_hits,
        unique_chunk_ids=len(chunk_ids),
        unique_topic_chunk_pairs=len(topic_chunks),
        prefix_chars_positive=prefix_positive,
        prefix_miss=prefix_miss,
        prefix_anomalies=dict(sorted(anomalies.items())),
        agent_labels=dict(sorted(labels.items())),
        agent_reasons=dict(sorted(reasons.items())),
    )


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """Streaming `sha256` of a file — the input's identity in every manifest."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def read_sha256sums(path: Path) -> dict[str, str]:
    """Parse a `sha256sum`-format file into `{basename: digest}`.

    Tolerates the binary-mode `*name` marker so a file produced by
    `sha256sum -b` verifies identically.
    """
    sums: dict[str, str] = {}
    for lineno, line in enumerate(Path(path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ExtractError(f"{path}:{lineno}: not a sha256sum line: {line!r}")
        digest, name = parts
        sums[name.lstrip("*").strip()] = digest.lower()
    return sums
