#!/usr/bin/env python3
"""Chunk prepared corpus jsonl shards into chunked-corpus shards.

Reads shard_NNNNN.jsonl ({"id","contents"} per line) from --corpus-dir,
applies a chunking strategy from tasks/chunking-strategy/scripts/chunkers.py
to every doc, and writes the same per-shard layout into --out-dir with chunk
ids <docid>_p<page> (page from 1). Emits shard_NNNNN.jsonl.ready markers and
a final .prepare_done, so encode_documents.py --watch can consume shards as
they appear (chunking and GPU encoding overlap).

Parallel over shards (--workers), per-shard resumable (existing outputs are
skipped), atomic (.tmp + rename). The chunking config is recorded in
--out-dir/chunking_meta.json — carry it into the index dir so serving can
re-derive chunk text from the parent doc deterministically.

Run in the tasks/custom_index env (stdlib only, but keep envs consistent).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHUNKERS_DIR = (HERE / ".." / ".." / "chunking-strategy" / "scripts").resolve()
sys.path.insert(0, str(CHUNKERS_DIR))
import chunkers  # noqa: E402


def chunk_shard(src: str, out_dir: str, strategy: str, tpw: float,
                params: dict[str, int]) -> tuple[str, int, int, bool]:
    src_p = Path(src)
    out = Path(out_dir) / src_p.name
    ready = Path(out_dir) / (src_p.name + ".ready")
    if out.exists():
        if not ready.exists():
            ready.touch()
        return src_p.name, 0, 0, True
    tmp = out.with_name(out.name + ".tmp")
    n_docs = n_chunks = 0
    with open(src_p, "rt", encoding="utf-8") as fin, \
         open(tmp, "wt", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            rec = json.loads(line)
            parts = chunkers.run_strategy(strategy, rec["contents"], tpw, params)
            for k, c in enumerate(parts):
                fout.write(json.dumps({"id": f"{rec['id']}_p{k + 1}",
                                       "contents": c},
                                      ensure_ascii=False) + "\n")
            n_docs += 1
            n_chunks += len(parts)
    os.replace(tmp, out)
    ready.touch()
    return src_p.name, n_docs, n_chunks, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", required=True, type=Path,
                    help="prepared corpus shards (shard_*.jsonl)")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--strategy", required=True, choices=sorted(chunkers.STRATEGIES))
    ap.add_argument("--tokens-per-word", type=float, default=1.3)
    ap.add_argument("--param", action="append", default=[], metavar="K=V",
                    help="strategy param, repeatable (e.g. --param target_max=500)")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    params: dict[str, int] = {}
    for kv in args.param:
        k, sep, v = kv.partition("=")
        if not sep or not v.lstrip("-").isdigit():
            raise SystemExit(f"bad --param {kv!r}, expected K=<int>")
        params[k] = int(v)

    shards = sorted(args.corpus_dir.glob("shard_*.jsonl"))
    if not shards:
        raise SystemExit(f"no shard_*.jsonl under {args.corpus_dir}")
    if not (args.corpus_dir / ".prepare_done").exists():
        print(f"[chunk] WARNING: {args.corpus_dir}/.prepare_done missing — "
              f"source corpus may be incomplete", flush=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "chunker": "tasks/chunking-strategy/scripts/chunkers.py",
        "strategy": args.strategy,
        "tokens_per_word": args.tokens_per_word,
        "params": params,
        "id_scheme": "<docid>_p<page>, page from 1",
        "source_corpus": str(args.corpus_dir),
        "n_shards": len(shards),
    }
    (args.out_dir / "chunking_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[chunk] {len(shards)} shards, strategy={args.strategy} "
          f"params={params} workers={args.workers}", flush=True)

    t0 = time.time()
    total_docs = total_chunks = skipped = 0
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(chunk_shard, str(s), str(args.out_dir),
                          args.strategy, args.tokens_per_word, params)
                for s in shards]
        for fut in as_completed(futs):
            stem, nd, nc, was_skipped = fut.result()
            done += 1
            if was_skipped:
                skipped += 1
            else:
                total_docs += nd
                total_chunks += nc
            if done % 50 == 0 or done == len(shards):
                rate = done / max(time.time() - t0, 1e-9)
                eta_h = (len(shards) - done) / max(rate, 1e-9) / 3600
                print(f"[chunk] {done}/{len(shards)} shards "
                      f"({skipped} skipped) docs={total_docs:,} "
                      f"chunks={total_chunks:,} eta={eta_h:.1f}h", flush=True)

    (args.out_dir / ".prepare_done").touch()
    dt = time.time() - t0
    print(f"[chunk] DONE {len(shards)} shards in {dt / 3600:.2f}h — "
          f"{total_docs:,} docs -> {total_chunks:,} chunks "
          f"({total_chunks / max(total_docs, 1):.3f}/doc, "
          f"{skipped} shards were pre-existing)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
