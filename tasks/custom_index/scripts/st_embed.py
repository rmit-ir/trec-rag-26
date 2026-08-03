"""Reproduce ``SentenceTransformer.encode(...)`` from pre-tokenized features.

Why this exists: Stage B (encode_pretokenized.py) feeds pre-tokenized input_ids
straight into the model to skip re-tokenization. It therefore has to reproduce
what ``model.encode(text, ...)`` would have done, exactly, or the vectors won't
match the query side.

The fine-tuned default model (``jina-v5-nano-trecrag26-agent-256d``) is saved as
a *standard* Sentence-Transformers pipeline:

    [0] Transformer  -> token_embeddings (768-d)     (jina EuroBERT, task adapter)
    [1] Pooling      -> sentence_embedding (lasttoken, include_prompt)
    [2] Normalize    -> L2-normalized 768-d

plus a Matryoshka ``truncate_dim = 256`` that ``encode()`` applies *after* the
pipeline. So the vector ``encode(..., normalize_embeddings=True)`` returns is:

    features -> chain all modules -> sentence_embedding (native dim, unit norm)
             -> slice[:truncate_dim] -> L2-renormalize

Verified equal to ``model.encode(prompt_name="document", task="retrieval",
normalize_embeddings=True)`` to ~1e-7 on right-padded batches.

This also works for a single-module model whose module[0] already emits
``sentence_embedding`` (later modules pass it through), so it is a safe drop-in
replacement for the old hard-coded ``model[0].forward(...)["sentence_embedding"]``.
"""
from __future__ import annotations


def resolve_out_dim(model) -> int:
    """Final embedding dim after any Matryoshka truncation (what encode returns)."""
    td = getattr(model, "truncate_dim", None)
    if td:
        return int(td)
    d = model.get_sentence_embedding_dimension()
    if d:
        return int(d)
    import numpy as np  # last resort: probe
    v = model.encode("x", convert_to_numpy=True, show_progress_bar=False)
    return int(np.asarray(v).shape[-1])


def embed_features(model, feats: dict, task: str | None = None):
    """Run the full ST module pipeline on a features dict, returning an
    L2-normalized, ``truncate_dim``-truncated embedding tensor (B, out_dim).

    ``feats`` holds torch tensors ``input_ids`` / ``attention_mask`` already on
    (or movable to) the model device. ``task`` selects the model's task adapter
    (e.g. ``"retrieval"``); modules that don't accept it are called without it.
    """
    import torch

    feat = dict(feats)
    with torch.no_grad():
        for mod in model._modules.values():
            try:
                feat = mod(feat, task=task)
            except TypeError:
                feat = mod(feat)
        emb = feat["sentence_embedding"]
        td = getattr(model, "truncate_dim", None)
        if td and emb.shape[-1] > td:
            emb = torch.nn.functional.normalize(emb[:, :td], p=2, dim=1)
    return emb
