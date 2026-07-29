"""Facet planning — narrative -> list of engine-pinned search facets.

The plan prompt is assembled here so the engine "when to use" blurbs and the
query-writing guidance come straight from ``tools.search_tool`` (the same
single source the interactive agents use). Parsing is defensive: an LLM that
strays from the schema, picks a disabled engine, or omits ``k`` is repaired
rather than rejected, and a completely unusable response falls back to a
single semantic facet over the raw narrative so a run always retrieves
something.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from tools.search_tool import ENGINE_INFO, _query_guidance

from .prompts import PLAN_PROMPT

DEFAULT_MIN_FACETS = 3
DEFAULT_MAX_FACETS = 6
DEFAULT_K = 10
MIN_K = 1
MAX_K = 20


@dataclass
class Facet:
    name: str
    engine: str
    query: str
    k: int = DEFAULT_K


def _engine_blurbs(engines: list[str]) -> str:
    """One ``- name: blurb`` line per enabled engine (from ENGINE_INFO)."""
    return "\n".join(f"- {e}: {ENGINE_INFO[e]['blurb']}" for e in engines)


def build_plan_prompt(narrative: str, engines: list[str], *,
                      min_facets: int = DEFAULT_MIN_FACETS,
                      max_facets: int = DEFAULT_MAX_FACETS) -> str:
    """Render PLAN_PROMPT with the enabled engines' blurbs + query guidance."""
    return PLAN_PROMPT.format(
        min_facets=min_facets,
        max_facets=max_facets,
        engine_blurbs=_engine_blurbs(engines),
        query_guidance=_query_guidance(engines),
        narrative=narrative,
    )


def _strip_fences(raw: str) -> str:
    """Drop ```json ... ``` fences a model may add despite instructions."""
    raw = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL)
    return fence.group(1).strip() if fence else raw


def parse_facets(raw: str, engines: list[str], *,
                 default_engine: str) -> list[Facet]:
    """Parse the planner JSON into validated facets.

    A facet whose engine is not enabled is coerced to ``default_engine``; ``k``
    is clamped to ``[MIN_K, MAX_K]``; facets with an empty query are dropped.
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
        query = str(row.get("query", "")).strip()
        if not query:
            continue
        engine = str(row.get("engine", "")).strip()
        if engine not in engines:
            engine = default_engine
        try:
            k = int(row.get("k", DEFAULT_K))
        except (TypeError, ValueError):
            k = DEFAULT_K
        k = max(MIN_K, min(MAX_K, k))
        name = str(row.get("name", "")).strip() or query[:40]
        facets.append(Facet(name=name, engine=engine, query=query, k=k))
    return facets


def fallback_facets(narrative: str, *, default_engine: str) -> list[Facet]:
    """A single facet over the raw narrative — used when planning is unusable."""
    return [Facet(name="whole narrative", engine=default_engine,
                  query=narrative.strip(), k=DEFAULT_K)]
