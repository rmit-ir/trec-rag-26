"""Query-encoder abstraction.

The engine talks to a ``QueryEncoder`` protocol so different deployments can
swap in different inference backends without touching SearchEngine. The only
implementation today is ``SentenceTransformerEncoder`` (CPU or CUDA). A
future ONNX/AMX backend just needs to register in ``_ENCODER_REGISTRY``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from errors import EngineLoadError
from server_info import cpu_flags


@dataclass
class EncoderConfig:
    """Knobs applied to whichever backend is selected."""
    kind: str = "sentence_transformer"     # extension point: "onnx_amx", "tensorrt", ...
    device: str = "auto"                   # "auto" | "cpu" | "cuda" | "cuda:0" ...
    dtype: str = "auto"                    # "auto" | "float32" | "float16" | "bfloat16"


@runtime_checkable
class QueryEncoder(Protocol):
    """Encode query strings into a 2D float32 ndarray (n, dim)."""

    dim: int

    def encode(self, queries: list[str]):
        ...


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _resolve_dtype(arg: str, device: str):
    """Default 'auto' picks bf16 when the hardware advertises it (CUDA, or
    CPUs with amx_bf16 / avx512_bf16). Otherwise float32."""
    import torch
    if arg != "auto":
        return {"float32": torch.float32, "float16": torch.float16,
                "bfloat16": torch.bfloat16}[arg]
    if device.startswith("cuda"):
        return torch.bfloat16
    flags = cpu_flags()
    if "amx_bf16" in flags or "avx512_bf16" in flags:
        return torch.bfloat16
    return torch.float32


class SentenceTransformerEncoder:
    """sentence-transformers backed encoder (CPU or CUDA)."""

    def __init__(self, model_name: str, encoding_meta: dict, cfg: EncoderConfig):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.device = _resolve_device(cfg.device)
        self.dtype = _resolve_dtype(cfg.dtype, self.device)
        self.dim = int(encoding_meta["dim"])
        self.normalize = bool(encoding_meta.get("normalize", True))
        trust = bool(encoding_meta.get("trust_remote_code", False))
        print(f"[encoder] sentence-transformers: model={model_name} "
              f"device={self.device} dtype={self.dtype} trust_remote_code={trust}",
              flush=True)
        self._model = SentenceTransformer(
            model_name, device=self.device, trust_remote_code=trust,
            model_kwargs={"dtype": self.dtype},
        )
        self._kwargs: dict = {}
        if encoding_meta.get("task"):
            self._kwargs["task"] = encoding_meta["task"]
        if encoding_meta.get("query_prompt_name"):
            self._kwargs["prompt_name"] = encoding_meta["query_prompt_name"]

    def encode(self, queries: list[str]):
        import numpy as np
        v = self._model.encode(
            queries, convert_to_numpy=True, show_progress_bar=False,
            normalize_embeddings=self.normalize, **self._kwargs,
        )
        return v.astype(np.float32, copy=False)


_ENCODER_REGISTRY: dict[str, type] = {
    "sentence_transformer": SentenceTransformerEncoder,
}


def build_encoder(encoding_meta: dict, cfg: EncoderConfig) -> QueryEncoder:
    impl = _ENCODER_REGISTRY.get(cfg.kind)
    if impl is None:
        raise EngineLoadError(
            f"unknown encoder kind {cfg.kind!r}. Available: {sorted(_ENCODER_REGISTRY)}"
        )
    return impl(encoding_meta["model"], encoding_meta, cfg)
