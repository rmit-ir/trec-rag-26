"""Live plan-independent audience-audit probe over the six saved drafts."""
from __future__ import annotations

import json
from pathlib import Path

from aus_agent_v2.agent import make_provider
from aus_agent_v2.audience_verify import (
    AUDIENCE_VERIFY_SYSTEM,
    audience_verify_request,
    normalize_audience_audit,
)


RUN_ID = "sol-aus-v2-blind-bounded-confirm6-20260806"
MODEL = "openai.gpt-5.6-sol"
OUTPUTS = Path("data/outputs/aus_agent_v2")


def answer_text(obj: dict) -> str:
    """Reconstruct the prose exactly as it appeared to the organizer."""
    return "\n".join(item["text"] for item in obj.get("answer", []))


def main() -> None:
    """Record exact packets and raw results so the prompt probe is auditable."""
    artifacts = []
    for path in OUTPUTS.glob("*.output.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("run_id") == RUN_ID:
            artifacts.append((obj["metadata"]["narrative_id"], path, obj))
    for qid, path, obj in sorted(artifacts):
        query = obj["metadata"]["narrative"]
        request = audience_verify_request(query, answer_text(obj))
        provider = make_provider("openai", MODEL)
        provider.start(AUDIENCE_VERIFY_SYSTEM, [])
        provider.add_user_message(request)
        turn = provider.run_turn()
        print(json.dumps({
            "qid": qid,
            "artifact": str(path),
            "system": AUDIENCE_VERIFY_SYSTEM,
            "request": request,
            "raw": turn.get("text"),
            "normalized": normalize_audience_audit(turn.get("text")),
            "usage": turn.get("usage"),
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
