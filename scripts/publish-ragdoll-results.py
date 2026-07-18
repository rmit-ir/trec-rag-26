#!/usr/bin/env python3
"""Copy completed RAGDoll results out of its submodule for Git publication."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = REPO_ROOT / "evaluation-results" / "ragdoll" / "aus-agent"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Completed RAGDoll evaluation directory.")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()

    source = args.source.resolve()
    required = [source / "graded.jsonl", source / "grade_inputs.jsonl", source / "scores"]
    missing = [path for path in required if not path.exists()]
    if missing:
        parser.error("evaluation is incomplete; missing: " + ", ".join(str(path) for path in missing))

    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "graded.jsonl", destination / "graded.jsonl")
    shutil.copy2(source / "grade_inputs.jsonl", destination / "grade_inputs.jsonl")
    shutil.copytree(source / "scores", destination / "scores", dirs_exist_ok=True)

    manifest = {
        "source": source.relative_to(REPO_ROOT).as_posix(),
        "artifacts": [
            "graded.jsonl",
            "grade_inputs.jsonl",
            *[f"scores/{path.name}" for path in sorted((source / "scores").glob("*")) if path.is_file()],
        ],
        "excluded": ["raw-events", "logs", "cache", "credentials"],
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"published completed RAGDoll results to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
