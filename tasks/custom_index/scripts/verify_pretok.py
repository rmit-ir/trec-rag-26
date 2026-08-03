"""Correctness gate for the pre-tokenized encode path.

Proves that encoding from pre-tokenized input_ids (Stage A format) produces
vectors identical (cosine ~= 1.0) to the reference `model.encode(...)` path we
already used to build the live index. If this does not pass, the pre-tokenized
run would produce vectors incompatible with the existing shards — so this is a
hard gate before we commit any GPU time.

Reference path  : model.encode([text], prompt_name="document", task="retrieval",
                                normalize_embeddings=True)
Pre-tokenized   : ids = tok("Document: " + text, max_length=L, truncation=True)
                  feats = {input_ids, attention_mask}   (ids padded to L)
                  emb = module.forward(feats, task="retrieval")["sentence_embedding"]

Run:
  uv run --project tasks/custom_index python tasks/custom_index/scripts/verify_pretok.py \
    --shard tasks/custom_index/work/climbmix-chunked/corpus/shard_01000.jsonl \
    --n 256 --max-seq-len 512
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import torch

from env_util import DEFAULT_MODEL, load_repo_env
from st_embed import embed_features

load_repo_env()  # HF_TOKEN for the private default model


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--shard", required=True)
    ap.add_argument("--n", type=int, default=256)
    ap.add_argument("--max-seq-len", type=int, default=512)
    ap.add_argument("--prompt", default="Document: ")
    ap.add_argument("--task", default="retrieval")
    ap.add_argument("--prompt-name", default="document")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    model = SentenceTransformer(
        args.model, trust_remote_code=True, device=device,
        model_kwargs={"dtype": dtype},
    )
    model.max_seq_length = args.max_seq_len
    module = model[0]
    tok = module.tokenizer

    texts = []
    with open(args.shard, "rt", encoding="utf-8") as f:
        for line in f:
            if len(texts) >= args.n:
                break
            texts.append(json.loads(line)["contents"])
    print(f"[verify] {len(texts)} chunks from {args.shard}")

    # --- reference path: exactly what built the live index ---
    ref = model.encode(
        texts, prompt_name=args.prompt_name, task=args.task,
        convert_to_numpy=True, normalize_embeddings=True,
        show_progress_bar=False, batch_size=32,
    ).astype(np.float32)

    # --- pre-tokenized path: Stage A tokenize -> pad -> Stage B forward ---
    L = args.max_seq_len
    enc = tok([args.prompt + t for t in texts], max_length=L, truncation=True,
              padding=False)
    ids_list = enc["input_ids"]
    pad_id = tok.pad_token_id or 0

    ids = np.full((len(ids_list), L), pad_id, dtype=np.int64)
    mask = np.zeros((len(ids_list), L), dtype=np.int64)
    lengths = np.zeros(len(ids_list), dtype=np.int32)
    for i, row in enumerate(ids_list):
        n = len(row)
        ids[i, :n] = row
        mask[i, :n] = 1
        lengths[i] = n

    mine = np.zeros_like(ref)
    bs = 32
    for s in range(0, len(texts), bs):
        feats = {
            "input_ids": torch.from_numpy(ids[s:s + bs]).to(device),
            "attention_mask": torch.from_numpy(mask[s:s + bs]).to(device),
        }
        # Same full-pipeline + truncate transform Stage B uses.
        out = embed_features(model, feats, task=args.task)
        mine[s:s + bs] = out.float().cpu().numpy()

    cos = (ref * mine).sum(axis=1) / (
        np.linalg.norm(ref, axis=1) * np.linalg.norm(mine, axis=1) + 1e-12)
    print(f"[verify] cosine  min={cos.min():.6f}  mean={cos.mean():.6f}  "
          f"p1={np.percentile(cos, 1):.6f}  max={cos.max():.6f}")
    print(f"[verify] token lengths  mean={lengths.mean():.1f}  "
          f"max={lengths.max()}  frac_at_{L}={(lengths >= L).mean():.2%}")
    ok = cos.min() >= 0.9999
    print(f"[verify] {'PASS' if ok else 'FAIL'} (gate: min cosine >= 0.9999)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
