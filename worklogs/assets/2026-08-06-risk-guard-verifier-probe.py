"""Run the revised coverage verifier against the latest two accepted drafts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aus_agent_v2.agent import make_provider
from aus_agent_v2.coverage_verify import (
    COVERAGE_VERIFY_SYSTEM,
    coverage_verify_request,
    normalize_coverage_audit,
)


RUN_ID = "sol-aus-v2-dual-scout-critical2-20260806"
MODEL = "openai.gpt-5.6-sol"
OUTPUTS = Path("data/outputs/aus_agent_v2")


def main() -> None:
    """Persist exact verifier input, output, normalization, and usage."""
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
        plan = obj["trace"]["input"]["coverage_plan"]
        draft = "\n".join(item["text"] + " " + " ".join(
            f"[{obj['references'][index]}]" for index in item["citations"]
        ) for item in obj["answer"])
        request = coverage_verify_request(query, plan, draft)
        provider = make_provider("openai", MODEL)
        provider.start(COVERAGE_VERIFY_SYSTEM, [])
        provider.add_user_message(request)
        turn = provider.run_turn()
        print(json.dumps({
            "qid": qid,
            "artifact": str(path),
            "system": COVERAGE_VERIFY_SYSTEM,
            "request": request,
            "raw": turn.get("text"),
            "normalized": normalize_coverage_audit(turn.get("text")),
            "usage": turn.get("usage"),
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
