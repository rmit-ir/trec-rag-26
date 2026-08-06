#!/usr/bin/env python3
"""Replay the saved U-Net draft through old and new terminal projections.

No generation, retrieval, or judging occurs.  The script extracts the exact
``exec("...")`` payloads that Sol already wrote in the frozen full-30 winner,
compiles them before and after the old prose projection, and then submits the
raw payloads through the new typed contract validator.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from aus_agent_v2.answer_form import AnswerFormPolicy
from aus_agent_v2.coverage_contract import (
    EvidenceLedger,
    build_coverage_contract,
    validate_submission,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / (
    "data/outputs/aus_agent_v2/"
    "20260807T002205962434+1000.pre_repair_counterfactual.output.json"
)
EXEC_RE = re.compile(r'exec\(("(?:\\.|[^"\\])*")\)')


def payloads(text: str) -> list[str]:
    """Decode Python string literals embedded in the model's prose wrapper."""
    return [ast.literal_eval(match.group(1)) for match in EXEC_RE.finditer(text)]


def compile_result(code: str) -> str:
    """Return a stable one-line syntax verdict without executing model code."""
    try:
        compile(code, "<replayed-python>", "exec")
    except SyntaxError as exc:
        return f"FAIL line {exc.lineno}: {exc.msg}"
    return "PASS"


def main() -> None:
    """Print the complete comparison and terminal-preservation verdict."""
    output = json.loads(ARTIFACT.read_text())
    raw_step = next(
        step for step in reversed(output["trace"]["steps"])
        if step.get("type") == "generation"
        and isinstance(step.get("output"), dict)
        and "exec(" in str(step["output"].get("text") or "")
    )
    raw_text = raw_step["output"]["text"]
    strict_texts = [
        item["text"] for item in output["answer"] if "exec(" in item["text"]
    ]
    raw = payloads(raw_text)
    strict = [code for text in strict_texts for code in payloads(text)]
    if len(raw) != 3 or len(strict) != 3:
        raise RuntimeError(
            f"expected three raw and strict code blocks, got {len(raw)}/{len(strict)}"
        )

    policy = AnswerFormPolicy(python_code=True)
    contract = build_coverage_contract(
        "1. FORMAT: Include runnable Python model, loss, and decoder code.",
        answer_form=policy,
    )
    combined = "\n\n".join(raw)
    submitted, errors, stats = validate_submission(
        {
            "answer_items": [{
                "kind": "code",
                "text": combined,
                "evidence_ids": [],
                "satisfies": ["P01", "F01"],
            }],
            "unresolved": [],
        },
        contract,
        EvidenceLedger(),
        set(),
        answer_form=policy,
    )

    print(f"artifact: {ARTIFACT.relative_to(ROOT)}")
    print(f"qid: {output['metadata']['narrative_id']}")
    print(f"raw generation step: {raw_step['id']}")
    print()
    print("| block | raw Sol draft | old strict answer |")
    print("|---|---|---|")
    for index, (raw_code, strict_code) in enumerate(zip(raw, strict), 1):
        print(
            f"| {index} | {compile_result(raw_code)} | "
            f"{compile_result(strict_code)} |"
        )
    print()
    print(f"combined raw code: {compile_result(combined)}")
    print(
        "old projection removed __init__: "
        f"{('__init__' in raw[0]) and ('__init__' not in strict[0])}"
    )
    print(
        "old projection removed multiplication: "
        f"{('p*y' in raw[1]) and ('p*y' not in strict[1])}"
    )
    print(
        "old projection removed decoder [0]: "
        f"{('ndi.label(m)[0]' in raw[2]) and ('ndi.label(m)[0]' not in strict[2])}"
    )
    print(f"new typed terminal accepted: {submitted is not None}")
    print(f"new typed terminal errors: {json.dumps(errors)}")
    print(f"new typed terminal python_items: {stats.get('python_items')}")
    print(
        "new typed terminal byte preservation: "
        f"{bool(submitted and submitted[0]['text'] == combined)}"
    )


if __name__ == "__main__":
    main()
