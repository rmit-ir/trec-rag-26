"""Load selected keys from the repo-root ``.env`` into ``os.environ``.

The served index may be built with a *private* HF model (e.g. the fine-tuned
``RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d``); its query encoder pulls the
model from the Hub, which needs ``HF_TOKEN``. ``huggingface_hub`` reads that env
var automatically — this helper just sources it from the repo ``.env`` (which is
gitignored) so no secret ever touches the launch command line.

Stdlib only, idempotent, non-clobbering: a value already in ``os.environ`` wins.
Kept self-contained (not shared with tasks/custom_index) because each task is an
isolated env with no cross-task import path.
"""
from __future__ import annotations

import os
from pathlib import Path

_ALLOWED = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACEHUB_API_TOKEN")


def find_repo_env(start: Path | None = None) -> Path | None:
    here = (start or Path(__file__)).resolve()
    for parent in (here if here.is_dir() else here.parent, *here.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_repo_env(keys: tuple[str, ...] = _ALLOWED) -> list[str]:
    """Set allowed ``keys`` from the repo ``.env`` if absent. Returns names set
    (never values)."""
    env_path = find_repo_env()
    if env_path is None:
        return []
    loaded: list[str] = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k in keys and not os.environ.get(k):
            os.environ[k] = v.strip().strip('"').strip("'")
            loaded.append(k)
    return loaded
