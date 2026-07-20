"""CLI for the aus_agent RAG harness.

Usage (from the repo root):

    uv run --group aus-agent python src/systems/aus_agent/run.py \\
        --qid 6847465956a0f6376a605492
    uv run --group aus-agent python src/systems/aus_agent/run.py \\
        --query "..." [--model au.anthropic.claude-sonnet-5] [--k 10]
    uv run --group aus-agent python src/systems/aus_agent/run.py --all

Every option's default can also be set via a ``RUN_AUS_AGENT_<OPTION>`` env
var (e.g. ``RUN_AUS_AGENT_BACKEND=openai``, ``RUN_AUS_AGENT_MODEL=...`` in a
``.env``); an explicit CLI flag still wins.
"""
from __future__ import annotations
from utils.env import env
from systems.aus_agent.agent import DEFAULT_MAX_COMMITTED_PER_STEP, run_agent
from ragrun.outputs import data_dir

import argparse
import json
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
_src_root = str(_SRC_ROOT)
sys.path[:] = [entry for entry in sys.path if entry != _src_root]
sys.path.insert(0, _src_root)


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


def finished_topics(run_id: str) -> set[str]:
    """Topic ids this ``run_id`` has already answered successfully.

    A crashed run still writes a schema-valid artifact whose answer is a single
    "Run failed: ..." sentence, so the run's own status — not the file's
    existence — decides whether a topic is done. Scoping to ``run_id`` means a
    fresh id re-runs everything, while reusing one resumes it.
    """
    out_dir = data_dir() / "outputs" / "aus_agent"
    done: set[str] = set()
    for path in out_dir.glob("*.output.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if obj.get("metadata", {}).get("run_id") != run_id:
            continue
        if obj.get("trace", {}).get("status") in ("completed",
                                                  "budget_exhausted"):
            done.add(str(obj["metadata"]["narrative_id"]))
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="aus_agent RAG harness")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="ad-hoc query text (qid 'adhoc')")
    src.add_argument("--qid", help="topic id from the topics TSV")
    src.add_argument("--all", action="store_true",
                     help="run every topic in the topics TSV")
    ap.add_argument("--topics", type=Path,
                    default=env("RUN_AUS_AGENT_TOPICS", DEFAULT_TOPICS),
                    help=f"topics TSV (default: {DEFAULT_TOPICS})")
    ap.add_argument("--backend",
                    default=env("RUN_AUS_AGENT_BACKEND", "bedrock"))
    ap.add_argument("--model",
                    default=env("RUN_AUS_AGENT_MODEL", None),
                    help="model id (default: backend's own env/default, e.g. "
                         "BEDROCK_MODEL_ID or OPENAI_MODEL_ID)")
    ap.add_argument("--k", type=int, default=env("RUN_AUS_AGENT_K", 10),
                    help="search results per call")
    ap.add_argument(
        "--context-token-budget", type=int,
        default=env("RUN_AUS_AGENT_CONTEXT_TOKEN_BUDGET", 500_000),
        help="stop retrieval when one generation's provider-reported input "
             "context reaches this size (default: 500000)")
    ap.add_argument(
        "--safety-max-rounds", "--max-rounds", type=int,
        default=env("RUN_AUS_AGENT_SAFETY_MAX_ROUNDS", 100),
        help="runaway-loop safety backstop, not the normal research budget "
             "(default: 100)")
    ap.add_argument(
        "--max-committed-per-step", type=int,
        default=env("RUN_AUS_AGENT_MAX_COMMITTED_PER_STEP",
                    DEFAULT_MAX_COMMITTED_PER_STEP),
        help="maximum documents commit_context may retain from one staged "
             f"batch (default: {DEFAULT_MAX_COMMITTED_PER_STEP})")
    ap.add_argument("--run-id",
                    default=env("RUN_AUS_AGENT_RUN_ID", "aus-agent-dev"))
    ap.add_argument(
        "--skip-existing", action="store_true",
        default=env("RUN_AUS_AGENT_SKIP_EXISTING", False),
        help="skip topics this --run-id has already answered successfully, so "
             "an interrupted batch resumes instead of starting over (a failed "
             "run does not count as answered)")
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

    if args.skip_existing:
        done = finished_topics(args.run_id)
        remaining = [job for job in jobs if job[0] not in done]
        print(f"--skip-existing: {len(jobs) - len(remaining)} of {len(jobs)} "
              f"topics already answered by run-id {args.run_id!r}; "
              f"running {len(remaining)}", flush=True)
        jobs = remaining
        if not jobs:
            print("nothing to do", flush=True)
            return

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
