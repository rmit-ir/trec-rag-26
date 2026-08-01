"""ClimbMix corpus access for the claude-code-research agent, with tool logging.

Thin wrapper around shared ``utils.search.search`` dense+sparse RRF retrieval,
the ``tools.search_tool`` result envelope, and ``utils.fetch_doc``. It prints
the same output shape as the search-tool CLI and *additionally* appends one
JSONL record per call to ``<task-dir>/scratchpad/tool_log.jsonl``. This gives
every research task a faithful, machine-readable tool-call trace (consumed by
``scripts/save_run.py``) without relying on the agent to self-report.

Usage (root env; run from the repo or the system dir):

    uv run python scripts/corpus.py search "<query>" --k 10 [--max-chars 300] \
        --task-dir <task-dir>
    uv run python scripts/corpus.py fetch <docid> [--max-chars 200] \
        --task-dir <task-dir>

``--task-dir`` may be omitted when the ``TASK_DIR`` environment variable is
set. Each log record looks like:

    {"ts": "<ISO 8601>", "t_start": "<ISO 8601>", "t_end": "<ISO 8601>",
     "type": "tool_call",
     "tool_name": "search" | "get_document", "arguments": {...},
     "returned": [{"docid": ..., "score": ...}, ...],   # search only
     "output_head": "<first ~200 chars of the printed output>"}

``t_start``/``t_end`` (``ragrun.now_iso``, Melbourne local, ms precision) are
the wall-clock bounds of the underlying call; ``ts`` is kept for compatibility
and equals ``t_start``.

Failed calls carry ``"failed": true`` (and an ``"error"`` message) instead of
``returned``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ragrun import now_iso
from tools.search_tool import run_search_backend
from utils.fetch_doc import fetch_doc
from utils.search import search as hybrid_search

HEAD_CHARS = 200


def resolve_task_dir(arg: str | None) -> Path:
    """Task dir from ``--task-dir`` or the ``TASK_DIR`` env var (required)."""
    raw = arg or os.environ.get("TASK_DIR")
    if not raw:
        sys.exit("corpus.py: pass --task-dir or set TASK_DIR")
    return Path(raw)


def append_log(task_dir: Path, record: dict[str, Any]) -> None:
    """Append one record to ``<task-dir>/scratchpad/tool_log.jsonl``."""
    log = task_dir / "scratchpad" / "tool_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _base_record(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Record skeleton, stamped just before the underlying call runs.

    ``t_start`` is set here; the caller sets ``t_end`` right after the call.
    ``ts`` (== ``t_start``) is kept for backward compatibility.
    """
    start = now_iso()
    return {
        "ts": start,
        "t_start": start,
        "type": "tool_call",
        "tool_name": tool_name,
        "arguments": arguments,
    }


def cmd_search(args: argparse.Namespace) -> int:
    """Hybrid dense+sparse RRF search; same JSON output as search_tool CLI."""
    task_dir = resolve_task_dir(args.task_dir)
    query = " ".join(args.query)
    record = _base_record(
        "search",
        {"query": query, "k": args.k, "search_engine": "hybrid-rrf"},
    )

    out = run_search_backend(
        query,
        hybrid_search,
        engine="hybrid-rrf",
        k=args.k,
        max_chars=args.max_chars,
        with_text=True,
    )
    record["t_end"] = now_iso()
    data = json.loads(out)
    printed = json.dumps(data, indent=2, ensure_ascii=False)
    print(printed)

    if "error" in data:
        record["failed"] = True
        record["error"] = data["error"]
    else:
        record["returned"] = [{"docid": r["docid"], "score": r["score"]}
                              for r in data.get("results", [])]
    record["output_head"] = printed[:HEAD_CHARS]
    append_log(task_dir, record)
    return 1 if "error" in data else 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Fetch one document by docid; same ``<docid> -> <text head>`` output."""
    task_dir = resolve_task_dir(args.task_dir)
    record = _base_record("get_document", {"docid": args.docid})

    try:
        d = fetch_doc(args.docid)
    except Exception as e:  # log the failure, then report it
        record["t_end"] = now_iso()
        record["failed"] = True
        record["error"] = f"{type(e).__name__}: {e}"
        record["output_head"] = record["error"][:HEAD_CHARS]
        append_log(task_dir, record)
        print(f"corpus.py fetch: {record['error']}", file=sys.stderr)
        return 1
    record["t_end"] = now_iso()

    print(d["docid"], "->", d["text"][:args.max_chars].replace("\n", " "))
    record["output_head"] = d["text"][:HEAD_CHARS]
    append_log(task_dir, record)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Logged ClimbMix corpus access (search / fetch)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="hybrid RRF search over ClimbMix")
    sp.add_argument("query", nargs="+")
    sp.add_argument("--k", type=int, default=10)
    sp.add_argument("--max-chars", type=int, default=300,
                    help="truncate each result's text (default 300)")
    sp.add_argument("--task-dir", help="task folder (or set TASK_DIR)")
    sp.set_defaults(func=cmd_search)

    fp = sub.add_parser("fetch", help="fetch one document by docid")
    fp.add_argument("docid")
    fp.add_argument("--max-chars", type=int, default=200,
                    help="chars of text to print (default 200)")
    fp.add_argument("--task-dir", help="task folder (or set TASK_DIR)")
    fp.set_defaults(func=cmd_fetch)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
