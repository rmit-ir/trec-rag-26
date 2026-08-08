"""Coverage planning stays bounded before it enters two downstream contexts."""
from __future__ import annotations

from aus_agent_v2.coverage_plan import (
    COVERAGE_PLAN_SYSTEM,
    coverage_plan_request,
    normalize_coverage_plan,
)


def test_request_preserves_the_user_text_without_domain_hints() -> None:
    """The planner should discover implied needs rather than receive rubric clues."""
    query = "Write two beginner posts comparing retirement and house savings."

    assert coverage_plan_request(query).endswith(query)


def test_normalizer_removes_a_fence_and_caps_reused_plan_text() -> None:
    """Unbounded planner output would be paid for in research and review alike."""
    raw = "```text\n1. DELIVERABLE: two posts\n2. AUDIENCE: beginner\n```"

    assert normalize_coverage_plan(raw, max_chars=30) == (
        "1. DELIVERABLE: two posts")


def test_normalizer_enforces_the_planner_word_budget_without_flattening() -> None:
    """A model that ignores the prompt cap must not crowd the research turn."""
    raw = "1. BUDGET: one two three\n2. EVIDENCE: four five six"

    assert normalize_coverage_plan(raw, max_words=6) == (
        "1. BUDGET: one two three")


def test_planner_operationalizes_repeated_and_conceptual_deliverables() -> None:
    """Unstated counts and canonical concepts caused two repeatable coverage gaps."""
    prompt = " ".join(COVERAGE_PLAN_SYSTEM.split())
    assert 'a "series" means at least three parts' in prompt
    assert "at least two in every part" in prompt
    assert "illustrative thought experiment" in prompt
    assert "resource constraints" in prompt
