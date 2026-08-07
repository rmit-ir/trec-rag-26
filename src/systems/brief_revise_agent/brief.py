"""brief.py -- the pre-flight requirements-brief analyst (PLAN.md §3.1).

One tool-less LLM call before ``run_agent`` starts (``facet_rag.llm.one_shot``,
the same helper facet_rag's planner/curator use), producing a short checklist
of what a complete answer must do -- explicit obligations the request states,
and implicit ones a careful reader would infer. PLAN.md §1(b): this targets
`aus_agent`'s largest measured deficit (Implicit Criteria, 71% graded <=1),
not a `facets_agent`-style decomposition rewrite.

Parsing mirrors ``facet_rag.planner``'s defensive style exactly: a response
that strays from the schema, cites nothing, or fails to parse at all is
repaired or dropped entry-by-entry, never raised -- ``get_requirements`` can
never block a run. An empty/failed brief degrades the run to plain
`aus_agent` behaviour (no appendix), which is the correct fallback, not a
bug: PLAN.md §1's whole case for this step is additive evidence, and a
run must never depend on it succeeding.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from facet_rag.llm import one_shot, strip_fences

from .prompts import APPENDIX_TEMPLATE, BRIEF_PROMPT, ENTRY_TEMPLATE

log = logging.getLogger(__name__)

MAX_ENTRIES = 8
MAX_IMPLICIT = 4
_MIN_WORD_LEN = 4  # words shorter than this are too generic to count as overlap
_MIN_OVERLAP = 2   # word-overlap fallback when `why` carries no quote marks
_QUOTE_RE = re.compile(r'["‘’“”]([^"‘’“”]{3,})'
                       r'["‘’“”]')
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class Requirement:
    id: str
    requirement: str
    origin: str  # "explicit" | "implicit"
    why: str
    specific_form: str


def build_brief_prompt(narrative: str) -> str:
    """Render ``BRIEF_PROMPT`` with the request narrative."""
    return BRIEF_PROMPT.format(narrative=narrative)


def _why_quotes_narrative(why: str, narrative: str) -> bool:
    """The anti-hunch check (PLAN.md §3.1): an implicit entry's `why` must be
    traceable to the request's own wording, not just a plausible-sounding
    justification the model invented. A quoted snippet that actually appears
    in the narrative is the strongest signal; failing that, require at least
    two non-trivial words shared with the narrative so a model that named the
    phrase without quote marks is not punished for formatting alone.
    """
    narrative_lower = narrative.lower()
    quotes = _QUOTE_RE.findall(why)
    if quotes:
        return any(q.strip().lower() in narrative_lower for q in quotes)
    words = [w for w in _WORD_RE.findall(why.lower()) if len(w) >= _MIN_WORD_LEN]
    if not words:
        return False
    narrative_words = set(_WORD_RE.findall(narrative_lower))
    return sum(1 for w in words if w in narrative_words) >= _MIN_OVERLAP


def parse_brief(raw: str, narrative: str) -> list[Requirement]:
    """Parse the analyst's JSON into validated requirements.

    Caps at ``MAX_ENTRIES`` total / ``MAX_IMPLICIT`` implicit (PLAN.md §3.1:
    "an analyst that invents obligations is worse than none"); every implicit
    entry must pass ``_why_quotes_narrative``; every entry needs a non-empty
    ``specific_form`` (the anti-`covered_but_shallow` field). Anything
    malformed is dropped rather than raised.
    """
    try:
        payload = json.loads(strip_fences(raw)) if raw else None
        rows = payload.get("requirements") if isinstance(payload, dict) else None
    except (json.JSONDecodeError, AttributeError, TypeError):
        rows = None
    if not isinstance(rows, list):
        return []

    requirements: list[Requirement] = []
    implicit_count = 0
    for row in rows:
        if len(requirements) >= MAX_ENTRIES:
            break
        if not isinstance(row, dict):
            continue
        requirement = str(row.get("requirement", "")).strip()
        specific_form = str(row.get("specific_form", "")).strip()
        origin = str(row.get("origin", "")).strip().lower()
        why = str(row.get("why", "")).strip()
        if not requirement or not specific_form or origin not in (
                "explicit", "implicit"):
            continue
        if origin == "implicit":
            if implicit_count >= MAX_IMPLICIT:
                continue
            if not why or not _why_quotes_narrative(why, narrative):
                continue
            implicit_count += 1
        req_id = str(row.get("id", "")).strip() or f"R{len(requirements) + 1}"
        requirements.append(Requirement(
            id=req_id, requirement=requirement, origin=origin, why=why,
            specific_form=specific_form))
    return requirements


def get_requirements(provider: Any, narrative: str) -> list[Requirement]:
    """Run the one-shot brief call and parse it defensively.

    Never raises: a provider error, an empty response, or unusable JSON all
    fall back to ``[]`` -- the same "never block a run" policy as
    ``facet_rag.planner.fallback_facets``, except the fallback here is simply
    no appendix at all (the request narrative alone remains authoritative).
    """
    try:
        raw = one_shot(provider, "", build_brief_prompt(narrative))
    except Exception:
        log.exception("brief.get_requirements: one_shot call failed; "
                      "proceeding with an empty brief")
        return []
    return parse_brief(raw, narrative)


def render_appendix(requirements: list[Requirement]) -> str:
    """Render PLAN.md §3.2's "Appendix A" -- empty string when the brief is
    empty, so the system prompt is then byte-identical to the loaded
    template (plus the static Appendix B baked into default.md)."""
    if not requirements:
        return ""
    entries = "\n".join(
        ENTRY_TEMPLATE.format(id=r.id, origin=r.origin, requirement=r.requirement,
                              specific_form=r.specific_form)
        for r in requirements)
    return APPENDIX_TEMPLATE.format(entries=entries)


__all__ = [
    "MAX_ENTRIES", "MAX_IMPLICIT", "Requirement", "build_brief_prompt",
    "get_requirements", "parse_brief", "render_appendix",
]
