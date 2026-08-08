"""facets_agent's ``pre_final_hook``s (PLAN.md Phase 4, §7.1 and Phase 4e):
gates on the harness's ``run_agent`` final-report acceptance.

facets_agent's own ``commit_context`` schema (``tools.py``) already carries a
``coverage`` ledger and a ``ready_to_report`` flag, restated on every commit
call — but nothing enforced that ``ready_to_report`` was actually consistent
with the ledger before the harness accepted the report. ``coverage_gate`` is
that check: it reads the LAST ``commit_context`` call's ``coverage`` payload
straight out of ``last_commit_arguments`` (the ``ContextLedger`` itself only
tracks committed/rejected document ids, not this schema's requirement
entries — the harness stays generic by design, see
``agent_harness.agent.run_agent``'s ``pre_final_hook`` docstring), and if any
entry is still ``open``, sends the model back for one more targeted look
instead of accepting the report.

``citation_audit_gate`` (PLAN.md Phase 4e, two-tier retrieval's citation-
support follow-up — see
``worklogs/2026-08-06-facets-agent-two-tier-v2-improvements.md`` for the
evaluation this responds to) asks the model to self-identify two failure
patterns found in that evaluation's actual failing citations — a
topically-adjacent-but-factually-wrong document, and the model's own
recommendation/synthesis cited as if it were a sourced fact — and, unlike
a mechanical filter, explicitly directs it to run ANOTHER RETRIEVAL CYCLE
(new search/get_documents calls) to find better evidence rather than only
narrowing or dropping a weak citation. No new harness mechanism needed for
that: ``pre_final_hook`` firing already just injects one user message and
lets the model's next turn make whatever tool calls it wants before
attempting the report again. Instruction text drafted from the evaluation's
concrete examples, then reviewed and revised by gpt-5.6-sol — see
``worklogs/assets/2026-08-06-review-citation-audit-prompt.py`` /
``-sol-citation-audit-review.txt`` for the exact request and response.

``two_tier_final_gate`` composes both into the single shot
``pre_final_hook`` gets (it fires at most once per run, a structural
safety limit — see the harness's own docstring): coverage gaps first (a
missing requirement is a bigger defect than an imperfect citation), the
citation audit only if coverage is already clean.
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


_CITATION_AUDIT_TEMPLATE = """\
Before submitting the report, stop and audit every sentence–citation pair \
in the current draft. The document IDs cited in the draft are: {ids_list}. \
Treat this list only as an audit inventory: inspect every occurrence of \
every ID, and if a sentence has multiple IDs, verify each ID separately \
against the full text fetched with get_documents.

Flag either of these two failure patterns:

1. Topic match without claim support: the document concerns the right \
general subject but does not state the specific entity, attribution, \
fact, number, formula, comparison, or mechanism asserted in the sentence. \
For example, a general LSTM source does not support a claim about Apple \
QuickType unless it actually discusses Apple QuickType.

2. Model judgment presented as sourced fact: the sentence contains your \
own recommendation, heuristic, synthesis, or evaluation—such as "verify X \
before using it" or "N participants is too small for Y"—but the cited \
document does not itself state that recommendation or judgment. Evidence \
for background facts does not automatically support your evaluation of \
those facts.

For every claim flagged under either pattern, do not immediately narrow \
it, remove it, or merely delete its citation. First perform a targeted \
retrieval pass to find direct support for the exact claim or judgment. \
Use distinctive terms from the claim in new queries; try another engine \
or query formulation when useful; and inspect adjacent pages or related \
sections when the existing document appears close but the cited page is \
wrong. Search previews are not evidence: fetch promising results with \
get_documents, verify the relevant full text, and commit supporting \
documents with commit_context before citing them.

After that retrieval pass, replace unsupported citations with newly \
verified evidence wherever possible. If no direct support is found, only \
then use a fallback:
- For a factual claim, narrow it to exactly what the committed source \
states or remove it.
- For your own recommendation or synthesis, separate any sourced premises \
into cited factual sentences, then state the conclusion without a \
citation only if it introduces no new factual claim and genuinely follows \
from those premises; otherwise remove or qualify it.
- Remove any extra co-cited ID that does not independently support the \
part of the sentence for which it is cited.

Do not respond with an audit summary. Make the necessary search, \
get_documents, and commit_context calls first, then write the complete \
report again with only citations that pass this audit.\
"""


def citation_audit_gate(context: dict[str, Any]) -> str | None:
    """``pre_final_hook`` implementation: fires once, unconditionally,
    whenever the draft report carries at least one citation — ``None``
    only when there is nothing to audit (an uncited draft has no
    citation-support risk this check exists for)."""
    sentences = context.get("candidate_sentences") or []
    cited_ids = sorted({
        str(cid) for s in sentences if isinstance(s, dict)
        for cid in (s.get("citations") or [])
    })
    if not cited_ids:
        return None
    return _CITATION_AUDIT_TEMPLATE.format(ids_list=", ".join(cited_ids))


def two_tier_final_gate(context: dict[str, Any]) -> str | None:
    """Composes both checks into the single shot ``pre_final_hook`` gets
    (it fires at most once per run): coverage gaps first — a missing
    requirement is a bigger defect than an imperfect citation — the
    citation audit only if coverage is already clean."""
    return coverage_gate(context) or citation_audit_gate(context)
