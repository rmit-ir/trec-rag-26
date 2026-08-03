"""Load selected keys from the repo-root ``.env`` into ``os.environ``.

The default embedding model is now a *private* HF repo
(``RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d``), so every stage that pulls
the model/tokenizer from the Hub needs an auth token. ``huggingface_hub`` reads
``HF_TOKEN`` from the environment automatically — this helper just makes sure it
is there, sourced from the repo ``.env`` (which is gitignored), without any
secret-handling on the shell command line.

Stdlib only (no python-dotenv dep). Idempotent and non-clobbering: a value
already present in ``os.environ`` always wins, so ``HF_TOKEN=... uv run ...``
still overrides the file. Child processes (encode workers, ProcessPool workers)
inherit ``os.environ``, so calling this once in the parent is enough.
"""
from __future__ import annotations

import os
from pathlib import Path

# Default embedding model for the whole custom-index pipeline. Fine-tuned from
# jina-embeddings-v5-text-nano (tokenizer byte-identical to the base, so the
# pre-tokenized store is reusable) and outputs 256-d natively (no matryoshka
# truncation needed). Private HF repo -> requires HF_TOKEN (see load_repo_env).
DEFAULT_MODEL = "RMIT-ADMS/jina-v5-nano-trecrag26-agent-256d"

# Keys we are willing to import from .env. Deliberately narrow so this never
# pulls unrelated secrets into a subprocess's environment.
_ALLOWED = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACEHUB_API_TOKEN")


def find_repo_env(start: Path | None = None) -> Path | None:
    """Nearest ``.env`` walking up from ``start`` (default: this file)."""
    here = (start or Path(__file__)).resolve()
    for parent in (here if here.is_dir() else here.parent, *here.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_repo_env(keys: tuple[str, ...] = _ALLOWED) -> list[str]:
    """Set allowed ``keys`` from the repo ``.env`` if not already in the env.

    Returns the list of key names that were newly set (for optional logging).
    Never prints values.
    """
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


if __name__ == "__main__":  # tiny self-check (prints names only, never values)
    got = load_repo_env()
    print(f"[env_util] .env: {find_repo_env()}  set: {got}  "
          f"HF_TOKEN present: {bool(os.environ.get('HF_TOKEN'))}")
