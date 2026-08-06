"""Atomic-plan boundaries prevent broad prose rows from masquerading as closure.

The candidate is deliberately not wired into the live pipeline yet. These tests
defend its isolated prompt and normal form so later integration cannot admit a
partial, silently truncated, or presentation-authorizing obligation inventory.
"""
from __future__ import annotations

import json

from aus_agent_v2.atomic_plan import (
    ATOMIC_PLAN_SYSTEM,
    MAX_REQUIREMENT_CHARS,
    atomic_plan_request,
    normalize_atomic_plan,
)


def assert_row(index: int, **changes: object) -> dict[str, object]:
    """Build one valid unique row so each test changes only its target invariant."""
    row: dict[str, object] = {
        "mode": "assert",
        "kind": "evidence",
        "requirement": f"Report measured outcome {index}",
        "must_mention": [],
        "minimum_count": 1,
        "must_research": True,
        "must_answer": True,
    }
    row.update(changes)
    return row


def avoid_row(index: int, **changes: object) -> dict[str, object]:
    """Build a negative constraint whose absence from prose is intentional."""
    row: dict[str, object] = {
        "mode": "avoid",
        "kind": "penalty",
        "requirement": f"Avoid unsupported generalization {index}",
        "must_avoid": [f"unsupported generalization {index}"],
        "must_research": False,
        "must_answer": False,
    }
    row.update(changes)
    return row


def packet(rows: list[dict[str, object]]) -> str:
    """Serialize exactly the top-level shape advertised to the planner."""
    return json.dumps({"rows": rows})


def test_request_exposes_only_the_original_request() -> None:
    """Prior plans or hidden criteria would anchor the candidate on old bundles."""
    assert atomic_plan_request("  Compare A and B.  ") == (
        "ORIGINAL RESEARCH REQUEST\n\nCompare A and B."
    )


def test_prompt_requires_atomic_typed_rows_without_authorizing_markdown() -> None:
    """Structure is a coverage protocol, not permission to change answer form."""
    compact = " ".join(ATOMIC_PLAN_SYSTEM.split())

    assert "Return 10 to 24 rows total" in ATOMIC_PLAN_SYSTEM
    assert "exactly one binary check" in ATOMIC_PLAN_SYSTEM
    assert '"mode":"assert"' in ATOMIC_PLAN_SYSTEM
    assert '"mode":"avoid"' in ATOMIC_PLAN_SYSTEM
    assert "Every assert row has `must_answer` true" in ATOMIC_PLAN_SYSTEM
    assert "Avoid rows are constraints" in ATOMIC_PLAN_SYSTEM
    assert "do not authorize presentation syntax" in compact
    assert "do not invent Markdown, headings, tables, bullets" in compact


def test_valid_inventory_returns_contract_compatible_row_dicts() -> None:
    """Downstream compilation needs explicit closure flags without an import cycle."""
    rows = [assert_row(index) for index in range(9)] + [avoid_row(9)]
    rows[0] = assert_row(
        0,
        kind="comparison",
        requirement="Compare treatment A with treatment B",
        must_mention=["Treatment A", "Treatment B"],
        minimum_count=2,
    )

    normalized = normalize_atomic_plan(packet(rows))

    assert len(normalized) == 10
    assert normalized[0] == {
        "mode": "assert",
        "kind": "comparison",
        "requirement": "Compare treatment A with treatment B",
        "must_mention": ["Treatment A", "Treatment B"],
        "minimum_count": 2,
        "must_research": True,
        "must_answer": True,
    }
    assert normalized[-1]["must_answer"] is False
    assert normalized[-1]["must_avoid"] == ["unsupported generalization 9"]


def test_malformed_envelopes_and_row_count_overflow_fail_closed() -> None:
    """A partial plan is more dangerous than retrying an invalid planning turn."""
    ten = [assert_row(index) for index in range(10)]

    assert normalize_atomic_plan("not JSON") == []
    assert normalize_atomic_plan("```json\n{}\n```") == []
    assert normalize_atomic_plan(json.dumps(ten)) == []
    assert normalize_atomic_plan(json.dumps({"rows": ten, "note": "extra"})) == []
    assert normalize_atomic_plan(packet(ten[:9])) == []
    assert normalize_atomic_plan(
        packet([assert_row(index) for index in range(25)])) == []


def test_any_invalid_row_rejects_the_whole_inventory() -> None:
    """Filtering one bad obligation would silently erase expected answer coverage."""
    cases = [
        assert_row(0, kind="penalty"),
        assert_row(0, must_answer=False),
        assert_row(0, must_research="yes"),
        assert_row(0, minimum_count=True),
        assert_row(0, minimum_count=51),
        {**assert_row(0), "reason": "unexpected key"},
    ]
    for invalid in cases:
        rows = [invalid] + [assert_row(index) for index in range(1, 10)]
        assert normalize_atomic_plan(packet(rows)) == []


def test_strings_terms_and_atomic_clause_bounds_reject_without_slicing() -> None:
    """Truncation or clause dropping would change the obligation being enforced."""
    invalid_rows = [
        assert_row(0, requirement="x" * (MAX_REQUIREMENT_CHARS + 1)),
        assert_row(0, requirement="Report A; report B"),
        assert_row(0, requirement="Report A. Report B"),
        assert_row(0, requirement="Compare treatment A, treatment B, and placebo"),
        assert_row(0, requirement="Report safety and explain efficacy"),
        assert_row(0, must_mention=["one", "two", "three", "four"]),
        assert_row(0, must_mention=["x" * 81]),
    ]
    for invalid in invalid_rows:
        rows = [invalid] + [assert_row(index) for index in range(1, 10)]
        assert normalize_atomic_plan(packet(rows)) == []


def test_initialisms_do_not_create_false_sentence_boundaries() -> None:
    """Names such as U.S. must remain usable literals in one atomic comparison."""
    rows = [assert_row(index) for index in range(10)]
    rows[0] = assert_row(
        0,
        kind="comparison",
        requirement="Compare U.S. outcomes with Australian outcomes",
        must_mention=["U.S.", "Australian"],
    )

    normalized = normalize_atomic_plan(packet(rows))

    assert normalized[0]["requirement"] == (
        "Compare U.S. outcomes with Australian outcomes"
    )


def test_duplicates_collapse_before_the_minimum_is_enforced() -> None:
    """Repeated wording must not inflate a nine-obligation plan past the gate."""
    rows = [assert_row(index) for index in range(10)]
    duplicate = assert_row(
        99,
        requirement="  REPORT   MEASURED outcome 0  ",
        must_mention=["Alpha", "alpha", "Beta"],
    )

    normalized = normalize_atomic_plan(packet(rows + [duplicate]))
    too_small_after_dedup = normalize_atomic_plan(packet(rows[:9] + [duplicate]))

    assert len(normalized) == 10
    assert too_small_after_dedup == []


def test_literal_terms_are_deduplicated_without_losing_first_spelling() -> None:
    """Case-only repeats waste anchor capacity but must not rewrite exact literals."""
    rows = [assert_row(index) for index in range(10)]
    rows[0] = assert_row(
        0, must_mention=["HIPAA", "hipaa", "Privacy Rule"])

    normalized = normalize_atomic_plan(packet(rows))

    assert normalized[0]["must_mention"] == ["HIPAA", "Privacy Rule"]


def test_avoid_rows_require_specific_terms_and_false_closure_flags() -> None:
    """A penalty constraint must never become prose required for answer closure."""
    invalid_avoids = [
        avoid_row(0, must_answer=True),
        avoid_row(0, must_research=True),
        avoid_row(0, must_avoid=[]),
        avoid_row(0, kind="safety"),
        {**avoid_row(0), "minimum_count": 1},
    ]
    for invalid in invalid_avoids:
        rows = [assert_row(index) for index in range(9)] + [invalid]
        assert normalize_atomic_plan(packet(rows)) == []


def test_more_than_four_avoid_rows_fail_closed() -> None:
    """Penalty prediction must not crowd positive claim union out of the word cap."""
    rows = [assert_row(index) for index in range(5)] + [
        avoid_row(index) for index in range(5, 10)
    ]

    assert normalize_atomic_plan(packet(rows)) == []
