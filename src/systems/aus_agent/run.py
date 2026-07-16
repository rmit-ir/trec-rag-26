"""CLI for the aus_agent RAG harness.

Usage (from the repo root):

    uv run --group aus-agent python src/systems/aus_agent/run.py \\
        --qid 6847465956a0f6376a605492
    uv run --group aus-agent python src/systems/aus_agent/run.py \\
        --query "..." [--model au.anthropic.claude-sonnet-5] [--k 10]
    uv run --group aus-agent python src/systems/aus_agent/run.py --all
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
_src_root = str(_SRC_ROOT)
sys.path[:] = [entry for entry in sys.path if entry != _src_root]
sys.path.insert(0, _src_root)

from systems.aus_agent.agent import run_agent

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TOPICS = (_REPO_ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
                  "/development-data/topics/research-rubrics-topics-dev.tsv")


def load_topics(path: Path) -> list[tuple[str, str]]:
    """Parse a ``qid \\t narrative`` TSV into (qid, narrative) pairs."""
    topics = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        qid, _, narrative = line.partition("\t")
        topics.append((qid, narrative.strip()))
    return topics


def main() -> None:
    ap = argparse.ArgumentParser(description="aus_agent RAG harness")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="ad-hoc query text (qid 'adhoc')")
    src.add_argument("--qid", help="topic id from the topics TSV")
    src.add_argument("--all", action="store_true",
                     help="run every topic in the topics TSV")
    ap.add_argument("--topics", type=Path, default=DEFAULT_TOPICS,
                    help=f"topics TSV (default: {DEFAULT_TOPICS})")
    ap.add_argument("--backend", default="bedrock")
    ap.add_argument("--model", default=None,
                    help="model id (default: BEDROCK_MODEL_ID env or "
                         "au.anthropic.claude-sonnet-5)")
    ap.add_argument("--k", type=int, default=10, help="search results per call")
    ap.add_argument(
        "--context-token-budget", type=int, default=500_000,
        help="stop retrieval when one generation's provider-reported input "
             "context reaches this size (default: 500000)")
    ap.add_argument(
        "--safety-max-rounds", "--max-rounds", type=int, default=100,
        help="runaway-loop safety backstop, not the normal research budget "
             "(default: 100)")
    ap.add_argument(
        "--max-committed-per-step", type=int, default=6,
        help="maximum documents commit_context may retain from one staged "
             "batch (default: 6)")
    ap.add_argument("--run-id", default="aus-agent-dev")
    args = ap.parse_args()

    if args.query:
        jobs = [("adhoc", args.query)]
    elif args.qid:
        topics = dict(load_topics(args.topics))
        if args.qid not in topics:
            ap.error(f"qid {args.qid!r} not found in {args.topics}")
        jobs = [(args.qid, topics[args.qid])]
    else:
        jobs = load_topics(args.topics)

    failures = 0
    for qid, query in jobs:
        print(f"=== {qid}: {query[:80]}...", flush=True)
        try:
            summary = run_agent(qid, query, backend=args.backend,
                                model=args.model, k=args.k,
                                context_token_budget=args.context_token_budget,
                                safety_max_rounds=args.safety_max_rounds,
                                max_committed_per_step=(
                                    args.max_committed_per_step),
                                run_id=args.run_id)
        except Exception as e:  # keep --all going
            failures += 1
            print(f"    ERROR {type(e).__name__}: {e}", flush=True)
            continue
        summary["paths"] = {k: str(v) for k, v in summary["paths"].items()}
        print(json.dumps(summary, indent=2), flush=True)
        if summary["status"] == "failed":
            failures += 1
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
