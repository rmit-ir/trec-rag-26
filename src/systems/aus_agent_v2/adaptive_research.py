"""Request-shape routing between integrated and parallel research loops."""
from __future__ import annotations

import json
from typing import Any, Callable

from .agent import run_agent
from .facet_research import run_parallel_facets
from .provider import ResilientOpenAIProvider


ADAPTIVE_ROUTE_SYSTEM = """\
You route one research request to the architecture that best preserves its
dependencies. Choose exactly one route.

parallel_evidence: Use when the request has repeated deliverables, several
independent named cases to compare, or complementary evidence domains that can
be researched separately and synthesized only at the end. Examples include a
series of posts, comparisons across countries or products, or a report with
separable empirical, policy, and consequence strands.

integrated_research: Use when the request asks for one tightly coupled design,
framework, protocol, workflow, implementation, or experimental plan whose
components constrain each other and must be reasoned about end-to-end. Also use
it when the request is substantially one question rather than independent
evidence strands.

Route by dependency structure, not by topic or difficulty. The mere presence
of several requirements does not justify parallel_evidence when they are parts
of one coupled system. Return JSON only:
{"route":"parallel_evidence","reason":"one sentence about dependency structure"}
"""


def normalize_route(text: str | None) -> tuple[dict[str, str] | None, list[str]]:
    """Fail closed when a sampled route cannot be audited."""
    try:
        parsed = json.loads((text or "").strip())
    except (TypeError, json.JSONDecodeError):
        return None, ["route was not bare JSON"]
    if not isinstance(parsed, dict) or set(parsed) != {"route", "reason"}:
        return None, ["route has the wrong shape"]
    if parsed["route"] not in {"parallel_evidence", "integrated_research"}:
        return None, ["unknown route"]
    reason = " ".join(str(parsed["reason"]).split())
    if not 3 <= len(reason.split()) <= 80:
        return None, ["route reason is empty or too long"]
    return {"route": parsed["route"], "reason": reason}, []


def route_request(
    query: str,
    *,
    model: str = "openai.gpt-5.6-sol",
    provider_factory: Callable[..., Any] = ResilientOpenAIProvider,
) -> tuple[dict[str, str], dict[str, Any], int]:
    """Classify dependency shape in an isolated request-only context."""
    provider = provider_factory(model, max_tokens=1_500)
    provider.start(ADAPTIVE_ROUTE_SYSTEM, [])
    provider.add_user_message("ORIGINAL REQUEST\n\n" + query.strip())
    errors: list[str] = []
    turn: dict[str, Any] = {}
    for attempt in range(1, 3):
        turn = provider.run_turn()
        route, errors = normalize_route(turn.get("text"))
        if route is not None:
            return route, turn, attempt
        if attempt == 1:
            provider.add_user_message(
                "The route failed validation: " + "; ".join(errors)
                + ". Return the exact JSON contract now."
            )
    raise RuntimeError("invalid adaptive route: " + "; ".join(errors))


def run_adaptive_research(
    qid: str,
    query: str,
    *,
    run_id: str,
    model: str = "openai.gpt-5.6-sol",
    k: int = 20,
    context_token_budget: int = 500_000,
    safety_max_rounds: int = 40,
    route_override: str | None = None,
) -> dict[str, Any]:
    """Route by request shape, then run the corresponding complete system."""
    if route_override is None:
        route, route_turn, route_attempts = route_request(query, model=model)
    else:
        route, errors = normalize_route(json.dumps({
            "route": route_override,
            "reason": "Frozen from the persisted request-only routing audit.",
        }))
        if route is None:
            raise ValueError("invalid route_override: " + "; ".join(errors))
        route_turn, route_attempts = {"text": json.dumps(route)}, 0
    if route["route"] == "parallel_evidence":
        summary = run_parallel_facets(
            qid,
            query,
            run_id=run_id,
            model=model,
            k=k,
            child_context_token_budget=min(context_token_budget, 220_000),
            child_safety_max_rounds=safety_max_rounds,
        )
    else:
        summary = run_agent(
            qid,
            query,
            backend="openai",
            model=model,
            k=k,
            context_token_budget=context_token_budget,
            safety_max_rounds=safety_max_rounds,
            run_id=run_id,
            run_desc="Adaptive integrated research with request-only planning.",
            coverage_plan=True,
            plan_critic=True,
            observable_scout=False,
            plan_reconcile=False,
            coverage_verify=False,
            audience_verify=False,
            finish_review=False,
        )
    return {
        **summary,
        "adaptive_route": route,
        "route_attempts": route_attempts,
        "route_turn": route_turn,
    }
