"""Compile atomic scout ledgers with primary plans from the failed five-topic run."""
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
SCOUT_LOGS = [
    Path("worklogs/assets/2026-08-06-atomic-obligation-scout-probe5.log"),
    Path("worklogs/assets/2026-08-06-atomic-obligation-critical2.log"),
]


def load_scouts() -> dict[str, dict]:
    """Use the later critical re-probe when a qid occurs in both logs."""
    scouts: dict[str, dict] = {}
    for path in SCOUT_LOGS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                row = json.loads(line)
                scouts[row["qid"]] = row["normalized"]
    return scouts


def main() -> None:
    """Persist exact reconciler inputs, raw outputs, and missing exact terms."""
    scouts = load_scouts()
    artifacts = []
    for path in OUTPUTS.glob("*.output.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("run_id") == RUN_ID:
            artifacts.append((obj["metadata"]["narrative_id"], path, obj))
    for qid, path, obj in sorted(artifacts):
        query = obj["metadata"]["narrative"]
        primary = obj["trace"]["input"]["coverage_plan_initial"]
        scout = scouts[qid]
        request = plan_reconcile_request(query, primary, scout)
        provider = make_provider("openai", MODEL)
        provider.start(PLAN_RECONCILE_SYSTEM, [])
        provider.add_user_message(request)
        turn = provider.run_turn()
        normalized = normalize_reconciled_plan(turn.get("text"))
        mentions = [
            mention
            for item in scout.get("additions", [])
            for mention in item.get("must_mention", [])
        ]
        missing = [
            mention for mention in mentions
            if mention.casefold() not in (normalized or "").casefold()
        ]
        print(json.dumps({
            "qid": qid,
            "artifact": str(path),
            "system": PLAN_RECONCILE_SYSTEM,
            "request": request,
            "raw": turn.get("text"),
            "normalized": normalized,
            "must_mentions": mentions,
            "missing_must_mentions": missing,
            "usage": turn.get("usage"),
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
