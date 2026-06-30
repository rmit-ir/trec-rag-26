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

from docstore import DocstoreFetchStats, DocstoreFetchTimings, FlatShardDocStore
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
    """Per-call wall-clock latencies (ms). Descriptive counts (k, n_queries,
    docstore.n_records etc.) go in ``SearchMeta``."""
    encode_ms: float
    ann_ms: float
    docstore_fetch_ms: float
    total_ms: float
    docstore: DocstoreFetchTimings | None = None

    def to_dict(self) -> dict:
        out = {
            "encode_ms": round(self.encode_ms, 3),
            "ann_ms": round(self.ann_ms, 3),
            "docstore_fetch_ms": round(self.docstore_fetch_ms, 3),
            "total_ms": round(self.total_ms, 3),
        }
        if self.docstore is not None:
            out["docstore"] = self.docstore.to_dict()
        return out


@dataclass
class SearchMeta:
    """What the request asked for + what the fetch did. Descriptive integers
    and booleans only — never milliseconds."""
    n_queries: int
    k: int
    with_text: bool
    docstore: DocstoreFetchStats | None = None

    def to_dict(self) -> dict:
        out = {
            "n_queries": self.n_queries,
            "k": self.k,
            "with_text": self.with_text,
        }
        if self.docstore is not None:
            out["docstore"] = self.docstore.to_dict()
        return out


@dataclass
class SearchResult:
    """Structured return value. ``hits[i]`` corresponds to ``queries[i]``."""
    queries: list[str]
    hits: list[list[SearchHit]]
    timings: SearchTimings
    metadata: SearchMeta


@dataclass
class LoadStats:
    index_dir: str = ""
    meta_load_s: float = 0.0
    model_load_s: float = 0.0
    diskann_load_s: float = 0.0
    docstore_load_s: float = 0.0
    docids_load_s: float = 0.0
    warmup_s: float = 0.0
    total_load_s: float = 0.0
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


def _open_docstore(idx: Path, n_expected: int, lru_size: int,
                    parallel: int, parallel_min_k: int) -> FlatShardDocStore:
    ds = FlatShardDocStore(idx / "docstore", lru_size=lru_size,
                            parallel=parallel, parallel_min_k=parallel_min_k)
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
        docstore_parallel: int = 8,
        docstore_parallel_min_k: int = 64,
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

        t_total_start = time.perf_counter()
        t0 = time.perf_counter()
        _validate_layout(idx)
        eng.encoding_meta, eng.index_meta = _load_meta(idx)
        eng.stats.meta_load_s = time.perf_counter() - t0
        eng.stats.encoding_meta = eng.encoding_meta
        eng.stats.index_meta = eng.index_meta

        t0 = time.perf_counter()
        eng.docids = _load_docids(idx, int(eng.index_meta["n"]))
        eng.stats.docids_load_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        eng.docstore = _open_docstore(idx, len(eng.docids), docstore_lru,
                                       parallel=docstore_parallel,
                                       parallel_min_k=docstore_parallel_min_k)
        eng.stats.docstore_manifest = eng.docstore.manifest
        eng.stats.docstore_load_s = time.perf_counter() - t0
        parallel_note = (f" parallel={docstore_parallel} "
                          f"min_k={docstore_parallel_min_k}"
                          if docstore_parallel > 1 else " parallel=off")
        print(f"[engine]   docstore: compression={eng.docstore.compression} "
              f"n_records={eng.docstore.manifest['n_records']:,} "
              f"ratio={eng.docstore.manifest.get('ratio_x') or 1.0:.2f}x"
              f"{parallel_note} ({eng.stats.docstore_load_s:.1f}s)",
              flush=True)

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
        eng._log_fd_usage()
        eng.stats.total_load_s = time.perf_counter() - t_total_start
        eng._print_load_summary()
        print(f"[engine] ready: {idx}", flush=True)
        return eng

    def _print_load_summary(self) -> None:
        """Per-phase wall-clock breakdown of engine load. Helps an operator
        see which step dominated their startup time (usually DiskANN load
        on first-touch, encoder load when the model isn't HF-cached, or
        docids when the corpus has 100M+ rows)."""
        s = self.stats
        rows = [
            ("meta",     s.meta_load_s),
            ("docids",   s.docids_load_s),
            ("docstore", s.docstore_load_s),
            ("encoder",  s.model_load_s),
            ("diskann",  s.diskann_load_s),
            ("warmup",   s.warmup_s),
        ]
        print("[engine]   load summary:", flush=True)
        for name, secs in rows:
            pct = (secs / s.total_load_s * 100.0) if s.total_load_s > 0 else 0.0
            print(f"[engine]     {name:<10s} {secs:7.2f} s  ({pct:5.1f}%)",
                  flush=True)
        print(f"[engine]     {'-' * 32}", flush=True)
        print(f"[engine]     {'total':<10s} {s.total_load_s:7.2f} s "
              f"({s.total_load_s/60:.1f} min)", flush=True)

    def _log_fd_usage(self) -> None:
        """Surface the post-warmup file-descriptor footprint so an operator
        can spot a low RLIMIT_NOFILE soft cap before the first real
        request OOMs. Best effort — never raises."""
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            open_fds = len(os.listdir("/proc/self/fd"))
            headroom = soft - open_fds
            warn = "  ⚠ low headroom" if headroom < 256 else ""
            print(f"[engine]   fd usage: open={open_fds}  soft={soft}  hard={hard}"
                  f"  headroom={headroom}{warn}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[engine]   fd usage probe failed: {e!r}",
                  file=sys.stderr, flush=True)

    def _warmup(self, madvise_offsets: bool, madvise_pq: bool) -> None:
        """Each phase logs its own elapsed so the operator can see WHICH
        step is slow on first launch. madvise_pq=true against a 64 GB PQ
        table can take 30-90 s on its own; the natural dummy search already
        faults in hot pages, so consider leaving madvise_pq off."""
        print("[engine]   warm-up: starting", flush=True)
        t_total = time.perf_counter()
        assert self.encoder is not None

        t = time.perf_counter()
        _ = self.encoder.encode(["warm up the query encoder"])
        print(f"[engine]   warm-up     encoder JIT:        "
              f"{(time.perf_counter() - t):.2f}s", flush=True)

        t = time.perf_counter()
        result = self.search("photosynthesis", k=3, with_text=True)
        assert result.hits and result.hits[0], "warm-up search returned no hits"
        print(f"[engine]   warm-up     dummy search k=3:   "
              f"{(time.perf_counter() - t):.2f}s", flush=True)

        if madvise_offsets and self.docstore is not None:
            t = time.perf_counter()
            self.docstore.madvise_willneed()
            print(f"[engine]   warm-up     madvise offsets:    "
                  f"{(time.perf_counter() - t):.2f}s "
                  f"({self.docstore.manifest['n_shards']} shards)", flush=True)
        if madvise_pq and self.index_dir is not None:
            t = time.perf_counter()
            _madvise_willneed_file(self.index_dir / "ann_pq_compressed.bin")
            print(f"[engine]   warm-up     madvise PQ table:   "
                  f"{(time.perf_counter() - t):.2f}s", flush=True)

        self.stats.warmup_s = time.perf_counter() - t_total
        print(f"[engine]   warm-up done (total {self.stats.warmup_s:.1f}s)",
              flush=True)

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
        ds_timings: DocstoreFetchTimings | None = None
        ds_stats: DocstoreFetchStats | None = None
        if with_text and self.docstore is not None:
            ds_timings = DocstoreFetchTimings()
            ds_stats = DocstoreFetchStats()
            fetch_s = self._fill_text_inplace(hits_by_query, ds_timings, ds_stats)

        total_s = time.perf_counter() - t_total_start
        timings = SearchTimings(
            encode_ms=encode_s * 1000, ann_ms=ann_s * 1000,
            docstore_fetch_ms=fetch_s * 1000, total_ms=total_s * 1000,
            docstore=ds_timings,
        )
        metadata = SearchMeta(
            n_queries=len(queries), k=k, with_text=with_text,
            docstore=ds_stats,
        )
        return SearchResult(queries=list(queries), hits=hits_by_query,
                            timings=timings, metadata=metadata)

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

    def _fill_text_inplace(
        self,
        hits_by_query: list[list[SearchHit]],
        timings: DocstoreFetchTimings | None = None,
        stats: DocstoreFetchStats | None = None,
    ) -> float:
        """Coalesce a single docstore call across all queries in the batch
        and splice the texts back in. Returns elapsed seconds. If
        ``timings`` and/or ``stats`` are provided, they are filled with the
        per-phase latencies / descriptive counts."""
        flat = [h for hits in hits_by_query for h in hits]
        if not flat:
            return 0.0
        assert self.docstore is not None
        t0 = time.perf_counter()
        texts = self.docstore.get_texts([h.docid for h in flat],
                                         timings=timings, stats=stats)
        elapsed = time.perf_counter() - t0
        for h, t in zip(flat, texts):
            h.text = t
        return elapsed

    def close(self) -> None:
        if self.docstore is not None:
            self.docstore.close()
