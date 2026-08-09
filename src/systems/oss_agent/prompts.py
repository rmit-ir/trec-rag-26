"""oss_agent's own prompt fragment.

Every OTHER prompt this system uses is reused verbatim, not duplicated:
the base system prompt and the requirements-brief/review prompts come from
``brief_revise_agent`` (``prompts/system/default.md``, ``prompts.py``), and
the blind-scout prompt comes from ``aus_agent_v2.plan_critic``
(``PLAN_CRITIC_SYSTEM``) -- see ``agent.py``'s module docstring for why.
This file holds only the one template oss_agent adds: how a scout addition
renders into the system-prompt appendix.
"""
from __future__ import annotations

SCOUT_APPENDIX_TEMPLATE = """

## Requirements brief -- blind scout additions

A second, independent analyst was shown ONLY the original request above (not \
the requirements brief above it, and not each other's output) and asked to \
recall additional atomic checks a demanding, knowledgeable reader would use \
to separate a complete answer from a merely plausible one. Treat every entry \
below exactly like the requirements brief: give it a targeted search, and \
count it covered only when the report states it in the specific form named, \
not as a category label.
{entries}
"""

SCOUT_ENTRY_TEMPLATE = (
    "- [{id}] (scout/{kind}) {requirement}{mentions} -- {reason}")

__all__ = ["SCOUT_APPENDIX_TEMPLATE", "SCOUT_ENTRY_TEMPLATE"]
