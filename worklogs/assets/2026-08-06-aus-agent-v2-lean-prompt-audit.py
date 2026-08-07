#!/usr/bin/env python3
"""Capture every static model-facing input in the lean-contract intervention."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aus_agent.tools.commit_context import COMMIT_CONTEXT_TOOL
from aus_agent_v2.agent import load_system_prompt
from aus_agent_v2.answer_form import (
    AnswerFormPolicy,
    render_terminal_system_addendum,
)
from aus_agent_v2.coverage_contract import (
    ContractItem,
    commit_tool_with_contract,
    render_research_contract,
    submit_answer_tool,
)


def _metrics(text: str) -> dict[str, Any]:
    """Return stable size and identity fields for one exact input string."""
    return {
        "words": len(text.split()),
        "characters": len(text),
        "utf8_bytes": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    """Write one self-contained JSON record and print its audit summary."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    default = load_system_prompt(10, "default")
    lean = load_system_prompt(10, "contract-lean")
    terminal = render_terminal_system_addendum(AnswerFormPolicy())
    sample_contract = render_research_contract([
        ContractItem(
            id="P01",
            origin="plan",
            kind="evidence",
            requirement="Find a measured outcome and report its scope",
            must_mention=("12%", "trial population"),
            must_research=True,
            must_answer=True,
        ),
    ])
    base_commit = str(COMMIT_CONTEXT_TOOL["description"])
    lean_commit = str(commit_tool_with_contract()["description"])
    submit_description = str(
        submit_answer_tool(AnswerFormPolicy())["description"]
    )
    exact_inputs = {
        "default_system_prompt_max10": default,
        "lean_system_prompt_max10": lean,
        "lean_terminal_addendum_plain_prose": terminal,
        "research_contract_protocol_sample": sample_contract,
        "base_commit_tool_description": base_commit,
        "lean_contract_commit_tool_description": lean_commit,
        "lean_submit_answer_tool_description": submit_description,
    }
    combined = lean + "\n\n" + terminal
    checks = {
        "default_contains_internal_plan": "## Internal success plan" in default,
        "default_contains_free_prose_terminal": (
            "emit no tool calls and write the final report" in default
        ),
        "default_contains_sentence_per_line": (
            "Write exactly one sentence per line" in default
        ),
        "lean_contains_internal_plan_section": (
            "## Internal success plan" in lean
        ),
        "lean_contains_free_prose_terminal": (
            "emit no tool calls and write the final report" in lean
        ),
        "lean_contains_sentence_per_line": (
            "Write exactly one sentence per line" in lean
        ),
        "combined_contains_submit_answer": "submit_answer" in combined,
        "combined_mentions_australia_or_aus_agent": (
            "australia" in combined.casefold()
            or "aus agent" in combined.casefold()
        ),
        "submit_description_references_legacy_free_prose": (
            "replaces a free-prose answer turn" in submit_description
        ),
        "submit_description_has_single_terminal_route": (
            "This is the only terminal response." in submit_description
        ),
        "lean_is_under_one_quarter_default_words": (
            len(lean.split()) < len(default.split()) / 4
        ),
    }
    payload = {
        "method": (
            "Static exact-string audit only. No model, retrieval, provider, "
            "search, judge, or grader call. The sample contract makes the "
            "dynamic protocol observable but is not a dev-topic input."
        ),
        "exact_inputs": exact_inputs,
        "metrics": {name: _metrics(text) for name, text in exact_inputs.items()},
        "combined_lean_system_metrics": _metrics(combined),
        "checks": checks,
    }
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "output": str(args.output),
        "default": payload["metrics"]["default_system_prompt_max10"],
        "lean": payload["metrics"]["lean_system_prompt_max10"],
        "combined_lean_system": payload["combined_lean_system_metrics"],
        "base_commit": payload["metrics"]["base_commit_tool_description"],
        "lean_commit": payload["metrics"][
            "lean_contract_commit_tool_description"
        ],
        "checks": checks,
    }, indent=2))


if __name__ == "__main__":
    main()
