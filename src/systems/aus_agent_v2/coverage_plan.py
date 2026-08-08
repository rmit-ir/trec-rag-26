"""Isolated request decomposition for the AUS multi-stage pipeline."""
from __future__ import annotations

import re


COVERAGE_PLAN_SYSTEM = """\
You are the planning stage of a research system. Analyze the request before any
search happens. Produce a concise coverage plan for a separate research agent
and evidence writer; do not answer the request and do not invent facts.

The plan must identify:
- the exact deliverable form and number of parts the user requested;
- the organizer accepts plain prose sentences, so do not invent visible
  headings, sections, tables, bullets, or numbered answer parts unless the
  original request explicitly requires that presentation;
- operational counts for plural deliverables: absent an explicit count, a
  "series" means at least three parts, and examples/problems/cases requested
  in the plural for each repeated part mean at least two in every part; budget
  for those minima before optional topics;
- a section-by-section final-answer budget totaling at most 950 words (the hard
  track limit is 1,024); when the same requirement applies to every post,
  example, domain, or other repeated part, choose few enough parts that every
  one can contain all its required elements before adding optional breadth;
- the audience, assumed prior knowledge, and terms or acronyms that need plain
  definitions;
- every explicit topic, comparison, example, decision, or constraint;
- standard alternatives, institutions, instruments, dimensions, risks, or
  failure modes a knowledgeable reader would reasonably expect even when the
  request does not name them;
- the concrete evidence searches needed to support those points;
- for a proposed study, measurement, or prevalence analysis, at least one
  concrete prior study or dataset result that establishes the research context;
- for a judgment across people, countries, or society, which populations,
  study designs, causal limits, and counterevidence must qualify broad claims;
- for a tutorial, article series, or other pedagogical deliverable, the hook,
  prerequisites, formal definitions, important variations, worked examples,
  reusable heuristics with pitfalls, takeaways, and progression between parts;
- for a request demanding a definite proof about a conceptual or hypothetical
  system, both the formal conditional theorem and the limits of any universal
  claim, plus the field's canonical mechanisms, failure modes, one illustrative
  thought experiment, proposed mitigations, and computational/data/human
  resource constraints; do not let abstract formalism crowd these out;
- any time-sensitive or jurisdiction-sensitive details that must not be guessed.

Use 6 to 14 numbered items, ordered by importance. Each item must be one or two
sentences and label itself as DELIVERABLE, AUDIENCE, EXPLICIT, IMPLIED,
DEFINITION, EXAMPLE, EVIDENCE, BUDGET, or SAFETY. Stay under 500 words. Return
only the plan.
"""


def coverage_plan_request(query: str) -> str:
    """Frame the original request without adding domain-specific hints."""
    return "ORIGINAL RESEARCH REQUEST\n\n" + query.strip()


def normalize_coverage_plan(text: str | None, *, max_chars: int = 8_000,
                            max_words: int = 500) -> str:
    """Bound a provider response without cutting a numbered item in half."""
    compact = (text or "").strip()
    if compact.startswith("```") and compact.endswith("```"):
        lines = compact.splitlines()
        compact = "\n".join(lines[1:-1]).strip()
    blocks = re.split(r"\n(?=\s*\d+\.)", compact)
    kept: list[str] = []
    word_count = 0
    char_count = 0
    for block in blocks:
        block = block.strip()
        separator = 1 if kept else 0
        block_words = len(block.split())
        if (char_count + separator + len(block) > max_chars
                or word_count + block_words > max_words):
            break
        kept.append(block)
        char_count += separator + len(block)
        word_count += block_words
    if kept:
        return "\n".join(kept).rstrip()
    # Malformed output with no usable item still needs a hard safety bound.
    bounded = compact[:max_chars].rstrip()
    words = list(re.finditer(r"\S+", bounded))
    if len(words) > max_words:
        bounded = bounded[:words[max_words - 1].end()]
    return bounded.rstrip()
