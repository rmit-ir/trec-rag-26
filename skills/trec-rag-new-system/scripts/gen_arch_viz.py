#!/usr/bin/env python3
"""Generate an interactive architecture visualization of the TREC RAG 2026 systems.

Auto-derives the diagram from source (never imports the modules — pure ``ast``
parsing, so no env/network side effects) and writes a single self-contained
HTML file (inline SVG + vanilla JS + CSS, no server, no CDN).

Two zoom levels in one page:
  - OVERVIEW  — every ``src/systems/<name>`` wired to the shared layers
                (ragrun, tools.search_tool + its 4 selectable engines,
                utils.search dense+sparse RRF, utils.fetch_doc,
                ali_deepresearch.answer_format, agent_harness's run_agent
                loop, agent_harness.agent.make_provider -- kept as its own
                node/edge, distinct from the loop, since facet_rag imports
                ONLY this and never touches the loop, and the MCP server
                o3_deep_research calls over HTTP) and the output artifacts.
                Edges are colored + legended by type.
                A system's edges are expanded one hop through any shared
                layer's OWN imports of another shared layer (see
                ``_shared_internal_edges``), so a system that only imports
                ``agent_harness`` still draws a direct ``search_tool`` edge --
                ``agent_harness.tools.search`` wraps it, and stopping at the
                first hop would draw it as never touching retrieval at all.
                Every shared-rooted import a system (or a shared layer itself)
                makes must resolve to a real edge or an explicit entry in
                ``UNMODELED_SHARED_IMPORTS`` --
                ``tests/arch_viz/test_gen_arch_viz.py`` enforces this, so a
                newly added tool/component fails CI instead of silently
                missing from the diagram.
  - DRILL-IN  — click a system card to see its per-stage pipeline.

Stage flows come from a hand-authored ``STAGE_REGISTRY`` below, OVERRIDDEN per
system by a module-level ``ARCH_STAGES = [...]`` literal if the package declares
one (the scaffolder emits this, so new systems self-describe).

Regenerate (and launch) it whenever a system is added, changed, or run.

Usage (repo root):
    python skills/trec-rag-new-system/scripts/gen_arch_viz.py            # -> docs/architecture.html
    python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open     # + open in browser
    python skills/trec-rag-new-system/scripts/gen_arch_viz.py --system facet_rag
    python skills/trec-rag-new-system/scripts/gen_arch_viz.py --print-model
    python skills/trec-rag-new-system/scripts/gen_arch_viz.py --out /tmp/arch.html
    python skills/trec-rag-new-system/scripts/gen_arch_viz.py --check   # CI/pre-commit gate

Output is byte-deterministic, so ``--check`` is a reliable freshness gate and
regeneration produces clean diffs.
"""
from __future__ import annotations

import argparse
import ast
import json
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
SYSTEMS_DIR = SRC / "systems"
SEARCH_TOOL = SRC / "tools" / "search_tool.py"

# ---------------------------------------------------------------------------
# Shared-layer node catalog (the right-hand side of the overview graph). These
# are stable public surfaces documented in the repo; ``engines`` is read live
# from ENGINE_INFO in tools/search_tool.py so it never drifts.
# ---------------------------------------------------------------------------
SHARED = [
    {"id": "agent_harness", "label": "agent_harness.run_agent",
     "role": "harness", "detail": "shared staged-context tool-calling loop: "
             "ContextLedger + commit_context/get_documents/search tool "
             "builders"},
    {"id": "make_provider", "label": "make_provider",
     "role": "provider", "detail": "agent_harness.agent.make_provider — "
             "pluggable Bedrock/OpenAI backends, usable standalone (facet_rag) "
             "or as what run_agent calls internally"},
    {"id": "mcp_server", "label": "mcp/climbmix_server",
     "role": "mcp", "detail": "src/mcp/climbmix_server.py — MCP server "
             "exposing search + fetch_doc as MCP tools over HTTP. Reached by "
             "URL (--mcp-url/O3DR_MCP_URL), not a Python import, so this edge "
             "is hand-attributed (see MANUAL_EDGES) rather than AST-derived"},
    {"id": "answer_format", "label": "format_answer",
     "role": "answer-format", "detail": "ali_deepresearch.answer_format — prose -> references[] + per-sentence citations"},
    {"id": "search_tool", "label": "tools.search_tool",
     "role": "retrieval", "detail": "run_search_tool / build_search_tool over ClimbMix"},
    {"id": "hybrid_search", "label": "utils.search.search",
     "role": "retrieval", "detail": "concurrent dense + sparse retrieval, fused with RRF"},
    {"id": "fetch_doc", "label": "utils.fetch_doc",
     "role": "fetch-doc", "detail": "fetch_doc(docid) -> full document text"},
    {"id": "ragrun", "label": "ragrun",
     "role": "artifacts", "detail": "TrajectoryBuilder / build_rag_output / validate_rag_output / save_run"},
    {"id": "artifacts", "label": "data/outputs/<system>/",
     "role": "artifacts", "detail": "<ts>.<slug>.trajectory.json (strict) + .output.json (rich)"},
]

# Which owner package each reusable shared symbol lives in — a same-owner import
# is internal (no cross-system edge), a foreign import is a reuse edge.
# ``agent_harness`` needs no entry here: unlike ``answer_format`` (still hosted
# inside a system, ali_deepresearch), it lives in a real top-level package, so
# every importer — aus_agent included — draws a genuine cross-layer edge, with
# no self-import case to suppress.
OWNERS = {"answer_format": "ali_deepresearch"}

# Edges that exist but can never be AST-derived, because the dependency isn't
# a Python import: o3_deep_research reaches the MCP server by URL
# (--mcp-url/O3DR_MCP_URL) over HTTP, not `import`. Hand-maintained like
# STAGE_REGISTRY/SYSTEM_BLURB below -- update this when a system starts (or
# stops) calling an external service the same way.
MANUAL_EDGES: dict[str, list[dict[str, str]]] = {
    "o3_deep_research": [{"to": "mcp_server", "type": "mcp"}],
}

# ---------------------------------------------------------------------------
# Hand-authored stage flows for the current systems (see each README/pipeline).
# A package's own ARCH_STAGES literal, if present, overrides its entry here.
# stage.kind in {llm, no-llm, retrieval, format, artifact, loop}.
# ---------------------------------------------------------------------------
STAGE_REGISTRY: dict[str, list[dict[str, Any]]] = {
    "facet_rag": [
        {"id": "plan", "label": "PLAN", "kind": "llm",
         "note": "orchestrator, 1 turn: narrative -> facets JSON",
         "prompt": ["systems/facet_rag/prompts.py::PLAN_PROMPT"],
         "code": ["systems/facet_rag/planner.py::build_plan_prompt",
                  "systems/facet_rag/planner.py::parse_facets"]},
        {"id": "facet_loop", "label": "FACET LOOP", "kind": "loop",
         "note": "per facet, concurrent threads, <=10 iterations",
         "back_to": "search", "back_from": "curate",
         "back_label": "repeat until curator covered / cap",
         "parallel_over": "facet",
         "code": ["systems/facet_rag/pipeline.py::run_one"],
         "tools_note": "facets run concurrently in a ThreadPoolExecutor "
                        "(pipeline.run_one); each facet's own loop is capped "
                        "by planner.GLOBAL_ITERATION_CAP"},
        {"id": "search", "label": "SEARCH", "kind": "retrieval",
         "note": "orchestrator query-plan JSON: 1+ query per mandatory engine",
         "prompt": ["systems/facet_rag/prompts.py::ORCHESTRATOR_QUERY_PROMPT"],
         "code": ["systems/facet_rag/loop.py::run_facet_loop",
                  "tools/search_tool.py::run_search_tool"],
         "engines": {"mandatory": "systems/facet_rag/loop.py::MANDATORY_ENGINES",
                     "optional": "systems/facet_rag/loop.py::BOOLEAN_ENGINES"},
         "tools_note": "NOT native tool-calling — gpt-oss-120b via Bedrock "
                        "Converse never batched more than one search call per "
                        "turn, so the code executes every query in the parsed "
                        "JSON plan unconditionally (see loop.py module "
                        "docstring)"},
        {"id": "analyze", "label": "ANALYZE", "kind": "llm",
         "note": "analyzer judges new passages, keeps relevant + note",
         "prompt": ["systems/facet_rag/prompts.py::ANALYZER_PROMPT"],
         "code": ["systems/facet_rag/loop.py::parse_analysis"]},
        {"id": "curate", "label": "CURATE", "kind": "llm",
         "note": "curator ranks full pool by relevance+diversity (MMR); "
                 "top-N -> synthesis, covered? -> stop",
         "prompt": ["systems/facet_rag/prompts.py::CURATOR_PROMPT"],
         "code": ["systems/facet_rag/curator.py::curate",
                  "systems/facet_rag/curator.py::parse_curation"]},
        {"id": "draft", "label": "DRAFT", "kind": "llm",
         "note": "orchestrator: merged evidence -> cited prose",
         "prompt": ["systems/facet_rag/prompts.py::SYNTH_DRAFT_PROMPT"],
         "code": ["systems/facet_rag/pipeline.py::run_one"]},
        {"id": "fact_check", "label": "FACT-CHECK", "kind": "llm",
         "note": "analyzer: patches unsupported citations",
         "prompt": ["systems/facet_rag/prompts.py::FACT_CHECK_PROMPT"],
         "code": ["systems/facet_rag/pipeline.py::run_one"]},
        {"id": "format", "label": "FORMAT", "kind": "format",
         "note": "answer_format: prose -> references[] + citations",
         "prompt": ["systems/ali_deepresearch/prompts.py::FORMAT_ANSWER_PROMPT"],
         "code": ["systems/ali_deepresearch/answer_format.py::format_answer"]},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run -> trajectory + output",
         "code": ["ragrun/outputs.py::save_run"]},
    ],
    "ali_deepresearch": [
        {"id": "loop", "label": "ReAct LOOP", "kind": "loop",
         "note": "per turn until <answer>",
         # THINK -> TOOL_CALL -> THINK; ANSWER exits the loop, and FORMAT/SAVE
         # run exactly once after it.
         "back_to": "think", "back_from": "tool_call",
         "back_label": "repeat until <answer>",
         "tools": [{"name": "search", "ref": "systems/ali_deepresearch/tools.py::ClimbMixTools.search"},
                   {"name": "get_document", "ref": "systems/ali_deepresearch/tools.py::ClimbMixTools.get_document"}],
         "tools_note": "advertised in-band inside SYSTEM_PROMPT's <tools> "
                        "block, not via a native tools param"},
        {"id": "think", "label": "THINK", "kind": "llm",
         "note": "<think> -> reasoning step",
         "prompt": ["systems/ali_deepresearch/prompts.py::SYSTEM_PROMPT"],
         "code": ["systems/ali_deepresearch/react_agent.py::ReactAgent.run"]},
        {"id": "tool_call", "label": "TOOL_CALL", "kind": "retrieval",
         "note": "<tool_call> -> hybrid RRF search / fetch_doc",
         "code": ["systems/ali_deepresearch/react_agent.py::ReactAgent._handle_tool_call",
                  "systems/ali_deepresearch/tools.py::dispatch"]},
        {"id": "answer", "label": "ANSWER", "kind": "llm",
         "note": "<answer> -> final text",
         "prompt": ["systems/ali_deepresearch/prompts.py::SYSTEM_PROMPT"],
         "code": ["systems/ali_deepresearch/react_agent.py::ReactAgent._force_final_answer"]},
        {"id": "format", "label": "FORMAT", "kind": "format",
         "note": "answer_format: -> references[] + citations",
         "prompt": ["systems/ali_deepresearch/prompts.py::FORMAT_ANSWER_PROMPT"],
         "code": ["systems/ali_deepresearch/answer_format.py::format_answer"]},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run",
         "code": ["ragrun/outputs.py::save_run"]},
    ],
    "aus_agent": [
        {"id": "loop", "label": "TURN LOOP", "kind": "loop",
         "note": "staged-context state machine",
         # The model turn is the top of the cycle: REASON/COMMIT decides whether
         # to search again (back to SEARCH) or write the report, so the arrow
         # runs commit -> search. FINAL PROSE / MAP CITES / SAVE are post-loop.
         "back_to": "search", "back_from": "commit",
         "back_label": "repeat until report",
         "code": ["agent_harness/agent.py::run_agent"],
         "tools": [{"name": "search", "ref": "agent_harness/tools/search.py::SEARCH_TOOL_DEF"},
                   {"name": "get_documents", "ref": "agent_harness/tools/get_documents.py::GET_DOCUMENTS_TOOL"},
                   {"name": "commit_context", "ref": "agent_harness/tools/commit_context.py::COMMIT_CONTEXT_TOOL"}],
         "tools_note": "native Bedrock Converse toolConfig, passed once to "
                        "provider.start (agent.run_agent: "
                        "build_search_tool_def(engines) + GET_DOCUMENTS_TOOL "
                        "+ COMMIT_CONTEXT_TOOL)"},
        {"id": "search", "label": "SEARCH", "kind": "retrieval",
         "note": "full-text search; results staged",
         "code": ["agent_harness/tools/search.py::execute_full_text_search"]},
        {"id": "stage", "label": "STAGE", "kind": "no-llm",
         "note": "stage evidence; commit-before-expire protocol",
         "code": ["agent_harness/context.py::ContextLedger.stage"]},
        {"id": "commit", "label": "REASON/COMMIT", "kind": "llm",
         "note": "model turn commits selected evidence",
         "prompt": ["systems/aus_agent/prompts/system/default.md",
                    "agent_harness/agent.py::TASK_PROMPT"],
         "code": ["agent_harness/tools/commit_context.py::apply_commit",
                  "agent_harness/context.py::ContextLedger.commit"]},
        {"id": "final", "label": "FINAL PROSE", "kind": "llm",
         "note": "grounded prose with inline citations",
         "prompt": ["systems/aus_agent/prompts/system/default.md"],
         "tools_note": "same conversation as the loop — the report is a turn, "
                        "not a new call"},
        {"id": "map", "label": "MAP CITES", "kind": "format",
         "note": "docid -> reference-index mapping",
         "code": ["agent_harness/agent.py::_map_citations"]},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run",
         "code": ["ragrun/outputs.py::save_run"]},
    ],
    "o3_deep_research": [
        {"id": "research", "label": "DEEP RESEARCH", "kind": "llm",
         "note": "hosted DeepResearch + MCP over ClimbMix",
         "prompt": ["systems/o3_deep_research/run.py::SYSTEM_PROMPT"],
         "code": ["systems/o3_deep_research/run.py::run_one"],
         "tools_note": "hosted MCP tool block built at runtime in run_one "
                        "(server_url + optional bearer header)"},
        {"id": "format", "label": "FORMAT", "kind": "format",
         "note": "answer_format: -> references[] + citations",
         "prompt": ["systems/ali_deepresearch/prompts.py::FORMAT_ANSWER_PROMPT"],
         "code": ["systems/ali_deepresearch/answer_format.py::format_answer"]},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run",
         "code": ["ragrun/outputs.py::save_run"]},
    ],
    "claude-code-research": [
        {"id": "workflow", "label": "WORKFLOW", "kind": "no-llm",
         "note": "workflow-driven (scripts/ + tasks/), no python pipeline package"},
    ],
}

SYSTEM_KIND = {
    "facet_rag": "agent",
    "ali_deepresearch": "agent",
    "aus_agent": "agent",
    "facets_agent": "agent",
    "brief_revise_agent": "agent",
    "o3_deep_research": "single-file",
    "claude-code-research": "manual",
}

SYSTEM_BLURB = {
    "facet_rag": "orchestrator (gpt-oss) plans + searches, analyzer (Qwen) "
                 "judges + fact-checks, per-facet loops run concurrently",
    "ali_deepresearch": "Alibaba Tongyi DeepResearch ReAct port; owns answer_format",
    "aus_agent": "staged-context research agent; its own prompt/*.md variants "
                 "configuring the shared agent_harness loop",
    "facets_agent": "gpt-5.6-luna on the shared agent_harness loop, minimal "
                    "prompt covering facet_rag's process (decompose, "
                    "multi-engine per facet, curate, self-check)",
    "brief_revise_agent": "fork of aus_agent (same harness config, same "
                          "prompt) plus a pre-flight requirements brief "
                          "appended to the system prompt and one grounded "
                          "review-and-revise pass on pre_final_hook",
    "o3_deep_research": "minimal single-file runner (hosted DR + MCP)",
    "claude-code-research": "workflow-driven research (no python pipeline package)",
}


# ---------------------------------------------------------------------------
# AST extraction (no imports).
# ---------------------------------------------------------------------------
def _imported_names(py: Path) -> dict[str, set[str]]:
    """Map each absolute ``from X import a, b`` module to the names pulled from
    it (empty set for a bare ``import X``). Module-level granularity alone
    can't tell ``from agent_harness.agent import make_provider`` apart from
    ``... import run_agent`` -- two very different relationships that happen
    to share a module string -- so ``_edges_for_system`` needs the names too.
    """
    out: dict[str, set[str]] = {}
    try:
        tree = ast.parse(py.read_text(), filename=str(py))
    except (SyntaxError, UnicodeDecodeError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.setdefault(node.module, set()).update(
                alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.setdefault(alias.name, set())
    return out


def _arch_stages_override(pkg: Path) -> list[dict[str, Any]] | None:
    """Find a module-level ``ARCH_STAGES = [ {..}, .. ]`` literal in any package .py."""
    for py in sorted(pkg.glob("*.py")):
        try:
            tree = ast.parse(py.read_text(), filename=str(py))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "ARCH_STAGES":
                        try:
                            val = ast.literal_eval(node.value)
                        except (ValueError, SyntaxError):
                            return None
                        if isinstance(val, list) and all(isinstance(x, dict) for x in val):
                            try:
                                json.dumps(val)
                            except TypeError:
                                print(f"gen_arch_viz: {py} ARCH_STAGES has a "
                                      f"non-JSON-serializable value, ignoring override")
                                return None
                            return val
    return None


def _classify_import(name: str, mod: str, imported: set[str]
                     ) -> list[tuple[str, str]]:
    """One import (module + the names pulled from it) -> zero or more
    ``(shared_node_id, edge_type)`` pairs. Split out of ``_edges_for_system``
    so the completeness check in ``tests/arch_viz`` can call it per-import
    too (an import this returns nothing for, and that isn't in
    ``UNMODELED_SHARED_IMPORTS``, is a real gap: a shared-layer import the
    diagram doesn't know how to draw).
    """
    if mod == "ragrun" or mod.startswith("ragrun."):
        return [("ragrun", "artifacts")]
    if mod == "tools.search_tool":
        return [("search_tool", "retrieval")]
    if mod == "utils.search":
        return [("hybrid_search", "retrieval")]
    if mod == "utils.fetch_doc":
        return [("fetch_doc", "fetch-doc")]
    if mod.startswith("ali_deepresearch.answer_format") or \
            mod.startswith("systems.ali_deepresearch.answer_format"):
        return [] if OWNERS["answer_format"] == name else \
            [("answer_format", "answer-format")]
    if mod == "agent_harness.agent":
        # Same module, two very different relationships: make_provider is a
        # standalone factory (facet_rag uses ONLY this, never the loop), the
        # rest (run_agent, DEFAULT_*, ...) is the staged-context harness
        # itself. Route each name actually imported to its own edge rather
        # than bucketing both under one node.
        out: list[tuple[str, str]] = []
        if "make_provider" in imported:
            out.append(("make_provider", "provider"))
        if not imported or imported - {"make_provider"}:
            out.append(("agent_harness", "harness"))
        return out
    if mod == "agent_harness" or mod.startswith("agent_harness."):
        return [("agent_harness", "harness")]
    return []


# Shared-rooted imports that are real but deliberately NOT their own overview
# node -- low-level plumbing (env var reader, HTTP retry, hit-shape helper) or
# an engine module only ever reached through tools.search_tool/utils.search,
# never imported by a system directly (see ``_shared_internal_edges``'s
# docstring for why that specific chain isn't propagated either). Add here,
# with a one-line reason, rather than silencing the completeness check
# blindly -- see ``tests/arch_viz/test_gen_arch_viz.py::test_...`` for what
# happens when neither this nor ``_classify_import`` recognizes an import.
UNMODELED_SHARED_IMPORTS = {
    "utils.env": "env-var reader, not an architectural component",
    "utils.http_retry": "internal retry/backoff plumbing behind every hosted call",
    "utils.search_types": "SearchHit dataclass + id-shape helpers, not a node",
    "utils.search_dense": "engine impl, reached only via tools.search_tool/utils.search",
    "utils.search_sparse": "engine impl, reached only via tools.search_tool/utils.search",
    "utils.search_lucene_bool": "engine impl, reached only via tools.search_tool/utils.search",
    "utils.search_ssr": "engine impl, reached only via tools.search_tool/utils.search",
    "utils.ssr_hydrate": "SSR-only helper, not imported outside utils.search_ssr",
    "agent_harness.providers.base": "the Provider ABC -- providers are reached via make_provider, never subclassed directly by a system",
}


def _edges_for_system(name: str, py_files: list[Path]) -> list[dict[str, str]]:
    """Classify shared-layer edges from a system's import statements."""
    seen: set[tuple[str, str]] = set()
    edges: list[dict[str, str]] = []

    def add(to: str, typ: str) -> None:
        key = (to, typ)
        if key not in seen:
            seen.add(key)
            edges.append({"to": to, "type": typ})

    # sorted() on both the file list and the module set is what makes the output
    # byte-deterministic — a set's iteration order varies run to run (string hash
    # randomization), which would break --check and produce noisy diffs.
    for py in sorted(py_files):
        imports = _imported_names(py)
        for mod in sorted(imports):
            for to, typ in _classify_import(name, mod, imports[mod]):
                add(to, typ)
    return edges


def _read_engines() -> list[dict[str, str]]:
    """Read ENGINE_INFO (names + blurbs) from tools/search_tool.py via AST."""
    engines: list[dict[str, str]] = []
    tree = ast.parse(SEARCH_TOOL.read_text(), filename=str(SEARCH_TOOL))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "ENGINE_INFO" and node.value is not None:
            info = ast.literal_eval(node.value)
            for eid, meta in info.items():
                blurb = str(meta.get("blurb", "")).replace("\n", " ")
                # keep the short head of the blurb (before the first colon detail)
                engines.append({"id": eid, "label": eid, "blurb": " ".join(blurb.split())})
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "ENGINE_INFO":
                    info = ast.literal_eval(node.value)
                    for eid, meta in info.items():
                        blurb = str(meta.get("blurb", "")).replace("\n", " ")
                        engines.append({"id": eid, "label": eid,
                                        "blurb": " ".join(blurb.split())})
    return engines


def _split_ref(ref: str) -> tuple[Path, str | None]:
    """Split ``<path-relative-to-src>[::<Symbol>[.<attr>]]`` into (path, symbol)."""
    path_part, _, symbol = ref.partition("::")
    path = SRC / path_part
    if not path.exists():
        raise SystemExit(f"gen_arch_viz: unresolvable ref {ref!r} (no such file {path})")
    return path, (symbol or None)


def _module_value_soft(ref: str) -> Any | None:
    """literal_eval the RHS of a module-level ``NAME = <literal>``/``NAME: T = <literal>``.

    Returns ``None`` (not an error) when the name exists but its RHS isn't a
    literal (e.g. built by a function call) -- callers that can render a
    "built at runtime" fallback want that distinguished from "doesn't exist".
    Raises if the name has no module-level assignment at all, since that
    means the ref rotted (renamed/removed) and generation should fail loudly.
    """
    path, symbol = _split_ref(ref)
    if symbol is None or "." in symbol:
        raise SystemExit(f"gen_arch_viz: {ref!r} is not a bare module-level constant ref")
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id == symbol:
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        return None
    raise SystemExit(f"gen_arch_viz: unresolvable ref {ref!r} (no module-level "
                      f"{symbol!r} in {path})")


def _module_value(ref: str) -> Any:
    """Like ``_module_value_soft`` but requires the RHS to actually be a literal."""
    val = _module_value_soft(ref)
    if val is None:
        raise SystemExit(f"gen_arch_viz: {ref!r} RHS is not a literal")
    return val


def _symbol_exists(ref: str) -> bool:
    """True if ``path::Name`` or ``path::Class.method`` names a real def/class/const."""
    path, symbol = _split_ref(ref)
    if symbol is None:
        return True  # bare file ref -- existence of the file already checked
    tree = ast.parse(path.read_text(), filename=str(path))
    owner, _, attr = symbol.partition(".")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name == owner:
            if not attr:
                return True
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and sub.name == attr:
                    return True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and not attr:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id == owner:
                    return True
    return False


def _code_ref(ref: str) -> str:
    """Verify a code ref resolves to a real def/class/const; return it unchanged."""
    if not _symbol_exists(ref):
        raise SystemExit(f"gen_arch_viz: unresolvable code ref {ref!r}")
    return ref


def _prompt_text(ref: str) -> str:
    """Read a prompt ref's text: the whole file for a bare path, else the literal string RHS."""
    path, symbol = _split_ref(ref)
    if symbol is None:
        return path.read_text()
    val = _module_value(ref)
    if not isinstance(val, str):
        raise SystemExit(f"gen_arch_viz: prompt ref {ref!r} is not a string literal")
    return val


def _normalize_stage(stg: dict[str, Any], prompts: dict[str, str]) -> dict[str, Any]:
    """Resolve a STAGE_REGISTRY/ARCH_STAGES entry's optional detail keys.

    Verifies every ``code``/``prompt``/``tools``/``engines`` ref against the
    actual source (raises loudly on a rename/removal instead of silently
    showing stale detail), inlines prompt text into the shared top-level
    ``prompts`` dict (deduped by ref, since one prompt can back >1 stage), and
    derives ``run`` (``llm``/``code``/``llm+code``) from which of ``prompt``/
    ``code`` the stage actually declares -- see worklog for why this is
    derived rather than hand-authored.
    """
    out = dict(stg)

    code_refs = out.get("code") or []
    for ref in code_refs:
        _code_ref(ref)

    prompt_refs = out.get("prompt") or []
    for ref in prompt_refs:
        if ref not in prompts:
            prompts[ref] = _prompt_text(ref)

    if prompt_refs and code_refs:
        out["run"] = "llm+code"
    elif prompt_refs:
        out["run"] = "llm"
    elif code_refs:
        out["run"] = "code"

    tools: list[dict[str, str]] = []
    for t in out.get("tools") or []:
        ref = t["ref"]
        _, symbol = _split_ref(ref)
        # dotted refs (Class.method) are code, never a module-level literal
        val = _module_value_soft(ref) if symbol and "." not in symbol else None
        if isinstance(val, dict):
            if val.get("name") not in (None, t["name"]):
                raise SystemExit(f"gen_arch_viz: tool ref {ref!r} name "
                                  f"{val.get('name')!r} != declared {t['name']!r}")
            desc = str(val.get("description", ""))
        else:
            _code_ref(ref)  # still verify the symbol itself exists
            desc = ""
        tools.append({"name": t["name"], "ref": ref, "desc": desc, "group": "tool"})

    engines = out.get("engines")
    if engines:
        mandatory_ref = engines["mandatory"]
        for eid in _module_value(mandatory_ref):
            tools.append({"name": eid, "ref": mandatory_ref, "desc": "",
                          "group": "mandatory engine"})
        optional_ref = engines.get("optional")
        if optional_ref:
            for eid in _module_value(optional_ref):
                tools.append({"name": eid, "ref": optional_ref, "desc": "",
                              "group": "optional engine"})

    if tools:
        out["tools"] = tools
    else:
        out.pop("tools", None)
    out.pop("engines", None)

    return out


def _shared_internal_edges() -> dict[str, list[dict[str, str]]]:
    """Shared layers can themselves depend on other shared layers (e.g.
    ``agent_harness.tools.search`` wraps ``tools.search_tool``). Computed the
    same way as a system's own edges, scoped to shared-node targets only, so
    a consumer's edge list can be expanded to the real transitive dependency
    instead of stopping at the first shared hop (see ``build_model``).
    """
    shared_ids = {s["id"] for s in SHARED}
    internal: dict[str, list[dict[str, str]]] = {}
    for sid in shared_ids:
        pkg_dir = SRC / sid
        if not pkg_dir.is_dir():
            continue
        scan = [p for p in pkg_dir.rglob("*.py") if "__pycache__" not in p.parts]
        edges = [e for e in _edges_for_system(sid, scan) if e["to"] in shared_ids]
        if edges:
            internal[sid] = edges
    return internal


def build_model() -> dict[str, Any]:
    systems: list[dict[str, Any]] = []
    prompts: dict[str, str] = {}
    shared_internal = _shared_internal_edges()
    for pkg in sorted(p for p in SYSTEMS_DIR.iterdir() if p.is_dir()):
        name = pkg.name
        if name == "__pycache__":
            continue
        py_files = sorted(pkg.glob("*.py"))
        modules = [p.stem for p in py_files]
        stages_raw = _arch_stages_override(pkg) or STAGE_REGISTRY.get(name) \
            or [{"id": "run", "label": "RUN", "kind": "no-llm", "note": ""}]
        stages = [_normalize_stage(s, prompts) for s in stages_raw]
        # scan the whole package tree (subpackages like tools/, providers/ hold
        # the retrieval/provider imports), skipping caches.
        scan = [p for p in pkg.rglob("*.py") if "__pycache__" not in p.parts]
        edges = _edges_for_system(name, scan)
        # Expand one hop through shared-to-shared deps (e.g. a system that only
        # reaches agent_harness also really reaches search_tool through it) --
        # a fixpoint loop rather than one pass, so a future multi-hop shared
        # chain still resolves fully instead of silently stopping short.
        seen = {(e["to"], e["type"]) for e in edges}
        frontier = list(edges)
        while frontier:
            next_frontier = []
            for e in frontier:
                for extra in shared_internal.get(e["to"], []):
                    key = (extra["to"], extra["type"])
                    if key not in seen:
                        seen.add(key)
                        edges.append(extra)
                        next_frontier.append(extra)
            frontier = next_frontier
        for extra in MANUAL_EDGES.get(name, []):
            key = (extra["to"], extra["type"])
            if key not in seen:
                seen.add(key)
                edges.append(extra)
        systems.append({
            "name": name,
            "kind": SYSTEM_KIND.get(name, "pipeline"),
            "modules": modules,
            "blurb": SYSTEM_BLURB.get(name, ""),
            "stages": stages,
            "edges": edges,
        })
    return {
        "generated_from": "src/systems + shared layers (ragrun, tools, utils)",
        "systems": systems,
        "shared": SHARED,
        "engines": _read_engines(),
        "prompts": prompts,
    }


# ---------------------------------------------------------------------------
# HTML rendering. Deterministic layered layout is computed in-browser from the
# model (no RNG), so the file is a thin shell around the model JSON.
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TREC RAG 2026 — Systems Architecture</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f7f8fa; --panel: #ffffff; --ink: #1c2128; --muted: #5b6673;
    --line: #d3d8de; --card: #eef1f5; --cardstroke: #b9c2cc;
    --accent: #3d5afe;
    /* edge type palette (brand-neutral, >=3:1 vs bg, distinguishable) */
    --e-retrieval: #1a7f6b; --e-artifacts: #b45309; --e-answer-format: #7c3aed;
    --e-provider: #2563eb; --e-fetch-doc: #0891b2; --e-harness: #be185d;
    --e-mcp: #65a30d;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1216; --panel: #171b21; --ink: #e6edf3; --muted: #9aa7b4;
      --line: #2a323c; --card: #1e242c; --cardstroke: #3a4552;
      --accent: #7c8cff;
      --e-retrieval: #2dd4bf; --e-artifacts: #f59e0b; --e-answer-format: #a78bfa;
      --e-provider: #60a5fa; --e-fetch-doc: #22d3ee; --e-harness: #f472b6;
      --e-mcp: #a3e635;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI",
         Roboto, Helvetica, Arial, sans-serif; background: var(--bg); color: var(--ink); }
  header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
           padding: 14px 20px; border-bottom: 1px solid var(--line); background: var(--panel); }
  header h1 { font-size: 16px; margin: 0; }
  header .sub { color: var(--muted); font-size: 12px; }
  header .spacer { flex: 1; }
  button { font: inherit; color: var(--ink); background: var(--card);
           border: 1px solid var(--cardstroke); border-radius: 6px;
           padding: 5px 10px; cursor: pointer; }
  button:hover { border-color: var(--accent); }
  #legend { display: flex; gap: 14px; flex-wrap: wrap; padding: 8px 20px;
            border-bottom: 1px solid var(--line); font-size: 12px; color: var(--muted); }
  #legend .lg { display: inline-flex; align-items: center; gap: 6px; }
  #legend .sw { width: 22px; height: 3px; border-radius: 2px; display: inline-block; }
  #wrap { position: relative; }
  svg { width: 100%; height: calc(100vh - 96px); display: block; }
  .card { cursor: pointer; }
  .card rect { fill: var(--card); stroke: var(--cardstroke); stroke-width: 1.5; rx: 10; }
  .card:hover rect, .card:focus rect { stroke: var(--accent); stroke-width: 2.5; }
  .card .title { font-weight: 600; }
  .node rect { fill: var(--panel); stroke: var(--line); stroke-width: 1.5; rx: 8; }
  .lbl { fill: var(--ink); }
  .sub2 { fill: var(--muted); font-size: 11px; }
  .edge { fill: none; stroke-width: 2; opacity: .85; }
  .edge.dim { opacity: .12; }
  .engine rect { fill: var(--panel); stroke: var(--line); rx: 6; }
  .hint { fill: var(--muted); font-size: 11px; }
  #tip { position: absolute; pointer-events: none; background: var(--panel);
         border: 1px solid var(--cardstroke); border-radius: 6px; padding: 6px 9px;
         font-size: 12px; max-width: 320px; color: var(--ink); box-shadow: 0 4px 14px rgba(0,0,0,.18);
         opacity: 0; transition: opacity .1s; }
  .stage { cursor: pointer; }
  .stage rect { rx: 9; stroke-width: 2; }
  .stage:hover rect, .stage:focus rect { stroke-width: 3.5; }
  .k-llm      { fill: color-mix(in srgb, var(--e-provider) 18%, var(--panel)); stroke: var(--e-provider); }
  .k-retrieval{ fill: color-mix(in srgb, var(--e-retrieval) 18%, var(--panel)); stroke: var(--e-retrieval); }
  .k-format   { fill: color-mix(in srgb, var(--e-answer-format) 18%, var(--panel)); stroke: var(--e-answer-format); }
  .k-artifact { fill: color-mix(in srgb, var(--e-artifacts) 18%, var(--panel)); stroke: var(--e-artifacts); }
  .k-loop     { fill: var(--card); stroke: var(--accent); stroke-dasharray: 5 4; }
  .k-no-llm   { fill: var(--card); stroke: var(--cardstroke); }
  .runbadge   { fill: var(--muted); font-weight: 700; letter-spacing: .4px; }
  .loop-rect  { fill: none; stroke: var(--accent); stroke-dasharray: 6 5; stroke-width: 1.5; }
  .loop-rect.ghost1 { opacity: .35; }
  .loop-rect.ghost2 { opacity: .2; }
  .loop-label { fill: var(--muted); font-size: 11px; font-weight: 600; }
  #detail { position: fixed; top: 0; right: 0; width: min(440px, 45vw); height: 100%;
            overflow-y: auto; background: var(--panel); border-left: 1px solid var(--line);
            padding: 16px; box-shadow: -6px 0 18px rgba(0,0,0,.15); z-index: 5; }
  #detail[hidden] { display: none; }
  #detail h2 { margin: 4px 0 2px; font-size: 15px; }
  #detail h3 { margin: 14px 0 4px; font-size: 11px; letter-spacing: .6px; color: var(--muted);
               text-transform: uppercase; }
  #detail p { margin: 4px 0; font-size: 12px; }
  #detail pre { white-space: pre-wrap; font-size: 11px; background: var(--card);
                border: 1px solid var(--line); border-radius: 6px; padding: 8px;
                max-height: 280px; overflow: auto; margin: 4px 0 10px; }
  #detail code { font-size: 11px; color: var(--muted); word-break: break-all; }
  #detail ul { font-size: 12px; margin: 2px 0 0 18px; padding: 0; }
  #detail-close { position: absolute; top: 10px; right: 10px; padding: 2px 9px; }
</style>
</head>
<body>
<header>
  <h1>TREC RAG 2026 — Systems Architecture</h1>
  <span class="sub" id="crumb">overview</span>
  <span class="spacer"></span>
  <button id="back" style="display:none">&larr; Back to overview</button>
  <span class="sub">auto-derived from <code>src/systems</code> + shared layers</span>
</header>
<div id="legend"></div>
<div id="wrap">
  <svg id="stage" xmlns="http://www.w3.org/2000/svg"></svg>
  <div id="tip"></div>
  <aside id="detail" hidden>
    <button id="detail-close" aria-label="Close detail">&times;</button>
    <div id="detail-body"></div>
  </aside>
</div>

<script id="arch-model" type="application/json">__MODEL_JSON__</script>
<script>
const MODEL = JSON.parse(document.getElementById('arch-model').textContent);
const SVG_NS = 'http://www.w3.org/2000/svg';
const svg = document.getElementById('stage');
const tip = document.getElementById('tip');
const crumb = document.getElementById('crumb');
const backBtn = document.getElementById('back');
const detail = document.getElementById('detail');
const detailBody = document.getElementById('detail-body');
const ENGINE_BLURB = Object.fromEntries(MODEL.engines.map(e => [e.id, e.blurb]));

const EDGE_TYPES = [
  ['retrieval','Retrieval (search layers)'],
  ['fetch-doc','fetch_doc'],
  ['answer-format','answer_format (reuse)'],
  ['harness','agent_harness (reuse)'],
  ['provider','make_provider (reuse)'],
  ['mcp','MCP server (HTTP, hand-attributed)'],
  ['artifacts','Artifacts (ragrun)'],
];
const edgeColor = t => getComputedStyle(document.documentElement)
  .getPropertyValue('--e-' + t).trim() || 'gray';

function el(name, attrs = {}, text) {
  const e = document.createElementNS(SVG_NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}
function clear(n){ while(n.firstChild) n.removeChild(n.firstChild); }

// view is 'overview' or 'system' -- the drill-in legend swaps edge-type swatches
// for the run-class / loop-grouping key, since neither applies to the other view.
function buildLegend(view) {
  const box = document.getElementById('legend');
  clear(box);
  if (view === 'system') {
    ['LLM = calls a model', 'CODE = deterministic', 'LLM+CODE = both',
     'dashed box = loop span', 'stacked box = runs concurrently'].forEach(t => {
      const s = document.createElement('span'); s.className = 'lg'; s.textContent = t;
      box.appendChild(s);
    });
    return;
  }
  for (const [t, label] of EDGE_TYPES) {
    const s = document.createElement('span'); s.className = 'lg';
    const sw = document.createElement('span'); sw.className = 'sw';
    sw.style.background = edgeColor(t);
    s.appendChild(sw); s.appendChild(document.createTextNode(label));
    box.appendChild(s);
  }
  const hint = document.createElement('span'); hint.className = 'lg';
  hint.textContent = 'Click a system to drill into its pipeline.';
  box.appendChild(hint);
}

function showTip(evt, html) {
  tip.innerHTML = html;
  const r = svg.getBoundingClientRect();
  tip.style.left = (evt.clientX - r.left + 14) + 'px';
  tip.style.top  = (evt.clientY - r.top + 12) + 'px';
  tip.style.opacity = 1;
}
function hideTip(){ tip.style.opacity = 0; }

// ---- DETAIL PANEL (click-to-open, change #1 + #4) -------------------------
function closeDetail(){ detail.hidden = true; }
document.getElementById('detail-close').addEventListener('click', closeDetail);

// A stage lies inside a system's loop when its index falls within the loop's
// declared [back_to, back_from] span -- same span the bounding rect draws.
function findEnclosingLoop(sys, stg) {
  const lp = sys.stages.find(s => s.kind === 'loop');
  if (!lp || !lp.back_from || lp.id === stg.id) return null;
  const idx = id => sys.stages.findIndex(s => s.id === id);
  const from = idx(lp.back_from), to = lp.back_to ? idx(lp.back_to) : -1;
  const cur = idx(stg.id);
  return (from >= 0 && to >= 0 && cur >= to && cur <= from) ? lp : null;
}

function renderToolList(container, tools) {
  const groups = {};
  tools.forEach(t => { (groups[t.group] = groups[t.group] || []).push(t); });
  for (const group in groups) {
    const h = document.createElement('div'); h.className = 'hint'; h.style.marginTop = '6px';
    h.textContent = group + (groups[group].length > 1 ? 's' : '') + ':';
    container.appendChild(h);
    const ul = el2('ul');
    groups[group].forEach(t => {
      const li = el2('li');
      const b = el2('b'); b.textContent = t.name; li.appendChild(b);
      const desc = t.desc || (t.group === 'tool' ? 'schema built at runtime — see ' + t.ref
                                                  : (ENGINE_BLURB[t.name] || ''));
      if (desc) li.appendChild(document.createTextNode(' — ' + desc));
      ul.appendChild(li);
    });
    container.appendChild(ul);
  }
}
function el2(tag){ return document.createElement(tag); }

function showDetail(sys, stg) {
  clear(detailBody);
  detailBody.appendChild(Object.assign(el2('h2'), { textContent: stg.label }));
  const meta = el2('div'); meta.className = 'sub2';
  meta.textContent = stg.kind + (stg.run ? ' · ' + stg.run.toUpperCase() : '');
  detailBody.appendChild(meta);
  if (stg.note) detailBody.appendChild(Object.assign(el2('p'), { textContent: stg.note }));

  if (stg.prompt && stg.prompt.length) {
    detailBody.appendChild(Object.assign(el2('h3'), { textContent: 'Prompt' }));
    stg.prompt.forEach(ref => {
      detailBody.appendChild(Object.assign(el2('code'), { textContent: ref }));
      const pre = el2('pre'); pre.textContent = MODEL.prompts[ref] || '(prompt text unavailable)';
      detailBody.appendChild(pre);
    });
  }
  if (stg.code && stg.code.length) {
    detailBody.appendChild(Object.assign(el2('h3'), { textContent: 'Code' }));
    const ul = el2('ul');
    stg.code.forEach(ref => {
      const li = el2('li'); li.appendChild(Object.assign(el2('code'), { textContent: ref }));
      ul.appendChild(li);
    });
    detailBody.appendChild(ul);
  }

  const ownTools = stg.tools || [];
  const lp = findEnclosingLoop(sys, stg);
  const loopTools = (lp && lp.tools) ? lp.tools : [];
  if (ownTools.length || loopTools.length) {
    detailBody.appendChild(Object.assign(el2('h3'), { textContent: 'Tools / Engines' }));
    if (ownTools.length) renderToolList(detailBody, ownTools);
    if (loopTools.length) {
      const h4 = el2('div'); h4.className = 'hint'; h4.style.marginTop = '6px';
      h4.textContent = 'available in ' + lp.label + ':';
      detailBody.appendChild(h4);
      renderToolList(detailBody, loopTools);
    }
  }
  const note = stg.tools_note || (lp && lp.tools_note);
  if (note) detailBody.appendChild(Object.assign(el2('p'), { className: 'hint', textContent: note }));

  detail.hidden = false;
}

// ---- OVERVIEW ------------------------------------------------------------
function drawOverview() {
  crumb.textContent = 'overview';
  backBtn.style.display = 'none';
  closeDetail();
  buildLegend('overview');
  clear(svg);
  svg.removeAttribute('viewBox'); // clear() drops children only; a drill-in's viewBox would linger
  const W = svg.clientWidth || 1200, colGap = W / 5;
  const rowH = 64, pad = 30;
  const sysCol = colGap * 1.15, sharedCol = colGap * 2.6, engCol = colGap * 3.85;

  // shared-layer node positions (right column), ordered top->bottom
  const shared = MODEL.shared;
  const sHeight = Math.max(shared.length, MODEL.systems.length) * rowH + pad * 2;
  svg.setAttribute('height', Math.max(sHeight, svg.clientHeight));
  const sy0 = pad + 20;
  const sharedPos = {};
  shared.forEach((s, i) => { sharedPos[s.id] = { x: sharedCol, y: sy0 + i * rowH }; });

  const sysPos = {};
  MODEL.systems.forEach((s, i) => { sysPos[s.name] = { x: sysCol, y: sy0 + i * rowH }; });

  const edgesLayer = el('g'); svg.appendChild(edgesLayer);
  const nodesLayer = el('g'); svg.appendChild(nodesLayer);

  // All selectable engines hang off search_tool. The hybrid layer owns only
  // its semantic + keyword fan-out, so draw those two links separately.
  const st = sharedPos['search_tool'];
  const hybrid = sharedPos['hybrid_search'];
  MODEL.engines.forEach((e, i) => {
    const ey = st.y - ((MODEL.engines.length - 1) * 22) / 2 + i * 22;
    const g = el('g', { class: 'engine' });
    g.appendChild(el('rect', { x: engCol, y: ey - 9, width: 150, height: 18 }));
    g.appendChild(el('text', { x: engCol + 8, y: ey + 4, class: 'sub2' }, e.label));
    g.addEventListener('mousemove', ev => showTip(ev, '<b>'+e.label+'</b><br>'+e.blurb));
    g.addEventListener('mouseleave', hideTip);
    nodesLayer.appendChild(g);
    edgesLayer.appendChild(el('path', {
      class: 'edge', stroke: edgeColor('retrieval'),
      d: `M ${st.x+170} ${st.y} C ${engCol-30} ${st.y}, ${engCol-30} ${ey}, ${engCol} ${ey}`
    }));
    if (hybrid && (e.id === 'semantic' || e.id === 'keyword')) {
      edgesLayer.appendChild(el('path', {
        class: 'edge', stroke: edgeColor('retrieval'),
        d: `M ${hybrid.x+170} ${hybrid.y} C ${engCol-45} ${hybrid.y}, ${engCol-45} ${ey}, ${engCol} ${ey}`
      }));
    }
  });

  // system -> shared edges
  const allEdges = [];
  MODEL.systems.forEach(sys => {
    const a = sysPos[sys.name];
    sys.edges.forEach(e => {
      const b = sharedPos[e.to]; if (!b) return;
      const path = el('path', {
        class: 'edge', stroke: edgeColor(e.type),
        'data-sys': sys.name, 'data-type': e.type,
        d: `M ${a.x+170} ${a.y} C ${(a.x+b.x)/2} ${a.y}, ${(a.x+b.x)/2} ${b.y}, ${b.x} ${b.y}`
      });
      edgesLayer.appendChild(path);
      allEdges.push(path);
    });
  });
  // ragrun -> artifacts
  if (sharedPos['ragrun'] && sharedPos['artifacts']) {
    const a = sharedPos['ragrun'], b = sharedPos['artifacts'];
    edgesLayer.appendChild(el('path', { class:'edge', stroke: edgeColor('artifacts'),
      d:`M ${a.x+170} ${a.y} C ${(a.x+b.x)/2} ${a.y}, ${(a.x+b.x)/2} ${b.y}, ${b.x} ${b.y}`}));
  }

  // shared nodes
  shared.forEach(s => {
    const p = sharedPos[s.id];
    const g = el('g', { class: 'node' });
    g.appendChild(el('rect', { x: p.x, y: p.y - 18, width: 170, height: 36 }));
    g.appendChild(el('text', { x: p.x + 10, y: p.y - 1, class: 'lbl', 'font-weight':600 }, s.label));
    g.appendChild(el('text', { x: p.x + 10, y: p.y + 13, class: 'sub2' }, s.role));
    g.addEventListener('mousemove', ev => showTip(ev, '<b>'+s.label+'</b><br>'+s.detail));
    g.addEventListener('mouseleave', hideTip);
    nodesLayer.appendChild(g);
  });

  // system cards
  MODEL.systems.forEach(sys => {
    const p = sysPos[sys.name];
    const g = el('g', { class: 'card', tabindex: 0, role: 'button',
                        'aria-label': 'Open ' + sys.name + ' pipeline' });
    g.appendChild(el('rect', { x: p.x, y: p.y - 22, width: 170, height: 44 }));
    g.appendChild(el('text', { x: p.x + 10, y: p.y - 4, class: 'title lbl' }, sys.name));
    g.appendChild(el('text', { x: p.x + 10, y: p.y + 12, class: 'sub2' }, sys.kind));
    const focus = () => allEdges.forEach(pt =>
      pt.classList.toggle('dim', pt.getAttribute('data-sys') !== sys.name));
    const blur = () => allEdges.forEach(pt => pt.classList.remove('dim'));
    g.addEventListener('mouseenter', focus);
    g.addEventListener('mousemove', ev => showTip(ev, '<b>'+sys.name+'</b><br>'+sys.blurb));
    g.addEventListener('mouseleave', () => { blur(); hideTip(); });
    g.addEventListener('focus', focus);
    g.addEventListener('blur', blur);
    const open = () => { location.hash = encodeURIComponent(sys.name); };
    g.addEventListener('click', open);
    g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } });
    nodesLayer.appendChild(g);
  });

  // column headers
  const head = (x, t) => nodesLayer.appendChild(el('text', { x, y: pad, class: 'hint', 'font-weight':600 }, t));
  head(sysCol, 'systems'); head(sharedCol, 'shared layers'); head(engCol, 'engines');
}

// ---- DRILL-IN ------------------------------------------------------------
function drawSystem(sys) {
  crumb.textContent = 'overview  ›  ' + sys.name;
  backBtn.style.display = '';
  closeDetail();
  buildLegend('system');
  clear(svg);
  const H = svg.clientHeight;
  svg.setAttribute('height', H);
  // The `loop` stage is metadata (back_to/back_from/label/tools), not a drawn
  // box -- change #3 replaces its old standalone marker box with a bounding
  // rect around the stages it actually spans, so it's excluded from the row.
  const lp = sys.stages.find(s => s.kind === 'loop');
  const drawn = sys.stages.filter(s => s.kind !== 'loop');
  const bw = 150, bh = 62, gap = 34;
  const totalW = drawn.length * bw + (drawn.length - 1) * gap;
  // Long pipelines can exceed the viewport (7 stages need ~1334px); scale the
  // whole row down via viewBox instead of clipping the last box. Same svg is
  // reused across views, so the narrow path must remove a lingering viewBox.
  const needW = totalW + 80;
  let W = svg.clientWidth || 1200;
  if (needW > W) { svg.setAttribute('viewBox', '0 0 ' + needW + ' ' + H); W = needW; }
  else svg.removeAttribute('viewBox');
  const x0 = Math.max(40, (W - totalW) / 2), y = 150;

  svg.appendChild(el('text', { x: x0, y: 60, class: 'lbl', 'font-size': 18, 'font-weight': 700 }, sys.name));
  svg.appendChild(el('text', { x: x0, y: 84, class: 'sub2', 'font-size': 13 }, sys.kind + ' — ' + sys.blurb));
  svg.appendChild(el('text', { x: x0, y: 108, class: 'hint' }, 'modules: ' + sys.modules.join(', ')));

  const groups = el('g'); svg.appendChild(groups);   // loop bounding rects, drawn first (behind stages)
  const edges = el('g'); svg.appendChild(edges);
  const idx = id => drawn.findIndex(s => s.id === id);
  const cx = i => x0 + i * (bw + gap) + bw/2;

  // Loop span (index range + rect x-bounds), computed once so both the
  // straight in/out edges below and the bounding rect further down agree on
  // exactly the same rectangle -- see the `if (lp)` block below for why
  // `from`/`to` are found by declared span, not array position.
  let loopSpan = null;
  if (lp) {
    const from = idx(lp.back_from), to = lp.back_to ? idx(lp.back_to) : 0;
    if (from >= 0 && to >= 0 && from >= to) {
      loopSpan = { from, to, rx1: cx(to) - bw/2 - 14, rx2: cx(from) + bw/2 + 14 };
    }
  }

  drawn.forEach((stg, i) => {
    const x = x0 + i * (bw + gap);
    if (i > 0) {
      const px = x0 + (i - 1) * (bw + gap) + bw;
      // An edge crossing the loop's boundary connects to the bounding rect,
      // not the stage box just inside it -- otherwise the arrow reads as
      // pointing at SEARCH specifically rather than at "the loop" as a unit.
      let x1 = px, x2 = x;
      if (loopSpan) {
        if (i === loopSpan.to) x2 = loopSpan.rx1;
        if (i - 1 === loopSpan.from) x1 = loopSpan.rx2;
      }
      edges.appendChild(el('path', { class: 'edge', stroke: 'var(--muted)', 'marker-end':'url(#arw)',
        d: `M ${x1} ${y + bh/2} L ${x2} ${y + bh/2}` }));
    }
    const g = el('g', { class: 'stage', tabindex: 0, role: 'button',
                        'aria-label': 'Open ' + stg.label + ' detail',
                        'data-stage-id': stg.id, 'data-kind': stg.kind });
    if (stg.run) g.setAttribute('data-run', stg.run);
    g.appendChild(el('rect', { x, y, width: bw, height: bh, class: 'k-' + stg.kind }));
    g.appendChild(el('text', { x: x + bw/2, y: y + 26, 'text-anchor': 'middle', class: 'lbl', 'font-weight': 600 }, stg.label));
    g.appendChild(el('text', { x: x + bw/2, y: y + 44, 'text-anchor': 'middle', class: 'sub2' }, stg.kind));
    if (stg.run) {
      g.appendChild(el('text', { x: x + bw - 8, y: y + 16, 'text-anchor': 'end', class: 'runbadge', 'font-size': 9 },
        stg.run.toUpperCase()));
    }
    if (stg.note) {
      g.addEventListener('mousemove', ev => showTip(ev, '<b>'+stg.label+'</b><br>'+stg.note));
      g.addEventListener('mouseleave', hideTip);
    }
    const open = () => showDetail(sys, stg);
    g.addEventListener('click', open);
    g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); } });
    svg.appendChild(g);
  });

  // Loop-back arrow + bounding rect for agents. The cycle's span is DECLARED
  // by the `loop` stage (back_to = first stage inside the loop, back_from =
  // last one), never inferred from array position: `length - 2` silently
  // swept post-loop stages into the cycle (aus_agent's MAP CITES,
  // ali_deepresearch's FORMAT), drawing the repeat over formatting steps that
  // run exactly once. No back_from -> no arrow/rect, because a wrong one is
  // worse than a missing one.
  //
  // Found by `kind`, not by array position (`stages[0]`): that assumed the
  // loop is always the pipeline's very first activity, true for aus_agent and
  // ali_deepresearch (nothing precedes their loop) but not facet_rag, whose
  // PLAN stage genuinely runs once before the per-facet loop begins -- with
  // the position-based lookup, `stages[0]` resolved to PLAN (kind `llm`), the
  // `kind === 'loop'` check silently failed, and the back-edge was never
  // drawn at all, making an actually-repeating search/analyze/curate chain
  // render as flat and sequential with no visual indication it loops.
  if (loopSpan) {
    const { from, to, rx1, rx2 } = loopSpan;
    // Bounding rect around the loop's span (change #3), replacing the old
    // standalone marker box. `parallel_over` (facet_rag: facets run
    // concurrently, not just sequentially within one facet) is drawn as a
    // stack of ghost copies behind the main rect -- concurrency and
    // sequential repeat are two different facts about the same span, so
    // they get two different visual channels (depth vs. the dashed arrow)
    // instead of overloading one arrow to mean both.
    const ry1 = y - 26, ry2 = y + bh + 14;
    const rectAttrs = { x: rx1, y: ry1, width: rx2 - rx1, height: ry2 - ry1, rx: 12 };
    const gGroup = el('g', { class: 'loop-group', 'data-loop': lp.id,
                             'data-parallel': lp.parallel_over || '' });
    if (lp.parallel_over) {
      gGroup.appendChild(el('rect', { ...rectAttrs, x: rx1 + 12, y: ry1 - 12, class: 'loop-rect ghost2' }));
      gGroup.appendChild(el('rect', { ...rectAttrs, x: rx1 + 6, y: ry1 - 6, class: 'loop-rect ghost1' }));
    }
    gGroup.appendChild(el('rect', { ...rectAttrs, class: 'loop-rect' }));
    const label = lp.label + (lp.parallel_over ? ' × ' + lp.parallel_over + ' (concurrent)' : '');
    gGroup.appendChild(el('text', { x: rx1 + 10, y: ry1 + 16, class: 'loop-label' }, label));
    groups.appendChild(gGroup);

    // Back-edge arrow below the row so it doesn't collide with the rect's
    // label band above the boxes.
    const lx1 = cx(from), lx0 = cx(to);
    edges.appendChild(el('path', { class: 'edge', stroke: 'var(--accent)', 'stroke-dasharray':'5 4', 'marker-end':'url(#arw)',
      d: `M ${lx1} ${y+bh} C ${lx1} ${y+bh+50}, ${lx0} ${y+bh+50}, ${lx0} ${y+bh}` }));
    svg.appendChild(el('text', { x: (lx0+lx1)/2, y: y+bh+64, 'text-anchor':'middle', class:'hint' },
      lp.back_label || 'repeat until answer'));
  }
  // arrow marker
  const defs = el('defs');
  const m = el('marker', { id: 'arw', viewBox: '0 0 10 10', refX: 9, refY: 5,
    markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' });
  m.appendChild(el('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: 'var(--muted)' }));
  defs.appendChild(m); svg.appendChild(defs);
}

// Deep link: #<system-name> opens that system's pipeline directly, so a run can
// launch straight into the system it just executed. Empty hash = overview.
function route() {
  const want = decodeURIComponent((location.hash || '').replace(/^#/, ''));
  const sys = MODEL.systems.find(s => s.name === want);
  if (sys) drawSystem(sys); else drawOverview();
}
backBtn.addEventListener('click', () => {
  if (location.hash) location.hash = ''; else drawOverview();
});
document.addEventListener('keydown', ev => {
  if (ev.key !== 'Escape') return;
  if (!detail.hidden) { closeDetail(); return; }
  if (location.hash) location.hash = ''; else drawOverview();
});
window.addEventListener('hashchange', route);
window.addEventListener('resize', route);
route();
</script>
</body>
</html>
"""


def render_html(model: dict[str, Any]) -> str:
    blob = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    # guard against </script> in data (there is none, but be safe)
    blob = blob.replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__MODEL_JSON__", blob)


def _rel(path: Path) -> str:
    """Repo-relative path for display, falling back to the absolute one."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:  # --out pointed outside the repo (e.g. /tmp)
        return str(path)


def _launch(path: Path, system: str | None) -> None:
    """Open the generated HTML in the default browser (deep-linked if asked)."""
    url = path.resolve().as_uri()
    if system:
        url += "#" + quote(system)
    webbrowser.open(url)
    print(f"launched {url}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate (and optionally launch) the systems architecture "
                    "visualization")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "architecture.html")
    ap.add_argument("--print-model", action="store_true",
                    help="dump the derived model as JSON to stdout and exit")
    ap.add_argument("--open", action="store_true",
                    help="open the result in the default browser after writing")
    ap.add_argument("--system", metavar="NAME", default=None,
                    help="with --open, deep-link straight into NAME's pipeline "
                         "(e.g. --system facet_rag)")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed HTML is stale (writes "
                         "nothing) — used by the pre-commit hook and CI")
    args = ap.parse_args()

    model = build_model()
    if args.print_model:
        print(json.dumps(model, indent=2, ensure_ascii=False))
        return

    known = [s["name"] for s in model["systems"]]
    if args.system and args.system not in known:
        raise SystemExit(f"unknown system {args.system!r}; known: {', '.join(known)}")

    if args.check:
        fresh = render_html(model)
        current = args.out.read_text() if args.out.exists() else None
        rel = _rel(args.out)
        if current == fresh:
            print(f"{rel} is up to date ({len(known)} systems)")
            return
        reason = "missing" if current is None else "stale"
        raise SystemExit(
            f"{rel} is {reason} — the architecture changed.\n"
            f"Regenerate (and eyeball it) with:\n"
            f"    python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(model))
    n_edges = sum(len(s["edges"]) for s in model["systems"])
    print(f"wrote {_rel(args.out)} "
          f"({len(known)} systems, {n_edges} edges, {len(model['engines'])} engines)")

    if args.open or args.system:
        _launch(args.out, args.system)


if __name__ == "__main__":
    main()
