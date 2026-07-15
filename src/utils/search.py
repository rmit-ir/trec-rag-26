"""Hybrid retrieval — dense + sparse with Reciprocal Rank Fusion (RRF).

Runs the dense (Jina-v5 DiskANN) and sparse (BM25 / PRF) retrievers concurrently
and fuses their ranked lists with RRF:

    rrf_score(d) = sum_over_lists  weight_list * 1 / (rrf_k + rank_of_d_in_list)

RRF is rank-based, so it needs no score calibration between the two very
different scoring scales (cosine/IP vs BM25). Returns fused hits sorted by
rrf_score.

``SearchHit`` is the single result type shared by every retrieval backend
(``search_dense``, ``search_sparse``, ``search_pyserini``, and the fused
results here). Common fields are typed; anything backend-specific lives in the
untyped ``meta`` dict.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from utils.search_dense import search_dense
from utils.search_sparse import search_sparse
from utils.search_types import SearchHit


def rrf_fuse(rankings: list[list[SearchHit]], *, rrf_k: int = 60,
             weights: list[float] | None = None,
             source_names: list[str] | None = None) -> list[SearchHit]:
    """Fuse ranked ``SearchHit`` lists via RRF into a single ranked list."""
    if weights is None:
        weights = [1.0] * len(rankings)
    if source_names is None:
        source_names = [f"src{i}" for i in range(len(rankings))]

    # Fuse on the retrieval-unit id (chunk id for chunks, docid for documents) so
    # distinct chunks of the same document stay separate.
    fused: dict[str, SearchHit] = {}
    for li, ranking in enumerate(rankings):
        w = weights[li]
        name = source_names[li]
        for rank, hit in enumerate(ranking, start=1):
            unit_id = hit["id"]
            entry = fused.get(unit_id)
            if entry is None:
                entry = {"id": unit_id, "docid": hit["docid"], "kind": hit["kind"],
                         "score": 0.0, "rank": 0, "text": None,
                         "meta": {"sources": {}}}
                fused[unit_id] = entry
            entry["score"] += w * (1.0 / (rrf_k + rank))
            entry["meta"]["sources"][name] = {"rank": rank, "score": hit["score"]}
            # Keep any available text (dense/sparse/pyserini may or may not include it).
            if entry["text"] is None and hit.get("text") is not None:
                entry["text"] = hit["text"]

    ordered = sorted(fused.values(), key=lambda e: e["score"], reverse=True)
    for rank, e in enumerate(ordered, start=1):
        e["rank"] = rank
    return ordered


def search(query: str, k: int = 10, *, dense_k: int | None = None,
           sparse_k: int | None = None, rrf_k: int = 60, with_text: bool = True,
           weights: tuple[float, float] | None = None,
           timeout: float = 30.0) -> list[SearchHit]:
    """Hybrid dense+sparse search fused with RRF; returns top-``k`` fused hits.

    ``dense_k``/``sparse_k`` control each retriever's depth (default ``max(k,
    50)`` so fusion has enough candidates). ``weights`` = (dense, sparse) RRF
    weights. Fused hits carry ``score`` = RRF score and
    ``meta["sources"][name] = {rank, score}`` per backend.
    """
    depth = max(k, 50)
    dk = dense_k or depth
    sk = sparse_k or depth

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_dense = ex.submit(search_dense, query, dk, with_text=with_text, timeout=timeout)
        f_sparse = ex.submit(search_sparse, query, sk, timeout=timeout)
        dense = f_dense.result()
        sparse = f_sparse.result()

    w = list(weights) if weights else None
    fused = rrf_fuse([dense, sparse], rrf_k=rrf_k, weights=w,
                     source_names=["dense", "sparse"])
    return fused[:k]


if __name__ == "__main__":  # quick manual check
    import sys
    q = " ".join(sys.argv[1:]) or "influenza vaccination"
    for h in search(q, k=10):
        print(h["rank"], h["docid"], round(h["score"], 5), h["meta"]["sources"])
