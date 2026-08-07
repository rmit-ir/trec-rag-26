"""Priority reconciliation for the primary plan and blind scout inventory."""
from __future__ import annotations

import json
import re
from typing import Any

from .coverage_plan import normalize_coverage_plan


PLAN_RECONCILE_SYSTEM = """\
You are the final plan compiler for a research system with a hard 1,024-word
answer limit. You receive the original request, a primary coverage plan, and an
independent scout inventory. Produce one compact execution contract for the
researcher; do not answer the request or state unsupported facts.

The primary plan and scout are proposals, not cumulative obligations. Resolve
overlap and priority instead of concatenating them. Preserve, in this order:
1. every explicit user component, deliverable form, audience constraint, and
   repeated per-part requirement;
2. safety, privacy, legal, temporal, and scope constraints whose omission could
   make the answer wrong or harmful;
3. the exact evidence types needed for central claims, including a concrete
   prior measurement when the request proposes a study or comparison;
4. up to six distinct latent expectations with the highest coverage gained per
   answer word, expressed as atomic observable units rather than broad themes.

The final organizer answer is plain prose. Internal plan components may guide
sentence order but must not become a requirement for visible headings,
sections, tables, bullets, or numbering unless the original request explicitly
asks for that presentation.

The scout inventory is an atomic obligation ledger. Preserve every applicable
`must_mention` string literally in the compiled contract and preserve an
`evidence` obligation's exact subject-outcome combination; a nearby generic
study is not equivalent. When exact precedent may be unavailable, require the
closest measured precedent with an explicit scope mismatch; a bare evidence-gap
sentence is not a substitute for research context. Treat `safety` and `penalty`
obligations as higher priority than optional latent breadth. Do not copy search
queries into the contract.

Drop optional breadth, duplicate formulations, exhaustive taxonomies, source
shopping, and deeper variants of an already-covered concept. Never let a
latent addition displace an explicit requirement, a novice definition, or a
legal/safety requirement. Prefer two compact observable checks over one broad
latent item when the broad wording would let the writer satisfy only half. For
a repeated tutorial, fund the requested elements inside each selected part
before adding more branches. For a board report, retain execution ownership
and economics without crowding out the requested country comparisons. For a
definite proof, retain both the conclusion and the few canonical named
mechanisms needed to explain it.

Return 8 to 14 numbered items under 450 words. Each item is one sentence of at
most 32 words and starts exactly like `1. DELIVERABLE: ...`, using one label:
DELIVERABLE, AUDIENCE, CORE, SAFETY, EVIDENCE, LATENT, or BUDGET. Do not bold
the label or omit its colon. Use no more than six LATENT items, each covering
one atomic expectation rather than a packed wishlist. The final BUDGET item
must allocate at most 860 first-draft words across the deliverable, reserving
the remaining track allowance for evidence-grounded completion patches. Return
only the compiled plan.
"""


def plan_reconcile_request(
    query: str,
    primary_plan: str,
    scout_audit: dict[str, Any],
) -> str:
    """Expose both independent proposals while keeping their provenance clear."""
    return (
        "ORIGINAL RESEARCH REQUEST\n\n"
        + query.strip()
        + "\n\nPRIMARY PLAN\n\n"
        + primary_plan.strip()
        + "\n\nCOMBINED ATOMIC SCOUT INVENTORY\n\n"
        + json.dumps(scout_audit.get("additions", []), ensure_ascii=False)
    )


def normalize_reconciled_plan(text: str | None) -> str | None:
    """Canonicalize harmless label syntax and reject malformed contracts."""
    normalized = normalize_coverage_plan(text, max_words=450)
    # Providers sometimes return ``**CORE:**`` or ``CORE explanation`` even
    # when the schema is explicit. Those are presentation differences, not an
    # unsafe semantic failure, so canonicalize them before validation. Unknown
    # labels still survive this pass and are rejected by ``allowed`` below.
    item_prefix = re.compile(
        r"^(\s*\d+\.\s+)\*{0,2}([A-Z]+):?\*{0,2}\s*:?\s*"
    )
    canonical_lines: list[str] = []
    for line in normalized.splitlines():
        match = item_prefix.match(line)
        if match:
            remainder = line[match.end():].lstrip()
            line = f"{match.group(1)}{match.group(2)}: {remainder}"
        canonical_lines.append(line)
    normalized = "\n".join(canonical_lines).strip()
    items = re.findall(r"(?m)^\s*\d+\.\s+([A-Z]+):", normalized)
    if not 8 <= len(items) <= 14:
        return None
    allowed = {
        "DELIVERABLE", "AUDIENCE", "CORE", "SAFETY", "EVIDENCE",
        "LATENT", "BUDGET",
    }
    if any(label not in allowed for label in items):
        return None
    if items.count("LATENT") > 6 or "BUDGET" not in items:
        return None
    budget_line = next(
        (line for line in normalized.splitlines() if "BUDGET:" in line), "")
    budget_match = re.search(
        r"\b(\d{2,4})\s+(?:first-draft\s+)?words\b",
        budget_line,
        flags=re.IGNORECASE,
    )
    if budget_match is None or int(budget_match.group(1)) > 860:
        return None
    for line in normalized.splitlines():
        if re.match(r"^\s*\d+\.", line) and len(line.split()) > 34:
            return None
    return normalized


def missing_must_mentions(
    plan: str | None,
    scout_audit: dict[str, Any],
) -> list[str]:
    """Return atomic exact terms a compiler silently dropped or paraphrased."""
    folded = (plan or "").casefold()
    missing: list[str] = []
    for item in scout_audit.get("additions", []):
        for mention in item.get("must_mention", []):
            if (isinstance(mention, str) and mention.strip()
                    and mention.casefold() not in folded
                    and mention not in missing):
                missing.append(mention)
    return missing
