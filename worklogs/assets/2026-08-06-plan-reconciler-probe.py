"""Live priority-contract probe over the failed archetype-scout proposals."""
from __future__ import annotations

import json
from pathlib import Path

from aus_agent_v2.agent import make_provider
from aus_agent_v2.plan_reconcile import (
    PLAN_RECONCILE_SYSTEM,
    normalize_reconciled_plan,
    plan_reconcile_request,
)


RUN_ID = "sol-aus-v2-archetype-scout-probe5-20260806"
MODEL = "openai.gpt-5.6-sol"
OUTPUTS = Path("data/outputs/aus_agent_v2")


def main() -> None:
    """Record exact plan/scout inputs and compiled contracts for five topics."""
    artifacts = []
    for path in OUTPUTS.glob("*.output.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("run_id") == RUN_ID:
            artifacts.append((obj["metadata"]["narrative_id"], path, obj))
    for qid, path, obj in sorted(artifacts):
        query = obj["metadata"]["narrative"]
        trace_input = obj["trace"]["input"]
        primary = trace_input["coverage_plan_initial"]
        scout = trace_input["plan_critic"]
        request = plan_reconcile_request(query, primary, scout)
        provider = make_provider("openai", MODEL)
        provider.start(PLAN_RECONCILE_SYSTEM, [])
        provider.add_user_message(request)
        turn = provider.run_turn()
        print(json.dumps({
            "qid": qid,
            "artifact": str(path),
            "system": PLAN_RECONCILE_SYSTEM,
            "request": request,
            "raw": turn.get("text"),
            "normalized": normalize_reconciled_plan(turn.get("text")),
            "usage": turn.get("usage"),
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
