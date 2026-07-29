"""Per-engine retrieval client normalization (``src/utils/search_*.py``).

Every client answers the same question — "given this backend's wire format,
what ``SearchHit`` comes out?" — and each backend's format is different (dense
``hits[]``, sparse Elasticsearch-shaped ``hits.hits[]``, SSR ``results[]`` with
``docno``, Lucene ``BoolSearch`` stdout lines, Pyserini ``candidates[]``). The
fusion layer, the tool envelope, and the citation code all assume that
normalization is exact, so it is tested per client rather than end-to-end.

Two things beyond mapping are pinned here because both have bitten us:

- **Request shape.** ``complexity``/``beam_width`` must be *absent* from the
  dense body unless asked for (the server applies its own defaults, and sending
  ``null`` is not the same as sending nothing), and each client must hit its own
  endpoint path (``/search`` vs ``/api/search``).
- **The ``User-Agent`` header.** The hosted endpoint's proxy 403s the stock
  ``Python-urllib/x.y`` UA. That is a one-line regression away at all times, so
  the header is asserted directly on the captured ``urllib`` Request.

Offline discipline: the mapping tests patch each module's own ``post_json`` /
``subprocess.run`` seam, so no socket is involved. The two tests that must see
the real request object patch ``urllib.request.urlopen`` (overriding the autouse
``no_network`` block) with a canned response.
"""
from __future__ import annotations

import base64
import io
import json
import subprocess
from typing import Any, Callable

import pytest

from utils import (fetch_doc as fetch_doc_mod, search_dense as dense_mod,
                   search_lucene_bool as lucene_mod,
                   search_pyserini as pyserini_mod, search_sparse as sparse_mod,
                   search_ssr as ssr_mod)
from utils.fetch_doc import fetch_doc
from utils.search_dense import auth_headers, search_dense
from utils.search_lucene_bool import search_lucene_bool
from utils.search_pyserini import search_pyserini
from utils.search_sparse import search_sparse
from utils.search_ssr import search_ssr

DOCIDS = ("shard_00459_61697", "shard_01012_88420")


# ---------------------------------------------------------------------------
# Transport doubles
# ---------------------------------------------------------------------------
def _capturing_post_json(payload: dict[str, Any],
                         captured: dict[str, Any]) -> Callable[..., dict[str, Any]]:
    """A ``post_json`` stand-in that records its args and returns ``payload``."""
    def _fake(url: str, body: dict[str, Any], headers: dict[str, str],
              timeout: float) -> dict[str, Any]:
        captured.update(url=url, body=body, headers=headers, timeout=timeout)
        return payload
    return _fake


def _capturing_urlopen(payload: dict[str, Any],
                       captured: dict[str, Any]) -> Callable[..., Any]:
    """A ``urllib.request.urlopen`` stand-in returning ``payload`` as JSON.

    Records the ``Request`` itself so header/method/URL assertions can be made
    against exactly what would have gone on the wire.
    """
    class _Resp(io.BytesIO):
        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *exc: Any) -> None:
            self.close()

    def _fake(req: Any, *a: Any, timeout: float | None = None,
              **kw: Any) -> "_Resp":
        captured["request"] = req
        captured["timeout"] = timeout
        return _Resp(json.dumps(payload).encode())

    return _fake


# ---------------------------------------------------------------------------
# auth_headers — shared by dense / sparse / ssr
# ---------------------------------------------------------------------------
# `no_ambient_creds` strips SEARCH_API_KEY, so each case sets what it needs.
def test_auth_headers_empty_without_a_key() -> None:
    """No key must mean NO ``Authorization`` header, not an empty one: the SSR
    client points at a bare loopback shim in dev, and a present-but-empty header
    is rejected by some proxies where an absent one is fine."""
    assert auth_headers() == {}


def test_auth_headers_empty_for_a_blank_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SEARCH_API_KEY=`` in a ``.env`` (a commented-out or half-edited line) is
    treated as unset rather than producing ``Basic `` — which would 401 with a
    confusing "bad credentials" instead of the honest "no credentials"."""
    monkeypatch.setenv("SEARCH_API_KEY", "")
    assert auth_headers() == {}


def test_auth_headers_base64_encodes_user_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """The convenience path: a human pastes ``user:pass`` into ``.env`` and the
    client does the HTTP-Basic encoding. Decoded here rather than compared to a
    literal, so the assertion states the *intent* (round-trip) not a magic
    string."""
    monkeypatch.setenv("SEARCH_API_KEY", "climbmix:s3cret")
    header = auth_headers()["Authorization"]
    token = header.removeprefix("Basic ")
    assert base64.b64decode(token).decode() == "climbmix:s3cret"


def test_auth_headers_passes_an_encoded_token_through(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A pre-encoded token has no ``:``, which is the discriminator — it must be
    forwarded verbatim, not double-encoded."""
    pre = base64.b64encode(b"climbmix:s3cret").decode()
    monkeypatch.setenv("SEARCH_API_KEY", pre)
    assert auth_headers() == {"Authorization": f"Basic {pre}"}


def test_sparse_and_ssr_share_the_one_auth_implementation() -> None:
    """There is deliberately a single copy (imported, not duplicated), so the
    three hosted clients cannot drift in how they read SEARCH_API_KEY."""
    assert sparse_mod.auth_headers is auth_headers
    assert ssr_mod.auth_headers is auth_headers
    assert sparse_mod.post_json is dense_mod.post_json
    assert ssr_mod.post_json is dense_mod.post_json


# ---------------------------------------------------------------------------
# post_json — the wire request the hosted endpoints see
# ---------------------------------------------------------------------------
def test_post_json_sets_json_content_type_and_custom_user_agent(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """REGRESSION GUARD: the endpoint proxy 403s the default urllib UA."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"hits": []}, captured))

    out = dense_mod.post_json("https://example.invalid/search", {"query": "q"},
                              {}, 7.5)
    assert out == {"hits": []}

    req = captured["request"]
    assert req.get_method() == "POST"
    assert req.full_url == "https://example.invalid/search"
    assert json.loads(req.data) == {"query": "q"}
    assert req.get_header("Content-type") == "application/json"
    assert req.get_header("User-agent") == "trec-rag-search/1.0"
    assert "Python-urllib" not in req.get_header("User-agent")
    assert captured["timeout"] == 7.5


def test_post_json_merges_auth_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller headers are spread AFTER the defaults, so auth is added rather than
    dropped — and, deliberately, a caller could also override the UA. Without
    this merge every hosted request would 401."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({}, captured))
    dense_mod.post_json("https://example.invalid/search", {},
                        {"Authorization": "Basic abc"}, 1.0)
    assert captured["request"].get_header("Authorization") == "Basic abc"


# ---------------------------------------------------------------------------
# search_dense
# ---------------------------------------------------------------------------
def _dense_payload(*, with_rank: bool = True,
                   text: str | None = "toll revenue") -> dict[str, Any]:
    hit: dict[str, Any] = {"docid": DOCIDS[0], "score": 0.8123}
    if with_rank:
        hit["rank"] = 1
    if text is not None:
        hit["text"] = text
    second: dict[str, Any] = {"docid": DOCIDS[1], "score": 0.5,
                              "text": "who pays analysis"}
    if with_rank:
        second["rank"] = 2
    return {"hits": [hit, second]}


def test_dense_maps_hits_to_search_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline mapping for the dense engine, field by field.

    ``score`` is coerced with ``float()`` on purpose: the endpoint has returned
    JSON numbers that decode as ``int`` for exact values, and RRF/rounding
    downstream assume a float. ``meta["source"]`` is ``"dense"`` (not
    ``"semantic"``, the tool-facing engine name) — the fusion breakdown and the
    worklogs key on this string, so the two vocabularies must not be conflated.
    """
    captured: dict[str, Any] = {}
    monkeypatch.setattr(dense_mod, "post_json",
                        _capturing_post_json(_dense_payload(), captured))

    hits = search_dense("congestion pricing", k=2)
    assert [h["docid"] for h in hits] == list(DOCIDS)
    assert [h["id"] for h in hits] == list(DOCIDS)
    assert [h["rank"] for h in hits] == [1, 2]
    assert [h["kind"] for h in hits] == ["document", "document"]
    assert hits[0]["score"] == pytest.approx(0.8123)
    assert isinstance(hits[0]["score"], float)
    assert hits[0]["text"] == "toll revenue"
    assert hits[0]["meta"] == {"source": "dense"}


def test_dense_rank_falls_back_to_enumeration(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend that omits ``rank`` still yields 1-based ranks, because RRF
    fuses on position and a missing rank would break ordering."""
    monkeypatch.setattr(dense_mod, "post_json",
                        _capturing_post_json(_dense_payload(with_rank=False), {}))
    assert [h["rank"] for h in search_dense("q", k=2)] == [1, 2]


def test_dense_missing_text_is_none_not_empty_string(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``None`` means "the backend returned no text" (fusion then borrows text
    from another source); ``""`` would mean "an empty document"."""
    monkeypatch.setattr(dense_mod, "post_json",
                        _capturing_post_json({"hits": [{"docid": DOCIDS[0],
                                                        "score": 1.0}]}, {}))
    assert search_dense("q")[0]["text"] is None


def test_dense_empty_payload_yields_no_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """A payload with no ``hits`` key at all (an error body, or a health-check
    style response) must degrade to zero results, because the tool layer only
    catches exceptions — a ``KeyError`` here would surface to the agent as an
    error envelope instead of an honest empty result."""
    monkeypatch.setattr(dense_mod, "post_json", _capturing_post_json({}, {}))
    assert search_dense("q") == []


def test_dense_body_omits_optional_knobs_by_default(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent != ``null``. DiskANN's ``complexity``/``beam_width`` govern the
    recall/latency trade-off, and the server applies tuned defaults only when the
    keys are missing; sending ``null`` would either error or reset them. Building
    the body with the keys always present is the natural refactor that breaks
    this, hence the explicit ``not in`` assertions."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(dense_mod, "post_json",
                        _capturing_post_json(_dense_payload(), captured))
    search_dense("congestion pricing", k=5)
    assert captured["body"] == {"query": "congestion pricing", "k": 5,
                               "with_text": True}
    assert "complexity" not in captured["body"]
    assert "beam_width" not in captured["body"]


def test_dense_body_includes_knobs_when_passed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the above: when a sweep *does* set the DiskANN knobs they
    must reach the wire under those exact names, or a recall/latency experiment
    silently measures the server defaults over and over."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(dense_mod, "post_json",
                        _capturing_post_json(_dense_payload(), captured))
    search_dense("q", k=3, with_text=False, complexity=150, beam_width=8)
    assert captured["body"] == {"query": "q", "k": 3, "with_text": False,
                                "complexity": 150, "beam_width": 8}


@pytest.mark.parametrize("env_url,arg_url,expected", [
    (None, None, dense_mod.DEFAULT_DENSE_URL + "/search"),
    ("https://env.invalid", None, "https://env.invalid/search"),
    # trailing slashes are stripped so the path never doubles up
    ("https://env.invalid/", None, "https://env.invalid/search"),
    ("https://env.invalid", "https://arg.invalid/", "https://arg.invalid/search"),
])
def test_dense_endpoint_precedence(env_url: str | None, arg_url: str | None,
                                   expected: str,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit ``url=`` > ``DENSE_SEARCH_URL`` > the hosted default constant."""
    captured: dict[str, Any] = {}
    monkeypatch.delenv("DENSE_SEARCH_URL", raising=False)
    if env_url:
        monkeypatch.setenv("DENSE_SEARCH_URL", env_url)
    monkeypatch.setattr(dense_mod, "post_json",
                        _capturing_post_json(_dense_payload(), captured))
    search_dense("q", url=arg_url)
    assert captured["url"] == expected


def test_dense_passes_auth_headers_and_timeout_through(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``search_dense`` must call ``auth_headers()`` per request (not cache it at
    import), which is what lets a test — or a runner that loads ``.env`` late —
    set the key after the module is imported. The ``timeout`` assertion guards
    against the value being dropped, which would leave a hung endpoint blocking
    an agent turn forever."""
    captured: dict[str, Any] = {}
    monkeypatch.setenv("SEARCH_API_KEY", "u:p")
    monkeypatch.setattr(dense_mod, "post_json",
                        _capturing_post_json(_dense_payload(), captured))
    search_dense("q", timeout=12.0)
    assert captured["headers"] == auth_headers()
    assert captured["timeout"] == 12.0


# ---------------------------------------------------------------------------
# search_sparse — Elasticsearch-shaped index-server response
# ---------------------------------------------------------------------------
def _sparse_payload() -> dict[str, Any]:
    return {"hits": {"total": {"value": 2}, "hits": [
        {"_id": DOCIDS[0], "_score": 11.42, "_index": "climbmix-bm25",
         "_source": {"contents": "toll revenue"}},
        # No `_source` at all — the client must not KeyError on it.
        {"_id": DOCIDS[1], "_score": 9.01, "_index": "climbmix-bm25"},
    ]}}


def test_sparse_maps_nested_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """index-server answers in Elasticsearch's doubly-nested ``hits.hits[]`` shape
    with underscore-prefixed fields, so this mapping shares nothing with the dense
    one. The second fixture hit deliberately omits ``_source`` entirely — a real
    occurrence when the index stores no text — to prove the ``or {}`` guard means
    ``text is None`` rather than a ``KeyError`` mid-list."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(sparse_mod, "post_json",
                        _capturing_post_json(_sparse_payload(), captured))
    hits = search_sparse("congestion pricing", k=2)
    assert [h["docid"] for h in hits] == list(DOCIDS)
    assert [h["rank"] for h in hits] == [1, 2]
    assert hits[0]["score"] == pytest.approx(11.42)
    assert hits[0]["text"] == "toll revenue"
    assert hits[1]["text"] is None            # missing `_source` -> None, not ""
    assert hits[0]["meta"] == {"source": "sparse", "granularity": "chunk",
                               "_index": "climbmix-bm25"}


def test_sparse_rank_is_always_positional(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike dense, the sparse client ignores any payload ``rank`` and always
    enumerates — index-server returns results already ordered by score."""
    payload = _sparse_payload()
    payload["hits"]["hits"][0]["rank"] = 99
    monkeypatch.setattr(sparse_mod, "post_json",
                        _capturing_post_json(payload, {}))
    assert [h["rank"] for h in search_sparse("q")] == [1, 2]


def test_sparse_uses_hits_key_for_k_and_the_api_search_path(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """index-server's parameter is ``hits``, not ``k`` — a silent rename here
    would make every request fall back to the server default depth."""
    captured: dict[str, Any] = {}
    monkeypatch.delenv("SPARSE_SEARCH_URL", raising=False)
    monkeypatch.setattr(sparse_mod, "post_json",
                        _capturing_post_json(_sparse_payload(), captured))
    search_sparse("congestion pricing", k=25)
    assert captured["body"] == {"query": "congestion pricing", "hits": 25}
    assert captured["url"] == sparse_mod.DEFAULT_SPARSE_URL + "/api/search"


def test_sparse_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pointing the sparse client at a local ``:8085`` index-server is the normal
    dev/eval workflow, and both rungs (env var, explicit ``url=``) are used — the
    latter by sweeps that hit two servers in one process."""
    captured: dict[str, Any] = {}
    monkeypatch.setenv("SPARSE_SEARCH_URL", "http://127.0.0.1:8085/")
    monkeypatch.setattr(sparse_mod, "post_json",
                        _capturing_post_json(_sparse_payload(), captured))
    search_sparse("q")
    assert captured["url"] == "http://127.0.0.1:8085/api/search"
    search_sparse("q", url="http://other:9/")
    assert captured["url"] == "http://other:9/api/search"


def test_sparse_empty_payload_yields_no_hits(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Both levels of the nesting are ``.get``-guarded, so neither a missing
    ``hits`` envelope nor a missing inner ``hits`` list raises — same reasoning as
    the dense case: no results is not an error."""
    monkeypatch.setattr(sparse_mod, "post_json", _capturing_post_json({}, {}))
    assert search_sparse("q") == []


# ---------------------------------------------------------------------------
# search_ssr — GCL Boolean, docno + synthesized 1/rank score
# ---------------------------------------------------------------------------
def _ssr_payload(*, with_rank: bool = True) -> dict[str, Any]:
    rows = [{"docno": DOCIDS[0], "snippet": "…uranium enrichment…",
             "burrow": "group00"},
            {"docno": DOCIDS[1], "snippet": None, "burrow": "group07"}]
    if with_rank:
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
    return {"results": rows}


def test_ssr_maps_docno_and_synthesizes_reciprocal_rank_scores(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """SSR exposes no numeric score, so the client fabricates ``1/rank`` purely
    for stable descending order — asserted because downstream code sorts on it."""
    monkeypatch.setattr(ssr_mod, "post_json",
                        _capturing_post_json(_ssr_payload(), {}))
    hits = search_ssr("(^ uranium enrichment)", k=2)
    assert [h["docid"] for h in hits] == list(DOCIDS)
    assert [h["rank"] for h in hits] == [1, 2]
    assert [h["score"] for h in hits] == [1.0, 0.5]
    assert hits[0]["score"] > hits[1]["score"]
    assert hits[0]["text"] == "…uranium enrichment…"
    assert hits[1]["text"] is None
    assert hits[0]["meta"] == {"source": "ssr", "burrow": "group00"}


def test_ssr_rank_falls_back_to_enumeration(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Rank matters twice as much for SSR as elsewhere: it is also the *score*
    (``1/rank``). A rank-less payload defaulting to 0 would raise
    ``ZeroDivisionError``; defaulting to a constant would make every hit score
    identically and destroy the ordering the fan-out shim produced."""
    monkeypatch.setattr(ssr_mod, "post_json",
                        _capturing_post_json(_ssr_payload(with_rank=False), {}))
    hits = search_ssr("(^ a b)")
    assert [h["rank"] for h in hits] == [1, 2]
    assert [h["score"] for h in hits] == [1.0, 0.5]


def test_ssr_score_is_rounded_to_six_places(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``1/rank`` is non-terminating for most ranks, and these scores get written
    into ``data/outputs`` run artifacts — rounding keeps them short and makes two
    runs of the same query diff cleanly instead of on float noise. 6dp still
    separates ranks well past k=1000."""
    monkeypatch.setattr(ssr_mod, "post_json", _capturing_post_json(
        {"results": [{"docno": DOCIDS[0], "rank": 3, "snippet": "x"}]}, {}))
    assert search_ssr("(^ a b)")[0]["score"] == round(1 / 3, 6)


def test_ssr_string_rank_is_coerced_to_int(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``int(h.get("rank", i))`` — a JSON string rank still yields an int rank,
    which matters because the tool envelope and RRF index on it."""
    monkeypatch.setattr(ssr_mod, "post_json", _capturing_post_json(
        {"results": [{"docno": DOCIDS[0], "rank": "2", "snippet": "x"}]}, {}))
    hit = search_ssr("(^ a b)")[0]
    assert hit["rank"] == 2 and isinstance(hit["rank"], int)


def test_ssr_endpoint_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two SSR-specific details. The body key is ``k`` (the dense spelling), not
    the sparse ``hits`` — easy to copy wrong given the client is a near-clone of
    the sparse one. And the default timeout is 60 s, double the others, because a
    GCL Boolean query fans out across 26 group-burrows; lowering it to the 30 s
    "consistent" value would start timing out real queries."""
    captured: dict[str, Any] = {}
    monkeypatch.delenv("SSR_SEARCH_URL", raising=False)
    monkeypatch.setattr(ssr_mod, "post_json",
                        _capturing_post_json(_ssr_payload(), captured))
    search_ssr("(^ a b)", k=4)
    assert captured["url"] == ssr_mod.DEFAULT_SSR_URL + "/search"
    assert captured["body"] == {"query": "(^ a b)", "k": 4}
    assert captured["timeout"] == 60.0            # SSR's slower default

    monkeypatch.setenv("SSR_SEARCH_URL", "http://127.0.0.1:8099")
    search_ssr("(^ a b)")
    assert captured["url"] == "http://127.0.0.1:8099/search"


def test_ssr_empty_result_set_is_an_empty_list(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The "truthful zero" a required-but-absent term produces."""
    monkeypatch.setattr(ssr_mod, "post_json",
                        _capturing_post_json({"results": []}, {}))
    assert search_ssr("(^ impossible cooccurrence)") == []


# ---------------------------------------------------------------------------
# search_lucene_bool — stdout of a short-lived JVM, not HTTP
# ---------------------------------------------------------------------------
_BS_STDOUT = """\
query: +uranium +enrichment
hits: 2
[1] shard_00459_61697 score=10.11
    Uranium enrichment capacity expanded through 2025.
[2] shard_01012_88420 score=8.04
    Enrichment services contracts were renegotiated.
"""


class _Completed:
    """Minimal ``subprocess.CompletedProcess`` stand-in."""

    def __init__(self, stdout: str = "", stderr: str = "",
                 returncode: int = 0) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _fake_run(result: _Completed,
              captured: dict[str, Any]) -> Callable[..., _Completed]:
    def _run(cmd: list[str], **kw: Any) -> _Completed:
        captured.update(cmd=cmd, kw=kw)
        return result
    return _run


def test_lucene_bool_parses_hit_lines_and_snippets(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """This client's "wire format" is a JVM's stdout, so the regex IS the parser —
    the least stable interface in the retrieval layer, since any change to
    ``BoolSearch.java``'s print statements silently yields zero hits (non-matching
    lines are skipped, not flagged). The fixture keeps the real preamble lines
    (``query:``, ``hits:``) to prove they are ignored rather than mis-parsed."""
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(_Completed(_BS_STDOUT), {}))
    hits = search_lucene_bool("+uranium +enrichment", k=2)
    assert [h["docid"] for h in hits] == list(DOCIDS)
    assert [h["rank"] for h in hits] == [1, 2]
    assert [h["score"] for h in hits] == [pytest.approx(10.11),
                                          pytest.approx(8.04)]
    # The snippet is the indented line after the hit line, whitespace-stripped.
    assert hits[0]["text"] == "Uranium enrichment capacity expanded through 2025."
    assert hits[0]["meta"] == {"source": "lucene_bool"}
    # Non-hit preamble lines ("query:", "hits:") are ignored entirely.
    assert len(hits) == 2


def test_lucene_bool_invokes_bs_with_k_query_and_snippet_chars(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Positional CLI contract with ``bs.sh``: ``k``, query, snippet_chars — all
    stringified, and the query passed as ONE argv entry (never shell-split)."""
    captured: dict[str, Any] = {}
    monkeypatch.delenv("LUCENE_BOOL_BS", raising=False)
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(_Completed(_BS_STDOUT), captured))
    search_lucene_bool('+uranium +"enrichment services"', k=7,
                       snippet_chars=250, timeout=30.0)
    assert captured["cmd"] == ["bash", lucene_mod.DEFAULT_BS, "7",
                               '+uranium +"enrichment services"', "250"]
    assert captured["kw"]["timeout"] == 30.0
    assert captured["kw"]["capture_output"] is True and captured["kw"]["text"] is True


@pytest.mark.parametrize("source", ["env", "arg"])
def test_lucene_bool_bs_path_override(source: str,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """``DEFAULT_BS`` is an absolute path baked to one machine's ``/scratch``
    checkout, so on every other host the override IS the only working
    configuration. Axis: env var vs argument, with the env var set in both cases
    so the ``arg`` case also proves the argument wins."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(_Completed(_BS_STDOUT), captured))
    if source == "env":
        monkeypatch.setenv("LUCENE_BOOL_BS", "/tmp/bs-env.sh")
        search_lucene_bool("+a")
        assert captured["cmd"][1] == "/tmp/bs-env.sh"
    else:
        monkeypatch.setenv("LUCENE_BOOL_BS", "/tmp/bs-env.sh")
        search_lucene_bool("+a", bs_path="/tmp/bs-arg.sh")
        assert captured["cmd"][1] == "/tmp/bs-arg.sh"


def test_lucene_bool_raises_on_nonzero_exit(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A Lucene ParseException must become a RuntimeError so the tool layer can
    turn it into an ``{"error": ...}`` envelope the agent can correct from."""
    monkeypatch.setattr(subprocess, "run", _fake_run(
        _Completed(stderr="ParseException: Cannot parse '+(': ", returncode=1), {}))
    with pytest.raises(RuntimeError) as excinfo:
        search_lucene_bool("+(")
    assert "exited 1" in str(excinfo.value)
    assert "ParseException" in str(excinfo.value)


def test_lucene_bool_error_message_falls_back_to_stdout(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``(stderr or stdout)``: the JVM wrapper prints some failures (missing
    index, bad k) to stdout. Without the fallback the agent would receive
    ``RuntimeError: BoolSearch exited 2:`` with an empty reason and have nothing
    to correct from."""
    monkeypatch.setattr(subprocess, "run", _fake_run(
        _Completed(stdout="index missing", stderr="", returncode=2), {}))
    with pytest.raises(RuntimeError, match="index missing"):
        search_lucene_bool("+a")


def test_lucene_bool_zero_hits_yields_empty_list(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A Boolean query whose required terms don't co-occur exits 0 with a
    ``hits: 0`` header. That must be an empty list, NOT a RuntimeError — the
    truthful zero is a useful answer for the agent, and conflating it with a
    failure would make it retry a query that was already conclusive."""
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(_Completed("query: +a +b\nhits: 0\n"), {}))
    assert search_lucene_bool("+a +b") == []


def test_lucene_bool_trailing_hit_without_a_snippet_line_gets_none_text(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A hit line as the final output line has no following snippet line."""
    monkeypatch.setattr(subprocess, "run", _fake_run(
        _Completed("[1] shard_00459_61697 score=1.5"), {}))
    assert search_lucene_bool("+a")[0]["text"] is None


def test_lucene_bool_consecutive_hit_lines_borrow_the_next_hit_line_as_text(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """ACTUAL BEHAVIOUR (arguably a bug, asserted not fixed — see report):
    ``text`` is unconditionally "the next line", so when BoolSearch emits hits
    with no snippet in between (e.g. ``snippet_chars=0``), hit 1's text becomes
    hit 2's header line. Ranks/docids/scores stay correct, so this only pollutes
    the snippet text."""
    stdout = ("[1] shard_00459_61697 score=2.0\n"
              "[2] shard_01012_88420 score=1.0\n")
    monkeypatch.setattr(subprocess, "run", _fake_run(_Completed(stdout), {}))
    hits = search_lucene_bool("+a", snippet_chars=0)
    assert [h["rank"] for h in hits] == [1, 2]
    assert hits[0]["text"] == "[2] shard_01012_88420 score=1.0"
    assert hits[1]["text"] is None


def test_lucene_bool_parses_negative_scores(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``_HIT_RE`` allows a leading ``-``; asserted so the char class is not
    "simplified" away."""
    monkeypatch.setattr(subprocess, "run", _fake_run(
        _Completed("[1] shard_00459_61697 score=-0.5\n  snip\n"), {}))
    assert search_lucene_bool("+a")[0]["score"] == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# search_pyserini — hosted GET API with a Bearer token
# ---------------------------------------------------------------------------
def test_pyserini_maps_candidates(fake_search_response: Callable[..., dict[str, Any]],
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Driven by the canonical spec payload fixture, so the client is checked
    against the shape the track documents rather than a local invention."""
    payload = fake_search_response("congestion pricing MTA funding", 3)
    captured: dict[str, Any] = {}
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen(payload, captured))

    hits = search_pyserini("congestion pricing MTA funding", k=3)
    assert len(hits) == 3
    assert [h["rank"] for h in hits] == [1, 2, 3]
    assert [h["docid"] for h in hits] == [c["docid"] for c in payload["candidates"]]
    assert hits[0]["score"] == pytest.approx(payload["candidates"][0]["score"])
    # `doc` as a bare string is the text.
    assert hits[0]["text"] == payload["candidates"][0]["doc"]
    assert hits[0]["meta"] == {"source": "pyserini", "index": "climbmix-400b",
                               "api": "v1"}


def test_pyserini_doc_as_object_is_NOT_unwrapped(
        fake_search_response: Callable[..., dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """ACTUAL BEHAVIOUR (asserted, not fixed — see report): ``search_pyserini``
    copies ``candidate["doc"]`` straight into ``text``, so when the API returns
    ``doc`` as an OBJECT (``{"text": ...}``, which the spec permits and
    ``fake_search_response(doc_as_object=True)`` models) ``text`` ends up a dict
    instead of a string. ``utils.fetch_doc._doc_text`` handles both forms; this
    client has no equivalent."""
    payload = fake_search_response("q", 1, doc_as_object=True)
    monkeypatch.setattr("urllib.request.urlopen", _capturing_urlopen(payload, {}))
    text = search_pyserini("q", k=1)[0]["text"]
    assert isinstance(text, dict) and set(text) == {"text"}


def test_pyserini_rank_falls_back_to_enumeration(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``rank`` is documented in the API response but is not guaranteed present on
    every deployment; RRF fuses on position anyway, so enumerating keeps the
    fallback consistent with what fusion would have done regardless."""
    payload = {"index": "climbmix-400b", "api": "v1", "candidates": [
        {"docid": DOCIDS[0], "score": 12.5},
        {"docid": DOCIDS[1], "score": 11.5}]}
    monkeypatch.setattr("urllib.request.urlopen", _capturing_urlopen(payload, {}))
    assert [h["rank"] for h in search_pyserini("q")] == [1, 2]


def test_pyserini_missing_doc_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """The docids-only response mode (no ``doc`` field). ``text is None`` is what
    tells the fusion layer to borrow text from another source, and the ``None``
    entries in ``meta`` record that the payload carried no index/api identity
    rather than inventing one — the meta is read back when comparing runs across
    index versions."""
    payload = {"candidates": [{"docid": DOCIDS[0], "score": 1.0, "rank": 1}]}
    monkeypatch.setattr("urllib.request.urlopen", _capturing_urlopen(payload, {}))
    hit = search_pyserini("q")[0]
    assert hit["text"] is None
    assert hit["meta"] == {"source": "pyserini", "index": None, "api": None}


def test_pyserini_builds_a_get_with_query_and_hits_params(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike every other client this one is a GET with query-string params, so the
    query has to survive URL encoding — the ``&`` in the test query is the point:
    unencoded it would truncate the query and silently change the search. Also
    asserts no ``Authorization`` header is invented when no token is configured
    (the public endpoint works unauthenticated)."""
    captured: dict[str, Any] = {}
    monkeypatch.delenv("PYSERINI_SEARCH_URL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"candidates": []}, captured))
    search_pyserini("congestion pricing & tolls", k=17)
    req = captured["request"]
    assert req.get_method() == "GET" and req.data is None
    assert req.full_url == (pyserini_mod.DEFAULT_PYSERINI_URL
                            + "?query=congestion+pricing+%26+tolls&hits=17")
    assert req.get_header("User-agent") == "trec-rag-search/1.0"
    # No token in the env (no_ambient_creds) -> no Authorization header at all.
    assert req.get_header("Authorization") is None


@pytest.mark.parametrize("env_tok,arg_tok,expected", [
    ("env-token", None, "Bearer env-token"),
    ("env-token", "arg-token", "Bearer arg-token"),
    (None, "arg-token", "Bearer arg-token"),
])
def test_pyserini_bearer_token_precedence(env_tok: str | None,
                                          arg_tok: str | None, expected: str,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Bearer (not Basic) here — a different auth scheme from the dsync endpoints,
    with its own env var. Axis: env only, arg beating env, arg with no env; the
    middle case is the one that matters, since a script passing a token explicitly
    must not be overridden by a stale ``.env`` value."""
    captured: dict[str, Any] = {}
    if env_tok:
        monkeypatch.setenv("PYSERINI_API_TOKEN", env_tok)
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"candidates": []}, captured))
    search_pyserini("q", token=arg_tok)
    assert captured["request"].get_header("Authorization") == expected


def test_pyserini_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """``PYSERINI_SEARCH_URL`` is the FULL search URL (index name included), not a
    base — unlike every other client, which append their own path. Overriding it
    is how a different hosted index (or a mirror) is targeted, and nothing may be
    appended to it beyond the query string."""
    captured: dict[str, Any] = {}
    monkeypatch.setenv("PYSERINI_SEARCH_URL", "http://env.invalid/v1/x/search")
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"candidates": []}, captured))
    search_pyserini("q")
    assert captured["request"].full_url.startswith("http://env.invalid/v1/x/search?")
    search_pyserini("q", url="http://arg.invalid/s")
    assert captured["request"].full_url.startswith("http://arg.invalid/s?")


# ---------------------------------------------------------------------------
# fetch_doc — full document text by docid
# ---------------------------------------------------------------------------
def test_fetch_doc_string_doc(monkeypatch: pytest.MonkeyPatch) -> None:
    """The common case: ``doc`` is the text itself. ``fetch_doc`` is what an agent
    calls before citing a document, so its return contract (``{docid, text}`` with
    ``text`` always a ``str``) is what the citation/answer stage relies on."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("urllib.request.urlopen", _capturing_urlopen(
        {"docid": DOCIDS[0], "doc": "full document text"}, captured))
    assert fetch_doc(DOCIDS[0]) == {"docid": DOCIDS[0],
                                    "text": "full document text"}


@pytest.mark.parametrize("key", ["text", "contents", "segment", "body"])
def test_fetch_doc_object_doc_field_names(key: str,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """The hosted API's ``doc`` object has used several text keys; all four are
    accepted, in priority order."""
    monkeypatch.setattr("urllib.request.urlopen", _capturing_urlopen(
        {"docid": DOCIDS[0], "doc": {key: "body text", "other": 1}}, {}))
    assert fetch_doc(DOCIDS[0])["text"] == "body text"


def test_fetch_doc_object_prefers_text_over_the_others(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """When several candidate keys are present the ORDER decides, and it must be
    deterministic: an index that carries both ``text`` (full document) and
    ``contents`` (an indexed/analysed variant) would otherwise give different
    citations depending on dict iteration."""
    monkeypatch.setattr("urllib.request.urlopen", _capturing_urlopen(
        {"doc": {"body": "b", "contents": "c", "text": "t"}}, {}))
    assert fetch_doc(DOCIDS[0])["text"] == "t"


def test_fetch_doc_unrecognized_doc_is_json_dumped(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Rather than lose the payload, an unknown shape is serialized — the caller
    at least sees what came back."""
    monkeypatch.setattr("urllib.request.urlopen", _capturing_urlopen(
        {"docid": DOCIDS[0], "doc": {"weird": ["a", "b"]}}, {}))
    assert fetch_doc(DOCIDS[0])["text"] == '{"weird": ["a", "b"]}'


def test_fetch_doc_missing_docid_falls_back_to_the_request_docid(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The returned ``docid`` is what ends up in the submission's ``references``
    list, so it can never be ``None``: a response that echoes no docid must still
    yield the id we asked for, or the citation is unresolvable."""
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"doc": "text"}, {}))
    assert fetch_doc(DOCIDS[1])["docid"] == DOCIDS[1]


def test_fetch_doc_missing_doc_is_json_null_text(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """ACTUAL BEHAVIOUR: no ``doc`` key -> ``_doc_text(None)`` -> the string
    ``"null"`` (json.dumps of None), not ``""``. Asserted so the surprise is
    documented rather than discovered in a citation."""
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"docid": DOCIDS[0]}, {}))
    assert fetch_doc(DOCIDS[0])["text"] == "null"


def test_fetch_doc_url_percent_encodes_the_docid(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``safe=''`` means even ``/`` is escaped, so a weird docid cannot escape
    the doc path segment."""
    captured: dict[str, Any] = {}
    monkeypatch.delenv("PYSERINI_DOC_URL", raising=False)
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"doc": "x"}, captured))
    fetch_doc("shard_0/00 42")
    assert captured["request"].full_url == (
        fetch_doc_mod.DEFAULT_DOC_URL + "/shard_0%2F00%2042")
    assert captured["request"].get_method() == "GET"


def test_fetch_doc_bearer_token_and_url_overrides(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``PYSERINI_DOC_URL`` is a *base* (a docid path segment is appended), unlike
    the search client's full-URL env var — and the trailing slash must be stripped
    so the URL never contains ``//``, which some gateways treat as a distinct path
    and 404. Also pins that both env and argument rungs work for the token."""
    captured: dict[str, Any] = {}
    monkeypatch.setenv("PYSERINI_DOC_URL", "http://env.invalid/doc/")
    monkeypatch.setenv("PYSERINI_API_TOKEN", "env-token")
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"doc": "x"}, captured))
    fetch_doc(DOCIDS[0])
    req = captured["request"]
    assert req.full_url == f"http://env.invalid/doc/{DOCIDS[0]}"
    assert req.get_header("Authorization") == "Bearer env-token"

    fetch_doc(DOCIDS[0], url="http://arg.invalid/d", token="arg-token")
    assert captured["request"].full_url == f"http://arg.invalid/d/{DOCIDS[0]}"
    assert captured["request"].get_header("Authorization") == "Bearer arg-token"


def test_fetch_doc_no_auth_header_without_a_token(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The doc endpoint is reachable unauthenticated, so an absent token must mean
    no header at all — ``Bearer None`` would turn a working anonymous fetch into a
    401."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("urllib.request.urlopen",
                        _capturing_urlopen({"doc": "x"}, captured))
    fetch_doc(DOCIDS[0])
    assert captured["request"].get_header("Authorization") is None
