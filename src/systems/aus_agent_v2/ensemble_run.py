"""CLI for evidence-preserving selection across completed research runs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
sys.path[0:0] = [str(_SRC_ROOT), str(_SYSTEMS_ROOT)]

from systems.aus_agent_v2.ensemble_select import run_ensemble_selection  # noqa: E402
from systems.aus_agent_v2.run import DEFAULT_TOPICS, load_topics  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qid", required=True)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--candidate-run-id", action="append", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="openai.gpt-5.6-sol")
    parser.add_argument("--rubric-guided", action="store_true")
    args = parser.parse_args()
    topics = dict(load_topics(args.topics))
    if args.qid not in topics:
        parser.error(f"qid {args.qid!r} not found in {args.topics}")
    summary = run_ensemble_selection(
        args.qid,
        topics[args.qid],
        candidate_run_ids=args.candidate_run_id,
        run_id=args.run_id,
        model=args.model,
        rubric_guided=args.rubric_guided,
    )
    summary["paths"] = {key: str(value) for key, value in summary["paths"].items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
