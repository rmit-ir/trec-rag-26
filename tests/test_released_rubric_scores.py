"""Defend the released scoring reference without needing withheld assignments."""

import importlib.util
import json
from fractions import Fraction
from pathlib import Path

import pytest


SCORES = Path(__file__).resolve().parents[1] / "RMIT-ADM+S scores"
spec = importlib.util.spec_from_file_location("released_scores", SCORES / "compute_rubric_scores.py")
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)


def test_strict_scores_and_missing_topics(tmp_path, monkeypatch, capsys):
    """Partial support earns no credit, and completion must retain missing topics in the mean."""
    assignments = tmp_path / "assignments.jsonl"
    assignments.write_text(json.dumps({
        "run_id": "example-run", "qid": "rag2026-11", "nuggets": [
            {"text": "Vital supported", "importance": "vital", "assignment": "support"},
            {"text": "Vital partial", "importance": "vital", "assignment": "partial_support"},
            {"text": "Okay supported", "importance": "okay", "assignment": "support"},
        ],
    }) + "\n", encoding="utf-8")
    topics = tmp_path / "topics.txt"
    topics.write_text("rag2026-11\nrag2026-13\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing 1"):
        scorer.evaluate(assignments, run="example-run", topics=scorer.read_topics(topics))
    monkeypatch.setattr("sys.argv", [str(SCORES / "compute_rubric_scores.py"),
                                    str(assignments), "--run", "example-run", "-q", "-c",
                                    "--topics", str(topics)])
    scorer.main()
    assert capsys.readouterr().out == (
        "vital_strict\trag2026-11\t0.5000\nall_strict\trag2026-11\t0.6667\n"
        "vital_strict\trag2026-13\t0.0000\nall_strict\trag2026-13\t0.0000\n"
        "vital_strict\tall\t0.2500\nall_strict\tall\t0.3333\n"
    )
    assert scorer.format_measure("all_strict", Fraction(1, 32)) == "0.0313"


def test_zero_vital_and_invalid_labels():
    """Okay-only rubrics have zero vital coverage; unresolved judgments must fail rather than lower scores."""
    assert scorer.score_items([
        {"importance": "okay", "assignment": "support"},
    ]) == {"vital_strict": 0, "all_strict": 1}
    with pytest.raises(ValueError, match="Invalid importance"):
        scorer.score_items([{"importance": "vital", "assignment": "unknown"}])
