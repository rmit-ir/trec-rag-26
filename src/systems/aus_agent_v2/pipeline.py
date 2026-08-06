"""Public pipeline facade and architecture model for ``aus_agent_v2``."""
from __future__ import annotations

from typing import Any

from .agent import run_agent

SYSTEM_NAME = "aus_agent_v2"

# Kept literal: gen_arch_viz.py reads this module with ast, never imports it.
ARCH_STAGES = [
    {
        "id": "plan", "label": "COVERAGE PLAN", "kind": "llm",
        "note": "fresh context decomposes requested and implied coverage",
        "prompt": [
            "systems/aus_agent_v2/coverage_plan.py::COVERAGE_PLAN_SYSTEM"],
        "code": ["systems/aus_agent_v2/agent.py::run_agent"],
    },
    {
        "id": "critic", "label": "ATOMIC OBLIGATION SCOUT", "kind": "llm",
        "note": "request-only context predicts exact evaluator expectations",
        "prompt": [
            "systems/aus_agent_v2/plan_critic.py::PLAN_CRITIC_SYSTEM"],
        "code": [
            "systems/aus_agent_v2/plan_critic.py::merge_plan_critique",
            "systems/aus_agent_v2/agent.py::run_agent",
        ],
    },
    {
        "id": "research", "label": "RESEARCH LOOP", "kind": "loop",
        "note": "search, retain evidence, and draft in staged context",
        "back_to": "search", "back_from": "commit",
        "back_label": "evidence gaps",
        "prompt": ["systems/aus_agent_v2/prompts/system/default.md"],
        "code": ["systems/aus_agent_v2/agent.py::run_agent"],
        "tools": [
            {"name": "search", "ref":
             "systems/aus_agent_v2/search.py::SEARCH_TOOL_DEF"},
            {"name": "commit_context", "ref":
             "systems/aus_agent/tools/commit_context.py::COMMIT_CONTEXT_TOOL"},
        ],
        "tools_note": "reuses the stable staged-context tool protocol",
    },
    {
        "id": "search", "label": "SEARCH", "kind": "retrieval",
        "note": "ClimbMix retrieval plus automatic ±1 pages for top hits",
        "code": [
            "systems/aus_agent_v2/search.py::execute_full_text_search"],
    },
    {
        "id": "commit", "label": "COMMIT EVIDENCE", "kind": "no-llm",
        "note": "selected units persist; rejected units compact",
        "code": ["systems/aus_agent/tools/commit_context.py::apply_commit"],
    },
    {
        "id": "draft", "label": "CITED DRAFT", "kind": "llm",
        "note": "research model writes the complete answer once",
        "prompt": ["systems/aus_agent_v2/prompts/system/default.md"],
        "code": ["systems/aus_agent_v2/agent.py::run_agent"],
    },
    {
        "id": "map", "label": "VALIDATE + MAP", "kind": "format",
        "note": "deterministic parser and citation remapping",
        "code": ["systems/aus_agent_v2/agent.py::_map_citations"],
    },
    {
        "id": "save", "label": "SAVE", "kind": "artifact",
        "note": "strict trajectory plus rich organizer output",
        "code": ["ragrun/outputs.py::save_run"],
    },
]


def run_one(*, qid: str, narrative: str, run_id: str,
            run_desc: str | None = None, model_id: str | None = None,
            backend: str = "openai", **kwargs: Any) -> dict[str, Any]:
    """Run the highest-scoring fully graded v2 architecture."""
    options: dict[str, Any] = {
        "k": 20,
        "safety_max_rounds": 40,
        "coverage_plan": True,
        "plan_critic": True,
        "observable_scout": False,
        "plan_reconcile": False,
        "coverage_verify": False,
        "audience_verify": False,
        "finish_review": False,
        "answer_blueprint": False,
    }
    options.update(kwargs)
    return run_agent(
        qid,
        narrative,
        backend=backend,
        model=model_id,
        run_id=run_id,
        run_desc=run_desc,
        **options,
    )
