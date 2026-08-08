"""Lean contract-prompt tests.

The executable candidate already carries an isolated plan, a row ledger, and
typed tools in its task context. These tests prevent the research system prompt
from regrowing the legacy planner and contradictory free-prose output contract.
"""
from __future__ import annotations

from aus_agent_v2.agent import load_system_prompt
from aus_agent_v2.answer_form import (
    AnswerFormPolicy,
    render_terminal_system_addendum,
)
from aus_agent_v2.coverage_contract import (
    commit_tool_with_contract,
    submit_answer_tool,
)


def test_lean_contract_prompt_keeps_outcomes_and_drops_legacy_scaffolding(
) -> None:
    """Sol receives one plan and one terminal contract instead of both twice."""
    default = load_system_prompt(10, "default")
    lean = load_system_prompt(10, "contract-lean")
    compact = " ".join(lean.split())

    assert len(lean.split()) < 600
    assert len(lean.split()) < len(default.split()) / 4
    assert lean.startswith("# Research agent")
    assert "coverage plan and an executable contract" in compact
    assert "Only committed evidence may support the terminal answer." in compact
    assert "Keep at most 10 exact result ids" in compact
    assert "write exactly one sentence per line" not in lean.casefold()
    assert "australia" not in lean.casefold()
    assert "aus agent" not in lean.casefold()


def test_contract_terminal_and_commit_rules_are_each_stated_once() -> None:
    """Tool fields own detailed mechanics while the system owns final behavior."""
    addendum = render_terminal_system_addendum(AnswerFormPolicy())
    tool = commit_tool_with_contract()
    submit = submit_answer_tool(AnswerFormPolicy())

    assert addendum.count("submit_answer") == 1
    assert "replaces the final free-prose turn described above" not in addendum
    assert len(tool["description"].split()) < 90
    assert "immediately following turn" in tool["description"]
    assert "every unlisted result is compacted" in tool["description"]
    assert "ADJUDICATE, DO NOT DE-DUPLICATE" not in tool["description"]
    assert "replaces a free-prose answer turn" not in submit["description"]
    assert "This is the only terminal response." in submit["description"]
    reason = (
        tool["input_schema"]["properties"]["documents"]["items"]["properties"]
        ["reason"]["description"]
    )
    assert "kept over a competing result" in reason
