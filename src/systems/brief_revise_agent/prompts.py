"""Prompts for brief_revise_agent's two additions to the aus_agent fork
(PLAN.md §3): the pre-flight requirements brief (``brief.py``) and the
post-draft reviewer (``review.py``).

Phase 0 stub: the real prompt text lands with each stage's own
implementation -- ``BRIEF_PROMPT``/``APPENDIX_TEMPLATE``/``ENTRY_TEMPLATE``
in Phase 1 (``brief.py``), ``REVIEW_PROMPT`` in Phase 2 (``review.py``); see
PLAN.md §6 for the build sequence.
"""
from __future__ import annotations

BRIEF_PROMPT = ""  # Phase 1
APPENDIX_TEMPLATE = ""  # Phase 1
ENTRY_TEMPLATE = ""  # Phase 1
REVIEW_PROMPT = ""  # Phase 2

__all__ = ["APPENDIX_TEMPLATE", "BRIEF_PROMPT", "ENTRY_TEMPLATE", "REVIEW_PROMPT"]
