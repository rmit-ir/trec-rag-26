"""Recover the exact accepted draft before claim patches for causal grading."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from aus_agent_v2.agent import (
    _collapse_to_docs,
    _map_citations,
    _parse_final_prose,
)


SOURCE_OUTPUT = Path(
    "data/outputs/aus_agent_v2/"
    "20260806T234856147958+1000.conduct_an_analysis_to_determine.output.json"
)
SOURCE_TRAJECTORY = Path(str(SOURCE_OUTPUT).replace(
    ".output.json", ".trajectory.json"))
RUN_ID = "sol-aus-v2-risk-finish-social-prepatch-causal-20260806"
DESTINATION = Path(
    "data/outputs/aus_agent_v2/"
    "20260806T235500000000+1000.social_prepatch_causal.output.json"
)


def main() -> None:
    """Write one contract-shaped artifact differing only by accepted patches."""
    output = json.loads(SOURCE_OUTPUT.read_text(encoding="utf-8"))
    trajectory = json.loads(SOURCE_TRAJECTORY.read_text(encoding="utf-8"))
    messages = trajectory["raw_messages"]
    boundary = next(
        index for index, item in enumerate(messages)
        if item.get("type") == "phase_boundary"
        and item.get("phase") == "coverage_verifier_to_claim_patcher"
    )
    packet = messages[boundary + 1]["content"]
    numbered = packet.split(
        "NUMBERED ACCEPTED DRAFT — PRESERVE UNPATCHED LINES\n", 1)[1]
    numbered = numbered.split("\n\nMATERIAL FINDINGS", 1)[0]
    numbered = numbered.split("\n", 1)[1]  # discard wordroom metadata
    draft = "\n".join(
        re.sub(r"^\d+: ?", "", line) for line in numbered.splitlines()
    ).strip()

    committed = set(output["trace"]["summary"]["context"]["committed"])
    sentences, errors, repairs = _parse_final_prose(draft, committed)
    if errors or sentences is None:
        raise RuntimeError(f"pre-patch draft failed contract parsing: {errors}")
    unit_refs, answer = _map_citations(sentences, committed)
    references, answer = _collapse_to_docs(unit_refs, answer)

    counterfactual = copy.deepcopy(output)
    counterfactual["metadata"]["run_id"] = RUN_ID
    counterfactual["metadata"]["run_desc"] = (
        "Exact accepted social-media draft before two deterministic claim "
        "patches; derived from the source trajectory for causal grading."
    )
    counterfactual["references"] = references
    counterfactual["answer"] = answer
    counterfactual["trace"]["status"] = "completed"
    counterfactual["trace"]["summary"]["causal_counterfactual"] = {
        "source_output": str(SOURCE_OUTPUT),
        "source_trajectory": str(SOURCE_TRAJECTORY),
        "intervention": "remove accepted claim patches only",
        "parser_repairs": repairs,
        "words": sum(len(item["text"].split()) for item in answer),
    }
    DESTINATION.write_text(
        json.dumps(counterfactual, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "run_id": RUN_ID,
        "destination": str(DESTINATION),
        "source_output": str(SOURCE_OUTPUT),
        "words": counterfactual["trace"]["summary"]
        ["causal_counterfactual"]["words"],
        "sentences": len(answer),
        "references": len(references),
        "parser_repairs": repairs,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
