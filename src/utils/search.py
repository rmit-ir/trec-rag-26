"""Hybrid retrieval — dense + sparse with Reciprocal Rank Fusion (RRF).

Runs the dense (Jina-v5 DiskANN) and sparse (BM25 / PRF) retrievers concurrently
and fuses their ranked lists with RRF:

    rrf_score(d) = sum_over_lists  weight_list * 1 / (rrf_k + rank_of_d_in_list)

RRF is rank-based, so it needs no score calibration between the two very
different scoring scales (cosine/IP vs BM25). Returns fused hits sorted by
rrf_score, each ``{docid, rrf_score, rank, score_dense, score_sparse, text}``.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.utils.search_dense import search_dense
from src.utils.search_sparse import search_sparse


def rrf_fuse(rankings: list[list[dict[str, Any]]], *, rrf_k: int = 60,
             weights: list[float] | None = None,
             source_names: list[str] | None = None) -> list[dict[str, Any]]:
    """Fuse ranked lists (each ``{docid, score, rank, text}``) via RRF."""
    if weights is None:
        weights = [1.0] * len(rankings)
    if source_names is None:
        source_names = [f"src{i}" for i in range(len(rankings))]

    fused: dict[str, dict[str, Any]] = {}
    for li, ranking in enumerate(rankings):
        w = weights[li]
        name = source_names[li]
        for rank, hit in enumerate(ranking, start=1):
            docid = hit["docid"]
            entry = fused.setdefault(docid, {
                "docid": docid, "rrf_score": 0.0, "text": None,
            })
            entry["rrf_score"] += w * (1.0 / (rrf_k + rank))
            entry[f"score_{name}"] = hit.get("score")
            entry[f"rank_{name}"] = rank
            # Keep any available text (dense/sparse may or may not include it).
            if entry["text"] is None and hit.get("text") is not None:
                entry["text"] = hit["text"]

    ordered = sorted(fused.values(), key=lambda e: e["rrf_score"], reverse=True)
    for rank, e in enumerate(ordered, start=1):
        e["rank"] = rank
    return ordered


def search(query: str, k: int = 10, *, dense_k: int | None = None,
           sparse_k: int | None = None, prf: str | None = None,
           rrf_k: int = 60, with_text: bool = True,
           weights: tuple[float, float] | None = None,
           timeout: float = 30.0, **prf_params: Any) -> list[dict[str, Any]]:
    """Hybrid dense+sparse search fused with RRF; returns top-``k`` fused hits.

    ``dense_k``/``sparse_k`` control each retriever's depth (default ``max(k,
    50)`` so fusion has enough candidates). ``weights`` = (dense, sparse) RRF
    weights. ``prf`` and ``prf_params`` are forwarded to the sparse side.
    """
    depth = max(k, 50)
    dk = dense_k or depth
    sk = sparse_k or depth

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_dense = ex.submit(search_dense, query, dk, with_text=with_text, timeout=timeout)
        f_sparse = ex.submit(search_sparse, query, sk, prf=prf, timeout=timeout, **prf_params)
        dense = f_dense.result()
        sparse = f_sparse.result()

    w = list(weights) if weights else None
    fused = rrf_fuse([dense, sparse], rrf_k=rrf_k, weights=w,
                     source_names=["dense", "sparse"])
    return fused[:k]


if __name__ == "__main__":  # quick manual check
    import json
    import sys
    q = " ".join(sys.argv[1:]) or "influenza vaccination"
    for h in search(q, k=10, prf="rm3"):
        print(h["rank"], h["docid"], round(h["rrf_score"], 5),
              "d=", h.get("rank_dense"), "s=", h.get("rank_sparse"))
