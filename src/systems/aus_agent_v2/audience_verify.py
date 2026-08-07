"""Plan-independent audit of a draft's predictable audience expectations.

The plan verifier can only enforce requirements that planning already found.
This stage deliberately omits the plan and asks a fresh context to find a few
central, compact omissions that a knowledgeable reader would notice anyway.
It diagnoses only; the evidence-owning research conversation performs repairs.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .finish_review import _short, _source_spans, _span_score


AUDIENCE_VERIFY_SYSTEM = """\
You are the plan-independent audience-coverage auditor for a research system.
You receive only the original request and a cited draft. Infer the deliverable
type and intended reader, then identify central expectations a knowledgeable
reader would find conspicuously absent even when the request did not enumerate
them. Do not answer the request, rewrite prose, grade citations, or invent
facts. Do not assume another planner's checklist is complete.

Audit breadth before depth. Depending on the deliverable, check especially:
- for a novice guide or research plan: expand essential acronyms, define core
  terms, name usable standard tools, give one end-to-end worked workflow, and
  state concrete privacy or validation mechanisms rather than generic cautions;
- for a strategy or market report: a specific product or technical advantage,
  operating model and accountable roles, capital/staging logic, long-term
  strategic options, and policy programs that materially affect positioning;
- for a societal or historical analysis: justified geography and time scope,
  technological turning points, non-Western cases, policy and regulatory
  contrasts, mechanisms, confounders, and short- versus long-run effects;
- for a proof, possibility, or safety argument: the canonical named limits,
  mechanisms, definitions, failure scenarios, and strongest conditional
  alternatives needed to make the conclusion intelligible;
- for a tutorial or series: coverage of the field's major branches, intuitive
  definitions in every part, complete reasoning, at least one alternative
  solution or viewpoint, common failure modes, and cross-domain transfer.

These are prompts for inspection, not boxes to demand blindly. Report an item
only when it is relevant to this exact request, materially absent from the
draft, and addable without displacing a more central requirement. Every
proposed repair must fit in one sentence of at most 40 words. Prefer a specific
name, definition, mechanism, comparison, accountable role, or compact scope
clarification over more examples, more sources, ornamental detail, or
exhaustive lists. Never request a new post, section, domain, full worked
example, research program, or multi-part analysis; those cannot be inserted
safely at this stage.
Treat a generic allusion as missing when a named mechanism is what makes the
point useful. Never demand facts merely because they appear in this system
message.

For a proof or possibility answer that already supplies a valid counterexample
or conditional theorem, do not spend an item strengthening its formalism.
Prefer absent standard names, definitions, qualitative mechanisms, and
canonical scenarios that let a non-specialist understand why the result
matters.

Return JSON only in exactly one of these shapes:
{"verdict":"pass","missing":[]}
{"verdict":"repair","missing":[{"requirement":"compact concrete addition","draft_gap":"what is absent or too generic","search_lead":"one compact query or empty string"}]}

List at most two omissions, ranked by importance and expected coverage gained
per answer word. Each repair must fit in one sentence of at most 40 words. Use
"pass" when no such material omission remains. Do not wrap JSON in Markdown.
"""

AUDIENCE_PATCH_SYSTEM = """\
You are a citation-grounded insertion editor. Add at most two compact sentences
to an otherwise accepted research draft. Return JSON only:
{"insertions":[{"finding":1,"after_line":12,"sentence":"One sentence. [unit_id]"}]}

Rules:
- Address only the numbered audience findings and use only evidence excerpts
  and ALLOWED CITATION ids printed under that same finding.
- Each insertion must be one sentence of at most 45 words, end in at least one
  allowed [unit_id] citation, and fit naturally after an existing draft line.
- Prefer a missing name, definition, mechanism, contrast, or accountable role.
- Do not rewrite, delete, merge, split, or restate existing draft lines. Do not
  add headings, lists, newlines, a new section, or a whole worked example.
- Use each finding at most once. Omit a finding when its cards do not directly
  support a useful insertion. An empty insertions array is successful.
"""

MAX_AUDIENCE_ITEMS = 2
MAX_AUDIENCE_PACKET_CHARS = 24_000
MAX_PATCH_WORDS = 45
MAX_REPORT_WORDS = 1_024
_CITATION_RE = re.compile(r"\[([\w.-]+(?:[,;\s]+[\w.-]+)*)\]")


def audience_verify_request(query: str, draft: str) -> str:
    """Build a plan-free packet so prior decomposition cannot anchor review."""
    packet = (
        "ORIGINAL RESEARCH REQUEST\n\n"
        + query.strip()
        + "\n\nCITED DRAFT TO AUDIT\n\n"
        + draft.strip()
    )
    return packet[:MAX_AUDIENCE_PACKET_CHARS].rstrip()


def normalize_audience_audit(text: str | None) -> dict[str, Any]:
    """Fail closed to no repair when an auxiliary response is malformed."""
    candidate = (text or "").strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return {"verdict": "pass", "missing": [], "parse_error": True}
    if not isinstance(parsed, dict) or set(parsed) != {"verdict", "missing"}:
        return {"verdict": "pass", "missing": [], "parse_error": True}
    if parsed["verdict"] not in {"pass", "repair"} or not isinstance(
            parsed["missing"], list):
        return {"verdict": "pass", "missing": [], "parse_error": True}

    clean: list[dict[str, str]] = []
    for item in parsed["missing"][:MAX_AUDIENCE_ITEMS]:
        if not isinstance(item, dict) or set(item) != {
                "requirement", "draft_gap", "search_lead"}:
            continue
        requirement = item["requirement"]
        gap = item["draft_gap"]
        lead = item["search_lead"]
        if not all(isinstance(value, str) for value in (requirement, gap, lead)):
            continue
        if requirement.strip() and gap.strip():
            clean.append({
                "requirement": requirement.strip()[:500],
                "draft_gap": gap.strip()[:500],
                "search_lead": lead.strip()[:240],
            })
    if parsed["verdict"] == "pass" or not clean:
        return {"verdict": "pass", "missing": []}
    return {"verdict": "repair", "missing": clean}


def build_audience_patch_packet(
    query: str,
    draft: str,
    audit: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    *,
    documents_per_finding: int = 2,
    max_packet_chars: int = 32_000,
) -> tuple[str, dict[int, set[str]]] | None:
    """Pair each compact omission with the most relevant committed evidence."""
    cards: list[str] = []
    allowed: dict[int, set[str]] = {}
    source_cache: dict[str, list[str]] = {}
    for index, item in enumerate(audit.get("missing", []), 1):
        needle = " ".join((
            item.get("requirement", ""),
            item.get("draft_gap", ""),
            item.get("search_lead", ""),
        ))
        ranked: list[tuple[float, str, list[str]]] = []
        for unit_id, document in documents.items():
            spans = source_cache.setdefault(
                unit_id, _source_spans(str(document.get("text") or "")))
            best = sorted(
                spans, key=lambda span: _span_score(needle, span), reverse=True)
            score = _span_score(needle, best[0]) if best else 0.0
            # The finding and a source excerpt often use different surface
            # vocabulary ("owner" versus an agency name). Keep a low lexical
            # gate, then let the patch model and citation validator reject a
            # merely adjacent passage.
            if score >= 0.05:
                ranked.append((score, unit_id, best[:2]))
        ranked.sort(reverse=True)
        selected = ranked[:documents_per_finding]
        if not selected:
            continue
        allowed[index] = {unit_id for _score, unit_id, _spans in selected}
        parts = [
            f"FINDING {index}",
            f"REQUIREMENT: {item['requirement']}",
            f"DRAFT GAP: {item['draft_gap']}",
        ]
        for _score, unit_id, spans in selected:
            parts.append(f"ALLOWED CITATION: [{unit_id}]")
            parts.extend(
                f"SOURCE EXCERPT: {_short(span, 520)}" for span in spans)
        cards.append("\n".join(parts))
    if not cards:
        return None
    numbered_draft = "\n".join(
        f"{line_number}: {line}"
        for line_number, line in enumerate(draft.splitlines(), 1)
    )
    packet = (
        "ORIGINAL RESEARCH REQUEST\n"
        + query.strip()
        + "\n\nNUMBERED ACCEPTED DRAFT — DO NOT REWRITE\n"
        + numbered_draft
        + "\n\nAUDIENCE FINDINGS WITH CITATION-LOCAL EVIDENCE\n"
        + "\n\n".join(cards)
    )
    if len(packet) > max_packet_chars:
        packet = packet[:max_packet_chars].rstrip()
    return packet, allowed


def apply_audience_insertions(
    draft: str,
    response: str | None,
    allowed: dict[int, set[str]],
) -> tuple[str, dict[str, int], list[str]]:
    """Apply bounded insertions while preserving every original line exactly."""
    stats = {"proposed": 0, "accepted": 0, "rejected": 0}
    errors: list[str] = []
    try:
        parsed = json.loads((response or "").strip())
    except (TypeError, ValueError):
        return draft, stats, ["patch response was not valid JSON"]
    if not isinstance(parsed, dict) or set(parsed) != {"insertions"} or not (
            isinstance(parsed["insertions"], list)):
        return draft, stats, ["patch response had the wrong shape"]
    proposed = parsed["insertions"][:MAX_AUDIENCE_ITEMS]
    stats["proposed"] = len(parsed["insertions"])
    if len(parsed["insertions"]) > MAX_AUDIENCE_ITEMS:
        errors.append("more than two insertions were proposed")
        stats["rejected"] += len(parsed["insertions"]) - MAX_AUDIENCE_ITEMS

    lines = draft.splitlines()
    accepted: list[tuple[int, str]] = []
    used_findings: set[int] = set()
    running_words = len(draft.split())
    for item in proposed:
        if not isinstance(item, dict) or set(item) != {
                "finding", "after_line", "sentence"}:
            stats["rejected"] += 1
            errors.append("an insertion had the wrong shape")
            continue
        finding = item["finding"]
        after_line = item["after_line"]
        sentence = item["sentence"]
        if (not isinstance(finding, int) or finding in used_findings
                or finding not in allowed):
            stats["rejected"] += 1
            errors.append("an insertion used an unknown or duplicate finding")
            continue
        if not isinstance(after_line, int) or not 1 <= after_line <= len(lines):
            stats["rejected"] += 1
            errors.append("an insertion targeted an invalid draft line")
            continue
        if not isinstance(sentence, str) or "\n" in sentence:
            stats["rejected"] += 1
            errors.append("an insertion was not one line")
            continue
        sentence = sentence.strip()
        sentence_words = len(sentence.split())
        citations = {
            token
            for match in _CITATION_RE.finditer(sentence)
            for token in re.split(r"[,;\s]+", match.group(1)) if token
        }
        if (not citations or not citations <= allowed[finding]
                or sentence_words > MAX_PATCH_WORDS):
            stats["rejected"] += 1
            errors.append("an insertion exceeded its word or citation authority")
            continue
        if running_words + sentence_words > MAX_REPORT_WORDS:
            stats["rejected"] += 1
            errors.append("an insertion would exceed the report word cap")
            continue
        accepted.append((after_line, sentence))
        used_findings.add(finding)
        running_words += sentence_words
        stats["accepted"] += 1

    by_line: dict[int, list[str]] = {}
    for after_line, sentence in accepted:
        by_line.setdefault(after_line, []).append(sentence)
    patched: list[str] = []
    for line_number, line in enumerate(lines, 1):
        patched.append(line)
        patched.extend(by_line.get(line_number, []))
    return "\n".join(patched), stats, errors
