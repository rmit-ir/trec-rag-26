"""brief.py -- the pre-flight requirements-brief analyst (PLAN.md §3.1).

Phase 0 stub: ``get_requirements`` always returns an empty brief, so
``render_appendix`` always returns ``""`` and the fork's system prompt stays
byte-identical to aus_agent's own (plus the static review-pass Appendix B
already baked into ``prompts/system/default.md``). This is what PLAN.md §6
Phase 0's gate means by "the brief ... stubbed out": the wiring in
``agent.py`` is real, only the analyst's own logic is not built yet. The
real one-shot call and defensive JSON parsing land in Phase 1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Requirement:
    id: str
    requirement: str
    origin: str  # "explicit" | "implicit"
    why: str
    specific_form: str


def get_requirements(provider: Any, narrative: str) -> list[Requirement]:
    """Phase 0 stub -- always an empty brief; see module docstring."""
    return []


def render_appendix(requirements: list[Requirement]) -> str:
    """An empty brief renders to an empty appendix, so the system prompt is
    then exactly the loaded template."""
    return ""


__all__ = ["Requirement", "get_requirements", "render_appendix"]
