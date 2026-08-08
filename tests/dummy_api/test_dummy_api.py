"""Drive the REAL retrieval clients against a dummy API over a real socket.

These tests close the gap the in-process stubs leave open. ``stub_search_tool``
replaces ``tools.search_tool._DISPATCH``, so it never exercises the client
layer; here nothing is monkeypatched except the endpoint env var, and the client
code runs exactly as it does against the hosted services:

- URL construction (base + path, trailing-slash handling, docid quoting)
- HTTP verb and payload shape (POST-with-JSON vs GET-with-query-params)
- auth headers (Basic for the dsync endpoints, Bearer for Pyserini)
- the ``User-Agent`` override (the hosted proxy 403s stock ``Python-urllib``)
- response → ``SearchHit`` normalization, per backend's own envelope

Both directions are asserted: the RESPONSE mapping (dummy returns a documented
payload, client must normalize it correctly) and the REQUEST shape (the dummy
records what arrived, so a client that sends the wrong verb/field/header fails
here rather than in production).

These use real loopback sockets, so they carry ``local_socket`` — see this
package's ``conftest.py`` for why that opts out of the global ``no_network``
guard while staying entirely offline.
"""
from __future__ import annotations

import pytest

from dummy_api.dummy_server import DOCIDS, TEXTS, DummyClimbMixAPI

pytestmark = pytest.mark.local_socket


# ---------------------------------------------------------------------------
# Per-engine response mapping
# ---------------------------------------------------------------------------
def test_dense_client_maps_documented_payload(monkeypatch):
    """POST /search -> {"hits": [...]} normalizes to SearchHit."""
    from utils.search_dense import search_dense

    with DummyClimbMixAPI("dense") as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        hits = search_dense("congestion pricing", k=3)

    assert [h["docid"] for h in hits] == list(DOCIDS[:3])
    assert [h["rank"] for h in hits] == [1, 2, 3]
    assert hits[0]["score"] == pytest.approx(12.5)
    assert hits[0]["text"] == TEXTS[0]
    assert hits[0]["kind"] == "document"
    assert hits[0]["meta"]["source"] == "dense"


def test_sparse_client_maps_elasticsearch_envelope(monkeypatch):
    """POST /api/search -> {"hits": {"hits": [...]}} with _id/_score/_source."""
    from utils.search_sparse import search_sparse

    with DummyClimbMixAPI("sparse") as api:
        monkeypatch.setenv("SPARSE_SEARCH_URL", api.base_url)
        hits = search_sparse("congestion pricing", k=2)

    assert [h["docid"] for h in hits] == list(DOCIDS[:2])
    assert hits[0]["text"] == TEXTS[0]
    assert hits[0]["meta"]["source"] == "sparse"
    # The index name travels through meta so a run can be traced to its index.
    assert hits[0]["meta"]["_index"] == "climbmix-bm25"
    # The Anserini index-server takes the count as "hits", not "k".
    assert api.last_request["body"] == {"query": "congestion pricing",
                                        "hits": 2}


def test_ssr_client_synthesizes_rank_score(monkeypatch):
    """SSR exposes no numeric score, so the client derives 1/rank."""
    from utils.search_ssr import search_ssr

    with DummyClimbMixAPI("ssr") as api:
        monkeypatch.setenv("SSR_SEARCH_URL", api.base_url)
        hits = search_ssr("(^ congestion pricing)", k=3)

    assert [h["rank"] for h in hits] == [1, 2, 3]
    assert [h["score"] for h in hits] == [1.0, 0.5, pytest.approx(1 / 3, abs=1e-6)]
    assert hits[0]["meta"]["source"] == "ssr"
    assert hits[0]["meta"]["burrow"] == "burrow_01"
    # GCL text must reach the server verbatim — operators are significant.
    assert api.last_request["body"]["query"] == "(^ congestion pricing)"


def test_pyserini_client_maps_candidates(monkeypatch):
    """GET /v1/<index>/search -> {"candidates": [...]} per the track spec."""
    from utils.search_pyserini import search_pyserini

    with DummyClimbMixAPI("pyserini") as api:
        monkeypatch.setenv("PYSERINI_SEARCH_URL",
                           f"{api.base_url}/v1/climbmix-400b/search")
        hits = search_pyserini("congestion pricing", k=2)

    assert [h["docid"] for h in hits] == list(DOCIDS[:2])
    assert hits[0]["meta"] == {"source": "pyserini", "index": "climbmix-400b",
                               "api": "v1"}
    # A GET with query params, not a POST body.
    assert api.last_request["verb"] == "GET"
    assert api.last_request["params"] == {"query": "congestion pricing",
                                          "hits": "2"}


@pytest.mark.parametrize("doc_as_object", [False, True])
def test_fetch_doc_handles_both_doc_shapes(monkeypatch, doc_as_object):
    """The spec allows `doc` to be a string OR an object with a text field."""
    from utils.fetch_doc import fetch_doc

    with DummyClimbMixAPI("pyserini", doc_as_object=doc_as_object) as api:
        monkeypatch.setenv("PYSERINI_DOC_URL",
                           f"{api.base_url}/v1/climbmix-400b/doc")
        doc = fetch_doc(DOCIDS[0])

    assert doc == {"docid": DOCIDS[0], "text": TEXTS[0]}


def test_fetch_doc_quotes_the_docid(monkeypatch):
    """A docid is URL-quoted, so an id with a slash cannot forge a path."""
    from utils.fetch_doc import fetch_doc

    with DummyClimbMixAPI("pyserini") as api:
        monkeypatch.setenv("PYSERINI_DOC_URL",
                           f"{api.base_url}/v1/climbmix-400b/doc")
        fetch_doc("shard_00459_61697")
        assert api.last_request["path"].endswith("/doc/shard_00459_61697")


def test_get_documents_reads_dense_search_url_at_call_time(monkeypatch):
    """The endpoint must be resolved per call, not frozen at import.

    It used to be a module constant, so a ``.env`` loaded after this module was
    imported — or any redirection to a local service — was silently ignored and
    the request went to the hosted endpoint anyway. Nothing failed loudly; the
    chunk just came back in ``missing``.
    """
    from agent_harness.tools.get_documents import execute_get_documents

    with DummyClimbMixAPI("dense") as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        _out, documents, missing = execute_get_documents({"ids": [DOCIDS[0]]})

    assert missing == []
    assert [d["docid"] for d in documents] == [DOCIDS[0]]
    assert documents[0]["text"] == TEXTS[0]
    # The dense service answers {"docid", "text"} — not Pyserini's {"doc"}.
    assert api.last_request["path"] == f"/doc/{DOCIDS[0]}"


# ---------------------------------------------------------------------------
# Request-side contract: headers and auth
# ---------------------------------------------------------------------------
def test_dense_sends_required_user_agent(monkeypatch):
    """The hosted proxy 403s the stock urllib UA — this is a regression guard."""
    from utils.search_dense import search_dense

    with DummyClimbMixAPI("dense") as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        search_dense("q", k=1)

    headers = api.last_request["headers"]
    assert headers["User-Agent"] == "trec-rag-search/1.0"
    assert "Python-urllib" not in headers["User-Agent"]
    assert headers["Content-Type"] == "application/json"


def test_basic_auth_is_sent_when_search_api_key_is_set(monkeypatch):
    """SEARCH_API_KEY of the form user:pass becomes a Basic header."""
    from utils.search_dense import search_dense

    with DummyClimbMixAPI("dense", require_auth=True) as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        monkeypatch.setenv("SEARCH_API_KEY", "user:pass")
        hits = search_dense("q", k=1)

    assert hits, "authorized request should have returned hits"
    # base64("user:pass") == "dXNlcjpwYXNz"
    assert api.last_request["headers"]["Authorization"] == "Basic dXNlcjpwYXNz"


def test_pyserini_sends_bearer_token(monkeypatch):
    """Pyserini uses a Bearer token, not Basic auth."""
    from utils.search_pyserini import search_pyserini

    with DummyClimbMixAPI("pyserini", require_auth=True) as api:
        monkeypatch.setenv("PYSERINI_SEARCH_URL",
                           f"{api.base_url}/v1/climbmix-400b/search")
        monkeypatch.setenv("PYSERINI_API_TOKEN", "tok-123")
        hits = search_pyserini("q", k=1)

    assert hits
    assert api.last_request["headers"]["Authorization"] == "Bearer tok-123"


def test_missing_credentials_surface_as_an_error(monkeypatch):
    """With auth required and no key, the endpoint 401s.

    The client does not swallow it — ``urlopen`` raises ``HTTPError``. This is
    the documented behaviour the tool layer converts into an ``{"error": ...}``
    envelope (see ``test_search_tool_returns_error_envelope_from_dummy_401``).
    """
    import urllib.error

    from utils.search_dense import search_dense

    with DummyClimbMixAPI("dense", require_auth=True) as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        monkeypatch.delenv("SEARCH_API_KEY", raising=False)
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            search_dense("q", k=1)

    assert excinfo.value.code == 401


# ---------------------------------------------------------------------------
# The full tool layer over the dummy API
# ---------------------------------------------------------------------------
def test_search_tool_end_to_end_over_dummy_api(monkeypatch):
    """``run_search_tool`` on top of the real client, real socket, dummy API.

    This is the deepest offline path available: agent-facing tool JSON out,
    HTTP in, nothing patched but the endpoint.
    """
    import json

    from tools.search_tool import run_search_tool

    with DummyClimbMixAPI("dense") as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        out = json.loads(run_search_tool("congestion pricing", k=2,
                                         search_engine="semantic"))

    assert out["engine"] == "semantic"
    assert out["query"] == "congestion pricing"
    assert [r["docid"] for r in out["results"]] == list(DOCIDS[:2])
    # The envelope the agent sees, per run_search_tool's docstring.
    assert set(out["results"][0]) == {"rank", "id", "docid", "kind", "score",
                                      "text"}


def test_search_tool_truncates_text_from_a_real_response(monkeypatch):
    """max_chars applies to text that arrived over the wire."""
    import json

    from tools.search_tool import run_search_tool

    with DummyClimbMixAPI("dense") as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        out = json.loads(run_search_tool("q", k=1, max_chars=10,
                                         search_engine="semantic"))

    assert out["results"][0]["text"] == TEXTS[0][:10]


def test_search_tool_returns_error_envelope_from_dummy_401(monkeypatch):
    """A backend HTTP failure must reach the agent as data, not an exception.

    The agent has to be able to react to a failed search (retry, reformulate,
    switch engine), so ``run_search_tool`` converts any client exception into
    ``{"error": "..."}``.
    """
    import json

    from tools.search_tool import run_search_tool

    with DummyClimbMixAPI("dense", require_auth=True) as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        monkeypatch.delenv("SEARCH_API_KEY", raising=False)
        out = json.loads(run_search_tool("q", k=1, search_engine="semantic"))

    assert "error" in out
    assert "HTTPError" in out["error"]


# ---------------------------------------------------------------------------
# A full RAG pipeline against the dummy API
# ---------------------------------------------------------------------------
def test_facet_rag_pipeline_over_dummy_api(monkeypatch, read_artifacts):
    """End-to-end: dummy search API + scripted orchestrator/analyzer -> valid
    TREC artifacts.

    Every external dependency is a dummy returning correctly-formatted data —
    retrieval over real HTTP, both models via ``ScriptedProvider`` — so this
    proves the whole orchestrator/analyzer pipeline works without a single
    credential. Only semantic+keyword are enabled (no hybrid), so every
    facet's mandatory-engine round hits BOTH the dense (semantic) and sparse
    (keyword) dummy endpoints, exactly like a real orchestrator writing one
    query per enabled mandatory engine.
    """
    import json
    import re

    from ragrun import validate_rag_output

    from conftest import ScriptedProvider, model_turn

    from facet_rag.pipeline import run_one

    def orchestrator_responder(pending: str, turn: int) -> dict:
        if "ALLOWED DOCIDS" in pending:
            raw = json.loads(
                re.search(r"ALLOWED DOCIDS:\s*(\[.*?\])", pending,
                          re.DOTALL).group(1))
            # Entries may be bare docid strings or {"docid": ..., "excerpt":
            # ...} objects (PLAN.md §3.4 -- the formatter now sees evidence
            # text).
            allowed = [d["docid"] if isinstance(d, dict) else d for d in raw]
            cite = [allowed[0]] if allowed else []
            return model_turn(text=json.dumps({"sentences": [
                {"text": "Congestion pricing funds transit capital work.",
                 "citations": cite},
                {"text": "Costs fall mainly on higher-income peak drivers.",
                 "citations": cite},
            ]}))
        if "FACET: revenue" in pending:
            return model_turn(text=json.dumps({
                "queries": {"semantic": "congestion pricing MTA revenue dense",
                           "keyword": "congestion pricing MTA revenue sparse"},
                "boolean_engine": None, "boolean_query": None}))
        if "FACET: equity" in pending:
            return model_turn(text=json.dumps({
                "queries": {"semantic": "congestion pricing who pays equity dense",
                           "keyword": "congestion pricing who pays equity sparse"},
                "boolean_engine": None, "boolean_query": None}))
        if "EVIDENCE:" in pending:  # draft synthesis
            docids = re.findall(r"docid=(\S+)", pending)
            cite = f"[{docids[0]}]" if docids else ""
            return model_turn(text=(
                f"Congestion pricing dedicates revenue to transit {cite}. "
                f"Most peak-period drivers have higher incomes {cite}."))
        if "RESEARCH NARRATIVE:" in pending:  # plan
            return model_turn(text=json.dumps({"facets": [
                {"name": "revenue",
                 "description": "How does congestion pricing fund MTA "
                                "capital work?", "max_iterations": 2},
                {"name": "equity",
                 "description": "Who bears the cost of congestion pricing?",
                 "max_iterations": 2},
            ]}))
        raise AssertionError(
            f"unrecognised orchestrator prompt at turn {turn}: {pending[:150]!r}")

    def analyzer_responder(pending: str, turn: int) -> dict:
        if "DRAFT:" in pending:  # fact-check pass, pass the draft through
            docids = re.findall(r"docid=(\S+)", pending)
            cite = f"[{docids[0]}]" if docids else ""
            return model_turn(text=(
                f"Congestion pricing dedicates revenue to transit {cite}. "
                f"Most peak-period drivers have higher incomes {cite}."))
        if "EVIDENCE POOL:" in pending:  # curator pass (reuses this role/model)
            docids = list(dict.fromkeys(re.findall(r"docid=(\S+)", pending)))
            ranking = [{"docid": d, "redundant_with": None} for d in docids]
            return model_turn(text=json.dumps(
                {"ranking": ranking, "gap": None, "covered": True}))
        if "NEWLY RETRIEVED PASSAGES:" in pending:
            docids = re.findall(r"\[docid=(\S+?)\]", pending)
            relevant = ([{"docid": docids[0], "note": "supports the facet"}]
                       if docids else [])
            return model_turn(text=json.dumps(
                {"relevant": relevant, "gap": None, "satisfied": True}))
        raise AssertionError(
            f"unrecognised analyzer prompt at turn {turn}: {pending[:150]!r}")

    with DummyClimbMixAPI("dense") as dense, DummyClimbMixAPI("sparse") as sparse:
        # Both engines the orchestrator's facet turns pin are backed by their
        # own dummy endpoint.
        monkeypatch.setenv("DENSE_SEARCH_URL", dense.base_url)
        monkeypatch.setenv("SPARSE_SEARCH_URL", sparse.base_url)
        result = run_one(
            lambda: ScriptedProvider(orchestrator_responder),
            lambda: ScriptedProvider(analyzer_responder),
            qid="rag2026-37",
            narrative="Is congestion pricing a fair way to fund the MTA?",
            engines=["semantic", "keyword"],
            run_id="dummy-api.test", run_desc="dummy API end-to-end",
            orchestrator_model_id="scripted/test-model",
            analyzer_model_id="scripted/test-model",
            max_chars=2000, min_facets=2, max_facets=2, format_llm=True)

        # Each engine was reached over its own socket, once per facet (both
        # mandatory engines are enabled and queried every round now).
        assert len(dense.requests) == 2
        assert len(sparse.requests) == 2

    artifacts = read_artifacts(result["paths"])
    assert validate_rag_output(artifacts["output"]) == []
    assert artifacts["violations"] == []
    assert result["references"]
    # References must be real docids that came back from the dummy API.
    assert set(result["references"]) <= set(DOCIDS)
