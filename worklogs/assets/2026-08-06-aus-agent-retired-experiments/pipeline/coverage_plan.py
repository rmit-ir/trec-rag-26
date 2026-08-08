"""Isolated request decomposition for the AUS multi-stage pipeline."""
from __future__ import annotations


COVERAGE_PLAN_SYSTEM = """\
You are the planning stage of a research system. Analyze the request before any
search happens. Produce a concise coverage plan for a separate research agent
and evidence writer; do not answer the request and do not invent facts.

The plan must identify:
- the exact deliverable form and number of parts the user requested;
- the audience, assumed prior knowledge, and terms or acronyms that need plain
  definitions;
- every explicit topic, comparison, example, decision, or constraint;
- standard alternatives, institutions, instruments, dimensions, risks, or
  failure modes a knowledgeable reader would reasonably expect even when the
  request does not name them;
- the concrete evidence searches needed to support those points;
- any time-sensitive or jurisdiction-sensitive details that must not be guessed.

Use 6 to 14 numbered items, ordered by importance. Each item must be one or two
sentences and label itself as DELIVERABLE, AUDIENCE, EXPLICIT, IMPLIED,
DEFINITION, EXAMPLE, EVIDENCE, or SAFETY. Stay under 500 words. Return only the
plan.
"""


def coverage_plan_request(query: str) -> str:
    """Frame the original request without adding domain-specific hints."""
    return "ORIGINAL RESEARCH REQUEST\n\n" + query.strip()


def normalize_coverage_plan(text: str | None, *, max_chars: int = 8_000) -> str:
    """Bound a provider response before it enters two later model contexts."""
    compact = (text or "").strip()
    if compact.startswith("```") and compact.endswith("```"):
        lines = compact.splitlines()
        compact = "\n".join(lines[1:-1]).strip()
    return compact[:max_chars].rstrip()
