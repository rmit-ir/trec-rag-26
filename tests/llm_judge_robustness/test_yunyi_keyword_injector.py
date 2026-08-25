"""The combined injector must preserve both perturbations in the intended order."""
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

from yunyi_keyword_injector import inject_yunyi_keywords  # noqa: E402


def test_keywords_are_dispersed_before_yunyi_text() -> None:
    """Appending Yun Yi last keeps its adversarial instruction block intact."""
    passage = " ".join(f"word{index}" for index in range(20))
    keywords = ["alpha", "multi word phrase", "omega"]
    yunyi_text = "\n  YUN YI INSTRUCTION  \n"

    injected = inject_yunyi_keywords(
        passage, "query\0passage", keywords, yunyi_text
    )

    assert injected.endswith("YUN YI INSTRUCTION")
    prefix = injected.removesuffix(" YUN YI INSTRUCTION")
    for keyword in keywords:
        assert prefix.count(keyword.upper()) == 1
    assert prefix.split()[0] == "word0"
    assert prefix.split()[-1] == "word19"


def test_combined_injection_is_reproducible() -> None:
    """Stable placement permits exact rebuilds of the combined experiment."""
    passage = " ".join(f"word{index}" for index in range(50))
    keywords = ["alpha", "beta", "gamma"]

    first = inject_yunyi_keywords(passage, "query\0passage", keywords, "YUN YI")
    repeated = inject_yunyi_keywords(
        passage, "query\0passage", keywords, "YUN YI"
    )

    assert first == repeated


def test_empty_yunyi_text_is_rejected() -> None:
    """A keywords-only output would silently invalidate the combined condition."""
    try:
        inject_yunyi_keywords("passage words", "query\0passage", ["alpha"], "  ")
    except ValueError as error:
        assert str(error) == "Yun Yi injection text must not be empty"
    else:
        raise AssertionError("empty Yun Yi text was accepted")
