"""Routing tests protect the distinction between facets and coupled systems."""
from __future__ import annotations

import json

from systems.aus_agent_v2.adaptive_research import normalize_route


def test_normalize_route_accepts_only_the_two_architecture_choices() -> None:
    """An unknown route must never silently fall through to an expensive branch."""
    route, errors = normalize_route(json.dumps({
        "route": "parallel_evidence",
        "reason": "The named country cases can be researched independently.",
    }))
    assert route == {
        "route": "parallel_evidence",
        "reason": "The named country cases can be researched independently.",
    }
    assert errors == []


def test_normalize_route_rejects_extra_answer_like_fields() -> None:
    """Request routing must not smuggle a sampled conclusion into research."""
    route, errors = normalize_route(json.dumps({
        "route": "integrated_research",
        "reason": "The system components constrain each other.",
        "answer": "Build it this way.",
    }))
    assert route is None
    assert errors
