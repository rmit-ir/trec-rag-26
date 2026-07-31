"""Wiring for the `tasks/bm25_tune/` harness tests (PLAN §7.3).

The harness is a *task* (`tasks/bm25_tune/`), not a `src/` package, so it is not
on the root pytest `pythonpath`. This conftest puts it there for this directory
only — a localized `sys.path.insert` rather than a root `pyproject.toml` change,
which `--import-mode=importlib` makes safe.

**Why these tests need no dependency group, and must never acquire one.** Every
`bm25tune` module imported here is stdlib-only at import time: `pyserini` lives
inside `ChunkSearcher._open()` and `boto3` inside `BedrockJudge._client()` and
the `refresh-prices` body (PLAN §4.1). That is a deliberate architectural
constraint, not an accident — it means no `importorskip` is needed anywhere, so
`scripts/test.sh`, `.github/workflows/tests.yml`, and the pre-commit hook keep
their existing `DEP_GROUPS`, and the suite stays skip-free on a JVM-less CI
runner. If a future module breaks that rule, the fix is to move the import
inside a function, not to add a group here.

The root conftest's autouse fixtures apply and are exactly what we want:
`no_network` fails a test that reaches Bedrock, and `no_ambient_creds` strips AWS
vars so a "hermetic" test cannot pass only because the developer happened to be
logged in. `stub_search_tool` / `scripted_provider` belong to the `src/` layers
and are deliberately NOT reused — this task has its own seams.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "tasks" / "bm25_tune"
DATA_DIR = Path(__file__).resolve().parent / "data"

if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))


@pytest.fixture(scope="session")
def mini_labeled_path() -> Path:
    """The 6-row handcrafted stand-in for the 47 MB labeled search log.

    Mirrors the real schema exactly (PLAN §2.1) and packs one instance of every
    branch the extractor has to get right: two topics, a keyword/semantic mix, a
    duplicated (topic, query) pair at two different `k`s, a chunk retrieved by
    two of a topic's queries, a well-formed `prefix_chars > 0` header, the R4
    header outlier, and a voided (`unjudged`) hit.
    """
    path = DATA_DIR / "mini-labeled.jsonl"
    assert path.is_file(), f"missing fixture {path}"
    return path


@pytest.fixture
def bm25_config(tmp_path: Path,
                monkeypatch: pytest.MonkeyPatch,
                mini_labeled_path: Path) -> "object":
    """A `Config` pointed at a tmp data dir seeded with the mini input.

    Every CLI test runs against this rather than the real `data/bm25-tune/`, so a
    test can never overwrite the actual query set or judgment log — the same
    guarantee the root `isolated_data_dir` fixture gives the `src/` suite, applied
    to this task's own env var.
    """
    from bm25tune.config import Config

    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    target = inputs / mini_labeled_path.name
    target.write_bytes(mini_labeled_path.read_bytes())
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BM25_TUNE_INDEX_DIR", raising=False)
    return Config.from_env()


@pytest.fixture
def write_sha256sums() -> Callable[[Path], Path]:
    """Write a valid `SHA256SUMS` next to a file, returning the sums path.

    Lets a test build a *self-consistent* inputs dir, so a checksum failure in
    that test means the checking code is wrong rather than the fixture being
    stale.
    """
    def _write(target: Path) -> Path:
        from bm25tune.extract import sha256_file

        sums = target.parent / "SHA256SUMS"
        sums.write_text(f"{sha256_file(target)}  {target.name}\n")
        return sums

    return _write
