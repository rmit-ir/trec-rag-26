#!/usr/bin/env python3
"""Multi-GPU encoder for sharded ClimbMix corpus-jsonl files.

Parent mode: discovers shard jsonl files, splits them across N workers (one per
visible CUDA device by default), spawns each as its own subprocess with
CUDA_VISIBLE_DEVICES pinned, and watches global progress on the filesystem.

Worker mode (--worker-rank): loads the embedding model once and streams each
assigned shard, writing per-shard outputs:

  <stem>.fbin         DiskANN float vector binary (uint32 n, uint32 dim, n*dim float32)
  <stem>.docids.txt   one docid per line, parallel to rows in the fbin
  <stem>.meta.json    {model, dim, count, normalize, ...}

Doc-level embeddings (one vector per ClimbMix doc); chunking is a v1 follow-up.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Sibling helpers — formatting + on-disk progress reads.
from env_util import load_repo_env
from progress import (
    count_completed_shards,
    count_lines,
    global_progress_line,
    shard_finished_line,
    shard_progress_line,
)

# Private default model -> make HF_TOKEN available before any Hub download.
load_repo_env()


def parse_bool(s: str) -> bool:
    return str(s).lower() in ("1", "true", "yes", "y")


def resolve_dtype(arg: str, device: str):
    """Map a CLI --dtype value to a torch dtype, or None if no override."""
    import torch
    if arg == "auto":
        return torch.bfloat16 if device == "cuda" else torch.float32
    return {"float32": torch.float32,
            "float16": torch.float16,
            "bfloat16": torch.bfloat16}[arg]


# ---------------------------------------------------------------------------
# parent
# ---------------------------------------------------------------------------

def discover_shards(args) -> list[Path]:
    paths: list[Path] = []
    for s in args.shards or []:
        p = Path(s)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.jsonl")))
        else:
            paths.append(p)
    if args.shards_dir:
        paths.extend(sorted(Path(args.shards_dir).glob("*.jsonl")))
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return sorted(out, key=lambda x: x.name)


def detect_num_gpus() -> int:
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.device_count()
    except Exception:
        pass
    return 0


def split_round_robin(items: list, n: int) -> list[list]:
    buckets: list[list] = [[] for _ in range(n)]
    for i, x in enumerate(items):
        buckets[i % n].append(x)
    return buckets


def prewarm_model(model_name: str, trust_remote_code: bool) -> None:
    print(f"[parent] pre-warming HF cache for {model_name}", flush=True)
    from sentence_transformers import SentenceTransformer
    _ = SentenceTransformer(model_name, device="cpu", trust_remote_code=trust_remote_code)
    del _


def todo_shards(shards: list[Path], out_dir: Path, force: bool) -> list[Path]:
    todo: list[Path] = []
    for sh in shards:
        stem = sh.stem
        if (not force
                and (out_dir / f"{stem}.fbin").exists()
                and (out_dir / f"{stem}.docids.txt").exists()
                and (out_dir / f"{stem}.meta.json").exists()):
            print(f"[parent] skip {stem} (already encoded)", flush=True)
        else:
            todo.append(sh)
    return todo


def _common_worker_cmd(rank: int, n_gpus: int, args, out_dir: Path,
                       step_start: float, device: str) -> list[str]:
    return [
        sys.executable, __file__,
        "--worker-rank", str(rank),
        "--out-dir", str(out_dir),
        "--model", args.model,
        "--batch-size", str(args.batch_size),
        "--chunk-size", str(args.chunk_size),
        "--device", device,
        "--max-seq-len", str(args.max_seq_len),
        "--normalize", "true" if parse_bool(args.normalize) else "false",
        "--task", args.task,
        "--prompt-name", args.prompt_name,
        "--query-prompt-name", args.query_prompt_name,
        "--trust-remote-code", "true" if parse_bool(args.trust_remote_code) else "false",
        "--dtype", args.dtype,
        "--log-every", str(args.log_every),
        "--step-start-epoch", f"{step_start:.6f}",
    ]


def _resolve_worker_device(args, n_gpus: int) -> str:
    device = args.device
    if n_gpus == 0 and device in ("auto", "cuda"):
        device = "cpu"
    return device


def spawn_worker(rank: int, my_shards: list[Path], n_gpus: int, args,
                 out_dir: Path, total_shards: int, step_start: float) -> subprocess.Popen:
    env = os.environ.copy()
    if n_gpus > 0:
        env["CUDA_VISIBLE_DEVICES"] = str(rank)
    device = _resolve_worker_device(args, n_gpus)
    cmd = _common_worker_cmd(rank, n_gpus, args, out_dir, step_start, device)
    cmd += [
        "--total-shards", str(total_shards),
        "--shards", *[str(s) for s in my_shards],
    ]
    print(f"[parent] spawn worker rank={rank} CUDA_VISIBLE_DEVICES={env.get('CUDA_VISIBLE_DEVICES','')} "
          f"shards={[s.name for s in my_shards]}", flush=True)
    return subprocess.Popen(cmd, env=env)


def spawn_worker_watch(rank: int, n_workers: int, n_gpus: int, args,
                       out_dir: Path, corpus_dir: Path,
                       step_start: float) -> subprocess.Popen:
    env = os.environ.copy()
    if n_gpus > 0:
        env["CUDA_VISIBLE_DEVICES"] = str(rank)
    device = _resolve_worker_device(args, n_gpus)
    cmd = _common_worker_cmd(rank, n_gpus, args, out_dir, step_start, device)
    cmd += [
        "--watch",
        "--n-workers", str(n_workers),
        "--corpus-dir", str(corpus_dir),
        "--watch-poll-interval", str(args.watch_poll_interval),
    ]
    print(f"[parent] spawn watch worker rank={rank}/{n_workers} "
          f"CUDA_VISIBLE_DEVICES={env.get('CUDA_VISIBLE_DEVICES','')} "
          f"corpus_dir={corpus_dir}", flush=True)
    return subprocess.Popen(cmd, env=env)


def watch_progress(out_dir: Path, expected: set[str], step_start: float,
                   stop_evt: threading.Event) -> None:
    """Poll the filesystem every 5s for committed .fbin files and log diffs."""
    last_done = -1
    while not stop_evt.wait(5.0):
        done = sum(1 for s in expected if (out_dir / f"{s}.fbin").exists())
        if done != last_done:
            print(global_progress_line(done, len(expected), time.time() - step_start),
                  flush=True)
            last_done = done


def watch_progress_streaming(out_dir: Path, corpus_dir: Path, step_start: float,
                             stop_evt: threading.Event) -> None:
    """In watch mode the target count is unknown until prepare finishes, so we
    derive it from the live count of *.ready markers each tick."""
    last_done = -1
    last_total = -1
    while not stop_evt.wait(5.0):
        try:
            ready = list(corpus_dir.glob("*.jsonl.ready"))
            total = len(ready)
            done = sum(1 for r in ready
                       if (out_dir / f"{r.name[:-len('.jsonl.ready')]}.fbin").exists())
        except FileNotFoundError:
            continue
        if (done, total) != (last_done, last_total):
            print(global_progress_line(done, total, time.time() - step_start),
                  flush=True)
            last_done, last_total = done, total


def run_parent(args) -> int:
    shards = discover_shards(args)
    if not shards:
        print("[parent] no shard jsonl files found", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = todo_shards(shards, out_dir, args.force)
    if not todo:
        print("[parent] nothing to do", flush=True)
        return 0

    if args.num_workers < 0:
        print("[parent] --num-workers must be provided (>=0; 0 = auto)", file=sys.stderr)
        return 2
    n_gpus = detect_num_gpus()
    n_workers = args.num_workers if args.num_workers > 0 else (n_gpus or 1)
    if n_gpus > 0 and n_workers > n_gpus:
        print(f"[parent] clamping num_workers {n_workers} -> {n_gpus} (#cuda devices)", flush=True)
        n_workers = n_gpus
    n_workers = max(1, min(n_workers, len(todo)))
    print(f"[parent] cuda_devices={n_gpus} num_workers={n_workers} shards_todo={len(todo)}",
          flush=True)

    if not args.no_prewarm:
        prewarm_model(args.model, parse_bool(args.trust_remote_code))

    step_start = time.time()
    total_shards = len(todo)
    procs = [
        (rank, spawn_worker(rank, my_shards, n_gpus, args, out_dir, total_shards, step_start))
        for rank, my_shards in enumerate(split_round_robin(todo, n_workers))
        if my_shards
    ]

    expected = {s.stem for s in todo}
    stop_evt = threading.Event()
    watcher = threading.Thread(
        target=watch_progress, args=(out_dir, expected, step_start, stop_evt), daemon=True,
    )
    watcher.start()

    failed = []
    for rank, p in procs:
        rc = p.wait()
        print(f"[parent] worker rank={rank} exited rc={rc}", flush=True)
        if rc != 0:
            failed.append(rank)

    stop_evt.set()
    watcher.join(timeout=2.0)

    done = sum(1 for s in expected if (out_dir / f"{s}.fbin").exists())
    print(global_progress_line(done, len(expected), time.time() - step_start, tag="final"),
          flush=True)

    if failed:
        print(f"[parent] FAILED workers: {failed}", file=sys.stderr)
        return 1
    print(f"[parent] all {len(procs)} workers done", flush=True)
    return 0


def run_parent_watch(args) -> int:
    """Parent in watch mode: spawn N persistent workers that poll the corpus
    dir for new ready shards, then wait. Termination is signaled by prepare
    via .prepare_done / .prepare_fail in the corpus dir."""
    if not args.corpus_dir:
        print("[parent watch] --corpus-dir is required", file=sys.stderr)
        return 2
    corpus_dir = Path(args.corpus_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    if args.num_workers < 0:
        print("[parent watch] --num-workers must be provided (>=0; 0 = auto)", file=sys.stderr)
        return 2
    n_gpus = detect_num_gpus()
    n_workers = args.num_workers if args.num_workers > 0 else (n_gpus or 1)
    if n_gpus > 0 and n_workers > n_gpus:
        print(f"[parent watch] clamping num_workers {n_workers} -> {n_gpus} (#cuda devices)",
              flush=True)
        n_workers = n_gpus
    n_workers = max(1, n_workers)
    print(f"[parent watch] cuda_devices={n_gpus} num_workers={n_workers} "
          f"corpus_dir={corpus_dir} out_dir={out_dir}", flush=True)

    if not args.no_prewarm:
        prewarm_model(args.model, parse_bool(args.trust_remote_code))

    step_start = time.time()
    procs = [
        (rank, spawn_worker_watch(rank, n_workers, n_gpus, args, out_dir,
                                  corpus_dir, step_start))
        for rank in range(n_workers)
    ]

    stop_evt = threading.Event()
    watcher = threading.Thread(
        target=watch_progress_streaming,
        args=(out_dir, corpus_dir, step_start, stop_evt), daemon=True,
    )
    watcher.start()

    failed = []
    for rank, p in procs:
        rc = p.wait()
        print(f"[parent watch] worker rank={rank} exited rc={rc}", flush=True)
        if rc != 0:
            failed.append(rank)

    stop_evt.set()
    watcher.join(timeout=2.0)

    if failed:
        print(f"[parent watch] FAILED workers: {failed}", file=sys.stderr)
        return 1
    print(f"[parent watch] all {len(procs)} workers done", flush=True)
    return 0


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------

def detect_device(arg: str) -> str:
    if arg != "auto":
        return arg
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def stream_corpus(path: Path):
    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            yield rec["id"], rec["contents"]


def encode_one_shard(
    shard_path: Path,
    out_dir: Path,
    model,
    dim: int,
    normalize: bool,
    batch_size: int,
    chunk_size: int,
    max_seq_len: int,
    model_name: str,
    rank: int,
    log_every: int,
    shard_idx: int,
    shards_in_worker: int,
    total_shards_in_step: int,
    step_start_epoch: float,
    encode_kwargs: dict,
    meta_extra: dict,
) -> dict:
    """We accumulate ``chunk_size`` docs and hand them to ``model.encode()`` in
    one call (which internally splits to ``batch_size`` GPU mini-batches and
    length-sorts). Big chunks collapse Python-side per-call overhead from
    ``ceil(N/batch_size)`` to ``ceil(N/chunk_size)`` per shard."""
    import numpy as np

    stem = shard_path.stem
    tmp_fbin = out_dir / f"{stem}.fbin.tmp"
    tmp_docs = out_dir / f"{stem}.docids.txt.tmp"
    final_fbin = out_dir / f"{stem}.fbin"
    final_docs = out_dir / f"{stem}.docids.txt"
    meta_path = out_dir / f"{stem}.meta.json"

    total = count_lines(shard_path)
    print(f"[worker {rank}] START {shard_path.name} (worker shard {shard_idx}/{shards_in_worker}, "
          f"{total} docs, chunk_size={chunk_size}, batch_size={batch_size})",
          flush=True)

    t0 = time.time()
    vec_f = open(tmp_fbin, "wb")
    np.array([0, dim], dtype=np.uint32).tofile(vec_f)  # header placeholder
    docid_f = open(tmp_docs, "wt", encoding="utf-8")

    chunk_ids: list[str] = []
    chunk_texts: list[str] = []
    seen = 0
    last_log = 0

    def flush():
        nonlocal seen, last_log
        if not chunk_texts:
            return
        embs = model.encode(
            chunk_texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
            show_progress_bar=False,
            **encode_kwargs,
        ).astype(np.float32, copy=False)
        embs.tofile(vec_f)
        for d in chunk_ids:
            docid_f.write(d + "\n")
        seen += len(chunk_ids)
        chunk_ids.clear()
        chunk_texts.clear()
        if seen - last_log >= log_every:
            print(shard_progress_line(rank, shard_path.name, seen, total, time.time() - t0),
                  flush=True)
            last_log = seen

    for did, text in stream_corpus(shard_path):
        chunk_ids.append(did)
        chunk_texts.append(text)
        if len(chunk_texts) >= chunk_size:
            flush()
    flush()

    vec_f.seek(0)
    np.array([seen, dim], dtype=np.uint32).tofile(vec_f)
    vec_f.close()
    docid_f.close()
    os.replace(tmp_fbin, final_fbin)
    os.replace(tmp_docs, final_docs)

    elapsed = time.time() - t0
    meta = {
        "model": model_name,
        "dim": int(dim),
        "count": int(seen),
        "normalize": normalize,
        "max_seq_len": max_seq_len,
        "batch_size": batch_size,
        "shard": str(shard_path),
        "stem": stem,
        "rank": rank,
        "elapsed_seconds": round(elapsed, 2),
        "vectors_format": "diskann_fbin",
        **meta_extra,
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    step_done = count_completed_shards(out_dir)
    print(shard_finished_line(
        rank, shard_path.name, seen, total, elapsed,
        shard_idx, shards_in_worker,
        step_done, total_shards_in_step, time.time() - step_start_epoch,
    ), flush=True)
    return meta


def _load_worker_model(args):
    """Shared by fixed-list and watch worker modes. Returns
    (model, dim, normalize, encode_kwargs, meta_extra)."""
    from sentence_transformers import SentenceTransformer

    device = detect_device(args.device)
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    trust_remote_code = parse_bool(args.trust_remote_code)
    dtype = resolve_dtype(args.dtype, device)
    print(f"[worker {args.worker_rank}] device={device} dtype={dtype} "
          f"trust_remote_code={trust_remote_code} CUDA_VISIBLE_DEVICES={cvd}",
          flush=True)

    model = SentenceTransformer(
        args.model, device=device,
        trust_remote_code=trust_remote_code,
        model_kwargs={"dtype": dtype},
    )
    model.max_seq_length = args.max_seq_len
    normalize = parse_bool(args.normalize)

    encode_kwargs: dict = {}
    if args.task:
        encode_kwargs["task"] = args.task
    if args.prompt_name:
        encode_kwargs["prompt_name"] = args.prompt_name

    # Some custom-code models (e.g. Jina v5) don't populate
    # sentence_embedding_dimension. Probe by encoding a tiny input.
    dim = model.get_sentence_embedding_dimension()
    if dim is None:
        probe = model.encode("test", convert_to_numpy=True,
                             normalize_embeddings=normalize,
                             show_progress_bar=False, **encode_kwargs)
        dim = int(probe.shape[-1])
        print(f"[worker {args.worker_rank}] probed embedding dim = {dim}", flush=True)

    meta_extra = {
        "task": args.task or None,
        "prompt_name": args.prompt_name or None,
        "query_prompt_name": args.query_prompt_name or None,
        "trust_remote_code": trust_remote_code,
        "dtype": str(dtype).replace("torch.", ""),
    }
    return model, dim, normalize, encode_kwargs, meta_extra


def run_worker(args) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[worker {args.worker_rank}] shards={[Path(s).name for s in args.shards]}",
          flush=True)
    model, dim, normalize, encode_kwargs, meta_extra = _load_worker_model(args)

    n = len(args.shards)
    for i, sh in enumerate(args.shards, start=1):
        encode_one_shard(
            shard_path=Path(sh), out_dir=out_dir, model=model, dim=dim,
            normalize=normalize, batch_size=args.batch_size,
            chunk_size=args.chunk_size, max_seq_len=args.max_seq_len,
            model_name=args.model, rank=args.worker_rank,
            log_every=args.log_every, shard_idx=i, shards_in_worker=n,
            total_shards_in_step=args.total_shards,
            step_start_epoch=args.step_start_epoch,
            encode_kwargs=encode_kwargs, meta_extra=meta_extra,
        )
    return 0


def _ready_shards_for_rank(corpus_dir: Path, out_dir: Path,
                           n_workers: int, rank: int) -> list[Path]:
    """Returns [shard_*.jsonl, ...] that:
      - have a sibling shard_*.jsonl.ready marker (prepare finished them),
      - don't have a corresponding shard_*.fbin yet (not encoded),
      - belong to this worker by `sorted-index % n_workers == rank`.
    """
    ready = sorted(corpus_dir.glob("*.jsonl.ready"))
    mine: list[Path] = []
    for idx, ready_path in enumerate(ready):
        if idx % n_workers != rank:
            continue
        jsonl_path = ready_path.with_suffix("")  # strips .ready
        stem = jsonl_path.stem                   # strips .jsonl
        if (out_dir / f"{stem}.fbin").exists():
            continue
        mine.append(jsonl_path)
    return mine


def run_worker_watch(args) -> int:
    """Worker in watch mode: poll corpus_dir for ready shards belonging to my
    rank, process them one at a time, terminate when prepare signals done /
    fail and the queue is drained."""
    if not args.corpus_dir:
        print(f"[worker {args.worker_rank}] --corpus-dir is required in --watch",
              file=sys.stderr)
        return 2
    if args.n_workers <= 0:
        print(f"[worker {args.worker_rank}] --n-workers must be >0 in --watch",
              file=sys.stderr)
        return 2

    corpus_dir = Path(args.corpus_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    poll = max(1.0, float(args.watch_poll_interval))
    rank, n_workers = args.worker_rank, args.n_workers
    print(f"[worker {rank}] watch mode rank={rank}/{n_workers} corpus_dir={corpus_dir} "
          f"poll={poll:.1f}s", flush=True)

    model, dim, normalize, encode_kwargs, meta_extra = _load_worker_model(args)

    processed_in_worker = 0
    while True:
        mine = _ready_shards_for_rank(corpus_dir, out_dir, n_workers, rank)
        if mine:
            processed_in_worker += 1
            # total-in-step is unknown until prepare finishes; use the live
            # ready count as best-effort for the progress line.
            live_total = len(list(corpus_dir.glob("*.jsonl.ready")))
            encode_one_shard(
                shard_path=mine[0], out_dir=out_dir, model=model, dim=dim,
                normalize=normalize, batch_size=args.batch_size,
                chunk_size=args.chunk_size, max_seq_len=args.max_seq_len,
                model_name=args.model, rank=rank,
                log_every=args.log_every,
                shard_idx=processed_in_worker,
                shards_in_worker=0,           # unknown in watch mode
                total_shards_in_step=live_total,
                step_start_epoch=args.step_start_epoch,
                encode_kwargs=encode_kwargs, meta_extra=meta_extra,
            )
            continue

        # Nothing queued for me right now.
        if (corpus_dir / ".prepare_fail").exists():
            print(f"[worker {rank}] .prepare_fail observed; processed={processed_in_worker}; exit 1",
                  flush=True)
            return 1
        if (corpus_dir / ".prepare_done").exists():
            # Race-closer: re-glob once after seeing the sentinel.
            mine = _ready_shards_for_rank(corpus_dir, out_dir, n_workers, rank)
            if not mine:
                print(f"[worker {rank}] .prepare_done observed and queue drained; "
                      f"processed={processed_in_worker}; exit 0", flush=True)
                return 0
        time.sleep(poll)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", nargs="*", default=None,
                    help="shard jsonl files (or dirs, in parent mode)")
    ap.add_argument("--shards-dir", default=None,
                    help="directory of *.jsonl shard files (parent mode)")
    ap.add_argument("--out-dir", required=True)
    # Pipeline-owned knobs — required at parent level, no defaults here.
    ap.add_argument("--model", required=True)
    ap.add_argument("--batch-size", type=int, required=True)
    ap.add_argument("--device", required=True, choices=["auto", "cuda", "cpu", "mps"])
    # Only the parent uses --num-workers; workers re-parse argv but ignore it.
    # Sentinel -1 means "not provided"; run_parent validates explicitly.
    ap.add_argument("--num-workers", type=int, default=-1,
                    help="parent-mode only; 0 = auto (= #cuda devices, or 1)")
    # Encoder-internal knobs — defaults are fine here because nothing else sets them.
    ap.add_argument("--max-seq-len", type=int, default=512)
    ap.add_argument("--normalize", default="true")
    ap.add_argument("--chunk-size", type=int, default=256,
                    help="docs handed to model.encode() per call; ST then "
                         "length-sorts and splits into --batch-size GPU batches "
                         "internally. Big chunks reduce Python-side per-call overhead.")
    # Prompt / task mechanism (sentence-transformers >=3.x). Jina v5 uses
    # task="retrieval" with prompt_name="document" for passages and
    # prompt_name="query" at search time. Set --task "" to disable for models
    # that don't use it.
    ap.add_argument("--task", default="retrieval")
    ap.add_argument("--prompt-name", default="document")
    ap.add_argument("--query-prompt-name", default="query",
                    help="recorded in meta.json so search.py knows what to use")
    ap.add_argument("--trust-remote-code", default="true",
                    help="required for Jina v5 and other custom-code models")
    ap.add_argument("--dtype", default="auto",
                    choices=["auto", "float32", "float16", "bfloat16"],
                    help="auto picks bfloat16 on cuda, float32 elsewhere")
    ap.add_argument("--no-prewarm", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="re-encode shards even if outputs already exist")
    ap.add_argument("--log-every", type=int, default=2000)
    # Watch-mode args (parent + workers): overlap with the prepare step. The
    # encoder polls --corpus-dir for shard_*.jsonl.ready files and processes
    # them as they appear; prepare signals completion via .prepare_done and
    # failure via .prepare_fail in --corpus-dir.
    ap.add_argument("--watch", action="store_true",
                    help="watch corpus-dir for new ready shards (parent + worker)")
    ap.add_argument("--corpus-dir", default=None,
                    help="(watch mode) directory that prepare writes shard_*.jsonl + "
                         "shard_*.jsonl.ready / .prepare_done / .prepare_fail markers into")
    ap.add_argument("--watch-poll-interval", type=float, default=5.0,
                    help="(watch mode) seconds between filesystem polls in a worker")
    ap.add_argument("--n-workers", type=int, default=0,
                    help="(watch worker only) total worker count, for `idx %% n_workers == rank` slicing")
    # Internal worker-mode args.
    ap.add_argument("--worker-rank", type=int, default=-1,
                    help="internal: present means worker mode")
    ap.add_argument("--total-shards", type=int, default=0,
                    help="internal: total shards across the whole step")
    ap.add_argument("--step-start-epoch", type=float, default=0.0,
                    help="internal: parent's wall-clock start for step ETA")
    args = ap.parse_args()

    if args.worker_rank >= 0:
        if args.watch:
            return run_worker_watch(args)
        if not args.shards:
            print("[worker] no shards assigned", file=sys.stderr)
            return 2
        return run_worker(args)
    if args.watch:
        return run_parent_watch(args)
    return run_parent(args)


if __name__ == "__main__":
    sys.exit(main())
