"""Claim completion may add evidence but cannot erase unrelated coverage."""
from __future__ import annotations

import json

from aus_agent_v2.claim_finish import (
    apply_claim_patches,
    build_claim_finish_packet,
)


DRAFT = """\
The study requires institutional privacy review. [privacy_doc]
A prior EHR study measured disease prevalence in a large cohort. [old_doc]
The extraction pipeline uses manual validation. [method_doc]
"""


def test_replacement_preserves_claim_and_adds_atomic_named_constraint() -> None:
    """Generic privacy prose should become an explicit rule without a rewrite."""
    response = json.dumps({"patches": [{
        "finding": 1,
        "mode": "replace",
        "line": 1,
        "sentence": (
            "The study requires institutional privacy review under the HIPAA "
            "Privacy Rule. [privacy_doc]"
        ),
    }]})

    patched, stats, errors = apply_claim_patches(
        DRAFT, response, {1: {"privacy_doc"}})

    assert "HIPAA Privacy Rule" in patched
    assert patched.splitlines()[1:] == DRAFT.strip().splitlines()[1:]
    assert stats == {"proposed": 1, "accepted": 1, "rejected": 0}
    assert errors == []


def test_insertion_adds_one_cited_measurement_without_touching_draft() -> None:
    """A genuinely absent precedent can be appended beside the related point."""
    response = json.dumps({"patches": [{
        "finding": 2,
        "mode": "insert_after",
        "line": 2,
        "sentence": (
            "An Asian-subgroup lupus cohort reported the requested scoped "
            "measurement. [asian_doc]"
        ),
    }]})

    patched, stats, _errors = apply_claim_patches(
        DRAFT, response, {2: {"asian_doc"}})

    assert patched.splitlines()[0:2] == DRAFT.strip().splitlines()[0:2]
    assert patched.splitlines()[2].endswith("[asian_doc]")
    assert stats["accepted"] == 1


def test_replacement_that_discards_original_point_is_rejected() -> None:
    """A patch model cannot use one finding as permission for a new answer."""
    response = json.dumps({"patches": [{
        "finding": 1,
        "mode": "replace",
        "line": 1,
        "sentence": "A completely different market claim appears. [privacy_doc]",
    }]})

    patched, stats, errors = apply_claim_patches(
        DRAFT, response, {1: {"privacy_doc"}})

    assert patched == DRAFT.strip()
    assert stats["accepted"] == 0
    assert any("preserve" in error for error in errors)


def test_citation_only_patch_cannot_change_sensitive_synthesis_words() -> None:
    """A risk guard may ground a conclusion but must not rewrite its meaning."""
    draft = (
        "Adolescents face greater mental-health risk under passive use.\n"
        "The next claim remains unchanged. [other_doc]"
    )
    response = json.dumps({"patches": [{
        "finding": 1,
        "mode": "cite",
        "line": 1,
        "sentence": (
            "Adolescents face greater mental-health risk under passive use. "
            "[health_doc]"
        ),
    }]})

    patched, stats, errors = apply_claim_patches(
        draft, response, {1: {"health_doc"}})

    assert patched.splitlines()[0].endswith("[health_doc]")
    assert patched.splitlines()[1] == draft.splitlines()[1]
    assert stats["accepted"] == 1
    assert errors == []


def test_citation_only_patch_rejects_even_a_helpful_rephrase() -> None:
    """Citation authority is not authority to strengthen a medical conclusion."""
    draft = "Social comparison may affect some adolescents."
    response = json.dumps({"patches": [{
        "finding": 1,
        "mode": "cite",
        "line": 1,
        "sentence": (
            "Social comparison harms most adolescents. [health_doc]"
        ),
    }]})

    patched, stats, errors = apply_claim_patches(
        draft, response, {1: {"health_doc"}})

    assert patched == draft
    assert stats["accepted"] == 0
    assert any("citation-only" in error for error in errors)


def test_packet_recovers_page_locality_from_parent_output_citation() -> None:
    """Saved parent docids must still route a repair to the originally cited page."""
    draft = (
        "A prior EHR study measured autoimmune prevalence in a large cohort. "
        "[shard_02084_76011]"
    )
    audit = {"missing": [{
        "requirement": "Give the closest measured autoimmune prevalence precedent",
        "draft_gap": (
            "The draft needs the result and an explicit mismatch with the "
            "requested detailed Asian subgroup"
        ),
    }]}
    documents = {
        "shard_02084_76011_p2": {
            "text": (
                "CPRD Aurum covered about 20% of England and reported annual "
                "incidence and point prevalence for rheumatoid arthritis, "
                "psoriatic arthritis, and axial spondyloarthritis from 2004 "
                "to 2020; it did not report detailed Asian subgroups."
            ),
        },
        "shard_99999_1_p1": {
            "text": (
                "Asian subgroup autoimmune prevalence is an important missing "
                "measurement in electronic health record research."
            ),
        },
    }

    built = build_claim_finish_packet(
        "Research autoimmune prevalence in Asian patients.",
        draft,
        audit,
        documents,
        documents_per_finding=1,
    )

    assert built is not None
    packet, allowed = built
    assert allowed[1] == {"shard_02084_76011_p2"}
    assert "CPRD Aurum" in packet


def test_scoped_precedent_can_expand_an_incomplete_claim() -> None:
    """A precise result should pass despite replacing prose with standard acronyms."""
    draft = (
        "A large English EHR study measured rheumatoid-arthritis incidence "
        "and point prevalence, but I could not establish a published "
        "autoimmune-prevalence study jointly covering the detailed U.S. "
        "Asian categories above. [english_parent]"
    )
    response = json.dumps({"patches": [{
        "finding": 1,
        "mode": "replace",
        "line": 1,
        "sentence": (
            "Closest precedents: England's CPRD EHRs, covering 20% of the "
            "population, found RA incidence fell 40.1% in 2019–2020; RISE NLP "
            "analyzed 854,628 patients, but neither measured detailed-Asian "
            "prevalence. [english_page]"
        ),
    }]})

    patched, stats, errors = apply_claim_patches(
        draft, response, {1: {"english_page"}})

    assert "40.1%" in patched
    assert stats["accepted"] == 1
    assert errors == []
