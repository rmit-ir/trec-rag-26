"""V2 retrieval removes the model's rarely-used adjacent-page decision."""
from __future__ import annotations

import json

from aus_agent.tools.search import SearchExecution
from aus_agent_v2 import search as search_mod


def test_adjacent_ids_are_bounded_deduplicated_and_never_make_page_zero() -> None:
    """Automatic expansion must stay local even when ranked hits overlap."""
    assert search_mod.adjacent_page_ids([
        "shard_1_p1", "shard_1_p2", "shard_2_p5", "unpaged",
    ], max_seed_hits=3) == [
        "shard_1_p3", "shard_2_p4", "shard_2_p6",
    ]


def test_search_merges_fetched_neighbors_into_the_same_staged_batch(
        monkeypatch) -> None:
    """The agent should inspect adjacent text before making one commit choice."""
    base_document = {
        "id": "shard_9_p2", "docid": "shard_9", "kind": "document",
        "rank": 1, "score": 4.2, "text": "middle",
        "metadata": {},
    }
    base = SearchExecution(
        output=json.dumps({
            "query": "q",
            "results": [{
                "id": "shard_9_p2", "docid": "shard_9",
                "kind": "document", "rank": 1, "score": 4.2,
                "text": "middle",
            }],
        }),
        trace_output={
            "query": "q",
            "results": [{
                "id": "shard_9_p2", "docid": "shard_9",
                "kind": "document", "rank": 1, "score": 4.2,
            }],
        },
        returned=[{"docid": "shard_9", "score": 4.2}],
        failed=False,
        documents=[base_document],
    )
    monkeypatch.setattr(
        search_mod.base_search,
        "execute_full_text_search",
        lambda *args, **kwargs: base,
    )
    neighbor = {
        "id": "shard_9_p1", "docid": "shard_9", "kind": "document",
        "rank": 1, "score": None, "text": "opening context",
        "metadata": {"source": "get_documents"},
    }
    monkeypatch.setattr(
        search_mod.base_documents,
        "execute_get_documents",
        lambda arguments: ("{}", [neighbor], ["shard_9_p3"]),
    )

    result = search_mod.execute_full_text_search(
        {"query": "q", "search_engine": "semantic"},
        default_k=10,
        seen_docids=set(),
        engines=["semantic"],
    )
    payload = json.loads(result.output)

    assert [document["id"] for document in result.documents] == [
        "shard_9_p2", "shard_9_p1"]
    assert [item["id"] for item in payload["results"]] == [
        "shard_9_p2", "shard_9_p1"]
    assert payload["automatic_adjacent_pages"]["missing"] == ["shard_9_p3"]
    assert result.returned == [{"docid": "shard_9", "score": 4.2}]
