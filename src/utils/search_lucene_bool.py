"""Lucene Boolean retrieval client — full Lucene query-parser over the BM25 index.

Unlike the hosted BM25 index-server (``search_sparse``), whose
``BagOfWordsQueryGenerator`` strips operators to a bag-of-words OR, this runs the
*full* Lucene classic ``QueryParser`` over the same on-disk Anserini index via
``tasks/bm25_index/boolsearch`` (``BoolSearch.java`` + ``bs.sh``). It supports
required terms (``+term``), exclusion (``-term``), phrases (``"a b"``),
proximity (``"a b"~N``), wildcards, and grouping — the Boolean counterpart to
SSR for the retrieval comparison.

No server: each call spawns a short-lived JVM that mmap-opens the (page-cached)
index — ~0.4 s per query, fine for agentic use. Returns hits normalized to the
shared ``SearchHit`` shape.

Config:

- ``LUCENE_BOOL_BS`` path to ``bs.sh`` (default: the repo's boolsearch wrapper)
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from utils.search_types import SearchHit, make_hit

_REPO_ROOT = "/scratch/fast/kun/projects/trec-rag-26"
DEFAULT_BS = f"{_REPO_ROOT}/tasks/bm25_index/boolsearch/bs.sh"

# "[1] shard_00823_61684 score=10.11"  ->  rank, docid, score
_HIT_RE = re.compile(r"^\[(\d+)\]\s+(\S+)\s+score=([\-\d.]+)\s*$")


def search_lucene_bool(query: str, k: int = 10, *, snippet_chars: int = 500,
                       bs_path: str | None = None,
                       timeout: float = 120.0) -> list["SearchHit"]:
    """Run a Lucene query-parser query. Returns a list of ``SearchHit``.

    ``query`` is Lucene classic syntax, e.g. ``+uranium +enrichment +russia``
    (default operator is OR, so ``+`` marks required terms). Raises
    ``RuntimeError`` on a non-zero exit or an unparseable query so the tool
    layer can surface it as a tool error.
    """
    bs = bs_path or os.environ.get("LUCENE_BOOL_BS", DEFAULT_BS)
    proc = subprocess.run(
        ["bash", bs, str(k), query, str(snippet_chars)],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"BoolSearch exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:300]}")

    hits: list[SearchHit] = []
    lines = proc.stdout.splitlines()
    for i, line in enumerate(lines):
        m = _HIT_RE.match(line)
        if not m:
            continue
        rank = int(m.group(1))
        docid = m.group(2)
        score = float(m.group(3))
        # the snippet is the (indented) line immediately after the hit line
        text = lines[i + 1].strip() if i + 1 < len(lines) else None
        hits.append(make_hit(
            docid, score=score, rank=rank, text=text,
            meta={"source": "lucene_bool"},
        ))
    return hits


if __name__ == "__main__":  # quick manual check
    import sys
    q = " ".join(sys.argv[1:]) or "+influenza +vaccine"
    for h in search_lucene_bool(q, k=5):
        print(h["rank"], h["docid"], round(h["score"], 4),
              (h["text"] or "")[:80].replace("\n", " "))
