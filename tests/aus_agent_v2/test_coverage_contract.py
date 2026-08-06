"""Executable coverage-contract tests.

The contract is the only harness-owned link between planning, evidence
selection, and final prose.  These tests pin the failure modes that made the
older answer blueprint look mechanically healthy while silently dropping plan
items.
"""
from __future__ import annotations

from aus_agent_v2.coverage_contract import (
    EvidenceAnchor,
    EvidenceLedger,
    build_coverage_contract,
    commit_tool_with_contract,
    normalize_commit_supports,
    normalize_requirement_ids,
    render_contract_status,
    search_tool_with_contract,
    validate_support_routes,
    validate_submission,
)


PLAN = """\
1. DELIVERABLE: Produce three distinguishable beginner blog posts.
2. EVIDENCE: Compare account tax treatment with current US sources.
3. BUDGET: Allocate at most 900 words across the posts.
4. SCOUT: Name the employer account explicitly EXACT: 401(k) SEARCH: 401k IRS tax treatment.
"""


def contract():
    """Keep each test on the same realistic planner-plus-scout boundary."""
    return build_coverage_contract(PLAN)


def test_plan_and_scout_receive_stable_distinct_ids() -> None:
    """Flattening scout text into prose previously discarded its exact terms."""
    items = contract()

    assert [item.id for item in items] == ["P01", "P02", "P03", "S01"]
    assert items[0].must_research is False
    assert items[1].must_research is True
    assert items[2].must_answer is False
    assert items[3].must_mention == ("401(k)",)
    assert "SEARCH:" not in items[3].requirement


def test_structured_scout_kind_survives_the_prose_merge() -> None:
    """Penalty avoidance is a constraint, not content the answer must assert."""
    items = build_coverage_contract(PLAN, [{
        "kind": "penalty",
        "requirement": "Avoid promising guaranteed investment returns.",
        "must_mention": [],
    }])

    assert [item.id for item in items] == ["P01", "P02", "P03", "S01"]
    assert items[-1].kind == "penalty"
    assert items[-1].must_answer is False
    assert items[-1].must_research is False


def test_search_schema_requires_coverage_purpose() -> None:
    """A query without a row id cannot later prove a planned evidence attempt."""
    base = {
        "name": "search",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }

    enriched = search_tool_with_contract(base)

    assert enriched["input_schema"]["required"] == [
        "query", "for_requirements"]
    assert "for_requirements" not in base["input_schema"]["properties"]


def test_unknown_search_requirement_is_rejected_before_dispatch() -> None:
    """Typos must not create phantom closure state around an unsearched row."""
    requirement_ids, errors = normalize_requirement_ids(
        ["P02", "P99", "P02"], contract())

    assert requirement_ids == ["P02"]
    assert errors == ["unknown coverage-contract id 'P99'"]


def test_commit_schema_and_normalizer_preserve_bounded_source_anchor() -> None:
    """Commit-time facts become useful only when tied to an actual obligation."""
    tool = commit_tool_with_contract()
    doc_schema = tool["input_schema"]["properties"]["documents"]["items"]
    arguments = {
        "documents": [{
            "id": "d1",
            "reason": "tax treatment",
            "supports": [{
                "requirement_id": "P02",
                "claim": "Traditional contributions can be tax deferred.",
                "value_scope": "US federal tax treatment; plan rules vary",
            }],
        }],
    }

    supports, errors = normalize_commit_supports(arguments, contract())

    assert "supports" in doc_schema["properties"]
    assert errors == []
    assert supports["P02"] == [EvidenceAnchor(
        "d1",
        "Traditional contributions can be tax deferred.",
        "US federal tax treatment; plan rules vary",
    )]


def test_unknown_commit_mapping_is_rejected() -> None:
    """A globally committed document must not launder support for a fake row."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{"requirement_id": "S99", "claim": "A claim."}],
        }],
    }, contract())

    assert supports == {}
    assert errors == [
        "unknown coverage-contract id 'S99' in document 'd1'"]


def test_commit_support_must_follow_the_search_route() -> None:
    """A page found for one issue cannot silently close an unrelated obligation."""
    supports = {
        "P02": [EvidenceAnchor("d1", "Account tax treatment.")],
        "S01": [EvidenceAnchor("d1", "The account name.")],
    }
    staged = [{
        "id": "d1",
        "metadata": {"for_requirements": ["P02"]},
    }]

    errors = validate_support_routes(supports, staged)

    assert errors == ["document 'd1' was not retrieved for coverage row S01"]


def populated_ledger() -> EvidenceLedger:
    """Construct the smallest state that legitimately closes both factual rows."""
    ledger = EvidenceLedger()
    ledger.record_search(["P02", "S01"], "IRS 401k account tax treatment")
    ledger.record_supports({
        "P02": [EvidenceAnchor("d1", "Traditional tax treatment.")],
        "S01": [EvidenceAnchor("d1", "The account is named 401(k).")],
    })
    return ledger


def valid_arguments() -> dict:
    """Represent labels, sourced content, and shared sentence coverage."""
    return {
        "sentences": [
            {
                "text": "Blog post 1 — Start with the purpose of each account.",
                "evidence_ids": [],
                "satisfies": ["P01"],
            },
            {
                "text": (
                    "A traditional 401(k) can defer US federal income tax on "
                    "contributions, subject to plan rules."
                ),
                "evidence_ids": ["d1"],
                "satisfies": ["P02", "S01"],
            },
            {
                "text": "The choice also depends on withdrawal timing.",
                "evidence_ids": ["d1"],
                "satisfies": [],
            },
        ],
        "unresolved": [],
    }


def test_one_item_submission_cannot_pass_a_multi_item_plan() -> None:
    """The former blueprint accepted one valid requirement against twenty."""
    arguments = valid_arguments()
    arguments["sentences"] = arguments["sentences"][:1]

    answer, errors, stats = validate_submission(
        arguments, contract(), populated_ledger(), {"d1"})

    assert answer is None
    assert any("P02, S01" in error for error in errors)
    assert stats["missing"] == ["P02", "S01"]


def test_citation_must_be_mapped_to_the_tagged_requirement() -> None:
    """Global citation eligibility is weaker than obligation-specific support."""
    ledger = populated_ledger()
    arguments = valid_arguments()
    arguments["sentences"][1]["evidence_ids"] = ["d2"]

    answer, errors, _ = validate_submission(
        arguments, contract(), ledger, {"d1", "d2"})

    assert answer is None
    assert "sentence 2 has no evidence explicitly mapped to P02" in errors
    assert "sentence 2 has no evidence explicitly mapped to S01" in errors


def test_exact_term_must_appear_in_the_sentence_claiming_coverage() -> None:
    """A scout literal cannot survive only in trace while prose paraphrases it away."""
    arguments = valid_arguments()
    arguments["sentences"][1]["text"] = (
        "A traditional employer plan can defer federal income tax."
    )

    answer, errors, _ = validate_submission(
        arguments, contract(), populated_ledger(), {"d1"})

    assert answer is None
    assert errors == [
        "coverage row S01 is tagged but omits exact term(s): 401(k)"]


def test_unresolved_research_row_requires_a_real_tagged_attempt() -> None:
    """Unresolved is an evidence-gap outcome, not an escape from research."""
    arguments = valid_arguments()
    arguments["sentences"] = arguments["sentences"][:1]
    arguments["unresolved"] = ["P02", "S01"]

    answer, errors, _ = validate_submission(
        arguments, contract(), EvidenceLedger(), set())

    assert answer is None
    assert errors == [
        "unresolved research row P02 has no tagged search attempt",
        "unresolved research row S01 has no tagged search attempt",
    ]


def test_valid_submission_keeps_untagged_synthesis_sentence() -> None:
    """Coverage routing must not atomize away transitions and integrated judgment."""
    answer, errors, stats = validate_submission(
        valid_arguments(), contract(), populated_ledger(), {"d1"})

    assert errors == []
    assert answer is not None
    assert answer[-1] == {
        "text": "The choice also depends on withdrawal timing.",
        "citations": ["d1"],
    }
    assert stats["satisfied"] == 3
    assert stats["missing"] == []


def test_recency_status_replays_only_selected_bounded_anchors() -> None:
    """The final turn needs useful commit facts without another 35 KB blueprint."""
    ledger = populated_ledger()

    status = render_contract_status(contract(), ledger, max_chars=1_000)

    assert "P02 SUPPORTED: [d1] Traditional tax treatment." in status
    assert "S01 SUPPORTED: [d1] The account is named 401(k)." in status
    assert "P01 STRUCTURAL" in status
    assert len(status) <= 1_000
