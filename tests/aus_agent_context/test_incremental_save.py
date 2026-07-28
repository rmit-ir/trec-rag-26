"""Live-progress artifacts: a run rewrites ``output.json`` while it is still going.

The outputs viewer polls a run's ``output.json`` so a long run can be watched as
it happens. That turns saving into a concurrency problem the rest of the harness
does not have, and the guarantees it needs are asserted here:

- a partial is on disk **before** the first model turn, marked ``running``, and
  every later write lands on the SAME path (so the viewer's URL stays valid);
- a partial never writes the trajectory (~1.2 MB and growing) and never
  validates (an unfinished answer would leave a misleading violations file);
- writes are throttled, so a step-heavy run does not spend its I/O budget on
  progress reporting;
- ``atomic_write_text`` gives the poller old-or-new, never a truncated file, and
  leaves no ``.tmp`` debris.

Scope note: ``atomic_write_text`` lives in ``src/ragrun/outputs.py``, not in
``aus_agent``. It is tested here because ``aus_agent`` is its only partial-write
caller and these assertions came from that loop's suite;
``tests/contract/test_output_trajectory.py`` covers ``save_run``'s artifact
shape. Nothing here needs credentials or a network — the run is driven by a
scripted provider and writes under the autouse ``isolated_data_dir`` tmp tree.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

from aus_agent_context.fakes import StrictScriptedProvider, call, turn

from ragrun import outputs as ragrun_outputs

# One search, one commit, one cited report — the shortest run that produces a
# real trajectory, so the assertions are about saving rather than about content.
SAVE_SCRIPT = [
    turn(text="Searching.", calls=[call("s1", "search", query="alpha")]),
    turn(calls=[call("c1", "commit_context", documents=[
        {"docid": "b", "reason": "direct alpha evidence"}])]),
    turn(text="Supported finding. [b]"),
]


@pytest.fixture
def run_to_disk(monkeypatch: pytest.MonkeyPatch,
                fake_engine: dict[str, list[dict]],
                isolated_data_dir: Path) -> Callable[..., dict[str, Any]]:
    """Run ``agent.run_agent`` for real, letting ``save_run`` write to tmp.

    The sibling ``run_agent_capture`` fixture intercepts ``save_run`` because its
    tests assert on in-memory objects; this module's subject IS the on-disk
    behaviour, so only the provider is substituted.
    """
    from aus_agent import agent

    def _run(provider: Any, **kwargs: Any) -> dict[str, Any]:
        monkeypatch.setattr(agent, "make_provider", lambda *a, **kw: provider)
        summary = agent.run_agent("qid", "research query", **{
            "context_token_budget": 10_000,
            "safety_max_rounds": 20,
            "max_committed_per_step": 3,
            **kwargs,
        })
        return summary

    return _run


@pytest.fixture
def out_dir(isolated_data_dir: Path) -> Path:
    """The directory ``save_run`` writes this system's artifacts into."""
    return isolated_data_dir / "outputs" / "aus_agent"


# ---------------------------------------------------------------------------
# Partial saves
# ---------------------------------------------------------------------------
def test_a_partial_exists_before_the_first_turn_and_shares_the_final_path(
        run_to_disk, out_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The viewer must find a readable artifact from the very first second.

    A model turn takes tens of seconds, so a run that only wrote at the end would
    be invisible for minutes. Every partial and the final save target ONE path,
    so a link opened while the run is in flight keeps working after it finishes —
    and each partial is complete JSON, readable at any instant.
    """
    from aus_agent import agent

    provider = StrictScriptedProvider(list(SAVE_SCRIPT))
    seen: list[dict[str, Any]] = []
    base_run_turn = provider.run_turn

    def probe() -> dict[str, Any]:
        for path in sorted(out_dir.glob("*.output.json")):
            seen.append({
                "path": path,
                "data": json.loads(path.read_text(encoding="utf-8")),
                "siblings": sorted(p.name for p in out_dir.iterdir()),
            })
        return base_run_turn()

    monkeypatch.setattr(provider, "run_turn", probe)
    monkeypatch.setattr(agent, "PARTIAL_SAVE_MIN_INTERVAL_S", 0.0)
    summary = run_to_disk(provider)

    assert seen, "no partial existed before the first model turn"
    for snapshot in seen:
        assert snapshot["data"]["trace"]["status"] == "running"

    outputs = sorted(out_dir.glob("*.output.json"))
    assert len(outputs) == 1
    assert {s["path"] for s in seen} == set(outputs)
    assert summary["paths"]["output"] == outputs[0]

    final = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert final["trace"]["status"] == "completed"
    assert final["references"] == ["b"]
    assert ragrun_outputs.validate_rag_output(final) == []


def test_a_partial_writes_neither_the_trajectory_nor_a_violations_file(
        run_to_disk, out_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Partial mode is deliberately narrower than a real save, in two ways.

    The trajectory carries the full provider message history (~1.2 MB and
    growing), and the viewer never reads it — rewriting it every couple of
    seconds would be pure cost. Validation is off because an unfinished run has
    no answer, so validating would drop a violations file next to a run that is
    going to be perfectly valid.
    """
    from aus_agent import agent

    provider = StrictScriptedProvider(list(SAVE_SCRIPT))
    seen: list[list[str]] = []
    base_run_turn = provider.run_turn

    def probe() -> dict[str, Any]:
        seen.append(sorted(p.name for p in out_dir.iterdir()))
        return base_run_turn()

    monkeypatch.setattr(provider, "run_turn", probe)
    monkeypatch.setattr(agent, "PARTIAL_SAVE_MIN_INTERVAL_S", 0.0)
    summary = run_to_disk(provider)

    for siblings in seen:
        assert [n for n in siblings if n.endswith(".violations.json")] == []
        assert [n for n in siblings if n.endswith(".trajectory.json")] == []
    # The FINAL save is the one that writes it.
    assert summary["paths"]["trajectory"].exists()


def test_partial_saves_are_throttled_and_the_final_save_always_lands(
        run_to_disk, monkeypatch: pytest.MonkeyPatch) -> None:
    """Throttling bounds progress I/O; the two forced writes are never skipped.

    A trace grows to ~1 MB, and no human reads a viewer faster than the interval,
    so an unthrottled rewrite on every step is cost for no benefit. The throttle
    must not be able to swallow the two saves that matter: the one before the
    first turn (so the run is visible at all) and the final one (the artifact
    itself).
    """
    from aus_agent import agent

    writes: list[str] = []
    real_atomic = ragrun_outputs.atomic_write_text

    def counting(path: Path, text: str) -> None:
        if path.name.endswith(".output.json"):
            writes.append(path.name)
        real_atomic(path, text)

    monkeypatch.setattr(ragrun_outputs, "atomic_write_text", counting)

    # A window longer than the run leaves only the two forced saves.
    monkeypatch.setattr(agent, "PARTIAL_SAVE_MIN_INTERVAL_S", 3600.0)
    summary = run_to_disk(StrictScriptedProvider(list(SAVE_SCRIPT)))
    assert len(writes) == 2
    assert summary["status"] == "completed"

    writes.clear()
    monkeypatch.setattr(agent, "PARTIAL_SAVE_MIN_INTERVAL_S", 0.0)
    run_to_disk(StrictScriptedProvider(list(SAVE_SCRIPT)))
    assert len(writes) > 2


def test_a_failed_run_still_saves_once_with_status_failed(
        run_to_disk, out_dir: Path) -> None:
    """A crashed run must leave a readable artifact, not a ``running`` one.

    ``running`` is the status that hides an artifact from ``--skip-existing`` and
    from the submission exporter, so a failed run stuck at ``running`` would be
    silently retried forever by a batch driver. One file, terminal status.
    """
    summary = run_to_disk(StrictScriptedProvider([]))  # exhausts immediately

    assert summary["status"] == "failed"
    outputs = sorted(out_dir.glob("*.output.json"))
    assert len(outputs) == 1
    final = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert final["trace"]["status"] == "failed"


def test_a_completed_run_leaves_no_temp_files_behind(
        run_to_disk, out_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated atomic writes must not accumulate debris in the output dir.

    ``atomic_write_text`` writes its temp file into the TARGET directory (so
    ``os.replace`` stays on one filesystem and is therefore atomic), which puts
    every leaked temp file right where the viewer globs for artifacts. A run does
    dozens of these, so a single unclean path leaks dozens of files.
    """
    from aus_agent import agent

    monkeypatch.setattr(agent, "PARTIAL_SAVE_MIN_INTERVAL_S", 0.0)
    run_to_disk(StrictScriptedProvider(list(SAVE_SCRIPT)))

    leftovers = [p.name for p in out_dir.iterdir()
                 if p.name.endswith(".tmp") or p.name.startswith(".")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# atomic_write_text
# ---------------------------------------------------------------------------
@pytest.fixture
def existing_artifact(tmp_path: Path) -> Path:
    """A file already holding a complete JSON document, to be overwritten."""
    path = tmp_path / "output.json"
    path.write_text('{"old": true}', encoding="utf-8")
    return path


def test_atomic_write_keeps_the_umask_default_mode(
        tmp_path: Path, existing_artifact: Path) -> None:
    """The temp-file dance must not narrow an artifact to owner-only.

    ``mkstemp`` creates 0600 and ``os.replace`` keeps the temp file's mode, so the
    naive version of this function silently made every artifact unreadable to
    other accounts — including the viewer server, which runs as its own user. The
    old ``Path.write_text`` left them at the umask default, and that has to be
    preserved on a create AND on an overwrite (the second is easy to miss,
    because the existing file's mode is discarded along with the file).
    """
    reference = tmp_path / "reference.json"
    reference.write_text("{}")
    expected = reference.stat().st_mode & 0o777

    created = tmp_path / "created.json"
    ragrun_outputs.atomic_write_text(created, "{}")
    assert created.stat().st_mode & 0o777 == expected

    ragrun_outputs.atomic_write_text(existing_artifact, '{"second": true}')
    assert existing_artifact.stat().st_mode & 0o777 == expected


def test_the_target_is_never_truncated_before_the_rename(
        existing_artifact: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point: a poller reads old-or-new, never half a document.

    ``Path.write_text`` truncates in place, so the viewer polling a run's
    ``output.json`` would periodically read an incomplete JSON document and error.
    Reading the target at the last possible instant — inside the ``os.replace``
    call — proves the previous version is still intact right up to the swap.
    """
    observed: list[str] = []
    real_replace = os.replace

    def spy(src: Any, dst: Any) -> None:
        observed.append(Path(dst).read_text(encoding="utf-8"))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    ragrun_outputs.atomic_write_text(existing_artifact, '{"new": true}')

    assert observed == ['{"old": true}']
    assert json.loads(existing_artifact.read_text()) == {"new": True}


def test_a_failed_write_leaves_the_old_file_and_no_temp_debris(
        existing_artifact: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A write that fails must lose the new content, not the old.

    The artifact being overwritten is a run's only record of itself, and this
    function is called dozens of times per run — so a failure path that either
    destroyed the previous version or left a ``.tmp`` file behind would corrupt
    or clutter the output directory a viewer is globbing.
    """
    def boom(src: Any, dst: Any) -> None:
        raise OSError("boom")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="boom"):
        ragrun_outputs.atomic_write_text(existing_artifact, '{"new": true}')

    assert json.loads(existing_artifact.read_text()) == {"old": True}
    assert [p.name for p in existing_artifact.parent.iterdir()] == [
        "output.json"]
