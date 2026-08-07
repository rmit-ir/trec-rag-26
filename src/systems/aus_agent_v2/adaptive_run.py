"""CLI for request-shape-adaptive research."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
sys.path[0:0] = [str(_SRC_ROOT), str(_SYSTEMS_ROOT)]

from systems.aus_agent_v2.adaptive_research import run_adaptive_research  # noqa: E402
from systems.aus_agent_v2.run import DEFAULT_TOPICS, load_topics  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qid", required=True)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="openai.gpt-5.6-sol")
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--context-token-budget", type=int, default=500_000)
    parser.add_argument("--safety-max-rounds", type=int, default=40)
    parser.add_argument(
        "--route", choices=("parallel_evidence", "integrated_research"),
        help="use a route persisted by a prior request-only audit")
    args = parser.parse_args()
    topics = dict(load_topics(args.topics))
    if args.qid not in topics:
        parser.error(f"qid {args.qid!r} not found in {args.topics}")
    summary = run_adaptive_research(
        args.qid,
        topics[args.qid],
        run_id=args.run_id,
        model=args.model,
        k=args.k,
        context_token_budget=args.context_token_budget,
        safety_max_rounds=args.safety_max_rounds,
        route_override=args.route,
    )
    summary["paths"] = {key: str(value) for key, value in summary["paths"].items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
