"""Probe the new observable scout and compiler on the two hard checkpoint topics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aus_agent_v2.agent import make_provider
from aus_agent_v2.observable_scout import (
    OBSERVABLE_SCOUT_SYSTEM,
    combine_obligation_audits,
    normalize_observable_scout,
    observable_scout_request,
)
from aus_agent_v2.plan_reconcile import (
    PLAN_RECONCILE_SYSTEM,
    missing_must_mentions,
    normalize_reconciled_plan,
    plan_reconcile_request,
)


RUN_ID = "sol-aus-v2-atomic-claim-finish-critical2-20260806"
MODEL = "openai.gpt-5.6-sol"
OUTPUTS = Path("data/outputs/aus_agent_v2")


def main() -> None:
    """Persist every exact prompt, response, normalized audit, and contract."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--qid")
    args = parser.parse_args()
    artifacts = []
    for path in OUTPUTS.glob("*.output.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if (obj.get("metadata", {}).get("run_id") == RUN_ID
                and (args.qid is None
                     or obj["metadata"]["narrative_id"] == args.qid)):
            artifacts.append((obj["metadata"]["narrative_id"], path, obj))
    for qid, path, obj in sorted(artifacts):
        query = obj["metadata"]["narrative"]
        primary = obj["trace"]["input"]["coverage_plan_initial"]
        semantic = obj["trace"]["input"]["plan_critic"]
        scout_request = observable_scout_request(query, primary, semantic)
        scout_provider = make_provider("openai", MODEL)
        scout_provider.start(OBSERVABLE_SCOUT_SYSTEM, [])
        scout_provider.add_user_message(scout_request)
        scout_turn = scout_provider.run_turn()
        observable = normalize_observable_scout(scout_turn.get("text"))
        combined = combine_obligation_audits(semantic, observable)

        reconcile_request = plan_reconcile_request(query, primary, combined)
        reconcile_provider = make_provider("openai", MODEL)
        reconcile_provider.start(PLAN_RECONCILE_SYSTEM, [])
        reconcile_provider.add_user_message(reconcile_request)
        reconcile_turn = reconcile_provider.run_turn()
        compiled = normalize_reconciled_plan(reconcile_turn.get("text"))

        print(json.dumps({
            "qid": qid,
            "artifact": str(path),
            "observable_system": OBSERVABLE_SCOUT_SYSTEM,
            "observable_request": scout_request,
            "observable_raw": scout_turn.get("text"),
            "observable": observable,
            "combined": combined,
            "reconcile_system": PLAN_RECONCILE_SYSTEM,
            "reconcile_request": reconcile_request,
            "reconcile_raw": reconcile_turn.get("text"),
            "compiled": compiled,
            "missing_must_mentions": missing_must_mentions(compiled, combined),
            "usage": {
                "observable": scout_turn.get("usage"),
                "reconcile": reconcile_turn.get("usage"),
            },
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
