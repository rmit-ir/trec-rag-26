"""Wiring for the `gen_arch_viz.py` generator tests (issue #20).

The generator lives under `skills/trec-rag-new-system/scripts/`, not `src/`,
so it is not on the root pytest `pythonpath`. This conftest puts it there for
this directory only, mirroring `tests/bm25_tune/conftest.py`'s pattern for a
non-`src/` task script.

**Why these tests need no dependency group.** `gen_arch_viz` is stdlib-only
(`ast`, `json`, `pathlib`, `webbrowser`, `argparse`) by design (its own module
docstring: "pure ``ast`` parsing, so no env/network side effects"), so no
`importorskip` is needed and `scripts/test.sh` / CI / the pre-commit hook keep
their existing `DEP_GROUPS` unchanged. The root conftest's `no_network`
autouse fixture applies for free -- these tests only ever read files under
`src/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "skills" / "trec-rag-new-system" / "scripts"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
