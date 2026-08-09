"""blueprint.py -- an alternative ``pre_final_hook``: forces a validated,
evidence-conditioned report STRUCTURE before the single coherent prose
pass, instead of critiquing an already-written draft (``review.py``'s
approach, still this system's default).

Ported from a converged gpt-5.6-sol / Claude Opus 4.8 design review
(``worklogs/assets/2026-08-09-oss-agent-sol-plan-review.md``, turns 4-5,
plus ``worklogs/2026-08-09-oss-agent-open-weight-system.md``'s own D1
diagnostic): sol's own first-turn "A1" proposal, picked over its own "A3"
(a criterion-partitioned claim union with deterministic stitching)
specifically because D1 -- this repo's own fixed-evidence-replay
diagnostic -- found a flat writer-capability ceiling that survives even
perfect evidence. Opus's argument, which sol came to agree with: forcing
the model to mechanically STITCH claim fragments from parallel drafts
risks the very axes (Synthesis, Communication Quality) this mechanism is
meant to raise, when the underlying writer already struggles with
coherent prose; keeping ONE continuous writing pass, guided by an
explicit obligation-and-structure blueprint instead of the model's own
ad-hoc planning, does not carry that risk. Both S14 (blind scout) evidence
and D1's own finding that Implicit Criteria is NOT evidence-sensitive
motivate WHY a blueprint helps: the gap is that obligations get gathered
but don't survive into the final structure, not that evidence is missing.

Mechanism: on the model's first otherwise-valid final report (the same
trigger ``review.hook`` fires on), DISCARD that draft -- it was written
without a structure, which is the thing being fixed -- and make one fresh
isolated call producing a structured section-by-section blueprint
(heading, word budget, obligation ids covered, evidence-backed claims)
over the request, the full brief+scout obligation list, and committed
evidence read locally from the ledger (no re-fetch, no network, same
technique ``review._evidence_inventory`` uses). Validate it
deterministically and inject it as the harness's one guaranteed
revision-turn feedback, directing the model to write its REAL final
answer from this structure. Fires at most once (harness contract, same
as ``review.hook``) and is wrapped in one blanket exception guard -- a
blueprint failure must degrade to accepting the model's own original
draft, never fail a topic.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from facet_rag.llm import one_shot, strip_fences

from agent_harness.agent import MAX_REPORT_WORDS

from systems.brief_revise_agent.brief import Requirement

log = logging.getLogger(__name__)

# Leaves citation/organization margin under MAX_REPORT_WORDS, same target
# review.py's own feedback arithmetic uses (agent_harness.agent's own
# TARGET_REPORT_WORDS).
MAX_SECTION_BUDGET_TOTAL = 900
MIN_SECTIONS, MAX_SECTIONS = 2, 6
_SNIPPET_CHARS = 900  # fuller than review.py's 400 -- this call plans FROM evidence, not just checks a claim against it
_RELATIONS = frozenset({"comparison", "cause", "qualification", "fact"})
_REPAIR_SUFFIX = (
    "\n\nYour previous response did not parse as the exact JSON object "
    "shape requested above. Return ONLY that JSON object -- no prose, no "
    "code fences, no explanation before or after it.")

BLUEPRINT_SYSTEM = """\
You are a report architect for a corpus-grounded research assistant. You do \
NOT write the final report yourself -- you produce a structured plan the \
writer will follow, built entirely from evidence and obligations already \
gathered below. Every obligation must be placed somewhere or explicitly \
named as omitted; every claim must cite committed evidence ids that actually \
appear below -- never invent one.

Return JSON only, exactly this shape:
{"sections":[{"heading":"...","budget_words":130,"obligations":["R1","S2"],\
"claims":[{"claim":"...","docids":["shard_x_y_p1"],\
"relation":"comparison|cause|qualification|fact"}]}],\
"omitted_low_priority":["R9"]}

Rules:
- 2 to 6 sections, ordered for a coherent read (context/definition first, \
then evidence, then synthesis/implications last).
- Every obligation id given below appears in at least one section's \
`obligations`, OR in `omitted_low_priority` -- never silently dropped.
- Every claim has 1-3 docids, all drawn from the committed evidence given \
below.
- Section `budget_words` values sum to at most {max_total} words.
- Do not wrap the JSON in Markdown."""


def _clean_id(value: Any, max_len: int = 20) -> str:
    return value.strip()[:max_len] if isinstance(value, str) else ""


def _clean_text(value: Any, max_len: int = 400) -> str:
    return value.strip()[:max_len] if isinstance(value, str) else ""


def obligation_list(requirements: list[Requirement],
                    scout_additions: list[dict[str, Any]]
                    ) -> list[dict[str, str]]:
    """Unify brief requirements (``R``-ish ids, ``brief.parse_brief``'s own
    fallback naming) and scout additions (``S1..`` ids, matching
    ``scout.render_scout_appendix``'s own numbering -- both must agree so a
    blueprint obligation id and the appendix the model already read name
    the same thing) into one list the blueprint call and its validation
    share."""
    items = [{"id": r.id, "requirement": r.requirement,
             "specific_form": r.specific_form} for r in requirements]
    for i, addition in enumerate(scout_additions):
        items.append({"id": f"S{i + 1}", "requirement": addition["requirement"],
                     "specific_form": addition.get("reason", "")})
    return items


def _render_obligations(obligations: list[dict[str, str]]) -> str:
    if not obligations:
        return "(none -- no brief or scout obligations were produced for this topic)"
    return "\n".join(f"- [{o['id']}] {o['requirement']} -- {o['specific_form']}"
                     for o in obligations)


def _evidence_inventory(ledger: Any, committed_ids: set[str]) -> dict[str, str]:
    """Same technique as ``review._evidence_inventory`` (read locally from
    ``ledger.call_history``, no re-fetch) -- duplicated rather than
    imported because the snippet length differs (this call plans FROM
    evidence, review only spot-checks a claim against it) and importing a
    private helper across modules for a one-constant difference is worse
    than the ~15 lines of duplication."""
    call_history = getattr(ledger, "call_history", None) or {}
    committed_call_id = getattr(ledger, "committed_call_id", None) or {}
    inventory: dict[str, str] = {}
    for uid in committed_ids:
        call_id = committed_call_id.get(uid)
        result = call_history.get(call_id) if call_id else None
        documents = getattr(result, "documents", None) if result else None
        if not documents:
            continue
        for doc in documents:
            if str(doc.get("id")) == uid:
                inventory[uid] = str(doc.get("text") or "")[:_SNIPPET_CHARS]
                break
    return inventory


def _render_evidence(inventory: dict[str, str]) -> str:
    if not inventory:
        return "(no evidence has been committed)"
    return "\n".join(f"- {uid}: {text}" for uid, text in inventory.items())


def parse_blueprint(raw: str, valid_obligation_ids: set[str],
                    committed_ids: set[str]
                    ) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Parse the architect's JSON defensively -- drop what's invalid rather
    than reject the whole response, mirroring ``brief.parse_brief``'s and
    ``review._parse_review``'s own conventions. Returns ``(sections,
    omitted_ids, parsed_ok)``; ``parsed_ok=False`` only when the top-level
    shape itself didn't parse (triggers ``hook``'s one repair retry)."""
    try:
        payload = json.loads(strip_fences(raw)) if raw else None
    except (json.JSONDecodeError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        return [], [], False
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list):
        return [], [], False

    sections: list[dict[str, Any]] = []
    total_budget = 0
    for row in raw_sections[:MAX_SECTIONS]:
        if not isinstance(row, dict):
            continue
        heading = _clean_text(row.get("heading"), max_len=80)
        if not heading:
            continue
        budget = row.get("budget_words")
        budget = budget if (isinstance(budget, int) and not isinstance(budget, bool)
                            and 0 < budget <= MAX_SECTION_BUDGET_TOTAL) else 150
        obligations = [_clean_id(o) for o in (row.get("obligations") or [])
                      if _clean_id(o) in valid_obligation_ids]
        claims = []
        for claim_row in (row.get("claims") or []):
            if not isinstance(claim_row, dict):
                continue
            claim_text = _clean_text(claim_row.get("claim"))
            docids = [d for d in (claim_row.get("docids") or [])
                     if isinstance(d, str) and d in committed_ids][:3]
            if not claim_text or not docids:
                continue
            relation = _clean_id(claim_row.get("relation"), max_len=20).lower()
            claims.append({"claim": claim_text, "docids": docids,
                          "relation": relation if relation in _RELATIONS else "fact"})
        if total_budget + budget > MAX_SECTION_BUDGET_TOTAL:
            budget = max(0, MAX_SECTION_BUDGET_TOTAL - total_budget)
        total_budget += budget
        sections.append({"heading": heading, "budget_words": budget,
                        "obligations": obligations, "claims": claims})

    omitted = [_clean_id(o) for o in (payload.get("omitted_low_priority") or [])
              if _clean_id(o) in valid_obligation_ids]
    if len(sections) < MIN_SECTIONS:
        return [], [], False
    return sections, omitted, True


def render_blueprint_feedback(sections: list[dict[str, Any]], omitted: list[str],
                              obligations: list[dict[str, str]]) -> str:
    by_id = {o["id"]: o["requirement"] for o in obligations}
    lines = [
        "This draft is discarded -- write your REAL final answer now, "
        "following this exact structure (a section per heading, in this "
        "order, respecting each word budget):"
    ]
    for i, section in enumerate(sections, 1):
        obl = ", ".join(section["obligations"]) or "(none assigned)"
        lines.append(f"\n{i}. {section['heading']} (~{section['budget_words']} words) "
                    f"-- obligations: {obl}")
        for claim in section["claims"]:
            lines.append(f"   - [{claim['relation']}] {claim['claim']} "
                        f"[{', '.join(claim['docids'])}]")
    if omitted:
        named = "; ".join(f"[{o}] {by_id.get(o, o)}" for o in omitted)
        lines.append(f"\nExplicitly out of scope for this answer (say so if "
                    f"relevant, do not silently ignore): {named}")
    lines.append(
        "\nThe final response contract is UNCHANGED and still applies in "
        "full: write EXACTLY ONE SENTENCE PER LINE, in reading order, each "
        "ending with its own [docid] marker(s) (at most 3, only ids that "
        "directly support that exact sentence). The claims listed under "
        "each section above are a source of sentences, not paragraphs to "
        "compress them into -- a claim with a distinct fact, date, or "
        "number is its own line, not folded into a longer sentence with "
        "other claims. Do not write one long paragraph per section; that "
        "under-cites every fact in it down to 3 markers total. The section "
        "list above is your outline for ORDER and BUDGET, not a template "
        "to echo verbatim.")
    example = _worked_example(sections)
    if example:
        lines.append(f"\nWorked example of the exact format required, from "
                    f"your own section 1's claims:\n{example}")
    return "\n".join(lines)


def _worked_example(sections: list[dict[str, Any]]) -> str:
    """A concrete, this-topic-specific demonstration of one-sentence-per-
    line output, built from the model's own first section's claims --
    abstract format RULES did not stop a real glm-5 run from writing one
    long paragraph per section (smoke-tested 2026-08-09, twice); a
    worked example from the model's own claims is the standard fix for an
    instruction-following gap a rule restatement alone doesn't close."""
    for section in sections:
        claims = section["claims"][:2]
        if len(claims) >= 1:
            demo_lines = [f"{c['claim']} [{c['docids'][0]}]" for c in claims]
            return "\n".join(demo_lines) + (
                "\n(two short claims -> two separate lines, each with its "
                "own citation -- not one sentence combining both)")
    return ""


def hook(context: dict[str, Any], *,
        requirements: list[Requirement] = (),  # type: ignore[assignment]
        scout_additions: list[dict[str, Any]] = (),  # type: ignore[assignment]
        provider: Any = None) -> str | None:
    """``pre_final_hook``: replaces ``review.hook`` for this variant (the
    harness fires ``pre_final_hook`` at most once, so the two are
    alternatives, not stacked -- see module docstring). Never raises: any
    failure degrades to ``None`` (accept the model's own original draft),
    the same fail-open contract ``review.hook`` uses.
    """
    try:
        ledger = context.get("ledger")
        committed_ids = set(getattr(ledger, "committed_ids", None) or ())
        inventory = _evidence_inventory(ledger, committed_ids)
        obligations = obligation_list(list(requirements), list(scout_additions))
        valid_ids = {o["id"] for o in obligations}

        # .replace, not .format: the JSON schema example above is full of
        # literal {}s that .format would misparse as placeholders.
        prompt = BLUEPRINT_SYSTEM.replace("{max_total}", str(MAX_SECTION_BUDGET_TOTAL))
        user_text = (f"REQUEST\n\n{context.get('query', '')}\n\n"
                    f"OBLIGATIONS (brief + blind scout)\n"
                    f"{_render_obligations(obligations)}\n\n"
                    f"COMMITTED EVIDENCE\n{_render_evidence(inventory)}")
        raw = one_shot(provider, prompt, user_text)
        log.info("blueprint.hook: usage=%s", getattr(provider, "_last_usage", None))
        sections, omitted, parsed_ok = parse_blueprint(raw, valid_ids, committed_ids)
        if not parsed_ok:
            log.warning("blueprint.hook: architect response did not parse "
                       "(raw[:200]=%r); retrying once with a repair prompt",
                       raw[:200])
            raw = one_shot(provider, prompt, user_text + _REPAIR_SUFFIX)
            log.info("blueprint.hook: retry usage=%s",
                     getattr(provider, "_last_usage", None))
            sections, omitted, parsed_ok = parse_blueprint(raw, valid_ids, committed_ids)
            if not parsed_ok:
                log.warning("blueprint.hook: repair retry also failed to "
                           "parse; accepting the model's own draft as-is, "
                           "blueprint_failed=true")
                return None
        return render_blueprint_feedback(sections, omitted, obligations)
    except Exception:
        log.exception("blueprint.hook: unexpected failure; accepting the "
                     "model's own draft as-is")
        return None


__all__ = [
    "BLUEPRINT_SYSTEM", "MAX_SECTION_BUDGET_TOTAL", "hook",
    "obligation_list", "parse_blueprint", "render_blueprint_feedback",
]
