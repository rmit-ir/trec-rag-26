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
# Per-field cap on what a brief entry may inject into the system prompt: a
# degenerate/adversarial analyst response (a run-on `why`, a pasted-in
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
    id: str
    requirement: str
    origin: str  # "explicit" | "implicit"
    why: str
    specific_form: str
    target_words: int = 0  # round C: 0 means "no budget assigned" (fail-open)


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


MIN_TARGET_TOTAL = 500
MAX_TARGET_TOTAL = 1000  # stays under the 1024 hard cap with revision room
_SUM_TOLERANCE = 0.20  # per-requirement targets may total +/-20% of the stated total


def parse_brief(raw: str, narrative: str) -> list[Requirement]:
    """Parse the analyst's JSON into validated requirements.

    Caps at ``MAX_ENTRIES`` total / ``MAX_IMPLICIT`` implicit (PLAN.md §3.1:
    "an analyst that invents obligations is worse than none"); every implicit
    entry must pass ``_why_quotes_narrative``; every entry needs a non-empty
    ``specific_form`` (the anti-`covered_but_shallow` field). Anything
    malformed is dropped rather than raised.

    Round C (sol's word-budget design): a top-level ``target_total_words``
    plus a per-requirement ``target_words`` are parsed too, but validated as
    a UNIT separate from the requirements themselves -- if the total is out
    of range, or the per-requirement targets don't roughly sum to it, EVERY
    ``target_words`` is zeroed (fails open to the no-budget behavior every
    earlier round already has) rather than dropping the requirements or the
    whole brief. A budget is advisory extra information, never a gate.
    """
    try:
        payload = json.loads(strip_fences(raw)) if raw else None
        rows = payload.get("requirements") if isinstance(payload, dict) else None
        target_total = payload.get("target_total_words") if isinstance(
            payload, dict) else None
    except (json.JSONDecodeError, AttributeError, TypeError):
        rows = None
        target_total = None
    if not isinstance(rows, list):
        return []

    requirements: list[Requirement] = []
    implicit_count = 0
    for row in rows:
        if len(requirements) >= MAX_ENTRIES:
            break
        if not isinstance(row, dict):
            continue
        requirement = _clean_field(row.get("requirement"))
        specific_form = _clean_field(row.get("specific_form"))
        origin = _clean_field(row.get("origin"), max_len=20).lower()
        why = _clean_field(row.get("why"))
        if not requirement or not specific_form or origin not in (
                "explicit", "implicit"):
            continue
        if origin == "implicit":
            if implicit_count >= MAX_IMPLICIT:
                continue
            if not why or not _why_quotes_narrative(why, narrative):
                continue
            implicit_count += 1
        req_id = _clean_field(row.get("id"), max_len=20) or f"R{len(requirements) + 1}"
        target_words = row.get("target_words")
        target_words = target_words if (
            isinstance(target_words, int) and not isinstance(target_words, bool)
            and target_words >= 0) else 0
        requirements.append(Requirement(
            id=req_id, requirement=requirement, origin=origin, why=why,
            specific_form=specific_form, target_words=target_words))

    valid_total = (isinstance(target_total, int)
                  and not isinstance(target_total, bool)
                  and MIN_TARGET_TOTAL <= target_total <= MAX_TARGET_TOTAL)
    part_sum = sum(r.target_words for r in requirements)
    sum_ok = (valid_total and part_sum > 0
             and abs(part_sum - target_total) <= _SUM_TOLERANCE * target_total)
    if not sum_ok:
        if any(r.target_words for r in requirements):
            log.info("brief.parse_brief: word-budget validation failed "
                     "(target_total=%r, part_sum=%d); zeroing all "
                     "target_words, requirements unaffected",
                     target_total, part_sum)
        for r in requirements:
            r.target_words = 0
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
    template (plus the static Appendix B baked into default.md). Round C:
    a requirement with a validated ``target_words`` gets it appended to its
    entry line; a budget-free brief (every ``target_words`` is 0, the
    fail-open state) renders identically to before round C existed."""
    if not requirements:
        return ""
    entries = "\n".join(
        ENTRY_TEMPLATE.format(
            id=r.id, origin=r.origin, requirement=r.requirement,
            specific_form=r.specific_form,
            budget=f" (~{r.target_words} words)" if r.target_words else "")
        for r in requirements)
    total = sum(r.target_words for r in requirements)
    total_line = (f"\nTotal answer word budget: ~{total} words "
                  f"(hard cap 1024).\n" if total else "")
    return APPENDIX_TEMPLATE.format(entries=entries, total_line=total_line)


__all__ = [
    "MAX_ENTRIES", "MAX_IMPLICIT", "MAX_TARGET_TOTAL", "MIN_TARGET_TOTAL",
    "Requirement", "build_brief_prompt", "get_requirements", "parse_brief",
    "render_appendix",
]
