"""Request-only routing for the evidence-to-answer blueprint.

The low-eight paired gate showed a sharp interaction: explicit claim mapping
helped expository and applied reports, but hurt novel technical systems whose
parts must be synthesized together.  This router sees only the request and
chooses whether to insert the blueprint handoff; it never sees an answer,
rubric, retrieved document, or topic score.
"""
from __future__ import annotations

import json
from typing import Any

from .provider import ResilientOpenAIProvider


BLUEPRINT_ROUTE_SYSTEM = """\
You route research requests between two answer architectures. Inspect only the
request's intellectual shape; do not answer it or predict its factual result.

Choose evidence_blueprint when a final checklist of complete evidence-backed
claims is likely to protect explicit deliverables, audience needs, comparisons,
examples, or practical action steps. This usually includes expository reports,
historical or policy analyses, accessible multi-part articles, comparisons of
independent cases, and applied guidance for a human decision-maker.

Choose continuous_synthesis when quality depends on reasoning about one tightly
coupled novel technical object: designing a model, algorithm, engineering
architecture, experimental protocol, formal framework, or end-to-end research
system whose components constrain one another. Also choose it when the request
deliberately combines distinct scholarly domains into one compact analysis, so
a claim checklist would fragment the cross-domain synthesis.

MULTI-DOMAIN OVERRIDE: when substantial requested sections belong to different
knowledge domains, choose continuous_synthesis even if each section is
expository or could be researched separately. A report that joins an artifact
or historical subject, a scientific-method tutorial, method comparisons, and
unrelated case studies is cross-domain synthesis, not "independent cases."
Independent cases means several countries, policies, products, or examples
being compared along the same dimensions; those can use evidence_blueprint.

Do not route by length or number of requested parts alone. A long technical
system remains continuous_synthesis; a coherent but expository historical
report can use evidence_blueprint. Practical behavioral or safety guidance for
a named human audience is evidence_blueprint, not a novel technical system.

Return exactly one JSON object and no Markdown:
{"route":"evidence_blueprint|continuous_synthesis","reason":"one request-shape sentence"}
"""


def normalize_blueprint_route(text: str) -> tuple[dict[str, str] | None, list[str]]:
    """Parse only the two named routes and reject answer-like extra fields."""
    errors: list[str] = []
    try:
        value = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON: {exc.msg}"]
    if not isinstance(value, dict):
        return None, ["route result must be an object"]
    extras = set(value) - {"route", "reason"}
    if extras:
        errors.append("unexpected fields: " + ", ".join(sorted(extras)))
    route = str(value.get("route") or "").strip()
    reason = " ".join(str(value.get("reason") or "").split())
    if route not in {"evidence_blueprint", "continuous_synthesis"}:
        errors.append(f"unknown route {route!r}")
    if not reason:
        errors.append("reason is empty")
    if errors:
        return None, errors
    return {"route": route, "reason": reason}, []


def route_blueprint_request(
    query: str,
    *,
    model: str = "openai.gpt-5.6-sol",
) -> tuple[dict[str, str], dict[str, Any], int]:
    """Classify once, with one correction turn for malformed JSON only."""
    provider = ResilientOpenAIProvider(model, max_tokens=1_000)
    provider.start(BLUEPRINT_ROUTE_SYSTEM, [])
    provider.add_user_message("RESEARCH REQUEST\n" + query.strip())
    errors: list[str] = []
    for attempt in range(1, 3):
        turn = provider.run_turn()
        route, errors = normalize_blueprint_route(str(turn.get("text") or ""))
        if route is not None:
            return route, turn, attempt
        if attempt == 1:
            provider.add_user_message(
                "The route failed validation: " + "; ".join(errors)
                + ". Return the exact JSON contract now."
            )
    raise RuntimeError("invalid blueprint route: " + "; ".join(errors))
