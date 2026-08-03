#!/usr/bin/env python3
"""Stage B: GPU encode from the pre-tokenized ragged store (Stage A output).

Why this exists: the text encoder (encode_documents.py) is bottlenecked on
single-threaded tokenization in jina's custom EuroBERT path, leaving the GPUs
~30% idle. Stage A (tokenize_corpus.py) moves all tokenization off the critical
path into a reusable on-disk token store; this stage reads those token IDs,
so encode becomes GPU-bound and can use large, length-sorted batches.

Correctness: reproduces jina's encode() exactly (verified cosine == 1.0, see
verify_pretok.py). We call the ST module's own forward() with a features dict:
    forward({"input_ids", "attention_mask"}, task="retrieval") -> sentence_embedding
which sets the retrieval adapter, runs the model, does last-token pooling, and
L2-normalizes — identical to model.encode(prompt_name="document", task="retrieval").

Per-shard outputs match encode_documents.py byte-for-byte in layout so the
downstream truncate/build steps are unchanged:
    <stem>.fbin        (uint32 n, uint32 dim, then n*dim float32)
    <stem>.docids.txt  one chunk id per line, parallel to fbin rows
    <stem>.meta.json   {model, dim, count, normalize, ...}

Input store (per shard, from Stage A):
    <stem>.ids.u32     int32, all chunks' token ids concatenated
    <stem>.len.i16     int16, [N] per-chunk length
    <stem>.docids.txt  one id per line
    <stem>.ready       marker that the three above are complete

Parent mode discovers token shards, splits them round-robin across the visible
GPUs, and spawns one worker subprocess per GPU (CUDA pinned). No watch mode:
Stage A finishes before this runs.

Run:
  uv run --project tasks/custom_index python \
    tasks/custom_index/scripts/encode_pretokenized.py \
    --tokens-dir tasks/custom_index/work/climbmix-chunked/tokens \
    --out-dir    tasks/custom_index/work/climbmix-chunked/encoded \
    --model RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d \
    --batch-size 256 --dtype auto
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from env_util import DEFAULT_MODEL, load_repo_env
from st_embed import embed_features, resolve_out_dim

# Pull HF_TOKEN from the repo .env so the private default model authenticates.
# Must run before any HF download (parent spawns workers that inherit os.environ).
load_repo_env()


def parse_bool(s: str) -> bool:
    return str(s).lower() in ("1", "true", "yes", "y")


def resolve_dtype(arg: str, device: str):
    import torch
    if arg == "auto":
        return torch.bfloat16 if device == "cuda" else torch.float32
    return {"float32": torch.float32,
            "float16": torch.float16,
            "bfloat16": torch.bfloat16}[arg]


def detect_num_gpus() -> int:
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.device_count()
    except Exception:
        pass
    return 0


def detect_device(arg: str) -> str:
    if arg not in ("auto", "cuda"):
        return arg
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def split_round_robin(items: list, n: int) -> list[list]:
    buckets: list[list] = [[] for _ in range(n)]
    for i, x in enumerate(items):
        buckets[i % n].append(x)
    return buckets


# ---------------------------------------------------------------------------
# parent
# ---------------------------------------------------------------------------

def discover_token_shards(tokens_dir: Path) -> list[str]:
    """Stems that have a .ready marker (Stage A finished them)."""
    stems = []
    for r in sorted(tokens_dir.glob("*.ready")):
        stem = r.name[:-len(".ready")]
        if (tokens_dir / f"{stem}.ids.u32").exists():
            stems.append(stem)
    return stems


def todo_stems(tokens_dir: Path, out_dir: Path, stems: list[str],
               force: bool) -> list[str]:
    todo = []
    for stem in stems:
        if (not force
                and (out_dir / f"{stem}.fbin").exists()
                and (out_dir / f"{stem}.docids.txt").exists()
                and (out_dir / f"{stem}.meta.json").exists()):
            continue
        todo.append(stem)
    return todo


def run_parent(args) -> int:
    tokens_dir = Path(args.tokens_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stems = discover_token_shards(tokens_dir)
    if not stems:
        print(f"[parent] no ready token shards in {tokens_dir}", file=sys.stderr)
        return 1
    todo = todo_stems(tokens_dir, out_dir, stems, args.force)
    n_gpus = detect_num_gpus()
    n_workers = args.num_workers if args.num_workers > 0 else (n_gpus or 1)
    print(f"[parent] token_shards={len(stems)} todo={len(todo)} "
          f"gpus={n_gpus} workers={n_workers} batch_size={args.batch_size}",
          flush=True)
    if not todo:
        print("[parent] nothing to do — all shards encoded", flush=True)
        return 0

    buckets = split_round_robin(todo, n_workers)
    step_start = time.time()
    procs = []
    for rank, my in enumerate(buckets):
        if not my:
            continue
        env = os.environ.copy()
        if n_gpus > 0:
            env["CUDA_VISIBLE_DEVICES"] = str(rank % n_gpus)
        device = "cpu" if n_gpus == 0 else args.device
        cmd = [
            sys.executable, __file__,
            "--worker-rank", str(rank),
            "--tokens-dir", str(tokens_dir),
            "--out-dir", str(out_dir),
            "--model", args.model,
            "--batch-size", str(args.batch_size),
            "--device", device,
            "--dtype", args.dtype,
            "--task", args.task,
            "--prompt-name", args.prompt_name,
            "--query-prompt-name", args.query_prompt_name,
            "--trust-remote-code", "true" if parse_bool(args.trust_remote_code) else "false",
            "--normalize", "true" if parse_bool(args.normalize) else "false",
            "--max-seq-len", str(args.max_seq_len),
            "--log-every", str(args.log_every),
            "--total-shards", str(len(todo)),
            "--step-start-epoch", f"{step_start:.6f}",
            "--stems", *my,
        ]
        print(f"[parent] spawn rank={rank} "
              f"CUDA_VISIBLE_DEVICES={env.get('CUDA_VISIBLE_DEVICES','')} "
              f"shards={len(my)}", flush=True)
        procs.append(subprocess.Popen(cmd, env=env))

    rc = 0
    for p in procs:
        if p.wait() != 0:
            rc = 1
    done = len(list(out_dir.glob("*.fbin")))
    print(f"[parent] DONE rc={rc} encoded_fbin={done} "
          f"elapsed={(time.time()-step_start)/3600:.2f}h", flush=True)
    return rc


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------

def _load_shard(tokens_dir: Path, stem: str):
    import numpy as np
    ids = np.fromfile(tokens_dir / f"{stem}.ids.u32", dtype=np.int32)
    lens = np.fromfile(tokens_dir / f"{stem}.len.i16", dtype=np.int16).astype(np.int64)
    off = np.empty(len(lens) + 1, dtype=np.int64)
    off[0] = 0
    np.cumsum(lens, out=off[1:])
    docids = (tokens_dir / f"{stem}.docids.txt").read_text(
        encoding="utf-8").splitlines()
    if not (len(docids) == len(lens) == (len(off) - 1)):
        raise ValueError(f"{stem}: len mismatch docids={len(docids)} lens={len(lens)}")
    return ids, lens, off, docids


def encode_one_shard(tokens_dir, out_dir, stem, model, dim, pad_id, task,
                     batch_size, rank, log_every, shard_idx, n_shards,
                     total_shards, step_start, meta, model_name, normalize,
                     max_seq_len):
    import numpy as np
    import torch

    ids, lens, off, docids = _load_shard(tokens_dir, stem)
    n = len(docids)
    tmp_fbin = out_dir / f"{stem}.fbin.tmp"
    tmp_docs = out_dir / f"{stem}.docids.txt.tmp"
    t0 = time.time()
    print(f"[worker {rank}] START {stem} ({n:,} chunks, "
          f"mean_len={lens.mean():.0f}, batch={batch_size})", flush=True)

    # length-descending order => uniform batches, ~zero pad waste, OOM fails fast
    order = np.argsort(-lens, kind="stable")
    device = model.device

    vec_f = open(tmp_fbin, "wb")
    np.array([0, dim], dtype=np.uint32).tofile(vec_f)  # header placeholder
    out_docids: list[str] = []
    seen = last_log = 0

    for s in range(0, n, batch_size):
        rows = order[s:s + batch_size]
        blens = lens[rows]
        maxl = int(blens.max())
        bids = np.full((len(rows), maxl), pad_id, dtype=np.int64)
        bmask = np.zeros((len(rows), maxl), dtype=np.int64)
        for j, r in enumerate(rows):
            a, b = off[r], off[r + 1]
            L = b - a
            bids[j, :L] = ids[a:b]
            bmask[j, :L] = 1
        feats = {
            "input_ids": torch.from_numpy(bids).to(device),
            "attention_mask": torch.from_numpy(bmask).to(device),
        }
        # Full ST pipeline + Matryoshka truncate/renorm — reproduces
        # model.encode(prompt_name="document", task="retrieval") exactly.
        emb = embed_features(model, feats, task=task)
        emb = emb.float().cpu().numpy().astype(np.float32, copy=False)
        emb.tofile(vec_f)
        out_docids.extend(docids[r] for r in rows)
        seen += len(rows)
        if seen - last_log >= log_every:
            el = time.time() - t0
            print(f"[worker {rank}] {stem} {seen:,}/{n:,} "
                  f"({seen/el:.0f} ch/s)", flush=True)
            last_log = seen

    vec_f.seek(0)
    np.array([seen, dim], dtype=np.uint32).tofile(vec_f)
    vec_f.close()
    tmp_docs.write_text("".join(d + "\n" for d in out_docids), encoding="utf-8")

    elapsed = time.time() - t0
    shard_meta = {
        "model": model_name, "dim": int(dim), "count": int(seen),
        "normalize": normalize, "max_seq_len": int(max_seq_len),
        "batch_size": int(batch_size), "stem": stem, "rank": rank,
        "elapsed_seconds": round(elapsed, 2),
        "vectors_format": "diskann_fbin", "source": "pretokenized",
        **meta,
    }
    (out_dir / f"{stem}.meta.json").write_text(json.dumps(shard_meta, indent=2))
    os.replace(tmp_fbin, out_dir / f"{stem}.fbin")
    os.replace(tmp_docs, out_dir / f"{stem}.docids.txt")
    gdone = len(list(out_dir.glob("*.fbin")))
    print(f"[worker {rank}] DONE {stem} {seen:,} in {elapsed:.1f}s "
          f"({seen/elapsed:.0f} ch/s) | global {gdone}/{total_shards} "
          f"({(time.time()-step_start)/3600:.2f}h)", flush=True)


def run_worker(args) -> int:
    import torch
    from sentence_transformers import SentenceTransformer

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens_dir = Path(args.tokens_dir)
    device = detect_device(args.device)
    dtype = resolve_dtype(args.dtype, device)
    trust = parse_bool(args.trust_remote_code)
    normalize = parse_bool(args.normalize)
    print(f"[worker {args.worker_rank}] device={device} dtype={dtype} "
          f"CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES','')}",
          flush=True)

    model = SentenceTransformer(args.model, device=device,
                                trust_remote_code=trust,
                                model_kwargs={"dtype": dtype})
    model.max_seq_length = args.max_seq_len
    module = model[0]
    tok = module.tokenizer
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0

    # Final output dim = post-truncation dim encode() returns (256 for the
    # matryoshka fine-tune; native pooling dim otherwise).
    dim = resolve_out_dim(model)
    td = getattr(model, "truncate_dim", None)
    print(f"[worker {args.worker_rank}] dim={dim} "
          f"truncate_dim={td} pad_id={pad_id}", flush=True)

    meta_extra = {
        "task": args.task or None,
        "prompt_name": args.prompt_name or None,
        "query_prompt_name": args.query_prompt_name or None,
        "trust_remote_code": trust,
        "dtype": str(dtype).replace("torch.", ""),
    }
    stems = args.stems
    for i, stem in enumerate(stems, start=1):
        encode_one_shard(
            tokens_dir=tokens_dir, out_dir=out_dir, stem=stem, model=model,
            dim=dim, pad_id=pad_id, task=args.task, batch_size=args.batch_size,
            rank=args.worker_rank, log_every=args.log_every, shard_idx=i,
            n_shards=len(stems), total_shards=args.total_shards,
            step_start=args.step_start_epoch, meta=meta_extra,
            model_name=args.model, normalize=normalize,
            max_seq_len=args.max_seq_len)
    return 0


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--dtype", default="auto",
                    choices=["auto", "float32", "float16", "bfloat16"])
    ap.add_argument("--task", default="retrieval")
    ap.add_argument("--prompt-name", default="document")
    ap.add_argument("--query-prompt-name", default="query")
    ap.add_argument("--trust-remote-code", default="true")
    ap.add_argument("--normalize", default="true")
    ap.add_argument("--max-seq-len", type=int, default=1024)
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--log-every", type=int, default=20000)
    ap.add_argument("--force", action="store_true")
    # worker-only
    ap.add_argument("--worker-rank", type=int, default=-1)
    ap.add_argument("--total-shards", type=int, default=0)
    ap.add_argument("--step-start-epoch", type=float, default=0.0)
    ap.add_argument("--stems", nargs="*", default=[])
    return ap


def main() -> int:
    args = build_argparser().parse_args()
    if args.worker_rank >= 0:
        return run_worker(args)
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
