"""facets_agent — minimal-prompt, facet_rag-inspired configuration of the
shared ``agent_harness`` staged-context harness.

Where facet_rag runs a scripted plan -> per-facet orchestrator/analyzer/
curator loop -> synthesize pipeline across separate model calls, facets_agent
asks ONE continuous tool-calling agent (see ``agent_harness.agent.run_agent``)
to run that same process itself, driven by a much shorter prompt
(``prompts.SYSTEM_PROMPT``) than aus_agent's own. Nothing about the loop,
the search/get_documents/commit_context protocol, or the final-report
contract is reimplemented here — ``run_agent`` is the shared harness both
aus_agent and facets_agent configure differently:

- ``system_name`` keeps this system's artifacts under
  ``data/outputs/facets_agent/``, never mixing with aus_agent's own runs;
- ``system_prompt`` is this package's own minimal prompt, not one of
  aus_agent's ``prompts/system/*.md`` variants;
- ``engines`` defaults to the three natural-language retrieval backends
  (semantic, keyword, hybrid — ``ssr``/``lucene_bool`` are no longer
  supported and are not offered), and ``default_k_by_engine`` widens
  ``hybrid`` beyond the common default — mirroring facet_rag's
  ``HYBRID_K`` (PLAN.md §3.3): a HyDE-style hypothetical-passage query
  benefits from a wider net than a short keyword query.
- ``search_tool_def``/``commit_context_tool`` are this package's own tool
  definitions (``tools.py``), not the harness's own defaults: PLAN.md phase
  2's tool-carried requirement ledger (a required ``requirement`` field on
  every search, a ``coverage``/``ready_to_report`` ledger on every commit)
  rides on the same two calls the model already makes, so no new tool and
  no extra turn -- see ``tools.py``'s own docstring for the full design.
"""
from __future__ import annotations

from typing import Any

from agent_harness.agent import (
    DEFAULT_MAX_COMMITTED_PER_STEP,
    make_provider,
    run_agent as _run_agent,
)

from .prompts import SYSTEM_PROMPT
from .review import coverage_gate
from .tools import COMMIT_CONTEXT_TOOL, build_search_tool_def

SYSTEM_NAME = "facets_agent"

# The three natural-language engines the prompt leads with -- ssr/lucene_bool
# are no longer supported, so they are not offered here even though the
# shared tools.search_tool.ENGINE_INFO still lists them (other systems may
# still enable them).
MANDATORY_ENGINES = ("semantic", "keyword", "hybrid")
DEFAULT_ENGINES = list(MANDATORY_ENGINES)
DEFAULT_K = 10
# hybrid's query is a HyDE hypothetical answer, not a short phrase -- a fuller
# embedded query benefits from a wider net (facet_rag's HYBRID_K).
DEFAULT_HYBRID_K = 15

# Ordered stage flow for the architecture visualization
# (skills/trec-rag-new-system/scripts/gen_arch_viz.py reads this literal via
# ast, no import). The loop itself is the shared agent_harness package —
# stages point at agent_harness's implementation where the mechanics are
# inherited unchanged, and at this package's own files where facets_agent
# supplies the configuration (prompt, engine set, hybrid-k override) that
# makes it a distinct system rather than an aus_agent prompt variant.
ARCH_STAGES = [
    {"id": "loop", "label": "TURN LOOP", "kind": "loop",
     "note": "staged-context state machine (shared agent_harness package)",
     "back_to": "search", "back_from": "commit",
     "back_label": "repeat until report",
     "code": ["systems/facets_agent/agent.py::run_agent",
              "agent_harness/agent.py::run_agent"],
     "tools": [{"name": "search",
                "ref": "systems/facets_agent/tools.py::SEARCH_TOOL_DEF"},
               {"name": "get_documents",
                "ref": "agent_harness/tools/get_documents.py::GET_DOCUMENTS_TOOL"},
               {"name": "commit_context",
                "ref": "systems/facets_agent/tools.py::COMMIT_CONTEXT_TOOL"}],
     "tools_note": "native tool-calling, passed once to provider.start -- "
                    "both search and commit_context are this system's OWN "
                    "definitions (tools.py), not agent_harness's: search "
                    "adds a required `requirement` field (PLAN.md phase 2's "
                    "tool-carried plan review), commit_context adds "
                    "`release` plus a `coverage`/`ready_to_report` "
                    "requirement ledger (the pre-report coverage "
                    "self-check). The 3 NL engines are enabled by default; "
                    "ssr/lucene_bool are no longer supported."},
    {"id": "search", "label": "SEARCH", "kind": "retrieval",
     "note": "requirement-labeled queries per engine; hybrid gets a "
             "HyDE-style hypothetical-passage query and a wider k",
     "prompt": ["systems/facets_agent/prompts.py::SYSTEM_PROMPT"],
     "code": ["agent_harness/tools/search.py::execute_full_text_search",
              "agent_harness/agent.py::_execute_tool_calls"],
     "engines": {"mandatory": "systems/facets_agent/agent.py::MANDATORY_ENGINES"}},
    {"id": "stage", "label": "STAGE", "kind": "no-llm",
     "note": "stage evidence; commit-before-expire protocol",
     "code": ["agent_harness/context.py::ContextLedger.stage"]},
    {"id": "commit", "label": "REASON/COMMIT", "kind": "llm",
     "note": "model turn curates: commit only each result's distinct "
             "contribution, release a committed doc a better one "
             "supersedes, restate the requirement coverage ledger",
     "prompt": ["systems/facets_agent/prompts.py::SYSTEM_PROMPT"],
     "code": ["agent_harness/tools/commit_context.py::apply_commit",
              "agent_harness/context.py::ContextLedger.commit",
              "agent_harness/context.py::ContextLedger.release_committed"]},
    {"id": "final", "label": "FINAL PROSE", "kind": "llm",
     "note": "self-checks citations, then grounded prose with inline cites",
     "prompt": ["systems/facets_agent/prompts.py::SYSTEM_PROMPT"],
     "tools_note": "same conversation as the loop -- the report is a turn, "
                    "not a new call"},
    {"id": "map", "label": "MAP CITES", "kind": "format",
     "note": "docid -> reference-index mapping",
     "code": ["agent_harness/agent.py::_map_citations"]},
    {"id": "save", "label": "SAVE", "kind": "artifact",
     "note": "ragrun.save_run",
     "code": ["ragrun/outputs.py::save_run"]},
]

__all__ = [
    "ARCH_STAGES", "DEFAULT_ENGINES", "DEFAULT_HYBRID_K", "DEFAULT_K",
    "MANDATORY_ENGINES", "SYSTEM_NAME", "make_provider", "run_agent",
]


def run_agent(query_id: str, query: str, *, backend: str = "openai",
              model: str | None = None, k: int = DEFAULT_K,
              hybrid_k: int = DEFAULT_HYBRID_K,
              engines: list[str] | None = None,
              max_committed_per_step: int = DEFAULT_MAX_COMMITTED_PER_STEP,
              run_id: str = "facets-agent-dev",
              run_desc: str | None = None,
              pre_final_hook: Any = coverage_gate,
              **kwargs: Any) -> dict[str, Any]:
    """Run one topic end-to-end through the shared harness, facets_agent-configured.

    ``pre_final_hook`` defaults to ``review.coverage_gate`` (PLAN.md Phase 4,
    §7.1): before accepting a final report, sends the model back once if its
    own requirement ledger still lists an entry `open`. Pass ``None`` to
    disable (e.g. in tests exercising the bare harness behavior).

    ``**kwargs`` passes through to ``agent_harness.agent.run_agent`` unchanged
    (``context_token_budget``, ``safety_max_rounds``, ...).
    """
    engines = list(engines) if engines else list(DEFAULT_ENGINES)
    system_prompt = SYSTEM_PROMPT.format(max_committed=max_committed_per_step)
    return _run_agent(
        query_id, query, backend=backend, model=model, k=k, engines=engines,
        max_committed_per_step=max_committed_per_step, run_id=run_id,
        run_desc=run_desc, system_name=SYSTEM_NAME,
        system_prompt=system_prompt, prompt_variant="facets_agent_minimal",
        default_k_by_engine={"hybrid": hybrid_k},
        commit_context_tool=COMMIT_CONTEXT_TOOL,
        search_tool_def=build_search_tool_def(engines),
        pre_final_hook=pre_final_hook, **kwargs)
