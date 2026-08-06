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
_TOOL_KEYS = frozenset({
    "mode",
    "kind",
    "requirement",
    "must_mention",
    "must_avoid",
    "minimum_count",
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
{"mode":"assert","kind":"audience|comparison|definition|deliverable|evidence|example|mechanism|safety|scope|term","requirement":"one atomic operational check","must_mention":["literal required in the answer"],"must_avoid":[],"minimum_count":1,"must_research":true,"must_answer":true}

Use `must_mention` only for a name, value, date, law, acronym, dataset, method,
or other literal whose omission changes whether the check passes. Use an empty
array otherwise. Set `must_research` false only when the original request alone
establishes the obligation, such as audience, part count, or explicitly
requested form. Every assert row has `must_answer` true.

An avoid row has exactly these fields:
{"mode":"avoid","kind":"penalty","requirement":"one atomic prohibition","must_mention":[],"must_avoid":["specific unsupported claim or behavior"],"minimum_count":1,"must_research":false,"must_answer":false}

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

Call `submit_atomic_plan` exactly once. Do not write prose or raw JSON outside
the tool call. The tool uses one common row shape: assert rows set
`must_avoid` to `[]`; avoid rows set `must_mention` to `[]` and
`minimum_count` to `1`.\
"""


ATOMIC_PLAN_TOOL: dict[str, Any] = {
    "name": "submit_atomic_plan",
    "description": (
        "Submit the complete ranked atomic obligation inventory. This is the "
        "only valid response from the planning stage."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "minItems": MIN_ROWS,
                "maxItems": MAX_ROWS,
                "items": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string", "enum": ["assert", "avoid"],
                        },
                        "kind": {
                            "type": "string",
                            "enum": sorted((*ASSERT_KINDS, "penalty")),
                        },
                        "requirement": {
                            "type": "string",
                            "maxLength": MAX_REQUIREMENT_CHARS,
                        },
                        "must_mention": {
                            "type": "array",
                            "maxItems": MAX_TERMS,
                            "items": {
                                "type": "string", "maxLength": MAX_TERM_CHARS,
                            },
                        },
                        "must_avoid": {
                            "type": "array",
                            "maxItems": MAX_TERMS,
                            "items": {
                                "type": "string", "maxLength": MAX_TERM_CHARS,
                            },
                        },
                        "minimum_count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_MINIMUM_COUNT,
                        },
                        "must_research": {"type": "boolean"},
                        "must_answer": {"type": "boolean"},
                    },
                    "required": sorted(_TOOL_KEYS),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["rows"],
        "additionalProperties": False,
    },
}


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


def _compact_tool_row(
    raw: dict[str, Any],
    index: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Project the common tool shape into the mode-specific normal form."""
    if set(raw) != _TOOL_KEYS:
        return None, [
            f"row {index} fields differ from the tool schema"
        ]
    mode = raw.get("mode")
    if mode == "assert":
        if raw.get("must_avoid") != []:
            return None, [f"row {index} assert must_avoid must be empty"]
        return {key: raw[key] for key in _ASSERT_KEYS}, []
    if mode == "avoid":
        problems: list[str] = []
        if raw.get("must_mention") != []:
            problems.append(f"row {index} avoid must_mention must be empty")
        if raw.get("minimum_count") != 1:
            problems.append(f"row {index} avoid minimum_count must be 1")
        if problems:
            return None, problems
        return {key: raw[key] for key in _AVOID_KEYS}, []
    return None, [f"row {index} mode must be assert or avoid"]


def _diagnose_mode_row(raw: dict[str, Any], index: int) -> list[str]:
    """Explain a rejected mode-specific row precisely enough for correction."""
    mode = raw.get("mode")
    expected = _ASSERT_KEYS if mode == "assert" else _AVOID_KEYS
    problems: list[str] = []
    if set(raw) != expected:
        problems.append(
            f"row {index} has incorrect fields for mode {mode!r}")
    if mode == "assert":
        if raw.get("kind") not in ASSERT_KINDS:
            problems.append(f"row {index} has invalid assert kind")
        if _atomic_requirement(raw.get("requirement")) is None:
            problems.append(
                f"row {index} requirement is overlong or visibly compound")
        if _bounded_terms(raw.get("must_mention")) is None:
            problems.append(f"row {index} must_mention is invalid")
        minimum_count = raw.get("minimum_count")
        if (type(minimum_count) is not int
                or not 1 <= minimum_count <= MAX_MINIMUM_COUNT):
            problems.append(f"row {index} minimum_count is invalid")
        if type(raw.get("must_research")) is not bool:
            problems.append(f"row {index} must_research must be boolean")
        if raw.get("must_answer") is not True:
            problems.append(f"row {index} assert must_answer must be true")
    elif mode == "avoid":
        if raw.get("kind") != "penalty":
            problems.append(f"row {index} avoid kind must be penalty")
        if _atomic_requirement(raw.get("requirement")) is None:
            problems.append(
                f"row {index} requirement is overlong or visibly compound")
        if not _bounded_terms(raw.get("must_avoid")):
            problems.append(f"row {index} must_avoid needs 1-3 literals")
        if raw.get("must_research") is not False:
            problems.append(f"row {index} avoid must_research must be false")
        if raw.get("must_answer") is not False:
            problems.append(f"row {index} avoid must_answer must be false")
    else:
        problems.append(f"row {index} mode must be assert or avoid")
    return problems or [f"row {index} violates an atomic-plan invariant"]


def _normalize_atomic_plan_value(
    value: Any,
    *,
    require_tool_shape: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate one inventory with optional legacy mode-specific row support."""
    if require_tool_shape and isinstance(value, str):
        return [], [
            "tool arguments must be an object, not encoded JSON text"]
    if isinstance(value, str):
        raw_text = value.strip()
        if not raw_text:
            return [], ["planner response is empty"]
        if len(raw_text) > MAX_RESPONSE_CHARS:
            return [], [
                f"planner response exceeds {MAX_RESPONSE_CHARS} characters"]
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return [], [f"planner response is not valid JSON: {exc.msg}"]
    else:
        parsed = value
    if not isinstance(parsed, dict) or set(parsed) != {"rows"}:
        return [], ["planner output must contain exactly one rows field"]
    raw_rows = parsed.get("rows")
    if not isinstance(raw_rows, list):
        return [], ["rows must be an array"]
    if not MIN_ROWS <= len(raw_rows) <= MAX_ROWS:
        return [], [
            f"rows must contain {MIN_ROWS} through {MAX_ROWS} items; found "
            f"{len(raw_rows)}"
        ]

    clean: list[dict[str, Any]] = []
    fingerprints: dict[str, int] = {}
    avoid_rows = 0
    errors: list[str] = []
    for index, raw_value in enumerate(raw_rows, 1):
        if not isinstance(raw_value, dict):
            errors.append(f"row {index} is not an object")
            continue
        raw = raw_value
        if set(raw) == _TOOL_KEYS:
            compact, compact_errors = _compact_tool_row(raw, index)
            if compact_errors:
                errors.extend(compact_errors)
                continue
            assert compact is not None
            raw = compact
        elif require_tool_shape:
            errors.append(
                f"row {index} fields differ from the tool schema")
            continue
        mode = raw.get("mode")
        if mode == "assert":
            row = _normalize_assert(raw)
        elif mode == "avoid":
            row = _normalize_avoid(raw)
            avoid_rows += 1
        else:
            row = None
        if row is None:
            errors.extend(_diagnose_mode_row(raw, index))
            continue
        if avoid_rows > MAX_AVOID_ROWS:
            errors.append(
                f"rows contain more than {MAX_AVOID_ROWS} avoidance constraints")
            continue
        fingerprint = row["requirement"].casefold()
        if fingerprint in fingerprints:
            errors.append(
                f"row {index} duplicates the requirement in row "
                f"{fingerprints[fingerprint]}")
            continue
        fingerprints[fingerprint] = index
        clean.append(row)
    if errors:
        return [], errors
    if len(clean) < MIN_ROWS:
        return [], [
            f"only {len(clean)} distinct rows remain after de-duplication; "
            f"minimum is {MIN_ROWS}"
        ]
    return clean, []


def normalize_atomic_plan_value(
    value: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate common-shape tool arguments with all-or-nothing diagnostics."""
    return _normalize_atomic_plan_value(value, require_tool_shape=True)


def normalize_atomic_plan(text: str | None) -> list[dict[str, Any]]:
    """Parse the pre-tool mode-specific JSON protocol for frozen audit inputs."""
    rows, _ = _normalize_atomic_plan_value(text, require_tool_shape=False)
    return rows
