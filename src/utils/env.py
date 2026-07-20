"""Env-var-backed defaults for CLI arguments.

``env("RUN_AUS_AGENT_K", 10)`` lets a runner's argparse default be
overridden from the environment — including any ``.env`` picked up by
python-dotenv — without touching the CLI. Precedence: explicit flag > env var
> hardcoded default.

The cast applied to the env string is inferred from the default's type
(``bool``/``int``/``float``/``Path``, else ``str``); pass ``cast=`` explicitly
when the default is ``None`` but a non-string value is wanted.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

try:  # pull in the repo/cwd .env so env_default sees it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _to_bool(raw: str) -> bool:
    low = raw.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ValueError(f"not a boolean: {raw!r}")


def env(name: str, default: Any,
        cast: Callable[[str], Any] | None = None) -> Any:
    """Return ``$name`` (cast to the default's type) when set, else default."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    if cast is None:
        if isinstance(default, bool):  # before int: bool subclasses int
            cast = _to_bool
        elif isinstance(default, int):
            cast = int
        elif isinstance(default, float):
            cast = float
        elif isinstance(default, Path):
            cast = Path
        else:
            cast = str
    try:
        return cast(raw)
    except (TypeError, ValueError) as e:
        raise SystemExit(f"invalid value for env var {name}: {raw!r} ({e})")
