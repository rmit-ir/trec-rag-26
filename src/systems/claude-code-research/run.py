"""Run corpus-only Claude Code research for one or all development narratives."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SYSTEMS = _HERE.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
if str(_SYSTEMS) not in sys.path:
    sys.path.insert(0, str(_SYSTEMS))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from cli_research_common import completed_qids, load_topics  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "claude_code_research_pipeline", _HERE / "pipeline.py")
assert _spec and _spec.loader
_pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pipeline)

DEFAULT_DESC = (
    "Claude Code research agent using only ClimbMix hybrid MCP search and fetch, "
    "with schema-bound sentence citations checked against fetched documents."
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--qid")
    group.add_argument("--all", action="store_true")
    ap.add_argument("--topics", type=Path, default=None)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="max")
    ap.add_argument("--run-id", default="claude-code-research-dev30")
    ap.add_argument("--run-desc", default=DEFAULT_DESC)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    topics = load_topics(args.topics) if args.topics else load_topics()
    if args.query is not None:
        items = [("adhoc", args.query)]
    elif args.all:
        items = topics
    else:
        items = [(qid, narrative) for qid, narrative in topics if qid == args.qid]
        if not items:
            ap.error(f"qid {args.qid!r} not found")

    done = set() if args.no_resume else completed_qids(
        _pipeline.SYSTEM_NAME, args.run_id)
    pending = [(qid, narrative) for qid, narrative in items if qid not in done]
    print(f"system={_pipeline.SYSTEM_NAME} run={args.run_id} topics={len(items)} "
          f"completed={len(items) - len(pending)} pending={len(pending)} "
          f"workers={args.workers}", flush=True)
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _pipeline.run_one,
                qid=qid,
                narrative=narrative,
                run_id=args.run_id,
                run_desc=args.run_desc,
                model_id=args.model,
                effort=args.effort,
                timeout=args.timeout,
                attempts=args.attempts,
            ): qid
            for qid, narrative in pending
        }
        for future in as_completed(futures):
            qid = futures[future]
            try:
                result = future.result()
                print(f"[OK] {qid}: words={result['words']} refs="
                      f"{len(result['references'])} tools={result['tool_calls']} "
                      f"attempt={result['attempt']}", flush=True)
            except Exception as exc:  # noqa: BLE001 - finish independent topics
                failures[qid] = f"{type(exc).__name__}: {exc}"
                print(f"[FAILED] {qid}: {failures[qid]}", flush=True)

    expected = {qid for qid, _ in items}
    finished = completed_qids(_pipeline.SYSTEM_NAME, args.run_id) & expected
    missing = sorted(expected - finished)
    print(f"summary completed={len(finished)}/{len(expected)} missing={missing}",
          flush=True)
    if failures or missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
