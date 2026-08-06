"""CLI for a request-only evidence-blueprint routing audit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
sys.path[0:0] = [str(_SRC_ROOT), str(_SYSTEMS_ROOT)]

from systems.aus_agent_v2.blueprint_route import route_blueprint_request  # noqa: E402
from systems.aus_agent_v2.run import DEFAULT_TOPICS, load_topics  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qid", required=True)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--model", default="openai.gpt-5.6-sol")
    args = parser.parse_args()
    topics = dict(load_topics(args.topics))
    if args.qid not in topics:
        parser.error(f"qid {args.qid!r} not found in {args.topics}")
    route, turn, attempts = route_blueprint_request(
        topics[args.qid], model=args.model)
    print(json.dumps({
        "qid": args.qid,
        **route,
        "attempts": attempts,
        "raw": turn.get("text"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
