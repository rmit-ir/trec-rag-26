"""Keyword injection must disperse phrases without adding an artificial wrapper."""
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

from inject_keywords import inject_keywords  # noqa: E402


def test_keywords_are_inserted_individually_at_distinct_internal_boundaries() -> None:
    """A wrapper or one contiguous block would not model dispersed term stuffing."""
    passage_words = [f"word{index}" for index in range(20)]
    keywords = ["adults", "age", "begin losing bone mass", "bone mass loss onset"]

    injected = inject_keywords(" ".join(passage_words), "query\0passage", keywords)

    assert "[KEYWORDS:" not in injected
    for keyword in keywords:
        assert injected.count(keyword) == 1
    sentinel_keywords = [f"KEYWORD_SENTINEL_{index}" for index in range(4)]
    sentinel_injected = inject_keywords(
        " ".join(passage_words), "query\0passage", sentinel_keywords
    )
    remaining = [
        word for word in sentinel_injected.split() if not word.startswith("KEYWORD_SENTINEL_")
    ]
    assert remaining == passage_words
    keyword_positions = [
        index
        for index, word in enumerate(sentinel_injected.split())
        if word.startswith("KEYWORD_SENTINEL_")
    ]
    assert len(set(keyword_positions)) == len(sentinel_keywords)
    assert min(keyword_positions) > 0
    assert max(keyword_positions) < len(sentinel_injected.split()) - 1


def test_injection_is_reproducible_but_varies_by_passage() -> None:
    """Stable per-passage placement makes rebuilds exact without cloning positions."""
    passage = " ".join(f"word{index}" for index in range(100))
    keywords = ["alpha", "beta", "gamma", "delta", "epsilon"]

    first = inject_keywords(passage, "query\0passage-a", keywords)
    repeated = inject_keywords(passage, "query\0passage-a", keywords)
    other_passage = inject_keywords(passage, "query\0passage-b", keywords)

    assert first == repeated
    assert first != other_passage


def test_short_passages_still_receive_every_keyword_without_markup() -> None:
    """Degenerate passages must retain every generated phrase rather than dropping some."""
    injected = inject_keywords("single", "query\0passage", ["alpha", "beta"])

    assert injected == "single alpha beta"
    assert "[" not in injected
