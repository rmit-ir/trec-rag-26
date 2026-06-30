"""SearchEngine: load a built-index dir, validate every part, search.

A "built-index dir" is the output of tasks/custom_index/scripts/index_pipeline.sh
plus tasks/custom_index/scripts/build_docstore.py. The expected layout:

  <index_dir>/
    encoding_meta.json              # model, dim, normalize, task, prompt names
    index_meta.json                 # diskann build args
    docids.txt                      # one docid per line, parallel to vectors.fbin
    ann_disk.index                  # diskann disk index files
    ann_pq_pivots.bin
    ann_pq_compressed.bin
    ann_metadata.bin
    ann_disk.index_medoids.bin
    docstore/                       # built by build_docstore.py
      manifest.json
      zstd.dict                     # only when compression != "none"
      shard_NNNNN.bin
      shard_NNNNN.offsets.bin

On any missing piece, ``SearchEngine.load()`` prints the exact CLI that
produces it and raises ``EngineLoadError``.
"""
from __future__ import annotations

import json
import mmap
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from docstore import FlatShardDocStore
from encoder import EncoderConfig, QueryEncoder, build_encoder
from errors import (
    EngineLoadError,
    diskann_build_hint,
    docstore_build_hint,
    ensure_path,
)
from server_info import aio_slots, print_server_info


DISKANN_FILES = (
    "ann_disk.index",
    "ann_pq_pivots.bin",
    "ann_pq_compressed.bin",
    "ann_metadata.bin",
    "ann_disk.index_medoids.bin",
)
META_FILES = ("encoding_meta.json", "index_meta.json", "docids.txt")


@dataclass
class SearchHit:
    docid: str
    score: float
    rank: int
    text: str | None = None

    def to_dict(self) -> dict:
        return {"docid": self.docid, "score": self.score,
                "rank": self.rank, "text": self.text}


@dataclass
class SearchTimings:
    """Per-call latency breakdown. ``total_ms`` is wall-clock end-to-end
    inside SearchEngine; the per-stage fields are measured around the actual
    work (encoder.encode, diskann.batch_search, docstore.get_texts) so
    overhead between stages shows up as ``total_ms - sum(stages)``."""
    encode_ms: float
    ann_ms: float
    docstore_fetch_ms: float
    total_ms: float
    n_queries: int
    k: int
    with_text: bool

    def to_dict(self) -> dict:
        return {
            "encode_ms": round(self.encode_ms, 3),
            "ann_ms": round(self.ann_ms, 3),
            "docstore_fetch_ms": round(self.docstore_fetch_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "n_queries": self.n_queries,
            "k": self.k,
            "with_text": self.with_text,
        }


@dataclass
class SearchResult:
    """Structured return value. ``hits[i]`` corresponds to ``queries[i]``."""
    queries: list[str]
    hits: list[list[SearchHit]]
    timings: SearchTimings


@dataclass
class LoadStats:
    index_dir: str = ""
    model_load_s: float = 0.0
    diskann_load_s: float = 0.0
    docstore_load_s: float = 0.0
    docids_load_s: float = 0.0
    warmup_s: float = 0.0
    encoding_meta: dict = field(default_factory=dict)
    index_meta: dict = field(default_factory=dict)
    docstore_manifest: dict = field(default_factory=dict)
    aio_after_load: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "index_dir": self.index_dir,
            "model_load_s": round(self.model_load_s, 2),
            "diskann_load_s": round(self.diskann_load_s, 2),
            "docstore_load_s": round(self.docstore_load_s, 2),
            "docids_load_s": round(self.docids_load_s, 2),
            "warmup_s": round(self.warmup_s, 2),
            "encoding_meta": self.encoding_meta,
            "index_meta": self.index_meta,
            "docstore_manifest": {k: v for k, v in self.docstore_manifest.items()
                                  if k != "dict_size_bytes"},
            "aio_after_load": self.aio_after_load,
        }


# ---------------------------------------------------------------------------
# helpers used by SearchEngine.load() — kept tiny and named for the log line
# ---------------------------------------------------------------------------

def _validate_layout(idx: Path) -> None:
    if not idx.is_dir():
        raise EngineLoadError(
            f"index_dir does not exist or is not a directory: {idx}\n\n"
            f"Build one with tasks/custom_index/scripts/index_pipeline.sh "
            f"(and then build_docstore.py)."
        )
    for name in META_FILES:
        ensure_path(idx / name, diskann_build_hint)
    for name in DISKANN_FILES:
        ensure_path(idx / name, diskann_build_hint)


def _load_meta(idx: Path) -> tuple[dict, dict]:
    enc = json.loads((idx / "encoding_meta.json").read_text())
    im = json.loads((idx / "index_meta.json").read_text())
    print(f"[engine]   encoding_meta: model={enc['model']} dim={enc['dim']} "
          f"task={enc.get('task')!r} q_prompt={enc.get('query_prompt_name')!r}",
          flush=True)
    print(f"[engine]   index_meta: kind={im['kind']} metric={im['metric']} "
          f"n={im['n']:,} R={im['graph_degree']} L={im['complexity']}", flush=True)
    return enc, im


def _load_docids(idx: Path, expected_n: int) -> list[str]:
    t0 = time.perf_counter()
    with open(idx / "docids.txt", "rt", encoding="utf-8") as f:
        ids = [ln.rstrip("\n") for ln in f]
    elapsed = time.perf_counter() - t0
    if len(ids) != expected_n:
        raise EngineLoadError(
            f"docids.txt has {len(ids):,} rows but index_meta says n={expected_n:,}. "
            f"The two were not produced together — rebuild via "
            f"tasks/custom_index/scripts/build_diskann_index.py."
        )
    print(f"[engine]   docids: {len(ids):,} ({elapsed:.1f}s)", flush=True)
    return ids


def _open_docstore(idx: Path, n_expected: int, lru_size: int) -> FlatShardDocStore:
    ds = FlatShardDocStore(idx / "docstore", lru_size=lru_size)
    if ds.manifest["n_records"] != n_expected:
        raise EngineLoadError(
            f"docstore has {ds.manifest['n_records']:,} records but docids.txt "
            f"has {n_expected:,}. Mismatched corpus — rebuild docstore from the "
            f"same parquet shards used to build the index."
        )
    return ds


def _open_diskann(idx: Path, im: dict, enc: dict,
                  threads: int, nodes_to_cache: int):
    import numpy as np
    import diskannpy
    kind = im["kind"]
    metric = im["metric"]
    dim = int(enc["dim"])
    prefix = im.get("index_prefix", "ann")
    if kind == "disk":
        return kind, diskannpy.StaticDiskIndex(
            index_directory=str(idx),
            num_threads=threads,
            num_nodes_to_cache=nodes_to_cache,
            cache_mechanism=1,
            distance_metric=metric, vector_dtype=np.float32,
            dimensions=dim, index_prefix=prefix,
        )
    return kind, diskannpy.StaticMemoryIndex(
        index_directory=str(idx),
        num_threads=threads,
        initial_search_complexity=64,
        distance_metric=metric, vector_dtype=np.float32,
        dimensions=dim, index_prefix=prefix,
    )


def _madvise_willneed_file(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        mm = mmap.mmap(fd, os.fstat(fd).st_size, prot=mmap.PROT_READ)
        mm.madvise(mmap.MADV_WILLNEED)
        mm.close()
        os.close(fd)
    except OSError as e:
        print(f"[engine] madvise WILLNEED failed for {path}: {e}",
              file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# SearchEngine
# ---------------------------------------------------------------------------

class SearchEngine:
    """Load-and-search engine over a built-index dir."""

    def __init__(self):
        self.index_dir: Path | None = None
        self.encoding_meta: dict = {}
        self.index_meta: dict = {}
        self.docids: list[str] = []
        self.encoder: QueryEncoder | None = None
        self.diskann = None
        self.diskann_kind: str = ""
        self.docstore: FlatShardDocStore | None = None
        self.stats: LoadStats = LoadStats()
        self.server_info: dict = {}

    @classmethod
    def load(
        cls,
        index_dir: str | Path,
        *,
        encoder_config: EncoderConfig | None = None,
        diskann_search_threads: int = 4,
        docstore_lru: int = 1024,
        warmup: bool = True,
        warmup_madvise_offsets: bool = True,
        warmup_madvise_pq: bool = False,
        diskann_nodes_to_cache: int = 10_000,
        print_server_details: bool = True,
    ) -> "SearchEngine":
        idx = Path(index_dir).resolve()
        eng = cls()
        eng.index_dir = idx
        eng.stats = LoadStats(index_dir=str(idx))
        if print_server_details:
            eng.server_info = print_server_info(index_path=idx)
        print(f"[engine] loading {idx}", flush=True)

        _validate_layout(idx)
        eng.encoding_meta, eng.index_meta = _load_meta(idx)
        eng.stats.encoding_meta = eng.encoding_meta
        eng.stats.index_meta = eng.index_meta

        t0 = time.perf_counter()
        eng.docids = _load_docids(idx, int(eng.index_meta["n"]))
        eng.stats.docids_load_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        eng.docstore = _open_docstore(idx, len(eng.docids), docstore_lru)
        eng.stats.docstore_manifest = eng.docstore.manifest
        eng.stats.docstore_load_s = time.perf_counter() - t0
        print(f"[engine]   docstore: compression={eng.docstore.compression} "
              f"n_records={eng.docstore.manifest['n_records']:,} "
              f"ratio={eng.docstore.manifest.get('ratio_x') or 1.0:.2f}x "
              f"({eng.stats.docstore_load_s:.1f}s)", flush=True)

        cfg = encoder_config or EncoderConfig()
        print(f"[engine]   loading query encoder (kind={cfg.kind}, "
              f"device={cfg.device}, dtype={cfg.dtype}) ...", flush=True)
        t0 = time.perf_counter()
        eng.encoder = build_encoder(eng.encoding_meta, cfg)
        eng.stats.model_load_s = time.perf_counter() - t0
        print(f"[engine]   encoder loaded ({eng.stats.model_load_s:.1f}s)", flush=True)

        print(f"[engine]   loading DiskANN ({eng.index_meta['kind']}) ...", flush=True)
        t0 = time.perf_counter()
        eng.diskann_kind, eng.diskann = _open_diskann(
            idx, eng.index_meta, eng.encoding_meta,
            threads=diskann_search_threads,
            nodes_to_cache=diskann_nodes_to_cache,
        )
        eng.stats.diskann_load_s = time.perf_counter() - t0
        eng.stats.aio_after_load = aio_slots()
        print(f"[engine]   DiskANN loaded ({eng.stats.diskann_load_s:.1f}s)  "
              f"aio used={eng.stats.aio_after_load['used']}/"
              f"{eng.stats.aio_after_load['cap']}", flush=True)

        if warmup:
            eng._warmup(warmup_madvise_offsets, warmup_madvise_pq)
        print(f"[engine] ready: {idx}", flush=True)
        return eng

    def _warmup(self, madvise_offsets: bool, madvise_pq: bool) -> None:
        print("[engine]   warm-up: encoder + dummy search + docstore decode ...",
              flush=True)
        t0 = time.perf_counter()
        assert self.encoder is not None
        # First call JITs CUDA / CPU paths.
        _ = self.encoder.encode(["warm up the query encoder"])
        # Triggers libaio io_setup + first PQ table page-ins + first decode.
        result = self.search("photosynthesis", k=3, with_text=True)
        assert result.hits and result.hits[0], "warm-up search returned no hits"
        if madvise_offsets and self.docstore is not None:
            self.docstore.madvise_willneed()
        if madvise_pq and self.index_dir is not None:
            _madvise_willneed_file(self.index_dir / "ann_pq_compressed.bin")
        self.stats.warmup_s = time.perf_counter() - t0
        print(f"[engine]   warm-up done ({self.stats.warmup_s:.1f}s)", flush=True)

    # ---- search ---------------------------------------------------------

    def search(self, query: str, k: int = 10, *,
               complexity: int = 64, beam_width: int = 2,
               with_text: bool = True) -> SearchResult:
        return self.search_batch([query], k=k, complexity=complexity,
                                 beam_width=beam_width, with_text=with_text)

    def search_batch(self, queries: list[str], k: int = 10, *,
                     complexity: int = 64, beam_width: int = 2,
                     with_text: bool = True) -> SearchResult:
        if self.diskann is None or self.encoder is None:
            raise EngineLoadError("engine not loaded — call SearchEngine.load(...)")
        t_total_start = time.perf_counter()
        t0 = time.perf_counter()
        q_vecs = self.encoder.encode(queries)
        encode_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        res = self._batch_ann(q_vecs, k, complexity, beam_width)
        ann_s = time.perf_counter() - t0

        hits_by_query = [self._hits_without_text(res, qi, k) for qi in range(len(queries))]
        fetch_s = 0.0
        if with_text and self.docstore is not None:
            fetch_s = self._fill_text_inplace(hits_by_query)

        total_s = time.perf_counter() - t_total_start
        timings = SearchTimings(
            encode_ms=encode_s * 1000, ann_ms=ann_s * 1000,
            docstore_fetch_ms=fetch_s * 1000, total_ms=total_s * 1000,
            n_queries=len(queries), k=k, with_text=with_text,
        )
        return SearchResult(queries=list(queries), hits=hits_by_query, timings=timings)

    def _batch_ann(self, q_vecs, k: int, complexity: int, beam_width: int):
        if self.diskann_kind == "disk":
            return self.diskann.batch_search(
                queries=q_vecs, k_neighbors=k, complexity=complexity,
                beam_width=beam_width, num_threads=0,
            )
        return self.diskann.batch_search(
            queries=q_vecs, k_neighbors=k, complexity=complexity, num_threads=0,
        )

    def _hits_without_text(self, res, qi: int, k: int) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for rank in range(k):
            row = int(res.identifiers[qi, rank])
            if 0 <= row < len(self.docids):
                hits.append(SearchHit(
                    docid=self.docids[row],
                    score=float(res.distances[qi, rank]),
                    rank=rank + 1,
                ))
        return hits

    def _fill_text_inplace(self, hits_by_query: list[list[SearchHit]]) -> float:
        """Coalesce a single docstore call across all queries in the batch
        and splice the texts back in. Returns elapsed seconds."""
        flat = [h for hits in hits_by_query for h in hits]
        if not flat:
            return 0.0
        assert self.docstore is not None
        t0 = time.perf_counter()
        texts = self.docstore.get_texts([h.docid for h in flat])
        elapsed = time.perf_counter() - t0
        for h, t in zip(flat, texts):
            h.text = t
        return elapsed

    def close(self) -> None:
        if self.docstore is not None:
            self.docstore.close()
