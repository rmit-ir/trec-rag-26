"""Hermetic semantic-closure boundary tests.

The verifier is allowed to influence a final answer only through a bounded,
row-complete typed packet.  These tests defend the projections and strict
normalization rules that keep a malformed or overreaching judgment from
becoming a repair instruction.
"""
from __future__ import annotations

import copy
import json

import pytest

from aus_agent_v2.coverage_contract import (
    ContractItem,
    EvidenceAnchor,
    EvidenceLedger,
    build_semantic_answer_items,
    build_semantic_check_records,
)
from aus_agent_v2.semantic_closure import (
    MAX_DIAGNOSIS_CHARS,
    MAX_SEMANTIC_CHECKS,
    MAX_SEMANTIC_PACKET_CHARS,
    SEMANTIC_CLOSURE_SYSTEM,
    SEMANTIC_CLOSURE_TOOL,
    normalize_semantic_closure,
    render_semantic_closure_findings,
    semantic_closure_request,
    semantic_revision_errors,
)


def _contract_item(
    check_id: str,
    *,
    minimum_count: int = 1,
    must_research: bool = True,
    kind: str = "evidence",
) -> ContractItem:
    """Construct only the row fields relevant to semantic projection."""
    return ContractItem(
        id=check_id,
        origin="plan",
        kind=kind,
        requirement=f"Requirement for {check_id}",
        minimum_count=minimum_count,
        must_research=must_research,
    )


def _normalization_record(
    check_id: str,
    item_indices: list[int],
    *,
    must_research: bool = False,
    minimum_count: int = 1,
    evidence_ids: tuple[str, ...] = (),
    context_evidence_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    """Make a minimal trusted record for verifier-output validation."""
    return {
        "check_id": check_id,
        "repairable_item_indices": item_indices,
        "row": {
            "must_research": must_research,
            "minimum_count": minimum_count,
        },
        "evidence": [
            {"document_id": document_id} for document_id in evidence_ids
        ],
        "context_evidence": [
            {"document_id": document_id}
            for document_id in context_evidence_ids
        ],
    }


def _check(
    check_id: str,
    verdict: str,
    *,
    closure: str,
    support: str,
    count: str,
    failure_codes: list[str] | None = None,
    item_indices: list[int] | None = None,
    evidence_ids: list[str] | None = None,
    diagnosis: str = "",
) -> dict[str, object]:
    """Spell every required tool field so tests exercise the real schema."""
    return {
        "check_id": check_id,
        "verdict": verdict,
        "closure": closure,
        "support": support,
        "count": count,
        "failure_codes": failure_codes or [],
        "item_indices": item_indices or [],
        "evidence_ids": evidence_ids or [],
        "diagnosis": diagnosis,
    }


def _structural_pass(check_id: str) -> dict[str, object]:
    """Return the only valid pass labels for a one-item nonresearch row."""
    return _check(
        check_id,
        "pass",
        closure="complete",
        support="not_applicable",
        count="not_applicable",
    )


def test_semantic_answer_items_preserve_typed_order_with_bounded_fields() -> None:
    """The audit must see stable submission ordinals without unbounded metadata."""
    arguments = {
        "answer_items": [
            {
                "kind": " PROSE ",
                "text": "  Alpha   answers\n the row.  ",
                "evidence_ids": ["d1", "d2", "d3", "d4"],
                "satisfies": [f"P{index:02d}" for index in range(1, 10)],
            },
            {
                "kind": "code",
                "text": "\r\nprint('a')\r\nprint('b')\r\n",
                "evidence_ids": [],
                "satisfies": ["P10"],
            },
        ],
    }

    projected = build_semantic_answer_items(arguments)

    assert projected == [
        {
            "item_index": 1,
            "kind": "prose",
            "text": "Alpha answers the row.",
            "evidence_ids": ["d1", "d2", "d3"],
            "satisfies": [f"P{index:02d}" for index in range(1, 9)],
        },
        {
            "item_index": 2,
            "kind": "code",
            "text": "print('a')\nprint('b')",
            "evidence_ids": [],
            "satisfies": ["P10"],
        },
    ]


def test_multi_item_row_becomes_one_aggregate_check_packet() -> None:
    """A minimum-count obligation must be judged as a whole, not fragmented."""
    item = _contract_item("P01", minimum_count=2)
    arguments = {
        "answer_items": [
            {
                "kind": "prose",
                "text": "Alpha reduced latency by 20 percent.",
                "evidence_ids": ["d1"],
                "satisfies": ["P01"],
            },
            {
                "kind": "prose",
                "text": "Beta reduced errors by 30 percent.",
                "evidence_ids": ["d2"],
                "satisfies": ["P01"],
            },
        ],
    }
    ledger = EvidenceLedger(anchors={
        "P01": [
            EvidenceAnchor(
                "d1",
                "Alpha reduced latency.",
                must_include=("Alpha", "20 percent"),
                source_quote="Alpha reduced latency by 20 percent.",
            ),
            EvidenceAnchor(
                "d2",
                "Beta reduced errors.",
                must_include=("Beta", "30 percent"),
                source_quote="Beta reduced errors by 30 percent.",
            ),
        ],
    })

    records = build_semantic_check_records(arguments, [item], ledger)

    assert len(records) == 1
    record = records[0]
    assert record["check_id"] == "P01"
    assert record["scope"] == "row_aggregate"
    assert record["candidate_item_indices"] == [1, 2]
    assert record["repairable_item_indices"] == [1, 2]
    assert record["deterministic_state"]["distinct_item_count"] == 2
    assert [entry["document_id"] for entry in record["evidence"]] == ["d1", "d2"]
    assert [entry["item_indices"] for entry in record["evidence"]] == [[1], [2]]


def test_shared_sentence_is_projected_independently_for_each_row() -> None:
    """Each row owns support while seeing anchors for the sentence's other clause."""
    arguments = {
        "answer_items": [{
            "kind": "prose",
            "text": "Alpha reduced latency while Beta reduced errors.",
            "evidence_ids": ["d1", "d2"],
            "satisfies": ["P01", "P02"],
        }],
    }
    ledger = EvidenceLedger(anchors={
        "P01": [EvidenceAnchor(
            "d1",
            "Alpha reduced latency.",
            must_include=("Alpha", "latency"),
            source_quote="Alpha reduced latency.",
        )],
        "P02": [EvidenceAnchor(
            "d2",
            "Beta reduced errors.",
            must_include=("Beta", "errors"),
            source_quote="Beta reduced errors.",
        )],
    })

    records = build_semantic_check_records(
        arguments,
        [_contract_item("P01"), _contract_item("P02")],
        ledger,
    )

    assert [record["check_id"] for record in records] == ["P01", "P02"]
    assert [record["candidate_item_indices"] for record in records] == [[1], [1]]
    assert [record["scope"] for record in records] == ["row_item", "row_item"]
    assert [
        [entry["document_id"] for entry in record["evidence"]]
        for record in records
    ] == [["d1"], ["d2"]]
    assert [
        [entry["document_id"] for entry in record["context_evidence"]]
        for record in records
    ] == [["d2"], ["d1"]]


def test_global_row_can_target_any_visible_answer_item() -> None:
    """A whole-answer defect must not be visible yet impossible to repair."""
    arguments = {
        "answer_items": [{
            "kind": "prose",
            "text": "This guide is for clinicians.",
            "evidence_ids": [],
            "satisfies": ["P01"],
        }, {
            "kind": "prose",
            "text": "The unexplained acronym XYZ appears here.",
            "evidence_ids": [],
            "satisfies": ["P02"],
        }],
    }

    [record] = build_semantic_check_records(
        arguments,
        [_contract_item("P01", must_research=False, kind="audience")],
        EvidenceLedger(),
    )

    assert record["scope"] == "answer_global"
    assert record["candidate_item_indices"] == [1]
    assert record["repairable_item_indices"] == [1, 2]


def test_semantic_evidence_exposes_available_source_provenance() -> None:
    """Evidence-type judgments need the retrieval provenance the harness has."""
    arguments = {"answer_items": [{
        "kind": "prose",
        "text": "Alpha reduced latency by 20 percent.",
        "evidence_ids": ["d1"],
        "satisfies": ["P01"],
    }]}
    ledger = EvidenceLedger(anchors={"P01": [EvidenceAnchor(
        "d1",
        "Alpha reduced latency.",
        must_include=("Alpha", "20 percent"),
        source_quote="Alpha reduced latency by 20 percent.",
    )]})
    documents = {"d1": {
        "id": "d1", "docid": "parent-1", "kind": "chunk",
        "metadata": {
            "source": "semantic", "query": "alpha trial",
            "publisher": "Example Institute",
        },
    }}

    [record] = build_semantic_check_records(
        arguments, [_contract_item("P01")], ledger, documents)

    evidence = record["evidence"][0]
    assert evidence["parent_docid"] == "parent-1"
    assert evidence["document_kind"] == "chunk"
    assert evidence["source_provenance"] == {
        "source": "semantic",
        "query": "alpha trial",
        "publisher": "Example Institute",
    }


def test_evidence_projection_requires_source_anchor_terms_in_its_candidate() -> None:
    """A cited document cannot lend an unrelated quote to the sentence packet."""
    arguments = {
        "answer_items": [{
            "kind": "prose",
            "text": "Alpha reduced latency by 20 percent.",
            "evidence_ids": ["d1", "d2"],
            "satisfies": ["P01"],
        }],
    }
    ledger = EvidenceLedger(anchors={
        "P01": [
            EvidenceAnchor(
                "d1",
                "Alpha reduced latency.",
                must_include=("Alpha", "20 percent"),
                source_quote="Local quote supporting Alpha's 20 percent result.",
            ),
            EvidenceAnchor(
                "d2",
                "Gamma increased throughput.",
                must_include=("Gamma", "throughput"),
                source_quote="Unrelated quote about Gamma throughput.",
            ),
        ],
    })

    [record] = build_semantic_check_records(
        arguments, [_contract_item("P01")], ledger)

    assert record["evidence"] == [{
        "document_id": "d1",
        "claim": "Alpha reduced latency.",
        "source_quote": "Local quote supporting Alpha's 20 percent result.",
        "value_scope": "",
        "must_include": ["Alpha", "20 percent"],
        "item_indices": [1],
    }]


def test_evidence_projection_reports_bounded_omissions() -> None:
    """A packet that drops excess anchors must declare itself incomplete."""
    arguments = {"answer_items": [{
        "kind": "prose",
        "text": "Alpha reduced latency by 20 percent.",
        "evidence_ids": ["d1"],
        "satisfies": ["P01"],
    }]}
    ledger = EvidenceLedger(anchors={"P01": [
        EvidenceAnchor(
            "d1",
            f"Alpha claim {index}.",
            must_include=("Alpha",),
            source_quote=f"Alpha source quote {index}.",
        )
        for index in range(13)
    ]})

    [record] = build_semantic_check_records(
        arguments, [_contract_item("P01")], ledger)

    assert len(record["evidence"]) == 12
    assert record["deterministic_state"]["projection_complete"] is False
    assert record["deterministic_state"]["projection_omissions"] == {
        "row_evidence": 1,
        "context_evidence": 0,
    }


def test_normalizer_accepts_strict_pass_reject_and_abstain_rows() -> None:
    """Mixed judgments retain row order while a clear defect controls repair."""
    records = [
        _normalization_record("P01", [1]),
        _normalization_record(
            "P02", [2], must_research=True, evidence_ids=("d2",)),
        _normalization_record(
            "P03", [3, 4], must_research=True, minimum_count=2,
            evidence_ids=("d3",),
        ),
    ]
    checks = [
        _check(
            "P03",
            "abstain",
            closure="unclear",
            support="unclear",
            count="unclear",
            diagnosis="The excerpts do not resolve the aggregate comparison.",
        ),
        _structural_pass("P01"),
        _check(
            "P02",
            "reject",
            closure="partial",
            support="partial",
            count="not_applicable",
            failure_codes=["CLOSURE_PARTIAL", "SOURCE_PARTIAL"],
            item_indices=[2],
            evidence_ids=["d2"],
            diagnosis="The answer omits a material qualification.",
        ),
    ]

    audit = normalize_semantic_closure({"checks": checks}, records)

    assert audit["verdict"] == "repair"
    assert audit["parse_error"] is False
    assert [check["check_id"] for check in audit["checks"]] == ["P01", "P02", "P03"]
    assert [check["check_id"] for check in audit["failures"]] == ["P02"]
    assert [check["check_id"] for check in audit["abstentions"]] == ["P03"]


def test_incomplete_packet_abstains_instead_of_becoming_a_repair() -> None:
    """Missing context is uncertainty, never a failure code aimed at prose."""
    check = _check(
        "P01",
        "abstain",
        closure="unclear",
        support="not_applicable",
        count="not_applicable",
        diagnosis="The packet lacks enough context to judge this row.",
    )

    audit = normalize_semantic_closure(
        {"checks": [check]}, [_normalization_record("P01", [1])])

    assert audit["verdict"] == "abstain"
    assert audit["parse_error"] is False
    failure_enum = (
        SEMANTIC_CLOSURE_TOOL["input_schema"]["properties"]["checks"]
        ["items"]["properties"]["failure_codes"]["items"]["enum"]
    )
    assert "PACKET_INCOMPLETE" not in failure_enum


def test_reject_requires_a_failing_dimension_and_matching_code() -> None:
    """An arbitrary code cannot turn all-pass semantic labels into a repair."""
    check = _check(
        "P01",
        "reject",
        closure="complete",
        support="not_applicable",
        count="not_applicable",
        failure_codes=["CLOSURE_PARTIAL"],
        item_indices=[1],
        diagnosis="A claimed defect with no failing label.",
    )

    audit = normalize_semantic_closure(
        {"checks": [check]}, [_normalization_record("P01", [1])])

    assert audit["verdict"] == "indeterminate"
    assert any(
        "no failing semantic dimension" in error for error in audit["errors"])


def test_reject_cannot_target_context_only_evidence() -> None:
    """Neighboring-row quotes explain clauses but cannot indict this row's source."""
    check = _check(
        "P01",
        "reject",
        closure="complete",
        support="unsupported",
        count="not_applicable",
        failure_codes=["SOURCE_UNSUPPORTED"],
        item_indices=[1],
        evidence_ids=["d-context"],
        diagnosis="The neighboring quote does not support this row.",
    )
    record = _normalization_record(
        "P01",
        [1],
        must_research=True,
        evidence_ids=("d-owned",),
        context_evidence_ids=("d-context",),
    )

    audit = normalize_semantic_closure({"checks": [check]}, [record])

    assert audit["verdict"] == "indeterminate"
    assert audit["errors"] == ["check P01 names out-of-scope evidence"]


def test_scope_overreach_is_valid_for_nonresearch_partial_closure() -> None:
    """A request-scope defect must not need a fictional source-support failure."""
    check = _check(
        "P01",
        "reject",
        closure="partial",
        support="not_applicable",
        count="not_applicable",
        failure_codes=["SCOPE_OVERREACH"],
        item_indices=[1],
        diagnosis="The answer changes the requested temporal boundary.",
    )

    audit = normalize_semantic_closure(
        {"checks": [check]}, [_normalization_record("P01", [1])])

    assert audit["verdict"] == "repair"
    assert audit["failures"][0]["failure_codes"] == ["SCOPE_OVERREACH"]


@pytest.mark.parametrize(
    ("check", "error_fragment"),
    [
        (
            _check(
                "P01",
                "pass",
                closure="complete",
                support="direct_entailment",
                count="not_applicable",
            ),
            "nonresearch support must be not_applicable",
        ),
        (
            _check(
                "P01",
                "reject",
                closure="unclear",
                support="not_applicable",
                count="not_applicable",
                failure_codes=["CLOSURE_PARTIAL"],
                item_indices=[1],
                diagnosis="The closure is uncertain.",
            ),
            "uncertainty must abstain",
        ),
        (
            _check(
                "P01",
                "abstain",
                closure="unclear",
                support="not_applicable",
                count="not_applicable",
                item_indices=[1],
                diagnosis="The request is ambiguous.",
            ),
            "must not assign failures or repair targets",
        ),
    ],
)
def test_normalizer_rejects_internally_inconsistent_verdicts(
    check: dict[str, object],
    error_fragment: str,
) -> None:
    """Malformed labels must fail closed before they can target answer prose."""
    audit = normalize_semantic_closure(
        {"checks": [check]}, [_normalization_record("P01", [1])])

    assert audit["verdict"] == "indeterminate"
    assert audit["parse_error"] is True
    assert any(error_fragment in error for error in audit["errors"])


@pytest.mark.parametrize(
    ("checks", "error_fragment"),
    [
        ([_structural_pass("P01")], "missing semantic check_id(s): P02"),
        (
            [
                _structural_pass("P01"),
                _structural_pass("P01"),
                _structural_pass("P02"),
            ],
            "duplicates check_id 'P01'",
        ),
        (
            [
                _structural_pass("P01"),
                _structural_pass("P02"),
                _structural_pass("P99"),
            ],
            "unknown check_id 'P99'",
        ),
    ],
)
def test_normalizer_rejects_incomplete_or_ambiguous_row_identity(
    checks: list[dict[str, object]],
    error_fragment: str,
) -> None:
    """The verifier cannot silently omit, repeat, or invent a coverage row."""
    records = [
        _normalization_record("P01", [1]),
        _normalization_record("P02", [2]),
    ]

    audit = normalize_semantic_closure({"checks": checks}, records)

    assert audit["verdict"] == "indeterminate"
    assert audit["checks"] == []
    assert any(error_fragment in error for error in audit["errors"])


def test_semantic_revision_may_change_only_explicit_repair_targets() -> None:
    """A correction opportunity must not become permission for a broad rewrite."""
    original = {
        "answer_items": [
            {"kind": "prose", "text": "Keep one."},
            {"kind": "prose", "text": "Repair two."},
            {"kind": "prose", "text": "Keep three."},
        ],
        "unresolved": [{"requirement_id": "P04", "reason": "No evidence."}],
    }
    revision = copy.deepcopy(original)
    revision["answer_items"][1]["text"] = "Repaired two."

    assert semantic_revision_errors(original, revision, {2}) == []

    revision["answer_items"][0]["text"] = "Rewritten one."
    assert semantic_revision_errors(original, revision, {2}) == [
        "semantic correction changed unflagged answer item 1"]


def test_semantic_revision_cannot_reroute_a_flagged_item() -> None:
    """The writer may fix wording but cannot swap its obligation or evidence."""
    original = {
        "answer_items": [{
            "kind": "prose",
            "text": "Original claim.",
            "evidence_ids": ["d1"],
            "satisfies": ["P01"],
        }],
        "unresolved": [],
    }
    revision = copy.deepcopy(original)
    revision["answer_items"][0].update({
        "text": "Rerouted claim.",
        "evidence_ids": ["d2"],
        "satisfies": ["P02"],
    })

    assert semantic_revision_errors(original, revision, {1}) == [
        "semantic correction changed routing metadata for flagged answer "
        "item 1; only text may change"]


def test_semantic_findings_replay_named_rejected_quote() -> None:
    """The correction turn needs the exact source target the verifier rejected."""
    audit = {"failures": [{
        "check_id": "P01",
        "failure_codes": ["SOURCE_UNSUPPORTED"],
        "item_indices": [1],
        "evidence_ids": ["d1"],
        "diagnosis": "The conclusion exceeds the quote.",
    }]}
    records = [{
        "check_id": "P01",
        "row": {"requirement": "Report the observed result."},
        "evidence": [{
            "document_id": "d1",
            "source_quote": "Traffic remained below the pre-toll baseline.",
        }],
        "context_evidence": [],
    }]

    findings = render_semantic_closure_findings(audit, records)

    assert "evidence d1" in findings
    assert "Traffic remained below the pre-toll baseline." in findings


@pytest.mark.parametrize(
    ("mutate", "error_fragment"),
    [
        (
            lambda revision: revision["answer_items"].append(
                {"kind": "prose", "text": "Extra item."}),
            "preserve the answer item count and ordering",
        ),
        (
            lambda revision: revision.update({"unresolved": []}),
            "preserve the unresolved inventory",
        ),
    ],
)
def test_semantic_revision_preserves_packet_structure(
    mutate,
    error_fragment: str,
) -> None:
    """Item cardinality and unresolved state remain owned by deterministic checks."""
    original = {
        "answer_items": [{"kind": "prose", "text": "Original."}],
        "unresolved": [{"requirement_id": "P02", "reason": "Unavailable."}],
    }
    revision = copy.deepcopy(original)
    mutate(revision)

    errors = semantic_revision_errors(original, revision, {1})

    assert any(error_fragment in error for error in errors)


def test_semantic_request_is_complete_compact_and_fails_over_its_bound() -> None:
    """Oversized audit context must be explicit instead of silently truncated."""
    packet_text = semantic_closure_request(
        "  Compare\n alpha   and beta. ",
        [{"item_index": 1, "text": "Complete answer."}],
        [{"check_id": "P01"}],
    )

    assert len(packet_text) <= MAX_SEMANTIC_PACKET_CHARS
    assert json.loads(packet_text) == {
        "packet_version": "semantic-row-v1",
        "original_request": "Compare alpha and beta.",
        "answer_items": [{"item_index": 1, "text": "Complete answer."}],
        "checks": [{"check_id": "P01"}],
    }
    with pytest.raises(ValueError, match=r"maximum is 60000"):
        semantic_closure_request(
            "request",
            [{"item_index": 1, "text": "x" * MAX_SEMANTIC_PACKET_CHARS}],
            [{"check_id": "P01"}],
        )


def test_semantic_prompt_and_tool_expose_complete_bounded_protocol() -> None:
    """Prompt drift must not restore rewriting or permit partial row inventories."""
    checks_schema = SEMANTIC_CLOSURE_TOOL["input_schema"]["properties"]["checks"]
    result_schema = checks_schema["items"]

    assert checks_schema["maxItems"] == MAX_SEMANTIC_CHECKS
    assert result_schema["properties"]["diagnosis"]["maxLength"] == MAX_DIAGNOSIS_CHARS
    assert result_schema["additionalProperties"] is False
    assert SEMANTIC_CLOSURE_SYSTEM.count("exactly once") == 1
    assert "one result for every check_id" in SEMANTIC_CLOSURE_SYSTEM
    assert "One answer sentence may legitimately pass several rows" in SEMANTIC_CLOSURE_SYSTEM
    assert "several candidate" in SEMANTIC_CLOSURE_SYSTEM
    assert "Do not answer the request, rewrite prose" in SEMANTIC_CLOSURE_SYSTEM
