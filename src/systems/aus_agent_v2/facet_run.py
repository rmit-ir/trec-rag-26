"""CLI for the parallel-facet research architecture."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
sys.path[0:0] = [str(_SRC_ROOT), str(_SYSTEMS_ROOT)]

from systems.aus_agent_v2.facet_research import run_parallel_facets  # noqa: E402
from systems.aus_agent_v2.run import DEFAULT_TOPICS, load_topics  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--qid")
    source.add_argument("--query")
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--backend", default="openai")
    parser.add_argument("--model", default="openai.gpt-5.6-sol")
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--child-context-token-budget", type=int, default=220_000)
    parser.add_argument("--child-safety-max-rounds", type=int, default=40)
    parser.add_argument("--run-id", default="parallel-research-dev")
    args = parser.parse_args()
    if args.query is not None:
        qid, query = "adhoc", args.query
    else:
        topics = dict(load_topics(args.topics))
        if args.qid not in topics:
            parser.error(f"qid {args.qid!r} not found in {args.topics}")
        qid, query = args.qid, topics[args.qid]
    summary = run_parallel_facets(
        qid,
        query,
        run_id=args.run_id,
        backend=args.backend,
        model=args.model,
        k=args.k,
        child_context_token_budget=args.child_context_token_budget,
        child_safety_max_rounds=args.child_safety_max_rounds,
    )
    summary["paths"] = {key: str(value) for key, value in summary["paths"].items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
