#!/usr/bin/env python3
"""Snapshot the agent's tool + provider surface before changing it.

Git already records every version, but a git history is the wrong instrument for
this particular question. When an arm's score moves, the thing you need is "what
exactly was the tool contract when *this run_id* was generated" — and answering
that from git means correlating a run timestamp against a commit graph that also
contains unrelated work. A dated, self-contained copy under ``worklogs/assets/``
answers it by looking.

It also matters because the tool *description* is part of the prompt the model
sees. A one-word edit to ``commit_context``'s description changes behaviour as
surely as a prompt patch does, and is far easier to make without noticing.

    uv run --no-project python tasks/task-comparison/scripts/snapshot_tools.py \\
        --tag v1-pre-fact-extraction --note "before commit-time fact extraction"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "worklogs/assets"

# The surface the model actually sees or is bound by. Prompts are versioned
# separately (build_prompt_variants.py --check), so they are not duplicated here.
TRACKED = [
    "src/systems/aus_agent/tools/search.py",
    "src/systems/aus_agent/tools/commit_context.py",
    "src/systems/aus_agent/tools/get_documents.py",
    "src/systems/aus_agent/providers/openai.py",
    "src/systems/aus_agent/providers/bedrock.py",
    "src/systems/aus_agent/agent.py",
    "src/systems/aus_agent/context.py",
    "src/tools/search_tool.py",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True, help="short version tag, e.g. v1-pre-fact-extraction")
    ap.add_argument("--note", default="", help="one line on why this snapshot exists")
    ap.add_argument("--date", default="2026-08-06", help="date prefix for the directory")
    args = ap.parse_args()

    out = ASSETS / f"{args.date}-aus-agent-tools-{args.tag}"
    if out.exists():
        print(f"refusing to overwrite an existing snapshot: {out}")
        return 1
    out.mkdir(parents=True)

    manifest = {"tag": args.tag, "note": args.note, "files": {}}
    try:
        manifest["git_head"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=True).stdout.strip()
        manifest["git_dirty"] = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
            text=True, check=True).stdout.strip())
    except Exception:  # noqa: BLE001 — a snapshot is still useful without git
        manifest["git_head"] = None

    for rel in TRACKED:
        src = ROOT / rel
        if not src.exists():
            manifest["files"][rel] = None
            continue
        dest = out / rel.replace("/", "__")
        shutil.copy2(src, dest)
        manifest["files"][rel] = {"sha256_12": digest(src),
                                  "bytes": src.stat().st_size,
                                  "saved_as": dest.name}

    (out / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    kept = sum(1 for v in manifest["files"].values() if v)
    print(f"snapshot {args.tag}: {kept}/{len(TRACKED)} files -> {out.relative_to(ROOT)}")
    if manifest.get("git_dirty"):
        print("  NOTE: working tree was dirty — this snapshot is the truth, "
              "not the commit it names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
