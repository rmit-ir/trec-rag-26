#!/usr/bin/env python3
"""Generate an interactive architecture visualization of the TREC RAG 2026 systems.

Auto-derives the diagram from source (never imports the modules — pure ``ast``
parsing, so no env/network side effects) and writes a single self-contained
HTML file (inline SVG + vanilla JS + CSS, no server, no CDN).

Two zoom levels in one page:
  - OVERVIEW  — every ``src/systems/<name>`` wired to the shared layers
                (ragrun, tools.search_tool + its 4 selectable engines,
                utils.search dense+sparse RRF, utils.fetch_doc,
                ali_deepresearch.answer_format, aus_agent.make_provider) and
                the output artifacts. Edges are colored + legended by type.
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
SYSTEMS_DIR = REPO_ROOT / "src" / "systems"
SEARCH_TOOL = REPO_ROOT / "src" / "tools" / "search_tool.py"

# ---------------------------------------------------------------------------
# Shared-layer node catalog (the right-hand side of the overview graph). These
# are stable public surfaces documented in the repo; ``engines`` is read live
# from ENGINE_INFO in tools/search_tool.py so it never drifts.
# ---------------------------------------------------------------------------
SHARED = [
    {"id": "make_provider", "label": "make_provider",
     "role": "provider", "detail": "aus_agent.agent — pluggable Bedrock/OpenAI backends"},
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
OWNERS = {"answer_format": "ali_deepresearch", "make_provider": "aus_agent"}

# ---------------------------------------------------------------------------
# Hand-authored stage flows for the current systems (see each README/pipeline).
# A package's own ARCH_STAGES literal, if present, overrides its entry here.
# stage.kind in {llm, no-llm, retrieval, format, artifact, loop}.
# ---------------------------------------------------------------------------
STAGE_REGISTRY: dict[str, list[dict[str, str]]] = {
    "facet_rag": [
        {"id": "plan", "label": "PLAN", "kind": "llm",
         "note": "1 LLM turn: narrative -> facets JSON"},
        {"id": "execute", "label": "EXECUTE", "kind": "retrieval",
         "note": "no LLM: one ClimbMix search per facet, dedup by docid"},
        {"id": "synthesize", "label": "SYNTHESIZE", "kind": "llm",
         "note": "1 LLM turn: passages -> grounded prose"},
        {"id": "format", "label": "FORMAT", "kind": "format",
         "note": "answer_format: prose -> references[] + citations"},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run -> trajectory + output"},
    ],
    "ali_deepresearch": [
        {"id": "loop", "label": "ReAct LOOP", "kind": "loop",
         "note": "per turn until <answer>",
         # THINK -> TOOL_CALL -> THINK; ANSWER exits the loop, and FORMAT/SAVE
         # run exactly once after it.
         "back_to": "think", "back_from": "tool_call",
         "back_label": "repeat until <answer>"},
        {"id": "think", "label": "THINK", "kind": "llm",
         "note": "<think> -> reasoning step"},
        {"id": "tool_call", "label": "TOOL_CALL", "kind": "retrieval",
         "note": "<tool_call> -> hybrid RRF search / fetch_doc"},
        {"id": "answer", "label": "ANSWER", "kind": "llm",
         "note": "<answer> -> final text"},
        {"id": "format", "label": "FORMAT", "kind": "format",
         "note": "answer_format: -> references[] + citations"},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run"},
    ],
    "aus_agent": [
        {"id": "loop", "label": "TURN LOOP", "kind": "loop",
         "note": "staged-context state machine",
         # The model turn is the top of the cycle: REASON/COMMIT decides whether
         # to search again (back to SEARCH) or write the report, so the arrow
         # runs commit -> search. FINAL PROSE / MAP CITES / SAVE are post-loop.
         "back_to": "search", "back_from": "commit",
         "back_label": "repeat until report"},
        {"id": "search", "label": "SEARCH", "kind": "retrieval",
         "note": "full-text search; results staged"},
        {"id": "stage", "label": "STAGE", "kind": "no-llm",
         "note": "stage evidence; commit-before-expire protocol"},
        {"id": "commit", "label": "REASON/COMMIT", "kind": "llm",
         "note": "model turn commits selected evidence"},
        {"id": "final", "label": "FINAL PROSE", "kind": "llm",
         "note": "grounded prose with inline citations"},
        {"id": "map", "label": "MAP CITES", "kind": "format",
         "note": "docid -> reference-index mapping"},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run"},
    ],
    "o3_deep_research": [
        {"id": "research", "label": "DEEP RESEARCH", "kind": "llm",
         "note": "hosted DeepResearch + MCP over ClimbMix"},
        {"id": "format", "label": "FORMAT", "kind": "format",
         "note": "answer_format: -> references[] + citations"},
        {"id": "save", "label": "SAVE", "kind": "artifact",
         "note": "ragrun.save_run"},
    ],
    "claude-code-research": [
        {"id": "workflow", "label": "WORKFLOW", "kind": "no-llm",
         "note": "workflow-driven (scripts/ + tasks/), no python pipeline package"},
    ],
}

SYSTEM_KIND = {
    "facet_rag": "pipeline",
    "ali_deepresearch": "agent",
    "aus_agent": "agent",
    "o3_deep_research": "single-file",
    "claude-code-research": "manual",
}

SYSTEM_BLURB = {
    "facet_rag": "plan-then-execute, multi-facet; each facet pinned to its best engine",
    "ali_deepresearch": "Alibaba Tongyi DeepResearch ReAct port; owns answer_format",
    "aus_agent": "staged-context research agent; owns the pluggable providers",
    "o3_deep_research": "minimal single-file runner (hosted DR + MCP)",
    "claude-code-research": "workflow-driven research (no python pipeline package)",
}


# ---------------------------------------------------------------------------
# AST extraction (no imports).
# ---------------------------------------------------------------------------
def _imported_modules(py: Path) -> set[str]:
    """Return the set of dotted module names imported by ``py`` (from ... import ...)."""
    mods: set[str] = set()
    try:
        tree = ast.parse(py.read_text(), filename=str(py))
    except (SyntaxError, UnicodeDecodeError):
        return mods
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
    return mods


def _arch_stages_override(pkg: Path) -> list[dict[str, str]] | None:
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
                            return [{k: str(v) for k, v in x.items()} for x in val]
    return None


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
        for mod in sorted(_imported_modules(py)):
            if mod == "ragrun" or mod.startswith("ragrun."):
                add("ragrun", "artifacts")
            elif mod == "tools.search_tool":
                add("search_tool", "retrieval")
            elif mod == "utils.search":
                add("hybrid_search", "retrieval")
            elif mod == "utils.fetch_doc":
                add("fetch_doc", "fetch-doc")
            elif mod.startswith("ali_deepresearch.answer_format") or \
                    mod.startswith("systems.ali_deepresearch.answer_format"):
                if OWNERS["answer_format"] != name:
                    add("answer_format", "answer-format")
            elif mod in ("aus_agent.agent", "aus_agent.providers") or \
                    mod.startswith("aus_agent.providers") or \
                    mod.startswith("systems.aus_agent.agent") or \
                    mod.startswith("systems.aus_agent.providers"):
                if OWNERS["make_provider"] != name:
                    add("make_provider", "provider")
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


def build_model() -> dict[str, Any]:
    systems: list[dict[str, Any]] = []
    for pkg in sorted(p for p in SYSTEMS_DIR.iterdir() if p.is_dir()):
        name = pkg.name
        if name == "__pycache__":
            continue
        py_files = sorted(pkg.glob("*.py"))
        modules = [p.stem for p in py_files]
        stages = _arch_stages_override(pkg) or STAGE_REGISTRY.get(name) \
            or [{"id": "run", "label": "RUN", "kind": "no-llm", "note": ""}]
        # scan the whole package tree (subpackages like tools/, providers/ hold
        # the retrieval/provider imports), skipping caches.
        scan = [p for p in pkg.rglob("*.py") if "__pycache__" not in p.parts]
        systems.append({
            "name": name,
            "kind": SYSTEM_KIND.get(name, "pipeline"),
            "modules": modules,
            "blurb": SYSTEM_BLURB.get(name, ""),
            "stages": stages,
            "edges": _edges_for_system(name, scan),
        })
    return {
        "generated_from": "src/systems + shared layers (ragrun, tools, utils)",
        "systems": systems,
        "shared": SHARED,
        "engines": _read_engines(),
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
    --e-provider: #2563eb; --e-fetch-doc: #0891b2;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1216; --panel: #171b21; --ink: #e6edf3; --muted: #9aa7b4;
      --line: #2a323c; --card: #1e242c; --cardstroke: #3a4552;
      --accent: #7c8cff;
      --e-retrieval: #2dd4bf; --e-artifacts: #f59e0b; --e-answer-format: #a78bfa;
      --e-provider: #60a5fa; --e-fetch-doc: #22d3ee;
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
  .stage rect { rx: 9; stroke-width: 2; }
  .k-llm      { fill: color-mix(in srgb, var(--e-provider) 18%, var(--panel)); stroke: var(--e-provider); }
  .k-retrieval{ fill: color-mix(in srgb, var(--e-retrieval) 18%, var(--panel)); stroke: var(--e-retrieval); }
  .k-format   { fill: color-mix(in srgb, var(--e-answer-format) 18%, var(--panel)); stroke: var(--e-answer-format); }
  .k-artifact { fill: color-mix(in srgb, var(--e-artifacts) 18%, var(--panel)); stroke: var(--e-artifacts); }
  .k-loop     { fill: var(--card); stroke: var(--accent); stroke-dasharray: 5 4; }
  .k-no-llm   { fill: var(--card); stroke: var(--cardstroke); }
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
</div>

<script id="arch-model" type="application/json">__MODEL_JSON__</script>
<script>
const MODEL = JSON.parse(document.getElementById('arch-model').textContent);
const SVG_NS = 'http://www.w3.org/2000/svg';
const svg = document.getElementById('stage');
const tip = document.getElementById('tip');
const crumb = document.getElementById('crumb');
const backBtn = document.getElementById('back');

const EDGE_TYPES = [
  ['retrieval','Retrieval (search layers)'],
  ['fetch-doc','fetch_doc'],
  ['answer-format','answer_format (reuse)'],
  ['provider','make_provider (reuse)'],
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

function buildLegend() {
  const box = document.getElementById('legend');
  clear(box);
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

// ---- OVERVIEW ------------------------------------------------------------
function drawOverview() {
  crumb.textContent = 'overview';
  backBtn.style.display = 'none';
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
  clear(svg);
  const H = svg.clientHeight;
  svg.setAttribute('height', H);
  const stages = sys.stages;
  const bw = 150, bh = 62, gap = 34;
  const totalW = stages.length * bw + (stages.length - 1) * gap;
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

  const edges = el('g'); svg.appendChild(edges);
  stages.forEach((stg, i) => {
    const x = x0 + i * (bw + gap);
    if (i > 0) {
      const px = x0 + (i - 1) * (bw + gap) + bw;
      edges.appendChild(el('path', { class: 'edge', stroke: 'var(--muted)', 'marker-end':'url(#arw)',
        d: `M ${px} ${y + bh/2} L ${x} ${y + bh/2}` }));
    }
    const g = el('g', { class: 'stage' });
    g.appendChild(el('rect', { x, y, width: bw, height: bh, class: 'k-' + stg.kind }));
    g.appendChild(el('text', { x: x + bw/2, y: y + 26, 'text-anchor': 'middle', class: 'lbl', 'font-weight': 600 }, stg.label));
    g.appendChild(el('text', { x: x + bw/2, y: y + 44, 'text-anchor': 'middle', class: 'sub2' }, stg.kind));
    if (stg.note) {
      g.addEventListener('mousemove', ev => showTip(ev, '<b>'+stg.label+'</b><br>'+stg.note));
      g.addEventListener('mouseleave', hideTip);
    }
    svg.appendChild(g);
  });
  // Loop-back arrow for agents. The cycle's span is DECLARED by the `loop`
  // stage (back_to = first stage inside the loop, back_from = last one), never
  // inferred from array position: `length - 2` silently swept post-loop stages
  // into the cycle (aus_agent's MAP CITES, ali_deepresearch's FORMAT), drawing
  // the repeat over formatting steps that run exactly once. No back_from ->
  // no arrow, because a wrong arrow is worse than a missing one.
  const lp = stages[0];
  if (lp && lp.kind === 'loop') {
    const idx = id => stages.findIndex(s => s.id === id);
    const from = idx(lp.back_from), to = lp.back_to ? idx(lp.back_to) : 1;
    if (from > 0 && to > 0 && from >= to) {
      const cx = i => x0 + i * (bw + gap) + bw/2;
      const lx1 = cx(from), lx0 = cx(to);
      edges.appendChild(el('path', { class: 'edge', stroke: 'var(--accent)', 'stroke-dasharray':'5 4', 'marker-end':'url(#arw)',
        d: `M ${lx1} ${y} C ${lx1} ${y-50}, ${lx0} ${y-50}, ${lx0} ${y}` }));
      svg.appendChild(el('text', { x: (lx0+lx1)/2, y: y-56, 'text-anchor':'middle', class:'hint' },
        lp.back_label || 'repeat until answer'));
    }
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
  if (ev.key === 'Escape') { if (location.hash) location.hash = ''; else drawOverview(); }
});
window.addEventListener('hashchange', route);
window.addEventListener('resize', route);
buildLegend();
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
