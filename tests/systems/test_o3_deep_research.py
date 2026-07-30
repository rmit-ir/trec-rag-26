"""End-to-end + unit coverage for ``src/systems/o3_deep_research``.

This system is unlike the other four: **we do not run the agent loop.** OpenAI's
hosted deep-research agent plans and executes its own research server-side, and
`run.py`'s entire job is to (a) hand it an MCP tool block pointing at our corpus
and (b) faithfully reconstruct a trajectory from the *stream of Responses events*
it gets back. So almost everything worth testing is translation: Responses items
-> trajectory steps, usage -> token stats, MCP tool output -> docids.

That makes the fake here a fake **SDK**, not a fake model. There is no
``ScriptedProvider`` equivalent — the class below yields the same event sequence
(``response.created`` -> ``output_item.added``/``done`` per item ->
``response.completed``) the real SDK does, with attribute bags standing in for
Responses items. Nothing about the agent's *behaviour* is asserted; what is
asserted is that a given item stream produces the right artifacts.

Two properties get disproportionate attention because they are what a paid,
hour-long run depends on and what no unit test of a pure function would catch:

- **The stream is the source of timing** (``timing_resolution: stream-events``).
  ``responses.retrieve`` on an in-flight background DR+MCP run 500s reliably
  (OpenAI-side, observed 2026-07-19), which is why this system streams at all
  and why the reconnect path — ``retrieve(stream=True, starting_after=cursor)``
  — is load-bearing rather than defensive. A regression there does not fail
  loudly; it silently re-bills a whole research run.
- **`fetch` docids come from the call's *arguments*, not its output.** The fetch
  result is document text with no id in it, so the only record of *what* was
  fetched is what was asked for. That asymmetry with ``search`` is easy to
  "tidy up" into a bug.

No ``importorskip``: ``openai``/``boto3``/``mcp``/``dotenv`` all install under
the dep groups ``scripts/test.sh`` already passes, and none of them is reached
anyway — the client is injected.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import pytest
from conftest import CLIMBMIX_DOCIDS

from ragrun import validate_rag_output

RUN_PY = Path(__file__).resolve().parents[2] / "src" / "systems" \
    / "o3_deep_research" / "run.py"

QID = "mock_dr_001"
QUERY = "How is congestion pricing revenue in New York being spent?"
ANSWER = ("Revenue is dedicated to the capital plan. Traffic volumes fell "
          "below the pre-toll baseline.")


# ---------------------------------------------------------------------------
# The module under test (loaded by path — a bare `run.py` name would collide)
# ---------------------------------------------------------------------------
@pytest.fixture
def dr(load_module: Callable[[Path, str], Any]) -> Any:
    """``o3_deep_research/run.py`` as a module, with ``time.sleep`` neutered.

    Both retry paths in this module (``_retrieve``, ``FormatLLM.complete``) and
    the stream-reconnect loop sleep for up to two minutes between attempts. The
    patch is on the module object, so it is undone with the fixture rather than
    leaking into the rest of the session.
    """
    module = load_module(RUN_PY, "o3dr_run")
    return module


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every backoff in this module instantaneous.

    Autouse because a test that forgets it does not fail — it hangs for minutes,
    which is far worse than a red test.
    """
    monkeypatch.setattr(time, "sleep", lambda *_a, **_kw: None)


# ---------------------------------------------------------------------------
# Fake Responses SDK
# ---------------------------------------------------------------------------
def item(typ: str, **fields: Any) -> SimpleNamespace:
    """One Responses output item as an attribute bag.

    ``add_item_step`` reads every field with ``getattr(..., default)``, so a bag
    is a faithful stand-in — and an *unfaithful* one would be caught, since a
    missing attribute takes the default rather than raising.
    """
    return SimpleNamespace(type=typ, **fields)


def search_item(name: str = "search", *, ids: tuple[str, ...] = CLIMBMIX_DOCIDS[:2],
                query: str = "congestion pricing revenue") -> SimpleNamespace:
    """An ``mcp_call`` item for ``search``, output shaped like our MCP server's."""
    payload = json.dumps({
        "query": query,
        "results": [{"id": d, "docid": d, "text": f"passage from {d}"}
                    for d in ids],
    })
    return item("mcp_call", name=name, arguments=json.dumps({"query": query}),
                output=payload, error=None)


def fetch_item(docid: str = CLIMBMIX_DOCIDS[0]) -> SimpleNamespace:
    """An ``mcp_call`` item for ``fetch`` — note the id is only in *arguments*."""
    return item("mcp_call", name="fetch", arguments=json.dumps({"id": docid}),
                output=f"Full text of {docid}.", error=None)


def message_item(text: str = ANSWER) -> SimpleNamespace:
    return item("message", content=[SimpleNamespace(type="output_text", text=text)])


def usage(input_tokens: int = 12_000, output_tokens: int = 3_000, *,
          cached: int = 4_000, total: int | None = None) -> SimpleNamespace:
    details = SimpleNamespace(cached_tokens=cached)
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           total_tokens=total, input_tokens_details=details)


def response(items: list[SimpleNamespace], *, status: str = "completed",
             rid: str = "resp_abc", usage_obj: Any = None) -> SimpleNamespace:
    return SimpleNamespace(id=rid, status=status, output=items, usage=usage_obj)


DEFAULT_ITEMS = [
    item("mcp_list_tools", tools=[{"name": "search"}, {"name": "fetch"}]),
    item("reasoning", summary=[SimpleNamespace(text="Plan the searches."),
                               SimpleNamespace(text="Then read the best hits.")]),
    search_item(),
    fetch_item(),
    message_item(),
]


class FakeResponses:
    """``client.responses`` — records every call, replays scripted events.

    ``create`` returns an iterator of events (the SDK's streaming shape).
    ``event_script`` is a callable so a test can raise mid-iteration to
    simulate a dropped connection; ``retrieve`` serves both the resume path
    (non-stream) and the reconnect path (``stream=True``).
    """

    def __init__(self, items: list[SimpleNamespace] | None = None, *,
                 status: str = "completed", usage_obj: Any = None,
                 event_script: Callable[[], Iterator[Any]] | None = None,
                 retrieve_statuses: list[str] | None = None,
                 reconnect_script: Callable[[], Iterator[Any]] | None = None,
                 retrieve_failures: int = 0) -> None:
        self.items = DEFAULT_ITEMS if items is None else items
        self.status = status
        self.usage_obj = usage_obj
        self.created: list[dict[str, Any]] = []
        self.retrieved: list[tuple[str, dict[str, Any]]] = []
        self._event_script = event_script
        self._reconnect_script = reconnect_script
        self._retrieve_statuses = list(retrieve_statuses or [])
        self._retrieve_failures = retrieve_failures

    # -- streaming create ---------------------------------------------------
    def create(self, **kwargs: Any) -> Iterator[Any]:
        self.created.append(kwargs)
        if self._event_script is not None:
            return self._event_script()
        return self._default_events()

    def _default_events(self) -> Iterator[Any]:
        yield SimpleNamespace(type="response.created", sequence_number=1,
                              response=SimpleNamespace(id="resp_abc",
                                                       status="queued"))
        seq = 2
        for index, it in enumerate(self.items):
            yield SimpleNamespace(type="response.output_item.added",
                                  sequence_number=seq, output_index=index)
            seq += 1
            yield SimpleNamespace(type="response.output_item.done",
                                  sequence_number=seq, output_index=index,
                                  item=it)
            seq += 1
        terminal = ("response.completed" if self.status == "completed"
                    else f"response.{self.status}")
        yield SimpleNamespace(
            type=terminal, sequence_number=seq,
            response=response(self.items, status=self.status,
                              usage_obj=self.usage_obj))

    # -- retrieve (resume + reconnect) --------------------------------------
    def retrieve(self, response_id: str, **kwargs: Any) -> Any:
        self.retrieved.append((response_id, kwargs))
        if self._retrieve_failures > 0:
            self._retrieve_failures -= 1
            raise RuntimeError("simulated 500 from responses.retrieve")
        if kwargs.get("stream"):
            assert self._reconnect_script is not None, "unexpected re-stream"
            return self._reconnect_script()
        status = (self._retrieve_statuses.pop(0) if self._retrieve_statuses
                  else self.status)
        items = self.items if status == "completed" else []
        return response(items, status=status, rid=response_id,
                        usage_obj=self.usage_obj if status == "completed" else None)


class FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.responses = FakeResponses(**kwargs)


def cli_args(**overrides: Any) -> SimpleNamespace:
    """A parsed ``argparse.Namespace`` with every flag ``run_one`` reads.

    Spelled out rather than built from ``main()``'s parser so a *new* flag with a
    default that changes ``run_one``'s behaviour shows up as an AttributeError
    here instead of being silently exercised at its default.
    """
    args = {
        "mcp_url": "https://tunnel.example/mcp",
        "mcp_token": None,
        "model": "o3-deep-research",
        "max_tool_calls": None,
        "poll_interval": 0.0,
        "no_reasoning_summary": False,
        "no_background": False,
        "resume": None,
        "run_id": "o3-deep-research.test",
        "run_desc": "hermetic end-to-end test",
    }
    args.update(overrides)
    return SimpleNamespace(**args)


def run(dr: Any, client: Any, **overrides: Any) -> dict[str, Path]:
    return dr.run_one(client, qid=QID, query=QUERY, args=cli_args(**overrides),
                      format_llm=None)


# ---------------------------------------------------------------------------
# _docids_from_mcp_output
# ---------------------------------------------------------------------------
def test_search_output_yields_result_ids_in_rank_order(dr: Any) -> None:
    """Order matters downstream: it becomes the reference list's order.

    ``run_one`` feeds these straight into ``format_answer``'s candidate list,
    which assigns citations round-robin in the order given — so a sort or a set
    here would silently reorder every reference list we submit.
    """
    ids = dr._docids_from_mcp_output(
        "search", "", search_item(ids=CLIMBMIX_DOCIDS[:3]).output)

    assert ids == list(CLIMBMIX_DOCIDS[:3])


def test_a_double_encoded_search_payload_is_decoded_twice(dr: Any) -> None:
    """The MCP server has been observed returning JSON-encoded JSON.

    A single ``json.loads`` yields a ``str``, whose ``.get`` would raise
    ``AttributeError`` — not one of the caught exceptions — and take the whole
    paid run down at artifact-assembly time. The retry-on-str branch is the
    guard, and it is invisible unless a test sends the doubled shape.
    """
    doubled = json.dumps(json.dumps(
        {"results": [{"id": CLIMBMIX_DOCIDS[0]}]}))

    assert dr._docids_from_mcp_output("search", "", doubled) == \
        [CLIMBMIX_DOCIDS[0]]


@pytest.mark.parametrize("output", ["not json at all", "", "[1, 2, 3]",
                                    '{"results": "a string"}'])
def test_unparseable_search_output_degrades_to_no_docids(dr: Any,
                                                         output: str) -> None:
    """A malformed tool result must cost docids, never the run.

    Everything here is an OpenAI-side or MCP-side shape we do not control, and
    the artifacts are assembled *after* the expensive part is already paid for.
    Losing one call's docids is recoverable; raising is not.
    """
    assert dr._docids_from_mcp_output("search", "", output) == []


def test_results_without_an_id_are_skipped_not_defaulted(dr: Any) -> None:
    """A result missing ``id`` yields nothing rather than ``None`` or ``""``.

    A falsy entry would flow into ``references`` and produce a citation to an
    empty docid, which validates as a string and would reach a submission.
    """
    payload = json.dumps({"results": [{"id": CLIMBMIX_DOCIDS[0]}, {"text": "x"},
                                      {"id": ""}]})

    assert dr._docids_from_mcp_output("search", "", payload) == \
        [CLIMBMIX_DOCIDS[0]]


def test_fetch_docid_comes_from_the_arguments_not_the_output(dr: Any) -> None:
    """The asymmetry with ``search``, and the reason it exists.

    A fetch result is the document's *text* — it contains no id — so the request
    is the only record of what was read. Unifying the two branches to read the
    output (the obvious simplification) would silently empty
    ``state["fetched"]``, and fetched docids are the ones deliberately placed
    FIRST in the candidate list because the agent actually read them.
    """
    fetched = fetch_item(CLIMBMIX_DOCIDS[1])

    assert dr._docids_from_mcp_output("fetch", fetched.arguments,
                                      fetched.output) == [CLIMBMIX_DOCIDS[1]]
    # ...and the output alone yields nothing, which is the whole point.
    assert dr._docids_from_mcp_output("fetch", "{}", fetched.output) == []


def test_an_unknown_tool_name_yields_no_docids(dr: Any) -> None:
    """Only ``search``/``fetch`` are understood; anything else is not guessed.

    The MCP server may gain tools (a reranker, a doc-count probe) whose output
    is not a hit list. Falling through to `[]` keeps a new tool from injecting
    junk ids into the reference list before anyone has taught this function
    about it.
    """
    assert dr._docids_from_mcp_output("rerank", "{}", '{"results":[{"id":"a"}]}') \
        == []


# ---------------------------------------------------------------------------
# add_item_step
# ---------------------------------------------------------------------------
def _builder(dr: Any) -> tuple[Any, dict[str, Any]]:
    tb = dr.TrajectoryBuilder(QID, QUERY, metadata={})
    state: dict[str, Any] = {"answer": None, "fetched": [], "searched": []}
    return tb, state


def test_reasoning_summary_parts_are_joined_into_one_step(dr: Any) -> None:
    """Multi-part reasoning summaries become ONE trajectory item, blank-line joined.

    The Responses API splits a summary into parts; emitting one step per part
    would inflate the step count that a reviewer reads as "how many times did it
    think", and the blank line is what keeps the parts readable once merged.
    """
    tb, state = _builder(dr)

    dr.add_item_step(tb, DEFAULT_ITEMS[1], turn=0, t_start="t0", t_end="t1",
                     state=state)

    assert [i["type"] for i in tb.result] == ["reasoning"]
    assert tb.result[0]["output"] == "Plan the searches.\n\nThen read the best hits."


@pytest.mark.parametrize("summary", [None, [], [SimpleNamespace(text="")],
                                     [SimpleNamespace(other="x")]])
def test_an_empty_reasoning_summary_adds_no_step(dr: Any, summary: Any) -> None:
    """``reasoning.summary=auto`` is best-effort — an empty one is normal.

    Recording an empty reasoning item would put a content-free step in the
    trajectory for every model turn that happened not to summarize, which is
    noise in the artifact reviewers read.
    """
    tb, state = _builder(dr)

    dr.add_item_step(tb, item("reasoning", summary=summary), turn=0,
                     t_start="t0", t_end="t1", state=state)

    assert tb.result == []


def test_a_failed_mcp_call_records_the_error_as_its_output(dr: Any) -> None:
    """On error the *error* is stored, and the step is marked failed.

    The tool's partial output is deliberately discarded: for MCP failures it is
    empty or truncated, and keeping it would put a plausible-looking but
    incomplete passage in the trajectory where the failure reason belongs.
    """
    tb, state = _builder(dr)
    failed = item("mcp_call", name="search", arguments='{"query": "x"}',
                  output="partial junk", error="upstream 502")

    dr.add_item_step(tb, failed, turn=0, t_start="t0", t_end="t1", state=state)

    assert tb.result[0]["output"] == "upstream 502"
    assert tb.trace_steps[0]["failed"] is True


def test_mcp_list_tools_accepts_dict_and_object_entries(dr: Any) -> None:
    """The SDK returns either shape depending on version; both must map.

    A version bump that switches dicts to model objects would otherwise turn
    every tool name into ``None`` — and since this only affects a descriptive
    step, nothing else would complain.
    """
    tb, state = _builder(dr)
    mixed = item("mcp_list_tools",
                 tools=[{"name": "search"}, SimpleNamespace(name="fetch")])

    dr.add_item_step(tb, mixed, turn=0, t_start="t0", t_end="t1", state=state)

    assert json.loads(tb.result[0]["output"]) == ["search", "fetch"]
    assert tb.result[0]["tool_name"] == "mcp_list_tools"


def test_search_and_fetch_docids_land_in_separate_state_buckets(dr: Any) -> None:
    """The split exists so ``run_one`` can rank *read* documents above *seen* ones.

    Merging the buckets would lose that ordering, and it is the only signal we
    have about which documents the agent actually opened.
    """
    tb, state = _builder(dr)

    dr.add_item_step(tb, search_item(ids=CLIMBMIX_DOCIDS[:2]), turn=0,
                     t_start="t0", t_end="t1", state=state)
    dr.add_item_step(tb, fetch_item(CLIMBMIX_DOCIDS[1]), turn=1,
                     t_start="t2", t_end="t3", state=state)

    assert state["searched"] == list(CLIMBMIX_DOCIDS[:2])
    assert state["fetched"] == [CLIMBMIX_DOCIDS[1]]


def test_only_output_text_content_becomes_the_answer(dr: Any) -> None:
    """Non-``output_text`` content parts are skipped, not concatenated.

    A message can carry refusals and annotations alongside the prose. Splicing
    those into the answer would put SDK metadata into a submitted sentence.
    """
    tb, state = _builder(dr)
    mixed = item("message", content=[
        SimpleNamespace(type="refusal", text="I cannot."),
        SimpleNamespace(type="output_text", text="Real answer."),
    ])

    dr.add_item_step(tb, mixed, turn=0, t_start="t0", t_end="t1", state=state)

    assert state["answer"] == "Real answer."


def test_an_unrecognised_item_type_is_ignored(dr: Any) -> None:
    """Unknown item types must not raise — the API adds them without notice.

    ``web_search_call``, ``code_interpreter_call``, and friends can appear in a
    DR response. This runs after the expensive part is paid for, so an
    unhandled type must cost a step, not the run.
    """
    tb, state = _builder(dr)

    dr.add_item_step(tb, item("code_interpreter_call", code="print(1)"), turn=0,
                     t_start="t0", t_end="t1", state=state)

    assert tb.result == []
    assert state["answer"] is None


# ---------------------------------------------------------------------------
# usage_stats
# ---------------------------------------------------------------------------
def test_cached_input_is_excluded_from_processed_tokens(dr: Any) -> None:
    """``processed`` is the billable-work figure: uncached input + output.

    DR runs are long and heavily cached, so ``input_tokens`` alone overstates
    cost by multiples. This is the number the cost comparison between systems is
    read off, which is why the arithmetic is pinned rather than trusted.
    """
    stats = dr.usage_stats(SimpleNamespace(usage=usage(12_000, 3_000, cached=4_000,
                                                       total=15_000)))

    assert stats == {"tokens": {
        "input": 12_000, "input_uncached": 8_000, "cache_read": 4_000,
        "cache_write": 0, "output": 3_000, "total": 15_000,
        "processed_input": 8_000, "processed": 11_000,
    }}


def test_usage_stats_is_none_when_the_response_carries_no_usage(dr: Any) -> None:
    """No usage -> no stats block, rather than a block of zeros.

    A resumed or failed response has no usage. Zeros would read as "this run was
    free" in the trace, which is worse than an absent field.
    """
    assert dr.usage_stats(SimpleNamespace(usage=None)) is None


def test_missing_cached_token_details_count_as_zero_cached(dr: Any) -> None:
    """``input_tokens_details`` is optional; its absence must not crash.

    The nested ``getattr`` chain is easy to flatten into ``u.input_tokens_details
    .cached_tokens`` while refactoring, which raises on exactly the responses
    that have no caching — the cheap ones.
    """
    bare = SimpleNamespace(input_tokens=100, output_tokens=10, total_tokens=110)

    stats = dr.usage_stats(SimpleNamespace(usage=bare))

    assert stats["tokens"]["cache_read"] == 0
    assert stats["tokens"]["input_uncached"] == 100


def test_a_missing_total_falls_back_to_input_plus_output(dr: Any) -> None:
    """``total_tokens`` is derived when absent, so the field is never null.

    Downstream token aggregation in ``ragrun`` sums these across steps; a None
    would propagate as a TypeError from inside artifact assembly.
    """
    stats = dr.usage_stats(SimpleNamespace(usage=usage(100, 10, cached=0,
                                                       total=None)))

    assert stats["tokens"]["total"] == 110


def test_cached_tokens_exceeding_input_cannot_go_negative(dr: Any) -> None:
    """``max(inp - cached, 0)`` guards an inconsistency we have no control over.

    A negative ``processed`` would silently *reduce* an aggregate cost total
    when steps are summed — a wrong number that looks plausible.
    """
    stats = dr.usage_stats(SimpleNamespace(usage=usage(100, 10, cached=500,
                                                       total=110)))

    assert stats["tokens"]["input_uncached"] == 0
    assert stats["tokens"]["processed"] == 10


# ---------------------------------------------------------------------------
# _retrieve
# ---------------------------------------------------------------------------
def test_retrieve_recovers_from_transient_failures(dr: Any) -> None:
    """A 5xx during polling must not discard an already-paid-for run.

    DR responses are billed on creation and can take an hour; the artifacts only
    exist once retrieve succeeds. Giving up on the first error throws away the
    entire cost of the run.
    """
    client = FakeClient(retrieve_failures=2)

    resp = dr._retrieve(client, "resp_abc")

    assert resp.status == "completed"
    assert len(client.responses.retrieved) == 3


def test_retrieve_gives_up_after_the_attempt_budget(dr: Any) -> None:
    """It must eventually stop, and say how many tries it made.

    An unbounded retry loop against a permanently-500ing response id is
    indistinguishable from a hung run; the attempt count in the message is what
    tells an operator this was exhaustion rather than one bad call.
    """
    client = FakeClient(retrieve_failures=99)

    with pytest.raises(RuntimeError, match="retrieve failed after 3 tries"):
        dr._retrieve(client, "resp_abc", tries=3)

    assert len(client.responses.retrieved) == 3


# ---------------------------------------------------------------------------
# run_one — the streaming path
# ---------------------------------------------------------------------------
def test_run_one_maps_the_item_stream_onto_strict_trajectory_kinds(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """The whole translation, end to end: 5 items -> 5 strict entries in order.

    ``mcp_list_tools`` becoming a ``tool_call`` is deliberate and worth pinning:
    it inflates ``tool_call_counts`` by one relative to the agent's real
    retrieval effort, so anyone comparing this system's call counts against the
    other four needs to know it is there.
    """
    client = FakeClient(usage_obj=usage())

    artifacts = read_artifacts(run(dr, client))
    trajectory = artifacts["trajectory"]

    assert [i["type"] for i in trajectory["result"]] == [
        "tool_call", "reasoning", "tool_call", "tool_call", "output_text"]
    assert trajectory["tool_call_counts"] == {
        "mcp_list_tools": 1, "search": 1, "fetch": 1}
    assert trajectory["status"] == "completed"


def test_run_one_records_every_searched_docid_as_retrieved(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """``retrieved_docids`` is this system's answer to "what did it look at".

    It is the only per-run record of corpus coverage, and it is assembled purely
    from parsed tool output — there is no second source to reconcile it against.
    """
    client = FakeClient()

    trajectory = read_artifacts(run(dr, client))["trajectory"]

    assert trajectory["retrieved_docids"] == sorted(CLIMBMIX_DOCIDS[:2])


def test_fetched_documents_are_offered_as_citations_before_merely_seen_ones(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """Candidate order = fetched first, then searched — and it decides citations.

    ``format_answer``'s heuristic assigns references round-robin in candidate
    order, so this ordering is what makes the first sentence cite a document the
    agent actually read rather than one it only saw a snippet of. The fetch here
    is of the SECOND search hit, so a lost ordering shows up as a swap rather
    than as no change at all.
    """
    client = FakeClient(items=[search_item(ids=CLIMBMIX_DOCIDS[:2]),
                               fetch_item(CLIMBMIX_DOCIDS[1]),
                               message_item()])

    output = read_artifacts(run(dr, client))["output"]

    assert output["references"] == [CLIMBMIX_DOCIDS[1], CLIMBMIX_DOCIDS[0]]


def test_run_one_writes_artifacts_that_pass_the_track_validator(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """A completed run must be submittable without hand-fixing.

    This is the property the other four systems' e2e tests also assert; it is
    the reason ``format_answer`` is shared rather than reimplemented per system.
    """
    client = FakeClient(usage_obj=usage())

    artifacts = read_artifacts(run(dr, client))

    assert artifacts["violations"] == []
    assert validate_rag_output(artifacts["output"]) == []
    assert artifacts["output"]["metadata"]["narrative_id"] == QID
    assert artifacts["output"]["metadata"]["narrative"] == QUERY


def test_the_mcp_tool_block_describes_our_corpus_server(dr: Any) -> None:
    """``require_approval: never`` is what makes an unattended run possible.

    Any other value makes OpenAI's agent stop and wait for a human on its first
    tool call, which for a background run means it simply never progresses. The
    ``server_url`` assertion pins that the tunnel URL reaches the tool block at
    all — it is the single point of failure for corpus grounding.
    """
    client = FakeClient()

    run(dr, client)

    tool, = client.responses.created[0]["tools"]
    assert tool["type"] == "mcp"
    assert tool["server_url"] == "https://tunnel.example/mcp"
    assert tool["require_approval"] == "never"


def test_the_bearer_header_is_sent_only_when_a_token_is_configured(
        dr: Any) -> None:
    """No token must mean no ``headers`` key at all, not an empty one.

    The MCP server rejects a malformed ``Authorization`` header outright, so
    sending ``Bearer None`` against a token-less server would fail every tool
    call — and the failure surfaces inside OpenAI's agent, not in our logs.
    """
    with_token = FakeClient()
    run(dr, with_token, mcp_token="secret-token")
    without = FakeClient()
    run(dr, without)

    assert with_token.responses.created[0]["tools"][0]["headers"] == \
        {"Authorization": "Bearer secret-token"}
    assert "headers" not in without.responses.created[0]["tools"][0]


def test_reasoning_summaries_are_requested_unless_explicitly_disabled(
        dr: Any) -> None:
    """``--no-reasoning-summary`` must omit the key, not send a falsy value.

    The flag exists because ``reasoning.summary=auto`` is the suspected trigger
    of mid-stream APIErrors in DR+MCP runs (2026-07-19). Sending
    ``reasoning: {"summary": None}`` instead of omitting it would leave the
    suspected trigger in place while looking like the workaround was applied.
    """
    default = FakeClient()
    run(dr, default)
    disabled = FakeClient()
    run(dr, disabled, no_reasoning_summary=True)

    assert default.responses.created[0]["reasoning"] == {"summary": "auto"}
    assert "reasoning" not in disabled.responses.created[0]


def test_max_tool_calls_is_omitted_when_unset(dr: Any) -> None:
    """Passing ``max_tool_calls=None`` would cap the agent, not un-cap it.

    The API treats an explicit null differently from an absent field, and a
    capped DR run stops researching mid-plan — producing a short, poorly-grounded
    report that still looks like a successful run.
    """
    unset = FakeClient()
    run(dr, unset)
    capped = FakeClient()
    run(dr, capped, max_tool_calls=25)

    assert "max_tool_calls" not in unset.responses.created[0]
    assert capped.responses.created[0]["max_tool_calls"] == 25


def test_background_mode_is_the_default_and_can_be_turned_off(dr: Any) -> None:
    """``--no-background`` inverts into ``background=False``.

    Background is the default because it is what makes ``--resume`` possible
    after a dropped stream; the flag is the escape hatch for the
    background+MCP read-back bugs. Getting the inversion backwards silently
    removes resumability from every run.
    """
    default = FakeClient()
    run(dr, default)
    foreground = FakeClient()
    run(dr, foreground, no_background=True)

    assert default.responses.created[0]["background"] is True
    assert foreground.responses.created[0]["background"] is False


def test_each_item_gets_its_own_timing_from_the_stream_events(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-item ``t_start``/``t_end`` come from added/done events, not run bounds.

    This is the entire reason this system streams rather than polls. If the
    timing collapsed to the run's bounds, every step would report the full
    hour-long duration and per-step latency analysis — the point of the trace —
    would be meaningless.

    The clock is faked rather than real because the whole event stream here
    completes inside one millisecond, so real ``now_iso()`` values would be
    identical and the test would pass against run-bounds timing too. Each call
    now returns a distinct label: ``t000`` is ``started_at``, so any step
    carrying it took its bound from the run rather than from its own event.
    """
    ticks = iter(f"t{i:03d}" for i in range(500))
    monkeypatch.setattr(dr, "now_iso", lambda: next(ticks))
    client = FakeClient()

    trace = read_artifacts(run(dr, client))["output"]["trace"]
    tool_steps = [s for s in trace["steps"] if s["type"] == "tool_call"]

    assert len(tool_steps) == 3
    # added -> t_start, done -> t_end, per item, interleaved in stream order.
    assert [(s["t_start"], s["t_end"]) for s in tool_steps] == [
        ("t001", "t002"), ("t005", "t006"), ("t007", "t008")]


def test_the_timing_resolution_is_labelled_stream_events(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """The trace says *how* it was timed, because resume cannot do per-item.

    Without the label, a resumed run's run-bounds timings are indistinguishable
    from real per-item ones — every step would appear to take the whole run, and
    an analysis would draw conclusions from it.
    """
    client = FakeClient()

    trajectory = read_artifacts(run(dr, client))["trajectory"]

    assert trajectory["metadata"]["timing_resolution"] == "stream-events"


def test_a_dropped_stream_reconnects_from_the_last_sequence_number(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """Reconnect resumes at ``starting_after=cursor``, and the run still completes.

    The single most load-bearing behaviour in this file. Long DR streams drop;
    without ``starting_after`` the reconnect replays from the beginning (double
    steps) or, if it re-created the response, re-bills an hour of research. The
    assertion on the cursor value is what distinguishes a correct resume from a
    reconnect that merely happens to work on a short stream.
    """
    items = [search_item(), message_item()]

    def drops() -> Iterator[Any]:
        yield SimpleNamespace(type="response.created", sequence_number=1,
                              response=SimpleNamespace(id="resp_abc",
                                                       status="queued"))
        yield SimpleNamespace(type="response.output_item.added",
                              sequence_number=2, output_index=0)
        raise ConnectionError("connection reset by peer")

    def resumes() -> Iterator[Any]:
        yield SimpleNamespace(type="response.output_item.done",
                              sequence_number=3, output_index=0, item=items[0])
        yield SimpleNamespace(type="response.output_item.added",
                              sequence_number=4, output_index=1)
        yield SimpleNamespace(type="response.output_item.done",
                              sequence_number=5, output_index=1, item=items[1])
        yield SimpleNamespace(type="response.completed", sequence_number=6,
                              response=response(items))

    client = FakeClient(items=items, event_script=drops,
                        reconnect_script=resumes)

    trajectory = read_artifacts(run(dr, client))["trajectory"]

    assert client.responses.retrieved == [
        ("resp_abc", {"stream": True, "starting_after": 2})]
    assert len(client.responses.created) == 1        # never re-created (re-billed)
    assert trajectory["status"] == "completed"


def test_an_endlessly_dropping_stream_names_the_resume_id_when_it_gives_up(
        dr: Any) -> None:
    """After the reconnect budget, the error must carry ``--resume <id>``.

    The response is still running and still billed on OpenAI's side, so the id
    is the only way to recover the work. An error without it converts a
    recoverable stream problem into a lost run.
    """
    def always_drops() -> Iterator[Any]:
        yield SimpleNamespace(type="response.created", sequence_number=1,
                              response=SimpleNamespace(id="resp_abc",
                                                       status="queued"))
        raise ConnectionError("connection reset by peer")

    client = FakeClient(event_script=always_drops,
                        reconnect_script=always_drops)

    with pytest.raises(RuntimeError, match=r"--resume resp_abc"):
        run(dr, client)


def test_a_stream_that_never_announces_a_response_raises(dr: Any) -> None:
    """No ``response.created`` means there is no id to resume, so fail loudly.

    This is the one stream failure that is NOT recoverable: with no response id,
    a reconnect has nothing to reconnect to. Retrying it would loop forever
    against a request that never started.
    """
    def no_created() -> Iterator[Any]:
        yield SimpleNamespace(type="response.in_progress", sequence_number=1)

    client = FakeClient(event_script=no_created)

    with pytest.raises(RuntimeError, match="stream ended before response.created"):
        run(dr, client)


def test_a_stream_ending_without_a_terminal_event_falls_back_to_retrieve(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """Silent stream end + known id -> one plain ``retrieve`` recovers the run.

    Distinct from a dropped connection (no exception is raised here), and the
    branch is easy to lose in a refactor because it needs no error handling —
    the loop simply falls out of the ``for``.
    """
    def truncated() -> Iterator[Any]:
        yield SimpleNamespace(type="response.created", sequence_number=1,
                              response=SimpleNamespace(id="resp_abc",
                                                       status="queued"))

    client = FakeClient(event_script=truncated)

    trajectory = read_artifacts(run(dr, client))["trajectory"]

    assert client.responses.retrieved == [("resp_abc", {})]   # plain, not stream
    assert trajectory["status"] == "completed"


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_a_failed_response_still_writes_valid_artifacts(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]],
        status: str) -> None:
    """A failed run must persist its own evidence, and stay spec-valid.

    The trajectory is how a failure gets diagnosed, so refusing to write it is
    the worst possible response. The status is carried through verbatim so the
    submission exporter can refuse the row — ``export-rag-submission.py`` gates
    on ``trace.status`` precisely because a crashed run's artifacts otherwise
    validate clean.
    """
    client = FakeClient(items=[search_item()], status=status)

    artifacts = read_artifacts(run(dr, client))

    assert artifacts["trajectory"]["status"] == status
    assert artifacts["output"]["trace"]["status"] == status
    assert validate_rag_output(artifacts["output"]) == []


def test_a_completed_response_with_no_answer_text_is_not_completed(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """``status == "completed"`` requires an actual answer, not just a clean exit.

    A DR run that exhausts its tool budget can return ``completed`` with no
    message item. Trusting the API's status would mark an answerless run as a
    success, and since the exporter gates on exactly this field — accepting
    ``completed``/``budget_exhausted`` — it would then submit ``format_answer``'s
    ``"No answer was produced."`` placeholder as our answer for that topic. The
    status must therefore be one the exporter does *not* accept.
    """
    client = FakeClient(items=[search_item()])

    artifacts = read_artifacts(run(dr, client))

    assert artifacts["trajectory"]["status"] == "completed_no_answer"
    assert artifacts["output"]["trace"]["status"] not in \
        ("completed", "budget_exhausted")
    # The placeholder answer is what the exporter must never ship unnoticed.
    assert artifacts["output"]["answer"][0]["text"] == "No answer was produced."


# ---------------------------------------------------------------------------
# run_one — the resume path
# ---------------------------------------------------------------------------
def test_resume_polls_until_the_response_leaves_the_queue(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """``--resume`` waits out ``queued``/``in_progress`` before building artifacts.

    Building from an in-progress response would produce a truncated trajectory
    and a partial answer that both look complete. The retrieve count is the
    assertion that matters: a single-shot retrieve passes every other check here.
    """
    client = FakeClient(retrieve_statuses=["queued", "in_progress", "completed"])

    trajectory = read_artifacts(run(dr, client, resume="resp_abc"))["trajectory"]

    assert len(client.responses.retrieved) == 3
    assert client.responses.created == []       # nothing new was billed
    assert trajectory["status"] == "completed"


def test_a_resumed_run_labels_its_timing_as_run_bounds(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """Resume has no stream events, so every step shares the run's bounds.

    The honest label is the whole value here: the timings are real numbers that
    happen to be identical, and only ``timing_resolution`` distinguishes that
    from a run where every step genuinely took the same time.
    """
    client = FakeClient()

    artifacts = read_artifacts(run(dr, client, resume="resp_abc"))

    assert artifacts["trajectory"]["metadata"]["timing_resolution"] == "run-bounds"
    starts = {s["t_start"] for s in artifacts["output"]["trace"]["steps"]}
    assert len(starts) == 1


# ---------------------------------------------------------------------------
# FormatLLM
# ---------------------------------------------------------------------------
class FakeChatCompletions:
    """``client.chat.completions`` returning scripted contents / raising."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))])


def format_llm(dr: Any, script: list[Any]) -> Any:
    """A ``FormatLLM`` with its OpenAI client replaced (``__init__`` bypassed).

    ``FormatLLM.__init__`` constructs a real ``OpenAI``, which needs a key and
    would be blocked by ``no_network`` the moment it was used. Building the
    instance without ``__init__`` keeps ``complete``'s retry logic — the only
    part with behaviour — under test.
    """
    llm = dr.FormatLLM.__new__(dr.FormatLLM)
    llm.model = "gpt-5.6-luna"
    completions = FakeChatCompletions(script)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm.completions = completions
    return llm


def test_format_llm_retries_past_errors_and_blank_completions(dr: Any) -> None:
    """An empty completion is a failure, not an answer.

    Without the ``text.strip()`` check, a blank response would be returned as
    the formatted answer and ``format_answer`` would accept it — silently
    replacing a whole report with an empty string at the last step of a paid run.
    """
    llm = format_llm(dr, [RuntimeError("503"), "", "   Formatted answer.  "])

    assert llm.complete([{"role": "user", "content": "x"}]) == "Formatted answer."
    assert len(llm.completions.calls) == 3


def test_format_llm_raises_after_three_failed_attempts(dr: Any) -> None:
    """It gives up rather than looping, and surfaces the last error.

    ``format_answer`` catches this and falls back to the deterministic
    heuristic, so the run survives — but the message is the only record of why
    the formatting model was not used.
    """
    llm = format_llm(dr, [RuntimeError("a"), RuntimeError("b"),
                          RuntimeError("c")])

    with pytest.raises(RuntimeError, match="format LLM failed: c"):
        llm.complete([{"role": "user", "content": "x"}])


def test_format_llm_uses_max_completion_tokens_not_max_tokens(dr: Any) -> None:
    """Reasoning models reject ``max_tokens`` outright.

    The wrong parameter name is a 400 on every call, which ``complete`` retries
    three times and then converts into a fallback — so the symptom is a
    heuristic-formatted answer with nothing obviously wrong, not an error.
    """
    llm = format_llm(dr, ["ok"])

    llm.complete([{"role": "user", "content": "x"}], max_tokens=4000)

    call, = llm.completions.calls
    assert call["max_completion_tokens"] == 4000
    assert "max_tokens" not in call


def test_the_formatter_llm_result_is_preferred_over_the_heuristic(
        dr: Any, read_artifacts: Callable[..., dict[str, Any]]) -> None:
    """``run_one`` threads its ``format_llm`` through to ``format_answer``.

    The LLM path is what produces sentence-accurate citations; the heuristic
    distributes docids round-robin regardless of what each sentence says. If the
    wiring broke, every run would silently take the worse path and still look
    fine.
    """
    docid = CLIMBMIX_DOCIDS[0]
    llm = format_llm(dr, [json.dumps({"sentences": [
        {"text": "Revenue funds the capital plan.", "citations": [docid]}]})])
    client = FakeClient()

    output = read_artifacts(
        dr.run_one(client, qid=QID, query=QUERY, args=cli_args(),
                   format_llm=llm))["output"]

    assert output["answer"] == [
        {"text": "Revenue funds the capital plan.", "citations": [0]}]
    assert output["references"] == [docid]


# ---------------------------------------------------------------------------
# load_topics
# ---------------------------------------------------------------------------
def test_load_topics_skips_blank_and_narrative_less_lines(dr: Any,
                                                          tmp_path: Path) -> None:
    """Only ``qid<TAB>narrative`` rows survive; everything else is dropped.

    The dev topics TSV has a trailing newline and has been seen with stray blank
    lines. A blank row would become a topic with an empty narrative, which the
    DR agent would happily research — burning a full paid run on nothing.
    """
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("q1\tFirst narrative.\n"
                   "\n"
                   "no_tab_at_all\n"
                   "q3\t\n"
                   "q4\tFourth narrative.\n", encoding="utf-8")

    assert dr.load_topics(tsv) == [("q1", "First narrative."),
                                   ("q4", "Fourth narrative.")]


def test_a_narrative_containing_tabs_keeps_them(dr: Any, tmp_path: Path) -> None:
    """``partition`` splits on the FIRST tab only, so the narrative stays whole.

    A ``split("\\t")`` would truncate any narrative containing a tab at its
    first one — losing most of the topic while still producing a runnable row.
    """
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("q1\tpart one\tpart two\n", encoding="utf-8")

    assert dr.load_topics(tsv) == [("q1", "part one\tpart two")]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
@pytest.fixture
def main_env(dr: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub out ``OpenAI`` and ``run_one`` so ``main``'s wiring can be tested.

    ``main`` is argument plumbing plus a loop; the ``calls`` list records the
    ``(qid, query)`` pairs it decided to run, which is the only behaviour it
    actually owns.
    """
    import openai

    monkeypatch.setattr(openai, "OpenAI",
                        lambda **kw: SimpleNamespace(_kwargs=kw))
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(dr, "run_one",
                        lambda client, *, qid, query, args, format_llm:
                        calls.append((qid, query)) or {})
    monkeypatch.setenv("OPENAI_DEEP_RESEARCH_API_KEY", "test-key")
    monkeypatch.setenv("O3DR_MCP_URL", "https://tunnel.example/mcp")
    return {"calls": calls}


def _main(dr: Any, monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["run.py", *argv])
    dr.main()


def test_main_refuses_to_start_without_the_deep_research_key(
        dr: Any, main_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The DR key is a *different* key from ``OPENAI_API_KEY``.

    The repo ``.env`` carries an Azure ``OPENAI_API_KEY`` and ``OPENAI_BASE_URL``
    which the SDK would otherwise pick up — so failing fast on the specific var
    is what prevents a DR request being sent to Azure and failing obscurely
    after the tunnel is already up.
    """
    monkeypatch.delenv("OPENAI_DEEP_RESEARCH_API_KEY", raising=False)

    with pytest.raises(SystemExit):
        _main(dr, monkeypatch, "--query", QUERY)


def test_main_refuses_to_start_without_an_mcp_url(
        dr: Any, main_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """No MCP server means no corpus — and DR would answer from prior knowledge.

    That is the one outcome this whole system exists to prevent: an
    ungrounded report indistinguishable in shape from a grounded one.
    """
    monkeypatch.delenv("O3DR_MCP_URL", raising=False)

    with pytest.raises(SystemExit):
        _main(dr, monkeypatch, "--query", QUERY)


def test_an_adhoc_query_runs_under_the_qid_adhoc(
        dr: Any, main_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``--query`` has no topic id, so artifacts land under ``adhoc``.

    Worth pinning because that string is what keeps a plumbing check from being
    mistaken for a real topic's run when the outputs dir is scanned.
    """
    _main(dr, monkeypatch, "--query", QUERY, "--no-format-llm")

    assert main_env["calls"] == [("adhoc", QUERY)]


def test_a_missing_qid_is_an_error_not_a_silent_no_op(
        dr: Any, main_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """A typo'd ``--qid`` must fail, because an empty loop exits 0.

    In a shell loop over topic ids, a silent no-op is indistinguishable from a
    successful run and leaves a hole in the submission that only shows up at
    export time.
    """
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("q1\tFirst narrative.\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        _main(dr, monkeypatch, "--qid", "nonexistent", "--topics", str(tsv),
              "--no-format-llm")


def test_all_runs_every_topic_in_file_order(
        dr: Any, main_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """``--all`` preserves the TSV's order, and runs each topic exactly once.

    Order is how a partially-completed sweep is resumed by eye, and a duplicate
    would produce two artifacts for one narrative_id — which the exporter
    rejects outright.
    """
    tsv = tmp_path / "topics.tsv"
    tsv.write_text("q1\tFirst.\nq2\tSecond.\nq3\tThird.\n", encoding="utf-8")

    _main(dr, monkeypatch, "--all", "--topics", str(tsv), "--no-format-llm")

    assert main_env["calls"] == [("q1", "First."), ("q2", "Second."),
                                 ("q3", "Third.")]


def test_query_qid_and_all_are_mutually_exclusive(
        dr: Any, main_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly one input mode, chosen explicitly.

    Without the exclusive group, ``--all --qid x`` would silently pick one and
    a sweep intended to cover 119 topics could quietly run a single one.
    """
    with pytest.raises(SystemExit):
        _main(dr, monkeypatch, "--query", QUERY, "--all")


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_run_one_live_against_openai_and_a_real_mcp_tunnel(dr: Any) -> None:
    """The real thing: hosted DR agent, real Responses stream, real MCP corpus.

    Everything above fakes the SDK, so only this proves the pieces this system
    cannot test offline — that OpenAI's servers can actually reach our tunnel,
    that the bearer token is accepted, and that a real event stream maps onto
    the trajectory. ``o4-mini-deep-research`` with a small tool budget keeps it
    to the cheap plumbing check the module docstring describes.

    Needs ``OPENAI_DEEP_RESEARCH_API_KEY`` and ``O3DR_MCP_URL`` (a public URL —
    a cloudflared tunnel in front of ``src/mcp/climbmix_server.py``).
    """
    import os

    from openai import OpenAI

    api_key = os.environ.get("OPENAI_DEEP_RESEARCH_API_KEY")
    mcp_url = os.environ.get("O3DR_MCP_URL")
    if not api_key or not mcp_url:
        pytest.skip("needs OPENAI_DEEP_RESEARCH_API_KEY and O3DR_MCP_URL")

    client = OpenAI(api_key=api_key, base_url=dr.OPENAI_BASE_URL, timeout=600)
    paths = dr.run_one(
        client, qid="live_dr_001", query=QUERY,
        args=cli_args(mcp_url=mcp_url,
                      mcp_token=os.environ.get("CLIMBMIX_MCP_TOKEN"),
                      model="o4-mini-deep-research", max_tool_calls=4,
                      run_id="o3-deep-research.live"),
        format_llm=None)

    output = json.loads(paths["output"].read_text())
    assert validate_rag_output(output) == []
    assert output["references"], "a grounded run must cite at least one docid"
