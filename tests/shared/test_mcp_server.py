"""ClimbMix MCP server tool surface (``src/mcp/climbmix_server.py``).

The server exists for exactly one consumer: OpenAI Deep Research's remote-MCP
connector. That contract is rigid and *external* — DR only calls two tools, and
it only reads four keys per search result — so a rename or a missing key silently
degrades the o3-deep-research baseline into an ungrounded run rather than raising
anywhere we would notice. These tests pin the surface:

- **exactly** the tools ``search`` and ``fetch``, with the argument names DR
  sends (``query`` / ``id``);
- ``search`` rows carry ``{id, title, text, url}`` with ``id`` = the ClimbMix
  docid (the eval pipeline's join key, so it must NOT be a chunk id or a URL);
- ``fetch`` returns the *full* document, longer than the snippet ``search`` gave
  — the whole reason DR is told to fetch before citing;
- the optional bearer guard rejects unauthenticated requests, since the server is
  meant to be exposed through a public tunnel.

This file **ports the meaningful assertions of ``src/mcp/test_smoke.py``** (an
ad-hoc ``__main__`` script that boots a subprocess and hits the real hosted
backends) into offline pytest form: retrieval is stubbed at the module's own
``_run_search``/``fetch_doc`` seams, and the bearer middleware is exercised
through Starlette's in-process ASGI ``TestClient`` instead of a real socket. The
one test that genuinely needs a live server + creds is marked ``live``.

The module is loaded **by file path**, not by import: ``src/mcp`` shadows the
installed ``mcp`` SDK's name, so ``import mcp.climbmix_server`` cannot work (and
the SDK itself is only present in the ``o3-deep-research`` dep group — hence the
``importorskip``).
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest

# The MCP SDK lives in the `o3-deep-research` group, not `dev`; skip cleanly on a
# bare `uv run --group dev pytest`.
pytest.importorskip("mcp.server.fastmcp",
                    reason="MCP SDK (uv sync --group o3-deep-research)")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_PATH = _REPO_ROOT / "src" / "mcp" / "climbmix_server.py"

DOCID = "shard_00459_61697"
SNIPPET_SOURCE = ("Congestion pricing dedicates toll revenue to the MTA capital "
                  "plan, and early reporting showed traffic volumes below the "
                  "pre-toll baseline. ") * 12


def _load_server(name: str = "climbmix_server_under_test") -> ModuleType:
    """Load ``climbmix_server.py`` as a fresh module object.

    Fresh per call because the server reads its config (``MCP_SEARCH_K``,
    ``MCP_SEARCH_ENGINE``, ``PYSERINI_DOC_URL``) into module constants at import
    time, so env-driven behaviour can only be tested by re-importing.
    """
    spec = importlib.util.spec_from_file_location(name, _SERVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server() -> ModuleType:
    """The server module with default config."""
    return _load_server()


@pytest.fixture
def stub_retrieval(server: ModuleType,
                   monkeypatch: pytest.MonkeyPatch,
                   fake_hits: Callable[..., list[dict[str, Any]]]
                   ) -> dict[str, list[Any]]:
    """Replace ``_run_search`` and ``fetch_doc`` with recorders + canned data.

    Patched at the server's own seams (not the clients') so the tool bodies —
    title derivation, snippet truncation, URL building — are the code under test.
    """
    calls: dict[str, list[Any]] = {"search": [], "fetch": []}
    hits = fake_hits(3)
    hits[0]["text"] = SNIPPET_SOURCE

    def _search(query: str, k: int) -> list[dict[str, Any]]:
        calls["search"].append({"query": query, "k": k})
        return hits

    def _fetch(docid: str) -> dict[str, str]:
        calls["fetch"].append(docid)
        return {"docid": docid, "text": SNIPPET_SOURCE + "…and the full tail."}

    monkeypatch.setattr(server, "_run_search", _search)
    monkeypatch.setattr(server, "fetch_doc", _fetch)
    return calls


def _call(server: ModuleType, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Invoke a tool through the FastMCP manager, as a real MCP client would.

    Going through ``mcp.call_tool`` (rather than calling the Python function)
    exercises argument validation and the structured-output serialization that
    the wire protocol uses.
    """
    _content, structured = asyncio.run(server.mcp.call_tool(tool, args))
    return structured


# ---------------------------------------------------------------------------
# Tool surface — ported from test_smoke's `set(tools) == {"search", "fetch"}`
# ---------------------------------------------------------------------------
def test_exactly_two_tools_are_exposed(server: ModuleType) -> None:
    """DR connectors are spec'd as a two-tool surface; an extra tool (a debug
    helper left registered, say) changes what the hosted agent may call."""
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} == {"search", "fetch"}


@pytest.mark.parametrize("tool,arg", [("search", "query"), ("fetch", "id")])
def test_tool_schemas_take_one_required_string(tool: str, arg: str,
                                               server: ModuleType) -> None:
    """The argument NAMES are the contract — DR sends ``{"query": ...}`` and
    ``{"id": ...}``; renaming a parameter breaks every call, not just typing."""
    by_name = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    schema = by_name[tool].inputSchema
    assert schema["type"] == "object"
    assert schema["required"] == [arg]
    assert schema["properties"][arg]["type"] == "string"
    assert list(schema["properties"]) == [arg]


@pytest.mark.parametrize("tool,phrase", [
    # Both descriptions instruct the agent to fetch before citing — that
    # instruction is the only thing preventing citations from snippets.
    ("search", "fetch"),
    ("fetch", "before citing"),
])
def test_tool_descriptions_steer_search_then_fetch(tool: str, phrase: str,
                                                   server: ModuleType) -> None:
    """These descriptions are the only prompt we get with a hosted DR agent — we
    control no system prompt — so the "fetch before citing" instruction lives here
    or nowhere. Losing it means the agent cites 500-char snippets."""
    by_name = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert phrase in (by_name[tool].description or "")


# ---------------------------------------------------------------------------
# search — ported from test_smoke's result-shape + non-empty assertions
# ---------------------------------------------------------------------------
def test_search_rows_have_the_four_connector_keys(
        server: ModuleType, stub_retrieval: dict[str, list[Any]]) -> None:
    """The row contract DR reads. This is the assertion ported verbatim from
    ``test_smoke.py``, and the all-strings check is the addition: a ``None`` in any
    of the four would be rendered as the literal text "None" in a citation."""
    out = _call(server, "search", {"query": "congestion pricing"})
    assert out["results"], "search returned no results"
    for row in out["results"]:
        # `<=` (not `==`) mirrors test_smoke: extra keys are tolerated by DR,
        # missing ones are not.
        assert {"id", "title", "text", "url"} <= set(row)
        assert all(isinstance(row[k], str) for k in ("id", "title", "text", "url"))


def test_search_id_is_the_parent_docid_not_the_chunk_id(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch,
        fake_hits: Callable[..., list[dict[str, Any]]]) -> None:
    """The eval pipeline joins qrels on the doc-level id, and ``fetch`` only
    accepts a docid — so a chunk-granular index must still surface ``docid``."""
    monkeypatch.setattr(server, "_run_search", lambda q, k: fake_hits(
        2, ids=(f"{DOCID}_p3", "shard_01012_88420_p1")))
    ids = [r["id"] for r in _call(server, "search", {"query": "q"})["results"]]
    assert ids == [DOCID, "shard_01012_88420"]


def test_search_passes_the_configured_k(
        server: ModuleType, stub_retrieval: dict[str, list[Any]]) -> None:
    """The tool takes no ``k`` argument (DR cannot pass one), so depth comes
    solely from ``MCP_SEARCH_K``."""
    _call(server, "search", {"query": "congestion pricing"})
    assert stub_retrieval["search"] == [{"query": "congestion pricing",
                                         "k": server.SEARCH_K}]
    assert server.SEARCH_K == 10          # documented default


def test_search_truncates_text_to_the_snippet_budget(
        server: ModuleType, stub_retrieval: dict[str, list[Any]]) -> None:
    """A DR agent's context is the scarce resource here; the snippet cap is what
    keeps a 10-result search from dumping ten full documents into it."""
    assert server.SNIPPET_CHARS == 500
    row = _call(server, "search", {"query": "q"})["results"][0]
    assert len(row["text"]) == 500
    assert row["text"] == SNIPPET_SOURCE[:500]


def test_search_url_points_at_the_pyserini_doc_endpoint(
        server: ModuleType, stub_retrieval: dict[str, list[Any]]) -> None:
    """Citations need a resolvable URL while ``id`` stays the docid."""
    row = _call(server, "search", {"query": "q"})["results"][0]
    assert row["url"] == f"{server._DOC_BASE}/{row['id']}"
    assert server._DOC_BASE.endswith("/climbmix-400b/doc")


def test_search_handles_a_text_less_hit(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sparse hits can carry ``text=None``; the row must stay all-strings (and
    the title falls back to the docid) rather than emitting a JSON null."""
    from utils.search_types import make_hit

    monkeypatch.setattr(server, "_run_search", lambda q, k: [
        make_hit(DOCID, score=1.0, rank=1, text=None, meta={})])
    row = _call(server, "search", {"query": "q"})["results"][0]
    assert row["text"] == "" and row["title"] == DOCID


def test_search_empty_result_set_is_not_an_error(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero-result search must return ``{"results": []}``, not raise: an MCP tool
    error is surfaced to the DR agent as a broken connector (it may stop using the
    tool entirely) rather than as "nothing matched, try another query"."""
    monkeypatch.setattr(server, "_run_search", lambda q, k: [])
    assert _call(server, "search", {"query": "q"}) == {"results": []}


# ---------------------------------------------------------------------------
# fetch — ported from test_smoke's "full doc, longer than the snippet"
# ---------------------------------------------------------------------------
def test_fetch_returns_the_full_document_longer_than_the_snippet(
        server: ModuleType, stub_retrieval: dict[str, list[Any]]) -> None:
    """This inequality IS the reason ``fetch`` exists: if it ever returned the
    snippet, DR would cite from truncated text and never notice."""
    top = _call(server, "search", {"query": "q"})["results"][0]
    doc = _call(server, "fetch", {"id": top["id"]})
    assert doc["id"] == top["id"]
    assert len(doc["text"]) > len(top["text"])
    assert stub_retrieval["fetch"] == [top["id"]]


def test_fetch_row_shape_and_corpus_metadata(
        server: ModuleType, stub_retrieval: dict[str, list[Any]]) -> None:
    """``metadata.corpus`` is how a downstream reader knows a citation came from
    the fixed ClimbMix corpus and not the open web."""
    doc = _call(server, "fetch", {"id": DOCID})
    assert set(doc) == {"id", "title", "text", "url", "metadata"}
    assert doc["metadata"] == {"corpus": "climbmix-400b"}
    assert doc["url"] == f"{server._DOC_BASE}/{DOCID}"


def test_fetch_falls_back_to_the_requested_id_when_the_api_omits_docid(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """DR round-trips ``id`` between the two tools, so it must come back
    unchanged even from a sparse API response."""
    monkeypatch.setattr(server, "fetch_doc", lambda d: {"text": "body"})
    doc = _call(server, "fetch", {"id": DOCID})
    assert doc["id"] == DOCID and doc["url"].endswith(f"/{DOCID}")


def test_fetch_of_an_empty_document_still_titles_with_the_id(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``_title(text) or id`` fallback: an empty-bodied document must still get
    a non-empty title, since a blank title renders as an unclickable/unidentifiable
    entry in the agent's source list."""
    monkeypatch.setattr(server, "fetch_doc",
                        lambda d: {"docid": d, "text": ""})
    doc = _call(server, "fetch", {"id": DOCID})
    assert doc["text"] == "" and doc["title"] == DOCID


# ---------------------------------------------------------------------------
# _title
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Congestion pricing", "Congestion pricing"),
    # Newlines/runs of whitespace collapse: a title is rendered in a UI list.
    ("Congestion\n\npricing   revenue", "Congestion pricing revenue"),
    ("  leading and trailing  ", "leading and trailing"),
    ("", ""),
])
def test_title_normalizes_whitespace(text: str, expected: str,
                                     server: ModuleType) -> None:
    """ClimbMix bodies are raw web text full of newlines, and a title is displayed
    on one line — an unnormalized title would break the agent's source list layout
    and pad the char budget with whitespace. Axis: already-clean, embedded
    newlines/runs, surrounding padding, and empty."""
    assert server._title(text) == expected


def test_title_truncates_at_100_chars_with_an_ellipsis(server: ModuleType) -> None:
    """Exactly 100 chars is NOT truncated; 101 is — asserted on both sides of
    the boundary because an off-by-one here shows up in every DR citation."""
    assert server._title("x" * 100) == "x" * 100
    long = server._title("x" * 101)
    assert long.endswith("…") and len(long) == 101


def test_title_of_none_is_empty(server: ModuleType) -> None:
    """``h.get("text")`` can be ``None``; ``_title`` guards it rather than
    raising inside the tool body."""
    assert server._title(None) == ""


# ---------------------------------------------------------------------------
# _run_search — engine selection from MCP_SEARCH_ENGINE
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("engine,expected_fn,expects_with_text", [
    (None, "hybrid_search", True),        # default: dense+sparse RRF
    ("hybrid", "hybrid_search", True),
    ("semantic", "search_dense", True),
    ("keyword", "search_sparse", False),  # sparse client has no with_text arg
    ("nonsense", "hybrid_search", True),  # unknown value falls back to hybrid
])
def test_engine_selection(engine: str | None, expected_fn: str,
                          expects_with_text: bool,
                          monkeypatch: pytest.MonkeyPatch) -> None:
    """``MCP_SEARCH_ENGINE`` is read at import, so each case re-loads the module.

    ``with_text`` matters: passing it to ``search_sparse`` would be a TypeError,
    and NOT passing it to the dense/hybrid path would return text-less hits and
    make every snippet empty.
    """
    monkeypatch.delenv("MCP_SEARCH_ENGINE", raising=False)
    if engine is not None:
        monkeypatch.setenv("MCP_SEARCH_ENGINE", engine)
    mod = _load_server(f"climbmix_server_{engine}")

    calls: list[dict[str, Any]] = []
    for name in ("hybrid_search", "search_dense", "search_sparse"):
        monkeypatch.setattr(mod, name, (
            lambda n: lambda q, k, **kw: (calls.append(
                {"fn": n, "query": q, "k": k, **kw}) or []))(name))

    assert mod._run_search("congestion pricing", 7) == []
    assert len(calls) == 1
    assert calls[0]["fn"] == expected_fn
    assert calls[0]["k"] == 7
    assert ("with_text" in calls[0]) is expects_with_text


def test_an_unrecognised_engine_warns_before_falling_back(
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """The hybrid fallback must be announced on stderr, not silent.

    A typo'd ``MCP_SEARCH_ENGINE=semanic`` ran a whole experiment on the wrong
    retriever with nothing in the logs to say so — the run looked healthy and the
    comparison it fed was meaningless. Falling back is still right (a live server
    should not refuse to start over one env var), so the warning is the fix.
    """
    monkeypatch.setenv("MCP_SEARCH_ENGINE", "semanic")
    mod = _load_server("climbmix_server_typo")

    err = capsys.readouterr().err
    assert "semanic" in err
    assert "hybrid" in err
    assert mod.SEARCH_ENGINE == "semanic"  # the raw value is not rewritten


@pytest.mark.parametrize("var,attr,raw,expected", [
    ("MCP_SEARCH_K", "SEARCH_K", "25", 25),
    ("MCP_SNIPPET_CHARS", "SNIPPET_CHARS", "1200", 1200),
])
def test_numeric_config_is_read_from_the_environment(
        var: str, attr: str, raw: str, expected: int,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Both knobs are the tuning surface for a DR run's context budget."""
    monkeypatch.setenv(var, raw)
    assert getattr(_load_server(f"climbmix_server_{var}"), attr) == expected


def test_doc_base_follows_pyserini_doc_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trailing slash stripped, so citation URLs never contain ``//``."""
    monkeypatch.setenv("PYSERINI_DOC_URL", "https://mirror.invalid/v1/x/doc/")
    assert _load_server("climbmix_server_docbase")._DOC_BASE == \
        "https://mirror.invalid/v1/x/doc"


# ---------------------------------------------------------------------------
# build_app — the bearer guard (ported from test_smoke's "unauthenticated
# request rejected" check, without a subprocess)
# ---------------------------------------------------------------------------
def _post_initialize(app: Any, headers: dict[str, str] | None = None) -> Any:
    """POST an MCP ``initialize`` through Starlette's in-process ASGI client.

    No socket is opened (``TestClient`` speaks ASGI directly), so this stays
    inside the autouse ``no_network`` fixture's rules.
    """
    from starlette.testclient import TestClient

    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}}}
    with TestClient(app) as client:
        return client.post("/mcp", json=body, headers=headers or {})


def test_bearer_guard_rejects_a_missing_token(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The server is meant to be tunnelled to a public URL for OpenAI's servers
    to reach, so the token is the ONLY thing standing between the corpus
    endpoints and the internet."""
    monkeypatch.setenv("CLIMBMIX_MCP_TOKEN", "secret-token")
    resp = _post_initialize(server.build_app())
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


@pytest.mark.parametrize("header", ["Bearer wrong", "secret-token",
                                    "Basic secret-token", ""])
def test_bearer_guard_rejects_a_wrong_or_malformed_token(
        header: str, server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The comparison is against the exact ``Bearer <token>`` string — a bare
    token or the wrong scheme is rejected, not leniently parsed."""
    monkeypatch.setenv("CLIMBMIX_MCP_TOKEN", "secret-token")
    resp = _post_initialize(server.build_app(),
                            {"Authorization": header})
    assert resp.status_code == 401


def test_bearer_guard_lets_a_correct_token_reach_the_mcp_layer(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """A correct token must get *past* the middleware. The request then fails
    inside the SDK on content negotiation (406: our minimal client sends no
    ``Accept``), which is precisely the signal that the guard was cleared —
    anything other than 401 proves that."""
    monkeypatch.setenv("CLIMBMIX_MCP_TOKEN", "secret-token")
    resp = _post_initialize(server.build_app(),
                            {"Authorization": "Bearer secret-token"})
    assert resp.status_code != 401
    assert resp.status_code == 406


def test_no_guard_is_installed_without_a_token(
        server: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local/loopback use needs no token; the middleware is only added when
    ``CLIMBMIX_MCP_TOKEN`` is set, so an unset token is not a 401 trap."""
    monkeypatch.delenv("CLIMBMIX_MCP_TOKEN", raising=False)
    assert _post_initialize(server.build_app()).status_code != 401


def test_app_is_stateless_streamable_http(server: ModuleType) -> None:
    """OpenAI's DR connector guidance is stateless streamable-HTTP, and the SDK's
    DNS-rebinding protection must stay OFF or every tunnelled POST 421s (the Host
    header is the tunnel's, not localhost)."""
    assert server.mcp.settings.stateless_http is True
    assert server.mcp.settings.json_response is True
    security = server.mcp.settings.transport_security
    assert security is not None
    assert security.enable_dns_rebinding_protection is False


# ---------------------------------------------------------------------------
# Live: the part of test_smoke.py that cannot be made offline
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_smoke_end_to_end_against_the_real_backends() -> None:
    """Full ``src/mcp/test_smoke.py`` flow: boot the server as a subprocess with
    the bearer guard ON, drive it with the official MCP client over
    streamable-HTTP, then ``search`` and ``fetch`` against the real hosted
    retrieval endpoints.

    Live-only because it needs (a) a real listening socket for the SDK's HTTP
    client and (b) credentials for the ClimbMix endpoints. Everything *except*
    the transport and the backends is covered offline above.
    """
    import os
    import subprocess
    import time
    import urllib.error
    import urllib.request

    port = int(os.environ.get("MCP_TEST_PORT", "8721"))
    token = "smoke-test-token"
    url = f"http://127.0.0.1:{port}/mcp"
    query = "index fund investing strategies"

    env = {**os.environ, "MCP_PORT": str(port), "MCP_HOST": "127.0.0.1",
           "CLIMBMIX_MCP_TOKEN": token}
    proc = subprocess.Popen([sys.executable, str(_SERVER_PATH)], env=env)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:      # any HTTP answer means uvicorn is up
            try:
                urllib.request.urlopen(url, timeout=2)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.3)
        else:
            pytest.fail("MCP server did not come up in time")

        async def _drive() -> None:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            headers = {"Authorization": f"Bearer {token}"}
            async with streamablehttp_client(url, headers=headers) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    assert names == {"search", "fetch"}

                    res = await session.call_tool("search", {"query": query})
                    payload = (res.structuredContent
                               or json.loads(res.content[0].text))
                    rows = payload["results"]
                    assert rows, "search returned no results"
                    for row in rows:
                        assert {"id", "title", "text", "url"} <= set(row)

                    top = rows[0]
                    got = await session.call_tool("fetch", {"id": top["id"]})
                    doc = (got.structuredContent
                           or json.loads(got.content[0].text))
                    assert doc["id"] == top["id"]
                    assert len(doc["text"]) > len(top["text"])

        asyncio.run(_drive())
    finally:
        proc.terminate()
        proc.wait(timeout=10)
