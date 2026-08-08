"""Public pipeline facade and architecture model for ``aus_agent_v2``."""
from __future__ import annotations

from typing import Any, Callable

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run

from .agent import make_provider, run_agent
from .candidate_union import candidate_union_usage, select_candidate_union

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
             "agent_harness/tools/commit_context.py::COMMIT_CONTEXT_TOOL"},
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
            "agent_harness/tools/commit_context.py::apply_commit",
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
        "id": "union", "label": "EXTRACTIVE CANDIDATE UNION", "kind": "llm",
        "note": "optional complete-answer union selects immutable cited items",
        "prompt": [
            "systems/aus_agent_v2/candidate_union.py::CANDIDATE_UNION_SYSTEM",
        ],
        "code": [
            "systems/aus_agent_v2/candidate_union.py::select_candidate_union",
            "systems/aus_agent_v2/candidate_union.py::normalize_candidate_union",
            "systems/aus_agent_v2/pipeline.py::run_candidate_union_one",
        ],
        "tools": [
            {"name": "submit_candidate_union", "ref":
             "systems/aus_agent_v2/candidate_union.py::CANDIDATE_UNION_TOOL"},
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

# Kept literal: gen_arch_viz.py reads this module with ast, never imports it.
# Each path is mutually exclusive at runtime. Keeping the shared stage catalog
# above and declaring variant-specific labels/prompts/tools here prevents the
# architecture page from drawing candidate-only gates as if the verified
# submission control always executed them.
ARCH_VARIANTS = [
    {
        "id": "verified",
        "label": "Verified research-first control",
        "status": "VERIFIED · dev30 0.704159",
        "tone": "verified",
        "default": True,
        "input": "original request",
        "entrypoint": "systems/aus_agent_v2/pipeline.py::run_one",
        "note": (
            "Promoted research-first configuration: prose plan, blind atomic "
            "scout, one evidence-owning research conversation, and no editor."
        ),
        "path": [
            "plan", "critic", "form", "research", "search", "commit",
            "draft", "map", "save",
        ],
        "stage_overrides": {
            "plan": {
                "label": "PROSE COVERAGE PLAN",
                "note": "isolated request decomposition; no typed contract",
                "prompt": [
                    "systems/aus_agent_v2/coverage_plan.py::COVERAGE_PLAN_SYSTEM",
                ],
                "tools": [],
            },
            "critic": {
                "label": "ATOMIC OBLIGATION SCOUT",
                "note": "request-only blind scout; retain at most 8 additions",
                "prompt": [
                    "systems/aus_agent_v2/plan_critic.py::PLAN_CRITIC_SYSTEM",
                ],
                "code": [
                    "systems/aus_agent_v2/plan_critic.py::merge_plan_critique",
                    "systems/aus_agent_v2/agent.py::run_agent",
                ],
            },
            "research": {
                "label": "INTEGRATED RESEARCH LOOP",
                "note": "same conversation searches, commits, and writes",
                "prompt": [
                    "systems/aus_agent_v2/prompts/system/default.md",
                ],
                "tools": [
                    {"name": "search", "ref":
                     "systems/aus_agent_v2/search.py::SEARCH_TOOL_DEF"},
                    {"name": "commit_context", "ref":
                     "agent_harness/tools/commit_context.py::COMMIT_CONTEXT_TOOL"},
                ],
                "tools_note": (
                    "semantic + keyword retrieval; top five paginated hits "
                    "also stage their immediate adjacent pages"
                ),
            },
            "commit": {
                "label": "COMMIT SELECTED EVIDENCE",
                "note": "keep up to 10 useful pages from the staged batch",
                "code": [
                    "agent_harness/tools/commit_context.py::apply_commit",
                ],
            },
            "draft": {
                "label": "FINAL CITED PROSE",
                "note": "direct answer from the research conversation; no editor",
                "prompt": [
                    "systems/aus_agent_v2/prompts/system/default.md",
                ],
                "code": [
                    "systems/aus_agent_v2/agent.py::run_agent",
                ],
            },
            "map": {
                "label": "MAP CITATIONS",
                "note": "document ids become organizer reference indices",
                "code": [
                    "systems/aus_agent_v2/agent.py::_map_citations",
                ],
            },
        },
    },
    {
        "id": "lean",
        "label": "Lean atomic ledger",
        "status": "IMPLEMENTED · UNGRADED",
        "tone": "candidate",
        "input": "original request",
        "entrypoint": "systems/aus_agent_v2/pipeline.py::run_lean_contract_one",
        "note": (
            "Fresh-generation candidate with typed atomic obligations, dynamic "
            "source-backed rows, and a mandatory evidence handoff."
        ),
        "path": [
            "plan", "critic", "form", "research", "search", "commit",
            "draft", "map", "save",
        ],
        "stage_overrides": {
            "plan": {
                "label": "ATOMIC CONTRACT PLAN",
                "note": "typed 10–24 row executable obligation inventory",
                "prompt": [
                    "systems/aus_agent_v2/atomic_plan.py::ATOMIC_PLAN_SYSTEM",
                ],
            },
            "critic": {
                "label": "DUAL OBLIGATION SCOUTS",
                "note": "blind expectation scout plus observable/count scout",
                "prompt": [
                    "systems/aus_agent_v2/plan_critic.py::PLAN_CRITIC_SYSTEM",
                    "systems/aus_agent_v2/observable_scout.py::OBSERVABLE_SCOUT_SYSTEM",
                ],
                "code": [
                    "systems/aus_agent_v2/plan_critic.py::merge_plan_critique",
                    "systems/aus_agent_v2/observable_scout.py::combine_obligation_audits",
                    "systems/aus_agent_v2/agent.py::run_agent",
                ],
            },
            "research": {
                "label": "CONTRACT RESEARCH LOOP",
                "note": "search and commit against stable P/S/D obligation ids",
                "prompt": [
                    "systems/aus_agent_v2/prompts/system/contract-lean.md",
                ],
            },
            "commit": {
                "label": "COMMIT + PROMOTE ROWS",
                "note": "source-local claim/scope anchors; up to six Dxx rows",
            },
            "draft": {
                "label": "HANDOFF + TERMINAL SUBMIT",
                "note": "complete evidence replay, then one typed final answer",
                "prompt": [
                    "systems/aus_agent_v2/prompts/system/contract-lean.md",
                ],
            },
        },
    },
    {
        "id": "semantic",
        "label": "Semantic finish-the-claim",
        "status": "IMPLEMENTED · UNGRADED",
        "tone": "candidate",
        "input": "original request",
        "entrypoint": "systems/aus_agent_v2/pipeline.py::run_semantic_contract_one",
        "note": (
            "Lean atomic ledger followed by a fresh reject-only row audit and "
            "one preservation-safe text correction."
        ),
        "path": [
            "plan", "critic", "form", "research", "search", "commit",
            "draft", "semantic", "map", "save",
        ],
        "stage_overrides": {
            "plan": {
                "label": "ATOMIC CONTRACT PLAN",
                "note": "typed 10–24 row executable obligation inventory",
                "prompt": [
                    "systems/aus_agent_v2/atomic_plan.py::ATOMIC_PLAN_SYSTEM",
                ],
            },
            "critic": {
                "label": "DUAL OBLIGATION SCOUTS",
                "note": "blind expectation scout plus observable/count scout",
                "prompt": [
                    "systems/aus_agent_v2/plan_critic.py::PLAN_CRITIC_SYSTEM",
                    "systems/aus_agent_v2/observable_scout.py::OBSERVABLE_SCOUT_SYSTEM",
                ],
                "code": [
                    "systems/aus_agent_v2/plan_critic.py::merge_plan_critique",
                    "systems/aus_agent_v2/observable_scout.py::combine_obligation_audits",
                    "systems/aus_agent_v2/agent.py::run_agent",
                ],
            },
            "research": {
                "label": "CONTRACT RESEARCH LOOP",
                "note": "search and commit against stable P/S/D obligation ids",
                "prompt": [
                    "systems/aus_agent_v2/prompts/system/contract-lean.md",
                ],
            },
            "commit": {
                "label": "COMMIT + PROMOTE ROWS",
                "note": "source-local claim/scope anchors; up to six Dxx rows",
            },
            "draft": {
                "label": "HANDOFF + TERMINAL SUBMIT",
                "note": "complete evidence replay, then one typed final answer",
                "prompt": [
                    "systems/aus_agent_v2/prompts/system/contract-lean.md",
                ],
            },
            "semantic": {
                "label": "REJECT-ONLY SEMANTIC GATE",
                "note": "row-local support audit; at most one text-only repair",
            },
        },
    },
    {
        "id": "union",
        "label": "Extractive candidate union",
        "status": "UNGRADED · dev criterion ceiling 0.8284 (not a score)",
        "tone": "oracle",
        "input": "eight completed cited answers",
        "entrypoint": "systems/aus_agent_v2/pipeline.py::run_candidate_union_one",
        "note": (
            "Independent selector-only branch over already-paid answers; it "
            "copies immutable cited items and never writes prose."
        ),
        "path": ["union", "save"],
        "stage_overrides": {
            "union": {
                "label": "SELECT IMMUTABLE ITEMS",
                "note": "anonymous source runs; exact prose and citations only",
            },
        },
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


def run_candidate_union_one(
    *,
    qid: str,
    narrative: str,
    run_id: str,
    candidate_outputs: list[dict[str, Any]],
    anchor_run_id: str,
    run_desc: str | None = None,
    model_id: str | None = None,
    backend: str = "openai",
    provider_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Select an immutable cited union from complete same-topic candidates."""
    started_at = now_iso()
    factory = provider_factory or (lambda: make_provider(backend, model_id))
    selected = select_candidate_union(
        narrative,
        candidate_outputs,
        expected_qid=qid,
        anchor_run_id=anchor_run_id,
        provider_factory=factory,
    )
    ended_at = now_iso()
    attempts = selected["attempts"]
    actual_model = next((
        str(attempt.get("model_id") or "")
        for attempt in attempts if attempt.get("model_id")
    ), str(model_id or "unknown"))
    answer_words = sum(
        len(item["text"].split()) for item in selected["answer"])
    union_summary = {
        "accepted": selected["accepted"],
        "fallback": selected["fallback"],
        "errors": list(selected["errors"]),
        "attempts": len(attempts),
        "packet_chars": selected["packet_chars"],
        "selected_items": len(selected["selected_item_ids"]),
        "answer_words": answer_words,
        "candidate_runs": [
            str(output.get("metadata", {}).get("run_id") or "")
            for output in candidate_outputs
        ],
        "anchor_run": anchor_run_id,
        "coverage_accounting": list(selected["coverage"]),
        "anchor_replacements": list(selected["anchor_replacements"]),
    }
    builder = TrajectoryBuilder(qid, narrative, metadata={
        "model": actual_model,
        "backend": backend,
        "run_id": run_id,
        "architecture": "extractive_candidate_union",
    })
    builder.set_trace_input({
        "query": narrative,
        "packet": selected["packet"],
    })
    raw_messages: list[Any] = []
    for turn, attempt in enumerate(attempts):
        if raw_messages:
            raw_messages.append({
                "type": "phase_boundary",
                "phase": "candidate_union_retry",
                "attempt": int(attempt.get("attempt") or turn + 1),
            })
        raw_messages.extend(list(attempt.get("raw_messages") or []))
        builder.add_model_step(
            input={
                "kind": "candidate_union_selection",
                "attempt": int(attempt.get("attempt") or turn + 1),
            },
            output={
                "errors": list(attempt.get("errors") or []),
                "stats": dict(attempt.get("stats") or {}),
            },
            t_start=str(attempt.get("started_at") or started_at),
            t_end=str(attempt.get("ended_at") or ended_at),
            turn=turn,
            stats={"tokens": candidate_union_usage([attempt])},
        )
    builder.set_trace_output({
        "accepted": selected["accepted"],
        "fallback": selected["fallback"],
        "references": selected["references"],
        "answer": selected["answer"],
    })
    builder.add_output_text(
        " ".join(item["text"] for item in selected["answer"]),
        t_start=ended_at,
        t_end=ended_at,
        turn=max(0, len(attempts) - 1),
        record_trace=False,
    )
    trajectory = builder.finalize(
        "completed",
        raw_messages=raw_messages,
        started_at=started_at,
        ended_at=ended_at,
    )
    trajectory.trace["summary"]["candidate_union"] = union_summary
    output = build_rag_output(
        narrative_id=qid,
        narrative=narrative,
        run_id=run_id,
        run_desc=(run_desc or (
            "Extractive citation-preserving union over complete candidate "
            "research answers.")),
        references=selected["references"],
        answer=selected["answer"],
    )
    paths = save_run(
        SYSTEM_NAME, narrative, trajectory=trajectory, output=output)
    return {
        "status": "completed",
        "paths": paths,
        "accepted": selected["accepted"],
        "fallback": selected["fallback"],
        "n_references": len(selected["references"]),
        "n_sentences": len(selected["answer"]),
        "words": answer_words,
    }
