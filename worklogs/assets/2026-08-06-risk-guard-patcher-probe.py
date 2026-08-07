"""Exercise citation-local repairs on the two existing dual-scout drafts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aus_agent_v2.agent import make_provider
from aus_agent_v2.claim_finish import (
    CLAIM_FINISH_SYSTEM,
    apply_claim_patches,
    build_claim_finish_packet,
)


RUN_ID = "sol-aus-v2-dual-scout-critical2-20260806"
MODEL = "openai.gpt-5.6-sol"
OUTPUTS = Path("data/outputs/aus_agent_v2")
AUDIT_LOG = Path("worklogs/assets/2026-08-06-risk-guard-verifier-probe.log")


def audits() -> dict[str, dict]:
    """Load the exact normalized outputs produced by the verifier probe."""
    result = {}
    for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("{"):
            row = json.loads(line)
            result[row["qid"]] = row["normalized"]
    return result


def cited_draft(obj: dict) -> str:
    """Reconstruct the pre-mapping docid markers expected by the patcher."""
    return "\n".join(
        item["text"] + " " + " ".join(
            f"[{obj['references'][index]}]" for index in item["citations"])
        for item in obj["answer"]
    )


def committed_documents(obj: dict, output_path: Path) -> dict[str, dict]:
    """Recover only retained search units from the rich trace."""
    committed = set(obj["trace"]["summary"]["context"]["committed"])
    documents = {}
    trajectory_path = Path(str(output_path).replace(
        ".output.json", ".trajectory.json"))
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    for message in trajectory.get("raw_messages", []):
        if message.get("type") != "function_call_output":
            continue
        try:
            payload = str(message.get("output", "")).partition(
                "\n[context budget:")[0]
            output = json.loads(payload)
        except (TypeError, ValueError):
            continue
        for result in output.get("results", []):
            unit_id = result.get("id")
            if unit_id in committed and result.get("text"):
                documents[unit_id] = result
    return documents


def main() -> None:
    """Persist exact packets, model proposals, validation, and patched drafts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--qid", required=True)
    args = parser.parse_args()
    audit_by_qid = audits()
    for path in OUTPUTS.glob("*.output.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if (obj.get("metadata", {}).get("run_id") != RUN_ID
                or obj["metadata"]["narrative_id"] != args.qid):
            continue
        draft = cited_draft(obj)
        documents = committed_documents(obj, path)
        built = build_claim_finish_packet(
            obj["metadata"]["narrative"],
            draft,
            audit_by_qid[args.qid],
            documents,
        )
        if built is None:
            raise RuntimeError("no evidence packet could be built")
        packet, allowed = built
        provider = make_provider("openai", MODEL)
        provider.start(CLAIM_FINISH_SYSTEM, [])
        provider.add_user_message(packet)
        turn = provider.run_turn()
        patched, stats, errors = apply_claim_patches(
            draft, turn.get("text"), allowed)
        print(json.dumps({
            "qid": args.qid,
            "artifact": str(path),
            "system": CLAIM_FINISH_SYSTEM,
            "packet": packet,
            "allowed": {str(k): sorted(v) for k, v in allowed.items()},
            "raw": turn.get("text"),
            "stats": stats,
            "errors": errors,
            "original": draft,
            "patched": patched,
            "documents": len(documents),
            "usage": turn.get("usage"),
        }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
