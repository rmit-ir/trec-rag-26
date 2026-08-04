"""Facet planning — narrative -> list of research facets.

Unlike the old plan-then-execute architecture, a facet no longer pins an
engine/query/k up front: the orchestrator decides retrieval strategy live,
per facet, during its search loop (see ``loop.py``). Planning only decides
WHAT needs investigating and roughly how hard it looks (``max_iterations``).

Parsing is defensive: an LLM that strays from the schema or omits
``max_iterations`` is repaired rather than rejected, and a completely
unusable response falls back to a single facet over the raw narrative so a
run always retrieves something.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .prompts import PLAN_PROMPT

DEFAULT_MIN_FACETS = 3
DEFAULT_MAX_FACETS = 6
DEFAULT_MAX_ITERATIONS = 4
# Hard ceiling regardless of what the planner returns (spec requirement).
GLOBAL_ITERATION_CAP = 10


@dataclass
class Facet:
    name: str
    description: str
    max_iterations: int = DEFAULT_MAX_ITERATIONS


def build_plan_prompt(narrative: str, *,
                      min_facets: int = DEFAULT_MIN_FACETS,
                      max_facets: int = DEFAULT_MAX_FACETS) -> str:
    """Render ``PLAN_PROMPT`` with the requested facet-count band."""
    return PLAN_PROMPT.format(
        min_facets=min_facets, max_facets=max_facets, narrative=narrative)


def _strip_fences(raw: str) -> str:
    """Drop ```json ... ``` fences a model may add despite instructions."""
    raw = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL)
    return fence.group(1).strip() if fence else raw


def parse_facets(raw: str) -> list[Facet]:
    """Parse the planner JSON into validated facets.

    ``max_iterations`` is clamped to ``[1, GLOBAL_ITERATION_CAP]``; facets
    with an empty description are dropped.
    """
    try:
        payload = json.loads(_strip_fences(raw))
        rows = payload.get("facets") if isinstance(payload, dict) else None
    except (json.JSONDecodeError, AttributeError):
        rows = None
    if not isinstance(rows, list):
        return []

    facets: list[Facet] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        description = str(row.get("description", "")).strip()
        if not description:
            continue
        try:
            max_iterations = int(row.get("max_iterations", DEFAULT_MAX_ITERATIONS))
        except (TypeError, ValueError):
            max_iterations = DEFAULT_MAX_ITERATIONS
        max_iterations = max(1, min(GLOBAL_ITERATION_CAP, max_iterations))
        name = str(row.get("name", "")).strip() or description[:40]
        facets.append(Facet(name=name, description=description,
                            max_iterations=max_iterations))
    return facets


def fallback_facets(narrative: str) -> list[Facet]:
    """A single facet over the raw narrative — used when planning is unusable."""
    return [Facet(name="whole narrative", description=narrative.strip(),
                  max_iterations=GLOBAL_ITERATION_CAP)]
