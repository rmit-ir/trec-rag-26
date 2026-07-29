"""Let the dummy-API tests use real loopback sockets while staying offline.

The root ``no_network`` fixture is autouse and blocks ``urlopen`` /
``socket.create_connection`` for every test that is not marked ``live``. These
tests deliberately make real HTTP calls — to a dummy server on 127.0.0.1 — so
they need an exemption, but they must NOT be marked ``live``: that marker means
"talks to the hosted ClimbMix/model services and needs credentials", and these
run in CI with neither.

Hence a third category, ``local_socket``: real sockets, loopback only, no creds,
runs by default. This conftest overrides ``no_network`` for this package so the
marked tests are exempt, and the override still blocks anything that is not
loopback — so a client with a hardcoded hosted URL fails here rather than
quietly reaching the internet from CI.
"""
from __future__ import annotations

import socket
import urllib.parse
import urllib.request
from typing import Any

import pytest


def _is_loopback(host: str | None) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest,
               monkeypatch: pytest.MonkeyPatch) -> None:
    """Loopback-only network access for ``local_socket`` tests.

    Shadows the root fixture of the same name (pytest resolves fixtures from
    the closest conftest), so tests in this package get this policy instead of
    the blanket block.
    """
    if request.node.get_closest_marker("live"):
        return

    # A test here that is not marked local_socket gets the strict root policy.
    if not request.node.get_closest_marker("local_socket"):
        request.getfixturevalue("_strict_no_network")
        return

    real_urlopen = urllib.request.urlopen
    real_connect = socket.create_connection

    def _guarded_urlopen(req: Any, *a: Any, **kw: Any) -> Any:
        url = getattr(req, "full_url", req)
        host = urllib.parse.urlparse(str(url)).hostname
        if not _is_loopback(host):
            raise RuntimeError(
                f"local_socket test attempted a NON-loopback call to {url!r}. "
                "Point the client at the dummy server's base_url, or mark the "
                "test `live` if it genuinely needs the hosted service.")
        return real_urlopen(req, *a, **kw)

    def _guarded_connect(address: Any, *a: Any, **kw: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise RuntimeError(
                f"local_socket test attempted a NON-loopback connection to "
                f"{address!r}.")
        return real_connect(address, *a, **kw)

    monkeypatch.setattr(urllib.request, "urlopen", _guarded_urlopen)
    monkeypatch.setattr(socket, "create_connection", _guarded_connect)


@pytest.fixture
def _strict_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The root policy, for unmarked tests in this package."""
    def _blocked(target: Any, *a: Any, **kw: Any) -> None:
        raise RuntimeError(
            f"offline test attempted a network call to {target!r}. Mark it "
            "`local_socket` to use the dummy API server.")

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
