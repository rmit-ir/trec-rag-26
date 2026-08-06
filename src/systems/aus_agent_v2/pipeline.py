"""Public pipeline facade and architecture model for ``aus_agent_v2``."""
from __future__ import annotations

from typing import Any

from .agent import run_agent

SYSTEM_NAME = "aus_agent_v2"

# Kept literal: gen_arch_viz.py reads this module with ast, never imports it.
ARCH_STAGES = [
    {
        "id": "plan", "label": "COVERAGE PLAN", "kind": "llm",
        "note": "control uses prose; candidate emits 10-24 atomic typed rows",
        "prompt": [
            "systems/aus_agent_v2/coverage_plan.py::COVERAGE_PLAN_SYSTEM",
            "systems/aus_agent_v2/atomic_plan.py::ATOMIC_PLAN_SYSTEM",
        ],
        "code": ["systems/aus_agent_v2/agent.py::run_agent"],
        "tools": [
            {"name": "submit_atomic_plan", "ref":
             "systems/aus_agent_v2/atomic_plan.py::ATOMIC_PLAN_TOOL"},
        ],
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
        "id": "form", "label": "REQUEST FORM GATE", "kind": "no-llm",
        "note": "literal request cues authorize raw Python or repeated labels",
        "code": [
            "systems/aus_agent_v2/answer_form.py::infer_answer_form_policy",
        ],
    },
    {
        "id": "research", "label": "RESEARCH LOOP", "kind": "loop",
        "note": "route obligations through search and exact-term anchors",
        "back_to": "search", "back_from": "commit",
        "back_label": "evidence gaps",
        "prompt": [
            "systems/aus_agent_v2/prompts/system/default.md",
            "systems/aus_agent_v2/prompts/system/contract-lean.md",
        ],
        "code": ["systems/aus_agent_v2/agent.py::run_agent"],
        "tools": [
            {"name": "search", "ref":
             "systems/aus_agent_v2/search.py::SEARCH_TOOL_DEF"},
            {"name": "commit_context", "ref":
             "systems/aus_agent/tools/commit_context.py::COMMIT_CONTEXT_TOOL"},
            {"name": "submit_answer", "ref":
             "systems/aus_agent_v2/coverage_contract.py::SUBMIT_ANSWER_TOOL"},
        ],
        "tools_note": (
            "candidate adds ids, exact claims, and up to six Dxx discoveries; "
            "verified default retains the stable staged-context protocol"
        ),
    },
    {
        "id": "search", "label": "SEARCH", "kind": "retrieval",
        "note": "ClimbMix retrieval plus automatic ±1 pages for top hits",
        "code": [
            "systems/aus_agent_v2/search.py::execute_full_text_search"],
    },
    {
        "id": "commit", "label": "COMMIT EVIDENCE", "kind": "no-llm",
        "note": "exact unsliced anchors get bounded correction before expiry",
        "code": [
            "systems/aus_agent/tools/commit_context.py::apply_commit",
            "systems/aus_agent_v2/coverage_contract.py::normalize_commit_supports",
            "systems/aus_agent_v2/coverage_contract.py::normalize_commit_promotions",
        ],
    },
    {
        "id": "draft", "label": "ANSWER / TERMINAL SUBMIT", "kind": "llm",
        "note": "candidate gets mandatory evidence replay, then submits typed items",
        "prompt": [
            "systems/aus_agent_v2/prompts/system/default.md",
            "systems/aus_agent_v2/prompts/system/contract-lean.md",
        ],
        "code": [
            "systems/aus_agent_v2/agent.py::run_agent",
            "systems/aus_agent_v2/answer_form.py::render_terminal_system_addendum",
            "systems/aus_agent_v2/coverage_contract.py::validate_submission",
            "systems/aus_agent_v2/coverage_contract.py::render_terminal_evidence_handoff",
        ],
    },
    {
        "id": "semantic", "label": "SEMANTIC CLOSURE", "kind": "llm",
        "note": "fresh row-level reject-only audit; same writer gets one safe repair",
        "prompt": [
            "systems/aus_agent_v2/semantic_closure.py::SEMANTIC_CLOSURE_SYSTEM",
        ],
        "code": [
            "systems/aus_agent_v2/coverage_contract.py::build_semantic_check_records",
            "systems/aus_agent_v2/semantic_closure.py::normalize_semantic_closure",
            "systems/aus_agent_v2/semantic_closure.py::semantic_revision_errors",
            "systems/aus_agent_v2/agent.py::run_agent",
        ],
        "tools": [
            {"name": "submit_semantic_closure", "ref":
             "systems/aus_agent_v2/semantic_closure.py::SEMANTIC_CLOSURE_TOOL"},
        ],
    },
    {
        "id": "map", "label": "VALIDATE + MAP", "kind": "format",
        "note": "obligation, syntax, exact-term, and citation checks",
        "code": [
            "systems/aus_agent_v2/coverage_contract.py::validate_submission",
            "systems/aus_agent_v2/agent.py::_map_citations",
        ],
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
        "coverage_contract": False,
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


def run_contract_one(*, qid: str, narrative: str, run_id: str,
                     run_desc: str | None = None,
                     model_id: str | None = None,
                     backend: str = "openai", **kwargs: Any) -> dict[str, Any]:
    """Run the obligation/evidence-ledger candidate pending a full-30 grade."""
    options: dict[str, Any] = {
        "k": 20,
        "safety_max_rounds": 40,
        "coverage_plan": True,
        "plan_critic": True,
        "observable_scout": True,
        "plan_reconcile": False,
        "coverage_verify": False,
        "audience_verify": False,
        "finish_review": False,
        "answer_blueprint": False,
        "coverage_contract": True,
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


def run_lean_contract_one(
    *,
    qid: str,
    narrative: str,
    run_id: str,
    run_desc: str | None = None,
    model_id: str | None = None,
    backend: str = "openai",
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the executable ledger with its contradiction-free research prompt."""
    options: dict[str, Any] = {
        "k": 20,
        "safety_max_rounds": 40,
        "coverage_plan": True,
        "plan_critic": True,
        "observable_scout": True,
        "plan_reconcile": False,
        "coverage_verify": False,
        "audience_verify": False,
        "finish_review": False,
        "answer_blueprint": False,
        "coverage_contract": True,
        "prompt_variant": "contract-lean",
        "atomic_contract_plan": True,
        "dynamic_contract_rows": True,
        "terminal_evidence_handoff": True,
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


def run_semantic_contract_one(
    *,
    qid: str,
    narrative: str,
    run_id: str,
    run_desc: str | None = None,
    model_id: str | None = None,
    backend: str = "openai",
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the isolated row-semantic candidate pending a full-30 grade."""
    options: dict[str, Any] = {
        "k": 20,
        "safety_max_rounds": 40,
        "coverage_plan": True,
        "plan_critic": True,
        "observable_scout": True,
        "plan_reconcile": False,
        "coverage_verify": False,
        "audience_verify": False,
        "finish_review": False,
        "answer_blueprint": False,
        "coverage_contract": True,
        "prompt_variant": "contract-lean",
        "atomic_contract_plan": True,
        "dynamic_contract_rows": True,
        "terminal_evidence_handoff": True,
        "semantic_closure_verify": True,
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
