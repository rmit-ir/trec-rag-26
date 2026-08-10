"""open_weight_agent -- an open-weight-only fork of brief_revise_agent, plus a
blind obligation scout ported from aus_agent_v2.

Design rationale (worklogs/assets/2026-08-07-factor-analysis-report/report.typ
ranks every system in this repo; §10.2-10.3 name the two strongest):
``aus_agent_v2`` is the best arena performer but the most expensive system
in the repo by a wide margin and depends on OpenAI ``gpt-5.6-*`` models
throughout; ``brief_revise_agent`` ties it on standalone rubric grading at
roughly 1/50th the cost with a much simpler architecture (one pre-flight
requirements brief + one review/revise pass over the shared
``agent_harness.agent.run_agent`` loop). This system takes brief_revise_agent
as its base -- reusing its ``brief``/``review``/``adjacent_pages`` modules
directly rather than duplicating them -- and adds exactly one structural idea
ported from aus_agent_v2, its blind obligation-scout stage (``scout.py``),
plus the two confirmed-cheap wins from the same report's factor sweep (§4.2,
§4.6): adjacent-page augmentation (S5) on by default, and the ``hybrid``
retrieval engine alone (S6) as the default engine set instead of the
``semantic,keyword`` pair.

The one hard constraint this system exists to satisfy: every model role
(main writer, brief analyst, reviewer, scout) must be an open-weight model.
``ALLOWED_MODELS`` is the enforced allowlist (Bedrock ids confirmed working
under this account per ``agent_harness.providers.bedrock``'s own docstring);
``_check_model`` raises on anything else. There is no OpenAI backend option
here at all -- unlike brief_revise_agent, which defaults to Bedrock but
still accepts ``--backend openai``.

Everything not named above is deliberately unchanged from
brief_revise_agent: same shared ``agent_harness.agent.run_agent`` loop, same
267-line tuned system prompt (reused directly via
``brief_revise_agent.agent.load_system_prompt`` -- not copied into this
package, so there is exactly one copy of that file in the repo), same
commit/citation protocol.
"""
from __future__ import annotations

from typing import Any

from agent_harness import agent as agent_harness_mod
from agent_harness.agent import (
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    DEFAULT_MAX_COMMITTED_PER_STEP,
    DEFAULT_SAFETY_MAX_ROUNDS,
    make_provider,
    run_agent as _run_agent,
)

from systems.brief_revise_agent import adjacent_pages, brief, review
from systems.brief_revise_agent.brief import Requirement
from systems.brief_revise_agent.agent import (
    load_system_prompt as load_base_system_prompt,
)

from . import blueprint as blueprint_mod
from .scout import get_scout_additions, render_scout_appendix

SYSTEM_NAME = "open_weight_agent"

# The ONLY model ids this system will ever build a provider for, in any of
# its four roles (main writer, brief analyst, reviewer, scout) -- verified
# working Bedrock open-weight models under this account (see
# agent_harness/providers/bedrock.py's own docstring). No OpenAI backend, no
# proprietary Bedrock model (anthropic.*): staying open-weight end to end is
# this system's entire premise, not an incidental default.
ALLOWED_MODELS = frozenset({
    "openai.gpt-oss-120b-1:0",
    "qwen.qwen3-next-80b-a3b",
    "moonshot.kimi-k2-thinking",
    # Added 2026-08-09 after a gpt-5.6-sol design review
    # (worklogs/assets/2026-08-09-open-weight-agent-sol-plan-review.md) plus a real
    # `boto3 bedrock.list_foundation_models` catalog check (not guessed --
    # sol's own first pass named several candidates it could not verify
    # were actually reachable; this is the confirmed-real subset, sol's and
    # Gemini Deep Research's independent top picks).
    "qwen.qwen3-235b-a22b-2507-v1:0",
    "zai.glm-5",
    "deepseek.v3.2",
    "us.meta.llama3-3-70b-instruct-v1:0",  # inference-profile id, not the bare meta.* id
    "moonshotai.kimi-k2.5",
})
DEFAULT_MODEL = "zai.glm-5"
# qwen.*/moonshot.* only serve this account in us-east-1/us-west-2;
# gpt-oss-120b works in both ap-southeast-2 (the repo's own Bedrock default)
# and us-east-1. Pinned explicitly for every model (not left to fall back
# on an ambient BEDROCK_REGION) -- facet_rag/run.py's own comment names the
# exact failure this avoids: .env's BEDROCK_REGION can be a region (e.g.
# ap-southeast-1) that 400s "invalid model identifier" for these
# non-Anthropic models, and BedrockProvider's own region resolution prefers
# an already-set env var over its hardcoded default, so passing region=None
# here would NOT actually protect against a bad ambient value.
#
# The 2026-08-09 additions' region placement is a real catalog fact, not a
# guess: `qwen.qwen3-235b-a22b-2507-v1:0` is ap-southeast-2 ONLY (absent
# from the us-east-1 catalog listing entirely); `zai.glm-5`/`deepseek.v3.2`/
# `moonshotai.kimi-k2.5` are ON_DEMAND in both regions, pinned to
# ap-southeast-2 for consistency with gpt-oss-120b; Llama 3.3 70B is
# INFERENCE_PROFILE-only and was only confirmed in us-east-1
# (`list_inference_profiles`), hence the `us.` id prefix and region.
DEFAULT_REGION_BY_MODEL = {
    "openai.gpt-oss-120b-1:0": "ap-southeast-2",
    "qwen.qwen3-next-80b-a3b": "us-east-1",
    "moonshot.kimi-k2-thinking": "us-east-1",
    "qwen.qwen3-235b-a22b-2507-v1:0": "ap-southeast-2",
    "zai.glm-5": "ap-southeast-2",
    "deepseek.v3.2": "ap-southeast-2",
    "us.meta.llama3-3-70b-instruct-v1:0": "us-east-1",
    "moonshotai.kimi-k2.5": "ap-southeast-2",
}
# Most Bedrock models tolerate BedrockProvider's 16000-token default output
# cap; Llama 3.3 70B's endpoint hard-rejects any maxTokens above 8192 (a
# ValidationException, discovered smoke-testing this model) -- only models
# needing an override appear here, per-model, rather than lowering the
# shared default for every model.
MAX_TOKENS_BY_MODEL = {
    "us.meta.llama3-3-70b-instruct-v1:0": 8000,
}
# S6 (report §4.6): hybrid alone replicated as the one cheap-AND-better
# retrieval-engine lever found against the semantic,keyword default, on two
# independent 15-topic sets. Untested there for an open-weight model, so
# open_weight_agent's own bake-off re-checks it (worklogs/2026-08-09-open-weight-agent-*.md)
# rather than assuming the sol-specific result transfers unchecked.
DEFAULT_ENGINES = ["hybrid"]

_DEFAULT_HOOK = object()  # see brief_revise_agent.agent's own sentinel

ARCH_STAGES = [
    {"id": "brief", "label": "BRIEF", "kind": "llm",
     "note": "one tool-less call: narrative -> <=8 requirements (<=4 "
             "implicit), rendered into a system-prompt appendix. Reused "
             "unmodified from brief_revise_agent -- open-weight model only.",
     "prompt": ["systems/brief_revise_agent/prompts.py::BRIEF_PROMPT"],
     "code": ["systems/brief_revise_agent/brief.py::get_requirements",
              "systems/facet_rag/llm.py::one_shot"]},
    {"id": "scout", "label": "SCOUT (blind)", "kind": "llm",
     "note": "second, independent call: sees ONLY the original request, "
             "not the brief above -- ported from aus_agent_v2's "
             "plan_critic, this repo's best arena performer. Up to 8 "
             "additional atomic checks, rendered as extra bullet entries "
             "after the brief's own appendix. Bad JSON or a provider "
             "error -> no scout additions, run proceeds unchanged.",
     "prompt": ["systems/aus_agent_v2/plan_critic.py::PLAN_CRITIC_SYSTEM"],
     "code": ["systems/open_weight_agent/scout.py::get_scout_additions",
              "systems/aus_agent_v2/plan_critic.py::normalize_plan_critique"]},
    {"id": "loop", "label": "TURN LOOP", "kind": "loop",
     "note": "staged-context state machine (shared agent_harness package, "
             "unmodified) -- system prompt is brief_revise_agent's own "
             "default.md plus the brief and scout appendices",
     "back_to": "search", "back_from": "commit",
     "back_label": "repeat until report",
     "code": ["systems/open_weight_agent/agent.py::run_agent",
              "agent_harness/agent.py::run_agent"],
     "tools": [{"name": "search",
                "ref": "agent_harness/tools/search.py::SEARCH_TOOL_DEF"},
               {"name": "get_documents",
                "ref": "agent_harness/tools/get_documents.py::GET_DOCUMENTS_TOOL"},
               {"name": "commit_context",
                "ref": "agent_harness/tools/commit_context.py::COMMIT_CONTEXT_TOOL"}],
     "tools_note": "unmodified agent_harness tool schemas; engines=hybrid "
                    "only by default (S6)"},
    {"id": "search", "label": "SEARCH", "kind": "retrieval",
     "note": "hybrid (dense+sparse RRF) search, then search_result_augment "
             "auto-fetches +/-1 adjacent pages for the top 5 paginated "
             "hits (zero-LLM-call, default on, S5)",
     "code": ["agent_harness/tools/search.py::execute_full_text_search",
              "agent_harness/agent.py::_execute_tool_calls",
              "systems/brief_revise_agent/adjacent_pages.py::augment"]},
    {"id": "stage", "label": "STAGE", "kind": "no-llm",
     "note": "stage evidence; commit-before-expire protocol",
     "code": ["agent_harness/context.py::ContextLedger.stage"]},
    {"id": "commit", "label": "REASON/COMMIT", "kind": "llm",
     "note": "model turn curates staged evidence into committed context",
     "code": ["agent_harness/tools/commit_context.py::apply_commit",
              "agent_harness/context.py::ContextLedger.commit"]},
    {"id": "final", "label": "FINAL PROSE", "kind": "llm",
     "note": "cited prose report -- a draft until the review pass accepts it",
     "tools_note": "same conversation as the loop -- the report is a turn, "
                    "not a new call"},
    {"id": "review", "label": "REVIEW", "kind": "llm",
     "note": "pre_final_hook, fires at most once: deterministic "
             "uncited-sentence scan + one reviewer call reading committed "
             "evidence locally. Reused unmodified from brief_revise_agent "
             "-- open-weight model only.",
     "back_to": "final", "back_from": "review",
     "back_label": "at most one revision",
     "prompt": ["systems/brief_revise_agent/prompts.py::REVIEW_PROMPT"],
     "code": ["systems/brief_revise_agent/review.py::hook"]},
    {"id": "map", "label": "MAP CITES", "kind": "format",
     "note": "docid -> reference-index mapping",
     "code": ["agent_harness/agent.py::_map_citations"]},
    {"id": "save", "label": "SAVE", "kind": "artifact",
     "note": "ragrun.save_run",
     "code": ["ragrun/outputs.py::save_run"]},
]

__all__ = [
    "ALLOWED_MODELS", "ARCH_STAGES", "DEFAULT_CONTEXT_TOKEN_BUDGET",
    "DEFAULT_ENGINES", "DEFAULT_MAX_COMMITTED_PER_STEP", "DEFAULT_MODEL",
    "DEFAULT_REGION_BY_MODEL", "DEFAULT_SAFETY_MAX_ROUNDS",
    "SYSTEM_NAME", "load_base_system_prompt", "make_provider", "run_agent",
]


def _check_model(model: str, *, backend: str = "bedrock") -> None:
    """Enforced for every ``backend="bedrock"`` role, always. A support role
    (brief/scout/review, never the main writer) explicitly given
    ``backend="openai"`` skips this check entirely -- that is the ONLY way
    to run a proprietary model anywhere in this system, and it is a
    diagnostic escape hatch for offline role-decoupling experiments (sol +
    Gemini Deep Research plan review,
    worklogs/assets/2026-08-09-open-weight-agent-sol-plan-review.md), never a
    deployable configuration: ``run.py`` labels any such run's artifacts
    accordingly, and nothing in this system's own default path can reach
    this branch."""
    if backend != "bedrock":
        return
    if model not in ALLOWED_MODELS:
        raise ValueError(
            f"open_weight_agent is open-weight-only: {model!r} is not in "
            f"ALLOWED_MODELS ({sorted(ALLOWED_MODELS)}). This restriction is "
            "the system's entire premise (see README.md), not a bug to "
            "work around. A proprietary model is only ever permitted in a "
            "support role (brief/scout/review), and only via an explicit "
            "backend=\"openai\" diagnostic override -- never for the main "
            "writer, and never by adding it to ALLOWED_MODELS.")


def _resolve_region(model: str, region: str | None) -> str | None:
    return region if region else DEFAULT_REGION_BY_MODEL.get(model)


def _scout_additions_as_requirements(additions: list[dict[str, Any]]
                                     ) -> list[Requirement]:
    """Convert the blind scout's raw addition dicts (``scout.py``'s own
    shape: kind/requirement/must_mention/reason) into ``Requirement``
    objects with the SAME ``S1``/``S2``/... ids ``scout.render_scout_
    appendix`` already put in front of the model, so ``review.hook``
    grades exactly what the model was told to search against -- reused
    unmodified (``review_scout_obligations``), not a new review mechanism."""
    return [
        Requirement(id=f"S{i + 1}", requirement=addition["requirement"],
                   origin="implicit", why=addition.get("reason", ""),
                   specific_form=addition.get("reason") or addition["requirement"])
        for i, addition in enumerate(additions)
    ]


def run_agent(query_id: str, query: str, *,
              model: str = DEFAULT_MODEL, region: str | None = None, k: int = 10,
              context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
              safety_max_rounds: int = DEFAULT_SAFETY_MAX_ROUNDS,
              max_committed_per_step: int = DEFAULT_MAX_COMMITTED_PER_STEP,
              run_id: str = "open-weight-agent-dev",
              run_desc: str | None = None,
              engines: list[str] | None = None,
              system_prompt: str,
              pre_final_hook: Any = _DEFAULT_HOOK,
              search_result_augment: Any = adjacent_pages.augment,
              brief_model: str | None = None, brief_region: str | None = None,
              brief_backend: str = "bedrock",
              review_model: str | None = None, review_region: str | None = None,
              review_backend: str = "bedrock",
              scout_model: str | None = None, scout_region: str | None = None,
              scout_backend: str = "bedrock",
              plan_critic: bool = True, plan_critic_max_additions: int = 8,
              closure_check: bool = False,
              synthesis_compiler: bool = False,
              review_scout_obligations: bool = False,
              **kwargs: Any) -> dict[str, Any]:
    """Run one topic end-to-end: brief_revise_agent's own harness config
    (open-weight models only), plus a blind scout stage (ported from
    aus_agent_v2) merged into the same requirements-brief appendix.

    ``model``/``brief_model``/``review_model``/``scout_model`` each default
    to ``DEFAULT_MODEL`` when unset (a bare ``None`` is NOT accepted the way
    brief_revise_agent's "inherit main model" convention allows, because
    every role must independently clear ``_check_model`` -- accepting
    ``None`` here would silently defer that check to whatever
    ``make_provider``/``agent_harness.agent.run_agent`` do with a missing
    model, bypassing the allowlist for exactly the parameter this system
    exists to restrict).

    ``region``/``brief_region``/``review_region``/``scout_region`` default
    to ``DEFAULT_REGION_BY_MODEL[<that role's model>]`` when unset (qwen/
    kimi need ``us-east-1``/``us-west-2`` under this account; gpt-oss-120b
    works in the repo's own Bedrock default too). The MAIN loop's provider
    is built inside ``agent_harness.agent.run_agent`` itself, which has no
    per-call region parameter -- ``run.py`` sets ``BEDROCK_REGION`` in the
    environment before calling this function, per
    ``agent_harness.providers.bedrock``'s documented convention.

    ``plan_critic`` (default True) toggles the blind scout stage; pass
    False to isolate its effect from brief_revise_agent's own base
    behavior in an A/B comparison.

    ``brief_backend``/``scout_backend``/``review_backend`` each default to
    ``"bedrock"``, which is when ``_check_model`` enforces the open-weight
    allowlist for that role. Passing ``backend="openai"`` for exactly one
    support role (never ``model``/the main writer, which stays hardcoded to
    ``backend="bedrock"`` below) is the diagnostic-only role-decoupling
    escape hatch (worklogs/assets/2026-08-09-open-weight-agent-sol-plan-review.md)
    -- a proprietary support role's output is never eligible for
    submission; it exists to localize which role drives the measured
    -0.200 mixed-pipeline gap.

    ``synthesis_compiler`` (default False): use ``blueprint.hook`` instead
    of ``review.hook`` as the ``pre_final_hook`` -- forces a validated,
    obligation-covering structure before the final prose pass rather than
    critiquing an already-written draft (``blueprint.py``'s own module
    docstring has the full design rationale; converged sol/Opus review,
    worklogs/assets/2026-08-09-open-weight-agent-sol-plan-review.md). The harness
    fires ``pre_final_hook`` at most once, so this REPLACES the review
    pass for a run rather than adding a second one -- ignored when an
    explicit ``pre_final_hook`` is also passed (that always wins, same
    override rule brief_revise_agent's own ``_DEFAULT_HOOK`` sentinel uses).
    **Empirically tested and REJECTED** (worklogs/2026-08-09-open-weight-agent-
    open-weight-system.md): a 15-topic pilot scored 0.933 vs. 1.467 for
    plain ``review.hook`` -- both target axes (Implicit Criteria,
    Synthesis) moved the WRONG direction, plus a sharp Communication/
    Citation-Quality collapse. Kept in the codebase, off by default, as a
    validated negative result -- do not flip this default without new
    evidence.

    ``review_scout_obligations`` (default False): widen ``review.hook``'s
    own requirement list to also grade the blind scout's additions
    (S1, S2, ... converted to ``Requirement`` objects, ``origin=
    "implicit"``), not just the brief's own -- so scout obligations get
    the same proven FULL/PARTIAL/MISSING + additive-PATCH treatment brief
    requirements already get. The follow-up both sol and Opus converged
    on after ``synthesis_compiler``'s negative result: the only pattern
    with positive support in this system's evidence is additive
    correction layered on the model's own organic draft (what the scout
    and review passes already do individually) -- never wholesale
    replacement/restructuring (what both ``synthesis_compiler`` and the
    rejected criterion-partitioned-union alternative do). Ignored when
    ``synthesis_compiler=True`` (that hook doesn't take a requirements
    list the same way).

    ``**kwargs`` passes through to ``agent_harness.agent.run_agent`` unchanged.
    """
    _check_model(model)  # the main writer is ALWAYS backend="bedrock", always checked
    _check_model(brief_model or model, backend=brief_backend)
    _check_model(review_model or model, backend=review_backend)
    _check_model(scout_model or model, backend=scout_backend)
    engines = list(engines) if engines else list(DEFAULT_ENGINES)

    brief_provider = agent_harness_mod.make_provider(
        brief_backend, brief_model or model,
        region=_resolve_region(brief_model or model, brief_region),
        max_tokens=MAX_TOKENS_BY_MODEL.get(brief_model or model))
    requirements = brief.get_requirements(brief_provider, query)
    appendix = brief.render_appendix(requirements)

    scout_additions: list[dict[str, Any]] = []
    if plan_critic:
        scout_provider = agent_harness_mod.make_provider(
            scout_backend, scout_model or model,
            region=_resolve_region(scout_model or model, scout_region),
            max_tokens=MAX_TOKENS_BY_MODEL.get(scout_model or model))
        scout_additions = get_scout_additions(
            scout_provider, query, max_additions=plan_critic_max_additions)
        appendix += render_scout_appendix(scout_additions)

    full_system_prompt = system_prompt + appendix

    if pre_final_hook is _DEFAULT_HOOK:
        reviewer_provider = agent_harness_mod.make_provider(
            review_backend, review_model or model,
            region=_resolve_region(review_model or model, review_region),
            max_tokens=MAX_TOKENS_BY_MODEL.get(review_model or model))

        if synthesis_compiler:
            def active_hook(context: dict[str, Any]) -> str | None:
                return blueprint_mod.hook(
                    context, requirements=requirements,
                    scout_additions=scout_additions, provider=reviewer_provider)
        else:
            review_requirements = requirements
            if review_scout_obligations and scout_additions:
                review_requirements = requirements + _scout_additions_as_requirements(
                    scout_additions)

            def active_hook(context: dict[str, Any]) -> str | None:
                return review.hook(context, requirements=review_requirements,
                                   closure_check=closure_check,
                                   provider=reviewer_provider)
    else:
        active_hook = pre_final_hook

    return _run_agent(
        query_id, query, backend="bedrock", model=model, k=k,
        max_tokens=MAX_TOKENS_BY_MODEL.get(model), engines=engines,
        context_token_budget=context_token_budget,
        safety_max_rounds=safety_max_rounds,
        max_committed_per_step=max_committed_per_step, run_id=run_id,
        run_desc=run_desc, system_name=SYSTEM_NAME,
        system_prompt=full_system_prompt,
        pre_final_hook=active_hook, search_result_augment=search_result_augment,
        **kwargs)
