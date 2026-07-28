"""Behaviour of the agent-facing ``search`` tool wrapper (``tools/search_tool.py``).

Everything here is what the *model* sees and what the agent loop depends on, so
it is worth pinning independently of the retrieval backends:

1. **The tool definition is derived, not hardcoded.** ``build_search_tool`` is
   how a run restricts itself to one engine (the engine-comparison experiments)
   — so the ``enum``/``default``/``required`` triple must follow the enabled set
   exactly. A single-engine build that still marked ``search_engine`` required
   would force the model to name the only engine there is; a multi-engine build
   that left it optional would silently route everything to ``engines[0]``.
2. **The guidance string is the query language contract.** SSR needs GCL,
   lucene_bool needs Lucene syntax, semantic/keyword need natural language. A
   mixed engine set must carry *both* guidances with their ``[for ...]`` labels,
   or the model writes a GCL query into the dense engine and gets zero.
3. **Errors come back as a result, not as an exception.** ``run_search_tool``
   converts a backend failure into ``{"error": ...}`` so the agent can retry a
   different engine/query instead of the loop crashing. That is a design
   property, not an implementation detail, hence a dedicated test.

All retrieval is stubbed via ``stub_search_tool`` (patches ``_DISPATCH``), so the
real envelope/rounding/truncation code runs but no transport does.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from tools import search_tool
from tools.search_tool import (ENGINE_INFO, SEARCH_ENGINES, SEARCH_TOOL,
                               _query_guidance, build_search_tool,
                               run_search_tool)


# ---------------------------------------------------------------------------
# build_search_tool — schema derivation
# ---------------------------------------------------------------------------
def test_default_build_is_semantic_plus_keyword() -> None:
    """No argument == the documented default pair (what SEARCH_TOOL bakes in)."""
    tool = build_search_tool()
    assert tool["input_schema"]["properties"]["search_engine"]["enum"] == [
        "semantic", "keyword"]


@pytest.mark.parametrize("engine", SEARCH_ENGINES)
def test_single_engine_build_does_not_require_search_engine(engine: str) -> None:
    """One engine -> ``search_engine`` optional, enum/default pinned to it.

    The model should not have to spell out the only choice available; the
    dispatch default has to be that engine, not the table's first entry.
    """
    schema = build_search_tool([engine])["input_schema"]
    assert schema["required"] == ["query"]
    prop = schema["properties"]["search_engine"]
    assert prop["enum"] == [engine]
    assert prop["default"] == engine


def test_multi_engine_build_requires_search_engine() -> None:
    """With >1 engine, an omitted ``search_engine`` would silently route every
    call to ``engines[0]`` — so a run that thinks it is comparing engines would
    actually be measuring one of them. Making it required forces the choice."""
    tool = build_search_tool(["semantic", "ssr"])
    assert tool["input_schema"]["required"] == ["query", "search_engine"]


def test_engine_order_is_preserved_and_drives_the_default() -> None:
    """Order is the caller's, not ``ENGINE_INFO``'s — the first is the default."""
    schema = build_search_tool(["ssr", "keyword", "semantic"])["input_schema"]
    prop = schema["properties"]["search_engine"]
    assert prop["enum"] == ["ssr", "keyword", "semantic"]
    assert prop["default"] == "ssr"


def test_multi_engine_description_nudges_cross_engine_coverage() -> None:
    """The "cover a facet with more than one" sentence appears only when it can
    actually be acted on (>1 engine)."""
    def _engine_desc(engines: list[str]) -> str:
        schema = build_search_tool(engines)["input_schema"]
        return schema["properties"]["search_engine"]["description"]

    key = "cover an important facet with more than one"
    assert key in _engine_desc(["semantic", "keyword"])
    assert key not in _engine_desc(["semantic"])


@pytest.mark.parametrize("engines", [["nope"], ["semantic", "bm25"]])
def test_unknown_engine_raises_naming_the_bad_engine(engines: list[str]) -> None:
    """Fails loudly at build time (a runner typo), and the message names the
    offender plus the known set — this is a config error a human reads."""
    bad = [e for e in engines if e not in ENGINE_INFO]
    with pytest.raises(ValueError) as excinfo:
        build_search_tool(engines)
    msg = str(excinfo.value)
    assert bad[0] in msg
    for known in ENGINE_INFO:
        assert known in msg


def test_every_engine_has_a_blurb_in_the_description() -> None:
    """The tool description is the "when to use" the model routes on."""
    tool = build_search_tool(list(SEARCH_ENGINES))
    for engine in SEARCH_ENGINES:
        assert ENGINE_INFO[engine]["blurb"] in tool["description"]


def test_module_level_search_tool_is_a_valid_anthropic_tool_def() -> None:
    """``SEARCH_TOOL`` is passed verbatim into the provider's ``tools=`` list, so
    a malformed schema is an API 400 at the first turn of a real run, not a local
    failure. Structural validation here is cheap insurance."""
    assert set(SEARCH_TOOL) == {"name", "description", "input_schema"}
    assert SEARCH_TOOL["name"] == "search"
    assert isinstance(SEARCH_TOOL["description"], str) and SEARCH_TOOL["description"]
    schema = SEARCH_TOOL["input_schema"]
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"query", "k", "search_engine"}
    # Every declared `required` entry must exist in `properties`, or the model
    # is asked for a field the schema does not define.
    assert set(schema["required"]) <= set(schema["properties"])
    for prop in schema["properties"].values():
        assert prop["type"] in {"string", "integer"}
        assert isinstance(prop["description"], str) and prop["description"]


def test_search_tool_matches_the_default_build() -> None:
    """The module constant must stay a plain alias of the builder, so systems
    that import ``SEARCH_TOOL`` (back-compat) and systems that call
    ``build_search_tool`` cannot end up showing the model two different tools."""
    assert SEARCH_TOOL == build_search_tool(["semantic", "keyword"])
    assert SEARCH_TOOL["input_schema"]["required"] == ["query", "search_engine"]


# ---------------------------------------------------------------------------
# _query_guidance — the per-engine query language contract
# ---------------------------------------------------------------------------
# One marker substring per guidance kind, chosen to be unique to that text.
_NL_MARK = "Write the query as a short, specific phrase"
_GCL_MARK = "Write a GCL Boolean query"
_LUCENE_MARK = "Write a Lucene query-parser query"


@pytest.mark.parametrize("engines,present,absent", [
    (["semantic"], _NL_MARK, (_GCL_MARK, _LUCENE_MARK)),
    (["keyword"], _NL_MARK, (_GCL_MARK, _LUCENE_MARK)),
    (["semantic", "keyword"], _NL_MARK, (_GCL_MARK, _LUCENE_MARK)),
    (["ssr"], _GCL_MARK, (_NL_MARK, _LUCENE_MARK)),
    (["lucene_bool"], _LUCENE_MARK, (_NL_MARK, _GCL_MARK)),
])
def test_single_kind_engine_set_yields_exactly_that_guidance(
        engines: list[str], present: str, absent: tuple[str, ...]) -> None:
    """semantic+keyword share ``kind == "nl"``, so the pair is still one kind —
    no ``[for ...]`` labels, just the bare guidance."""
    guidance = _query_guidance(engines)
    assert present in guidance
    for other in absent:
        assert other not in guidance
    assert "[for " not in guidance


def test_mixed_kinds_yield_both_guidances_with_labels() -> None:
    """Mixed kinds means the query LANGUAGE depends on ``search_engine``, so both
    guidances must ship and both must be labelled. Dropping either one, or the
    labels, leaves the model writing GCL into the dense engine (zero hits) or
    prose into SSR (a parse error)."""
    guidance = _query_guidance(["semantic", "ssr"])
    assert "[for semantic/keyword]" in guidance
    assert "[for ssr]" in guidance
    assert _NL_MARK in guidance and _GCL_MARK in guidance
    # Order follows the engine order, so the model reads its default first.
    assert guidance.index("[for semantic/keyword]") < guidance.index("[for ssr]")


def test_all_engines_yield_all_three_labelled_guidances() -> None:
    """The maximal build — four engines collapsing to three query kinds. Guards
    the de-duplication in ``_query_guidance``: semantic and keyword share a kind,
    so the nl guidance must appear once, not twice."""
    guidance = _query_guidance(list(SEARCH_ENGINES))
    for label in ("[for semantic/keyword]", "[for ssr]", "[for lucene_bool]"):
        assert label in guidance
    for mark in (_NL_MARK, _GCL_MARK, _LUCENE_MARK):
        assert guidance.count(mark) == 1


def test_guidance_is_wired_into_the_query_property() -> None:
    """The guidance is only useful if it lands on the ``query`` property — that
    is the field the model is writing when it reads the description. A build that
    computed the guidance but attached it elsewhere would look fine in isolation."""
    tool = build_search_tool(["ssr"])
    assert tool["input_schema"]["properties"]["query"]["description"] == \
        _query_guidance(["ssr"])


# ---------------------------------------------------------------------------
# run_search_tool — routing + result envelope
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("engine", SEARCH_ENGINES)
def test_routes_to_the_named_engine_only(engine: str,
                                         stub_search_tool: dict[str, Any]) -> None:
    """Routing is the tool's entire job, and a mis-route is invisible in the
    output (results still look plausible) — only the per-engine call recorder can
    catch it. The ``list(calls) == [engine]`` assertion is the load-bearing one:
    it proves nothing was ALSO queried, which is what would quietly wreck a
    single-engine effectiveness comparison.

    Axis: every declared engine, so a new one cannot be added to ``ENGINE_INFO``
    without a wired dispatch entry.
    """
    out = json.loads(run_search_tool("congestion pricing", k=2,
                                     search_engine=engine))
    assert list(stub_search_tool) == [engine]           # nothing else was called
    assert stub_search_tool[engine] == [{"query": "congestion pricing", "k": 2}]
    assert out["engine"] == engine and out["query"] == "congestion pricing"
    assert out["k"] == 2


def test_result_envelope_shape_and_fields(stub_search_tool: dict[str, Any]) -> None:
    """This envelope is what the model actually reads and cites from, so the key
    set is a contract with the *prompt*: the answer stage tells the model to cite
    by ``docid``, and the trajectory analysis keys on ``rank``/``score``. An extra
    or renamed key means either wasted context or a citation the model cannot
    form."""
    out = json.loads(run_search_tool("congestion pricing", k=3))
    assert out["engine"] == "semantic"                  # documented default
    assert len(out["results"]) == 3
    for i, row in enumerate(out["results"], start=1):
        assert set(row) == {"rank", "id", "docid", "kind", "score", "text"}
        assert row["rank"] == i
        assert row["kind"] == "document"                # CLIMBMIX_DOCIDS are docs
        assert row["docid"] == row["id"]
        assert isinstance(row["text"], str) and row["text"]


def test_kwargs_pass_through_to_the_engine(stub_search_tool: dict[str, Any]) -> None:
    """Engine-specific knobs (dense ``complexity``, ``with_text``, ...) must
    reach the client untouched — the tool layer is not an allowlist."""
    run_search_tool("q", k=1, search_engine="semantic",
                    with_text=False, complexity=120)
    assert stub_search_tool["semantic"][0] == {
        "query": "q", "k": 1, "with_text": False, "complexity": 120}


@pytest.mark.parametrize("max_chars,expected_len", [(10, 10), (1, 1), (10_000, None)])
def test_max_chars_truncates_text(max_chars: int, expected_len: int | None,
                                  stub_search_tool: dict[str, Any]) -> None:
    """Truncation is the agent loop's main context-budget lever: 10 results ×
    full documents would blow the window in two turns. Axis: a hard cut, the
    degenerate 1-char cut, and a cap larger than the text (no padding, no crash).
    """
    out = json.loads(run_search_tool("q", k=1, max_chars=max_chars))
    text = out["results"][0]["text"]
    if expected_len is None:
        assert len(text) < max_chars                    # shorter than the cap
    else:
        assert len(text) == expected_len


def test_max_chars_none_keeps_full_text(stub_search_tool: dict[str, Any],
                                        fake_hits: Any) -> None:
    """``None`` is the documented opt-out, used when a pipeline wants the whole
    passage for its own downstream chunking/judging. Note ``None`` must NOT be
    treated as "use the default 500" — that would silently cap those pipelines."""
    full = fake_hits(1, source="semantic")[0]["text"]
    out = json.loads(run_search_tool("q", k=1, max_chars=None))
    assert out["results"][0]["text"] == full


def test_default_max_chars_is_500(stub_search_tool: dict[str, Any],
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards the documented default without needing a >500-char fixture."""
    from utils.search_types import make_hit

    long_text = "x" * 900
    monkeypatch.setitem(
        search_tool._DISPATCH, "semantic",
        lambda q, k, **kw: [make_hit("shard_00000_1", score=1.0, rank=1,
                                     text=long_text, meta={"source": "dense"})])
    out = json.loads(run_search_tool("q", k=1))
    assert len(out["results"][0]["text"]) == 500


def test_score_is_rounded_to_six_places(stub_search_tool: dict[str, Any],
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """SSR synthesizes ``1/rank`` scores; unrounded they bloat the JSON the
    agent has to read (and diff noisily between runs)."""
    from utils.search_types import make_hit

    monkeypatch.setitem(
        search_tool._DISPATCH, "ssr",
        lambda q, k, **kw: [make_hit("shard_00000_7", score=1.0 / 3.0, rank=1,
                                     text=None, meta={"source": "ssr"})])
    out = json.loads(run_search_tool("(^ a b)", k=1, search_engine="ssr"))
    assert out["results"][0]["score"] == pytest.approx(0.333333, abs=0)
    assert out["results"][0]["score"] == round(1.0 / 3.0, 6)


def test_missing_text_becomes_empty_string_in_the_envelope(
        stub_search_tool: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``SearchHit`` carries ``text=None``; the JSON envelope normalises it to
    ``""`` so the agent never sees a null it has to guard."""
    from utils.search_types import make_hit

    monkeypatch.setitem(
        search_tool._DISPATCH, "keyword",
        lambda q, k, **kw: [make_hit("shard_00000_2", score=3.5, rank=1,
                                     text=None, meta={"source": "sparse"})])
    out = json.loads(run_search_tool("q", k=1, search_engine="keyword"))
    assert out["results"][0]["text"] == ""


def test_chunk_ids_keep_id_and_docid_distinct(stub_search_tool: dict[str, Any],
                                              fake_hits: Any,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """Post-chunking, the citation key is ``docid`` while ``id`` is the chunk —
    the envelope must expose both."""
    hits = fake_hits(2, source="dense", ids=("shard_00459_61697_p3",
                                             "shard_01012_88420_p1"))
    monkeypatch.setitem(search_tool._DISPATCH, "semantic",
                        lambda q, k, **kw: hits)
    rows = json.loads(run_search_tool("q", k=2))["results"]
    assert [r["id"] for r in rows] == ["shard_00459_61697_p3",
                                       "shard_01012_88420_p1"]
    assert [r["docid"] for r in rows] == ["shard_00459_61697", "shard_01012_88420"]
    assert {r["kind"] for r in rows} == {"chunk"}


def test_empty_result_set_is_a_normal_envelope(
        stub_search_tool: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """SSR's "truthful zero" must not look like an error to the agent."""
    monkeypatch.setitem(search_tool._DISPATCH, "ssr", lambda q, k, **kw: [])
    out = json.loads(run_search_tool("(^ impossible cooccurrence)",
                                     search_engine="ssr"))
    assert out["results"] == [] and "error" not in out


# ---------------------------------------------------------------------------
# Error envelopes — the agent must be able to react, not crash
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("exc", [
    RuntimeError("BoolSearch exited 1: ParseException"),
    TimeoutError("read timed out"),
    KeyError("docid"),
])
def test_engine_exception_is_returned_as_an_error_envelope(
        exc: Exception, stub_search_tool: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The core resilience property: a backend failure must reach the model as a
    tool RESULT so it can retry another engine, not propagate and abort a run
    that may already be 20 turns and several dollars deep.

    Axis: the three failure classes seen in practice — a subprocess/parse error
    from lucene_bool, a network timeout from a hosted endpoint, and a
    ``KeyError`` from an unexpected payload shape (which is a *bug*, and must
    still be caught rather than crashing the loop).
    """
    def _boom(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
        raise exc

    monkeypatch.setitem(search_tool._DISPATCH, "lucene_bool", _boom)
    out = json.loads(run_search_tool("+a +b", search_engine="lucene_bool"))
    assert set(out) == {"error"}
    # The type name is part of the contract: it is the only machine-readable
    # signal the agent (and a post-hoc trajectory reader) gets.
    assert out["error"].startswith(f"{type(exc).__name__}: ")


def test_unknown_engine_returns_error_envelope_listing_valid_engines(
        stub_search_tool: dict[str, Any]) -> None:
    """A hallucinated engine name is an agent mistake, so it must be a tool
    result the model can correct from — not a Python exception."""
    out = json.loads(run_search_tool("q", search_engine="elasticsearch"))
    assert set(out) == {"error"}
    assert "elasticsearch" in out["error"]
    for engine in SEARCH_ENGINES:
        assert engine in out["error"]
    assert stub_search_tool == {}                      # nothing was dispatched


def test_dispatch_table_covers_exactly_the_declared_engines() -> None:
    """``ENGINE_INFO`` (schema) and ``_DISPATCH`` (transport) must not drift:
    an engine in the enum with no dispatch entry would surface to the model as
    a valid choice that always errors."""
    assert tuple(search_tool._DISPATCH) == SEARCH_ENGINES
