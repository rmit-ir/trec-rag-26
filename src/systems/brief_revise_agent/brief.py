"""brief.py -- the pre-flight requirements-brief analyst (PLAN.md §3.1, v3
per ``worklogs/2026-08-07-brief-revise-agent-sol-iteration2-vs-aus-agent-v2.md``:
the "atomic expert-completion brief").

One tool-less LLM call before ``run_agent`` starts (``facet_rag.llm.one_shot``,
the same helper facet_rag's planner/curator use), producing a checklist of
small, independently-gradable answer checks -- both what the request states
(``kind="REQUEST"``) and what a domain expert would expect even though the
request never names it (``kind="EXPERT_COMPLETION"``).

v3 change from v2, and why: sol's analysis of iteration 1's losses against
``aus_agent_v2`` found the OLD lexical anti-hunch gate (an implicit entry's
`why` had to word-overlap the narrative) was suppressing exactly the
domain-completion material that distinguishes the stronger opponent's
answers -- e.g. "specify a prospective external validation stage" for a
clinical-AI topic, or "define an uncertainty/abstention rule", neither of
which the request's own wording implies but both of which an expert reader
expects. The gate is replaced with a cheaper, less restrictive check: an
EXPERT_COMPLETION entry needs a stated concrete reason (``why_needed``), not
narrative word-overlap. Ids are now HARNESS-assigned (``A01``, ``A02``, ...
in accepted order) rather than model-supplied, closing a real gap sol found
in the REVIEWER (not this module) that this module's id scheme enables
fixing cleanly: a reviewer response can no longer omit, duplicate, or
invent an id, because there is no model-chosen id space to omit from.

Parsing mirrors ``facet_rag.planner``'s defensive style exactly: a response
that strays from the schema or fails to parse at all is repaired or dropped
entry-by-entry, never raised -- ``get_requirements`` can never block a run.
An empty/failed brief degrades the run to plain `aus_agent` behaviour (no
appendix), which is the correct fallback, not a bug.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from facet_rag.llm import one_shot, strip_fences

from .prompts import APPENDIX_TEMPLATE, BRIEF_PROMPT, ENTRY_TEMPLATE

log = logging.getLogger(__name__)

MAX_ENTRIES = 14
MAX_EXPERT = 6
KINDS = frozenset({"REQUEST", "EXPERT_COMPLETION"})
# Per-field cap on what a brief entry may inject into the system prompt: a
# degenerate/adversarial analyst response (a run-on field, a pasted-in
# passage) must not silently balloon every subsequent turn's context. Also
# closes a real gap gpt-5.6-sol's code review flagged: `str(row.get(...))`
# turns a JSON `null`/list/object into literal text ("None", "['x']") that
# then reads as a non-empty field -- `_clean_field` rejects anything that
# was not actually a string before stripping/capping.
_MAX_FIELD_CHARS = 300


def _clean_field(value: Any, max_len: int = _MAX_FIELD_CHARS) -> str:
    """``value`` as a stripped, length-capped string -- or ``""`` for
    anything that was not actually a JSON string (``None``, a list, a dict),
    so a malformed field degrades to "missing" rather than to placeholder
    text like ``"None"``."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_len]


@dataclass
class Requirement:
    id: str            # harness-assigned: "A01", "A02", ... in accepted order
    kind: str           # "REQUEST" | "EXPERT_COMPLETION"
    requirement: str
    answer_form: str    # what counts as covering it -- a name/number/mechanism
    why_needed: str      # EXPERT_COMPLETION only: the concrete reason it matters


def build_brief_prompt(narrative: str) -> str:
    """Render ``BRIEF_PROMPT`` with the request narrative."""
    return BRIEF_PROMPT.format(narrative=narrative)


def parse_brief(raw: str, narrative: str) -> list[Requirement]:  # noqa: ARG001
    """Parse the analyst's JSON into validated, harness-numbered requirements.

    Caps at ``MAX_ENTRIES`` total / ``MAX_EXPERT`` expert-completion rows
    (PLAN.md §3.1: "an analyst that invents obligations is worse than none");
    every entry needs a non-empty ``requirement`` and ``answer_form``; every
    ``EXPERT_COMPLETION`` entry needs a non-empty ``why_needed``. ``narrative``
    is accepted but no longer used for a lexical check (v3 -- see module
    docstring); kept as a parameter for call-site stability.  Anything
    malformed is dropped rather than raised. Ids are assigned here, in
    accepted order, never read from the model's own JSON.
    """
    try:
        payload = json.loads(strip_fences(raw)) if raw else None
        rows = payload.get("requirements") if isinstance(payload, dict) else None
    except (json.JSONDecodeError, AttributeError, TypeError):
        rows = None
    if not isinstance(rows, list):
        return []

    requirements: list[Requirement] = []
    expert_count = 0
    for row in rows:
        if len(requirements) >= MAX_ENTRIES:
            break
        if not isinstance(row, dict):
            continue
        requirement = _clean_field(row.get("requirement"))
        answer_form = _clean_field(row.get("answer_form"))
        kind = _clean_field(row.get("kind"), max_len=20).upper()
        why_needed = _clean_field(row.get("why_needed"))
        if not requirement or not answer_form or kind not in KINDS:
            continue
        if kind == "EXPERT_COMPLETION":
            if expert_count >= MAX_EXPERT or not why_needed:
                continue
            expert_count += 1
        req_id = f"A{len(requirements) + 1:02d}"
        requirements.append(Requirement(
            id=req_id, kind=kind, requirement=requirement,
            answer_form=answer_form, why_needed=why_needed))
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
    # This call's tokens are real spend the harness's own trajectory never
    # sees (it only accounts the main run_agent provider) -- log it so a
    # pilot run's cost isn't silently undercounted (gpt-5.6-sol code review
    # finding). `_last_usage` is `one_shot`'s own documented side channel.
    log.info("brief.get_requirements: usage=%s",
             getattr(provider, "_last_usage", None))
    return parse_brief(raw, narrative)


def render_appendix(requirements: list[Requirement]) -> str:
    """Render PLAN.md §3.2's "Appendix A" -- empty string when the brief is
    empty, so the system prompt is then byte-identical to the loaded
    template (plus the static Appendix B baked into default.md)."""
    if not requirements:
        return ""
    entries = "\n".join(
        ENTRY_TEMPLATE.format(id=r.id, kind=r.kind, requirement=r.requirement,
                              answer_form=r.answer_form)
        for r in requirements)
    return APPENDIX_TEMPLATE.format(entries=entries)


__all__ = [
    "MAX_ENTRIES", "MAX_EXPERT", "Requirement", "build_brief_prompt",
    "get_requirements", "parse_brief", "render_appendix",
]
