"""facets_agent's own tool definitions: the search tool with a `requirement`
field, and the `commit_context` tool with `release` and a `coverage` ledger.

Phase 2 of ``PLAN.md`` (2026-08-05): the tool-carried requirement ledger the
plan designs as the structured half of the coverage-gap fix Phase 1's prompt
wording alone can only ask for informally. Two instruments, read ``PLAN.md``
§1.1/§1.2 for the full design rationale (why a required field beats a
separate review tool or turn, why the enum stays at three values, why
``requirement`` and ``query`` must stay orthogonal):

- ``requirement`` on ``search`` — binds every call to the request
  requirement it serves, in the request's own words; a hunch about the
  answer belongs in ``query``, never here (see ``build_search_tool_def``).
- ``coverage`` + ``ready_to_report`` on ``commit_context`` — the full
  requirement ledger, restated on every call, which is what the model's
  report is checked against and how it decides it is actually done.

Both are marked ``required`` in the JSON schema (a model-compliance forcing
function -- OpenAI tools are not sent in strict mode, so this carries no
validation risk) but the underlying handlers
(``agent_harness.tools.commit_context.apply_commit`` /
``agent_harness.tools.search.execute_full_text_search``) read only the
arguments they already understood before this change and silently ignore
everything else -- exactly like ``release`` already does. A call that omits
or malforms either field cannot fail the run; the schema is a forcing
function, never a failure mode. Non-compliance is visible in the saved
trace (every raw tool-call argument is recorded verbatim), which is what
``PLAN.md`` §5's Tier 1 metrics read.
"""
from __future__ import annotations

from typing import Any

from agent_harness.tools.commit_context import COMMIT_CONTEXT_TOOL as _BASE_COMMIT_TOOL
from agent_harness.tools.search import build_search_tool_def as _base_build_search_tool_def

_RELEASE_PROPERTY: dict[str, Any] = {
    "release": {
        "type": "array",
        "description": (
            "Previously committed ids to drop because a document you are "
            "committing in THIS SAME call supersedes them — same fact, more "
            "precise, better-sourced, or more complete. Each facet should "
            "end up with the minimal set of documents that actually cover "
            "it, not every document that was ever useful; when a better one "
            "arrives, release the one it replaces rather than keeping both. "
            "Only ids already committed may be listed here — never a "
            "currently staged id (list those in `documents` instead)."
        ),
        "items": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "An already-committed id, exactly as committed.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "What specifically supersedes it — name the newly "
                        "committed id and what it has that this one lacked."
                    ),
                },
            },
            "required": ["id", "reason"],
        },
    },
}

_COVERAGE_PROPERTY: dict[str, Any] = {
    "coverage": {
        "type": "array",
        "description": (
            "Your full requirement ledger, restated every time you call "
            "this tool — not just what changed since last time. One entry "
            "per requirement the request states, explicit or implied: a "
            "named comparison, a stated audience or scope, a demanded "
            "structure, a concrete deliverable. This is what your final "
            "report is checked against, and `ready_to_report` below is "
            "computed from it."
        ),
        "items": {
            "type": "object",
            "properties": {
                "requirement": {
                    "type": "string",
                    "description": (
                        "The requirement in the request's own words, worded "
                        "identically to the `requirement` you use on "
                        "`search` calls for it."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": ["covered", "open", "unavailable"],
                    "description": (
                        "covered — committed evidence supports it now; "
                        "state what the corpus actually says even if it "
                        "contradicts what you expected. open — nothing "
                        "committed yet and the corpus has not been "
                        "properly asked. unavailable — searched on more "
                        "than one engine and the corpus does not have it; "
                        "this includes the case where you searched for a "
                        "specific name, work, technique, or event you were "
                        "confident about and the corpus does not carry "
                        "it — that requirement is `unavailable`, not "
                        "`covered`, and the thing you expected does not "
                        "enter the report as an asserted fact."
                    ),
                },
                "note": {
                    "type": "string",
                    "description": (
                        "For covered: the committed ids that carry it. For "
                        "open: the next query you will run for it. For "
                        "unavailable: the specific terms and names you "
                        "searched, spelled out — this is the record of "
                        "what the corpus was actually asked."
                    ),
                },
            },
            "required": ["requirement", "status", "note"],
        },
    },
    "ready_to_report": {
        "type": "boolean",
        "description": (
            "True only when no entry in `coverage` is `open`. While any "
            "entry is open you still have searches left to run, however "
            "much you have already found for the rest."
        ),
    },
}

COMMIT_CONTEXT_TOOL: dict[str, Any] = {
    **_BASE_COMMIT_TOOL,
    "description": (
        _BASE_COMMIT_TOOL["description"] + " Optionally also pass `release`: "
        "ids already committed that a document committed in this same call "
        "now supersedes, so each facet's evidence stays the minimal set "
        "that covers it rather than accumulating every document that was "
        "ever useful. Also pass `coverage` (your full requirement ledger, "
        "restated) and `ready_to_report` (computed from it) every time — "
        "this is your before-the-report coverage self-check, not just a "
        "record of this batch's decisions."
    ),
    "input_schema": {
        **_BASE_COMMIT_TOOL["input_schema"],
        "properties": {
            **_BASE_COMMIT_TOOL["input_schema"]["properties"],
            **_RELEASE_PROPERTY,
            **_COVERAGE_PROPERTY,
        },
        "required": [
            *_BASE_COMMIT_TOOL["input_schema"]["required"],
            "coverage",
            "ready_to_report",
        ],
    },
}

_DEFAULT_ENGINES_FOR_SEARCH_DEF = ("semantic", "keyword", "hybrid")

_REQUIREMENT_PROPERTY: dict[str, Any] = {
    "requirement": {
        "type": "string",
        "description": (
            "The requirement from the request that this query serves, "
            "quoted or paraphrased in the request's own words — not a "
            "description of the query, and never a candidate answer: if "
            "you are searching for a specific name you expect to be "
            "relevant, that name goes in `query`; the requirement is still "
            "the thing in the request the name would serve. Asking the "
            "same requirement on semantic, keyword, and hybrid is "
            "expected — that is one requirement approached from three "
            "angles, not three requirements. If this requirement already "
            "has committed evidence, do not restate it — say instead what "
            "is specifically still missing from it that this query goes "
            "after. If you cannot name either, the call is a re-search: "
            "spend it on a requirement that has no evidence yet."
        ),
    },
}

_NAMED_CANDIDATE_QUERY_HINT = (
    " When a requirement asks for concrete specifics — named partners, "
    "products, tools, techniques, works, people, events — write one query "
    "naming your own best candidates and one query for the category "
    "around them, so the corpus can both test the candidates you brought "
    "and offer ones you did not think of. `keyword` is the engine for a "
    "named candidate; `semantic` or `hybrid` for the category. A "
    "candidate you supplied is a hypothesis to test here, not a finding "
    "for the report."
)


def build_search_tool_def(engines: list[str] | tuple[str, ...] | None = None
                          ) -> dict[str, Any]:
    """facets_agent's own search tool: agent_harness's shared definition plus
    a required ``requirement`` field, and -- when `keyword` is among the
    enabled engines -- a named-candidate query hint appended to the
    `query` property's own description.

    ENGINE-DEPENDENT, exactly like the base builder it wraps: always call
    this with the run's actual enabled engines, never cache a definition
    built for a different set (see ``agent_harness.agent.run_agent``'s
    ``search_tool_def`` parameter docstring for why).
    """
    base = _base_build_search_tool_def(engines)
    resolved_engines = (list(engines) if engines
                       else list(_DEFAULT_ENGINES_FOR_SEARCH_DEF))
    properties = {**base["input_schema"]["properties"], **_REQUIREMENT_PROPERTY}
    if "keyword" in resolved_engines:
        properties = {
            **properties,
            "query": {
                **properties["query"],
                "description": (
                    properties["query"]["description"] + _NAMED_CANDIDATE_QUERY_HINT
                ),
            },
        }
    return {
        **base,
        "input_schema": {
            **base["input_schema"],
            "properties": properties,
            "required": [*base["input_schema"]["required"], "requirement"],
        },
    }


# A module-level constant purely for gen_arch_viz.py, which introspects tool
# refs via AST and can only literal_eval a module-level assignment, never call
# a function -- mirrors agent_harness.tools.search's own SEARCH_TOOL_DEF constant.
# The real harness always calls build_search_tool_def(engines) with the run's
# actual engine list (see agent.py); this fixed-default rendering is for the
# diagram only and must not be imported by runtime code.
SEARCH_TOOL_DEF: dict[str, Any] = build_search_tool_def(list(_DEFAULT_ENGINES_FOR_SEARCH_DEF))

__all__ = ["COMMIT_CONTEXT_TOOL", "SEARCH_TOOL_DEF", "build_search_tool_def"]
