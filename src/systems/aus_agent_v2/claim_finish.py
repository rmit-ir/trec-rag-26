"""Preservation-safe patches for concrete obligations missing from a draft."""
from __future__ import annotations

import json
from typing import Any

from .finish_review import (
    _CITATION_RE,
    _citations,
    _claim_tokens_without_citations,
    _short,
    _source_spans,
    _span_score,
)


CLAIM_FINISH_SYSTEM = """\
You are the final claim-completion editor for a cited research draft. You
receive numbered draft lines and at most four material findings, each paired
with citation-local source excerpts. Return JSON only:
{"patches":[{"finding":1,"mode":"replace","line":12,"sentence":"One complete sentence. [unit_id]"}]}

For each finding, either replace one related draft line or insert one sentence
after a related line, or add citation markers without changing its prose. Use
`mode` equal to `replace`, `insert_after`, or `cite`.

Rules:
- Address only the numbered findings using only their ALLOWED CITATION ids.
- Prefer `replace` when a draft line already begins the point but lacks its
  exact name, value, comparison, population, time/scope, source, or limitation.
- A replacement must preserve the original line's point and citations while
  completing it; an insertion must add one genuinely absent atomic point.
- Use `cite` for an otherwise sound uncited medical, safety, or causal
  synthesis. Its sentence words must remain exactly unchanged; append only
  directly supporting allowed citations.
- When a finding identifies an uncited sentence or asks only for citation
  presence, `cite` is the only permitted mode; copy that line's prose exactly.
- For a requested measurement, state its value, population/sample, time/scope,
  and source or study name when the excerpts support them. A nearby generic
  study is not a substitute for the finding's subject-outcome combination.
- When a finding explicitly asks for the closest measured precedent and a
  stated scope mismatch, that scoped adjacent measurement is the requested
  evidence; name both the result and the mismatch instead of omitting it.
- For a named safety, legal, or penalty obligation, state the exact name and
  how it constrains this request rather than offering generic caution.
- Every sentence must be one line, at most 55 words, and end with at least one
  allowed citation. Use each finding at most once and return at most four
  patches.
- Do not add headings, lists, sections, commentary, or an entire worked
  example. Do not rewrite, delete, merge, split, or reorder any other line.
- Omit a finding when its evidence does not directly support a compact patch.
  An empty patches array is successful.
"""

MAX_FINDINGS = 4
MAX_PATCH_WORDS = 55
MAX_REPORT_WORDS = 1_024


def _parent_unit_id(unit_id: str) -> str:
    """Return the document id shared by page-level ClimbMix citations."""
    parent, marker, page = unit_id.rpartition("_p")
    return parent if marker and parent and page.isdigit() else unit_id


def build_claim_finish_packet(
    query: str,
    draft: str,
    audit: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    *,
    documents_per_finding: int = 3,
    max_packet_chars: int = 44_000,
) -> tuple[str, dict[int, set[str]]] | None:
    """Pair each normalized omission with its best committed evidence."""
    cards: list[str] = []
    allowed: dict[int, set[str]] = {}
    source_cache: dict[str, list[str]] = {}
    draft_lines = [line for line in draft.splitlines() if line.strip()]
    for index, item in enumerate(audit.get("missing", [])[:MAX_FINDINGS], 1):
        needle = " ".join((
            str(item.get("requirement") or ""),
            str(item.get("draft_gap") or ""),
        ))
        scored_lines = sorted(
            ((_span_score(needle, line), line) for line in draft_lines),
            reverse=True,
        )
        best_line_score = scored_lines[0][0] if scored_lines else 0.0
        # A finding often names one draft sentence almost verbatim.  Do not
        # dilute that strong link with a weak runner-up whose generic citation
        # happens to contain words such as "prevalence" or "method".  Keep a
        # second line only when the finding genuinely refers to two comparably
        # related conclusions.
        related_lines = [
            line for score, line in scored_lines[:2]
            if score >= max(0.05, best_line_score * 0.55)
        ]
        related_ids = {
            unit_id
            for line in related_lines
            if _span_score(needle, line) >= 0.05
            for unit_id in _citations(line)
        }
        related_parents = {_parent_unit_id(unit_id) for unit_id in related_ids}
        ranked: list[tuple[float, str, list[str]]] = []
        for unit_id, document in documents.items():
            spans = source_cache.setdefault(
                unit_id, _source_spans(str(document.get("text") or "")))
            best = sorted(
                spans, key=lambda span: _span_score(needle, span), reverse=True)
            score = _span_score(needle, best[0]) if best else 0.0
            citation_local = unit_id in related_ids
            parent_local = _parent_unit_id(unit_id) in related_parents
            if citation_local:
                # The research writer already linked this source to the draft
                # claim the verifier named.  Keep lexical scoring for excerpt
                # choice, but give citation locality priority for document
                # choice so "complete this result" does not retrieve an
                # unrelated document that merely repeats the rubric words.
                score += 1.0
            elif parent_local:
                # Final output artifacts canonicalize page citations to their
                # parent document id.  Recover page locality when replaying a
                # saved draft, while retaining a slight preference for an
                # exact page id in the live pre-canonicalization pipeline.
                score += 0.8
            if score >= 0.05:
                # A complete result is commonly distributed across adjacent
                # source sentences: population, method, period, value, then
                # limitation.  Preserve that evidence bundle for a document
                # already cited by the target claim; two isolated lexical hits
                # are enough only for non-local candidate documents.
                ranked.append((
                    score,
                    unit_id,
                    best[:5] if citation_local or parent_local else best[:2],
                ))
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
                f"SOURCE EXCERPT: {_short(span, 620)}" for span in spans)
        cards.append("\n".join(parts))
    if not cards:
        return None
    numbered = "\n".join(
        f"{line_number}: {line}"
        for line_number, line in enumerate(draft.splitlines(), 1)
    )
    draft_words = len(draft.split())
    wordroom = max(0, MAX_REPORT_WORDS - draft_words)
    packet = (
        "ORIGINAL RESEARCH REQUEST\n"
        + query.strip()
        + "\n\nNUMBERED ACCEPTED DRAFT — PRESERVE UNPATCHED LINES\n"
        + f"DRAFT WORDS: {draft_words}; MAXIMUM NET PATCH GROWTH: "
        + f"{wordroom} WORDS; FINAL CAP: {MAX_REPORT_WORDS} WORDS\n"
        + numbered
        + "\n\nMATERIAL FINDINGS WITH CITATION-LOCAL EVIDENCE\n"
        + "\n\n".join(cards)
    )
    return packet[:max_packet_chars].rstrip(), allowed


def apply_claim_patches(
    draft: str,
    response: str | None,
    allowed: dict[int, set[str]],
) -> tuple[str, dict[str, int], list[str]]:
    """Apply local patches while retaining all unrelated draft lines exactly."""
    stats = {"proposed": 0, "accepted": 0, "rejected": 0}
    errors: list[str] = []
    try:
        parsed = json.loads((response or "").strip())
    except (TypeError, ValueError):
        return draft, stats, ["claim patch response was not valid JSON"]
    if not isinstance(parsed, dict) or set(parsed) != {"patches"} or not (
            isinstance(parsed["patches"], list)):
        return draft, stats, ["claim patch response had the wrong shape"]

    proposals = parsed["patches"]
    stats["proposed"] = len(proposals)
    if len(proposals) > MAX_FINDINGS:
        errors.append("more than four claim patches were proposed")
    lines = draft.splitlines()
    replacements: dict[int, str] = {}
    insertions: dict[int, list[str]] = {}
    used_findings: set[int] = set()
    used_replacement_lines: set[int] = set()

    for item in proposals[:MAX_FINDINGS]:
        if not isinstance(item, dict) or set(item) != {
                "finding", "mode", "line", "sentence"}:
            stats["rejected"] += 1
            errors.append("a claim patch had the wrong shape")
            continue
        finding = item["finding"]
        mode = item["mode"]
        line_number = item["line"]
        sentence = item["sentence"]
        if (not isinstance(finding, int) or finding in used_findings
                or finding not in allowed):
            stats["rejected"] += 1
            errors.append("a claim patch used an unknown or duplicate finding")
            continue
        if mode not in {"replace", "insert_after", "cite"}:
            stats["rejected"] += 1
            errors.append("a claim patch used an invalid mode")
            continue
        if (not isinstance(line_number, int)
                or not 1 <= line_number <= len(lines)):
            stats["rejected"] += 1
            errors.append("a claim patch targeted an invalid draft line")
            continue
        if (not isinstance(sentence, str) or not sentence.strip()
                or "\n" in sentence):
            stats["rejected"] += 1
            errors.append("a claim patch was not one nonempty line")
            continue
        sentence = " ".join(sentence.split())
        if len(sentence.split()) > MAX_PATCH_WORDS:
            stats["rejected"] += 1
            errors.append("a claim patch exceeded the word limit")
            continue
        cited = set(_citations(sentence))
        if not cited or not (cited & allowed[finding]):
            stats["rejected"] += 1
            errors.append("a claim patch lacked an allowed citation")
            continue
        original = lines[line_number - 1].strip()
        if mode in {"replace", "cite"}:
            if line_number in used_replacement_lines:
                stats["rejected"] += 1
                errors.append("two patches tried to replace the same line")
                continue
            original_citations = set(_citations(original))
            if not cited <= allowed[finding] | original_citations:
                stats["rejected"] += 1
                errors.append("a replacement used a non-authorized citation")
                continue
            if mode == "cite":
                old_plain = " ".join(
                    _CITATION_RE.sub(" ", original).split())
                new_plain = " ".join(
                    _CITATION_RE.sub(" ", sentence).split())
                if old_plain != new_plain or not original_citations <= cited:
                    stats["rejected"] += 1
                    errors.append(
                        "a citation-only patch changed its sentence")
                    continue
            else:
                old_tokens = _claim_tokens_without_citations(original)
                new_tokens = _claim_tokens_without_citations(sentence)
                retention = (
                    len(old_tokens & new_tokens) / len(old_tokens)
                    if old_tokens else 1.0
                )
                old_words = len(original.split())
                # This editor is intentionally allowed to replace a vague
                # sentence with the standard study name, acronym, figures,
                # and scoped limitation that complete the same point.  Those
                # substitutions have low surface overlap despite preserving
                # the claim; the citation and length gates remain mandatory.
                if retention < 0.20 or len(sentence.split()) < 0.75 * old_words:
                    stats["rejected"] += 1
                    errors.append("a replacement did not preserve its claim")
                    continue
            replacements[line_number] = sentence
            used_replacement_lines.add(line_number)
        else:
            if not cited <= allowed[finding]:
                stats["rejected"] += 1
                errors.append("an insertion used a non-authorized citation")
                continue
            insertions.setdefault(line_number, []).append(sentence)

        candidate: list[str] = []
        for number, line in enumerate(lines, 1):
            candidate.append(replacements.get(number, line))
            candidate.extend(insertions.get(number, []))
        if len("\n".join(candidate).split()) > MAX_REPORT_WORDS:
            replacements.pop(line_number, None)
            used_replacement_lines.discard(line_number)
            if mode == "insert_after":
                insertions[line_number].pop()
            stats["rejected"] += 1
            errors.append("a claim patch would exceed the report word cap")
            continue
        used_findings.add(finding)
        stats["accepted"] += 1

    stats["rejected"] = stats["proposed"] - stats["accepted"]
    patched: list[str] = []
    for number, line in enumerate(lines, 1):
        patched.append(replacements.get(number, line))
        patched.extend(insertions.get(number, []))
    return "\n".join(patched), stats, errors
