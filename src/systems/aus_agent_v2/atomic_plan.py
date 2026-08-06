"""Candidate-only structured planner for independently closable obligations.

The legacy coverage planner emits compact prose rows that often contain many
separately scoreable requirements.  Treating each broad row as one executable
contract item makes its first supported clause close the entire bundle.  This
module defines an isolated candidate protocol whose rows are atomic before the
harness assigns stable ids.  It deliberately does not import ``ContractItem``:
the normal form is plain dictionaries so a later compiler can consume it
without introducing a planner/contract import cycle.
"""
from __future__ import annotations

import json
import re
from typing import Any


MIN_ROWS = 10
MAX_ROWS = 24
MAX_AVOID_ROWS = 4
MAX_RESPONSE_CHARS = 30_000
MAX_REQUIREMENT_CHARS = 300
MAX_REQUIREMENT_WORDS = 36
MAX_TERMS = 3
MAX_TERM_CHARS = 80
MAX_MINIMUM_COUNT = 50

ASSERT_KINDS = frozenset({
    "audience",
    "comparison",
    "definition",
    "deliverable",
    "evidence",
    "example",
    "mechanism",
    "safety",
    "scope",
    "term",
})

_ASSERT_KEYS = frozenset({
    "mode",
    "kind",
    "requirement",
    "must_mention",
    "minimum_count",
    "must_research",
    "must_answer",
})
_AVOID_KEYS = frozenset({
    "mode",
    "kind",
    "requirement",
    "must_avoid",
    "must_research",
    "must_answer",
})
_MULTI_SENTENCE_RE = re.compile(r"[.!?]\s+\S")
_INITIALISM_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")
_SERIAL_LIST_RE = re.compile(r",.+,\s*(?:and|or)\s+[^,]+$", re.IGNORECASE)
_COORDINATED_DIRECTIVE_RE = re.compile(
    r"\band\s+(?:also\s+)?(?:address|analyze|assess|compare|cover|define|"
    r"describe|distinguish|evaluate|examine|explain|identify|include|map|"
    r"recommend|report|state|verify)\b",
    re.IGNORECASE,
)


ATOMIC_PLAN_SYSTEM = """\
You are the isolated atomic planning stage of a research system. You receive
only the original request. Do not answer it, state facts, invent evidence, or
use prior knowledge as support. Return a ranked inventory of independently
checkable obligations that a single evidence/research agent can execute.

Return 10 to 24 rows total. Most rows assert something the answer must contain;
at most four rows may identify a concrete claim or behavior the answer must
avoid. Each row represents exactly one binary check. If a request names several
topics, countries, mechanisms, examples, definitions, comparisons, or repeated
parts, give each independently scoreable check its own row. Do not bundle a
serial list into one requirement and do not join separate directives with a
semicolon or a second sentence. Use `minimum_count` for a repeated requirement
that is otherwise the same check, without lowering any count in the request.

An assert row has exactly these fields:
{"mode":"assert","kind":"audience|comparison|definition|deliverable|evidence|example|mechanism|safety|scope|term","requirement":"one atomic operational check","must_mention":["literal required in the answer"],"minimum_count":1,"must_research":true,"must_answer":true}

Use `must_mention` only for a name, value, date, law, acronym, dataset, method,
or other literal whose omission changes whether the check passes. Use an empty
array otherwise. Set `must_research` false only when the original request alone
establishes the obligation, such as audience, part count, or explicitly
requested form. Every assert row has `must_answer` true.

An avoid row has exactly these fields:
{"mode":"avoid","kind":"penalty","requirement":"one atomic prohibition","must_avoid":["specific unsupported claim or behavior"],"must_research":false,"must_answer":false}

Avoid rows are constraints, never text the final answer must assert. Do not use
an avoid row for a positive caveat that should appear in the answer; make that
an assert safety or scope row instead.

Preserve requested counts, but do not authorize presentation syntax. In
particular, do not invent Markdown, headings, tables, bullets, numbering,
labels, or code. A separate deterministic request-form gate owns the few forms
it can represent safely; do not create planner rows for presentation syntax.

Keep each requirement to one sentence of at most 36 words and 300 characters.
Use at most three distinct `must_mention` or `must_avoid` strings, each at most
80 characters. `minimum_count` is an integer from 1 through 50. Rank assertions
by expected answer value per word and keep the whole inventory feasible within
the 1,024-word answer cap. Do not emit duplicate or contradictory rows.

Return JSON only, with exactly one top-level key and no Markdown fence:
{"rows":[...]}\
"""


def atomic_plan_request(query: str) -> str:
    """Give the candidate planner only the untouched research request."""
    return "ORIGINAL RESEARCH REQUEST\n\n" + query.strip()


def _compact_string(value: Any, *, maximum: int) -> str | None:
    """Normalize bounded model text without silently changing an overlong value."""
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    if not compact or len(compact) > maximum:
        return None
    return compact


def _bounded_terms(value: Any) -> list[str] | None:
    """Normalize a short literal list, rejecting overflow or non-string members."""
    if not isinstance(value, list) or len(value) > MAX_TERMS:
        return None
    clean: list[str] = []
    fingerprints: set[str] = set()
    for raw in value:
        term = _compact_string(raw, maximum=MAX_TERM_CHARS)
        if term is None:
            return None
        fingerprint = term.casefold()
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        clean.append(term)
    return clean


def _atomic_requirement(value: Any) -> str | None:
    """Reject obvious multi-clause rows while leaving semantic checks to planning."""
    requirement = _compact_string(value, maximum=MAX_REQUIREMENT_CHARS)
    if requirement is None or len(requirement.split()) > MAX_REQUIREMENT_WORDS:
        return None
    sentence_probe = _INITIALISM_RE.sub(
        lambda match: match.group(0).replace(".", ""), requirement)
    if (
        ";" in requirement
        or _MULTI_SENTENCE_RE.search(sentence_probe)
        or _SERIAL_LIST_RE.search(requirement)
        or _COORDINATED_DIRECTIVE_RE.search(requirement)
    ):
        return None
    return requirement


def _normalize_assert(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Validate one positive obligation without importing the contract layer."""
    if set(raw) != _ASSERT_KEYS:
        return None
    kind = raw.get("kind")
    requirement = _atomic_requirement(raw.get("requirement"))
    must_mention = _bounded_terms(raw.get("must_mention"))
    minimum_count = raw.get("minimum_count")
    if (
        raw.get("mode") != "assert"
        or kind not in ASSERT_KINDS
        or requirement is None
        or must_mention is None
        or type(minimum_count) is not int
        or not 1 <= minimum_count <= MAX_MINIMUM_COUNT
        or type(raw.get("must_research")) is not bool
        or raw.get("must_answer") is not True
    ):
        return None
    return {
        "mode": "assert",
        "kind": kind,
        "requirement": requirement,
        "must_mention": must_mention,
        "minimum_count": minimum_count,
        "must_research": raw["must_research"],
        "must_answer": True,
    }


def _normalize_avoid(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Validate one negative constraint that never demands answer prose."""
    if set(raw) != _AVOID_KEYS:
        return None
    requirement = _atomic_requirement(raw.get("requirement"))
    must_avoid = _bounded_terms(raw.get("must_avoid"))
    if (
        raw.get("mode") != "avoid"
        or raw.get("kind") != "penalty"
        or requirement is None
        or not must_avoid
        or raw.get("must_research") is not False
        or raw.get("must_answer") is not False
    ):
        return None
    return {
        "mode": "avoid",
        "kind": "penalty",
        "requirement": requirement,
        "must_avoid": must_avoid,
        "must_research": False,
        "must_answer": False,
    }


def normalize_atomic_plan(text: str | None) -> list[dict[str, Any]]:
    """Return a complete bounded inventory, or ``[]`` if any invariant fails.

    Validation is intentionally all-or-nothing. Silently dropping an invalid or
    overflowing row would recreate the coverage loss this candidate is meant to
    prevent. Exact duplicate requirements are collapsed before the final
    10-row minimum is checked.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    raw_text = text.strip()
    if len(raw_text) > MAX_RESPONSE_CHARS:
        return []
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict) or set(parsed) != {"rows"}:
        return []
    raw_rows = parsed.get("rows")
    if (
        not isinstance(raw_rows, list)
        or not MIN_ROWS <= len(raw_rows) <= MAX_ROWS
    ):
        return []

    clean: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    avoid_rows = 0
    for raw in raw_rows:
        if not isinstance(raw, dict):
            return []
        mode = raw.get("mode")
        if mode == "assert":
            row = _normalize_assert(raw)
        elif mode == "avoid":
            row = _normalize_avoid(raw)
            avoid_rows += 1
        else:
            return []
        if row is None or avoid_rows > MAX_AVOID_ROWS:
            return []
        fingerprint = row["requirement"].casefold()
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        clean.append(row)
    if len(clean) < MIN_ROWS:
        return []
    return clean
