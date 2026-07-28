"""Fixtures shared by the per-system end-to-end tests.

The root ``tests/conftest.py`` owns everything generic (hermeticism, the
scripted provider, the search-tool stub). This file adds only what the
*systems* layer needs on top:

- ``stub_fetch_doc`` — the document-fetch half of retrieval. ``stub_search_tool``
  covers ``tools.search_tool``, but ``ali_deepresearch.tools.get_document`` goes
  straight to ``utils.fetch_doc.fetch_doc`` (a second, independent urllib
  client), so a hermetic ReAct run has to stub both.
- ``load_script`` — ``src/systems/claude-code-research/`` has a HYPHEN in its
  name, so it is not an importable package and its two scripts can only be
  reached by path. One loader, used by both script test modules, keeps the
  ``importlib`` boilerplate in a single place.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMS_DIR = REPO_ROOT / "src" / "systems"
CCR_SCRIPTS = SYSTEMS_DIR / "claude-code-research" / "scripts"


def load_script(path: Path, name: str) -> ModuleType:
    """Import a standalone script file under an explicit module name.

    Used for the modules that are not importable as packages: the
    hyphenated ``claude-code-research/scripts/*.py`` and
    ``o3_deep_research/run.py`` (a bare ``run.py``, which would collide with
    every other system's runner if imported by its own name).
    """
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the scripts do sys.path surgery at import time and
    # a partially-initialised module in sys.modules is what a real `python
    # script.py` run would also see.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stub_fetch_doc(monkeypatch: pytest.MonkeyPatch
                   ) -> dict[str, list[str]]:
    """Replace ``ali_deepresearch.tools.fetch_doc`` with an in-memory corpus.

    Patched at the *importing* module (``ali_deepresearch.tools`` did a
    ``from utils.fetch_doc import fetch_doc``, so patching ``utils.fetch_doc``
    would not be seen). Returns a ``calls`` dict recording the docids asked
    for, so a test can assert the agent opened the document it claimed to.
    """
    from ali_deepresearch import tools as ali_tools

    calls: dict[str, list[str]] = {"docids": []}

    def _fake(docid: str, **_kw: Any) -> dict[str, str]:
        calls["docids"].append(docid)
        if docid.startswith("missing"):
            raise RuntimeError("simulated 404 from the doc endpoint")
        return {"docid": docid,
                "text": (f"Full text of {docid}. Congestion pricing revenue is "
                         "dedicated to the capital plan, and traffic volumes "
                         "fell below the pre-toll baseline.")}

    monkeypatch.setattr(ali_tools, "fetch_doc", _fake)
    return calls


@pytest.fixture
def load_module() -> Callable[[Path, str], ModuleType]:
    """The ``load_script`` helper, as a fixture (for readability in tests)."""
    return load_script
