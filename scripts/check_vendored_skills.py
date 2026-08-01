#!/usr/bin/env python3
"""Check the vendored TREC-RAG official skills against upstream.

Three of the four directories under ``skills/`` are *copies* of skills published
at https://github.com/TREC-RAG/trec-rag-skills — including
``trec-rag-2026-track-guidelines``, which the official data repo designates as
the canonical spec for the 2026 submission formats. They are copies rather than a
git submodule because Claude Code only discovers skills at ``skills/<name>/``
directly, and because we occasionally need to read them offline.

The cost of that choice is that nothing refreshes them. ``git submodule update
--remote`` does not touch them, so on 2026-07-30 we spent a session reasoning
from a v0.3.0 spec while upstream had been at v0.6.0 for some time — which had
already answered an open question of ours, and had relaxed three validation
rules our validator was still enforcing (rejecting conforming submissions). The
same check then found ``pyserini-rest-api`` a version behind as well, hiding a
mandatory request-pacing policy for shared infrastructure.

This script is the missing refresh signal. It clones upstream at ``main`` and
byte-compares every vendored file, reporting version deltas from the SKILL.md
frontmatter. It needs network, so it is NOT part of the hermetic pytest suite;
it runs in CI (``.github/workflows/vendored-skills.yml``) on a schedule and on
demand:

    python scripts/check_vendored_skills.py            # report drift, exit 1 if any
    python scripts/check_vendored_skills.py --update    # re-vendor in place

``--update`` overwrites the vendored copies wholesale. That is safe *only*
because we never locally edit them; if you ever need a local deviation, record
it here as an exception rather than letting ``--update`` silently revert it.
Local-only skills (``trec-rag-new-system``, ``bm25-parameter-tuning``) are
ignored — anything upstream does not publish is ours.
"""
from __future__ import annotations

import argparse
import filecmp
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM = "https://github.com/TREC-RAG/trec-rag-skills.git"
REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

# Skills authored in this repo, not vendored from upstream. Everything else
# under skills/ that upstream also publishes is expected to match byte for byte.
LOCAL_ONLY = {"trec-rag-new-system", "bm25-parameter-tuning"}

_VERSION_RE = re.compile(r"^\s*version:\s*(\S+)\s*$", re.MULTILINE)


def skill_version(skill_md: Path) -> str:
    """Read ``metadata.version`` from a SKILL.md's frontmatter.

    A hand-rolled regex rather than a YAML parse: the frontmatter is the only
    place ``version:`` appears at that indentation, and this keeps the script
    stdlib-only so CI needs no install step.
    """
    if not skill_md.is_file():
        return "?"
    match = _VERSION_RE.search(skill_md.read_text(encoding="utf-8"))
    return match.group(1) if match else "unversioned"


def clone_upstream(dest: Path) -> str:
    """Shallow-clone upstream ``main``; returns the commit sha."""
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", UPSTREAM, str(dest)],
        check=True)
    return subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()


def relative_files(root: Path) -> set[Path]:
    """Every file under ``root``, as paths relative to it (``.git`` excluded)."""
    return {p.relative_to(root) for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts}


def compare_skill(ours: Path, theirs: Path) -> list[str]:
    """Report per-file differences between two copies of one skill."""
    our_files, their_files = relative_files(ours), relative_files(theirs)
    problems = [f"missing locally: {p}" for p in sorted(their_files - our_files)]
    problems += [f"not upstream (local addition?): {p}"
                 for p in sorted(our_files - their_files)]
    problems += [f"differs: {p}" for p in sorted(our_files & their_files)
                 if not filecmp.cmp(ours / p, theirs / p, shallow=False)]
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="re-vendor drifted skills from upstream in place")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        upstream_root = Path(tmp) / "trec-rag-skills"
        sha = clone_upstream(upstream_root)
        upstream_skills = upstream_root / "skills"
        print(f"upstream {UPSTREAM} @ {sha}\n")

        drifted: list[str] = []
        for ours in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
            name = ours.name
            if name in LOCAL_ONLY:
                print(f"  {name}: local-only, skipped")
                continue
            theirs = upstream_skills / name
            if not theirs.is_dir():
                print(f"  {name}: not published upstream — treat as local-only "
                      "and add it to LOCAL_ONLY")
                continue

            our_v = skill_version(ours / "SKILL.md")
            their_v = skill_version(theirs / "SKILL.md")
            problems = compare_skill(ours, theirs)
            if not problems:
                print(f"  {name}: up to date ({our_v})")
                continue

            drifted.append(name)
            version_note = (f"{our_v} -> {their_v}" if our_v != their_v
                            else f"{our_v} (same version, content differs)")
            print(f"  {name}: STALE {version_note}")
            for problem in problems:
                print(f"      {problem}")
            if args.update:
                shutil.rmtree(ours)
                shutil.copytree(theirs, ours)
                print(f"      re-vendored -> {their_v}")

    if not drifted:
        print("\nAll vendored skills match upstream.")
        return 0
    if args.update:
        print(f"\nRe-vendored {len(drifted)}: {', '.join(drifted)}")
        print("Review the diff — a spec change may invalidate validator rules, "
              "tests, or docs. See worklogs/2026-07-30-spec-revendor-validator-"
              "relax.md for what a re-vendor can break.")
        return 0
    print(f"\n{len(drifted)} vendored skill(s) stale: {', '.join(drifted)}")
    print("Refresh with: python scripts/check_vendored_skills.py --update")
    return 1


if __name__ == "__main__":
    sys.exit(main())
