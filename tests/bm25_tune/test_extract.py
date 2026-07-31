"""What `bm25tune/extract.py` defends: the judge's input text and the query set.

Both are *silent*-corruption surfaces, which is why they get a test file rather
than a reading:

- **The passage text.** `strip_page_prefix` decides what the judge actually
  reads. Leave a `"Page N of document: <title>"` header in and the judge scores
  a passage whose first line contains topical words it did not earn; slice on a
  bad offset and 30 characters of real evidence vanish from the middle. Neither
  shows up in any downstream metric — a corrupted qrel looks exactly like a
  well-formed one.
- **The query set.** 1063 unique (topic, query) pairs is the number every volume,
  cost, and statistical-power figure in the plan is keyed to. A filter or dedupe
  regression changes the experiment without changing anything that looks wrong.
- **Reproducibility.** Stage A sweeps a 238-query subsample. If that draw is not
  a pure function of the seed — if it can drift with dict ordering or input row
  order — then "seed 13" documents nothing and the published Stage-A result is
  not re-derivable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bm25tune import extract
from bm25tune.extract import (ObservedHit, QueryRec, calibration_sample,
                              load_keyword_queries, load_observed_hits,
                              prefix_anomaly, read_query_file,
                              stratified_subsample, strip_page_prefix,
                              summarize_input, write_query_file)

# Header lengths baked into the fixture, restated here so an accidental edit to
# mini-labeled.jsonl fails these tests loudly rather than shifting them.
HDR_A2_LEN = 56
HDR_B3_LEN = 50
OUTLIER_CHUNK = "shard_00005_88_p2"


# ---------------------------------------------------------------------------
# Query loading
# ---------------------------------------------------------------------------
def test_keyword_filter_drops_semantic_rows(mini_labeled_path: Path) -> None:
    """Only `engine == "keyword"` rows may reach the sweep.

    The fixture's semantic rows deliberately reuse a keyword row's exact
    `search_query`, so a filter applied *after* dedupe would yield the same pair
    count and pass a weaker check. Mixing engines would sweep BM25 over queries
    a dense retriever generated — a different experiment wearing this one's name.
    """
    queries = load_keyword_queries(mini_labeled_path)
    assert {q.topic_id for q in queries} == {"rag2026-900", "rag2026-901"}
    # The semantic-only chunk must not appear anywhere in the observed hits.
    hits = load_observed_hits(mini_labeled_path)
    assert all(h.chunk_id != "shard_00009_999_p1" for h in hits)
    # The topic-B semantic query text is absent even though its topic is present.
    assert all("compare to ET scheduling" not in q.query for q in queries)


def test_topic_query_pairs_are_deduped_keeping_max_k(
        mini_labeled_path: Path) -> None:
    """A pair issued twice counts once, and keeps the deeper original `k`.

    aus_agent re-issued queries across turns; the labeled file therefore holds
    1070 rows for 1063 pairs. Sweeping the duplicates would double-count those
    queries in every mean nDCG and in the paired test's `n`. Where duplicate rows
    disagree on `k` (6 real pairs do), the max is kept because the deeper request
    is the one whose hits the file actually contains.
    """
    queries = load_keyword_queries(mini_labeled_path)
    assert len(queries) == 3, [q.query for q in queries]
    dup = next(q for q in queries
               if q.query.startswith("public library print reference"))
    assert dup.k_orig == 8, "the k=5 duplicate must not win over k=8"


def test_qkey_is_derived_from_query_text_not_row_order(
        mini_labeled_path: Path) -> None:
    """`qkey` must be a pure function of (topic_id, query text).

    It tags rankings in the TREC run files, so it is the join key between a
    search run and its judgments. If it depended on row position, re-extracting
    the queries would silently re-attribute every run file — Stage B would score
    Stage A's rankings against the wrong queries.
    """
    queries = load_keyword_queries(mini_labeled_path)
    for rec in queries:
        assert rec.qkey == QueryRec.make(rec.topic_id, rec.topic, rec.query,
                                        rec.k_orig).qkey
        assert rec.qkey.startswith(f"{rec.topic_id}::")
    assert len({q.qkey for q in queries}) == len(queries)


def test_conflicting_narrative_for_one_topic_is_fatal(tmp_path: Path) -> None:
    """One topic id may not carry two narratives.

    The narrative is the judge target and the cache key is topic-level, so two
    meanings for one `topic_id` would make a cached grade answer a question it
    was never asked. Better to refuse the file than to judge against whichever
    narrative happened to be read first.
    """
    path = tmp_path / "conflict.jsonl"
    rows = [
        {"run_id": "r", "engine": "keyword", "query_id": "rag2026-1",
         "topic": "narrative one", "search_query": "a", "k": 5, "results": []},
        {"run_id": "r", "engine": "keyword", "query_id": "rag2026-1",
         "topic": "narrative TWO", "search_query": "b", "k": 5, "results": []},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    with pytest.raises(extract.ExtractError, match="two different narratives"):
        load_keyword_queries(path)


def test_malformed_line_names_its_line_number(tmp_path: Path) -> None:
    """A bad JSON line aborts with its position, rather than being skipped.

    Skipping would produce a smaller-but-plausible query set, and the row-count
    assertions in `verify-inputs` exist precisely to catch that class of silent
    truncation — so the loader must not defeat them.
    """
    path = tmp_path / "bad.jsonl"
    path.write_text('{"engine": "keyword"}\nnot json at all\n')
    with pytest.raises(extract.ExtractError, match=r"bad\.jsonl:2"):
        list(extract.iter_rows(path))


# ---------------------------------------------------------------------------
# Observed hits
# ---------------------------------------------------------------------------
def test_observed_hits_dedupe_per_topic_keeping_best_rank(
        mini_labeled_path: Path) -> None:
    """(topic, chunk) is the unit, matching the judgment cache key.

    The fixture has `shard_00001_11_p1` retrieved by two of topic A's queries at
    ranks 1 and 3 — the real file collapses 9208 hits to 8580 pairs this way. The
    dedupe is what makes the cache economy work (one judgment serves every query
    in the topic); keeping the *best* rank means the record describes the pair's
    strongest appearance rather than an arbitrary one.
    """
    hits = load_observed_hits(mini_labeled_path)
    assert len(hits) == 6
    shared = [h for h in hits if h.chunk_id == "shard_00001_11_p1"]
    assert len(shared) == 1
    assert shared[0].rank == 1, "the rank-3 re-retrieval must not win"


def test_agent_class_buckets_voided_hits_as_unjudged(
        mini_labeled_path: Path) -> None:
    """`unjudged` is its own class, not folded into negative.

    PLAN R5: the 202 voided hits are collateral from a failed `commit_context`,
    not a judgment of any kind. Counting them as negatives would put them in the
    agreement cross-tab and make the judge look worse (or better) for a reason
    that has nothing to do with relevance.
    """
    hits = {h.chunk_id: h for h in load_observed_hits(mini_labeled_path)}
    assert hits["shard_00002_77_p1"].agent_class == "unjudged"
    assert hits["shard_00001_11_p1"].agent_class == "positive"
    # `not retained` is still a negative *label* — the class comes from `label`,
    # not from the free-text `reason`.
    assert hits["shard_00003_5_p1"].agent_class == "positive"
    assert hits["shard_00005_88_p2"].agent_class == "negative"


def test_parent_docid_recovers_the_document_from_a_chunk_id() -> None:
    """`<docid>_p<page>` -> `<docid>`, unambiguously.

    Chunk ids are the qrel's unit but documents are what a citation names, so
    this mapping is on the path to every published result. It is safe only
    because the page component is pure digits — a `_p` inside a shard name
    cannot be mistaken for the separator.
    """
    assert extract.parent_docid("shard_00122_5199_p1") == "shard_00122_5199"
    assert extract.parent_docid("shard_00122_5199_p12") == "shard_00122_5199"


# ---------------------------------------------------------------------------
# strip_page_prefix — the judge's input fidelity
# ---------------------------------------------------------------------------
def test_strip_by_recorded_prefix_chars(mini_labeled_path: Path) -> None:
    """The corroborated-`prefix_chars` branch removes exactly the header.

    This is the branch that fires on all 3890 real hits that have one. Getting
    the boundary off by even one character would leave a stray newline or eat the
    passage's first word in every one of them.
    """
    header = "Page 2 of document: Collection Development Review 2019\n\n"
    assert len(header) == HDR_A2_LEN
    body = "Staff consultation ran as four facilitated sessions."
    out, stripped = strip_page_prefix(header + body, HDR_A2_LEN)
    assert (out, stripped) == (body, True)
    hits = {h.chunk_id: h for h in load_observed_hits(mini_labeled_path)}
    assert hits["shard_00001_11_p2"].text.startswith("Staff consultation")
    assert "Page 2 of document" not in hits["shard_00001_11_p2"].text


def test_strip_by_regex_when_prefix_chars_is_absent() -> None:
    """Chunks fetched from the index carry no `prefix_chars`, so regex must work.

    The sweep's pool comes from `doc(id).contents()`, which has no offset
    metadata at all. Without this branch every pooled passage above page 1 would
    reach the judge with its header intact — and the pool, not the labeled file,
    is what the whole sweep is judged on.
    """
    text = "Page 7 of document: Some Title Here\n\nThe actual body text."
    out, stripped = strip_page_prefix(text, None)
    assert (out, stripped) == ("The actual body text.", True)
    out_zero, stripped_zero = strip_page_prefix(text, 0)
    assert (out_zero, stripped_zero) == ("The actual body text.", True)


def test_outlier_passes_through_unmodified(mini_labeled_path: Path) -> None:
    """A `prefix_chars` that points at no header must NOT be sliced (PLAN R4).

    The plan contradicts itself here: §5.1 says trust `prefix_chars`
    unconditionally, §2.1/R4 say the 31 outliers "land in" the passthrough branch
    and are counted. R4 wins, because the failure modes are asymmetric — leaving
    a header in is bounded, visible noise, while slicing on a wrong offset
    amputates real evidence from the passage with nothing able to detect it. The
    fixture's outlier would lose 30 characters of its cost figure under a blind
    slice.
    """
    text = ("Capital cost for a four-station soil-moisture array, installed, "
            "ran to AUD 6,400 including telemetry.")
    out, stripped = strip_page_prefix(text, 30)
    assert (out, stripped) == (text, False)
    hits = {h.chunk_id: h for h in load_observed_hits(mini_labeled_path)}
    outlier = hits[OUTLIER_CHUNK]
    assert outlier.text.startswith("Capital cost for a four-station")
    assert outlier.prefix_stripped is False


def test_prefix_chars_covering_whole_text_never_yields_a_blank_passage() -> None:
    """An out-of-range offset must not produce an empty passage.

    A blank passage would be graded 0 and enter the qrel as a legitimate
    judgment, so one bad offset would become one bogus relevance label — the
    kind of thing that shifts a marginal nDCG difference.
    """
    text = "Page 1 of document: T\n\n"
    out, stripped = strip_page_prefix(text, len(text))
    assert out == text and stripped is False
    assert strip_page_prefix("short", 999) == ("short", False)


@pytest.mark.parametrize("text,prefix_chars,expected", [
    ("Page 2 of document: T\n\nbody", 23, None),
    ("Page 2 of document: T\n\nbody", 30, "out_of_range"),
    ("no header at all here", 5, "not_a_header"),
    ("Page 2 of document: T\n\nbody", None, None),
    ("body with no header", None, None),
])
def test_prefix_anomaly_names_each_disagreement(
        text: str, prefix_chars: int | None, expected: str | None) -> None:
    """The `[PREFIX-MISS]` counter must count something falsifiable.

    `verify-inputs` asserts zero anomalies on the committed input. That
    assertion is only worth making if "anomaly" means "`prefix_chars` disagrees
    with the text" — if it merely meant "a slice ran off the end of a string" it
    would read zero for a file full of corrupted offsets, and R4's mitigation
    would be decorative.
    """
    assert prefix_anomaly(text, prefix_chars) == expected


def test_real_style_header_is_detected_by_the_shared_pattern() -> None:
    """One pattern serves both the offset check and the regex fallback.

    Two patterns would eventually disagree, and the disagreement would show up
    as passages stripped one way in calibration (from the labeled file) and
    another way in the sweep (from the index) — an invisible inconsistency
    between the two halves of the same experiment.
    """
    assert extract.PAGE_PREFIX_RE.match(
        "Page 12 of document: A Title: With Punctuation, & Symbols\n\nx")
    assert extract.PAGE_PREFIX_RE.match("Page one of document: T\n\nx") is None
    assert extract.PAGE_PREFIX_RE.match("Page 3 of document: T\nx") is None


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def test_subsample_takes_per_topic_and_is_seed_deterministic(
        mini_labeled_path: Path) -> None:
    """Same seed, same draw — regardless of input order or dict iteration.

    Stage A's published result names 238 specific queries. If the draw could
    drift, "seed 13" would document nothing and the result would not be
    re-derivable. The reversed-input check is the real test: it is the way this
    silently breaks, since a `random.sample` over an unsorted per-topic list
    depends on the order rows happened to be read in.
    """
    queries = load_keyword_queries(mini_labeled_path)
    first = stratified_subsample(queries, per_topic=1, seed=13)
    again = stratified_subsample(queries, per_topic=1, seed=13)
    reversed_input = stratified_subsample(list(reversed(queries)),
                                          per_topic=1, seed=13)
    assert [q.qkey for q in first] == [q.qkey for q in again]
    assert [q.qkey for q in first] == [q.qkey for q in reversed_input]
    # One per topic, and every topic represented.
    assert len(first) == 2
    assert {q.topic_id for q in first} == {"rag2026-900", "rag2026-901"}


def test_subsample_keeps_all_queries_of_an_underfull_topic(
        mini_labeled_path: Path) -> None:
    """A topic with fewer than `per_topic` queries contributes all of them.

    Real topics have 3-16 queries so this never fires on the full set — but Stage
    B's held-out split and any filtered re-run can produce an underfull topic,
    and dropping it would silently remove a topic from the metric's
    topic-level ideal DCG rather than just from the sample.
    """
    queries = load_keyword_queries(mini_labeled_path)
    picked = stratified_subsample(queries, per_topic=5, seed=13)
    assert len(picked) == len(queries)
    assert {q.topic_id for q in picked} == {"rag2026-900", "rag2026-901"}


def test_subsample_rejects_a_nonsensical_per_topic() -> None:
    """`per_topic=0` fails loudly instead of returning an empty Stage A.

    An empty query set would sail through the searcher and the pooler and only
    surface as a scores table full of zeros, hours later.
    """
    with pytest.raises(ValueError, match="per_topic"):
        stratified_subsample([], per_topic=0)


def test_calibration_sample_spreads_over_topics_and_agent_classes(
        mini_labeled_path: Path) -> None:
    """WP0's sample must contain both agent classes, spread across topics.

    The agreement smell test (PLAN §3.3) compares agent-positive against
    agent-negative grades. If the draw happened to take only positives at some
    topics and only negatives at others, that comparison would measure
    between-topic variation instead of the judge's discrimination — and WP0's gate
    decision would rest on it.
    """
    hits = load_observed_hits(mini_labeled_path)
    sample = calibration_sample(hits, n=4, seed=7)
    assert len(sample) == 4
    assert {h.topic_id for h in sample} == {"rag2026-900", "rag2026-901"}
    assert {h.agent_class for h in sample} >= {"positive", "negative"}
    # Determinism, on the same terms as the subsample: order-independent.
    again = calibration_sample(list(reversed(hits)), n=4, seed=7)
    assert [(h.topic_id, h.chunk_id) for h in sample] == \
           [(h.topic_id, h.chunk_id) for h in again]


def test_calibration_sample_never_repeats_a_pair(
        mini_labeled_path: Path) -> None:
    """Asking for more pairs than exist returns each at most once.

    A duplicated (topic, chunk) would be a guaranteed cache hit on its second
    appearance, so the "n=280 pairs" the report claims would silently be fewer
    distinct judgments — inflating the apparent stability rate and shrinking the
    grade distribution's real support.
    """
    hits = load_observed_hits(mini_labeled_path)
    sample = calibration_sample(hits, n=99, seed=7)
    keys = [(h.topic_id, h.chunk_id) for h in sample]
    assert len(keys) == len(set(keys)) == len(hits)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_query_file_round_trips_and_is_byte_stable(mini_labeled_path: Path,
                                                   tmp_path: Path) -> None:
    """Writing the same query set twice must produce identical bytes.

    Persisted query files are how Stage A's reproducibility claim is discharged:
    later stages read the file rather than re-deriving the sample. Sorted keys
    and a stable row order make `sha256sum` a meaningful check on it, which is
    what the `[SUMMARY] subsample sha256=` log line reports.
    """
    queries = load_keyword_queries(mini_labeled_path)
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    assert write_query_file(first, queries) == len(queries)
    write_query_file(second, queries)
    assert first.read_bytes() == second.read_bytes()
    assert [q.qkey for q in read_query_file(first)] == [q.qkey for q in queries]


def test_read_query_file_rejects_a_tampered_qkey(tmp_path: Path) -> None:
    """A stored `qkey` that disagrees with its query text is fatal.

    `qkey` joins run files to queries. If a hand-edited (or half-written) file
    could pass, the sweep would score one query's ranking under another query's
    name — a wrong result that looks entirely well-formed.
    """
    path = tmp_path / "q.jsonl"
    path.write_text(json.dumps({
        "topic_id": "rag2026-1", "topic": "n", "query": "real query",
        "qkey": "rag2026-1::deadbeefcafe", "k_orig": 8}) + "\n")
    with pytest.raises(extract.ExtractError, match="stored qkey"):
        read_query_file(path)


def test_write_jsonl_is_atomic_leaving_no_partial_file(
        tmp_path: Path) -> None:
    """A failed write must not leave a truncated artifact behind.

    A half-written `subsample-250.jsonl` that a later stage happily read would
    silently change which queries Stage A swept — so the write goes to a tmp file
    and is renamed into place, and a crash leaves the previous good file intact.
    """
    target = tmp_path / "out.jsonl"
    write_query_file(target, [QueryRec.make("rag2026-1", "n", "q", 8)])
    good = target.read_bytes()

    def _explode():
        yield {"ok": 1}
        raise RuntimeError("boom mid-write")

    with pytest.raises(RuntimeError, match="boom"):
        extract.write_jsonl(target, _explode())
    assert target.read_bytes() == good, "the previous good file was clobbered"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def test_summarize_input_counts_every_field_verify_inputs_asserts(
        mini_labeled_path: Path) -> None:
    """One streaming pass produces every count, with the engine split kept.

    `verify-inputs` runs before every stage (PLAN R8), so the summary must be
    cheap AND complete: a check that needed a second pass over 47 MB would get
    dropped, and a missing field would mean a count nobody verifies. The
    keyword/semantic split is included because `keyword_rows` alone cannot
    distinguish "the semantic rows are gone" from "the export changed shape".
    """
    summary = summarize_input(mini_labeled_path)
    assert summary.total_rows == 6
    assert summary.keyword_rows == 4
    assert summary.engines == {"keyword": 4, "semantic": 2}
    assert summary.run_ids == {"test-keyword-119": 4}
    assert summary.topics == 2
    assert summary.unique_pairs == 3
    # 7 keyword hits collapse to 6 (topic, chunk) pairs — one chunk twice.
    assert summary.keyword_hits == 7
    assert summary.unique_chunk_ids == 6
    assert summary.unique_topic_chunk_pairs == 6
    assert summary.prefix_chars_positive == 3
    assert summary.prefix_miss == 1
    assert summary.prefix_anomalies == {"not_a_header": 1}
    assert summary.agent_labels == {"negative": 3, "positive": 3,
                                    "unjudged": 1}
    assert set(summary.to_json()) >= {"total_rows", "unique_pairs",
                                      "prefix_anomalies"}


def test_read_sha256sums_accepts_the_binary_mode_marker(
        tmp_path: Path) -> None:
    """`sha256sum -b` output must verify identically to text mode.

    The committed `SHA256SUMS` was produced by whichever mode the operator
    happened to use; refusing one form would make `verify-inputs` fail on a file
    that is byte-for-byte correct, and the plan's instruction is to STOP on a
    checksum failure — so a false alarm here costs a real investigation.
    """
    target = tmp_path / "f.txt"
    target.write_text("hello")
    digest = extract.sha256_file(target)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{digest.upper()} *f.txt\n# a comment\n")
    assert extract.read_sha256sums(sums) == {"f.txt": digest}


def test_read_sha256sums_rejects_a_malformed_line(tmp_path: Path) -> None:
    """A garbled sums file is an error, not an empty (vacuously passing) dict.

    An empty parse would make the checksum lookup miss and — depending on the
    caller — either fail confusingly or silently skip verification of the one
    file the whole experiment rests on.
    """
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("garbage-with-no-filename\n")
    with pytest.raises(extract.ExtractError, match="not a sha256sum line"):
        extract.read_sha256sums(sums)


def test_observed_hit_json_carries_a_text_digest(
        mini_labeled_path: Path) -> None:
    """Serialized hits record `sha256(text)` alongside the text.

    The judgment log stores the passage digest (PLAN §5.3) so a cached grade can
    be proven to refer to the same bytes that were sent. Without the digest on
    the sampling side too, a calibration pair and its cached judgment could not
    be reconciled after a re-chunking.
    """
    hit = load_observed_hits(mini_labeled_path)[0]
    payload = hit.to_json()
    assert payload["text_sha256"] == extract.sha256_text(hit.text)
    assert payload["agent_class"] == hit.agent_class
    assert isinstance(hit, ObservedHit)
