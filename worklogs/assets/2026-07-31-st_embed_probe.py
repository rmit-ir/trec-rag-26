import os
from pathlib import Path
REPO = Path("/mnt/raid10/e128356/projects/trec-rag-26")
for line in (REPO / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import numpy as np, torch
from sentence_transformers import SentenceTransformer

FT = "RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d"
m = SentenceTransformer(FT, device="cpu", trust_remote_code=True)
print("model.truncate_dim =", getattr(m, "truncate_dim", "MISSING"))
print("pooling config:", m[1].get_config_dict() if hasattr(m[1], "get_config_dict") else vars(m[1]))

texts = ["Photosynthesis converts light to energy.",
         "The Roman empire fell in 476 AD.",
         "Insulin regulates blood glucose levels."]

def full_pipeline(texts, prompt, task):
    tok = m[0].tokenizer
    enc = tok([prompt + t for t in texts], return_tensors="pt", padding=True,
              truncation=True, max_length=1024)
    feat = {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]}
    with torch.no_grad():
        for mod in m._modules.values():
            try:
                feat = mod(feat, task=task)
            except TypeError:
                feat = mod(feat)
    return feat["sentence_embedding"].float().numpy()

ref = m.encode(texts, prompt_name="document", task="retrieval",
               normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)
print("\nencode() shape:", ref.shape, "norms:", np.linalg.norm(ref, axis=1).round(4))

se768 = full_pipeline(texts, "Document: ", "retrieval")
print("pipeline shape:", se768.shape, "norms:", np.linalg.norm(se768, axis=1).round(4))

def cos_rows(a, b):
    return [float((a[i]*b[i]).sum()/(np.linalg.norm(a[i])*np.linalg.norm(b[i])+1e-9))
            for i in range(len(a))]

# candidate A: slice then renorm
A = se768[:, :256].copy()
A /= np.linalg.norm(A, axis=1, keepdims=True)
# candidate B: slice, no renorm
B = se768[:, :256].copy()
print("\ncos(encode, slice+renorm):", [round(c,6) for c in cos_rows(ref, A)])
print("cos(encode, slice norao ):", [round(c,6) for c in cos_rows(ref, B)])
print("max|encode - slice+renorm|:", float(np.abs(ref - A).max()))
