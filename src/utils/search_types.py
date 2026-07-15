"""Shared types for the search layer.

Kept in its own module (no imports from the client/fusion modules) so every
retrieval backend and the fusion layer can share ``SearchHit`` without an import
cycle.
"""
from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

Kind = Literal["document", "chunk"]

# Chunk ids follow the corpus convention ``<docid>_p<page>`` (page from 1, e.g.
# ``shard_00000_3908_p1``); the parent docid is everything before the ``_p<n>``
# suffix. Document ids (e.g. ``shard_00000_3908``) have no such suffix.
_CHUNK_SUFFIX_RE = re.compile(r"_p\d+$")


class SearchHit(TypedDict):
    """One normalized retrieval result, uniform across all backends
    (``search_dense``, ``search_sparse``, ``search_pyserini``, and the fused
    results from ``search``).

    - ``id``     the retrieval unit's id: a chunk id when ``kind == "chunk"``,
                 otherwise the document id.
    - ``docid``  the parent document id (always doc-level; ``== id`` for
                 documents, the ``_p<page>``-stripped parent for chunks).
    - ``kind``   ``"document"`` or ``"chunk"`` — retrieval granularity.
    - ``score``  backend score (BM25 / inner-product / RRF for fused results)
    - ``rank``   1-based rank within that backend's result list
    - ``text``   unit text if the backend returned it, else ``None``
    - ``meta``   untyped backend-specific extras (source name, raw fields,
                 per-source RRF breakdown, hosted-index name, ...)
    """
    id: str
    docid: str
    kind: Kind
    score: float
    rank: int
    text: str | None
    meta: dict[str, Any]


def classify_id(unit_id: str) -> tuple[Kind, str]:
    """Return ``(kind, docid)`` for a retrieval-unit id.

    A ``<docid>_p<page>`` id is a chunk (parent = the id minus the ``_p<page>``
    suffix); anything else is treated as a document (docid == id).
    """
    if _CHUNK_SUFFIX_RE.search(unit_id):
        return "chunk", _CHUNK_SUFFIX_RE.sub("", unit_id)
    return "document", unit_id


def make_hit(unit_id: str, *, score: float, rank: int, text: str | None,
             meta: dict[str, Any] | None = None,
             kind: Kind | None = None, docid: str | None = None) -> SearchHit:
    """Build a ``SearchHit``, deriving ``kind``/``docid`` from ``unit_id`` unless
    the backend already knows them (e.g. a chunk index that returns both ids)."""
    if kind is None or docid is None:
        derived_kind, derived_docid = classify_id(unit_id)
        kind = kind or derived_kind
        docid = docid or derived_docid
    return {
        "id": unit_id,
        "docid": docid,
        "kind": kind,
        "score": score,
        "rank": rank,
        "text": text,
        "meta": meta or {},
    }
