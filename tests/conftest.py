"""Shared harness fixtures for the `src/` test suite.

Two invariants this file exists to enforce, because every other test depends
on them:

1. **Hermetic by default.** ``no_network`` is autouse: any test that reaches
   ``urllib``/``socket`` without opting in fails loudly with the URL it tried,
   instead of silently hitting a real endpoint (or hanging on a host without
   creds). Opt out per-test with the ``live`` marker.
2. **No artifacts outside tmp.** ``ragrun.save_run`` writes under
   ``data/outputs/<system>/``; the autouse ``isolated_data_dir`` repoints
   ``RAGRUN_DATA_DIR`` at a tmp dir so a test run never litters the real
   ``data/`` tree (or races the outputs viewer).

Fixture layers, cheapest first:

- ``fake_hits`` / ``fake_search_response`` — canonical ClimbMix search payloads
  in the exact shape the spec documents (see ``tests/contract``).
- ``stub_search_tool`` — monkeypatches ``tools.search_tool``'s engine dispatch
  and ``utils.search``'s dense/sparse clients, so single-engine and hybrid
  pipelines exercise REAL retrieval plumbing against fake transport.
- ``ScriptedProvider`` — the ``aus_agent.providers.base.Provider`` contract,
  driven by a queued list of turns; the single mock every system's LLM stage
  is exercised through.
"""
from __future__ import annotations

import itertools
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

# The pytest `pythonpath` ini option already puts src/ and src/systems/ on the
# path. Assert it rather than re-do it, so a broken config fails here (once)
# rather than as a confusing ImportError in every test module.
_REPO_ROOT = Path(__file__).resolve().parents[1]
assert str(_REPO_ROOT / "src") in sys.path, (
    "src/ not on sys.path — check [tool.pytest.ini_options] pythonpath")


# ---------------------------------------------------------------------------
# Hermeticism
# ---------------------------------------------------------------------------
class NetworkAccessError(RuntimeError):
    """Raised when an offline test tries to open a socket."""


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest,
               monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any non-``live`` test that attempts real network I/O.

    Patched at two levels because the retrieval clients use ``urllib`` while a
    model SDK would use ``socket`` directly: ``urlopen`` gives a readable error
    naming the URL, ``socket.create_connection`` is the backstop.
    """
    if request.node.get_closest_marker("live"):
        return

    def _blocked_urlopen(req: Any, *a: Any, **kw: Any) -> None:
        url = getattr(req, "full_url", req)
        raise NetworkAccessError(
            f"offline test attempted a network call to {url!r}. "
            "Stub the backend (see `stub_search_tool`) or mark the test "
            "`@pytest.mark.live`.")

    def _blocked_connect(address: Any, *a: Any, **kw: Any) -> None:
        raise NetworkAccessError(
            f"offline test attempted a socket connection to {address!r}. "
            "Stub it, or mark the test `@pytest.mark.live`.")

    monkeypatch.setattr(urllib.request, "urlopen", _blocked_urlopen)
    monkeypatch.setattr(socket, "create_connection", _blocked_connect)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory: pytest.TempPathFactory,
                      monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``ragrun.data_dir()`` at a per-test tmp dir.

    ``ragrun.outputs.data_dir`` reads ``RAGRUN_DATA_DIR`` on every call, so
    setting the env var is enough — no need to patch the function.
    """
    root = tmp_path_factory.mktemp("ragrun-data")
    monkeypatch.setenv("RAGRUN_DATA_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def no_ambient_creds(monkeypatch: pytest.MonkeyPatch,
                     request: pytest.FixtureRequest) -> None:
    """Strip credential env vars for offline tests.

    A developer's real ``.env`` is auto-loaded by ``utils.env`` at import time.
    Clearing the keys keeps an offline test's behaviour identical on a machine
    with creds and one without — otherwise a "hermetic" test can pass locally
    only because it silently authenticated somewhere.
    """
    if request.node.get_closest_marker("live"):
        return
    for var in ("SEARCH_API_KEY", "PYSERINI_API_TOKEN", "OPENAI_API_KEY",
                "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Canonical ClimbMix payloads
# ---------------------------------------------------------------------------
# Docids follow the real corpus convention `shard_<5 digits>_<row>`; chunk ids
# add the `_p<page>` suffix (see utils.search_types.classify_id).
CLIMBMIX_DOCIDS = (
    "shard_00459_61697",
    "shard_01012_88420",
    "shard_00210_44018",
    "shard_00044_91812",
)

_PASSAGE_TEXTS = (
    "Congestion pricing dedicates toll revenue to the MTA capital plan, and "
    "early reporting showed traffic volumes below the pre-toll baseline.",
    "Analyses of who pays note that most peak-period drivers into the zone "
    "have higher household incomes than the average transit rider.",
    "Air-quality monitoring in the Bronx was written into the environmental "
    "assessment because of concerns about rerouted truck traffic.",
    "State oversight provisions require the authority to report capital "
    "spending against the plan it published before tolling began.",
)


@pytest.fixture
def fake_hits() -> Callable[..., list[dict[str, Any]]]:
    """Build a list of ``utils.search_types.SearchHit`` dicts.

    Uses the real ``make_hit`` so ``kind``/``docid`` derivation is the code
    under test, not a copy of it — a chunk id passed here classifies exactly
    as it would in production.
    """
    from utils.search_types import make_hit

    def _build(k: int = 3, *, source: str = "dense",
               ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        unit_ids = ids or CLIMBMIX_DOCIDS
        if k > len(unit_ids):
            raise ValueError(f"fake_hits: k={k} exceeds {len(unit_ids)} ids")
        return [
            make_hit(unit_ids[i],
                     score=round(12.5 - i, 4),
                     rank=i + 1,
                     text=_PASSAGE_TEXTS[i % len(_PASSAGE_TEXTS)],
                     meta={"source": source})
            for i in range(k)
        ]

    return _build


@pytest.fixture
def fake_search_response() -> Callable[..., dict[str, Any]]:
    """A Pyserini-REST search response, exactly as the spec documents it.

    Shape per `skills/trec-rag-2026-track-guidelines/references/retrieval-task.md`:
    ``{api, index, query: {text}, candidates: [{docid, rank, score, doc}]}``.
    """
    def _build(query: str = "congestion pricing MTA funding",
               k: int = 3, *, doc_as_object: bool = False) -> dict[str, Any]:
        candidates = []
        for i in range(k):
            text = _PASSAGE_TEXTS[i % len(_PASSAGE_TEXTS)]
            candidates.append({
                "docid": CLIMBMIX_DOCIDS[i % len(CLIMBMIX_DOCIDS)],
                "rank": i + 1,
                "score": round(12.5 - i, 4),
                "doc": {"text": text} if doc_as_object else text,
            })
        return {"api": "v1", "index": "climbmix-400b",
                "query": {"text": query}, "candidates": candidates}

    return _build


@pytest.fixture
def stub_search_tool(monkeypatch: pytest.MonkeyPatch,
                     fake_hits: Callable[..., list[dict[str, Any]]]
                     ) -> dict[str, list[dict[str, Any]]]:
    """Replace tool dispatch and the hybrid layer's two clients with fakes.

    Patching the dispatch table (not ``run_search_tool``) keeps the real
    serialization, truncation, and error-envelope logic under test while
    removing the transport. Patching the aliases held by ``utils.search`` does
    the same for its real concurrency and RRF fusion path. Returns a ``calls``
    dict recording what each engine was asked for, so a test can assert routing:

        assert calls["semantic"][0]["query"] == "..."

    Every query returns the same ``CLIMBMIX_DOCIDS``, which most tests want
    (stable ids to assert against). A test that needs *different* docids per
    query — cross-query de-duplication, disjoint staged batches — wants
    ``tests/aus_agent_context/conftest.py::fake_engine`` instead, which maps
    queries to three disjoint doc sets.
    """
    from tools import search_tool
    from utils import search as hybrid_search

    calls: dict[str, list[dict[str, Any]]] = {}

    def _make(engine: str) -> Callable[..., list[dict[str, Any]]]:
        def _fake(query: str, k: int = 10, **kw: Any) -> list[dict[str, Any]]:
            calls.setdefault(engine, []).append(
                {"query": query, "k": k, **kw})
            return fake_hits(min(k, len(CLIMBMIX_DOCIDS)), source=engine)
        return _fake

    patched = {engine: _make(engine) for engine in search_tool._DISPATCH}
    monkeypatch.setattr(search_tool, "_DISPATCH", patched)
    monkeypatch.setattr(hybrid_search, "search_dense", patched["semantic"])
    monkeypatch.setattr(hybrid_search, "search_sparse", patched["keyword"])
    return calls


# ---------------------------------------------------------------------------
# Scripted Provider (the aus_agent Provider contract)
# ---------------------------------------------------------------------------
def model_turn(*, text: str | None = None,
               reasoning: list[str] | None = None,
               tool_calls: list[dict[str, Any]] | None = None,
               stop_reason: str = "end_turn",
               usage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one normalized ``ModelTurn`` (see providers/base.py docstring).

    ``blocks`` is assembled in content order — reasoning, then tool calls, then
    text — with the convenience views derived from it, so a scripted turn is
    structurally identical to a real provider's output.
    """
    blocks: list[dict[str, Any]] = []
    for r in reasoning or []:
        blocks.append({"type": "reasoning", "text": r})
    for call in tool_calls or []:
        blocks.append({"type": "tool_call", "call": call})
    if text:
        blocks.append({"type": "text", "text": text})
    return {
        "blocks": blocks,
        "reasoning_blocks": list(reasoning or []),
        "tool_calls": list(tool_calls or []),
        "text": text,
        "stop_reason": ("tool_use" if tool_calls else stop_reason),
        "usage": usage or {"inputTokens": 100, "outputTokens": 50,
                           "cacheReadInputTokens": 0,
                           "cacheWriteInputTokens": 0},
        "raw": {"scripted": True},
    }


_CALL_SEQ = itertools.count(1)


def tool_call(name: str, arguments: dict[str, Any], *,
              id: str | None = None) -> dict[str, Any]:
    """Build one normalized ``tool_call`` event.

    The default id carries a process-wide sequence number because a tool-call
    id is a *key*: ``add_tool_results``/``compact_tool_results`` look results up
    by it and ``StrictScriptedProvider.content_by_id`` is a dict keyed on it, so
    two calls sharing an id silently collapse into one instead of failing. Pass
    ``id=`` explicitly whenever a test asserts on the id.
    """
    return {"id": id or f"call_{name}_{next(_CALL_SEQ)}",
            "name": name, "arguments": dict(arguments)}


class ScriptedProvider:
    """A ``Provider`` that replays queued turns — the shared LLM mock.

    Implements the full contract from ``aus_agent.providers.base.Provider`` so
    it is substitutable anywhere a real backend is: turns are consumed in
    order, and the conversation (system prompt, tool defs, user messages, tool
    results) is recorded for assertions.

    Two scripting modes:

    - a list of ``ModelTurn`` dicts, replayed in order;
    - a callable ``responder(pending_text, turn_index) -> ModelTurn``, for
      stage-dependent behaviour (e.g. facet_rag's plan/synthesize/format
      turns, which are distinguished by their prompt).
    """

    model_id = "scripted/test-model"

    def __init__(self, turns: list[dict[str, Any]] |
                 Callable[[str, int], dict[str, Any]]) -> None:
        self._script = turns
        self._queue = list(turns) if isinstance(turns, list) else None
        self.turn_index = 0
        # Recorded conversation, for assertions.
        self.system_prompt: str | None = None
        self.tools: list[dict[str, Any]] = []
        self.user_messages: list[str] = []
        self.tool_results: list[list[dict[str, Any]]] = []
        self.compactions: list[dict[str, str]] = []
        self._history: list[Any] = []

    # -- Provider contract --------------------------------------------------
    def start(self, system_prompt: str, tools: list[dict[str, Any]]) -> None:
        self.system_prompt = system_prompt
        self.tools = list(tools)
        self._history = [{"role": "system", "content": system_prompt}]

    def add_user_message(self, text: str) -> None:
        self.user_messages.append(text)
        self._history.append({"role": "user", "content": text})

    def run_turn(self) -> dict[str, Any]:
        pending = self.user_messages[-1] if self.user_messages else ""
        if self._queue is not None:
            if not self._queue:
                raise AssertionError(
                    f"ScriptedProvider exhausted after {self.turn_index} turns "
                    "— the system under test ran more turns than scripted.")
            turn = self._queue.pop(0)
        else:
            turn = self._script(pending, self.turn_index)  # type: ignore[misc]
        self.turn_index += 1
        self._history.append({"role": "assistant",
                              "content": turn.get("text") or "",
                              "tool_calls": turn.get("tool_calls") or []})
        return turn

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        self.tool_results.append([dict(r) for r in results])
        for r in results:
            self._history.append({"role": "tool", "tool_call_id": r["id"],
                                  "content": r["content"],
                                  "is_error": r.get("is_error", False)})

    def compact_tool_results(self, replacements: dict[str, str]) -> None:
        """Rewrite earlier tool results, raising on an id that isn't in history.

        The raise matches `BedrockProvider.compact_tool_results`
        (`providers/bedrock.py:237`), which is the behaviour a test should be
        able to rely on: silently dropping an unknown id would let a caller that
        compacts the wrong batch pass here and fail against the real provider.
        """
        self.compactions.append(dict(replacements))
        remaining = dict(replacements)
        for message in self._history:
            if isinstance(message, dict) and message.get("role") == "tool":
                new = remaining.pop(message.get("tool_call_id", ""), None)
                if new is not None:
                    message["content"] = new
        if remaining:
            missing = ", ".join(sorted(remaining))
            raise KeyError(f"tool results not found for compaction: {missing}")

    @property
    def raw_messages(self) -> list[Any]:
        return self._history

    # -- test helpers -------------------------------------------------------
    @property
    def remaining(self) -> int:
        """Unconsumed scripted turns (``-1`` for a responder callable)."""
        return len(self._queue) if self._queue is not None else -1


@pytest.fixture
def scripted_provider() -> type[ScriptedProvider]:
    """The ``ScriptedProvider`` class (tests construct it with their script)."""
    return ScriptedProvider


@pytest.fixture
def read_artifacts() -> Callable[[dict[str, Path]], dict[str, Any]]:
    """Load the JSON artifacts a ``save_run`` call wrote, by path dict.

    Returns ``{"trajectory": ..., "output": ..., "violations": [...]}`` with
    ``violations`` defaulting to ``[]`` when no violations file exists — so a
    test asserts ``artifacts["violations"] == []`` rather than probing for the
    file's absence.
    """
    def _read(paths: dict[str, Path]) -> dict[str, Any]:
        loaded: dict[str, Any] = {"violations": []}
        for key in ("trajectory", "output", "violations"):
            path = paths.get(key)
            if path is not None and Path(path).exists():
                loaded[key] = json.loads(Path(path).read_text())
        return loaded

    return _read
