"""Entry point for `python -m bm25tune` (PLAN §5.6's canonical invocation).

A separate file rather than a `__main__` guard in `cli.py` so `cli` can be
imported by tests without argparse ever seeing pytest's argv.
"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
