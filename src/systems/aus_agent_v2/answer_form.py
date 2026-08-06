"""Request-conditioned answer forms for the executable terminal path.

The public RAG artifact stores an ordered list of opaque text units.  That is
enough for runnable source code and visible part labels, provided the harness
does not send those units through the ordinary prose/Markdown cleaner.  This
module grants only the narrow forms the original request itself authorizes;
it is not a general Markdown switch.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


_PYTHON_CODE_RE = re.compile(
    r"(?:\b(?:include|provide|show|write)\b[^.\n]{0,80}\bpython\s+code\b)"
    r"|(?:\bpython\s+(?:code|implementation|script)\b)"
    r"|(?:\bimplement\b[^.\n]{0,80}\bin\s+python\b)",
    re.IGNORECASE,
)
_BLOG_SERIES_RE = re.compile(
    r"\bseries\s+of\s+(?:blog\s+)?posts\b", re.IGNORECASE)
_BLOG_COUNT_RE = re.compile(
    r"\b(?:series\s+of\s+)?"
    r"(?P<count>\d+|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:blog\s+)?posts\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass(frozen=True)
class AnswerFormPolicy:
    """Forms authorized by literal cues in the original user request."""

    python_code: bool = False
    repeated_label: str = ""
    minimum_labels: int = 0

    def trace(self) -> dict[str, Any]:
        """Return a JSON-safe record of the harness decision."""
        return asdict(self)


def infer_answer_form_policy(query: str) -> AnswerFormPolicy:
    """Infer only narrow, directly requested forms from the untouched query."""
    python_code = bool(_PYTHON_CODE_RE.search(query))
    count_match = _BLOG_COUNT_RE.search(query)
    if _BLOG_SERIES_RE.search(query) or count_match:
        count_text = count_match.group("count").casefold() if count_match else ""
        requested_count = (
            int(count_text) if count_text.isdigit()
            else _NUMBER_WORDS.get(count_text, 3)
        )
        return AnswerFormPolicy(
            python_code=python_code,
            repeated_label="Blog post",
            minimum_labels=max(3, requested_count),
        )
    return AnswerFormPolicy(python_code=python_code)


def render_terminal_system_addendum(policy: AnswerFormPolicy) -> str:
    """Override the legacy free-prose ending only for contract candidates."""
    lines = [
        "## Executable terminal answer",
        "For this architecture, the submit_answer tool replaces the final "
        "free-prose turn described above. Put citations only in each answer "
        "item's evidence_ids field; do not write citation markers in text.",
        "A label item may be used only for a request-authorized repeated "
        "deliverable. This does not authorize Markdown headings, bullets, "
        "tables, bold text, or other presentational syntax.",
    ]
    if policy.python_code:
        lines.append(
            "The original request explicitly requires Python. Put raw, "
            "complete, multiline Python in a code item without Markdown "
            "fences. Its indentation, operators, and bracket expressions are "
            "preserved and compiled for syntax before acceptance. Explain "
            "source-grounded design claims in adjacent cited prose items; "
            "generated code itself may be uncited."
        )
    else:
        lines.append(
            "The original request does not authorize a code item; use prose "
            "and any request-authorized labels only."
        )
    return "\n\n".join((lines[0], "\n".join(lines[1:])))
