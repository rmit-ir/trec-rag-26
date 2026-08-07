"""Unit coverage for ``src/systems/brief_revise_agent/adjacent_pages.py`` --
round B of the sol-vs-aus_agent_v2 improvement loop (a ``search_result_augment``
closure, zero LLM calls, ported from ``aus_agent_v2/search.py``'s own
adjacent-page mechanism). ``adjacent_page_ids`` is pure id arithmetic, tested
directly without touching the network; ``augment`` additionally needs
``execute_get_documents`` to be exercised, monkeypatched here rather than
hitting a real endpoint.
"""
from __future__ import annotations

from typing import Any

from brief_revise_agent import adjacent_pages


def test_adjacent_ids_for_a_single_hit() -> None:
    assert adjacent_pages.adjacent_page_ids(["shard_1_p3"]) == [
        "shard_1_p2", "shard_1_p4"]


def test_page_one_has_no_predecessor() -> None:
    assert adjacent_pages.adjacent_page_ids(["shard_1_p1"]) == ["shard_1_p2"]


def test_already_present_neighbor_is_not_duplicated() -> None:
    """Page 4 is ALSO an original hit (a seed in its own right, so it still
    contributes its own p3/p5 candidates) -- p3 is already present and must
    not be re-listed, while p5 (genuinely new) is."""
    ids = adjacent_pages.adjacent_page_ids(["shard_1_p3", "shard_1_p4"])
    assert ids == ["shard_1_p2", "shard_1_p5"]


def test_non_paginated_ids_are_ignored() -> None:
    assert adjacent_pages.adjacent_page_ids(["shard_00459_61697"]) == []


def test_only_the_top_max_seed_hits_generate_candidates() -> None:
    ids = [f"shard_{i}_p2" for i in range(8)]
    result = adjacent_pages.adjacent_page_ids(ids, max_seed_hits=3)
    # 3 seeds x 2 candidates each (p1 and p3)
    assert len(result) == 6
    assert "shard_0_p1" in result and "shard_7_p1" not in result


def test_augment_returns_empty_with_no_paginated_hits(monkeypatch: Any) -> None:
    """No network call must happen when there is nothing page-shaped to
    expand -- proven by NOT monkeypatching execute_get_documents at all
    (an accidental real call would raise ImportError/network error here)."""
    assert adjacent_pages.augment(
        [{"id": "shard_00459_61697", "text": "x"}]) == []


def test_augment_fetches_and_tags_adjacent_documents(monkeypatch: Any) -> None:
    def fake_execute_get_documents(arguments: dict[str, Any]):
        ids = arguments["ids"]
        fetched = [{"id": i, "docid": i, "text": f"text for {i}"} for i in ids]
        return "{}", fetched, []

    monkeypatch.setattr(adjacent_pages, "execute_get_documents",
                        fake_execute_get_documents)
    result = adjacent_pages.augment([{"id": "shard_1_p3", "text": "seed"}])
    assert {d["id"] for d in result} == {"shard_1_p2", "shard_1_p4"}
    assert all(d["metadata"]["source"] == "adjacent_pages" for d in result)


def test_augment_tolerates_missing_adjacent_pages(monkeypatch: Any) -> None:
    def fake_execute_get_documents(arguments: dict[str, Any]):
        return "{}", [], list(arguments["ids"])  # everything missing

    monkeypatch.setattr(adjacent_pages, "execute_get_documents",
                        fake_execute_get_documents)
    assert adjacent_pages.augment([{"id": "shard_1_p3", "text": "seed"}]) == []
