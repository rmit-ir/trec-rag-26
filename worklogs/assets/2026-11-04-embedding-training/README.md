---
license: cc-by-nc-4.0
base_model: jinaai/jina-embeddings-v5-text-nano
tags:
- sentence-transformers
- sentence-similarity
- feature-extraction
- dense-retrieval
- matryoshka
- eurobert
pipeline_tag: sentence-similarity
library_name: sentence-transformers
---

# jina-v5-nano-trecrag26-agent-256d

[`jinaai/jina-embeddings-v5-text-nano`](https://huggingface.co/jinaai/jina-embeddings-v5-text-nano)
(retrieval adapter merged into the EuroBERT-210M base), fine-tuned for
**256-dimensional** retrieval on relevance signal mined from agentic search
trajectories over the TREC RAG 2026 corpus (ClimbMix, chunked).

Output: **256-dim L2-normalized embeddings** (the repo's default
`truncate_dim`). Query prefix `"Query: "`, document prefix `"Document: "`,
last-token pooling. Standalone weights — no adapters, no remote code.

## How to use

### Option 1 — sentence-transformers (recommended)

```bash
pip install -U sentence-transformers
```

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("wshuai190/jina-v5-nano-trecrag26-agent-256d")
# truncate_dim=256 and the "Query: "/"Document: " prompts are built into the repo config.

queries = ["nursing diversity recruitment retention"]
docs = [
    "Title IX made a profound impact on American sports.",
    "The nursing school pipeline program supports underrepresented students.",
]

q_emb = model.encode_query(queries)        # applies "Query: " automatically
d_emb = model.encode_document(docs)        # applies "Document: " automatically
print(q_emb.shape)                         # (1, 256)
print(model.similarity(q_emb, d_emb))      # cosine similarities
```

### Option 2 — plain transformers

```python
import torch, torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

repo = "wshuai190/jina-v5-nano-trecrag26-agent-256d"
model = AutoModel.from_pretrained(repo)
tok = AutoTokenizer.from_pretrained(repo)

def encode(texts, prefix, dim=256):
    batch = tok([prefix + t for t in texts], return_tensors="pt",
                padding=True, truncation=True, max_length=1024)
    with torch.no_grad():
        hidden = model(**batch).last_hidden_state
    last = batch["attention_mask"].sum(1) - 1          # last non-pad token (EOS)
    pooled = hidden[torch.arange(hidden.shape[0]), last][:, :dim]
    return F.normalize(pooled, dim=-1)

q = encode(["nursing diversity recruitment retention"], "Query: ")
d = encode(["Title IX made a profound impact on American sports."], "Document: ")
print(q @ d.T)
```

Both options produce identical embeddings (verified to cosine 1.0).

**Important:** always use the `"Query: "` prefix for queries and `"Document: "`
for passages — the model was trained with them. Trained/evaluated at 256 dims
only; other Matryoshka dims of the base model are not guaranteed preserved.

## Training signal

An agentic research harness (`aus_agent`, RMIT-IR) answered all 119 TREC RAG
2026 test topics twice — once with a BM25 engine, once with a jina-v5 dense
engine. Every `search` sub-query's results were later explicitly judged by the
agent's context-commitment step (committed = relevant). Training pairs are
(sub-query → committed chunk): 1,587 sub-queries / 3,849 pairs from 95 topics;
24 topics held out for validation.

## Training setup

- Trainer: [tevatron](https://github.com/texttron/tevatron), patched to slice
  representations to `truncate_dim=256` **before** normalization — the InfoNCE
  loss sees only the first 256 dims (single Matryoshka target).
- LoRA (r=16, α=64, dropout 0.1, all attention+MLP projections), lr 1e-4,
  4 epochs, batch 64, in-batch negatives, temperature 0.05, bf16.
  Adapter merged into the base for this release.
- Compared against full fine-tuning and against query-formulation variants
  (narrative+subquery concatenation, mixed augmentation, mined hard negatives);
  this configuration won on held-out topics.

## Results (val = 24 held-out topics, 410 sub-queries, 256 dims)

Pool-ranking protocol over the 4,071 agent-committed chunks.

| model | nDCG@10 | MRR@10 | R@10 | R@20 |
|---|---|---|---|---|
| jina-v5-nano (merged retrieval, 256d) | 0.751 | 0.749 | 0.900 | 0.970 |
| **this model** | **0.793** | **0.796** | **0.946** | **0.989** |

On the BM25-arm queries (positives not self-selected by the dense model —
the unbiased subset): nDCG@10 0.604 → **0.752** (paired t-test p≈7e-22,
129 wins / 23 losses over 209 queries).

### Comparison with other embedding models (same protocol)

| model | params | dim | nDCG@10 | R@10 |
|---|---|---|---|---|
| **this model** | **239M** | **256** | **0.793** | **0.946** |
| jina-v5-text-nano (base) | 239M | 768 | 0.763 | 0.921 |
| jina-v5-text-small | ~600M | 1024 | 0.760 | 0.927 |
| jina-v5-text-nano (base) | 239M | 256 | 0.751 | 0.900 |
| jina-v5-text-small | ~600M | 256 | 0.722 | 0.888 |
| bge-large-en-v1.5 | 335M | 1024 | 0.697 | 0.873 |
| jina-embeddings-v3 | 570M | 1024 | 0.647 | 0.840 |

Domain fine-tuning at 256 dims outperforms larger models at their native
dimensions on this workload.

## Model architecture (sentence-transformers)

```
SentenceTransformer(
  (0): Transformer(EuroBertModel, max_seq_length=1024)
  (1): Pooling(768, pooling_mode='lasttoken')
  (2): Normalize()
)  # truncate_dim=256
```

## Framework versions

- sentence-transformers 5.6.1, transformers 5.14.1, torch 2.13.0, tevatron @ texttron/tevatron (patched)
