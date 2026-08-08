"""Evidence-aware draft review for the AUS agent's finishing pipeline.

The first ``finish-the-claim`` experiment was prompt-only: it asked the model
to prefer fewer complete points, but never inspected the draft or connected a
sentence to the structured facts previously extracted for its citations.  The
result changed surface behavior (more figures, fewer vague phrases) while also
deleting coverage.  This module supplies the missing pipeline stage.

Facts are captured only for documents the harness actually commits.  The target
Sol model does not reliably emit that optional annotation, though, so the live
review path cannot depend on it.  Instead, each draft sentence is paired with
the best-matching excerpts from exactly the committed units it cites.  A fresh
writer context receives those citation-local cards, the request, and the draft;
it never has to recover evidence from the long research trajectory.
"""
from __future__ import annotations

import re
from typing import Any


FactLedger = dict[str, list[dict[str, str]]]

FINISH_REVIEW_SYSTEM = """\
You are the evidence patcher for a completed cited research draft. Do not
rewrite the report. Identify only draft lines whose existing claim can be made
more precise from that line's evidence cards, and propose a replacement for
that same line.

Return one JSON object with this exact shape:
{"edits":[{"line":12,"replacement":"Complete sentence. [unit_id]"}]}

Rules:
- Each line number must be a DRAFT CLAIM line number printed on a card.
- Preserve the original line's point; add its missing value, scope, source,
  definition, or comparison only when the card directly supports it.
- Use only ALLOWED CITATION ids printed for that same line, and end every
  factual replacement with one or more [unit_id] markers.
- Do not delete, merge, split, reorder, summarize, or add report lines.
- Omit a line from edits when no clearly better evidence-grounded replacement
  exists. An empty edits array is a successful result.
- Return JSON only, with no Markdown fence or commentary.

The harness applies accepted replacements to the original draft
deterministically. Unmentioned lines remain byte-for-byte unchanged, so report
coverage cannot disappear during this stage.
"""

FINISH_COVERAGE_AUDIT_SYSTEM = """\
You are the coverage verifier between a research draft and its final evidence
editor. Compare the draft with the original request and the pre-research plan.
Do not rewrite the report and do not assess citation support. List only material
omissions or format/audience failures that the final editor must repair.

Prioritize the requested deliverable form, number of parts, audience and assumed
knowledge, every explicit comparison or example, and distinct high-value items
in the plan. Do not demand every optional idea when the draft already answers
the request well. Return 1 to 12 short numbered findings, or exactly NO MATERIAL
COVERAGE GAPS. Stay under 350 words and return only the audit.
"""

_CITATION_RE = re.compile(r"\[([\w.-]+(?:[,;\s]+[\w.-]+)*)\]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[.,:/-][A-Za-z0-9]+)*")
_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "in", "is", "it", "of", "on", "or", "that", "the", "their",
    "this", "to", "was", "were", "with",
})

MAX_EVIDENCE_CARDS = 48
MAX_EXCERPT_CHARS = 560
MAX_PACKET_CHARS = 80_000
MAX_REPORT_WORDS = 1_024


def build_coverage_audit_request(
    query: str,
    draft: str,
    coverage_plan: str = "",
) -> str:
    """Give the verifier only requirements and prose, never the noisy trajectory."""
    return (
        "ORIGINAL RESEARCH REQUEST\n"
        + query.strip()
        + ("\n\nPRE-RESEARCH COVERAGE PLAN\n" + coverage_plan.strip()
           if coverage_plan.strip() else "")
        + "\n\nDRAFT TO AUDIT\n"
        + draft.strip()
    )


def capture_committed_facts(
    arguments: dict[str, Any],
    committed_ids: list[str],
    ledger: FactLedger,
) -> int:
    """Persist valid fact cards for the ids the commit handler accepted.

    ``ContextLedger`` intentionally ignores optional model annotations.  That
    is correct for document retention, but it previously left ``facts`` buried
    only in the historical function-call arguments.  Capturing them here makes
    them explicit pipeline state while preserving the handler's authority over
    which ids actually committed (including its per-step cap).
    """
    accepted = set(committed_ids)
    added = 0
    documents = arguments.get("documents", [])
    if not isinstance(documents, list):
        return 0
    for document in documents:
        if not isinstance(document, dict):
            continue
        unit_id = str(document.get("id") or document.get("docid") or "").strip()
        if unit_id not in accepted:
            continue
        raw_facts = document.get("facts", [])
        if not isinstance(raw_facts, list):
            continue
        # Do not create an empty bucket merely because the document committed.
        # The old summary therefore claimed "documents_with_facts=18" when Sol
        # had emitted zero fact cards for all 18 documents.
        stored = ledger.get(unit_id, [])
        seen = {(fact["claim"], fact["value"]) for fact in stored}
        for raw in raw_facts:
            if not isinstance(raw, dict):
                continue
            claim = str(raw.get("claim") or "").strip()
            value = str(raw.get("value") or "").strip()
            if not claim or not value or (claim, value) in seen:
                continue
            fact = {"claim": claim, "value": value}
            for optional in ("scope", "source"):
                text = str(raw.get(optional) or "").strip()
                if text:
                    fact[optional] = text
            stored.append(fact)
            ledger[unit_id] = stored
            seen.add((claim, value))
            added += 1
    return added


def _tokens(text: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 1 and token not in _STOP
    }


def _value_already_used(value: str, sentence: str) -> bool:
    value_tokens = _tokens(value)
    if not value_tokens:
        return False
    sentence_tokens = _tokens(sentence)
    if " ".join(_TOKEN_RE.findall(value.lower())) in " ".join(
            _TOKEN_RE.findall(sentence.lower())):
        return True
    return len(value_tokens & sentence_tokens) / len(value_tokens) >= 0.65


def _relevance(fact: dict[str, str], sentence: str) -> float:
    sentence_tokens = _tokens(sentence)
    claim_tokens = _tokens(fact["claim"])
    scope_tokens = _tokens(fact.get("scope", ""))
    if not sentence_tokens or not claim_tokens:
        return 0.0
    claim_overlap = len(sentence_tokens & claim_tokens) / len(claim_tokens)
    scope_overlap = (
        len(sentence_tokens & scope_tokens) / len(scope_tokens)
        if scope_tokens else 0.0
    )
    return claim_overlap + 0.25 * scope_overlap


def _citations(line: str) -> list[str]:
    ids: list[str] = []
    for match in _CITATION_RE.finditer(line):
        for token in re.split(r"[,;\s]+", match.group(1)):
            if token and token not in ids:
                ids.append(token)
    return ids


def _short(text: str, limit: int = 280) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def _source_spans(text: str) -> list[str]:
    """Return readable source spans without pretending sentence splitting is NLP.

    ClimbMix chunks mix prose, headings, and list fragments. Splitting first on
    line boundaries and then on terminal punctuation gives the reviewer compact
    verbatim evidence while retaining a fallback for punctuation-poor text.
    """
    spans: list[str] = []
    for block in re.split(r"\n+", text):
        block = " ".join(block.split())
        if not block:
            continue
        pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", block)
        for piece in pieces:
            piece = piece.strip()
            if len(piece) >= 24:
                spans.append(piece)
    return spans or ([" ".join(text.split())] if text.strip() else [])


def _span_score(claim: str, span: str) -> float:
    """Lexical relevance with a small bonus for matching exact quantities."""
    claim_tokens = _tokens(claim)
    span_tokens = _tokens(span)
    if not claim_tokens or not span_tokens:
        return 0.0
    overlap = len(claim_tokens & span_tokens)
    score = overlap / max(
        1.0, len(claim_tokens) ** 0.5 * len(span_tokens) ** 0.5)
    claim_numbers = set(re.findall(r"\b\d[\d.,:/%-]*", claim))
    span_numbers = set(re.findall(r"\b\d[\d.,:/%-]*", span))
    if claim_numbers & span_numbers:
        score += 0.35
    return score


def build_finish_review_packet(
    query: str,
    draft: str,
    documents: dict[str, dict[str, Any]],
    facts: FactLedger | None = None,
    *,
    coverage_plan: str = "",
    max_cards: int = MAX_EVIDENCE_CARDS,
    max_packet_chars: int = MAX_PACKET_CHARS,
) -> tuple[str, dict[str, int]] | None:
    """Build a bounded claim-to-evidence packet from committed source text.

    Cards are keyed by one draft line and one of that line's citations. No
    excerpt can migrate across citation ids, so the reviewer sees weak support
    as weak support instead of being handed a plausible passage from some other
    committed source. Model-extracted facts are included when available, but
    raw source excerpts make the stage work when the research model emits none.
    """
    cards: list[str] = []
    cited_documents: set[str] = set()
    source_cache: dict[str, list[str]] = {}
    card_number = 0
    limit_reached = False
    inferred_citations = 0
    for line_number, raw_line in enumerate(draft.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        claim = _CITATION_RE.sub(" ", line).strip()
        unit_ids = _citations(line)
        citation_status = "present"
        if not unit_ids:
            # Do not repeat the failed cite-or-cut intervention. Find the one
            # committed unit whose text most closely matches an uncited draft
            # point and let the reviewer add that citation when it truly
            # supports the point. A weak match is left without a card rather
            # than laundering unrelated evidence into the sentence.
            best: tuple[float, str] | None = None
            for candidate_id, document in documents.items():
                spans = source_cache.setdefault(
                    candidate_id,
                    _source_spans(str(document.get("text") or "")),
                )
                score = max((_span_score(claim, span) for span in spans),
                            default=0.0)
                if best is None or score > best[0]:
                    best = (score, candidate_id)
            if best is not None and best[0] >= 0.18:
                unit_ids = [best[1]]
                citation_status = "missing; add only if the excerpts support it"
                inferred_citations += 1
        for unit_id in unit_ids:
            document = documents.get(unit_id)
            if not document:
                continue
            spans = source_cache.setdefault(
                unit_id, _source_spans(str(document.get("text") or "")))
            ranked = sorted(
                spans, key=lambda span: _span_score(claim, span), reverse=True)
            excerpts = [
                _short(span, MAX_EXCERPT_CHARS) for span in ranked[:2]
            ]
            fact_lines = []
            for fact in (facts or {}).get(unit_id, [])[:2]:
                fact_lines.append(
                    "claim=" + _short(fact["claim"], 180)
                    + "; value=" + _short(fact["value"], 180)
                    + ("; scope=" + _short(fact["scope"], 140)
                       if fact.get("scope") else "")
                    + ("; source=" + _short(fact["source"], 140)
                       if fact.get("source") else "")
                )
            if not excerpts and not fact_lines:
                continue
            card_number += 1
            parts = [
                f"CARD {card_number} — draft line {line_number}",
                f"DRAFT CLAIM: {_short(claim, 500)}",
                f"DRAFT CITATION STATUS: {citation_status}",
                f"ALLOWED CITATION: [{unit_id}]",
            ]
            parts.extend(
                f"SOURCE EXCERPT {index}: {excerpt}"
                for index, excerpt in enumerate(excerpts, 1)
            )
            parts.extend(
                f"EXTRACTED FACT {index}: {fact}"
                for index, fact in enumerate(fact_lines, 1)
            )
            card = "\n".join(parts)
            projected = len("\n\n".join(cards + [card]))
            if projected > max_packet_chars or len(cards) >= max_cards:
                limit_reached = True
                break
            cards.append(card)
            cited_documents.add(unit_id)
        if limit_reached:
            break
    if not cards:
        return None

    packet = (
        "ORIGINAL RESEARCH REQUEST\n"
        + query.strip()
        + ("\n\nPRE-RESEARCH COVERAGE PLAN\n" + coverage_plan.strip()
           if coverage_plan.strip() else "")
        + "\n\nDRAFT TO VERIFY AND REVISE\n"
        + f"DRAFT WORD COUNT: {len(draft.split())}\n"
        + draft.strip()
        + "\n\nCITATION-LOCAL EVIDENCE CARDS\n"
        + "\n\n".join(cards)
    )
    return packet, {
        "cards": len(cards),
        "documents": len(cited_documents),
        "packet_chars": len(packet),
        "inferred_citations": inferred_citations,
    }


def build_finish_review_feedback(
    draft: str,
    ledger: FactLedger,
    *,
    max_suggestions: int = 12,
) -> str | None:
    """Build one bounded, citation-local revision brief for a valid draft.

    One best unused fact is offered per cited sentence.  Relevance must be
    visible in the claim wording, so the review does not turn a shared source
    into permission to inject unrelated details.  A low suggestion cap avoids
    reproducing the failed ``sol-tools`` arm, where large tool payloads crowded
    the finishing turn.
    """
    suggestions: list[str] = []
    for line_number, raw_line in enumerate(draft.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        ids = _citations(line)
        if not ids:
            continue
        sentence = _CITATION_RE.sub(" ", line)
        candidates: list[tuple[float, str, dict[str, str]]] = []
        for unit_id in ids:
            for fact in ledger.get(unit_id, []):
                if _value_already_used(fact["value"], sentence):
                    continue
                score = _relevance(fact, sentence)
                if score >= 0.20:
                    candidates.append((score, unit_id, fact))
        if not candidates:
            continue
        _score, unit_id, fact = max(candidates, key=lambda item: item[0])
        parts = [
            f"line {line_number}, citation {unit_id}",
            f"current point: {_short(sentence, 180)}",
            f"document states: {_short(fact['claim'], 180)}",
            f"specific value: {_short(fact['value'])}",
        ]
        if fact.get("scope"):
            parts.append(f"scope: {_short(fact['scope'], 160)}")
        if fact.get("source"):
            parts.append(f"source: {_short(fact['source'], 160)}")
        suggestions.append("; ".join(parts))
        if len(suggestions) >= max_suggestions:
            break
    if not suggestions:
        return None

    return (
        "Revise the draft once using this evidence-to-claim review. Preserve "
        "every accurate, supported point already in the draft and preserve its "
        "coverage; do not shorten the answer merely to make fewer points. The "
        "cards below are not new topics and are not a checklist to include. "
        "Each is an unused specific from the SAME document the current point "
        "already cites. Where it genuinely completes that point, replace vague "
        "or generic wording with the specific value and its scope/source. "
        "Otherwise leave the point unchanged. Do not invent, do not move a fact "
        "to a different claim, and keep the complete answer at or below 1,024 "
        "words. Emit no commentary about this review; return only the revised "
        "cited report.\n\nEvidence-to-claim opportunities:\n- "
        + "\n- ".join(suggestions)
    )


def _json_object(text: str | None) -> dict[str, Any] | None:
    """Parse a bare or fenced JSON object without accepting trailing prose."""
    candidate = (text or "").strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        import json

        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _card_permissions(packet: str) -> dict[int, set[str]]:
    """Recover the line-to-citation permissions printed in evidence cards."""
    permissions: dict[int, set[str]] = {}
    current: int | None = None
    for raw in packet.splitlines():
        card = re.match(r"CARD \d+ — draft line (\d+)$", raw.strip())
        if card:
            current = int(card.group(1))
            permissions.setdefault(current, set())
            continue
        allowed = re.match(r"ALLOWED CITATION: \[([^\]]+)\]$", raw.strip())
        if allowed and current is not None:
            permissions[current].add(allowed.group(1))
    return permissions


def _claim_tokens_without_citations(text: str) -> set[str]:
    """Content tokens used by the conservative claim-retention gate."""
    return _tokens(_CITATION_RE.sub(" ", text))


def apply_evidence_patches(
    draft: str,
    response: str | None,
    packet: str,
    *,
    max_words: int = MAX_REPORT_WORDS,
) -> tuple[str, dict[str, int], list[str]]:
    """Apply safe line replacements while making deletion structurally impossible.

    The model never returns the final report. It returns proposed replacements;
    this function reconstructs the report from the original lines. A patch is
    accepted only when it targets a carded line, cites only evidence permitted
    for that line, retains the original claim's vocabulary, does not shrink the
    line materially, and keeps the whole report under the track cap.
    """
    parsed = _json_object(response)
    stats = {"proposed": 0, "accepted": 0, "rejected": 0}
    errors: list[str] = []
    if parsed is None or set(parsed) != {"edits"} or not isinstance(
            parsed.get("edits"), list):
        return draft, stats, ["patch response was not an exact edits JSON object"]

    permissions = _card_permissions(packet)
    lines = draft.splitlines()
    seen: set[int] = set()
    for edit in parsed["edits"]:
        stats["proposed"] += 1
        if not isinstance(edit, dict) or set(edit) != {"line", "replacement"}:
            stats["rejected"] += 1
            errors.append("edit did not contain exactly line and replacement")
            continue
        line_number = edit["line"]
        replacement = edit["replacement"]
        if (not isinstance(line_number, int) or line_number < 1
                or line_number > len(lines) or line_number in seen
                or line_number not in permissions):
            stats["rejected"] += 1
            errors.append(f"line {line_number!r} was not one unique carded line")
            continue
        if not isinstance(replacement, str) or not replacement.strip():
            stats["rejected"] += 1
            errors.append(f"line {line_number} had an empty replacement")
            continue

        original = lines[line_number - 1].strip()
        replacement = " ".join(replacement.split())
        cited = set(_citations(replacement))
        if not cited or not cited <= permissions[line_number]:
            stats["rejected"] += 1
            errors.append(f"line {line_number} used a non-card citation")
            continue

        old_tokens = _claim_tokens_without_citations(original)
        new_tokens = _claim_tokens_without_citations(replacement)
        retention = (len(old_tokens & new_tokens) / len(old_tokens)
                     if old_tokens else 1.0)
        old_words = len(_CITATION_RE.sub(" ", original).split())
        new_words = len(_CITATION_RE.sub(" ", replacement).split())
        if retention < 0.35 or new_words < max(1, int(old_words * 0.75)):
            stats["rejected"] += 1
            errors.append(f"line {line_number} did not preserve its claim")
            continue

        candidate = list(lines)
        candidate[line_number - 1] = replacement
        if len("\n".join(candidate).split()) > max_words:
            stats["rejected"] += 1
            errors.append(f"line {line_number} would exceed {max_words} words")
            continue
        lines = candidate
        seen.add(line_number)
        stats["accepted"] += 1

    stats["rejected"] = stats["proposed"] - stats["accepted"]
    return "\n".join(lines), stats, errors
