"""Stage A: pre-tokenize the chunked corpus to a reusable on-disk token store.

Motivation: the GPU encode is bottlenecked on single-threaded tokenization
(jina v5's custom EuroBERT path), leaving the GPUs ~30% idle. This stage does
all tokenization up front across every CPU core, writing token IDs to disk, so
the encode stage (Stage B) becomes GPU-bound and can use large batches. The
token store is ALSO the input for later embedding-model fine-tuning, so the
one-time cost is amortized across both uses.

Exactness: reproduces jina's own preprocessing bit-for-bit (verified by
`verify_pretok.py`, cosine == 1.0):
    text  = PROMPT + contents            # PROMPT defaults to "Document: "
    ids   = tokenizer(text, max_length=L, truncation=True)   # L default 1024

Storage is RAGGED (variable-length, no padding): with a generous cap (1024)
almost no chunk clips, but the mean chunk is only ~486 tokens, so fixed-width
[N, L] padding would nearly double the store for nothing. Ragged costs
sum(real lengths) regardless of L, so the cap is effectively free. Per-batch
dynamic padding at encode time is reconstructed from the lengths array; the
encoder's last-token pooling makes padding amount irrelevant to the vector.

Per-shard outputs (in --out-dir), atomic + resumable:
    shard_NNNNN.ids.u32     raw int32, all chunks' ids concatenated (sum(len))
    shard_NNNNN.len.i16     raw int16, [N]  (per-chunk token length; L<=32767)
    shard_NNNNN.docids.txt  one chunk id per line, same order as rows
    shard_NNNNN.meta.json   {n, seq_len, total_tokens, pad_id, prompt, ...}
    shard_NNNNN.ready       zero-byte marker (all four above are complete)

Load a shard (ragged) for encode/finetune with:
    ids  = np.memmap(f"{stem}.ids.u32", dtype=np.int32, mode="r")
    lens = np.fromfile(f"{stem}.len.i16", dtype=np.int16).astype(np.int64)
    off  = np.concatenate([[0], np.cumsum(lens)])   # chunk k = ids[off[k]:off[k+1]]

Run (all cores, one pass):
    uv run --project tasks/custom_index python \
      tasks/custom_index/scripts/tokenize_corpus.py \
      --corpus-dir tasks/custom_index/work/climbmix-chunked/corpus \
      --out-dir    tasks/custom_index/work/climbmix-chunked/tokens \
      --model jinaai/jina-embeddings-v5-text-nano \
      --max-seq-len 1024 --workers 96
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from env_util import DEFAULT_MODEL, load_repo_env

# Private default model -> tokenizer download needs HF_TOKEN (from repo .env).
load_repo_env()

# One tokenizer per worker process, lazily built.
_TOK = None
_TOK_MODEL = None


def _get_tokenizer(model: str):
    global _TOK, _TOK_MODEL
    if _TOK is None or _TOK_MODEL != model:
        from transformers import AutoTokenizer
        # Keep tokenization single-threaded per process; parallelism is across
        # processes, so Rust-side threads would only oversubscribe the box.
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        _TOK = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
        _TOK_MODEL = model
    return _TOK


def _iter_shard(path: Path):
    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            yield rec["id"], rec["contents"]


def tokenize_shard(shard_path: str, out_dir: str, model: str, seq_len: int,
                   prompt: str, sub_batch: int) -> dict:
    shard_path = Path(shard_path)
    out_dir = Path(out_dir)
    stem = shard_path.stem  # shard_NNNNN
    ready = out_dir / f"{stem}.ready"
    if ready.exists():
        return {"stem": stem, "skipped": True}

    tok = _get_tokenizer(model)
    pad_id = tok.pad_token_id
    if pad_id is None:
        pad_id = 0

    ids_parts: list[np.ndarray] = []   # ragged: each chunk's ids, concatenated
    lengths: list[int] = []
    docids: list[str] = []

    buf_ids: list[str] = []
    buf_txt: list[str] = []

    def flush():
        if not buf_txt:
            return
        enc = tok(buf_txt, max_length=seq_len, truncation=True, padding=False)
        for row in enc["input_ids"]:
            ids_parts.append(np.asarray(row, dtype=np.int32))
            lengths.append(len(row))
        docids.extend(buf_ids)
        buf_ids.clear()
        buf_txt.clear()

    for did, text in _iter_shard(shard_path):
        buf_ids.append(did)
        buf_txt.append(prompt + text)
        if len(buf_txt) >= sub_batch:
            flush()
    flush()

    n = len(lengths)
    ids_arr = (np.concatenate(ids_parts) if n else np.empty(0, np.int32))
    len_arr = np.asarray(lengths, dtype=np.int16)

    tmp_ids = out_dir / f"{stem}.ids.u32.tmp"
    tmp_len = out_dir / f"{stem}.len.i16.tmp"
    tmp_doc = out_dir / f"{stem}.docids.txt.tmp"
    ids_arr.tofile(tmp_ids)
    len_arr.tofile(tmp_len)
    tmp_doc.write_text("".join(d + "\n" for d in docids), encoding="utf-8")

    meta = {
        "stem": stem, "n": int(n), "seq_len": int(seq_len),
        "pad_id": int(pad_id), "prompt": prompt, "model": model,
        "layout": "ragged", "dtype_ids": "int32", "dtype_len": "int16",
        "total_tokens": int(ids_arr.size),
        "truncated_at_seq_len": int((len_arr >= seq_len).sum()),
        "mean_len": float(len_arr.mean()) if n else 0.0,
        "shard": str(shard_path),
    }
    (out_dir / f"{stem}.meta.json").write_text(json.dumps(meta, indent=2))
    os.replace(tmp_ids, out_dir / f"{stem}.ids.u32")
    os.replace(tmp_len, out_dir / f"{stem}.len.i16")
    os.replace(tmp_doc, out_dir / f"{stem}.docids.txt")
    ready.touch()
    return {"stem": stem, "skipped": False, "n": n,
            "trunc": int((len_arr >= seq_len).sum())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-seq-len", type=int, default=1024)
    ap.add_argument("--prompt", default="Document: ")
    ap.add_argument("--workers", type=int, default=96)
    ap.add_argument("--sub-batch", type=int, default=2048)
    ap.add_argument("--log-every", type=int, default=50)
    args = ap.parse_args()

    corpus_dir = Path(args.corpus_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shards = sorted(str(p) for p in corpus_dir.glob("*.jsonl"))
    if not shards:
        print(f"[tokenize] no *.jsonl in {corpus_dir}", flush=True)
        return 1
    print(f"[tokenize] {len(shards)} shards -> {out_dir} "
          f"(seq_len={args.max_seq_len}, prompt={args.prompt!r}, "
          f"workers={args.workers})", flush=True)

    t0 = time.time()
    done = skipped = tot_n = tot_trunc = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(tokenize_shard, s, str(out_dir), args.model,
                          args.max_seq_len, args.prompt, args.sub_batch)
                for s in shards]
        for fut in as_completed(futs):
            r = fut.result()
            done += 1
            if r.get("skipped"):
                skipped += 1
            else:
                tot_n += r.get("n", 0)
                tot_trunc += r.get("trunc", 0)
            if done % args.log_every == 0 or done == len(shards):
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(shards) - done) / rate / 3600 if rate else 0
                tr = (tot_trunc / tot_n * 100) if tot_n else 0
                print(f"[tokenize] {done}/{len(shards)} shards "
                      f"({skipped} skipped) chunks={tot_n:,} "
                      f"truncated={tr:.1f}% eta={eta:.2f}h", flush=True)

    (out_dir / ".tokenize_done").touch()
    print(f"[tokenize] DONE {done} shards in {(time.time()-t0)/3600:.2f}h "
          f"chunks={tot_n:,} truncated={(tot_trunc/tot_n*100 if tot_n else 0):.1f}%",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
