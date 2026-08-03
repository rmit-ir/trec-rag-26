#!/usr/bin/env python3
"""Probe ONE model: config (attn impl, params, layers, adapters, dtype) + a
timed forward on a fixed pretokenized batch, matching the encoder's path.
Run once per model (separate processes) to avoid jina custom-module reload bugs.
"""
import sys, time, os
sys.path.insert(0, "tasks/custom_index/scripts")
from env_util import load_repo_env
load_repo_env()
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from st_embed import embed_features, resolve_out_dim

model_id = sys.argv[1]
BATCH = 256
SEQ = 1024
dev = "cuda"
dtype = torch.bfloat16

m = SentenceTransformer(model_id, device=dev, trust_remote_code=True,
                        model_kwargs={"dtype": dtype})
m.max_seq_length = SEQ

print(f"\n===== {model_id} =====")
print(f"n ST modules: {len(m._modules)}  -> {[type(x).__name__ for x in m._modules.values()]}")
tr = m[0]
auto = getattr(tr, "auto_model", None)
print(f"module[0] class: {type(tr).__name__}")
if auto is not None:
    cfg = auto.config
    print(f"auto_model class: {type(auto).__name__}")
    print(f"attn_implementation: {getattr(cfg, '_attn_implementation', '?')}")
    print(f"num_hidden_layers: {getattr(cfg, 'num_hidden_layers', '?')}  "
          f"hidden_size: {getattr(cfg, 'hidden_size', '?')}")
    print(f"model_type: {getattr(cfg, 'model_type', '?')}")
    # PEFT / LoRA?
    print(f"has peft_config: {hasattr(auto, 'peft_config')}  "
          f"active_adapters: {getattr(auto, 'active_adapters', 'n/a')}")
    has_lora = any('lora' in n.lower() for n, _ in auto.named_modules())
    print(f"any LoRA submodule: {has_lora}")
tot = sum(p.numel() for p in m.parameters())
print(f"total params: {tot/1e6:.1f} M")
print(f"truncate_dim: {getattr(m, 'truncate_dim', None)}  out_dim: {resolve_out_dim(m)}")
p0 = next(m.parameters())
print(f"param dtype: {p0.dtype}")

# fixed batch: random valid token ids, full seq, all-ones mask (worst case)
rng = np.random.default_rng(0)
vocab = getattr(auto.config, "vocab_size", 128000) if auto is not None else 128000
bids = rng.integers(low=5, high=vocab-1, size=(BATCH, SEQ), dtype=np.int64)
bmask = np.ones((BATCH, SEQ), dtype=np.int64)
feats0 = {"input_ids": torch.from_numpy(bids).to(dev),
          "attention_mask": torch.from_numpy(bmask).to(dev)}

def one():
    with torch.no_grad():
        e = embed_features(m, dict(feats0), task="retrieval")
    torch.cuda.synchronize()
    return e

# warmup
for _ in range(3):
    e = one()
print(f"emb shape: {tuple(e.shape)} dtype: {e.dtype}")
N = 10
t0 = time.time()
for _ in range(N):
    one()
el = time.time() - t0
ch = BATCH * N
print(f"TIMING: {ch} seqs @ seq={SEQ} in {el:.3f}s -> {ch/el:.0f} ch/s/GPU (bf16, batch {BATCH})")
print(f"peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.1f} GB")
