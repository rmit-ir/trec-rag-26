"""Contracts for facet handoffs, where one malformed child can poison synthesis."""
from __future__ import annotations

import json

from systems.aus_agent_v2.facet_research import (
    facet_from_query,
    facet_query,
    memo_from_output,
    normalize_facets,
    synthesis_packet,
)


def _facets() -> list[dict]:
    return [
        {
            "name": f"Facet {index}",
            "brief": f"Research evidence area {index} without overlap.",
            "must_cover": [f"requirement {index}a", f"requirement {index}b"],
        }
        for index in range(1, 4)
    ]


def test_normalize_facets_requires_exact_three_way_contract() -> None:
    """Launching two or four expensive children would invalidate paired runs."""
    valid = json.dumps({"facets": _facets()})
    facets, errors = normalize_facets(valid)
    assert facets == _facets()
    assert errors == []

    malformed = json.dumps({"facets": _facets()[:2]})
    facets, errors = normalize_facets(malformed)
    assert facets == []
    assert errors == ["decomposition must contain exactly three facets"]


def test_memo_from_output_restores_reference_ids() -> None:
    """The final writer needs docids, not child-local citation indices."""
    memo, refs = memo_from_output({
        "references": ["shard_a", "shard_b"],
        "answer": [
            {"text": "First finding.", "citations": [1, 0]},
            {"text": "Proposed example.", "citations": []},
        ],
    })
    assert memo == "First finding. [shard_b] [shard_a]\nProposed example."
    assert refs == {"shard_a", "shard_b"}


def test_facet_query_keeps_child_on_assigned_evidence() -> None:
    """A child that answers the whole request merely triples duplicate search."""
    query = facet_query("Compare alpha and beta.", _facets()[0], 1)
    assert "Overall user request (context only)" in query
    assert "Assigned facet 1 — Facet 1" in query
    assert "Do not attempt the full overall deliverable" in query


def test_facet_query_round_trips_exact_assignment() -> None:
    """Parent-only retries must not relabel cached evidence after re-sampling."""
    facet = _facets()[1]
    query = facet_query("Compare alpha and beta.", facet, 2)
    assert facet_from_query(query) == facet


def test_synthesis_packet_pairs_each_assignment_and_memo() -> None:
    """Facet identity must survive the context boundary into final synthesis."""
    packet = synthesis_packet("Original request.", _facets(), ["A", "B", "C"])
    assert packet.startswith("ORIGINAL REQUEST\nOriginal request.")
    assert packet.count("CITED EVIDENCE MEMO") == 3
    assert "FACET 2 — Facet 2" in packet
    assert packet.endswith("CITED EVIDENCE MEMO\nC")
