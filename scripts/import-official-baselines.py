#!/usr/bin/env python3
"""Import the organizer-provided TREC RAG 2026 RAG baselines into data/outputs/.

The organizers ship each baseline as ONE JSONL file holding 119 submission
records (``metadata`` / ``references`` / ``answer``). The outputs viewer indexes
one *file per session* under ``data/outputs/<system>/<ts>.<slug>.output.json``,
so this splits each JSONL row into that layout under a single synthetic system
(default ``baseline``), with the organizer's own ``run_id`` distinguishing the
two runs — which is exactly what the viewer's per-system "Run" filter keys on.

The written files contain ONLY the three submission fields: baselines carry no
agent trajectory, so there is no ``trace`` key and the viewer renders them as
answer-only sessions.

Timestamps are synthetic — baselines have no per-topic run time. Every record
of one baseline file shares a single stamp derived from that file's mtime (plus
a one-second offset per file so the two runs never interleave), and the viewer
tie-breaks equal stamps by narrative id, so a baseline lists in topic order.

    uv run python scripts/import-official-baselines.py
    uv run python scripts/import-official-baselines.py --system baseline --prune
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ragrun import query_slug, validate_rag_output  # noqa: E402
from ragrun.outputs import TZ, data_dir  # noqa: E402

DEFAULT_BASELINES_DIR = (
    REPO_ROOT / "data" / "official" / "trec-rag-2026-data" / "trec-rag-2026"
    / "baselines" / "rag"
)

README = """\
# Organizer-provided RAG baselines (generated — do not hand-edit)

Imported from `{src}` by `scripts/import-official-baselines.py`.

These are TREC RAG 2026 *baseline* submissions published by the track
organizers, not runs of ours. They carry no trajectory, so each session shows
the answer, its references and citations only — the viewer labels them
"no output trace".

| run_id | records | stamp |
| --- | ---: | --- |
{rows}

Re-import (idempotent) with:

```bash
uv run python scripts/import-official-baselines.py --prune
```
"""


def stamp_for(path: Path, offset_seconds: int) -> str:
    """Deterministic per-file stamp: the JSONL's mtime, in the same compact
    Melbourne-local format ``ragrun.run_timestamp`` emits for real runs.

    Offsetting by file index keeps two baselines checked out with identical
    mtimes from sharing a stamp, which would interleave them in the session
    list.
    """
    ts = datetime.fromtimestamp(path.stat().st_mtime, TZ) + timedelta(seconds=offset_seconds)
    return ts.strftime("%Y%m%dT%H%M%S%f%z")


def session_slug(record: dict) -> str:
    """``rag2026-12_i_m_on_a`` — narrative id first so the filename sorts and
    greps by topic, then the usual first-five-words query slug.
    """
    meta = record.get("metadata") or {}
    nid = str(meta.get("narrative_id") or "unknown").replace(".", "-")
    return f"{nid}_{query_slug(meta.get('narrative') or '')}"


def import_file(src: Path, out_dir: Path, offset_seconds: int,
                strict: bool) -> tuple[str, int, str, set[str]]:
    """Split one baseline JSONL into per-session output.json files."""
    stamp = stamp_for(src, offset_seconds)
    run_id = ""
    written: set[str] = set()
    for lineno, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        submission = {
            "metadata": record["metadata"],
            "references": record["references"],
            "answer": record["answer"],
        }
        violations = validate_rag_output(submission)
        if violations:
            msg = f"{src.name}:{lineno} fails the output contract: {violations}"
            if strict:
                raise SystemExit(f"error: {msg}")
            print(f"warning: {msg}", file=sys.stderr)
        run_id = run_id or str(submission["metadata"].get("run_id", ""))
        name = f"{stamp}.{session_slug(record)}.output.json"
        (out_dir / name).write_text(
            json.dumps(submission, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.add(name)
    return run_id, len(written), stamp, written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baselines-dir", type=Path, default=DEFAULT_BASELINES_DIR,
                    help="directory of organizer baseline *.jsonl files")
    ap.add_argument("--system", default="baseline",
                    help="system name to file them under in data/outputs/")
    ap.add_argument("--prune", action="store_true",
                    help="delete *.output.json in the target dir that this import did not write")
    ap.add_argument("--strict", action="store_true",
                    help="fail instead of warning when a record violates the output contract")
    args = ap.parse_args()

    sources = sorted(args.baselines_dir.glob("*.jsonl"))
    if not sources:
        raise SystemExit(f"error: no *.jsonl under {args.baselines_dir}")

    out_dir = data_dir() / "outputs" / args.system
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[str] = []
    kept: set[str] = set()
    for i, src in enumerate(sources):
        run_id, n, stamp, written = import_file(src, out_dir, i, args.strict)
        kept |= written
        rows.append(f"| `{run_id}` | {n} | `{stamp}` |")
        print(f"{src.name}: {n} sessions -> {out_dir}/{stamp}.*")

    if args.prune:
        for stale in out_dir.glob("*.output.json"):
            if stale.name not in kept:
                stale.unlink()
                print(f"pruned {stale.name}")

    (out_dir / "README.md").write_text(
        README.format(
            src=args.baselines_dir.relative_to(REPO_ROOT),
            rows="\n".join(rows),
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
