"""facets_agent's ``pre_final_hook`` (PLAN.md Phase 4, §7.1): a coverage gate
on the harness's ``run_agent`` final-report acceptance.

facets_agent's own ``commit_context`` schema (``tools.py``) already carries a
``coverage`` ledger and a ``ready_to_report`` flag, restated on every commit
call — but nothing enforced that ``ready_to_report`` was actually consistent
with the ledger before the harness accepted the report. This hook is that
check: it reads the LAST ``commit_context`` call's ``coverage`` payload
straight out of ``last_commit_arguments`` (the ``ContextLedger`` itself only
tracks committed/rejected document ids, not this schema's requirement
entries — the harness stays generic by design, see
``agent_harness.agent.run_agent``'s ``pre_final_hook`` docstring), and if any
entry is still ``open``, sends the model back for one more targeted look
instead of accepting the report.

Deliberately NOT implemented here (PLAN.md Phase 4b): re-scanning
``ledger.rejected_ids``'s original text via a cheap secondary-model judge for
material that could close a ``covered_but_shallow`` gap without a new
search. That's a separate, independently-measurable capability.
"""
from __future__ import annotations

from typing import Any


def coverage_gate(context: dict[str, Any]) -> str | None:
    """``pre_final_hook`` implementation: ``None`` accepts the report as-is;
    a string sends the model back with the open requirements named."""
    arguments = context.get("last_commit_arguments")
    coverage = arguments.get("coverage") if isinstance(arguments, dict) else None
    if not isinstance(coverage, list) or not coverage:
        return None
    open_entries = [
        entry for entry in coverage
        if isinstance(entry, dict) and entry.get("status") == "open"
    ]
    if not open_entries:
        return None
    lines = "\n".join(
        f"- {entry.get('requirement', '(unnamed requirement)')}"
        + (f" — {entry['note']}" if entry.get("note") else "")
        for entry in open_entries
    )
    return (
        "Before this report is accepted: your own requirement ledger still "
        f"lists {len(open_entries)} entr"
        + ("y" if len(open_entries) == 1 else "ies")
        + " as `open` (not yet covered by committed evidence):\n" + lines
        + "\nSearch for exactly these, then write the report again. If one "
          "is genuinely unavailable after being searched on more than one "
          "engine, mark it `unavailable` in your next commit_context call "
          "instead of leaving it `open`, and say so in the report rather "
          "than silently omitting it."
    )
