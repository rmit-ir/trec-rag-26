"""Enrich uvicorn's opaque "Invalid HTTP request received." warning.

By default uvicorn logs a bare one-liner when the HTTP parser rejects the bytes
on a connection, with no client address and no payload — useless for telling a
buggy client apart from a port scanner or a browser that spoke TLS to a
plaintext port. This module monkeypatches the httptools protocol so each
invalid request logs the peer address and a safe repr of the raw bytes, and
labels the two most common causes (TLS handshake / proxy CONNECT).

Idempotent + defensive: if uvicorn's internals move, it logs a note and leaves
the server untouched. Installed once per worker from server.py at import time,
so it covers both the direct-uvicorn and gunicorn-UvicornWorker launches.
"""
from __future__ import annotations

import logging

_LOG = logging.getLogger("uvicorn.error")
_INSTALLED = False
_MAX_DUMP = 256  # bytes of the failing payload to log


def _peername(transport) -> str:
    try:
        info = transport.get_extra_info("peername")
    except Exception:
        info = None
    if isinstance(info, tuple) and len(info) >= 2:
        return f"{info[0]}:{info[1]}"
    return str(info)


def _classify(data: bytes) -> str:
    """Best-effort label for why the parser choked — turns anonymous noise
    into an actionable cause."""
    if not data:
        return "empty payload"
    # TLS record: content-type 0x16 (handshake) + version 0x03 0x0X. This is a
    # browser/client that hit http://... expecting https, or an HTTPS scanner.
    if data[0] == 0x16 and len(data) >= 3 and data[1] == 0x03:
        return "looks like a TLS/HTTPS handshake to a plaintext HTTP port"
    if data[:8].upper() == b"CONNECT ":
        return "HTTP CONNECT (proxy tunnel attempt)"
    # Printable ASCII but not a known method -> probably a scanner/garbage line.
    first = data.split(b"\r\n", 1)[0][:64]
    try:
        first.decode("ascii")
        return "unrecognized request line (probe/garbage)"
    except UnicodeDecodeError:
        return "non-HTTP binary payload (scanner/garbage)"


def _log_invalid(transport, data: bytes) -> None:
    try:
        peer = _peername(transport)
        why = _classify(data or b"")
        dump = bytes(data or b"")[:_MAX_DUMP]
        _LOG.warning(
            "Invalid HTTP request from %s: %s | %d bytes, first %d: %r",
            peer, why, len(data or b""), len(dump), dump,
        )
    except Exception as exc:  # never let logging break the connection teardown
        _LOG.warning("Invalid HTTP request (failed to introspect: %r)", exc)


def install() -> None:
    """Patch httptools protocol to log peer + payload on invalid requests."""
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
    except Exception as exc:
        _LOG.info("[request_logging] httptools protocol unavailable (%r); "
                  "invalid-request enrichment disabled", exc)
        return

    if not (hasattr(HttpToolsProtocol, "data_received")
            and hasattr(HttpToolsProtocol, "send_400_response")):
        _LOG.info("[request_logging] uvicorn internals moved; "
                  "invalid-request enrichment disabled")
        return

    _orig_data_received = HttpToolsProtocol.data_received
    _orig_send_400 = HttpToolsProtocol.send_400_response

    def data_received(self, data):  # noqa: ANN001
        # Stash the most recent chunk so send_400_response (the unique
        # invalid-request signal) can report exactly what failed to parse.
        self._last_recv_data = data
        return _orig_data_received(self, data)

    def send_400_response(self, msg):  # noqa: ANN001
        _log_invalid(getattr(self, "transport", None),
                     getattr(self, "_last_recv_data", b""))
        return _orig_send_400(self, msg)

    HttpToolsProtocol.data_received = data_received
    HttpToolsProtocol.send_400_response = send_400_response
    _INSTALLED = True
    _LOG.info("[request_logging] invalid-request enrichment installed "
              "(logs client + payload on malformed HTTP)")
