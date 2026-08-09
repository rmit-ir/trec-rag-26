"""scout.py -- the blind obligation scout, ported from aus_agent_v2.

``aus_agent_v2`` (this repo's strongest arena performer,
``worklogs/assets/2026-08-07-factor-analysis-report/report.typ`` S3) runs a
"blind" second planner, ``plan_critic.py``: shown ONLY the original request,
never the first planner's own output, so its recall is independent rather
than anchored on what the first planner already noticed. This module reuses
that exact prompt and parsing (``systems.aus_agent_v2.plan_critic``) and
adapts only the rendering: aus_agent_v2 merges additions into a free-text
numbered plan, oss_agent instead renders them as extra bullet entries
appended after ``brief_revise_agent.brief``'s own requirements appendix
(``prompts.SCOUT_APPENDIX_TEMPLATE``/``SCOUT_ENTRY_TEMPLATE``), so both
sources read as one consistent checklist to the main research loop.

Fails open exactly like ``brief.get_requirements``: any provider error or
unparseable response degrades to no scout additions, never blocks a run.
"""
from __future__ import annotations

import logging
from typing import Any

from facet_rag.llm import one_shot

from systems.aus_agent_v2.plan_critic import (
    PLAN_CRITIC_SYSTEM,
    normalize_plan_critique,
    plan_critic_request,
)

from .prompts import SCOUT_APPENDIX_TEMPLATE, SCOUT_ENTRY_TEMPLATE

log = logging.getLogger(__name__)

MAX_ADDITIONS = 8


def get_scout_additions(provider: Any, query: str,
                        max_additions: int = MAX_ADDITIONS
                        ) -> list[dict[str, Any]]:
    """Run the blind scout call and parse it defensively. Never raises."""
    try:
        raw = one_shot(provider, PLAN_CRITIC_SYSTEM, plan_critic_request(query))
    except Exception:
        log.exception("scout.get_scout_additions: one_shot call failed; "
                      "proceeding with no scout additions")
        return []
    log.info("scout.get_scout_additions: usage=%s",
             getattr(provider, "_last_usage", None))
    critique = normalize_plan_critique(raw, max_additions=max_additions)
    return critique.get("additions", [])


def render_scout_appendix(additions: list[dict[str, Any]]) -> str:
    """Empty string when there are no additions, so the appendix is then
    byte-identical to the brief's own (fail-open, same contract as
    ``brief.render_appendix``)."""
    if not additions:
        return ""
    entries = "\n".join(
        SCOUT_ENTRY_TEMPLATE.format(
            id=f"S{i + 1}", kind=item.get("kind", "term"),
            requirement=item["requirement"],
            mentions=(" EXACT: " + "; ".join(item["must_mention"])
                      if item.get("must_mention") else ""),
            reason=item["reason"])
        for i, item in enumerate(additions))
    return SCOUT_APPENDIX_TEMPLATE.format(entries=entries)


__all__ = ["MAX_ADDITIONS", "get_scout_additions", "render_scout_appendix"]
