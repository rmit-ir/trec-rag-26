"""Regression tests for `gen_arch_viz.py`'s data model (issue #20).

Maps each of issue #20's four requested changes to an in-memory assertion on
`build_model()`/`render_html()` output -- there is no browser harness in this
repo, so JS/SVG interaction (the click-to-open panel, the loop rectangle
geometry) is exercised manually in a browser instead; these tests guard the
*data* that rendering consumes, plus the string markers that prove the JS/CSS
wiring for it is actually present in the generated HTML.
"""
from __future__ import annotations

import gen_arch_viz as gav


def _system(model: dict, name: str) -> dict:
    return next(s for s in model["systems"] if s["name"] == name)


def _stage(system: dict, stage_id: str) -> dict:
    return next(s for s in system["stages"] if s["id"] == stage_id)


def _variant(system: dict, variant_id: str) -> dict:
    return next(v for v in system["variants"] if v["id"] == variant_id)


def test_build_model_succeeds_without_raising() -> None:
    """Every ref declared in STAGE_REGISTRY must resolve against real source.

    `_normalize_stage` raises `SystemExit` on any renamed/removed prompt or
    code symbol, so a passing `build_model()` is itself the ref-rot guard --
    if this test fails, some STAGE_REGISTRY ref no longer matches the code it
    claims to document.
    """
    gav.build_model()


def test_curate_detail_shows_real_prompt_text_not_just_the_note() -> None:
    """Issue test 1.2: CURATE's detail must surface CURATOR_PROMPT's actual text."""
    model = gav.build_model()
    curate = _stage(_system(model, "facet_rag"), "curate")
    assert curate["prompt"] == ["systems/facet_rag/prompts.py::CURATOR_PROMPT"]
    assert "MOST to LEAST useful" in model["prompts"][curate["prompt"][0]]


def test_search_detail_references_code_not_a_prompt() -> None:
    """Issue test 1.3: facet_rag's SEARCH is retrieval code, not an LLM prompt."""
    model = gav.build_model()
    search = _stage(_system(model, "facet_rag"), "search")
    assert "tools/search_tool.py::run_search_tool" in search["code"]


def test_run_class_marks_agentic_vs_code_vs_both() -> None:
    """Issue test 2: run-badge classes, including the documented FORMAT deviation.

    facet_rag's PLAN/ANALYZE/CURATE/DRAFT/FACT-CHECK are LLM-driven, SAVE is
    pure code -- matching the issue's literal expectation. FORMAT is a
    deliberate deviation from that literal expectation (see worklog): it
    really does call FORMAT_ANSWER_PROMPT, so it is llm+code, not code-only.
    """
    fr = _system(gav.build_model(), "facet_rag")
    assert _stage(fr, "plan")["run"] == "llm+code"
    assert _stage(fr, "analyze")["run"] == "llm+code"
    assert _stage(fr, "curate")["run"] == "llm+code"
    assert _stage(fr, "draft")["run"] == "llm+code"
    assert _stage(fr, "fact_check")["run"] == "llm+code"
    assert _stage(fr, "save")["run"] == "code"
    assert _stage(fr, "format")["run"] == "llm+code"


def test_loop_span_covers_exactly_the_declared_stages() -> None:
    """Issue tests 3.1/3.3: the loop rectangle's span must generalize across systems.

    The `loop` stage itself is excluded from the drawn row (change #3 draws a
    bounding rect instead of a standalone marker box), and back_to..back_from
    must name exactly the stages the issue lists for each system.
    """
    model = gav.build_model()
    cases = {
        "facet_rag": ("search", "curate", ["plan", "search", "analyze", "curate",
                                            "draft", "fact_check", "format", "save"]),
        "aus_agent": ("search", "commit", ["search", "stage", "commit", "final",
                                            "map", "save"]),
        "ali_deepresearch": ("think", "tool_call", ["think", "tool_call", "answer",
                                                     "format", "save"]),
    }
    for sys_name, (back_to, back_from, drawn_ids) in cases.items():
        sys_model = _system(model, sys_name)
        loop = next(s for s in sys_model["stages"] if s["kind"] == "loop")
        assert loop["back_to"] == back_to
        assert loop["back_from"] == back_from
        drawn = [s["id"] for s in sys_model["stages"] if s["kind"] != "loop"]
        assert drawn == drawn_ids
        span = drawn[drawn.index(back_to):drawn.index(back_from) + 1]
        assert span == drawn_ids[drawn_ids.index(back_to):drawn_ids.index(back_from) + 1]


def test_facet_loop_is_parallel_turn_loop_and_react_loop_are_not() -> None:
    """Issue test 3: only facet_rag's loop runs concurrently across facets."""
    model = gav.build_model()
    facet_loop = next(s for s in _system(model, "facet_rag")["stages"] if s["kind"] == "loop")
    turn_loop = next(s for s in _system(model, "aus_agent")["stages"] if s["kind"] == "loop")
    react_loop = next(s for s in _system(model, "ali_deepresearch")["stages"] if s["kind"] == "loop")
    assert facet_loop.get("parallel_over") == "facet"
    assert not turn_loop.get("parallel_over")
    assert not react_loop.get("parallel_over")


def test_aus_agent_search_lists_the_three_native_tools() -> None:
    """Issue test 4.1: SEARCH's detail must list the loop's native tool trio.

    aus_agent configures its tools once on the whole TURN LOOP conversation
    (one `provider.start` call), not per-stage, so SEARCH inherits them via
    the enclosing-loop lookup the detail panel performs at render time; here
    we assert the loop stage itself carries the right names.
    """
    loop = _stage(_system(gav.build_model(), "aus_agent"), "loop")
    assert {t["name"] for t in loop["tools"]} == {"search", "get_documents", "commit_context"}


def test_facet_rag_search_lists_five_engines_split_mandatory_optional() -> None:
    """Issue test 4.2: facet_rag's SEARCH lists all 5 engines, grouped correctly."""
    search = _stage(_system(gav.build_model(), "facet_rag"), "search")
    by_group: dict[str, set[str]] = {}
    for t in search["tools"]:
        by_group.setdefault(t["group"], set()).add(t["name"])
    assert by_group["mandatory engine"] == {"semantic", "keyword", "hybrid"}
    assert by_group["optional engine"] == {"ssr", "lucene_bool"}


def test_rendering_wiring_is_present_in_the_generated_html() -> None:
    """The JS/CSS hooks change #1-#4 depend on must actually reach the output.

    Not a substitute for the manual browser pass (this repo has no DOM
    harness), but catches a future edit that silently drops one of the
    wired-up pieces (e.g. the click handler, the loop group, the run badge).
    """
    html = gav.render_html(gav.build_model())
    for marker in ("data-run", "loop-group", "showDetail", "detail-close", "runbadge"):
        assert marker in html


def test_aus_agent_v2_variants_are_mutually_exclusive_runnable_paths() -> None:
    """The diagram must not imply candidate gates run after the graded default.

    Each path maps to one callable pipeline entrypoint. In particular, semantic
    closure belongs only to its candidate lane and extractive union consumes
    completed answers instead of appearing in the normal request pipeline.
    """
    system = _system(gav.build_model(), "aus_agent_v2")
    assert [variant["id"] for variant in system["variants"]] == [
        "verified", "lean", "semantic", "union",
    ]
    assert [variant["id"] for variant in system["variants"]
            if variant["default"]] == ["verified"]

    verified = _variant(system, "verified")
    lean = _variant(system, "lean")
    semantic = _variant(system, "semantic")
    union = _variant(system, "union")
    assert verified["entrypoint"].endswith("::run_one")
    assert lean["entrypoint"].endswith("::run_lean_contract_one")
    assert semantic["entrypoint"].endswith("::run_semantic_contract_one")
    assert union["entrypoint"].endswith("::run_candidate_union_one")
    assert "semantic" not in {stage["id"] for stage in verified["stages"]}
    assert "semantic" not in {stage["id"] for stage in lean["stages"]}
    assert "semantic" in {stage["id"] for stage in semantic["stages"]}
    assert [stage["id"] for stage in union["stages"]] == ["union", "save"]
    assert union["input"] == "eight completed cited answers"


def test_verified_variant_exposes_only_the_tools_used_by_graded_research() -> None:
    """Candidate terminal-submit tooling must not leak into the default lane."""
    verified = _variant(_system(gav.build_model(), "aus_agent_v2"), "verified")
    research = next(stage for stage in verified["stages"] if stage["id"] == "research")
    assert {tool["name"] for tool in research["tools"]} == {
        "search", "commit_context",
    }


def test_variant_renderer_wraps_labels_and_uses_scrollable_branch_lanes() -> None:
    """Long labels must retain font size without overlapping adjacent boxes."""
    html = gav.render_html(gav.build_model())
    for marker in (
        "drawVariantSystem", "variant-lane", "appendWrappedText",
        "overflow: auto", "each lane = a mutually exclusive runnable branch",
    ):
        assert marker in html


def test_render_html_is_deterministic() -> None:
    """`--check` (pre-commit/CI freshness gate) depends on byte-stable output."""
    model = gav.build_model()
    assert gav.render_html(model) == gav.render_html(model)


def test_arch_stages_override_preserves_types_instead_of_stringifying(tmp_path) -> None:
    """Regression for the `str(v)` coercion bug found while reading the code.

    A scaffolded system's `ARCH_STAGES` literal can declare list/dict-valued
    keys (`prompt`, `code`, `tools`) same as STAGE_REGISTRY; the old
    `{k: str(v) for k, v in x.items()}` would have flattened a list into its
    Python repr string (e.g. `"['a', 'b']"`), corrupting it for any future
    system that opts in. This drives `_arch_stages_override` directly against
    a throwaway package dir, not a real one, so it stays independent of
    whichever systems currently exist under `src/systems/`.
    """
    pkg = tmp_path / "fake_system"
    pkg.mkdir()
    (pkg / "run.py").write_text(
        "ARCH_STAGES = ["
        "{'id': 'a', 'label': 'A', 'kind': 'llm', 'note': 'n', "
        "'prompt': ['systems/o3_deep_research/run.py::SYSTEM_PROMPT']}"
        "]\n"
    )
    override = gav._arch_stages_override(pkg)
    assert override == [{
        "id": "a", "label": "A", "kind": "llm", "note": "n",
        "prompt": ["systems/o3_deep_research/run.py::SYSTEM_PROMPT"],
    }]


def _shared_rooted_imports(name: str, py_files: list) -> list[str]:
    """Every ``ragrun``/``tools``/``utils``/``agent_harness`` import in
    ``py_files`` that ``_classify_import`` can't turn into an edge and that
    isn't explicitly named in ``UNMODELED_SHARED_IMPORTS`` -- i.e. a gap.
    """
    roots = ("ragrun", "tools", "utils", "agent_harness")
    gaps = []
    for py in py_files:
        for mod, names in gav._imported_names(py).items():
            if mod.split(".")[0] not in roots:
                continue
            if mod in gav.UNMODELED_SHARED_IMPORTS:
                continue
            if gav._classify_import(name, mod, names):
                continue
            gaps.append(f"{py.relative_to(gav.REPO_ROOT)}: {mod}")
    return gaps


def test_every_shared_rooted_import_is_classified_or_explicitly_unmodeled() -> None:
    """Nothing under ragrun/tools/utils/agent_harness may go un-diagrammed silently.

    The point of this test: it fails the moment someone adds a NEW shared-layer
    import to a system (or to agent_harness/ragrun themselves), not months
    later when a human notices the overview graph is missing an edge. The fix
    when it fails is always one of two things -- add a ``_classify_import``
    branch (+ a ``SHARED`` catalog entry) for the new import, or add it to
    ``UNMODELED_SHARED_IMPORTS`` with a one-line reason if it's genuinely
    internal plumbing, not an architectural component worth its own node.

    Also covers shared-layer packages scanning THEMSELVES (mirroring
    ``_shared_internal_edges``): a new dependency agent_harness or ragrun
    picks up must be classified too, or the one-hop expansion in
    ``build_model`` would silently miss it for every consumer.
    """
    gaps: list[str] = []
    for pkg in sorted(p for p in gav.SYSTEMS_DIR.iterdir() if p.is_dir()):
        if pkg.name == "__pycache__":
            continue
        scan = [p for p in pkg.rglob("*.py") if "__pycache__" not in p.parts]
        gaps += _shared_rooted_imports(pkg.name, scan)
    for shared in gav.SHARED:
        pkg_dir = gav.SRC / shared["id"]
        if not pkg_dir.is_dir():
            continue
        scan = [p for p in pkg_dir.rglob("*.py") if "__pycache__" not in p.parts]
        gaps += _shared_rooted_imports(shared["id"], scan)
    assert gaps == [], (
        "shared-layer import(s) the diagram can't classify:\n" + "\n".join(gaps))


def test_arch_variants_override_preserves_nested_stage_overrides(tmp_path) -> None:
    """Branch metadata must survive AST extraction without importing a system."""
    pkg = tmp_path / "fake_system"
    pkg.mkdir()
    (pkg / "pipeline.py").write_text(
        "ARCH_VARIANTS = [{"
        "'id': 'lean', 'label': 'Lean', 'status': 'UNTESTED', "
        "'path': ['search'], 'stage_overrides': {"
        "'search': {'tools': [{'name': 'search', 'ref': 'x::Y'}]}}"
        "}]\n"
    )
    override = gav._arch_variants_override(pkg)
    assert override is not None
    assert override[0]["stage_overrides"]["search"]["tools"][0]["name"] == "search"
