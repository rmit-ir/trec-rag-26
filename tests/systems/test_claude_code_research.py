"""End-to-end coverage for ``src/systems/claude-code-research/scripts/``.

This system has no runner: **Claude Code itself is the agent**, driven by the
system dir's ``CLAUDE.md``, and the two scripts here are all the code there is.
That inverts what a test can prove. The other four systems' suites assert what
the agent *did*; nothing offline can assert that about a human-or-Claude session.
What these scripts own instead is the *evidence chain*, and that is what is
tested:

    corpus.py  --appends-->  scratchpad/tool_log.jsonl  --read-by-->  save_run.py

Every property here defends one link:

- ``corpus.py`` logs a record for every call, **including failures**, because
  the log is the only trace of research that exists. The agent is instructed
  never to call ``src/tools`` directly for exactly this reason — a call made off
  the log is a call that never happened as far as the artifacts are concerned.
- ``save_run.py`` **drops any citation to a docid no logged call returned.**
  This is the system's one real safety property: the agent writes citations by
  hand into ``answer_sentences.json``, so a hallucinated or mistyped docid is a
  live possibility on every run, and there is no retrieval step downstream to
  catch it. The drop is what keeps an unretrieved docid out of a submission.

The pair is tested end-to-end through a temp task dir rather than per-function
where possible, since the file format between them is the actual contract and
neither script validates it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest
from conftest import CLIMBMIX_DOCIDS

from ragrun import validate_rag_output

CCR_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "systems" \
    / "claude-code-research" / "scripts"

QID = "mock_ccr_001"
QUERY = "How is congestion pricing revenue in New York being spent?"
A, B, C = CLIMBMIX_DOCIDS[0], CLIMBMIX_DOCIDS[1], CLIMBMIX_DOCIDS[2]
GHOST = "shard_99999_00000"      # never returned by any logged call


# ---------------------------------------------------------------------------
# The two modules under test (loaded by path — the dir name has a hyphen)
# ---------------------------------------------------------------------------
@pytest.fixture
def corpus(load_module: Callable[[Path, str], Any]) -> Any:
    return load_module(CCR_SCRIPTS / "corpus.py", "ccr_corpus")


@pytest.fixture
def save_run_mod(load_module: Callable[[Path, str], Any]) -> Any:
    return load_module(CCR_SCRIPTS / "save_run.py", "ccr_save_run")


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """An empty research task folder, as the lead agent would create it."""
    d = tmp_path / "tasks" / "congestion_pricing_20260730_120000"
    (d / "scratchpad").mkdir(parents=True)
    return d


def log_records(task_dir: Path) -> list[dict[str, Any]]:
    log = task_dir / "scratchpad" / "tool_log.jsonl"
    return [json.loads(line) for line in
            log.read_text(encoding="utf-8").splitlines() if line.strip()]


def tool_record(name: str, arguments: dict[str, Any], **extra: Any
                ) -> dict[str, Any]:
    """One ``tool_log.jsonl`` record in the shape ``corpus.py`` writes.

    Handwritten rather than produced by running ``corpus.py`` so a
    ``save_run.py`` test can construct log shapes that are awkward to provoke
    through the CLI (a failed fetch, a search with no results). The
    round-trip tests below cover that the two shapes really do agree.
    """
    rec = {"ts": "2026-07-30T12:00:00.000+10:00",
           "t_start": "2026-07-30T12:00:00.000+10:00",
           "t_end": "2026-07-30T12:00:01.000+10:00",
           "type": "tool_call", "tool_name": name, "arguments": arguments,
           "output_head": f"head of {name} output"}
    rec.update(extra)
    return rec


def write_log(task_dir: Path, records: list[dict[str, Any]]) -> None:
    (task_dir / "scratchpad" / "tool_log.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8")


def write_answer(task_dir: Path, sentences: list[dict[str, Any]], *,
                 run_id: str = "ccr.test",
                 run_desc: str = "hermetic end-to-end test") -> Path:
    path = task_dir / "answer_sentences.json"
    path.write_text(json.dumps({"run_id": run_id, "run_desc": run_desc,
                                "answer": sentences}), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# corpus.py — task dir resolution
# ---------------------------------------------------------------------------
def test_a_missing_task_dir_stops_the_call_before_it_runs(
        corpus: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """No task dir means nowhere to log, so the search must not happen at all.

    Resolution is deliberately the FIRST thing each subcommand does. Searching
    first and failing to log after would spend a real retrieval call whose
    result exists only in the agent's context — untraceable, and uncitable,
    since ``save_run.py`` drops docids no logged call returned.
    """
    monkeypatch.delenv("TASK_DIR", raising=False)

    with pytest.raises(SystemExit, match="pass --task-dir or set TASK_DIR"):
        corpus.resolve_task_dir(None)


def test_the_task_dir_env_var_is_honoured(corpus: Any, task_dir: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """``TASK_DIR`` exists so an agent can export it once per task.

    Without it every one of the dozens of ``corpus.py`` calls in a run needs the
    flag repeated, and the one that forgets it is the one whose evidence is lost.
    """
    monkeypatch.setenv("TASK_DIR", str(task_dir))

    assert corpus.resolve_task_dir(None) == task_dir


def test_an_explicit_task_dir_beats_the_environment(
        corpus: Any, task_dir: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``--task-dir`` wins, which is what lets a sub-agent share the lead's log.

    ``CLAUDE.md`` requires sub-agents to log into the *lead's* task dir. A
    sub-agent inheriting a stale ``TASK_DIR`` from the environment would scatter
    its evidence into another task's folder, and the lead's ``save_run`` would
    then drop every docid the sub-agent found.
    """
    monkeypatch.setenv("TASK_DIR", str(tmp_path / "some_other_task"))

    assert corpus.resolve_task_dir(str(task_dir)) == task_dir


# ---------------------------------------------------------------------------
# corpus.py — logging
# ---------------------------------------------------------------------------
def test_the_log_directory_is_created_on_first_write(corpus: Any,
                                                     tmp_path: Path) -> None:
    """``scratchpad/`` is created if absent — an agent may not have made it yet.

    ``CLAUDE.md`` tells the lead to create it, but the first corpus call often
    comes first. Raising here would mean losing the first call's evidence to a
    directory that the very next line would have created.
    """
    fresh = tmp_path / "brand_new_task"

    corpus.append_log(fresh, {"tool_name": "search"})

    assert log_records(fresh) == [{"tool_name": "search"}]


def test_log_records_append_rather_than_overwrite(corpus: Any,
                                                  task_dir: Path) -> None:
    """Each call adds a line; the log is the whole run's history, in order.

    Order is what makes the trajectory's step sequence meaningful, and an
    open-mode slip (``"w"``) would leave every run with exactly one tool call —
    a trajectory that still validates and still looks plausible.
    """
    for i in range(3):
        corpus.append_log(task_dir, {"n": i})

    assert log_records(task_dir) == [{"n": 0}, {"n": 1}, {"n": 2}]


def test_non_ascii_is_written_literally_to_the_log(corpus: Any,
                                                   task_dir: Path) -> None:
    """``ensure_ascii=False``: the log is read by humans debugging a run.

    ClimbMix is a web-crawl corpus full of accented names and non-Latin scripts;
    ``\\uXXXX`` soup in the ``output_head`` makes the one artifact a person reads
    while diagnosing a bad answer unreadable.
    """
    corpus.append_log(task_dir, {"output_head": "Café — 東京"})

    raw = (task_dir / "scratchpad" / "tool_log.jsonl").read_text(encoding="utf-8")
    assert "Café — 東京" in raw
    assert "\\u" not in raw


def test_the_record_timestamp_alias_matches_t_start(corpus: Any) -> None:
    """``ts`` is a back-compat alias for ``t_start`` and must not drift from it.

    Two separate ``now_iso()`` calls would produce two nearly-equal but distinct
    timestamps, and any consumer comparing them would see a phantom sub-second
    gap in every single record.
    """
    record = corpus._base_record("search", {"query": "x"})

    assert record["ts"] == record["t_start"]
    assert record["type"] == "tool_call"
    assert record["arguments"] == {"query": "x"}


# ---------------------------------------------------------------------------
# corpus.py — search
# ---------------------------------------------------------------------------
def _search_args(task_dir: Path, query: list[str], *, k: int = 3,
                 max_chars: int = 300) -> Any:
    from argparse import Namespace
    return Namespace(query=query, k=k, max_chars=max_chars,
                     task_dir=str(task_dir))


def test_search_logs_the_returned_docids_and_scores(
        corpus: Any, task_dir: Path, stub_search_tool: dict[str, Any],
        capsys: pytest.CaptureFixture[str]) -> None:
    """``returned`` is the evidence record that makes those docids citable.

    ``save_run.py`` builds its ``retrieved`` set from this field alone. A search
    logged without it makes every docid it found uncitable — the answer's
    citations get silently dropped and the references list comes out short,
    with the run still exiting 0.
    """
    rc = corpus.cmd_search(_search_args(task_dir, ["congestion", "pricing"]))

    assert rc == 0
    record, = log_records(task_dir)
    assert record["tool_name"] == "search"
    assert [h["docid"] for h in record["returned"]] == list(CLIMBMIX_DOCIDS[:3])
    assert all(isinstance(h["score"], (int, float)) for h in record["returned"])


def test_a_multi_word_query_is_logged_as_one_string(
        corpus: Any, task_dir: Path, stub_search_tool: dict[str, Any],
        capsys: pytest.CaptureFixture[str]) -> None:
    """``nargs="+"`` means the shell's word splitting must be undone.

    The agent writes ``corpus.py search congestion pricing revenue`` without
    quotes routinely. Logging the list rather than the joined string would make
    the logged ``arguments`` disagree with what was actually searched, and the
    joined form is also what reaches the retriever.
    """
    corpus.cmd_search(_search_args(task_dir, ["congestion", "pricing", "revenue"]))

    record, = log_records(task_dir)
    assert record["arguments"] == {
        "query": "congestion pricing revenue",
        "k": 3,
        "search_engine": "hybrid-rrf",
    }
    assert set(stub_search_tool) == {"semantic", "keyword"}
    assert all(calls[0]["query"] == "congestion pricing revenue"
               for calls in stub_search_tool.values())


def test_search_fans_out_to_dense_and_sparse_then_returns_rrf_order(
        corpus: Any, task_dir: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """The agent is promised hybrid retrieval, so calling both backends is not
    enough: the visible order must be RRF output rather than either input list."""
    from utils import search as search_mod
    from utils.search_types import make_hit

    calls: list[tuple[str, str, int]] = []

    def ranking(source: str, ids: tuple[str, ...]) -> list[dict[str, Any]]:
        return [make_hit(docid, score=10.0 - rank, rank=rank,
                         text=f"{source} text for {docid}",
                         meta={"source": source})
                for rank, docid in enumerate(ids, start=1)]

    def dense(query: str, k: int, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(("dense", query, k))
        return ranking("dense", (A, B))

    def sparse(query: str, k: int, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append(("sparse", query, k))
        return ranking("sparse", (B, C))

    monkeypatch.setattr(search_mod, "search_dense", dense)
    monkeypatch.setattr(search_mod, "search_sparse", sparse)

    corpus.cmd_search(_search_args(task_dir, ["congestion pricing"]))

    payload = json.loads(capsys.readouterr().out)
    assert {source for source, _, _ in calls} == {"dense", "sparse"}
    assert all(query == "congestion pricing" and depth == 50
               for _, query, depth in calls)
    assert [hit["docid"] for hit in payload["results"]] == [B, A, C]
    assert payload["engine"] == "hybrid-rrf"
    record, = log_records(task_dir)
    assert record["arguments"]["search_engine"] == "hybrid-rrf"


def test_a_search_error_is_logged_as_a_failure_and_exits_non_zero(
        corpus: Any, task_dir: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """A failed search must still appear in the log, with no ``returned``.

    Two things depend on it: the agent sees a non-zero exit and knows to retry
    or reformulate, and ``tool_call_counts_all`` records the attempt so a run
    that spent half its budget on a broken retriever is visible afterwards
    rather than looking like a run that simply searched less.
    """
    def fail_search(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("backend 503")

    monkeypatch.setattr(corpus, "hybrid_search", fail_search)

    rc = corpus.cmd_search(_search_args(task_dir, ["congestion pricing"]))

    assert rc == 1
    record, = log_records(task_dir)
    assert record["failed"] is True
    assert record["error"] == "RuntimeError: backend 503"
    assert "returned" not in record


def test_the_logged_output_head_is_bounded(
        corpus: Any, task_dir: Path, stub_search_tool: dict[str, Any],
        capsys: pytest.CaptureFixture[str]) -> None:
    """``output_head`` is a 200-char excerpt, not the whole result payload.

    Every head lands in the trajectory as a step's ``output``. Logging full
    search results (10 passages each) would balloon the artifact by orders of
    magnitude on a 20-round run, for text already recoverable by docid.
    """
    corpus.cmd_search(_search_args(task_dir, ["congestion pricing"]))

    record, = log_records(task_dir)
    assert len(record["output_head"]) <= corpus.HEAD_CHARS


# ---------------------------------------------------------------------------
# corpus.py — fetch
# ---------------------------------------------------------------------------
def _fetch_args(task_dir: Path, docid: str, *, max_chars: int = 200) -> Any:
    from argparse import Namespace
    return Namespace(docid=docid, max_chars=max_chars, task_dir=str(task_dir))


@pytest.fixture
def stub_corpus_fetch(corpus: Any, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace ``corpus.py``'s ``fetch_doc`` with an in-memory corpus.

    Patched on the ``corpus`` module rather than ``utils.fetch_doc``, since the
    script did a ``from utils.fetch_doc import fetch_doc`` and holds its own
    reference. Docids starting ``missing`` raise, to exercise the failure log.
    """
    asked: list[str] = []

    def _fake(docid: str, **_kw: Any) -> dict[str, str]:
        asked.append(docid)
        if docid.startswith("missing"):
            raise RuntimeError("404 no such docid")
        return {"docid": docid, "text": "Full text of " + docid + ". " + "x" * 500}

    monkeypatch.setattr(corpus, "fetch_doc", _fake)
    return asked


def test_fetch_is_logged_under_the_spec_tool_name(
        corpus: Any, task_dir: Path, stub_corpus_fetch: list[str],
        capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI subcommand is ``fetch``; the logged tool name is ``get_document``.

    The rename is deliberate — ``get_document`` is the name the track's sample
    trajectories use, so it is what makes this system's ``tool_call_counts``
    comparable with the other four systems' and with the organizers' examples.
    """
    rc = corpus.cmd_fetch(_fetch_args(task_dir, A))

    assert rc == 0
    record, = log_records(task_dir)
    assert record["tool_name"] == "get_document"
    assert record["arguments"] == {"docid": A}


def test_a_fetch_record_carries_no_returned_field(
        corpus: Any, task_dir: Path, stub_corpus_fetch: list[str],
        capsys: pytest.CaptureFixture[str]) -> None:
    """Fetch logs no ``returned`` — its docid is recovered from ``arguments``.

    ``save_run.build_trajectory`` branches on exactly this: ``returned is None``
    plus ``tool_name == "get_document"`` is what makes it read the docid from the
    request. Adding a ``returned`` here would take the other branch, and a
    ``returned`` shaped like search's (``[{"docid", "score"}]``) is not what a
    fetch has to offer.
    """
    corpus.cmd_fetch(_fetch_args(task_dir, A))

    record, = log_records(task_dir)
    assert "returned" not in record
    assert "failed" not in record


def test_a_failed_fetch_is_logged_with_the_exception_text(
        corpus: Any, task_dir: Path, stub_corpus_fetch: list[str],
        capsys: pytest.CaptureFixture[str]) -> None:
    """The failure is logged BEFORE it is reported, so evidence survives.

    A missing docid usually means the agent invented or mistyped one, which is
    precisely what a reviewer wants to see in the trace. The exception type is
    kept in the message because ``404`` and a timeout imply completely different
    follow-ups.
    """
    rc = corpus.cmd_fetch(_fetch_args(task_dir, "missing_doc_1"))

    assert rc == 1
    record, = log_records(task_dir)
    assert record["failed"] is True
    assert record["error"] == "RuntimeError: 404 no such docid"
    assert record["output_head"] == record["error"]
    assert capsys.readouterr().err.strip().startswith("corpus.py fetch:")


def test_a_fetch_head_is_bounded_independently_of_what_was_printed(
        corpus: Any, task_dir: Path, stub_corpus_fetch: list[str],
        capsys: pytest.CaptureFixture[str]) -> None:
    """``--max-chars`` widens the PRINTED text, not the logged head.

    The agent routinely fetches with ``--max-chars 2000`` to read a document
    properly. If that also set the logged head, every such call would paste 2000
    chars into the trajectory — and the agent's display preference would end up
    silently determining artifact size.
    """
    corpus.cmd_fetch(_fetch_args(task_dir, A, max_chars=2000))

    printed = capsys.readouterr().out
    record, = log_records(task_dir)
    assert len(record["output_head"]) == corpus.HEAD_CHARS
    assert len(printed) > corpus.HEAD_CHARS


def test_printed_fetch_text_is_flattened_to_one_line(
        corpus: Any, task_dir: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Newlines are stripped from the printed line, keeping the CLI grep-able.

    ``<docid> -> <text>`` on one line is what lets the agent (and a person)
    scan a batch of fetches; a multi-paragraph document would otherwise scroll
    the docid off screen.
    """
    monkeypatch.setattr(corpus, "fetch_doc",
                        lambda docid, **kw: {"docid": docid,
                                             "text": "line one\nline two"})

    corpus.cmd_fetch(_fetch_args(task_dir, A))

    out = capsys.readouterr().out.strip()
    assert out == f"{A} -> line one line two"


# ---------------------------------------------------------------------------
# save_run.py — narrative lookup and log reading
# ---------------------------------------------------------------------------
def test_a_narrative_is_looked_up_by_qid(save_run_mod: Any,
                                         tmp_path: Path) -> None:
    """``--topics`` resolves the narrative, so the artifact's text is the official one.

    Retyping a 119-topic narrative by hand into ``--query`` is how a submission
    ends up with a paraphrased ``metadata.narrative`` that no longer matches the
    organizers' topic file.
    """
    tsv = tmp_path / "topics.tsv"
    tsv.write_text(f"other\tSomething else.\n{QID}\t{QUERY}\n", encoding="utf-8")

    assert save_run_mod.load_narrative(tsv, QID) == QUERY


def test_an_unknown_qid_is_fatal(save_run_mod: Any, tmp_path: Path) -> None:
    """A qid typo must stop the run rather than produce an empty narrative.

    An empty narrative still validates and still saves — the artifact would look
    complete while being unattributable to any topic.
    """
    tsv = tmp_path / "topics.tsv"
    tsv.write_text(f"{QID}\t{QUERY}\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="not found"):
        save_run_mod.load_narrative(tsv, "no_such_qid")


def test_a_missing_tool_log_is_fatal_and_says_why(save_run_mod: Any,
                                                  task_dir: Path) -> None:
    """No log means no evidence, so no artifacts — and the message names the cause.

    Without the log every citation would be dropped as unretrieved, producing an
    uncited answer with an empty reference list that still validates clean. The
    error text points at ``scripts/corpus.py`` because bypassing it is the one
    way to get here.
    """
    with pytest.raises(SystemExit, match="must go through scripts/corpus.py"):
        save_run_mod.read_tool_log(task_dir)


def test_blank_lines_in_the_log_are_skipped(save_run_mod: Any,
                                            task_dir: Path) -> None:
    """A stray blank line must not abort artifact assembly.

    The log is appended to by many concurrent ``corpus.py`` processes (the agent
    batches parallel searches), and this runs at the very end of a long research
    session — a ``JSONDecodeError`` here discards the whole run's trace.
    """
    log = task_dir / "scratchpad" / "tool_log.jsonl"
    log.write_text('{"tool_name": "search"}\n\n   \n{"tool_name": "fetch"}\n',
                   encoding="utf-8")

    assert [r["tool_name"] for r in save_run_mod.read_tool_log(task_dir)] == \
        ["search", "fetch"]


# ---------------------------------------------------------------------------
# save_run.py — build_trajectory
# ---------------------------------------------------------------------------
def _builder(save_run_mod: Any) -> Any:
    from ragrun import TrajectoryBuilder
    return TrajectoryBuilder(QID, QUERY, metadata={})


def test_search_and_fetch_docids_both_become_retrievable(save_run_mod: Any) -> None:
    """Both call types feed the ``retrieved`` set, by different routes.

    Search contributes via ``returned``; fetch via its ``arguments`` (a fetch
    record has no ``returned``). A regression in either branch silently
    un-cites a whole class of the agent's evidence.
    """
    tb = _builder(save_run_mod)

    retrieved = save_run_mod.build_trajectory(tb, [
        tool_record("search", {"query": "x", "k": 2},
                    returned=[{"docid": A, "score": 1.0},
                              {"docid": B, "score": 0.9}]),
        tool_record("get_document", {"docid": C}),
    ])

    assert retrieved == {A, B, C}


def test_a_failed_fetch_contributes_no_retrieved_docid(save_run_mod: Any) -> None:
    """A fetch that errored proves nothing was read, so the docid stays uncitable.

    This is the ``and not failed`` guard, and it is the one place where the
    fetch branch could quietly over-credit: the docid is present in
    ``arguments`` whether or not the document exists. Without the guard, a
    citation to a docid that 404'd would sail into the submission.
    """
    tb = _builder(save_run_mod)

    retrieved = save_run_mod.build_trajectory(tb, [
        tool_record("get_document", {"docid": A}, failed=True,
                    error="RuntimeError: 404"),
    ])

    assert retrieved == set()
    assert tb.trace_steps[0]["failed"] is True


def test_successful_and_attempted_call_counts_are_kept_apart(
        save_run_mod: Any) -> None:
    """``tool_call_counts`` counts successes; ``tool_call_counts_all`` counts tries.

    The gap between them is the run's failure rate, which is how a broken
    retriever or a run full of invented docids is spotted after the fact. Both
    numbers appear in the trajectory precisely so neither can hide the other.
    """
    tb = _builder(save_run_mod)

    save_run_mod.build_trajectory(tb, [
        tool_record("search", {"query": "x", "k": 1},
                    returned=[{"docid": A, "score": 1.0}]),
        tool_record("get_document", {"docid": A}),
        tool_record("get_document", {"docid": GHOST}, failed=True, error="404"),
    ])
    trajectory = tb.finalize(status="completed")

    assert trajectory["tool_call_counts"] == {"search": 1, "get_document": 1}
    assert trajectory["tool_call_counts_all"] == {"search": 1, "get_document": 2}


def test_a_search_that_returned_nothing_is_not_treated_as_a_failure(
        save_run_mod: Any) -> None:
    """An empty ``returned`` list is a successful search with no hits.

    ``returned=[]`` is falsy, so a truthiness check would either mark it failed
    or push it down the ``get_document`` branch and raise ``KeyError:
    'docid'``. A zero-hit search is a completely normal research outcome — the
    agent is told to reformulate and retry.
    """
    tb = _builder(save_run_mod)

    retrieved = save_run_mod.build_trajectory(tb, [
        tool_record("search", {"query": "nothing matches", "k": 10}, returned=[]),
    ])
    trajectory = tb.finalize(status="completed")

    assert retrieved == set()
    # Counted as a success in BOTH tallies — a zero-hit search is not a failure.
    assert trajectory["tool_call_counts"] == {"search": 1}
    assert trajectory["tool_call_counts_all"] == {"search": 1}
    assert tb.trace_steps[0]["failed"] is False


def test_the_logged_wall_clock_bounds_reach_the_trajectory(
        save_run_mod: Any) -> None:
    """Timings come from ``corpus.py``'s log, since nothing else knows them.

    Each call is a separate short-lived process; by the time ``save_run.py``
    runs, the only record of when anything happened is the log. Dropping the
    fields would leave every step timestamped at assembly time — plausible
    values that describe nothing.
    """
    tb = _builder(save_run_mod)

    save_run_mod.build_trajectory(tb, [
        tool_record("get_document", {"docid": A})])

    step = tb.trace_steps[0]
    assert step["t_start"] == "2026-07-30T12:00:00.000+10:00"
    assert step["t_end"] == "2026-07-30T12:00:01.000+10:00"


# ---------------------------------------------------------------------------
# save_run.py — map_citations (the safety property)
# ---------------------------------------------------------------------------
def test_references_are_cited_docids_in_first_appearance_order(
        save_run_mod: Any) -> None:
    """Indices are assigned on first citation, so ``answer`` indexes ``references``.

    The whole answer format hangs on this: a citation is an integer index into
    ``references``. An ordering change here re-points every citation in the
    submission at a different document — a maximally-wrong output that validates
    perfectly.
    """
    references, answer = save_run_mod.map_citations([
        {"text": "First.", "citations": [B]},
        {"text": "Second.", "citations": [A, B]},
    ], {A, B})

    assert references == [B, A]
    assert answer == [{"text": "First.", "citations": [0]},
                      {"text": "Second.", "citations": [1, 0]}]


def test_a_docid_no_logged_call_returned_is_dropped_with_a_warning(
        save_run_mod: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """The system's core safety property: hand-written citations are verified.

    The agent writes ``answer_sentences.json`` itself, so a hallucinated or
    mistyped docid is possible on every run and there is no retrieval step after
    this to catch it. Dropping it keeps an unretrieved document out of the
    submission; the stderr warning is what tells the agent to fix its answer,
    since the run otherwise exits 0 and looks clean.
    """
    references, answer = save_run_mod.map_citations([
        {"text": "Grounded claim.", "citations": [A, GHOST]},
    ], {A})

    assert references == [A]
    assert answer == [{"text": "Grounded claim.", "citations": [0]}]
    err = capsys.readouterr().err
    assert GHOST in err and "no logged tool call returned" in err


def test_a_sentence_whose_every_citation_is_dropped_survives_uncited(
        save_run_mod: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """The sentence is kept with ``citations: []`` rather than deleted.

    Deleting it would silently rewrite the agent's answer, and an empty
    ``citations`` list is explicitly legal under ``rag-task.md`` v0.6.0 — so the
    honest artifact is an uncited sentence, which a reviewer can see, not a
    missing one they cannot.
    """
    references, answer = save_run_mod.map_citations([
        {"text": "Ungrounded claim.", "citations": [GHOST]},
        {"text": "Grounded claim.", "citations": [A]},
    ], {A})

    assert references == [A]
    assert answer == [{"text": "Ungrounded claim.", "citations": []},
                      {"text": "Grounded claim.", "citations": [0]}]


def test_a_docid_cited_twice_in_one_sentence_yields_one_index(
        save_run_mod: Any) -> None:
    """Within-sentence duplicates collapse, keeping the ≤3-citation cap honest.

    A sentence citing ``[A, A, A, B]`` would otherwise report four citations and
    breach the per-sentence cap on what is really two distinct documents.
    """
    references, answer = save_run_mod.map_citations([
        {"text": "Repeated.", "citations": [A, A, B, A]},
    ], {A, B})

    assert references == [A, B]
    assert answer == [{"text": "Repeated.", "citations": [0, 1]}]


def test_a_sentence_with_no_citations_key_is_accepted(save_run_mod: Any) -> None:
    """A missing ``citations`` key is read as no citations, not an error.

    The agent hand-writes this JSON; omitting the key on a transitional sentence
    is a likely slip, and failing the whole assembly for it would discard a
    completed research run's artifacts over one absent empty list.
    """
    references, answer = save_run_mod.map_citations([{"text": "Bare."}], {A})

    assert references == []
    assert answer == [{"text": "Bare.", "citations": []}]


def test_the_flattened_answer_text_keeps_docid_markers(save_run_mod: Any) -> None:
    """The trajectory's ``output_text`` shows docids inline, not indices.

    That string is the human-readable record of what was answered; docids are
    readable there, whereas ``[0][1]`` would require cross-referencing the other
    artifact to interpret. Note it renders the agent's citations *as written* —
    ``map_citations`` filtering is a separate concern, asserted below.
    """
    text = save_run_mod.render_answer_text([
        {"text": "First.", "citations": [A, B]},
        {"text": "Second.", "citations": []},
    ])

    assert text == f"First. [{A}][{B}] Second."


def test_the_rendered_text_shows_a_dropped_docid_that_the_answer_hides(
        save_run_mod: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """Deliberate asymmetry: the trace keeps what the submission drops.

    ``render_answer_text`` renders the agent's citations verbatim, so a docid
    ``map_citations`` dropped still appears in the trajectory's ``output_text``
    while being absent from the submitted ``answer``. That is the desired
    behaviour — the trajectory is the forensic record of what the agent *claimed*
    — and it means the two artifacts legitimately disagree, which is worth
    stating so nobody "fixes" it into agreement.
    """
    sentences = [{"text": "Claim.", "citations": [A, GHOST]}]

    rendered = save_run_mod.render_answer_text(sentences)
    _, answer = save_run_mod.map_citations(sentences, {A})

    assert GHOST in rendered
    assert answer[0]["citations"] == [0]      # the ghost is gone from the answer


# ---------------------------------------------------------------------------
# save_run.py — main (end to end through a task dir)
# ---------------------------------------------------------------------------
def _run_main(save_run_mod: Any, monkeypatch: pytest.MonkeyPatch,
              *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["save_run.py", *argv])
    save_run_mod.main()


@pytest.fixture
def researched_task(task_dir: Path) -> Path:
    """A task dir with a plausible completed research session logged in it."""
    write_log(task_dir, [
        tool_record("search", {"query": "congestion pricing revenue", "k": 3},
                    returned=[{"docid": A, "score": 12.5},
                              {"docid": B, "score": 11.5}]),
        tool_record("get_document", {"docid": A}),
        tool_record("get_document", {"docid": GHOST}, failed=True,
                    error="RuntimeError: 404"),
    ])
    write_answer(task_dir, [
        {"text": "Revenue is dedicated to the capital plan.", "citations": [A]},
        {"text": "Traffic volumes fell below the pre-toll baseline.",
         "citations": [A, B]},
    ])
    return task_dir


def test_main_writes_both_artifacts_and_reports_no_violations(
        save_run_mod: Any, researched_task: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """The happy path an agent is told to verify: two paths + ``violations: none``.

    ``CLAUDE.md`` makes the run incomplete until this exact line is printed, so
    the string is a contract with the agent, not just a log message — an agent
    that never sees it is instructed to keep fixing and rerunning.
    """
    _run_main(save_run_mod, monkeypatch,
              "--task-dir", str(researched_task), "--qid", QID,
              "--query", QUERY,
              "--answer-json", str(researched_task / "answer_sentences.json"))

    out = capsys.readouterr().out
    assert "violations: none" in out
    assert "trajectory:" in out and "output:" in out


def test_the_saved_output_passes_the_track_validator(
        save_run_mod: Any, researched_task: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """A clean research session must produce a submittable output object.

    Asserted against ``validate_rag_output`` rather than ``main``'s printed
    summary so the artifact is checked by the same code the exporter uses,
    not by the script's own opinion of itself.
    """
    _run_main(save_run_mod, monkeypatch,
              "--task-dir", str(researched_task), "--qid", QID,
              "--query", QUERY,
              "--answer-json", str(researched_task / "answer_sentences.json"))

    out = capsys.readouterr().out
    output_path = Path([l for l in out.splitlines()
                        if l.startswith("output:")][0].split(None, 1)[1].strip())
    output = json.loads(output_path.read_text())

    assert validate_rag_output(output) == []
    assert output["references"] == [A, B]
    assert output["answer"][1]["citations"] == [0, 1]
    assert output["metadata"]["narrative_id"] == QID


def test_reasoning_notes_become_the_leading_trajectory_step(
        save_run_mod: Any, researched_task: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """``scratchpad/reasoning.md`` is embedded FIRST, before any tool call.

    It records the agent's plan, which only makes sense ahead of the calls it
    planned. This is also the only part of the agent's own thinking that reaches
    the trajectory at all — everything else is reconstructed from the tool log.
    """
    (researched_task / "scratchpad" / "reasoning.md").write_text(
        "Plan: search for revenue allocation, then fetch the best hits.",
        encoding="utf-8")

    _run_main(save_run_mod, monkeypatch,
              "--task-dir", str(researched_task), "--qid", QID,
              "--query", QUERY,
              "--answer-json", str(researched_task / "answer_sentences.json"))

    out = capsys.readouterr().out
    traj_path = Path([l for l in out.splitlines()
                      if l.startswith("trajectory:")][0].split(None, 1)[1].strip())
    trajectory = json.loads(traj_path.read_text())

    assert [i["type"] for i in trajectory["result"]] == [
        "reasoning", "tool_call", "tool_call", "tool_call", "output_text"]
    assert "Plan: search for revenue" in trajectory["result"][0]["output"]


def test_a_run_without_reasoning_notes_is_still_complete(
        save_run_mod: Any, researched_task: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """``reasoning.md`` is optional — its absence adds no step and no error.

    ``CLAUDE.md`` marks it optional, so most runs will not have one; requiring
    it would fail exactly the runs that followed the instructions. Note the
    three ``tool_call`` entries for three logged calls including the failed one:
    the strict projection records every *attempt*, and it is
    ``tool_call_counts`` (asserted elsewhere) that separates successes.
    """
    _run_main(save_run_mod, monkeypatch,
              "--task-dir", str(researched_task), "--qid", QID,
              "--query", QUERY,
              "--answer-json", str(researched_task / "answer_sentences.json"))

    out = capsys.readouterr().out
    traj_path = Path([l for l in out.splitlines()
                      if l.startswith("trajectory:")][0].split(None, 1)[1].strip())
    trajectory = json.loads(traj_path.read_text())

    assert [i["type"] for i in trajectory["result"]] == [
        "tool_call", "tool_call", "tool_call", "output_text"]


def test_an_over_long_answer_exits_non_zero_and_saves_the_violations(
        save_run_mod: Any, task_dir: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Over the 1024-word cap: artifacts are still saved, then the run fails.

    The order matters in both directions. Saving first means the agent can read
    the violations file to see what to fix; exiting non-zero is what stops it
    from treating an over-long answer as done — the cap is a hard track rule, so
    a submitted row breaching it is rejected outright.
    """
    write_log(task_dir, [
        tool_record("search", {"query": "x", "k": 1},
                    returned=[{"docid": A, "score": 1.0}])])
    write_answer(task_dir, [
        {"text": " ".join(["word"] * 1100), "citations": [A]}])

    with pytest.raises(SystemExit) as exc:
        _run_main(save_run_mod, monkeypatch,
                  "--task-dir", str(task_dir), "--qid", QID, "--query", QUERY,
                  "--answer-json", str(task_dir / "answer_sentences.json"))

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "VIOLATIONS" in captured.err
    traj_path = Path([l for l in captured.out.splitlines()
                      if l.startswith("trajectory:")][0].split(None, 1)[1].strip())
    assert list(traj_path.parent.glob("*.output.violations.json"))


def test_the_metadata_records_which_task_folder_produced_the_run(
        save_run_mod: Any, researched_task: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """``task_dir`` in the trajectory metadata is the link back to the evidence.

    Artifacts land in a shared ``data/outputs/`` directory while the tool log,
    ``answer.md`` and ``workflow.md`` stay in the task folder. Without this
    field there is no way to pair a saved run with the session that produced it.
    """
    _run_main(save_run_mod, monkeypatch,
              "--task-dir", str(researched_task), "--qid", QID,
              "--query", QUERY,
              "--answer-json", str(researched_task / "answer_sentences.json"))

    out = capsys.readouterr().out
    traj_path = Path([l for l in out.splitlines()
                      if l.startswith("trajectory:")][0].split(None, 1)[1].strip())
    metadata = json.loads(traj_path.read_text())["metadata"]

    assert metadata["task_dir"] == str(researched_task)
    assert metadata["system"] == "claude-code-research"
    assert metadata["run_id"] == "ccr.test"


def test_neither_query_nor_topics_is_an_error(
        save_run_mod: Any, researched_task: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """One of the two narrative sources is mandatory.

    Defaulting to an empty narrative would save an artifact with no topic text —
    valid, saved, and useless, discovered only at export time.
    """
    with pytest.raises(SystemExit):
        _run_main(save_run_mod, monkeypatch,
                  "--task-dir", str(researched_task), "--qid", QID,
                  "--answer-json",
                  str(researched_task / "answer_sentences.json"))


def test_topics_supplies_the_narrative_when_query_is_absent(
        save_run_mod: Any, researched_task: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """``--topics`` is the path a real topic run takes, and it must reach metadata.

    The exporter matches artifacts to the 119 official topics by
    ``narrative_id``/``narrative``; a narrative that came from anywhere but the
    topics file is how a mismatch gets into a submission.
    """
    tsv = tmp_path / "topics.tsv"
    tsv.write_text(f"{QID}\t{QUERY}\n", encoding="utf-8")

    _run_main(save_run_mod, monkeypatch,
              "--task-dir", str(researched_task), "--qid", QID,
              "--topics", str(tsv),
              "--answer-json", str(researched_task / "answer_sentences.json"))

    out = capsys.readouterr().out
    output_path = Path([l for l in out.splitlines()
                        if l.startswith("output:")][0].split(None, 1)[1].strip())

    assert json.loads(output_path.read_text())["metadata"]["narrative"] == QUERY


# ---------------------------------------------------------------------------
# The two scripts together
# ---------------------------------------------------------------------------
def test_a_log_written_by_corpus_py_is_readable_by_save_run_py(
        corpus: Any, save_run_mod: Any, task_dir: Path,
        stub_search_tool: dict[str, Any], stub_corpus_fetch: list[str],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """The real round trip — the log format is an unvalidated contract.

    Every other test here writes log records by hand, so all of them would keep
    passing if ``corpus.py``'s record shape and ``save_run.py``'s reader drifted
    apart. Nothing validates that format at runtime either: a mismatch surfaces
    as dropped citations at the end of a completed research session. This is the
    one test that would catch it.
    """
    corpus.cmd_search(_search_args(task_dir, ["congestion", "pricing"]))
    corpus.cmd_fetch(_fetch_args(task_dir, CLIMBMIX_DOCIDS[2]))
    capsys.readouterr()

    write_answer(task_dir, [
        {"text": "Grounded in a searched document.",
         "citations": [CLIMBMIX_DOCIDS[0]]},
        {"text": "Grounded in a fetched document.",
         "citations": [CLIMBMIX_DOCIDS[2]]},
    ])
    _run_main(save_run_mod, monkeypatch,
              "--task-dir", str(task_dir), "--qid", QID, "--query", QUERY,
              "--answer-json", str(task_dir / "answer_sentences.json"))

    out = capsys.readouterr().out
    assert "violations: none" in out
    output_path = Path([l for l in out.splitlines()
                        if l.startswith("output:")][0].split(None, 1)[1].strip())
    output = json.loads(output_path.read_text())

    # Both docids survived: nothing was dropped as unretrieved, which is what a
    # format drift between the two scripts would cause.
    assert output["references"] == [CLIMBMIX_DOCIDS[0], CLIMBMIX_DOCIDS[2]]
    assert [s["citations"] for s in output["answer"]] == [[0], [1]]


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------
@pytest.mark.live
def test_corpus_py_search_and_fetch_against_the_real_backends(
        corpus: Any, task_dir: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """The real retrieval path: hosted search, then a fetch of what it returned.

    Everything above stubs both backends, so only this proves what the agent
    actually depends on — that the configured search endpoint answers, that its
    top docid is fetchable, and that both calls land in the log with the fields
    ``save_run.py`` reads. Fetching a docid *from the search result* is the point:
    it checks the two backends agree on ids, which no stub can.

    Needs ``SEARCH_API_KEY`` (and whatever endpoint env the search tool uses).
    """
    import os

    if not os.environ.get("SEARCH_API_KEY"):
        pytest.skip("needs SEARCH_API_KEY for the hosted ClimbMix endpoints")

    assert corpus.cmd_search(_search_args(
        task_dir, ["congestion", "pricing", "revenue"], k=3)) == 0
    search_record, = log_records(task_dir)
    assert search_record["returned"], "live search returned no hits"
    top_docid = search_record["returned"][0]["docid"]

    assert corpus.cmd_fetch(_fetch_args(task_dir, top_docid)) == 0
    fetch_record = log_records(task_dir)[1]
    assert fetch_record["tool_name"] == "get_document"
    assert fetch_record["output_head"], "live fetch returned empty text"
