"""Contract: the ClimbMix document input format (Pyserini REST payloads).

`retrieval-task.md` "Input Format: Documents" pins two response shapes — the
search response (``{api, index, query.text, candidates: [{docid, rank, score,
doc}]}``) and the doc-fetch wrapper (``{api, index, docid, doc}``) — and one
awkward rule: ``doc`` "allows this payload to be a string, object, array, number,
boolean, or null depending on index contents and ``parse`` behavior". So the
polymorphism is not hypothetical; the same code has to survive a flip in the
hosted API's parse mode without turning every passage into ``None``.

The other spec rule tested here is the one that keeps the *submission* valid:
"If a system chunks documents internally, keep final ``references`` tied to
ClimbMix document IDs." That contract lives entirely in
``utils.search_types.classify_id`` / ``make_hit`` — the ``id`` vs ``docid`` split
is what lets a chunk-level index feed a doc-level ``references`` list.

Everything here is offline: the search clients are exercised by substituting
their JSON transport (``_get_json`` / ``urlopen``), never by hitting the API.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from utils.fetch_doc import _doc_text, fetch_doc
from utils.search_pyserini import search_pyserini
from utils.search_types import classify_id, make_hit

from conftest import CLIMBMIX_DOCIDS

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Search response envelope
# ---------------------------------------------------------------------------
def test_search_response_top_level_keys(
        fake_search_response: Callable[..., dict[str, Any]]) -> None:
    """The documented envelope: ``api``, ``index``, ``query.text``, ``candidates``."""
    resp = fake_search_response("congestion pricing MTA funding", 3)

    assert set(resp) == {"api", "index", "query", "candidates"}
    assert resp["api"] == "v1"
    assert resp["index"] == "climbmix-400b"          # the configured index name
    assert resp["query"]["text"] == "congestion pricing MTA funding"
    assert len(resp["candidates"]) == 3


def test_candidate_keys_and_field_types(
        fake_search_response: Callable[..., dict[str, Any]]) -> None:
    """Each candidate carries exactly ``docid``/``rank``/``score``/``doc``."""
    resp = fake_search_response(k=4)

    for i, cand in enumerate(resp["candidates"], start=1):
        assert set(cand) == {"docid", "rank", "score", "doc"}
        assert isinstance(cand["docid"], str)
        assert cand["rank"] == i                     # 1-based, ascending
        assert isinstance(cand["score"], float)
    scores = [c["score"] for c in resp["candidates"]]
    assert scores == sorted(scores, reverse=True)    # rank order == score order


def test_candidate_docids_are_climbmix_shard_ids(
        fake_search_response: Callable[..., dict[str, Any]]) -> None:
    """``docid`` is the ClimbMix external id, not an MS MARCO segment id.

    ``retrieval-task.md``: "Do not emit MS MARCO segment IDs unless official 2026
    instructions explicitly require a mapping step."
    """
    resp = fake_search_response(k=4)

    for cand in resp["candidates"]:
        assert cand["docid"] in CLIMBMIX_DOCIDS
        shard, _, row = cand["docid"].partition("_")[2].partition("_")
        assert shard.isdigit() and row.isdigit()
        assert "#" not in cand["docid"]              # msmarco segment marker


# ---------------------------------------------------------------------------
# `doc` polymorphism — string vs object
# ---------------------------------------------------------------------------
def _stub_pyserini(monkeypatch: pytest.MonkeyPatch,
                   response: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace the client's JSON transport; return a log of request params."""
    import utils.search_pyserini as mod

    seen: list[dict[str, Any]] = []

    def _fake(url: str, params: dict[str, Any], token: str | None,
              timeout: float) -> dict[str, Any]:
        seen.append({"url": url, "params": params, "token": token})
        return response

    monkeypatch.setattr(mod, "_get_json", _fake)
    return seen


def test_search_pyserini_maps_string_doc_to_hit_text(
        monkeypatch: pytest.MonkeyPatch,
        fake_search_response: Callable[..., dict[str, Any]]) -> None:
    """The common case: ``doc`` is a string, used directly as the passage text."""
    resp = fake_search_response("q", 2, doc_as_object=False)
    _stub_pyserini(monkeypatch, resp)

    hits = search_pyserini("q", k=2)

    assert [h["docid"] for h in hits] == [c["docid"] for c in resp["candidates"]]
    assert [h["text"] for h in hits] == [c["doc"] for c in resp["candidates"]]
    assert [h["rank"] for h in hits] == [1, 2]
    assert all(h["meta"]["source"] == "pyserini" for h in hits)
    assert all(h["meta"]["index"] == "climbmix-400b" for h in hits)
    assert all(h["meta"]["api"] == "v1" for h in hits)


def test_search_pyserini_extracts_the_text_field_of_an_object_doc(
        monkeypatch: pytest.MonkeyPatch,
        fake_search_response: Callable[..., dict[str, Any]]) -> None:
    """An object ``doc`` must be unwrapped, per the spec, not copied verbatim.

    ``retrieval-task.md``: "If ``doc`` is an object, extract its text-bearing
    field such as ``text`` or ``contents``; if it is a string, use the string
    directly." A dict reaching ``SearchHit["text"]`` (typed ``str | None``) is
    what makes ``run_search_tool``'s ``text[:max_chars]`` raise ``TypeError``,
    so a parse-mode flip on the hosted API would take down the tool layer rather
    than degrade it.

    The client shares ``fetch_doc._doc_text`` so the two cannot drift.
    """
    resp = fake_search_response("q", 1, doc_as_object=True)
    _stub_pyserini(monkeypatch, resp)

    hits = search_pyserini("q", k=1)

    assert isinstance(resp["candidates"][0]["doc"], dict)
    assert hits[0]["text"] == resp["candidates"][0]["doc"]["text"]
    assert isinstance(hits[0]["text"], str)


def test_search_pyserini_missing_doc_is_none(
        monkeypatch: pytest.MonkeyPatch,
        fake_search_response: Callable[..., dict[str, Any]]) -> None:
    """A candidate without ``doc`` (fields=none style response) yields ``text=None``
    rather than raising — a docid-only run is still usable for the retrieval task."""
    resp = fake_search_response("q", 1)
    del resp["candidates"][0]["doc"]
    _stub_pyserini(monkeypatch, resp)

    hits = search_pyserini("q", k=1)

    assert hits[0]["text"] is None
    assert hits[0]["docid"] == CLIMBMIX_DOCIDS[0]


def test_search_pyserini_synthesizes_rank_when_absent(
        monkeypatch: pytest.MonkeyPatch,
        fake_search_response: Callable[..., dict[str, Any]]) -> None:
    """``rank`` is optional in practice; the client falls back to list position."""
    resp = fake_search_response("q", 3)
    for cand in resp["candidates"]:
        del cand["rank"]
    _stub_pyserini(monkeypatch, resp)

    assert [h["rank"] for h in search_pyserini("q", k=3)] == [1, 2, 3]


@pytest.mark.parametrize("doc, expected", [
    pytest.param("plain document text", "plain document text", id="string"),
    pytest.param({"text": "from text"}, "from text", id="object-text"),
    pytest.param({"contents": "from contents"}, "from contents",
                 id="object-contents"),
    pytest.param({"segment": "from segment"}, "from segment",
                 id="object-segment"),
    pytest.param({"body": "from body"}, "from body", id="object-body"),
    pytest.param({"text": "wins", "contents": "loses"}, "wins",
                 id="text-preferred-over-contents"),
])
def test_doc_text_extraction_follows_the_spec(doc: Any, expected: str) -> None:
    """``fetch_doc._doc_text`` is the repo's only spec-conformant ``doc`` extractor.

    ``retrieval-task.md``: "If ``doc`` is an object, extract its text-bearing field
    such as ``text`` or ``contents``; if it is a string, use the string directly."
    The key order in ``_doc_text`` is a precedence, not a set — ``text`` wins over
    ``contents`` — because a payload carrying both usually has the parsed body in
    ``text`` and the raw stored JSON in ``contents``. ``segment``/``body`` are
    accepted beyond the spec's two examples so an index-server response works too.
    Getting this wrong yields a passage that is JSON boilerplate rather than
    evidence, which produces confidently wrong cited sentences.
    """
    assert _doc_text(doc) == expected


@pytest.mark.parametrize("doc", [
    pytest.param({"unknown_field": "x"}, id="object-without-text-field"),
    pytest.param(["a", "b"], id="array"),
    pytest.param(3, id="number"),
    pytest.param(True, id="boolean"),
])
def test_doc_text_falls_back_to_json_for_exotic_payloads(doc: Any) -> None:
    """The spec permits array/number/boolean ``doc`` payloads.

    ``_doc_text`` never raises and never returns a non-``str``: anything it cannot
    recognise is re-serialized as JSON. That keeps the "text is a string"
    invariant that every downstream slice/truncation depends on, at the cost of
    handing the model a JSON blob when the API changes shape.

    ``null`` is the one exception — see
    ``test_doc_text_maps_a_null_doc_to_the_empty_string``.
    """
    out = _doc_text(doc)

    assert isinstance(out, str)
    assert json.loads(out) == doc


def test_doc_text_maps_a_null_doc_to_the_empty_string() -> None:
    """A null/absent ``doc`` is "no text", so it must not take the JSON fallback.

    ``json.dumps(None)`` is the string ``"null"``, which then behaves like a
    one-word passage: it counts toward the answer word budget, and the model can
    quote the literal word *null* into a cited sentence. ``""`` is falsy, so
    every downstream "did we get text?" check sees the truth instead.
    """
    assert _doc_text(None) == ""


def test_fetch_doc_wrapper_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """The doc-fetch wrapper ``{api, index, docid, doc}`` becomes
    ``{docid, text}`` — the docid is preserved exactly, text is extracted."""
    import utils.fetch_doc as mod

    docid = CLIMBMIX_DOCIDS[0]
    wrapper = {"api": "v1", "index": "climbmix-400b", "docid": docid,
               "doc": {"contents": "full document body"}}
    requested: list[str] = []

    class _Resp:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

    def _fake_urlopen(req: Any, timeout: float | None = None) -> Any:
        requested.append(req.full_url)
        return _Resp()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(mod.json, "load", lambda _fh: wrapper)

    out = fetch_doc(docid, url="http://example.invalid/v1/climbmix-400b/doc")

    assert out == {"docid": docid, "text": "full document body"}
    assert requested == [f"http://example.invalid/v1/climbmix-400b/doc/{docid}"]


# ---------------------------------------------------------------------------
# classify_id / make_hit: the doc-level `references` contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("unit_id, kind, docid", [
    pytest.param("shard_00000_3908_p1", "chunk", "shard_00000_3908",
                 id="chunk-page-1"),
    pytest.param("shard_00459_61697_p12", "chunk", "shard_00459_61697",
                 id="chunk-page-12"),
    pytest.param("shard_00459_61697", "document", "shard_00459_61697",
                 id="bare-docid"),
    # A `_p` that isn't followed by digits is not a page suffix.
    pytest.param("shard_00459_61697_page", "document", "shard_00459_61697_page",
                 id="_page-suffix-is-not-a-chunk"),
    pytest.param("shard_00459_61697_p", "document", "shard_00459_61697_p",
                 id="_p-without-number"),
    # Only the trailing `_p<n>` is stripped — a mid-id `_p3_` stays put.
    pytest.param("shard_00459_61697_p3_p4", "chunk", "shard_00459_61697_p3",
                 id="only-the-last-page-suffix-is-stripped"),
])
def test_classify_id(unit_id: str, kind: str, docid: str) -> None:
    """``<docid>_p<page>`` is a chunk; everything else is a document.

    This is what "keep final ``references`` tied to ClimbMix document IDs" reduces
    to in code: whatever granularity retrieval used, ``hit["docid"]`` is always the
    parent ClimbMix id that may be cited.
    """
    assert classify_id(unit_id) == (kind, docid)


def test_make_hit_derives_docid_for_a_chunk() -> None:
    """A chunk carries two identities and the pair must not collapse.

    ``id`` is the retrieval unit (what fusion dedups on, what a rerank scores);
    ``docid`` is the citable ClimbMix document (what goes in ``references`` and
    the runfile). Collapsing them either way corrupts a submission silently:
    citing ``..._p1`` yields a docid the organizers cannot resolve, while
    fusing on ``docid`` merges sibling chunks into one row and loses recall.
    """
    hit = make_hit("shard_00000_3908_p1", score=9.5, rank=1, text="passage")

    assert hit["id"] == "shard_00000_3908_p1"        # retrieval unit
    assert hit["docid"] == "shard_00000_3908"        # citable ClimbMix docid
    assert hit["kind"] == "chunk"
    assert hit["id"] != hit["docid"]


def test_make_hit_document_id_equals_docid() -> None:
    """Whole-document hits are the degenerate case of the same rule.

    Nothing downstream branches on ``kind``, so document and chunk hits have to
    be interchangeable: ``docid`` is always present and always citable. ``text``
    stays ``None`` rather than becoming ``""`` — the answer stage tests for
    absence to decide whether it must fetch the document body.
    """
    hit = make_hit(CLIMBMIX_DOCIDS[0], score=12.5, rank=1, text=None)

    assert hit["kind"] == "document"
    assert hit["docid"] == hit["id"] == CLIMBMIX_DOCIDS[0]
    assert hit["text"] is None
    assert hit["meta"] == {}


def test_make_hit_respects_backend_supplied_kind_and_docid() -> None:
    """A chunk index that returns both ids wins over the id-suffix heuristic."""
    hit = make_hit("chunk-42", score=1.0, rank=1, text="t",
                   kind="chunk", docid="shard_00210_44018")

    assert (hit["kind"], hit["docid"]) == ("chunk", "shard_00210_44018")


def test_make_hit_keys_are_exactly_the_searchhit_contract() -> None:
    """Every backend returns the same seven keys — the fusion layer depends on it."""
    hit = make_hit(CLIMBMIX_DOCIDS[1], score=1.0, rank=2, text="t",
                   meta={"source": "dense"})

    assert set(hit) == {"id", "docid", "kind", "score", "rank", "text", "meta"}


def test_fake_hits_fixture_uses_the_real_derivation(
        fake_hits: Callable[..., list[dict[str, Any]]]) -> None:
    """Sanity check on the shared fixture: chunk ids classify as chunks."""
    hits = fake_hits(2, ids=("shard_00000_3908_p1", "shard_00000_3908_p2"))

    assert [h["kind"] for h in hits] == ["chunk", "chunk"]
    assert {h["docid"] for h in hits} == {"shard_00000_3908"}


# ---------------------------------------------------------------------------
# run_search_tool: the envelope the agent actually sees
# ---------------------------------------------------------------------------
def test_run_search_tool_result_envelope(
        stub_search_tool: dict[str, list[dict[str, Any]]]) -> None:
    """``{query, k, engine, results: [{rank, id, docid, kind, score, text}]}``.

    The per-result keys are the documented projection of ``SearchHit`` — notably
    ``meta`` is dropped (backend internals never reach the model) while both ``id``
    and ``docid`` survive, so the model can cite doc-level even when retrieval was
    chunk-level.
    """
    from tools.search_tool import run_search_tool

    payload = json.loads(run_search_tool("congestion pricing", k=3,
                                         search_engine="semantic"))

    assert set(payload) == {"query", "k", "engine", "results"}
    assert (payload["query"], payload["k"], payload["engine"]) == (
        "congestion pricing", 3, "semantic")
    for i, res in enumerate(payload["results"], start=1):
        assert set(res) == {"rank", "id", "docid", "kind", "score", "text"}
        assert res["rank"] == i
        assert res["kind"] == "document"
        assert res["docid"] in CLIMBMIX_DOCIDS
    # The engine actually dispatched to is the one requested.
    assert list(stub_search_tool) == ["semantic"]
    assert stub_search_tool["semantic"][0]["k"] == 3


@pytest.mark.parametrize("max_chars", [1, 20, 80])
def test_run_search_tool_truncates_text(
        stub_search_tool: dict[str, list[dict[str, Any]]],
        max_chars: int) -> None:
    """``max_chars`` caps passage text — the context-budget lever every system
    relies on. Truncation is a prefix, so the head of the passage is kept."""
    from tools.search_tool import run_search_tool

    full = json.loads(run_search_tool("q", k=2, max_chars=None))
    capped = json.loads(run_search_tool("q", k=2, max_chars=max_chars))

    for uncut, cut in zip(full["results"], capped["results"]):
        assert len(uncut["text"]) > max_chars      # fixture text is long prose
        assert len(cut["text"]) == max_chars
        assert uncut["text"].startswith(cut["text"])


def test_run_search_tool_unknown_engine_is_an_error_envelope() -> None:
    """Errors come back as tool output so the agent can react, not as exceptions."""
    from tools.search_tool import run_search_tool

    payload = json.loads(run_search_tool("q", search_engine="not-an-engine"))

    assert set(payload) == {"error"}
    assert "not-an-engine" in payload["error"]
