"""Contract: the strict trajectory artifact and the strict/rich split.

``trajectory.json`` is not a track-mandated file, but it is the artifact the
organizers' reference sample defines (see ``ragrun.trajectory``'s docstring:
schema-compatible with ``run_InfoSeekQA_1000_*.json``), and it is the one place
where our own diagnostics could plausibly leak into a submitted-alongside file.
So the invariant this module defends is the *split*:

- the strict projection carries only sample-compatible fields;
- everything we added for the outputs viewer — timings, token stats, span tree,
  staged context, document lists — lives in ``TrajectoryArtifact.trace``, which
  ``save_run`` embeds into ``output.json`` and nowhere else.

Both halves are recorded by the same ``add_*`` call, so a refactor that forgot to
strip one field would produce a plausible-looking artifact with viewer internals
in it. The `assert "trace" not in dict(trajectory)` test below is the cheap
tripwire for exactly that; the field-partition tests are the thorough version.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from ragrun import TrajectoryBuilder, build_rag_output, save_run
from ragrun.outputs import run_artifact_paths, run_timestamp
from ragrun.trajectory import TRACE_SCHEMA_VERSION

from conftest import CLIMBMIX_DOCIDS

pytestmark = pytest.mark.contract

# The sample-compatible top-level key set, in order.
STRICT_TOP_LEVEL = ("metadata", "query_id", "tool_call_counts",
                    "tool_call_counts_all", "status", "retrieved_docids",
                    "result", "raw_messages")

# Fields that exist only to serve the outputs viewer / analysis.
RICH_ONLY_FIELDS = ("t_start", "t_end", "turn", "stats", "id", "parent_id",
                    "documents", "context", "failed", "tool_call_id")

T0 = "2026-07-28T10:00:00.000+10:00"
T1 = "2026-07-28T10:00:01.500+10:00"


def build_trajectory() -> Any:
    """A representative finished trajectory: reasoning, a generation span, one
    successful + one failed tool call, and the final answer text.

    Built with the REAL builder so every assertion below is about production
    behaviour; every rich-only knob is exercised so the partition tests have
    something to find if the split ever breaks.
    """
    builder = TrajectoryBuilder(
        "rag2026-37", "congestion pricing MTA funding",
        {"run_id": "contract-run", "model": "scripted/test-model"})
    builder.set_trace_input({"query": "congestion pricing MTA funding",
                             "engines": ["semantic"]})
    builder.add_reasoning("I should search for the revenue mechanism first.",
                          t_start=T0, t_end=T1, turn=1)
    builder.add_model_step("planning", turn=1,
                           stats={"tokens": {"input": 120, "output": 40}})
    builder.add_tool_call(
        "search", {"query": "congestion pricing revenue", "k": 3},
        '{"results": [...]}',
        returned=[{"docid": CLIMBMIX_DOCIDS[1]}, {"docid": CLIMBMIX_DOCIDS[0]},
                  {"docid": CLIMBMIX_DOCIDS[0]}],
        turn=1, t_start=T0, t_end=T1, k=3,
        documents=[{"docid": CLIMBMIX_DOCIDS[1]}],
        tool_call_id="call_search_1")
    builder.add_tool_call(
        "search", {"query": "(^ a b c d e)", "k": 3},
        '{"error": "empty result set"}', failed=True, turn=1)
    builder.add_output_text("Toll revenue is dedicated to the capital plan.",
                            turn=2)
    builder.set_trace_output({"references": [CLIMBMIX_DOCIDS[0]]})
    return builder.finalize("completed", raw_messages=[
        {"role": "system", "content": "..."},
        {"role": "user", "content": "congestion pricing MTA funding"}],
        started_at=T0, ended_at=T1)


def make_output() -> dict[str, Any]:
    return build_rag_output(
        narrative_id="rag2026-37",
        narrative="Can you help me understand congestion pricing?",
        run_id="contract-run", run_desc="contract fixture run",
        references=[CLIMBMIX_DOCIDS[0]],
        answer=[{"text": "Toll revenue is dedicated to the capital plan.",
                 "citations": [0]}])


# ---------------------------------------------------------------------------
# Strict top-level schema
# ---------------------------------------------------------------------------
def test_finalize_top_level_keys_exactly() -> None:
    """The sample-compatible key set — asserted as an ordered tuple.

    Order matters only cosmetically (a human diffing our artifact against the
    sample), but key *identity* is the schema contract, so this is an equality on
    both.
    """
    trajectory = build_trajectory()

    assert tuple(trajectory) == STRICT_TOP_LEVEL


def test_finalize_scalar_fields() -> None:
    """``query_id`` must be the topic id, verbatim, and the query text must be
    recoverable from the artifact.

    ``query_id`` is the join key between ``trajectory.json`` and the submitted
    ``metadata.narrative_id``: an analysis that pairs a run with its topic (or an
    organizer spot-checking a trajectory against a submitted answer) matches on it,
    so a normalized or synthesized id makes the artifact unmatchable. The query
    text is carried as ``metadata.query_source`` rather than a top-level field —
    the reference sample has no query field, so the builder tucks it into metadata.
    """
    trajectory = build_trajectory()

    assert trajectory["query_id"] == "rag2026-37"
    assert trajectory["status"] == "completed"
    assert trajectory["metadata"]["run_id"] == "contract-run"
    # The query text is preserved as metadata.query_source (set by the builder).
    assert trajectory["metadata"]["query_source"] == \
        "congestion pricing MTA funding"
    assert len(trajectory["raw_messages"]) == 2


@pytest.mark.parametrize("status", ["completed", "max_turns", "error"])
def test_finalize_passes_status_through(status: str) -> None:
    """``status`` records how the run ended, is never normalized to success, and is
    caller-supplied free text rather than a validated enum.

    The two non-``completed`` values are the ones that matter: a ``max_turns`` or
    ``error`` trajectory still has usable partial retrieval, so it is written rather
    than discarded, and ``status`` is then the only field distinguishing it from a
    clean run when triaging a batch. Because the builder does not constrain the
    vocabulary, systems must agree on these strings by convention — if a system
    invented ``"failed"`` instead of ``"error"``, nothing here would complain and a
    sweep filtering on status would quietly miss those runs.
    """
    builder = TrajectoryBuilder("q", "query")
    builder.add_output_text("text")

    assert builder.finalize(status)["status"] == status


def test_finalize_is_json_serializable_without_the_trace() -> None:
    """``json.dumps(dict(trajectory))`` is what ``save_run`` writes."""
    trajectory = build_trajectory()

    reloaded = json.loads(json.dumps(dict(trajectory), ensure_ascii=False))

    assert tuple(reloaded) == STRICT_TOP_LEVEL


# ---------------------------------------------------------------------------
# CRITICAL: the rich trace must never leak into the strict trajectory
# ---------------------------------------------------------------------------
def test_trace_is_not_a_trajectory_key() -> None:
    """The tripwire. ``TrajectoryArtifact`` carries ``trace`` as an *attribute*,
    deliberately not as a dict item, so serializing the trajectory cannot emit it.
    """
    trajectory = build_trajectory()

    assert "trace" not in dict(trajectory)
    assert "trace" not in json.dumps(dict(trajectory))
    assert trajectory.trace["schema_version"] == TRACE_SCHEMA_VERSION


@pytest.mark.parametrize("field", RICH_ONLY_FIELDS)
def test_rich_only_fields_never_appear_in_strict_result(field: str) -> None:
    """Viewer-only fields appear in ``trace.steps`` and ONLY there.

    Asserted per field so a regression names the offending key, and asserted in
    both directions: absent from every strict item, present on at least one rich
    step (otherwise the test would pass vacuously after a rename).
    """
    trajectory = build_trajectory()

    assert all(field not in item for item in trajectory["result"]), \
        f"rich-only field {field!r} leaked into trajectory.result"
    assert any(field in step for step in trajectory.trace["steps"]), \
        f"rich-only field {field!r} is not recorded in trace.steps either"


def test_strict_result_item_keys_are_the_documented_set() -> None:
    """Strict items carry ``type``/``tool_name``/``arguments``/``output`` plus the
    documented tool extras (``returned_docids``, ``returned``, and tool-specific
    keys like ``k`` that the reference sample itself uses)."""
    trajectory = build_trajectory()
    core = {"type", "tool_name", "arguments", "output"}
    allowed = core | {"returned_docids", "returned", "k"}

    for item in trajectory["result"]:
        assert core <= set(item)
        assert set(item) <= allowed, f"unexpected strict keys: {set(item) - allowed}"


def test_strict_result_types_and_order() -> None:
    """One strict item per non-generation event, in call order.

    ``add_model_step`` is rich-only by design (it exists to account for model
    latency/tokens when a provider returns signature-only reasoning), so it must
    NOT add a strict item — the count difference below is the assertion.
    """
    trajectory = build_trajectory()

    assert [item["type"] for item in trajectory["result"]] == [
        "reasoning", "tool_call", "tool_call", "output_text"]
    assert [step["type"] for step in trajectory.trace["steps"]] == [
        "reasoning", "generation", "tool_call", "tool_call", "output_text"]


def test_generation_span_is_rich_only() -> None:
    """A ``generation`` span must add NOTHING to ``result`` — the strict/rich split
    at its sharpest.

    ``add_model_step`` exists purely to account for model latency and token usage
    when a provider returns signature-only reasoning (no text to record as a
    ``reasoning`` item). The reference sample
    (``run_InfoSeekQA_1000_*.json``) has no ``generation`` item type, so a
    ``generation`` leaking into ``result`` would produce a ``trajectory.json`` that
    is locally plausible — it still serializes, still validates, still renders —
    but no longer schema-compatible with the sample our artifact is defined
    against. That is the failure mode this asserts against, and it is invisible
    without the check because nothing else in the pipeline reads item ``type``.
    """
    builder = TrajectoryBuilder("q", "query")
    step_id = builder.add_model_step("planning", turn=1)
    trajectory = builder.finalize("completed")

    assert trajectory["result"] == []
    assert [s["id"] for s in trajectory.trace["steps"]] == [step_id]


def test_reasoning_and_output_text_have_null_tool_fields() -> None:
    """Non-tool items keep the sample's explicit ``null`` tool_name/arguments
    rather than omitting the keys."""
    trajectory = build_trajectory()

    for item in trajectory["result"]:
        if item["type"] in ("reasoning", "output_text"):
            assert item["tool_name"] is None
            assert item["arguments"] is None


def test_empty_reasoning_is_dropped() -> None:
    """An empty reasoning block is dropped from BOTH projections, not recorded as
    an empty-string item.

    Providers routinely emit empty or whitespace-only reasoning (a signature-only
    thinking block, or a turn that went straight to a tool call), so without the
    guard in ``add_reasoning`` a normal run would accumulate ``{"type":
    "reasoning", "output": ""}`` padding in ``result`` — noise in an artifact whose
    whole purpose is to show what the agent actually did, and step-count inflation
    in any analysis that measures reasoning steps per run.
    """
    builder = TrajectoryBuilder("q", "query")
    builder.add_reasoning("")

    trajectory = builder.finalize("completed")

    assert trajectory["result"] == []
    assert trajectory.trace["steps"] == []


def test_record_trace_false_keeps_the_strict_item_only() -> None:
    """``record_trace=False`` is the inverse leak direction: an item that must be
    in the strict artifact but not in the viewer's span tree."""
    builder = TrajectoryBuilder("q", "query")
    builder.add_reasoning("strict only", record_trace=False)
    assert builder.add_output_text("strict only", record_trace=False) is None

    trajectory = builder.finalize("completed")

    assert [item["type"] for item in trajectory["result"]] == [
        "reasoning", "output_text"]
    assert trajectory.trace["steps"] == []


# ---------------------------------------------------------------------------
# arguments encoding: JSON string (strict) vs structured object (trace)
# ---------------------------------------------------------------------------
def test_arguments_is_a_json_string_in_strict_and_an_object_in_trace() -> None:
    """The sample encodes tool arguments as a JSON *string*; the viewer wants the
    object. Both come from the same ``add_tool_call`` argument."""
    trajectory = build_trajectory()
    strict = trajectory["result"][1]
    rich = trajectory.trace["steps"][2]

    assert isinstance(strict["arguments"], str)
    assert json.loads(strict["arguments"]) == {
        "query": "congestion pricing revenue", "k": 3}
    assert isinstance(rich["arguments"], dict)
    assert rich["arguments"] == {"query": "congestion pricing revenue", "k": 3}


def test_string_arguments_are_not_double_encoded() -> None:
    """A caller that already has the provider's raw JSON string passes it through
    untouched — otherwise the strict field would be a JSON string of a JSON string.
    """
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("search", '{"query": "x"}', "out")

    trajectory = builder.finalize("completed")

    assert trajectory["result"][0]["arguments"] == '{"query": "x"}'
    assert json.loads(trajectory["result"][0]["arguments"]) == {"query": "x"}


def test_arguments_encoding_keeps_unicode_literal() -> None:
    """``arguments`` is encoded with ``ensure_ascii=False``, matching ``save_run``.

    Non-ASCII query terms are routine (a topic about *café* closures, an accented
    place name, a curly apostrophe copied out of a narrative). Escaping them to
    ``\\u00e9`` would be equally valid JSON but changes the artifact's bytes without
    changing its meaning: the viewer shows escapes instead of the query the agent
    actually ran, and a diff between two runs lights up on encoding rather than on
    behaviour. The strict field is a JSON *string*, so this is the one place where
    the escaping choice is baked into a value rather than into the file writer —
    ``json.dumps`` is called inside ``add_tool_call``, not by ``save_run``. The
    ``json.loads`` half of the assertion pins that readability did not cost
    correctness: the value still parses back to the original string.
    """
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("search", {"query": "café ’25"}, "out")

    encoded = builder.finalize("completed")["result"][0]["arguments"]

    assert "café" in encoded                       # ensure_ascii=False
    assert json.loads(encoded)["query"] == "café ’25"


def test_trace_output_override_does_not_change_strict_output() -> None:
    """``trace_output`` lets the viewer show a structured payload while the strict
    artifact (and the model transcript) keeps the literal tool string."""
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("search", {"query": "x"}, '{"results": []}',
                          trace_output={"results": []})

    trajectory = builder.finalize("completed")

    assert trajectory["result"][0]["output"] == '{"results": []}'
    assert trajectory.trace["steps"][0]["output"] == {"results": []}


# ---------------------------------------------------------------------------
# Counts and retrieved docids
# ---------------------------------------------------------------------------
def test_tool_call_counts_exclude_failed_calls() -> None:
    """``tool_call_counts`` = successful calls; ``tool_call_counts_all`` = every
    attempt. The pair is how a run's error rate is read off the artifact."""
    trajectory = build_trajectory()

    assert trajectory["tool_call_counts"] == {"search": 1}
    assert trajectory["tool_call_counts_all"] == {"search": 2}


def test_tool_call_counts_are_per_tool_name() -> None:
    """Counts are keyed by tool name, and a tool whose only call failed still
    appears in ``tool_call_counts_all`` while being absent from
    ``tool_call_counts``.

    The asymmetry is the point: ``fetch_doc`` here has one attempt and zero
    successes, so it is a key in one dict and missing from the other. A reader
    computing a per-tool error rate must therefore treat a missing key in
    ``tool_call_counts`` as zero rather than as "tool unused" — if the builder
    instead emitted ``{"fetch_doc": 0}``, every such consumer would keep working,
    which is why the shape needs pinning rather than merely documenting.
    """
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("search", {}, "o")
    builder.add_tool_call("search", {}, "o")
    builder.add_tool_call("fetch_doc", {}, "o", failed=True)

    trajectory = builder.finalize("completed")

    assert trajectory["tool_call_counts"] == {"search": 2}
    assert trajectory["tool_call_counts_all"] == {"search": 2, "fetch_doc": 1}


def test_counts_are_mirrored_in_the_trace_summary() -> None:
    """The same three aggregates are computed once and written to both artifacts.

    ``trajectory.json`` puts them at top level (sample compatibility) while
    ``output.json.trace.summary`` repeats them for the viewer, which never reads
    the trajectory file. Duplicated data is duplicated opportunity to disagree: if
    ``finalize`` ever recomputed the trace copy from a different pass over
    ``trace_steps``, the two files would silently diverge and there would be no
    way to tell which one a worklog's numbers came from. Asserting equality (not
    just presence) makes them one source of truth.
    """
    trajectory = build_trajectory()

    assert trajectory.trace["summary"]["tool_call_counts"] == \
        trajectory["tool_call_counts"]
    assert trajectory.trace["summary"]["tool_call_counts_all"] == \
        trajectory["tool_call_counts_all"]
    assert trajectory.trace["summary"]["retrieved_docids"] == \
        trajectory["retrieved_docids"]


def test_retrieved_docids_are_sorted_and_deduplicated() -> None:
    """The run-level docid set is normalized even though each call's
    ``returned_docids`` keeps its own rank order and duplicates."""
    trajectory = build_trajectory()

    assert trajectory["retrieved_docids"] == sorted(
        {CLIMBMIX_DOCIDS[0], CLIMBMIX_DOCIDS[1]})
    # Per-call order/duplicates are preserved (rank order is information).
    assert trajectory["result"][1]["returned_docids"] == [
        CLIMBMIX_DOCIDS[1], CLIMBMIX_DOCIDS[0], CLIMBMIX_DOCIDS[0]]


def test_retrieved_docids_accumulate_across_calls() -> None:
    """The union across every call, with the overlap counted once — not per-call,
    not insertion-ordered.

    ``retrieved_docids`` is the run's answer to "what evidence was this system
    ever allowed to cite" — the pool that ``references`` must be a subset of, and
    the denominator for any recall figure computed from a run. ``a`` is returned by
    both calls here and must appear once, and the sort means two runs that
    retrieved the same set produce byte-identical artifacts regardless of the order
    the searches happened to fire. Multi-facet systems
    (facet_rag issues one search per facet) routinely return the same strong
    document for several facets, so per-call accumulation has to be set union: a
    list-extend would inflate the pool size and make that recall figure wrong,
    while overwriting per call would lose all but the last facet's evidence.
    """
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("search", {}, "o", returned_docids=["b", "a"])
    builder.add_tool_call("search", {}, "o", returned_docids=["c", "a"])

    assert builder.finalize("completed")["retrieved_docids"] == ["a", "b", "c"]


def test_failed_call_docids_still_count_as_retrieved_current_behaviour() -> None:
    """CURRENT BEHAVIOUR: ``returned_docids`` from a call marked ``failed=True``
    are still merged into ``retrieved_docids``.

    In practice a failed call returns nothing, so the set is unaffected; the note
    is here because "retrieved" is otherwise read as "successfully retrieved".
    """
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("search", {}, "o", returned_docids=["z"], failed=True)

    trajectory = builder.finalize("completed")

    assert trajectory["retrieved_docids"] == ["z"]
    assert trajectory["tool_call_counts"] == {}


def test_returned_docids_are_derived_from_returned_hits() -> None:
    """A caller passing hits does not also have to pass the docid list."""
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("search", {}, "o",
                          returned=[{"docid": "a"}, {"docid": "b"}])

    trajectory = builder.finalize("completed")

    assert trajectory["result"][0]["returned_docids"] == ["a", "b"]


def test_tool_call_without_returned_omits_both_fields() -> None:
    """A non-retrieval tool must not gain empty ``returned``/``returned_docids``
    keys — the sample only has them on search-like calls."""
    builder = TrajectoryBuilder("q", "query")
    builder.add_tool_call("finish", {"reason": "done"}, "ok")

    item = builder.finalize("completed")["result"][0]

    assert "returned" not in item and "returned_docids" not in item


# ---------------------------------------------------------------------------
# Rich trace envelope (asserted here because save_run embeds it in output.json)
# ---------------------------------------------------------------------------
def test_trace_envelope_keys() -> None:
    """The rich trace's own top-level schema, pinned here because ``save_run``
    embeds it into ``output.json`` where the outputs viewer reads it.

    Asserted as an exact key set for the same reason the strict projection is: the
    viewer indexes these names directly, so a rename is a silently blank panel
    rather than an error. Three of them are conditional in ``finalize`` and so are
    the real content of this test — ``output`` only appears after
    ``set_trace_output``, and ``started_at``/``ended_at``/``duration_ms`` only when
    the caller passed both timestamps (``duration_ms`` is derived, and is dropped
    entirely if the clock went backwards). ``schema_version`` is what lets the
    viewer tell a v2 trace from a future v3 one.
    """
    trajectory = build_trajectory()

    assert set(trajectory.trace) == {
        "schema_version", "query_id", "status", "metadata", "summary", "input",
        "steps", "output", "started_at", "ended_at", "duration_ms"}
    assert trajectory.trace["duration_ms"] == 1500
    assert trajectory.trace["input"]["engines"] == ["semantic"]
    assert trajectory.trace["output"] == {"references": [CLIMBMIX_DOCIDS[0]]}


def test_trace_step_ids_are_sequential_and_parented() -> None:
    """Step ids are positional (``step-NNNN``) and the tool calls of a turn hang
    off that turn's generation span — the viewer's tree structure."""
    trajectory = build_trajectory()
    steps = trajectory.trace["steps"]

    assert [s["id"] for s in steps] == [f"step-{i:04d}" for i in range(len(steps))]
    generation = next(s for s in steps if s["type"] == "generation")
    assert generation["parent_id"] == "run"
    assert [s["parent_id"] for s in steps if s["type"] == "tool_call"] == \
        [generation["id"], generation["id"]]


def test_trace_metadata_is_a_copy_not_an_alias() -> None:
    """Mutating the strict metadata must not silently edit the trace's copy."""
    trajectory = build_trajectory()

    trajectory["metadata"]["run_id"] = "mutated"

    assert trajectory.trace["metadata"]["run_id"] == "contract-run"


# ---------------------------------------------------------------------------
# save_run: what actually lands on disk
# ---------------------------------------------------------------------------
def test_save_run_writes_both_artifacts_and_no_violations_file(
        read_artifacts: Callable[[dict[str, Path]], dict[str, Any]]) -> None:
    """A clean run writes exactly two files.

    The absence of ``*.violations.json`` is the signal a human uses to triage a
    directory of runs, so "no violations file" is asserted directly rather than
    inferred from an empty list.
    """
    trajectory = build_trajectory()
    ts = run_timestamp()

    written = save_run("contract_system", "congestion pricing MTA funding",
                       trajectory=trajectory, output=make_output(), timestamp=ts)

    assert set(written) == {"trajectory", "output"}
    paths = run_artifact_paths("contract_system",
                               "congestion pricing MTA funding", ts)
    assert paths["trajectory"].exists() and paths["output"].exists()
    assert not paths["violations"].exists()

    artifacts = read_artifacts(paths)
    assert artifacts["violations"] == []
    assert tuple(artifacts["trajectory"]) == STRICT_TOP_LEVEL


def test_save_run_embeds_the_trace_in_output_only(
        read_artifacts: Callable[[dict[str, Path]], dict[str, Any]]) -> None:
    """The split, enforced on disk: ``output.json`` has ``trace``,
    ``trajectory.json`` does not."""
    trajectory = build_trajectory()
    ts = run_timestamp()
    paths = save_run("contract_system", "query text", trajectory=trajectory,
                     output=make_output(), timestamp=ts)
    artifacts = read_artifacts(run_artifact_paths("contract_system",
                                                  "query text", ts))

    assert "trace" in artifacts["output"]
    assert artifacts["output"]["trace"]["schema_version"] == TRACE_SCHEMA_VERSION
    assert "trace" not in artifacts["trajectory"]
    assert "trace" not in paths["trajectory"].read_text()

    # And the rich-only fields are on the trace steps in the written file.
    step_keys = set().union(*(set(s) for s in
                              artifacts["output"]["trace"]["steps"]))
    assert {"id", "parent_id", "t_start", "stats"} <= step_keys


def test_save_run_writes_violations_file_when_the_output_is_invalid(
        read_artifacts: Callable[[dict[str, Path]], dict[str, Any]]) -> None:
    """An invalid output is still saved (visibility over hard failure) with the
    violation list alongside it."""
    output = make_output()
    output["references"] = list(CLIMBMIX_DOCIDS[:2])      # index 1 now uncited
    ts = run_timestamp()

    written = save_run("contract_system", "query text",
                       trajectory=build_trajectory(), output=output,
                       timestamp=ts)

    assert set(written) == {"trajectory", "output", "violations"}
    artifacts = read_artifacts(run_artifact_paths("contract_system",
                                                  "query text", ts))
    assert artifacts["violations"] == ["references never cited: indices [1]"]
    assert artifacts["output"]["references"] == list(CLIMBMIX_DOCIDS[:2])


def test_save_run_partial_mode_skips_trajectory_and_validation() -> None:
    """The in-flight write path: only ``output.json``, no premature violations
    file for an answer that is not finished yet."""
    ts = run_timestamp()
    output = make_output()
    output["answer"] = []                                 # would be invalid

    written = save_run("contract_system", "query text",
                       trajectory=build_trajectory(), output=output,
                       timestamp=ts, validate=False, write_trajectory=False)
    paths = run_artifact_paths("contract_system", "query text", ts)

    assert set(written) == {"output"}
    assert paths["output"].exists()
    assert not paths["trajectory"].exists()
    assert not paths["violations"].exists()


def test_save_run_repeated_saves_land_on_the_same_files() -> None:
    """A pinned timestamp makes incremental saves idempotent in path terms — the
    outputs viewer polls one stable filename per run."""
    ts = run_timestamp()
    first = save_run("contract_system", "query text",
                     trajectory=build_trajectory(), output=make_output(),
                     timestamp=ts, validate=False, write_trajectory=False)
    second = save_run("contract_system", "query text",
                      trajectory=build_trajectory(), output=make_output(),
                      timestamp=ts)

    assert first["output"] == second["output"]
    assert len(list(second["output"].parent.glob("*.json"))) == 2


def test_run_artifact_paths_layout() -> None:
    """``data/outputs/<system>/<ts>.<slug>.<kind>.json`` — the slug is derived
    from the query so a directory listing is readable."""
    ts = "20260728T100000000000+1000"
    paths = run_artifact_paths("contract_system",
                               "Congestion pricing: fair way to fund the MTA?",
                               ts)

    assert paths["output"].parent.name == "contract_system"
    assert paths["output"].parent.parent.name == "outputs"
    assert paths["output"].name == \
        f"{ts}.congestion_pricing_fair_way_to.output.json"
    assert paths["trajectory"].name == \
        f"{ts}.congestion_pricing_fair_way_to.trajectory.json"
    assert paths["violations"].name == \
        f"{ts}.congestion_pricing_fair_way_to.output.violations.json"


def test_save_run_output_is_still_submission_projectable(
        read_artifacts: Callable[[dict[str, Path]], dict[str, Any]]) -> None:
    """The saved (trace-carrying) output projects cleanly to the submission form —
    i.e. embedding the trace does not disturb the spec fields."""
    from ragrun import submission_output, validate_rag_output

    ts = run_timestamp()
    save_run("contract_system", "query text", trajectory=build_trajectory(),
             output=make_output(), timestamp=ts)
    saved = read_artifacts(run_artifact_paths("contract_system", "query text",
                                              ts))["output"]

    projected = submission_output(saved)

    assert set(projected) == {"metadata", "references", "answer"}
    assert validate_rag_output(projected) == []
