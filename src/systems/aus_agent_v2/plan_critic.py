"""Blind atomic-obligation scout for a pre-research coverage plan.

The first planner is good at decomposing what it noticed, but showing that plan
to its reviewer anchors the review on the same concepts. This stage therefore
sees only the original request and independently recalls a bounded inventory.
It cannot answer the request, change counts, or supply evidence.
"""
from __future__ import annotations

import json
import re
from typing import Any


PLAN_CRITIC_SYSTEM = """\
You are the blind evaluator-expectation scout for a research system. You receive
the original request but deliberately do not see the other planner's output.
Predict the small set of atomic, binary checks that a demanding knowledgeable
reader would use to distinguish a complete answer from a merely plausible one.
Do not answer the request, state facts, or treat your own knowledge as evidence.

Coverage diversity comes before depth. Do not write broad wishlist items: each
addition must express one independently checkable obligation. Check for:
- canonical concepts and terminology needed to frame the domain completely,
  including qualitative mechanisms and risk dynamics rather than only formal
  machinery;
- standard alternatives, mechanisms, institutions, dimensions, or competing
  approaches that the plan overlooked;
- concrete examples, counterexamples, prior measurements, or evidence types
  needed to turn an abstract answer into a useful one; when the request joins
  two central variables or populations, require at least one prior measurement
  that studies that combination, not two unrelated adjacent studies; if an
  exact match proves unavailable, require the closest measured precedent with
  its population/outcome mismatch stated explicitly—a sentence saying no study
  was found does not establish the requested research context;
- failure scenarios, boundary conditions, resource limits, and credible
  mitigations for a claim about what is possible or guaranteed;
- every repeated deliverable requirement, prerequisite, definition, variation,
  alternative viewpoint, transferable insight, and progression step in a
  tutorial, series, or other pedagogical request; and
- the exact proper name, acronym, governing law or standard, canonical method,
  dataset, comparison baseline, or metric that generic prose would otherwise
  paraphrase away; and
- feasibility under the 1,024-word answer cap: rank atomic checks by expected
  evaluation value per answer word and prefer coverage over optional depth.

For a broad named domain or problem, actively recall the small set of standard
terms, mechanisms, and illustrative cases a serious introductory treatment is
normally expected to cover. For a series on important topics, inventory major
branches of the field, prerequisites and variations for each part, at least one
alternative viewpoint and cross-domain transfer, and an explicit progression
that reuses earlier ideas. For a conceptual safety or possibility argument,
inventory both the formal limits and the standard motivating dynamics,
failure scenarios, learning approaches, thought experiments, and resource
constraints.

Match the request to its answer archetype and reserve coverage for the compact
expectations that type routinely hides:
- A novice research guide normally needs expanded acronyms, named usable tools,
  the exact governing privacy or validation mechanisms, a concrete end-to-end
  workflow, and enough domain examples to make the proposed measurement real.
- A board strategy normally needs a defensible and measurable product edge,
  accountable roles and operating model, capital and unit-economics gates,
  long-term strategic or exit options, and named government programs material
  to positioning.
- A society-wide judgment normally needs justified geography and time scope,
  non-Western cases, technological turning points and platform mechanisms,
  regulatory contrasts at relevant levels, and short- versus long-run effects.
- A proof or possibility answer normally needs the field's canonical named
  limits, definitions, qualitative dynamics, and scenarios, not only a valid
  formal argument. For a recursively self-improving system, explicitly recall
  escalation or intelligence-feedback dynamics, concealed-cooperation or
  deceptive-turn scenarios, and instrumental incentives alongside formal
  self-verification limits.
- A tutorial series normally needs the field's major branches, intuitive
  definitions in every part, at least one alternative solution or viewpoint,
  common failure modes, and one explicit cross-domain transfer.

These are archetype prompts, not a checklist to copy. Select only expectations
material to this request. For each selected check, put any term that must be
stated literally in `must_mention`; use an empty list when no exact term is
needed. A search phrase is not an obligation: if HIPAA, a named theorem, a
regulator, or another standard matters, name it in both the requirement and
`must_mention`. When sensitive records, protected attributes, health, law, or
another regulated domain is present, one `safety` obligation naming the
applicable law or standard is mandatory and displaces the lowest-ranked format
item. For a society-wide, medical, or causal judgment, include one `penalty`
obligation naming the specific unsupported generalization to avoid. Include at
most two penalty-avoidance checks total.

Do not propose fewer parts, examples, cases, or other deliverables. Do not
relax or contradict the request. Add only high-value coverage; do not produce a
niche wishlist.

Return JSON only in exactly one of these shapes:
{"verdict":"pass","additions":[]}
{"verdict":"add","additions":[{"kind":"term|evidence|mechanism|comparison|scope|safety|format|penalty","requirement":"one atomic operational requirement","must_mention":["exact term"],"reason":"why its absence is material","search_leads":["one compact retrieval query"]}]}

Return at most twelve additions, ranked by expected evaluation weight per answer
word. Keep each requirement under 30 words, each reason under 35 words, at most
three exact terms, and at most one search lead. Do not combine distinct checks
with a list joined by "and". Use verdict "pass" only when no material implicit
check exists. Do not wrap the JSON in Markdown.
"""

_KINDS = {
    "term", "evidence", "mechanism", "comparison", "scope", "safety",
    "format", "penalty",
}


def plan_critic_request(query: str) -> str:
    """Keep the scout blind to the first plan so its recall is independent."""
    return "ORIGINAL RESEARCH REQUEST\n\n" + query.strip()


def normalize_plan_critique(text: str | None, *, max_additions: int = 8,
                            max_leads: int = 1,
                            max_mentions: int = 3) -> dict[str, Any]:
    """Fail closed on malformed output and bound every reused string."""
    raw = (text or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"verdict": "pass", "additions": [], "parse_error": True}
    if not isinstance(parsed, dict):
        return {"verdict": "pass", "additions": [], "parse_error": True}
    additions = parsed.get("additions")
    if parsed.get("verdict") not in {"pass", "add"} or not isinstance(
            additions, list):
        return {"verdict": "pass", "additions": [], "parse_error": True}

    clean: list[dict[str, Any]] = []
    for item in additions[:max_additions]:
        if not isinstance(item, dict):
            continue
        requirement = item.get("requirement")
        reason = item.get("reason")
        leads = item.get("search_leads", [])
        mentions = item.get("must_mention", [])
        kind = item.get("kind", "term")
        if not isinstance(requirement, str) or not requirement.strip():
            continue
        if not isinstance(reason, str) or not reason.strip():
            continue
        if not isinstance(leads, list):
            leads = []
        if not isinstance(mentions, list):
            mentions = []
        if kind not in _KINDS:
            kind = "term"
        clean.append({
            "kind": kind,
            "requirement": requirement.strip()[:300],
            "must_mention": [
                mention.strip()[:80]
                for mention in mentions[:max_mentions]
                if isinstance(mention, str) and mention.strip()
            ],
            "reason": reason.strip()[:300],
            "search_leads": [
                lead.strip()[:240]
                for lead in leads[:max_leads]
                if isinstance(lead, str) and lead.strip()
            ],
        })
    return {
        "verdict": "add" if clean else "pass",
        "additions": clean,
        "parse_error": False,
    }


def merge_plan_critique(plan: str, critique: dict[str, Any], *,
                        max_words: int = 700,
                        include_search_leads: bool = True) -> str:
    """Append only complete ranked findings without truncating an item."""
    additions = critique.get("additions") or []
    if not additions:
        return plan.strip()
    numbers = [int(value) for value in re.findall(r"(?m)^\s*(\d+)\.", plan)]
    next_number = max(numbers, default=0) + 1
    lines = [plan.strip()]
    word_count = len(plan.split())
    for offset, item in enumerate(additions):
        line = f"{next_number + offset}. SCOUT: {item['requirement']}"
        mentions = item.get("must_mention") or []
        if mentions:
            line += " EXACT: " + "; ".join(mentions)
        leads = item.get("search_leads") or []
        if include_search_leads and leads:
            line += " SEARCH: " + "; ".join(leads)
        line = line.rstrip() + "."
        line_words = len(line.split())
        if word_count + line_words > max_words:
            break
        lines.append(line)
        word_count += line_words
    return "\n\n".join(lines).rstrip()
