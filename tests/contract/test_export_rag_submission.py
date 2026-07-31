"""Full-run contract for ``scripts/export-rag-submission.py``.

Per-row schema validation cannot prove that a submission represents one complete
run. This module defends the cross-row requirements that fail only at export
time: exact coverage of all 119 official narratives, source-text fidelity,
stable run identity, official ordering, and failure-safe output replacement.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/export-rag-submission.py"
SPEC = importlib.util.spec_from_file_location("export_rag_submission", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
exporter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = exporter
SPEC.loader.exec_module(exporter)

TEAM_ID = "rmit-ir"
RUN_ID = "submission-contract"
RUN_DESC = "Complete test run used to verify the official exporter contract."
DOCIDS = ("shard_00459_61697", "shard_01012_88420")


def _narrative(index: int) -> str:
    return f"Official narrative {index} preserves Unicode: café — naïve."


def _write_topics(path: Path, ids: list[str] | None = None) -> bytes:
    narrative_ids = ids or list(exporter.OFFICIAL_NARRATIVE_IDS)
    raw = "".join(
        f"{narrative_id}\t{_narrative(int(narrative_id.rsplit('-', 1)[1]))}\n"
        for narrative_id in narrative_ids
    ).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _artifact(
    narrative_id: str,
    narrative: str,
    *,
    team_id: str = TEAM_ID,
    run_id: str = RUN_ID,
    run_desc: str = RUN_DESC,
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "metadata": {
            "team_id": team_id,
            "narrative_id": narrative_id,
            "narrative": narrative,
            "run_id": run_id,
            "run_desc": run_desc,
            "generator": "contract/fake-model",
        },
        "references": list(DOCIDS),
        "answer": [
            {"text": "A supported claim.", "citations": [DOCIDS[0]]},
            {"text": "## Context", "citations": []},
        ],
        "trace": {"status": status, "api_key": "must-not-be-exported"},
    }


def _write_run(directory: Path) -> dict[str, Path]:
    directory.mkdir()
    paths: dict[str, Path] = {}
    for index, narrative_id in enumerate(exporter.OFFICIAL_NARRATIVE_IDS):
        # Reverse filename order so a passing test proves the exporter follows
        # the topics TSV rather than incidental timestamps/paths.
        path = directory / f"{118 - index:03d}.output.json"
        path.write_text(
            json.dumps(
                _artifact(narrative_id, _narrative(index)),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        paths[narrative_id] = path
    return paths


def _rewrite(path: Path, change: Any) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _export(run_dir: Path, topics: Path, output: Path) -> tuple[int, str]:
    return exporter.export_submission(
        [run_dir],
        topics_path=topics,
        output_path=output,
        expected_team_id=TEAM_ID,
        expected_run_id=RUN_ID,
    )


def test_complete_export_is_officially_ordered_and_trace_free(
    tmp_path: Path,
) -> None:
    """Filesystem ordering is unrelated to topic order, while leaked trace data
    can include credentials that must never reach the organizer."""
    topics = tmp_path / "topics.tsv"
    raw_topics = _write_topics(topics)
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    output = tmp_path / "submission/rag_output_trec_rag_2026.jsonl"

    count, digest = _export(run_dir, topics, output)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").split("\n")
            if line]
    assert count == 119
    assert digest == hashlib.sha256(raw_topics).hexdigest()
    assert [row["metadata"]["narrative_id"] for row in rows] == \
        list(exporter.OFFICIAL_NARRATIVE_IDS)
    assert all(set(row) == {"metadata", "references", "answer"} for row in rows)
    assert all(row["metadata"]["generator"] == "contract/fake-model" for row in rows)
    assert "must-not-be-exported" not in output.read_text(encoding="utf-8")


def test_cli_reports_the_topics_checksum_and_run_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The checksum and explicit identity make the final command auditable
    without putting provenance fields outside the organizer's schema."""
    topics = tmp_path / "topics.tsv"
    raw_topics = _write_topics(topics)
    run_dir = tmp_path / "run"
    _write_run(run_dir)
    output = tmp_path / "rag_output_trec_rag_2026.jsonl"

    result = exporter.main([
        str(run_dir), "--topics", str(topics), "--team-id", TEAM_ID,
        "--run-id", RUN_ID, "--output", str(output),
    ])

    stdout = capsys.readouterr().out
    assert result == 0
    assert hashlib.sha256(raw_topics).hexdigest() in stdout
    assert f"team_id={TEAM_ID!r}" in stdout
    assert f"run_id={RUN_ID!r}" in stdout


def test_missing_topic_does_not_replace_an_existing_submission(
    tmp_path: Path,
) -> None:
    """A failed rerun must leave the last reviewable file intact instead of
    replacing it with a valid-looking 118-row subset."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    paths["rag2026-37"].unlink()
    output = tmp_path / "rag_output_trec_rag_2026.jsonl"
    output.write_text("previous-valid-submission\n", encoding="utf-8")

    with pytest.raises(exporter.ExportError, match="missing narratives: rag2026-37"):
        _export(run_dir, topics, output)

    assert output.read_text(encoding="utf-8") == "previous-valid-submission\n"


def test_unknown_topic_is_rejected_before_it_can_mask_a_missing_one(
    tmp_path: Path,
) -> None:
    """Counting 119 files is insufficient when one official topic was replaced
    by an ad-hoc or development narrative."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    _rewrite(
        paths["rag2026-118"],
        lambda row: row["metadata"].update(narrative_id="rag2026-999"),
    )

    with pytest.raises(exporter.ExportError, match="rag2026-999.*not in the official"):
        _export(run_dir, topics, tmp_path / "submission.jsonl")


def test_duplicate_topic_error_identifies_both_artifacts(tmp_path: Path) -> None:
    """Naming both paths makes a resume collision actionable when two attempts
    for the same narrative coexist in one output directory."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    duplicate = run_dir / "duplicate.output.json"
    duplicate.write_text(paths["rag2026-0"].read_text(encoding="utf-8"),
                         encoding="utf-8")

    with pytest.raises(exporter.ExportError) as excinfo:
        _export(run_dir, topics, tmp_path / "submission.jsonl")

    message = str(excinfo.value)
    assert "duplicate narrative_id 'rag2026-0'" in message
    assert str(paths["rag2026-0"].resolve()) in message
    assert str(duplicate.resolve()) in message


def test_narrative_must_match_the_official_unicode_text_exactly(
    tmp_path: Path,
) -> None:
    """Whitespace normalization or Unicode replacement changes a required input
    field even when the prose remains visually similar."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    _rewrite(
        paths["rag2026-5"],
        lambda row: row["metadata"].update(
            narrative=row["metadata"]["narrative"] + " "
        ),
    )

    with pytest.raises(exporter.ExportError, match="does not exactly match"):
        _export(run_dir, topics, tmp_path / "submission.jsonl")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        pytest.param("team_id", "another-team", "expected 'rmit-ir'", id="team"),
        pytest.param("run_id", "another-run", "expected 'submission-contract'", id="run"),
    ],
)
def test_explicit_identity_rejects_the_wrong_run(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    """A directory can be internally consistent yet belong to a different team
    or experiment than the operator intended to submit."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    _rewrite(paths["rag2026-0"],
             lambda row: row["metadata"].update({field: value}))

    with pytest.raises(exporter.ExportError, match=message):
        _export(run_dir, topics, tmp_path / "submission.jsonl")


def test_run_description_cannot_change_between_topics(tmp_path: Path) -> None:
    """A stable run ID with changing descriptions indicates artifacts from
    different configurations were accidentally assembled together."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    _rewrite(
        paths["rag2026-0"],
        lambda row: row["metadata"].update(run_desc="Different configuration."),
    )

    with pytest.raises(exporter.ExportError, match=r"metadata\.run_desc"):
        _export(run_dir, topics, tmp_path / "submission.jsonl")


@pytest.mark.parametrize("status", [None, "failed"])
def test_unfinished_artifact_cannot_pass_via_a_schema_valid_failure_answer(
    tmp_path: Path, status: str | None
) -> None:
    """Failure answers intentionally satisfy the row schema, so trace status is
    the only signal that prevents an expired credential from shipping."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)

    def change(row: dict[str, Any]) -> None:
        if status is None:
            row["trace"].pop("status")
        else:
            row["trace"]["status"] = status

    _rewrite(paths["rag2026-0"], change)

    with pytest.raises(exporter.ExportError, match="trace.status|not a finished run"):
        _export(run_dir, topics, tmp_path / "submission.jsonl")


def test_empty_answer_text_is_rejected_by_the_export_boundary(tmp_path: Path) -> None:
    """The final exporter must apply the official non-empty-text rule even when
    an internal artifact was written before validation completed."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    _rewrite(paths["rag2026-0"],
             lambda row: row["answer"][0].update(text=""))

    with pytest.raises(exporter.ExportError, match=r"answer\[0\]\.text must be non-empty"):
        _export(run_dir, topics, tmp_path / "submission.jsonl")


def test_topics_file_must_preserve_the_canonical_id_order(tmp_path: Path) -> None:
    """A complete but reordered source file is not the released test input and
    must not silently redefine the final JSONL order."""
    ids = list(exporter.OFFICIAL_NARRATIVE_IDS)
    ids[0], ids[1] = ids[1], ids[0]
    topics = tmp_path / "topics.tsv"
    _write_topics(topics, ids)

    with pytest.raises(exporter.ExportError, match="not in official order"):
        exporter.load_official_topics(topics)


def test_output_cannot_overwrite_an_input_artifact(tmp_path: Path) -> None:
    """A path typo must not replace the only recoverable internal artifact with
    its stripped organizer-facing projection."""
    topics = tmp_path / "topics.tsv"
    _write_topics(topics)
    run_dir = tmp_path / "run"
    paths = _write_run(run_dir)
    victim = paths["rag2026-0"]
    original = victim.read_bytes()

    with pytest.raises(exporter.ExportError, match="must not overwrite"):
        _export(run_dir, topics, victim)

    assert victim.read_bytes() == original
