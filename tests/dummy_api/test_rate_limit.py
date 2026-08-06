"""Prove the REAL clients honour the mandated 429 backoff, over a real socket.

``tests/shared/test_http_retry.py`` covers the retry decision logic with a fake
opener. What it cannot cover is whether each client actually *routes through*
``urlopen_with_backoff`` — five separate call sites, each one an independent
chance to have been missed, and a missed one is invisible until the hosted
endpoint rate-limits us mid-run and the affected client fails alone.

So these tests point each client at a dummy server programmed to answer the
first N requests with ``429``, and assert (a) the client came back with the real
payload anyway and (b) the server saw more than one request. A client still
calling ``urllib.request.urlopen`` directly fails both.

``utils.http_retry._sleep`` is patched to a no-op: the schedule itself is
asserted in the unit tests, and real 1s/2s waits here would dominate the suite's
runtime.
"""
from __future__ import annotations

import pytest

from dummy_api.dummy_server import DOCIDS, TEXTS, DummyClimbMixAPI

pytestmark = pytest.mark.local_socket


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the backoff wait for every test in this module.

    Patches the module-level indirection rather than ``time.sleep`` so nothing
    else in the process (including the HTTP server thread) is affected.
    """
    import utils.http_retry

    monkeypatch.setattr(utils.http_retry, "_sleep", lambda _s: None)


def test_dense_client_recovers_from_a_429(monkeypatch):
    """Dense is the default engine, so a 429 here would sink most runs."""
    from utils.search_dense import search_dense

    with DummyClimbMixAPI("dense", fail_times=2) as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        hits = search_dense("congestion pricing", k=2)

    assert [h["docid"] for h in hits] == list(DOCIDS[:2])
    assert len(api.requests) == 3, "expected two rejections then a success"


def test_sparse_client_recovers_from_a_429(monkeypatch):
    """Sparse imports ``post_json`` from the dense module — same code path.

    Asserted separately anyway: the sharing is an implementation detail that a
    future refactor could undo without either client's own tests noticing.
    """
    from utils.search_sparse import search_sparse

    with DummyClimbMixAPI("sparse", fail_times=1) as api:
        monkeypatch.setenv("SPARSE_SEARCH_URL", api.base_url)
        hits = search_sparse("congestion pricing", k=2)

    assert [h["docid"] for h in hits] == list(DOCIDS[:2])
    assert len(api.requests) == 2


def test_ssr_client_recovers_from_a_429(monkeypatch):
    """The third consumer of ``post_json``; see the sparse test's rationale."""
    from utils.search_ssr import search_ssr

    with DummyClimbMixAPI("ssr", fail_times=1) as api:
        monkeypatch.setenv("SSR_SEARCH_URL", api.base_url)
        hits = search_ssr("(^ congestion pricing)", k=2)

    assert [h["rank"] for h in hits] == [1, 2]
    assert len(api.requests) == 2


def test_pyserini_client_recovers_from_a_429(monkeypatch):
    """The hosted Pyserini API is the one the pacing policy is written about."""
    from utils.search_pyserini import search_pyserini

    with DummyClimbMixAPI("pyserini", fail_times=2) as api:
        monkeypatch.setenv("PYSERINI_SEARCH_URL",
                           f"{api.base_url}/v1/climbmix-400b/search")
        hits = search_pyserini("congestion pricing", k=2)

    assert [h["docid"] for h in hits] == list(DOCIDS[:2])
    assert len(api.requests) == 3


def test_fetch_doc_recovers_from_a_429(monkeypatch):
    """Doc fetch is per-docid, so it hits the endpoint far more often than search.

    That volume makes it the most likely client to trip the rate limit, and the
    one whose failure would silently thin out a report's evidence.
    """
    from utils.fetch_doc import fetch_doc

    with DummyClimbMixAPI("pyserini", fail_times=2) as api:
        monkeypatch.setenv("PYSERINI_DOC_URL",
                           f"{api.base_url}/v1/climbmix-400b/doc")
        doc = fetch_doc(DOCIDS[0])

    assert doc == {"docid": DOCIDS[0], "text": TEXTS[0]}
    assert len(api.requests) == 3


def test_boolean_tool_recovers_from_a_429(monkeypatch):
    """The Boolean tool turns exceptions into ``{"error": ...}`` tool output.

    So without backoff a 429 would reach the agent as a search failure it would
    likely respond to by reformulating and searching again — more load on an
    endpoint that just asked for less.
    """
    import json

    from tools.search_boolean_tool import run_search_boolean_tool

    with DummyClimbMixAPI("ssr", fail_times=2) as api:
        out = json.loads(run_search_boolean_tool(
            "(^ congestion pricing)", k=2, url=api.base_url))

    assert "error" not in out, out
    assert [r["docid"] for r in out["results"]] == list(DOCIDS[:2])
    assert len(api.requests) == 3


def test_get_documents_recovers_from_a_429(monkeypatch):
    """``_fetch_one`` swallows every exception, so a 429 became a silent miss.

    That is worse than a visible failure: an id in ``missing`` reads to the agent
    as "this chunk does not exist" — indistinguishable from an out-of-range
    ``_p<page>`` — so it stops asking rather than retrying.
    """
    import json

    from agent_harness.tools.get_documents import execute_get_documents

    with DummyClimbMixAPI("dense", fail_times=2) as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        out_json, documents, missing = execute_get_documents(
            {"ids": [DOCIDS[0]]})

    assert missing == [], json.loads(out_json)
    assert [d["docid"] for d in documents] == [DOCIDS[0]]
    assert len(api.requests) == 3


def test_a_client_gives_up_after_the_retry_budget(monkeypatch):
    """A sustained outage must still fail, not retry forever.

    The bound is the other half of the policy: backing off is only safe if it
    terminates, otherwise a down endpoint hangs a batch job indefinitely.
    """
    import urllib.error

    from utils.http_retry import MAX_RETRIES
    from utils.search_dense import search_dense

    with DummyClimbMixAPI("dense", fail_times=99) as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            search_dense("q", k=1)

    assert excinfo.value.code == 429
    assert len(api.requests) == MAX_RETRIES + 1


def test_retry_after_header_is_read_from_a_real_response(monkeypatch):
    """A header set by a real HTTP server must reach ``parse_retry_after``.

    The unit tests build ``HTTPError`` by hand; this checks the header actually
    survives the ``urlopen`` → ``HTTPError.headers`` path, which is where a
    wrong attribute name would hide.
    """
    import utils.http_retry
    from utils.search_dense import search_dense

    waits: list[float] = []
    monkeypatch.setattr(utils.http_retry, "_sleep", waits.append)

    with DummyClimbMixAPI("dense", fail_times=1, retry_after="3") as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        hits = search_dense("q", k=1)

    assert hits
    assert waits == [3.0], "the server's stated wait should win over backoff"


def test_a_non_retryable_status_is_not_retried_over_the_wire(monkeypatch):
    """A real 401 must still fail on the first attempt.

    The counterpart to the recovery tests: routing through the wrapper must not
    have turned every error into four requests against a shared endpoint.
    """
    import urllib.error

    from utils.search_dense import search_dense

    with DummyClimbMixAPI("dense", require_auth=True) as api:
        monkeypatch.setenv("DENSE_SEARCH_URL", api.base_url)
        monkeypatch.delenv("SEARCH_API_KEY", raising=False)
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            search_dense("q", k=1)

    assert excinfo.value.code == 401
    assert len(api.requests) == 1
