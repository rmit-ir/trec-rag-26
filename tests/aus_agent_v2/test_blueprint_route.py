"""Routing must distinguish expository handoffs from coupled technical design."""
from __future__ import annotations

import json

from systems.aus_agent_v2.blueprint_route import normalize_blueprint_route


def test_blueprint_route_accepts_only_the_named_architectures() -> None:
    """A route typo must not silently enable a costly final handoff."""
    route, errors = normalize_blueprint_route(json.dumps({
        "route": "evidence_blueprint",
        "reason": "The report has independent audience-facing deliverables.",
    }))

    assert errors == []
    assert route == {
        "route": "evidence_blueprint",
        "reason": "The report has independent audience-facing deliverables.",
    }


def test_blueprint_route_rejects_answer_content() -> None:
    """Request-only routing cannot leak a sampled conclusion into research."""
    route, errors = normalize_blueprint_route(json.dumps({
        "route": "continuous_synthesis",
        "reason": "The model components constrain one another.",
        "recommended_architecture": "Use a transformer.",
    }))

    assert route is None
    assert errors
