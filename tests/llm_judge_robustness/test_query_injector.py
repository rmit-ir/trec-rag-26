"""Query injection must append the row's query without altering its wording."""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / "tasks"
    / "llm_judge_robustness"
    / "scripts"
)
sys.path.insert(0, str(SCRIPT_DIR))

from query_injector import inject_query  # noqa: E402


def test_query_is_appended_at_the_end_of_the_passage() -> None:
    """The condition specifically tests a complete query placed after all passage text."""
    injected = inject_query(
        "  Passage text with   spacing.  ",
        "  what is the answer?  ",
    )

    assert injected == "Passage text with spacing. what is the answer?"
    assert injected.endswith("what is the answer?")


def test_query_case_and_punctuation_are_preserved() -> None:
    """Changing query form would confound placement with a second perturbation."""
    query = "Who Was Ada Lovelace?"

    assert inject_query("A short passage.", query) == f"A short passage. {query}"


def test_empty_query_is_rejected() -> None:
    """Silently emitting an uninjected row would invalidate condition coverage."""
    try:
        inject_query("passage", "  \n ")
    except ValueError as error:
        assert str(error) == "query text must not be empty"
    else:
        raise AssertionError("empty query text was accepted")
