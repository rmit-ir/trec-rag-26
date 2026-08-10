"""brief_revise_agent -- a fork of aus_agent, plus a pre-flight requirements
brief and one grounded review-and-revise pass (see ``PLAN.md``).

Everything else is deliberately byte-identical to aus_agent: the same shared
``agent_harness.agent.run_agent`` loop, the same 267-line tuned prompt (its
own ``prompts/system/default.md``, a byte-copy of aus_agent's plus two
additive appendices), the same engine set and budgets (PLAN.md §3.4 lists
what does NOT change). ``facets_agent.agent`` is the worked example this
module is modelled on -- thin configuration over ``run_agent``, its own
``pre_final_hook`` wired as an overridable default kwarg -- except
brief_revise_agent's two additions need per-run state (the parsed brief, a
reviewer provider) that a bare function reference like
``facets_agent.review.coverage_gate`` never needed, so the hook is built as a
closure inside ``run_agent`` itself rather than passed as a module-level
default.

Two things this module adds on top of aus_agent's own config:

1. **The requirements brief** (``brief.py``): one tool-less LLM call, on its
   own provider (built from the same ``backend``/``model`` factory the run
   itself uses), rendered into an appendix appended to the loaded system
   prompt. An empty/failed brief renders to an empty appendix, so the prompt
   is then exactly aus_agent's own (plus the static, per-topic-invariant
   Appendix B baked into ``default.md``) -- the brief can only ever add
   advisory text, never remove or gate anything.
2. **The review pass** (``review.py``), wired as ``run_agent``'s
   ``pre_final_hook``: built as a closure over the parsed brief and a second
   provider from the same factory, so the reviewer can name brief entries by
   id and never needs the harness to widen its own contract. Passing an
   explicit ``pre_final_hook=`` (including ``None``) overrides this default,
   e.g. for tests exercising the bare fork with the pass disabled.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_harness import agent as agent_harness_mod
from agent_harness.agent import (  # noqa: F401  (re-exported for run.py + tests)
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    DEFAULT_ENGINES,
    DEFAULT_MAX_COMMITTED_PER_STEP,
    DEFAULT_SAFETY_MAX_ROUNDS,
    FINISHING_ROUNDS_GRACE,
    PARTIAL_SAVE_MIN_INTERVAL_S,
    make_provider,
    run_agent as _run_agent,
)

from . import adjacent_pages, brief, review

SYSTEM_NAME = "brief_revise_agent"

# Own prompts/system/ dir -- a separate copy of aus_agent's loader, not a
# reused import, because SYSTEM_PROMPTS_DIR is resolved relative to __file__
# (see aus_agent.agent.load_system_prompt's own docstring for why: every
# caller with its own prompt-variant scheme resolves its own files).
SYSTEM_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts" / "system"
DEFAULT_PROMPT_VARIANT = "default"
MAX_COMMITTED_PLACEHOLDER = "__MAX_COMMITTED_DOCS__"

# Sentinel distinguishing "caller passed no pre_final_hook" (build the
# default brief+review closure) from "caller explicitly passed None" (the
# whole pass is disabled) -- a plain `= review.hook` default, the pattern
# facets_agent uses, does not work here because the hook needs per-run state
# (the parsed brief, a reviewer provider) that only exists once run_agent
# starts.
_DEFAULT_HOOK = object()


def load_system_prompt(max_committed: int,
                       variant: str = DEFAULT_PROMPT_VARIANT) -> str:
    """Load this package's own system prompt variant (see
    ``aus_agent.agent.load_system_prompt`` -- identical contract, own dir)."""
    path = SYSTEM_PROMPTS_DIR / f"{variant}.md"
    if not path.exists():
        raise RuntimeError(f"unknown prompt variant {variant!r}: "
                           f"{path} not found")
    template = path.read_text(encoding="utf-8")
    count = template.count(MAX_COMMITTED_PLACEHOLDER)
    if count != 1:
        raise RuntimeError(
            f"prompt variant {variant!r} must contain exactly one "
            f"{MAX_COMMITTED_PLACEHOLDER} placeholder; found {count}")
    return template.replace(MAX_COMMITTED_PLACEHOLDER, str(max_committed))


# Ordered stage flow for the architecture visualization (gen_arch_viz.py
# reads this literal via ast, no import) -- see facets_agent.agent's own
# ARCH_STAGES for the convention. The two new stages (BRIEF, REVIEW) bracket
# the shared loop; everything inside it is unmodified aus_agent/agent_harness
# code.
ARCH_STAGES = [
    {"id": "brief", "label": "BRIEF", "kind": "llm",
     "note": "one tool-less call: narrative -> <=8 requirements (<=4 "
             "implicit), rendered into a system-prompt appendix. Bad JSON "
             "or a provider error -> empty brief, run proceeds unchanged",
     "prompt": ["systems/brief_revise_agent/prompts.py::BRIEF_PROMPT"],
     "code": ["systems/brief_revise_agent/brief.py::get_requirements",
              "systems/brief_revise_agent/brief.py::parse_brief",
              "systems/facet_rag/llm.py::one_shot"]},
    {"id": "loop", "label": "TURN LOOP", "kind": "loop",
     "note": "staged-context state machine (shared agent_harness package, "
             "unmodified) -- system prompt is aus_agent's own default.md "
             "plus the brief appendix",
     "back_to": "search", "back_from": "commit",
     "back_label": "repeat until report",
     "code": ["systems/brief_revise_agent/agent.py::run_agent",
              "agent_harness/agent.py::run_agent"],
     "tools": [{"name": "search",
                "ref": "agent_harness/tools/search.py::SEARCH_TOOL_DEF"},
               {"name": "get_documents",
                "ref": "agent_harness/tools/get_documents.py::GET_DOCUMENTS_TOOL"},
               {"name": "commit_context",
                "ref": "agent_harness/tools/commit_context.py::COMMIT_CONTEXT_TOOL"}],
     "tools_note": "unmodified agent_harness tool schemas -- same as "
                    "aus_agent, engines=semantic,keyword"},
    {"id": "search", "label": "SEARCH", "kind": "retrieval",
     "note": "full-text search over the enabled engines, then "
             "search_result_augment auto-fetches +/-1 adjacent pages for "
             "the top 5 paginated hits (zero-LLM-call, default on)",
     "prompt": ["systems/brief_revise_agent/prompts/system/default.md"],
     "code": ["agent_harness/tools/search.py::execute_full_text_search",
              "agent_harness/agent.py::_execute_tool_calls",
              "systems/brief_revise_agent/adjacent_pages.py::augment"]},
    {"id": "stage", "label": "STAGE", "kind": "no-llm",
     "note": "stage evidence; commit-before-expire protocol",
     "code": ["agent_harness/context.py::ContextLedger.stage"]},
    {"id": "commit", "label": "REASON/COMMIT", "kind": "llm",
     "note": "model turn curates staged evidence into committed context",
     "prompt": ["systems/brief_revise_agent/prompts/system/default.md"],
     "code": ["agent_harness/tools/commit_context.py::apply_commit",
              "agent_harness/context.py::ContextLedger.commit"]},
    {"id": "final", "label": "FINAL PROSE", "kind": "llm",
     "note": "cited prose report -- a draft until the review pass accepts it",
     "prompt": ["systems/brief_revise_agent/prompts/system/default.md"],
     "tools_note": "same conversation as the loop -- the report is a turn, "
                    "not a new call"},
    {"id": "review", "label": "REVIEW", "kind": "llm",
     "note": "pre_final_hook, fires at most once: deterministic "
             "uncited-sentence scan + one reviewer call reading committed "
             "evidence locally from ledger.call_history. None issues + no "
             "uncited sentences -> accept; otherwise -> one revision turn, "
             "usually back through FINAL PROSE, but the feedback re-enters "
             "the same turn loop the model always has, so it may search "
             "again first (REVIEW_PROMPT tells it to prefer an existing "
             "committed docid and only search if a requirement is "
             "genuinely unsupported). Either way, no second review fires. "
             "Any failure -> log, accept anyway",
     "back_to": "final", "back_from": "review",
     "back_label": "usual: patch the draft",
     "decision_to": "search", "decision_label": "rare: unsupported requirement",
     "prompt": ["systems/brief_revise_agent/prompts.py::REVIEW_PROMPT"],
     "code": ["systems/brief_revise_agent/review.py::hook",
              "agent_harness/agent.py::run_agent"]},
    {"id": "map", "label": "MAP CITES", "kind": "format",
     "note": "docid -> reference-index mapping",
     "code": ["agent_harness/agent.py::_map_citations"]},
    {"id": "save", "label": "SAVE", "kind": "artifact",
     "note": "ragrun.save_run",
     "code": ["ragrun/outputs.py::save_run"]},
]

__all__ = [
    "ARCH_STAGES", "DEFAULT_CONTEXT_TOKEN_BUDGET", "DEFAULT_ENGINES",
    "DEFAULT_MAX_COMMITTED_PER_STEP", "DEFAULT_PROMPT_VARIANT",
    "DEFAULT_SAFETY_MAX_ROUNDS", "FINISHING_ROUNDS_GRACE",
    "MAX_COMMITTED_PLACEHOLDER", "PARTIAL_SAVE_MIN_INTERVAL_S", "SYSTEM_NAME",
    "SYSTEM_PROMPTS_DIR", "load_system_prompt", "make_provider", "run_agent",
]


def run_agent(query_id: str, query: str, *, backend: str = "bedrock",
              model: str | None = None, region: str | None = None, k: int = 10,
              context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
              safety_max_rounds: int = DEFAULT_SAFETY_MAX_ROUNDS,
              max_committed_per_step: int = DEFAULT_MAX_COMMITTED_PER_STEP,
              run_id: str = "brief-revise-agent-dev",
              run_desc: str | None = None,
              prompt_variant: str = DEFAULT_PROMPT_VARIANT,
              engines: list[str] | None = None,
              system_prompt: str,
              pre_final_hook: Any = _DEFAULT_HOOK,
              search_result_augment: Any = adjacent_pages.augment,
              brief_backend: str | None = None, brief_model: str | None = None,
              brief_region: str | None = None,
              closure_check: bool = False,
              review_backend: str | None = None, review_model: str | None = None,
              review_region: str | None = None,
              **kwargs: Any) -> dict[str, Any]:
    """Run one topic end-to-end: aus_agent's own harness config, plus the
    requirements brief appended to ``system_prompt`` and the review pass
    wired as ``pre_final_hook`` (PLAN.md §3).

    ``system_prompt`` is the LOADED base template (e.g. from this module's
    own ``load_system_prompt``) -- exactly aus_agent/run.py's own calling
    convention. The brief appendix is appended to it here, not baked into the
    file, because it is per-topic.

    ``pre_final_hook`` defaults to the review pass (brief-aware, built fresh
    per run since it closes over the parsed brief and its own provider); pass
    ``None`` to disable it entirely (the brief step still runs -- these are
    independent additions, see module docstring), or any other callable to
    replace it outright (e.g. in tests exercising the bare harness).

    ``search_result_augment`` (round B of the sol-vs-aus_agent_v2 loop, see
    ``adjacent_pages.py``) defaults to the stateless adjacent-page fetcher --
    no per-run state needed (unlike the review hook), so a plain module
    function works as the default the way ``facets_agent.review.coverage_gate``
    does. Pass ``None`` to disable it (isolating this round's test from the
    review/brief axis, per the preregistered A/B/C/D design), or another
    callable to replace it.

    ``brief_backend``/``brief_model``/``brief_region`` and
    ``review_backend``/``review_model``/``review_region`` (the factorial-
    analysis round, sol's design: "does the main research/writer model
    matter, holding the analyst/reviewer roles fixed") decouple the brief
    analyst's and reviewer's providers from the main loop's ``backend``/
    ``model``/``region`` -- each defaults to ``None``, meaning "inherit the
    main run's own", so every call site that predates this parameter is
    unaffected. Passing them explicitly lets the three roles run on
    different models/backends independently (e.g. main on a Bedrock model,
    analyst and reviewer staying on the usual OpenAI one).

    ``region``/``brief_region``/``review_region`` only affect the brief and
    reviewer providers, constructed directly here via ``make_provider``.
    ``agent_harness.agent.run_agent`` builds the MAIN loop's own provider
    internally with no per-call region parameter -- a Bedrock region for the
    main model (e.g. Qwen needing ``us-east-1``/``us-west-2``) must be set
    via the ``BEDROCK_REGION`` environment variable for that invocation,
    per ``agent_harness.providers.bedrock``'s own documented convention.

    ``**kwargs`` passes through to ``agent_harness.agent.run_agent`` unchanged.
    """
    engines = list(engines) if engines else list(DEFAULT_ENGINES)

    brief_provider = agent_harness_mod.make_provider(
        brief_backend or backend, brief_model or model,
        region=brief_region or region)
    requirements = brief.get_requirements(brief_provider, query)
    full_system_prompt = system_prompt + brief.render_appendix(requirements)

    if pre_final_hook is _DEFAULT_HOOK:
        reviewer_provider = agent_harness_mod.make_provider(
            review_backend or backend, review_model or model,
            region=review_region or region)

        def active_hook(context: dict[str, Any]) -> str | None:
            return review.hook(context, requirements=requirements,
                               closure_check=closure_check,
                               provider=reviewer_provider)
    else:
        active_hook = pre_final_hook

    return _run_agent(
        query_id, query, backend=backend, model=model, k=k, engines=engines,
        context_token_budget=context_token_budget,
        safety_max_rounds=safety_max_rounds,
        max_committed_per_step=max_committed_per_step, run_id=run_id,
        run_desc=run_desc, prompt_variant=prompt_variant,
        system_name=SYSTEM_NAME, system_prompt=full_system_prompt,
        pre_final_hook=active_hook, search_result_augment=search_result_augment,
        **kwargs)
