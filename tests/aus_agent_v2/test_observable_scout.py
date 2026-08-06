"""The second planning lens must add atomic checks without becoming evidence."""
from __future__ import annotations

import json

from aus_agent_v2.observable_scout import (
    OBSERVABLE_SCOUT_SYSTEM,
    combine_obligation_audits,
    normalize_observable_scout,
    observable_scout_request,
)


def test_request_exposes_existing_inventory_to_prevent_duplicate_checks() -> None:
    """A complementary scout is useful only when it knows what not to repeat."""
    packet = observable_scout_request(
        "Assess a policy.",
        "1. CORE: compare outcomes.",
        {"additions": [{"requirement": "Name the governing law."}]},
    )

    assert "PRIMARY PLAN" in packet
    assert "SEMANTIC OBLIGATIONS ALREADY FOUND" in packet
    assert "Name the governing law" in packet


def test_normalizer_uses_the_smaller_second_lens_limits() -> None:
    """A second recall pass must not double the prompt with another long list."""
    raw = json.dumps({
        "verdict": "add",
        "additions": [{
            "kind": "term",
            "requirement": f"Name observable item {index}.",
            "must_mention": ["one", "two", "three"],
            "reason": "It is independently checkable.",
            "search_leads": ["one query", "second query"],
        } for index in range(8)],
    })

    audit = normalize_observable_scout(raw)

    assert len(audit["additions"]) == 6
    assert all(len(item["must_mention"]) == 2 for item in audit["additions"])
    assert all(len(item["search_leads"]) == 1 for item in audit["additions"])


def test_combiner_preserves_distinct_lenses_and_drops_exact_retries() -> None:
    """The compiler needs both kinds of unit but should not pay twice for one."""
    semantic = {"verdict": "add", "additions": [{
        "requirement": "Name the governing privacy rule.",
        "must_mention": ["HIPAA"],
    }]}
    observable = {"verdict": "add", "additions": [
        {
            "requirement": "Name the governing privacy rule.",
            "must_mention": ["HIPAA"],
        },
        {
            "requirement": "Name one usable open-source NLP library.",
            "must_mention": ["spaCy"],
        },
    ]}

    combined = combine_obligation_audits(semantic, observable)

    assert len(combined["additions"]) == 2
    assert combined["additions"][1]["must_mention"] == ["spaCy"]


def test_prompt_forbids_answers_and_demands_sentence_level_checks() -> None:
    """Planning-time prior knowledge may propose searches but cannot ground facts."""
    compact = " ".join(OBSERVABLE_SCOUT_SYSTEM.split())

    assert "Do not answer the request" in OBSERVABLE_SCOUT_SYSTEM
    assert "sentence granularity" in OBSERVABLE_SCOUT_SYSTEM
    assert "at most six additions" in OBSERVABLE_SCOUT_SYSTEM
    assert "one complete record-to-result walkthrough" in compact
    assert "post-level feedback" not in compact
