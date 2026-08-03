#!/usr/bin/env python3
"""Time the BASE jina custom single-module model with task set at load, and
dig out its attention implementation + adapter structure."""
import sys, time
sys.path.insert(0, "tasks/custom_index/scripts")
from env_util import load_repo_env
load_repo_env()
import numpy as np, torch
from sentence_transformers import SentenceTransformer

BATCH, SEQ, dev, dtype = 256, 1024, "cuda", torch.bfloat16
m = SentenceTransformer("jinaai/jina-embeddings-v5-text-nano", device=dev,
                        trust_remote_code=True,
                        model_kwargs={"dtype": dtype, "default_task": "retrieval"})
m.max_seq_length = SEQ
tr = m[0]
print(f"module[0] class: {type(tr).__name__}")
print(f"module[0] attrs w/ 'model'/'transformer': "
      f"{[a for a in dir(tr) if ('model' in a.lower() or 'transformer' in a.lower()) and not a.startswith('__')]}")

# hunt for the underlying HF model + its config._attn_implementation
def find_attn(obj, depth=0, seen=None):
    seen = seen or set()
    if id(obj) in seen or depth > 4: return
    seen.add(id(obj))
    cfg = getattr(obj, "config", None)
    if cfg is not None and hasattr(cfg, "_attn_implementation"):
        print(f"  [{type(obj).__name__}] attn={cfg._attn_implementation} "
              f"layers={getattr(cfg,'num_hidden_layers','?')} "
              f"model_type={getattr(cfg,'model_type','?')}")
    for name in ("auto_model", "model", "transformer", "bert", "encoder", "_model"):
        sub = getattr(obj, name, None)
        if sub is not None and hasattr(sub, "__class__"):
            find_attn(sub, depth+1, seen)
find_attn(tr)

# LoRA / adapters?
loras = [n for n, _ in m.named_modules() if 'lora' in n.lower()]
print(f"LoRA submodules: {len(loras)}  e.g. {loras[:3]}")
adapters = set()
for n, _ in m.named_parameters():
    if 'lora' in n.lower() or 'adapter' in n.lower():
        adapters.add(n.split('.lora')[0].split('.adapter')[0][-40:])
print(f"adapter-bearing param groups: {len(adapters)}")
print(f"total params: {sum(p.numel() for p in m.parameters())/1e6:.1f} M")

rng = np.random.default_rng(0)
bids = rng.integers(5, 128000, size=(BATCH, SEQ), dtype=np.int64)
bmask = np.ones((BATCH, SEQ), dtype=np.int64)
feats0 = {"input_ids": torch.from_numpy(bids).to(dev),
          "attention_mask": torch.from_numpy(bmask).to(dev)}

def one():
    with torch.no_grad():
        out = m[0]({**feats0}, task="retrieval")
        e = out["sentence_embedding"] if "sentence_embedding" in out else out["token_embeddings"]
    torch.cuda.synchronize(); return e

for _ in range(3): e = one()
print(f"emb shape: {tuple(e.shape)}")
N=10; t0=time.time()
for _ in range(N): one()
el=time.time()-t0
print(f"TIMING base: {BATCH*N} seqs @ seq={SEQ} in {el:.3f}s -> {BATCH*N/el:.0f} ch/s/GPU")
print(f"peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.1f} GB")
