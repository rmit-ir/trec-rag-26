#!/usr/bin/env python3
"""Matryoshka-truncate per-shard encoded vectors into a parallel encoded dir.

Reads <stem>.fbin (native-dim float32) + <stem>.docids.txt + <stem>.meta.json
from --encoded-dir, keeps the first --truncate-dim dims, L2-renormalizes each
vector (required after matryoshka slicing), and writes the same per-shard
layout into --out-dir:

  <stem>.fbin         truncated vectors (uint32 n, uint32 dim, n*dim float32)
  <stem>.docids.txt   hardlink to the source file (identical rows)
  <stem>.meta.json    source meta with dim updated and
                      matryoshka_truncated_from / renormalized recorded

The output dir is a drop-in --encoded-dir for build_diskann_index.py. The
native-dim source dir is left untouched (keep it — re-deriving any dim from
it is cheap; re-encoding is GPU-days).

Resumable: shards whose output .fbin already exists are skipped; writes go to
.tmp and are renamed on completion.

Run in the tasks/custom_index env (numpy only).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
from pathlib import Path

import numpy as np

FBIN_HEADER = 8  # uint32 n + uint32 dim
BATCH = 200_000  # rows per read — ~600 MB at 768d, keeps RAM tame


def truncate_shard(src_fbin: Path, out_fbin: Path, td: int) -> tuple[int, int]:
    """Write the first td dims of every vector, renormalized. Returns (n, native_dim)."""
    tmp = out_fbin.with_suffix(out_fbin.suffix + ".tmp")
    with open(src_fbin, "rb") as f, open(tmp, "wb") as out:
        n, dim = struct.unpack("<II", f.read(FBIN_HEADER))
        if td > dim:
            raise SystemExit(f"truncate_dim {td} > native dim {dim} in {src_fbin}")
        out.write(struct.pack("<II", n, td))
        left = n
        while left:
            rows = min(left, BATCH)
            arr = np.fromfile(f, dtype=np.float32, count=rows * dim)
            if arr.size != rows * dim:
                raise SystemExit(f"short read in {src_fbin}: expected {rows * dim}, got {arr.size}")
            arr = arr.reshape(rows, dim)[:, :td].copy()
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            np.divide(arr, norms, out=arr, where=norms > 0)
            arr.tofile(out)
            left -= rows
    os.replace(tmp, out_fbin)
    return n, dim


def link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoded-dir", required=True, type=Path,
                    help="dir of native-dim per-shard *.fbin + *.docids.txt + *.meta.json")
    ap.add_argument("--out-dir", required=True, type=Path,
                    help="dir to write the truncated per-shard layout into")
    ap.add_argument("--truncate-dim", required=True, type=int)
    args = ap.parse_args()

    fbins = sorted(p for p in args.encoded_dir.glob("*.fbin")
                   if not p.name.endswith(".tmp"))
    if not fbins:
        raise SystemExit(f"no *.fbin under {args.encoded_dir}")
    if args.out_dir.resolve() == args.encoded_dir.resolve():
        raise SystemExit("--out-dir must differ from --encoded-dir (source is kept)")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    td = args.truncate_dim
    total = 0
    done = 0
    skipped = 0
    for fb in fbins:
        stem = fb.stem
        out_fbin = args.out_dir / fb.name
        src_doc = args.encoded_dir / f"{stem}.docids.txt"
        src_meta = args.encoded_dir / f"{stem}.meta.json"
        if not src_doc.exists():
            raise SystemExit(f"missing docids file for {fb}: {src_doc}")

        if out_fbin.exists():
            n, _ = struct.unpack("<II", open(out_fbin, "rb").read(FBIN_HEADER))
            skipped += 1
        else:
            n, native = truncate_shard(fb, out_fbin, td)
            done += 1
            print(f"[truncate] {fb.name}: {n} vecs {native}->{td}", flush=True)
        total += n

        link_or_copy(src_doc, args.out_dir / src_doc.name)
        if src_meta.exists():
            meta = json.loads(src_meta.read_text())
            meta.update({"dim": td,
                         "matryoshka_truncated_from": int(meta["dim"]) if "dim" in meta else None,
                         "renormalized": True})
            (args.out_dir / src_meta.name).write_text(json.dumps(meta, indent=2))

    print(f"[truncate] {len(fbins)} shards ({done} truncated, {skipped} already done), "
          f"{total} vectors x {td}d -> {args.out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
