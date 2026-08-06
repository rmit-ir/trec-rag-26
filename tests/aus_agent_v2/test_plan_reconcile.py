"""Priority compilation must bound scout breadth without losing hard obligations."""
from __future__ import annotations

from aus_agent_v2.plan_reconcile import (
    PLAN_RECONCILE_SYSTEM,
    missing_must_mentions,
    normalize_reconciled_plan,
    plan_reconcile_request,
)


VALID_PLAN = """\
1. DELIVERABLE: Produce the requested comparison in one concise report.
2. AUDIENCE: Define essential terms for a novice reader.
3. CORE: Compare both named countries using the same dimensions.
4. CORE: Preserve every explicit requested risk and recommendation.
5. SAFETY: State the governing privacy and legal constraints.
6. EVIDENCE: Include one concrete prior measurement with scope.
7. LATENT: Name the accountable implementation owner.
8. BUDGET: Allocate 840 first-draft words across comparison, evidence, risks, and actions.
"""


def test_request_keeps_primary_and_scout_provenance_separate() -> None:
    """The compiler must arbitrate proposals rather than inherit one as truth."""
    packet = plan_reconcile_request(
        "Compare two systems.",
        "1. CORE: compare them.",
        {"additions": [{"requirement": "Name the owner."}]},
    )

    assert "PRIMARY PLAN" in packet
    assert "COMBINED ATOMIC SCOUT INVENTORY" in packet
    assert "Name the owner" in packet


def test_normalizer_accepts_a_bounded_priority_contract() -> None:
    """A valid compiler result replaces the larger additive handoff."""
    assert normalize_reconciled_plan(VALID_PLAN) == VALID_PLAN.strip()


def test_normalizer_canonicalizes_harmless_provider_label_styles() -> None:
    """Formatting drift must not discard an otherwise valid priority decision."""
    varied = VALID_PLAN.replace(
        "1. DELIVERABLE:", "1. **DELIVERABLE:**"
    ).replace(
        "2. AUDIENCE:", "2. AUDIENCE"
    )

    normalized = normalize_reconciled_plan(varied)

    assert normalized is not None
    assert normalized.startswith("1. DELIVERABLE:")
    assert "2. AUDIENCE:" in normalized


def test_normalizer_rejects_too_many_latent_items() -> None:
    """Even atomic coverage must remain bounded under the report word limit."""
    overloaded = VALID_PLAN.replace(
        "8. BUDGET:",
        "8. LATENT: Add another hidden expectation.\n"
        "9. LATENT: Add a third hidden expectation.\n"
        "10. LATENT: Add a fourth hidden expectation.\n"
        "11. LATENT: Add a fifth hidden expectation.\n"
        "12. LATENT: Add a sixth hidden expectation.\n"
        "13. LATENT: Add a seventh hidden expectation.\n"
        "14. BUDGET:",
    )

    assert normalize_reconciled_plan(overloaded) is None


def test_normalizer_rejects_a_compiler_that_spends_patch_wordroom() -> None:
    """Without reserved space the deterministic completion stage cannot operate."""
    crowded = VALID_PLAN.replace(
        "840 first-draft words", "900 first-draft words")

    assert normalize_reconciled_plan(crowded) is None


def test_exact_scout_terms_are_a_post_compile_gate() -> None:
    """A fluent compiler paraphrase must not erase an atomic named obligation."""
    audit = {"additions": [{
        "must_mention": ["HIPAA Privacy Rule", "IRB"],
    }]}

    assert missing_must_mentions(VALID_PLAN, audit) == [
        "HIPAA Privacy Rule", "IRB"]
    assert missing_must_mentions(
        VALID_PLAN + "\nThe HIPAA Privacy Rule and IRB apply.", audit) == []


def test_prompt_prioritizes_explicit_and_safety_before_latent_breadth() -> None:
    """Priority must be an execution rule rather than aspirational wording."""
    assert "latent addition displace" in " ".join(
        PLAN_RECONCILE_SYSTEM.split())
    assert "up to six distinct latent expectations" in PLAN_RECONCILE_SYSTEM
    assert "at most 860 first-draft words" in PLAN_RECONCILE_SYSTEM
    assert "hard 1,024-word" in PLAN_RECONCILE_SYSTEM
    assert "Do not bold" in PLAN_RECONCILE_SYSTEM
    assert "must_mention" in PLAN_RECONCILE_SYSTEM
    assert "subject-outcome combination" in PLAN_RECONCILE_SYSTEM
