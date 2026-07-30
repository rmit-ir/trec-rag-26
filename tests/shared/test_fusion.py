"""Reciprocal Rank Fusion behaviour (``src/utils/search.py``).

``rrf_fuse`` is the only place in the stack where results from different engines
are combined, and it is pure — given ranked lists in, a fused list out — so it
is tested on hand-built inputs with arithmetic worked out by hand rather than
recomputed from the implementation. The properties that matter downstream:

- **Rank-based, score-blind.** RRF exists precisely because BM25 (~10) and
  inner-product (~0.8) are not comparable; a hit's own ``score`` must not affect
  the fused order at all. A regression to score-summing would be invisible in an
  end-to-end test but wrecks hybrid quality.
- **Fuses on ``id``, not ``docid``.** Post-chunking, two chunks of one document
  are distinct retrieval units and must stay separate rows.
- **``meta["sources"]``** is the provenance the analysis/worklog layer reads —
  per-source rank and native score, keyed by source name.
- **Text is borrowed.** Sparse may return no text where dense does (and vice
  versa); the fused hit keeps the first non-``None`` text so the answer stage
  always has something to quote.

``search()`` itself only adds concurrency + depth defaults; it is tested with the
two clients patched out, since the fan-out (not the transport) is what can break.
"""
from __future__ import annotations

from typing import Any

import pytest

from utils import search as search_mod
from utils.search import rrf_fuse, search
from utils.search_types import make_hit

# Short aliases for the canonical docids, so expected orders stay readable.
A, B, C, D = ("shard_00459_61697", "shard_01012_88420",
              "shard_00210_44018", "shard_00044_91812")


def _ranking(ids: tuple[str, ...], *, source: str = "x",
             base_score: float = 10.0) -> list[dict[str, Any]]:
    """A ranked list of ``SearchHit`` in the given id order."""
    return [make_hit(unit_id, score=base_score - i, rank=i + 1,
                     text=f"{unit_id} text", meta={"source": source})
            for i, unit_id in enumerate(ids)]


def _rrf(rank: int, k: int = 60, w: float = 1.0) -> float:
    return w * (1.0 / (k + rank))


# ---------------------------------------------------------------------------
# The fusion arithmetic
# ---------------------------------------------------------------------------
def test_single_ranking_is_passed_through_in_order() -> None:
    """The degenerate case, and a real one: when one engine returns nothing, RRF
    is left fusing a single list and must not reorder it. Also establishes the
    baseline ``1/(60+rank)`` values the multi-source tests build on."""
    fused = rrf_fuse([_ranking((A, B, C))])
    assert [h["id"] for h in fused] == [A, B, C]
    assert [h["rank"] for h in fused] == [1, 2, 3]
    assert fused[0]["score"] == pytest.approx(_rrf(1))
    assert fused[2]["score"] == pytest.approx(_rrf(3))


def test_hand_computed_fusion_order() -> None:
    """Two disagreeing lists; the expected order is computed by hand.

        dense:  A B C          sparse: C A D
        A = 1/61 + 1/62 = .032796   (in both, near the top of each)
        C = 1/63 + 1/61 = .032266
        B = 1/62         = .016129
        D = 1/63         = .015873
    """
    fused = rrf_fuse([_ranking((A, B, C)), _ranking((C, A, D))],
                     source_names=["dense", "sparse"])
    assert [h["id"] for h in fused] == [A, C, B, D]
    assert fused[0]["score"] == pytest.approx(_rrf(1) + _rrf(2))
    assert fused[1]["score"] == pytest.approx(_rrf(3) + _rrf(1))
    assert fused[2]["score"] == pytest.approx(_rrf(2))
    assert fused[3]["score"] == pytest.approx(_rrf(3))
    assert [h["rank"] for h in fused] == [1, 2, 3, 4]


def test_a_doc_in_every_source_ranks_first() -> None:
    """Even when it is last in each list, agreement across all sources beats a
    single source's #1 — the whole point of RRF."""
    fused = rrf_fuse([_ranking((B, C, A)), _ranking((C, D, A)),
                      _ranking((D, B, A))],
                     source_names=["dense", "sparse", "ssr"])
    assert fused[0]["id"] == A
    assert fused[0]["score"] == pytest.approx(3 * _rrf(3))
    assert set(fused[0]["meta"]["sources"]) == {"dense", "sparse", "ssr"}


def test_fusion_is_blind_to_native_scores() -> None:
    """Same ranks, wildly different score scales -> identical fused output."""
    bm25 = _ranking((A, B), source="sparse", base_score=42.0)
    dense = _ranking((A, B), source="dense", base_score=0.9)
    high = rrf_fuse([bm25, dense])
    low = rrf_fuse([_ranking((A, B), source="sparse", base_score=0.001),
                    _ranking((A, B), source="dense", base_score=0.002)])
    assert [h["id"] for h in high] == [h["id"] for h in low]
    assert [h["score"] for h in high] == [h["score"] for h in low]


@pytest.mark.parametrize("rrf_k,expected_first", [
    # A is #1 in dense only; B is #4 in both lists. Small rrf_k makes the
    # 1/(k+rank) curve steep, so one #1 outranks two #4s; the default k=60
    # flattens it, and the two-source agreement wins instead.
    (1, A),      # 1/2 = .500  vs  2 * 1/5   = .400
    (60, B),     # 1/61 = .0164 vs  2 * 1/64 = .0313
])
def test_rrf_k_controls_how_much_top_ranks_dominate(rrf_k: int,
                                                    expected_first: str) -> None:
    """``rrf_k`` is the one tuning dial, and this is what it trades off: how much
    a single engine's top hit is worth against agreement between engines. The two
    parameter rows flip the winner, which is the only way to show the constant is
    actually in the denominator and not a no-op — an ``rrf_k`` accidentally
    ignored would still pass every other test in this file.
    """
    # Filler ids are unique per list so only A and B are contested.
    dense = _ranking((A, C, D, B))
    sparse = _ranking(("shard_00777_1", "shard_00777_2", "shard_00777_3", B))
    fused = rrf_fuse([dense, sparse], rrf_k=rrf_k)
    assert fused[0]["id"] == expected_first


def test_weights_scale_each_list_contribution() -> None:
    """A zero-weighted list contributes no score but still registers in
    ``meta["sources"]`` and still introduces its ids — worth knowing before
    someone uses weight 0 as an "off switch"."""
    fused = rrf_fuse([_ranking((A,)), _ranking((B,))],
                     weights=[3.0, 0.0], source_names=["dense", "sparse"])
    by_id = {h["id"]: h for h in fused}
    assert by_id[A]["score"] == pytest.approx(3 * _rrf(1))
    assert by_id[B]["score"] == 0.0
    assert fused[0]["id"] == A
    assert by_id[B]["meta"]["sources"] == {"sparse": {"rank": 1,
                                                     "score": 10.0}}


def test_default_weights_are_uniform_and_names_are_positional() -> None:
    """Called without ``weights``/``source_names``, fusion must still be usable:
    equal weights, and synthetic ``src<i>`` labels so ``meta["sources"]`` is never
    empty (a caller inspecting provenance would otherwise see nothing and conclude
    the hit came from nowhere)."""
    fused = rrf_fuse([_ranking((A,)), _ranking((B,))])
    assert {h["id"]: h["score"] for h in fused} == {A: pytest.approx(_rrf(1)),
                                                   B: pytest.approx(_rrf(1))}
    assert set(fused[0]["meta"]["sources"]) <= {"src0", "src1"}
    names = set().union(*(set(h["meta"]["sources"]) for h in fused))
    assert names == {"src0", "src1"}


# ---------------------------------------------------------------------------
# Deduplication + provenance
# ---------------------------------------------------------------------------
def test_deduplicates_across_sources_with_a_per_source_breakdown() -> None:
    """One document found by both engines must become ONE row — a duplicate would
    waste a citation slot and let the model double-count the same evidence — while
    ``meta["sources"]`` retains each engine's native rank and score so a post-hoc
    analysis can still tell who found it and how highly."""
    dense = [make_hit(A, score=0.81, rank=1, text="dense text",
                      meta={"source": "dense"})]
    sparse = [make_hit(A, score=11.4, rank=2, text="sparse text",
                       meta={"source": "sparse"})]
    fused = rrf_fuse([dense, sparse], source_names=["dense", "sparse"])
    assert len(fused) == 1
    entry = fused[0]
    # Both recorded ranks are 1 because each list has one element — the fused
    # rank is the POSITION in the list, not the hit's own `rank` field (see the
    # dedicated test below).
    assert entry["meta"]["sources"] == {"dense": {"rank": 1, "score": 0.81},
                                        "sparse": {"rank": 1, "score": 11.4}}
    # The fused score replaces the native score entirely.
    assert entry["score"] == pytest.approx(2 * _rrf(1))


def test_fusion_uses_list_position_not_the_hit_rank_field() -> None:
    """ACTUAL BEHAVIOUR (worth knowing, arguably the safer choice): ``rrf_fuse``
    re-enumerates each list and ignores ``hit["rank"]``. So a caller that hands
    in a *filtered* list (say, ranks 5-10 after a dedup pass) gets those hits
    treated as ranks 1-6, and ``meta["sources"][...]["rank"]`` reports the
    position rather than the backend's original rank."""
    sliced = [make_hit(A, score=1.0, rank=7, text=None, meta={}),
              make_hit(B, score=0.9, rank=9, text=None, meta={})]
    fused = rrf_fuse([sliced], source_names=["dense"])
    assert fused[0]["meta"]["sources"]["dense"]["rank"] == 1
    assert fused[1]["meta"]["sources"]["dense"]["rank"] == 2
    assert fused[0]["score"] == pytest.approx(_rrf(1))


def test_duplicate_id_within_one_ranking_counts_once_at_its_best_rank() -> None:
    """RRF gives each unit ONE contribution per ranking, duplicates included.

    A backend repeating an id used to have its contribution added twice, which
    promotes it over hits the sources genuinely agreed on — and ``meta["sources"]``
    kept the *later*, worse rank, so the fused row also misreported where it came
    from. The first occurrence wins because that is the rank the backend itself
    ranked highest. No hosted backend does this today; the guard is one line and
    the failure would be a silently wrong ranking.
    """
    dup = [make_hit(A, score=1.0, rank=1, text="t", meta={}),
           make_hit(A, score=0.5, rank=2, text="t", meta={})]
    fused = rrf_fuse([dup], source_names=["dense"])
    assert len(fused) == 1
    assert fused[0]["score"] == pytest.approx(_rrf(1))
    assert fused[0]["meta"]["sources"]["dense"] == {"rank": 1, "score": 1.0}


def test_fuses_on_unit_id_so_sibling_chunks_stay_separate() -> None:
    """Two chunks of the same document are two rows, both carrying the shared
    parent ``docid`` — dedup at the doc level is the citation layer's job."""
    chunk_a, chunk_b = f"{A}_p1", f"{A}_p4"
    fused = rrf_fuse([_ranking((chunk_a, chunk_b)), _ranking((chunk_b,))],
                     source_names=["dense", "sparse"])
    assert [h["id"] for h in fused] == [chunk_b, chunk_a]
    assert {h["docid"] for h in fused} == {A}
    assert {h["kind"] for h in fused} == {"chunk"}


def test_kind_and_docid_are_carried_from_the_first_source_to_see_the_id() -> None:
    """Fusion copies ``kind``/``docid`` rather than re-deriving them from the id,
    so a backend that knows better (a chunk index returning both ids explicitly)
    keeps its answer — and the fused row is still a complete ``SearchHit`` that
    the citation layer can map back to a parent document."""
    fused = rrf_fuse([_ranking((f"{A}_p2",))])
    assert fused[0]["docid"] == A and fused[0]["kind"] == "chunk"


# ---------------------------------------------------------------------------
# Text borrowing + empty inputs
# ---------------------------------------------------------------------------
def test_text_is_borrowed_from_the_first_source_that_has_it() -> None:
    """Sparse may be text-less (no ``_source``) while dense is not; the fused row
    must still be quotable."""
    textless = [make_hit(A, score=11.4, rank=1, text=None, meta={})]
    texted = [make_hit(A, score=0.8, rank=1, text="the passage", meta={})]
    assert rrf_fuse([textless, texted])[0]["text"] == "the passage"
    # ...and an earlier non-None text is not overwritten by a later one.
    assert rrf_fuse([texted, [make_hit(A, score=1.0, rank=1, text="other",
                                       meta={})]])[0]["text"] == "the passage"


def test_text_stays_none_when_no_source_has_it() -> None:
    """``None`` must survive the borrow logic rather than becoming ``""`` — the
    distinction is what lets a caller decide to hydrate the text with
    ``fetch_doc`` instead of quoting an empty passage."""
    hits = [make_hit(A, score=1.0, rank=1, text=None, meta={})]
    assert rrf_fuse([hits, hits])[0]["text"] is None


def test_an_empty_source_does_not_change_the_other_ranking() -> None:
    """The SSR "truthful zero" case: one engine returns nothing, fusion degrades
    to the surviving engine rather than erroring or dropping everything."""
    solo = rrf_fuse([_ranking((A, B, C))], source_names=["dense"])
    with_empty = rrf_fuse([_ranking((A, B, C)), []],
                          source_names=["dense", "ssr"])
    assert [h["id"] for h in with_empty] == [h["id"] for h in solo]
    assert [h["score"] for h in with_empty] == [h["score"] for h in solo]
    # The empty source leaves no trace in the provenance.
    assert all("ssr" not in h["meta"]["sources"] for h in with_empty)


def test_all_sources_empty_yields_an_empty_list() -> None:
    """Total-miss queries happen (a Boolean AND with no co-occurrence), and the
    no-rankings-at-all case is what a future 0-engine config would hit. Neither
    may raise: the caller above turns ``[]`` into a normal empty tool result."""
    assert rrf_fuse([[], []]) == []
    assert rrf_fuse([]) == []


def test_fused_entries_have_the_full_searchhit_shape() -> None:
    """A fused hit is handed to the same consumers as a raw one (the tool
    envelope indexes ``h["rank"]``, ``h["kind"]``, ... without ``.get``), so
    fusion must produce a COMPLETE ``SearchHit`` and not a partial dict."""
    for hit in rrf_fuse([_ranking((A, B)), _ranking((B,))]):
        assert set(hit) == {"id", "docid", "kind", "score", "rank", "text", "meta"}
        assert isinstance(hit["score"], float) and isinstance(hit["rank"], int)


def test_input_rankings_are_not_mutated() -> None:
    """Fusion builds new entries; a caller that keeps the per-engine lists for
    logging must still see their native scores/ranks."""
    dense = _ranking((A, B))
    before = [dict(h) for h in dense]
    rrf_fuse([dense, _ranking((B,))])
    assert dense == before


# ---------------------------------------------------------------------------
# search() — the dense+sparse fan-out wrapper
# ---------------------------------------------------------------------------
def _patch_clients(monkeypatch: pytest.MonkeyPatch,
                   dense: list[dict[str, Any]],
                   sparse: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace both clients in ``utils.search``'s namespace; record their args."""
    calls: dict[str, Any] = {}

    def _dense(query: str, k: int, **kw: Any) -> list[dict[str, Any]]:
        calls["dense"] = {"query": query, "k": k, **kw}
        return dense

    def _sparse(query: str, k: int, **kw: Any) -> list[dict[str, Any]]:
        calls["sparse"] = {"query": query, "k": k, **kw}
        return sparse

    monkeypatch.setattr(search_mod, "search_dense", _dense)
    monkeypatch.setattr(search_mod, "search_sparse", _sparse)
    return calls


def test_search_fans_out_to_both_clients_and_fuses(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The happy path through the ``ThreadPoolExecutor``: both retrievers get the
    same query, and the fused output is the RRF order (not concatenation, and not
    dense-then-sparse). Both futures must be awaited — dropping one would still
    return plausible results, just half-hybrid."""
    calls = _patch_clients(monkeypatch, _ranking((A, B, C), source="dense"),
                           _ranking((C, A, D), source="sparse"))
    fused = search("congestion pricing", k=3)
    assert [h["id"] for h in fused] == [A, C, B]          # top-3 of A C B D
    assert set(fused[0]["meta"]["sources"]) == {"dense", "sparse"}
    assert calls["dense"]["query"] == calls["sparse"]["query"] == "congestion pricing"


def test_search_retrieval_depth_defaults_to_at_least_50(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Fusion needs candidates below the cut to be useful, so each retriever is
    asked for ``max(k, 50)`` regardless of the requested ``k``."""
    calls = _patch_clients(monkeypatch, [], [])
    search("q", k=5)
    assert calls["dense"]["k"] == 50 and calls["sparse"]["k"] == 50
    search("q", k=200)
    assert calls["dense"]["k"] == 200 and calls["sparse"]["k"] == 200


def test_search_explicit_per_retriever_depths_win(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Asymmetric depths are how the retrievers' cost difference is managed (dense
    DiskANN depth is cheap, BM25 depth less so). The two values are deliberately
    different AND different from ``k``, so a swapped or shared argument shows up."""
    calls = _patch_clients(monkeypatch, [], [])
    search("q", k=10, dense_k=100, sparse_k=20)
    assert calls["dense"]["k"] == 100 and calls["sparse"]["k"] == 20


def test_search_forwards_with_text_and_timeout(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``with_text`` is dense-only (sparse has no such knob) — assert the split,
    since passing it to sparse would be a TypeError at runtime."""
    calls = _patch_clients(monkeypatch, [], [])
    search("q", with_text=False, timeout=5.0)
    assert calls["dense"] == {"query": "q", "k": 50, "with_text": False,
                              "timeout": 5.0}
    assert calls["sparse"] == {"query": "q", "k": 50, "timeout": 5.0}


def test_search_truncates_to_k(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fusion happens at depth ≥50 but the CALLER asked for ``k`` — returning the
    full fused list would silently hand an agent 50 passages (context blowout) and
    make the MCP server's ``MCP_SEARCH_K`` meaningless."""
    _patch_clients(monkeypatch, _ranking((A, B, C, D), source="dense"),
                   _ranking((D, C, B, A), source="sparse"))
    assert len(search("q", k=2)) == 2


def test_search_weights_are_applied_dense_then_sparse(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A (0, 1) weighting must yield the sparse ordering, which is the only
    unambiguous way to prove the tuple is not swapped."""
    _patch_clients(monkeypatch, _ranking((A, B), source="dense"),
                   _ranking((C, D), source="sparse"))
    sparse_only = search("q", k=2, weights=(0.0, 1.0))
    assert [h["id"] for h in sparse_only] == [C, D]
    dense_only = search("q", k=2, weights=(1.0, 0.0))
    assert [h["id"] for h in dense_only] == [A, B]


def test_search_rrf_k_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """``rrf_k`` must reach ``rrf_fuse`` rather than being shadowed by the default
    60 — otherwise a tuning sweep over the dial would produce identical numbers at
    every setting and look like "RRF k doesn't matter"."""
    _patch_clients(monkeypatch, _ranking((A,), source="dense"), [])
    assert search("q", k=1, rrf_k=1)[0]["score"] == pytest.approx(1 / 2)


def test_search_source_names_are_dense_and_sparse(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The MCP server and the worklogs read these names; they are part of the
    artifact format, not an internal label."""
    _patch_clients(monkeypatch, _ranking((A,), source="dense"),
                   _ranking((A,), source="sparse"))
    assert set(search("q", k=1)[0]["meta"]["sources"]) == {"dense", "sparse"}


def test_search_propagates_a_client_failure(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """No swallowing inside the thread pool — the tool layer above is what turns
    an exception into an agent-visible error envelope."""
    def _boom(query: str, k: int, **kw: Any) -> list[dict[str, Any]]:
        raise RuntimeError("dense endpoint 503")

    monkeypatch.setattr(search_mod, "search_dense", _boom)
    monkeypatch.setattr(search_mod, "search_sparse",
                        lambda q, k, **kw: _ranking((A,)))
    with pytest.raises(RuntimeError, match="dense endpoint 503"):
        search("q")
