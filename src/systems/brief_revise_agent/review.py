"""review.py -- brief_revise_agent's ``pre_final_hook`` (PLAN.md §3.3).

Phase 0 stub: ``hook`` always returns ``None``, so a run behaves
byte-identically to no hook at all -- PLAN.md §6 Phase 0's gate ("the ...
hook stubbed out"): the wiring in ``agent.py`` (a closure over the parsed
brief and a second provider, passed as ``pre_final_hook``) is real, only the
reviewer's own logic is not built yet. The deterministic uncited-sentence
scan, the evidence inventory read from ``ledger.call_history``, and the
grounded reviewer call land in Phase 2.
"""
from __future__ import annotations

from typing import Any

from .brief import Requirement


def hook(context: dict[str, Any], *,
        requirements: list[Requirement] = (),  # type: ignore[assignment]
        provider: Any = None) -> str | None:
    """Phase 0 stub -- always accepts the draft; see module docstring."""
    return None


__all__ = ["hook"]
