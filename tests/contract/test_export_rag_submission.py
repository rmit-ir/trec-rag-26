"""The submission CLI must isolate one production run from shared artifact dirs.

Every system directory contains historical runs and failed preflights. These
tests defend the final boundary where selecting too broadly would silently mix
systems or omit an official narrative even though every individual row validates.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTER = REPO_ROOT / "scripts/export-rag-submission.py"


def _artifact(topic: str, narrative: str, run_id: str) -> dict:
    return {
        "metadata": {
            "team_id": "rmit-ir",
            "narrative_id": topic,
            "narrative": narrative,
            "run_id": run_id,
            "run_desc": "test run",
        },
        "references": ["shard_00001_1"],
        "answer": [{"text": "Supported answer.", "citations": [0]}],
        "trace": {"status": "completed", "secret_debug": "strip me"},
    }


def test_exporter_filters_run_and_follows_official_topic_order(tmp_path: Path) -> None:
    """A shared directory's timestamps must not determine submission membership or order."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    rows = [
        ("z.output.json", _artifact("rag2026-1", "Second.", "wanted")),
        ("a.output.json", _artifact("rag2026-0", "First.", "wanted")),
        ("old.output.json", _artifact("rag2026-0", "First.", "old")),
    ]
    failed = _artifact("rag2026-1", "Second.", "wanted")
    failed["trace"]["status"] = "failed"
    failed["answer"] = [{"text": "Run failed: transient provider error",
                          "citations": []}]
    rows.append(("failed.output.json", failed))
    for name, row in rows:
        (artifacts / name).write_text(json.dumps(row), encoding="utf-8")
    topics = tmp_path / "topics.tsv"
    topics.write_text("rag2026-0\tFirst.\nrag2026-1\tSecond.\n",
                      encoding="utf-8")
    output = tmp_path / "submission" / "rag_output_trec_rag_2026.jsonl"

    result = subprocess.run(
        [sys.executable, str(EXPORTER), str(artifacts), "--run-id", "wanted",
         "--topics", str(topics), "--output", str(output)],
        check=False, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    exported = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["metadata"]["narrative_id"] for row in exported] == [
        "rag2026-0", "rag2026-1"]
    assert all(set(row) == {"metadata", "references", "answer"}
               for row in exported)
    assert "secret_debug" not in output.read_text()
    assert "ignored 1 superseded failed attempt" in result.stdout


def test_exporter_rewrites_run_id_in_output_only(tmp_path: Path) -> None:
    """rag26's run_id_max_len=20 (NIST run-tag convention) is shorter than
    this repo's own descriptive internal run_ids -- --output-run-id must
    swap the emitted tag without touching --run-id's artifact selection."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    long_id = "a-very-long-internal-bookkeeping-run-id-2026"
    (artifacts / "a.output.json").write_text(
        json.dumps(_artifact("rag2026-0", "First.", long_id)),
        encoding="utf-8")
    output = tmp_path / "submission" / "rag_output_trec_rag_2026.jsonl"

    result = subprocess.run(
        [sys.executable, str(EXPORTER), str(artifacts), "--run-id", long_id,
         "--output-run-id", "short-tag", "--output", str(output)],
        check=False, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    exported = [json.loads(line) for line in output.read_text().splitlines()]
    assert exported[0]["metadata"]["run_id"] == "short-tag"


def test_exporter_refuses_incomplete_official_topic_set(tmp_path: Path) -> None:
    """A structurally valid partial run must never become a full-run submission."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "one.output.json").write_text(
        json.dumps(_artifact("rag2026-0", "First.", "wanted")),
        encoding="utf-8",
    )
    topics = tmp_path / "topics.tsv"
    topics.write_text("rag2026-0\tFirst.\nrag2026-1\tSecond.\n",
                      encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(EXPORTER), str(artifacts), "--run-id", "wanted",
         "--topics", str(topics), "--output", str(tmp_path / "out.jsonl")],
        check=False, capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert "missing 1 narrative(s): rag2026-1" in result.stderr
