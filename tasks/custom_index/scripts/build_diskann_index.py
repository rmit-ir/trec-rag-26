#!/usr/bin/env python3
"""Build a DiskANN index from per-shard *.fbin or a single vectors.fbin.

Two input modes:
  --vectors PATH                use a single vectors.fbin as-is
  --encoded-dir DIR             concatenate all *.fbin (and *.docids.txt) under
                                DIR in sorted-name order into vectors.fbin +
                                docids.txt, then build from those.

The on-disk index variant is what the CPU+SSD Rust serve task will load.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path


FBIN_HEADER_SIZE = 8  # uint32 n + uint32 dim


def read_fbin_header(p: Path) -> tuple[int, int]:
    with open(p, "rb") as f:
        n, d = struct.unpack("<II", f.read(FBIN_HEADER_SIZE))
    return n, d


def concat_fbin(shard_fbins: list[Path], out_fbin: Path) -> tuple[int, int]:
    """Concatenate per-shard .fbin files into a single .fbin with patched header."""
    if not shard_fbins:
        raise SystemExit("no shard .fbin files to concatenate")
    total = 0
    dim = None
    for p in shard_fbins:
        n, d = read_fbin_header(p)
        if dim is None:
            dim = d
        elif d != dim:
            raise SystemExit(f"dim mismatch: {p} has dim={d}, expected {dim}")
        total += n
    out_fbin.parent.mkdir(parents=True, exist_ok=True)
    with open(out_fbin, "wb") as out:
        out.write(struct.pack("<II", total, dim))
        for p in shard_fbins:
            with open(p, "rb") as src:
                src.seek(FBIN_HEADER_SIZE)
                # Stream copy; 16MB chunks keep memory tiny.
                while True:
                    buf = src.read(16 * 1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
    return total, dim


def concat_docids(shard_docs: list[Path], out_docs: Path) -> int:
    n = 0
    with open(out_docs, "wt", encoding="utf-8") as out:
        for p in shard_docs:
            with open(p, "rt", encoding="utf-8") as src:
                for line in src:
                    if line and not line.endswith("\n"):
                        line += "\n"
                    out.write(line)
                    n += 1
    return n


def materialize_from_encoded_dir(encoded_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    fbins = sorted(encoded_dir.glob("*.fbin"))
    fbins = [p for p in fbins if not p.name.endswith(".tmp")]
    docs = []
    for fb in fbins:
        d = fb.with_suffix("").with_suffix(".docids.txt")
        # the above turns shard_00000.fbin -> shard_00000.docids.txt only if naming
        # was exactly shard_XXX.fbin (no extra suffix). Be defensive:
        if not d.exists():
            d = encoded_dir / (fb.stem + ".docids.txt")
        if not d.exists():
            raise SystemExit(f"missing docids file for {fb}: tried {d}")
        docs.append(d)

    out_dir.mkdir(parents=True, exist_ok=True)
    vec_out = out_dir / "vectors.fbin"
    doc_out = out_dir / "docids.txt"

    print(f"[concat] {len(fbins)} shards -> {vec_out}", flush=True)
    total, dim = concat_fbin(fbins, vec_out)
    n_docs = concat_docids(docs, doc_out)
    if total != n_docs:
        raise SystemExit(f"row mismatch after concat: fbin={total} docids={n_docs}")
    print(f"[concat] total_vectors={total} dim={dim}", flush=True)

    # Carry a manifest describing the concat for auditability.
    manifest = {
        "shards": [p.name for p in fbins],
        "total_vectors": total,
        "dim": dim,
    }
    (out_dir / "concat_manifest.json").write_text(json.dumps(manifest, indent=2))
    return vec_out, doc_out


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--vectors", type=Path,
                     help="single vectors.fbin to build from")
    src.add_argument("--encoded-dir", type=Path,
                     help="directory of per-shard *.fbin + *.docids.txt to concat first")
    ap.add_argument("--out-dir", required=True, type=Path,
                    help="where to write the built index (and concatenated vectors)")
    # Pipeline-owned knobs — required, no defaults here.
    ap.add_argument("--kind", required=True, choices=["disk", "memory"])
    ap.add_argument("--metric", required=True, choices=["mips", "l2", "cosine"])
    ap.add_argument("--graph-degree", type=int, default=64)
    ap.add_argument("--complexity", type=int, default=100)
    ap.add_argument("--search-mem-gb", type=float, default=2.0)
    ap.add_argument("--build-mem-gb", type=float, default=8.0)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--pq-disk-bytes", type=int, default=0)
    ap.add_argument("--index-prefix", default="ann")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.encoded_dir:
        vec_path, _ = materialize_from_encoded_dir(args.encoded_dir, args.out_dir)
        # Carry encoder metadata (model name, dim, normalize) into the index dir
        # so search.py / the Rust serve task can recover it without re-reading
        # the per-shard meta files.
        shard_meta_files = sorted(args.encoded_dir.glob("*.meta.json"))
        if shard_meta_files:
            first = json.loads(shard_meta_files[0].read_text())
            carry = {
                "model": first["model"],
                "dim": first["dim"],
                "normalize": first["normalize"],
                "max_seq_len": first["max_seq_len"],
                "vectors_format": first.get("vectors_format", "diskann_fbin"),
                "task": first.get("task"),
                "prompt_name": first.get("prompt_name"),
                "query_prompt_name": first.get("query_prompt_name"),
                "trust_remote_code": first.get("trust_remote_code", False),
                "dtype": first.get("dtype"),
                "n_shards": len(shard_meta_files),
            }
            # Matryoshka provenance (set by truncate_vectors.py). Consumers
            # (search.py, search_serve) truncate+renormalize query vectors
            # to `dim` when matryoshka_truncated_from is present.
            for key in ("matryoshka_truncated_from", "renormalized"):
                if key in first:
                    carry[key] = first[key]
            (args.out_dir / "encoding_meta.json").write_text(
                json.dumps(carry, indent=2))
    else:
        vec_path = args.vectors

    import numpy as np
    import diskannpy

    t0 = time.time()
    n, dim = read_fbin_header(vec_path)
    print(f"[index] kind={args.kind} metric={args.metric} R={args.graph_degree} "
          f"L={args.complexity} n={n} dim={dim} vectors={vec_path}", flush=True)

    if args.kind == "disk":
        diskannpy.build_disk_index(
            data=str(vec_path),
            distance_metric=args.metric,
            index_directory=str(args.out_dir),
            complexity=args.complexity,
            graph_degree=args.graph_degree,
            search_memory_maximum=args.search_mem_gb,
            build_memory_maximum=args.build_mem_gb,
            num_threads=args.threads,
            pq_disk_bytes=args.pq_disk_bytes,
            vector_dtype=np.float32,
            index_prefix=args.index_prefix,
        )
    else:
        diskannpy.build_memory_index(
            data=str(vec_path),
            distance_metric=args.metric,
            index_directory=str(args.out_dir),
            complexity=args.complexity,
            graph_degree=args.graph_degree,
            num_threads=args.threads,
            alpha=1.2,
            use_pq_build=False,
            num_pq_bytes=0,
            use_opq=False,
            vector_dtype=np.float32,
            index_prefix=args.index_prefix,
        )

    elapsed = time.time() - t0
    meta = {
        "kind": args.kind,
        "metric": args.metric,
        "graph_degree": args.graph_degree,
        "complexity": args.complexity,
        "search_mem_gb": args.search_mem_gb,
        "build_mem_gb": args.build_mem_gb,
        "pq_disk_bytes": args.pq_disk_bytes,
        "index_prefix": args.index_prefix,
        "vectors": str(vec_path),
        "n": n,
        "dim": dim,
        "elapsed_seconds": round(elapsed, 2),
    }
    (args.out_dir / "index_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[index] built in {elapsed:.1f}s -> {args.out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
