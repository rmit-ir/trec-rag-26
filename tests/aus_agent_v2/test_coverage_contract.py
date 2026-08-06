"""Executable coverage-contract tests.

The contract is the only harness-owned link between planning, evidence
selection, and final prose.  These tests pin the failure modes that made the
older answer blueprint look mechanically healthy while silently dropping plan
items.
"""
from __future__ import annotations

from aus_agent_v2.answer_form import (
    AnswerFormPolicy,
    infer_answer_form_policy,
)
from aus_agent_v2.coverage_contract import (
    ContractItem,
    EvidenceAnchor,
    EvidenceLedger,
    build_coverage_contract,
    commit_tool_with_contract,
    normalize_commit_promotions,
    normalize_commit_supports,
    normalize_requirement_ids,
    render_contract_status,
    render_terminal_evidence_handoff,
    search_tool_with_contract,
    submit_answer_tool,
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


def test_markdown_bold_plan_labels_still_become_planner_rows() -> None:
    """Sol bolded three saved plans, which previously erased every primary row."""
    items = build_coverage_contract(
        "1. **DELIVERABLE:** Write one report.\n"
        "2. **EVIDENCE:** Find one measured result."
    )

    assert [(item.id, item.kind) for item in items] == [
        ("P01", "deliverable"),
        ("P02", "evidence"),
    ]


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
                "must_include": [
                    "Traditional contributions", "plan rules vary"],
            }],
        }],
    }

    supports, errors = normalize_commit_supports(arguments, contract())

    assert "supports" in doc_schema["properties"]
    support_schema = doc_schema["properties"]["supports"]["items"]["properties"]
    assert support_schema["claim"]["maxLength"] == 500
    assert support_schema["value_scope"]["maxLength"] == 300
    assert support_schema["must_include"]["maxItems"] == 4
    assert support_schema["must_include"]["items"]["maxLength"] == 80
    assert errors == []
    assert supports["P02"] == [EvidenceAnchor(
        "d1",
        "Traditional contributions can be tax deferred.",
        "US federal tax treatment; plan rules vary",
        ("Traditional contributions", "plan rules vary"),
    )]


def test_commit_can_promote_a_bounded_retrieval_discovered_atomic_row() -> None:
    """Facts found after planning need a stable executable path into the answer."""
    tool = commit_tool_with_contract(allow_promotions=True)
    arguments = {
        "documents": [{"id": "d1", "reason": "measured outcome"}],
        "promotions": [{
            "document_id": "d1",
            "kind": "evidence",
            "requirement": "Report the measured 12% outcome among adults",
            "must_mention": ["12%"],
            "minimum_count": 1,
            "claim": "The measured outcome was 12%.",
            "value_scope": "among adults",
            "must_include": ["12%", "among adults"],
        }],
    }

    additions, supports, errors = normalize_commit_promotions(
        arguments, contract(), eligible_document_ids={"d1"})

    assert "promotions" in tool["input_schema"]["required"]
    assert errors == []
    assert [(item.id, item.origin, item.minimum_count) for item in additions] == [
        ("D01", "retrieval", 1)]
    assert supports == {"D01": [EvidenceAnchor(
        "d1", "The measured outcome was 12%.", "among adults",
        ("12%", "among adults"),
    )]}


def test_dynamic_promotions_fail_as_a_batch_instead_of_dropping_rows() -> None:
    """Silent filtering would make the model believe a missing row was installed."""
    arguments = {
        "documents": [{"id": "d1", "reason": "result"}],
        "promotions": [{
            "document_id": "d1",
            "kind": "evidence",
            "requirement": "Report measured result",
            "must_mention": ["missing literal"],
            "minimum_count": 1,
            "claim": "A measured result was reported.",
            "must_include": ["measured result"],
        }],
    }

    additions, supports, errors = normalize_commit_promotions(
        arguments, contract(), eligible_document_ids={"d1"})

    assert additions == []
    assert supports == {}
    assert errors == [
        "promotion 1 must_mention term 'missing literal' does not occur "
        "exactly in its requirement"
    ]


def test_unknown_commit_mapping_is_rejected() -> None:
    """A globally committed document must not launder support for a fake row."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "S99",
                "claim": "A claim.",
                "must_include": ["claim"],
            }],
        }],
    }, contract())

    assert supports == {}
    assert errors == [
        "unknown coverage-contract id 'S99' in document 'd1'"]


def test_commit_support_can_cross_search_purpose_when_source_grounded() -> None:
    """A query purpose is not an ACL on other exact facts the page supplies."""
    supports = {
        "P02": [EvidenceAnchor(
            "d1", "Account tax treatment.", must_include=("traditional",))],
        "S01": [EvidenceAnchor(
            "d1", "The account name.", must_include=("401(k)",))],
    }
    staged = [{
        "id": "d1",
        "text": "A traditional account is named 401(k).",
        "metadata": {"for_requirements": ["P02"]},
    }]

    errors = validate_support_routes(supports, staged)

    assert errors == []


def test_commit_anchor_terms_must_exist_verbatim_in_the_source() -> None:
    """A model cannot invent a convenient value and make carry-through validate it."""
    supports = {
        "P02": [EvidenceAnchor(
            "d1", "Traffic changed.", must_include=("12%", "2025"))],
    }
    staged = [{
        "id": "d1",
        "text": "The evaluation reported a 9% change in 2024.",
        "metadata": {"for_requirements": ["P02"]},
    }]

    errors = validate_support_routes(supports, staged)

    assert errors == [
        "document 'd1' does not contain exact must_include term(s): 12%, 2025"
    ]


def test_commit_anchor_rejects_generic_fragments_and_substring_matches() -> None:
    """A generic verb or a number fragment cannot certify quantified scope."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "The study reported 12 observations.",
                "value_scope": "measured against the pre-toll baseline",
                "must_include": ["12", "pre-toll baseline"],
            }],
        }],
    }, contract())

    route_errors = validate_support_routes(supports, [{
        "id": "d1",
        "text": "The 120-person study used the pre-toll baseline.",
        "metadata": {"for_requirements": ["P02"]},
    }])

    assert errors == []
    assert supports["P02"][0].must_include == ("12", "pre-toll baseline")
    assert route_errors == [
        "document 'd1' does not contain exact must_include term(s): 12"
    ]

    mixed_supports, mixed_errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "The study reported a 12% change.",
                "must_include": ["reported", "12%"],
            }],
        }],
    }, contract())
    assert mixed_supports == {}
    assert any(
        "uninformative" in error and "reported" in error
        for error in mixed_errors
    )


def test_quantified_claim_literals_cannot_bypass_finish_the_claim() -> None:
    """Invented values formerly survived by omitting them from must_include."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "Traffic volumes fell by 12%.",
                "value_scope": "pre-toll baseline in 2025",
                "must_include": ["traffic volumes", "pre-toll baseline"],
            }],
        }],
    }, contract())

    assert supports == {}
    assert errors == [
        "document 'd1' support 1 must_include omits quantitative/date "
        "literal(s) stated in claim or value_scope: 12%, 2025"
    ]


def test_selected_quantified_literals_must_also_exist_in_the_source() -> None:
    """Selecting an invented number cannot make a complete-looking anchor valid."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "Traffic volumes fell by 12%.",
                "value_scope": "pre-toll baseline in 2025",
                "must_include": ["12%", "pre-toll baseline", "2025"],
            }],
        }],
    }, contract())
    route_errors = validate_support_routes(supports, [{
        "id": "d1",
        "text": "Traffic volumes were below the pre-toll baseline.",
        "metadata": {"for_requirements": ["P02"]},
    }])

    assert errors == []
    assert route_errors == [
        "document 'd1' does not contain exact must_include term(s): 12%, 2025"
    ]


def test_nonempty_scope_must_contribute_a_final_answer_literal() -> None:
    """Scope metadata must not disappear while only a headline value survives."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "The measured change was 12%.",
                "value_scope": "among Australian adults",
                "must_include": ["12%"],
            }],
        }],
    }, contract())

    assert supports == {}
    assert errors == [
        "document 'd1' support 1 value_scope contributes no exact textual "
        "must_include term"
    ]


def test_scope_year_does_not_stand_in_for_a_named_population() -> None:
    """A carried date must not let the population boundary disappear."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "The measured change was 12%.",
                "value_scope": "among adults in 2025",
                "must_include": ["12%", "2025"],
            }],
        }],
    }, contract())

    assert supports == {}
    assert errors == [
        "document 'd1' support 1 value_scope contributes no exact textual "
        "must_include term"
    ]


def test_negative_findings_are_material_exact_terms() -> None:
    """Rejecting “no evidence” erased a substantive saved study conclusion."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "The global study found no evidence of population harm.",
                "value_scope": "worldwide sample",
                "must_include": ["no evidence", "worldwide sample"],
            }],
        }],
    }, contract())

    assert errors == []
    assert supports["P02"][0].must_include == (
        "no evidence", "worldwide sample")


def test_oversized_anchor_text_is_rejected_without_prefix_truncation() -> None:
    """A truncated invariant can pass while changing what the model promised."""
    long_term = "complete source phrase " + ("x" * 70)
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": f"The finding was {long_term}.",
                "must_include": [long_term],
            }],
        }],
    }, contract())

    assert len(long_term) > 80
    assert supports == {}
    assert errors == [
        "document 'd1' support 1 has a "
        f"{len(long_term)}-character must_include term; maximum is 80; "
        "submit a shorter complete source-verbatim fragment"
    ]


def test_anchor_card_bounds_reject_whole_rows_instead_of_slicing_them() -> None:
    """Schema overflow must trigger bounded correction, not invisible data loss."""
    base = {
        "requirement_id": "P02",
        "claim": "A complete material claim.",
        "must_include": ["material claim"],
    }
    cases = [
        (
            [{**base, "claim": "x" * 501}],
            "document 'd1' support 1 claim is 501 characters; maximum is 500",
        ),
        (
            [{**base, "value_scope": "x" * 301}],
            "document 'd1' support 1 value_scope is 301 characters; maximum is 300",
        ),
        (
            [{**base, "must_include": ["one", "two", "three", "four", "five"]}],
            "document 'd1' support 1 has 5 must_include terms; maximum is 4",
        ),
        (
            [dict(base) for _ in range(13)],
            "document 'd1' has 13 supports; maximum is 12",
        ),
    ]
    for raw_supports, expected in cases:
        supports, errors = normalize_commit_supports({
            "documents": [{"id": "d1", "supports": raw_supports}],
        }, contract())

        assert supports == {}
        assert errors == [expected]


def test_material_anchor_allows_single_domain_terms_and_named_entities() -> None:
    """Materiality filtering must retain concise terms such as inflation and Cellpose."""
    supports, errors = normalize_commit_supports({
        "documents": [{
            "id": "d1",
            "supports": [{
                "requirement_id": "P02",
                "claim": "Cellpose estimates spatial gradients.",
                "value_scope": "performance under inflation",
                "must_include": ["Cellpose", "inflation"],
            }],
        }],
    }, contract())

    assert errors == []
    assert supports["P02"][0].must_include == ("Cellpose", "inflation")


def populated_ledger() -> EvidenceLedger:
    """Construct the smallest state that legitimately closes both factual rows."""
    ledger = EvidenceLedger()
    ledger.record_search(["P02", "S01"], "IRS 401k account tax treatment")
    ledger.record_supports({
        "P02": [EvidenceAnchor(
            "d1", "Traditional tax treatment.",
            must_include=("traditional", "plan rules"))],
        "S01": [EvidenceAnchor(
            "d1", "The account is named 401(k).",
            must_include=("401(k)",))],
    })
    return ledger


def valid_arguments() -> dict:
    """Represent labels, sourced content, and shared sentence coverage."""
    return {
        "answer_items": [
            {
                "kind": "prose",
                "text": "Blog post 1 — Start with the purpose of each account.",
                "evidence_ids": [],
                "satisfies": ["P01"],
            },
            {
                "kind": "prose",
                "text": (
                    "A traditional 401(k) can defer US federal income tax on "
                    "contributions, subject to plan rules."
                ),
                "evidence_ids": ["d1"],
                "satisfies": ["P02", "S01"],
            },
            {
                "kind": "prose",
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
    arguments["answer_items"] = arguments["answer_items"][:1]

    answer, errors, stats = validate_submission(
        arguments, contract(), populated_ledger(), {"d1"})

    assert answer is None
    assert any("P02, S01" in error for error in errors)
    assert stats["missing"] == ["P02", "S01"]


def test_citation_must_be_mapped_to_the_tagged_requirement() -> None:
    """Global citation eligibility is weaker than obligation-specific support."""
    ledger = populated_ledger()
    arguments = valid_arguments()
    arguments["answer_items"][1]["evidence_ids"] = ["d2"]

    answer, errors, _ = validate_submission(
        arguments, contract(), ledger, {"d1", "d2"})

    assert answer is None
    assert "answer item 2 has no evidence explicitly mapped to P02" in errors
    assert "answer item 2 has no evidence explicitly mapped to S01" in errors


def test_exact_term_must_appear_in_the_sentence_claiming_coverage() -> None:
    """A scout literal cannot survive only in trace while prose paraphrases it away."""
    arguments = valid_arguments()
    arguments["answer_items"][1]["text"] = (
        "A traditional employer plan can defer federal income tax."
    )

    answer, errors, _ = validate_submission(
        arguments, contract(), populated_ledger(), {"d1"})

    assert answer is None
    assert (
        "answer item 2 does not finish research row S01; include every exact "
        "term from one cited anchor: 401(k)"
    ) in errors
    assert "coverage row S01 is tagged but omits exact term(s): 401(k)" in errors


def test_finish_the_claim_requires_selected_anchor_terms_in_final_prose() -> None:
    """Commit-time facts must reach the answer instead of dying in pipeline state."""
    arguments = valid_arguments()
    arguments["answer_items"][1]["text"] = (
        "A traditional 401(k) can defer US federal income tax on contributions."
    )

    answer, errors, _ = validate_submission(
        arguments, contract(), populated_ledger(), {"d1"})

    assert answer is None
    assert (
        "answer item 2 does not finish research row P02; include every exact "
        "term from one cited anchor: traditional + plan rules"
    ) in errors


def test_unresolved_research_row_requires_a_real_tagged_attempt() -> None:
    """Unresolved is an evidence-gap outcome, not an escape from research."""
    arguments = valid_arguments()
    arguments["answer_items"] = arguments["answer_items"][:1]
    arguments["unresolved"] = ["P02", "S01"]

    answer, errors, _ = validate_submission(
        arguments, contract(), EvidenceLedger(), set())

    assert answer is None
    assert errors == [
        "unresolved research row P02 has no tagged search attempt",
        "unresolved research row S01 has no tagged search attempt",
    ]


def test_unresolved_cannot_discard_structure_or_committed_support() -> None:
    """Unresolved must represent missing evidence, not a general closure escape."""
    arguments = valid_arguments()
    arguments["answer_items"][0]["satisfies"] = []
    arguments["answer_items"][1]["satisfies"] = ["S01"]
    arguments["unresolved"] = ["P01", "P02"]

    answer, errors, _ = validate_submission(
        arguments, contract(), populated_ledger(), {"d1"})

    assert answer is None
    assert errors == [
        "structural coverage row P01 cannot be unresolved; satisfy it "
        "directly from the request",
        "unresolved research row P02 already has committed support; use its "
        "mapped anchor in the answer",
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


def test_counted_and_avoidance_rows_are_terminally_enforced() -> None:
    """Typed rows must protect list cardinality and penalties, not just row tags."""
    items = [
        ContractItem(
            "P01", "planner", "example", "Give two distinct examples",
            must_research=False, must_answer=True, minimum_count=2,
        ),
        ContractItem(
            "P02", "planner", "penalty", "Avoid a guarantee",
            must_research=False, must_answer=False, mode="avoid",
            must_avoid=("guaranteed returns",),
        ),
    ]
    arguments = {
        "answer_items": [{
            "kind": "prose",
            "text": "One example cannot promise guaranteed returns.",
            "evidence_ids": [],
            "satisfies": ["P01"],
        }],
        "unresolved": [],
    }

    answer, errors, stats = validate_submission(
        arguments, items, EvidenceLedger(), set())

    assert answer is None
    assert errors == [
        "coverage row P01 requires at least 2 distinct tagged answer items; "
        "found 1",
        "avoidance row P02 forbids exact term(s) present in the answer: "
        "guaranteed returns",
    ]
    assert stats["avoidance_rows"] == 1
    assert stats["counted_rows"] == 1


def test_terminal_handoff_replays_every_row_and_multiple_anchor_choices() -> None:
    """The final writer needs a complete recency transition, not a lossy status."""
    ledger = populated_ledger()
    ledger.record_supports({
        "P02": [
            EvidenceAnchor(
                f"d{index}", f"Alternative claim {index}.",
                must_include=(f"alternative {index}",),
            )
            for index in range(2, 5)
        ],
    })

    handoff = render_terminal_evidence_handoff(contract(), ledger)

    assert "TERMINAL EVIDENCE HANDOFF" in handoff
    assert "P01 ASSERT MIN=1" in handoff
    assert "P02 ASSERT MIN=1" in handoff
    assert "S01 ASSERT MIN=1" in handoff
    assert "CHOICE [d1] Traditional tax treatment." in handoff
    assert "CHOICE [d4] Alternative claim 4." in handoff
    assert "P03" not in handoff  # budget is not an answer obligation


def test_recency_status_replays_only_selected_bounded_anchors() -> None:
    """The final turn needs useful commit facts without another 35 KB blueprint."""
    ledger = populated_ledger()

    status = render_contract_status(contract(), ledger, max_chars=1_000)

    assert (
        "P02 SUPPORTED: [d1] Traditional tax treatment. | USE EXACT: "
        "traditional; plan rules"
    ) in status
    assert (
        "S01 SUPPORTED: [d1] The account is named 401(k). | USE EXACT: 401(k)"
    ) in status
    assert "P01 STRUCTURAL" in status
    assert len(status) <= 1_000


def test_python_policy_is_enabled_only_by_an_explicit_request() -> None:
    """Coding guidance must not become a generic format escape hatch."""
    explicit = infer_answer_form_policy(
        "Include Python code for the model and loss.")
    guidance = infer_answer_form_policy(
        "Explain how I can code and test an embedded processor.")

    assert explicit.python_code is True
    assert guidance.python_code is False


def test_python_item_preserves_indentation_operators_and_brackets() -> None:
    """The old prose parser corrupted all three otherwise compilable code blocks."""
    policy = AnswerFormPolicy(python_code=True)
    items = build_coverage_contract(
        "1. FORMAT: Include runnable Python.", answer_form=policy)
    code = (
        "class Block:\n"
        "    def __init__(self, values):\n"
        "        self.first = values[0]\n\n"
        "def loss(p, y):\n"
        "    return p * y + (1 - p) * (1 - y)\n"
    )
    arguments = {
        "answer_items": [{
            "kind": "code",
            "text": code,
            "evidence_ids": [],
            "satisfies": ["P01", "F01"],
        }],
        "unresolved": [],
    }

    answer, errors, stats = validate_submission(
        arguments, items, EvidenceLedger(), set(), answer_form=policy)

    assert errors == []
    assert answer == [{"text": code.rstrip("\n"), "citations": []}]
    assert stats["python_items"] == 1


def test_invalid_or_unrequested_python_is_rejected() -> None:
    """A typed code unit grants whitespace preservation, not unchecked content."""
    policy = AnswerFormPolicy(python_code=True)
    items = build_coverage_contract(
        "1. FORMAT: Include runnable Python.", answer_form=policy)
    invalid = {
        "answer_items": [{
            "kind": "code",
            "text": "def broken(:\n    pass",
            "evidence_ids": [],
            "satisfies": ["P01", "F01"],
        }],
        "unresolved": [],
    }

    answer, errors, _ = validate_submission(
        invalid, items, EvidenceLedger(), set(), answer_form=policy)
    unauthorized, unauthorized_errors, _ = validate_submission(
        invalid,
        build_coverage_contract("1. FORMAT: Explain the implementation."),
        EvidenceLedger(),
        set(),
    )

    assert answer is None
    assert any("Python syntax error" in error for error in errors)
    assert unauthorized is None
    assert any("not authorized" in error for error in unauthorized_errors)


def test_oversized_python_is_rejected_instead_of_truncated() -> None:
    """Acceptance must compile and emit the same complete source payload."""
    policy = AnswerFormPolicy(python_code=True)
    items = build_coverage_contract(
        "1. FORMAT: Include runnable Python.", answer_form=policy)
    code = "#" + ("x" * 8_000) + "\nraise RuntimeError('must remain')"
    arguments = {
        "answer_items": [{
            "kind": "code",
            "text": code,
            "evidence_ids": [],
            "satisfies": ["P01", "F01"],
        }],
        "unresolved": [],
    }

    answer, errors, _ = validate_submission(
        arguments, items, EvidenceLedger(), set(), answer_form=policy)

    assert answer is None
    assert any("hard maximum is 8000" in error for error in errors)


def test_explicit_python_request_cannot_close_with_prose_only() -> None:
    """Tagging a form row cannot masquerade as the requested implementation."""
    policy = AnswerFormPolicy(python_code=True)
    items = build_coverage_contract(
        "1. FORMAT: Include runnable Python.", answer_form=policy)
    arguments = {
        "answer_items": [{
            "kind": "prose",
            "text": "The implementation uses a class and a loss function.",
            "evidence_ids": [],
            "satisfies": ["P01", "F01"],
        }],
        "unresolved": [],
    }

    answer, errors, _ = validate_submission(
        arguments, items, EvidenceLedger(), set(), answer_form=policy)

    assert answer is None
    assert "coverage row F01 requires a code answer item" in errors
    assert "the request requires at least one valid Python code item" in errors


def test_series_policy_requires_distinct_plain_labels_without_markdown() -> None:
    """Repeated deliverables need visible identities without enabling headings."""
    policy = infer_answer_form_policy("Write a series of blog posts on saving.")
    items = build_coverage_contract(
        "1. DELIVERABLE: Write the requested series.", answer_form=policy)
    arguments = {
        "answer_items": [
            {
                "kind": "label",
                "text": "Blog post 1 — Start early",
                "evidence_ids": [],
                "satisfies": ["P01", "F01"],
            },
            {
                "kind": "label",
                "text": "Blog post 2 — Match the horizon",
                "evidence_ids": [],
                "satisfies": [],
            },
            {
                "kind": "label",
                "text": "Blog post 3 — Revisit the plan",
                "evidence_ids": [],
                "satisfies": [],
            },
        ],
        "unresolved": [],
    }

    answer, errors, stats = validate_submission(
        arguments, items, EvidenceLedger(), set(), answer_form=policy)

    assert errors == []
    assert answer is not None
    assert stats["label_items"] == 3


def test_series_policy_honors_count_and_rejects_duplicate_ordinals() -> None:
    """Different titles cannot disguise two copies of the same installment."""
    policy = infer_answer_form_policy(
        "Write a series of four blog posts about long-term saving.")
    items = build_coverage_contract(
        "1. DELIVERABLE: Write the requested series.", answer_form=policy)
    arguments = {
        "answer_items": [
            {
                "kind": "label",
                "text": f"Blog post {number} — Part {index}",
                "evidence_ids": [],
                "satisfies": ["P01", "F01"] if index == 1 else [],
            }
            for index, number in enumerate((1, 1, 2, 4), 1)
        ],
        "unresolved": [],
    }

    answer, errors, _ = validate_submission(
        arguments, items, EvidenceLedger(), set(), answer_form=policy)

    assert policy.minimum_labels == 4
    assert answer is None
    assert any("duplicates Blog post 1" in error for error in errors)
    assert any("missing 3" in error for error in errors)


def test_submit_tool_exposes_typed_items_and_request_gate() -> None:
    """The model must see a code-capable unit rather than a field named sentences."""
    tool = submit_answer_tool(AnswerFormPolicy(python_code=True))
    schema = tool["input_schema"]

    assert "answer_items" in schema["properties"]
    assert "sentences" not in schema["properties"]
    assert "raw Python code items" in tool["description"]
