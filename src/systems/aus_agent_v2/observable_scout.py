"""Complementary scout for literal, countable answer-completeness checks.

The blind obligation scout recalls the important concepts.  This second pass
sees that inventory and looks for a different failure mode: small observable
units that disappear when a sound concept is compressed into one broad plan
item.  It still has no evidence and cannot answer the request.
"""
from __future__ import annotations

import json
from typing import Any

from .plan_critic import normalize_plan_critique


OBSERVABLE_SCOUT_SYSTEM = """\
You are the observable-completeness scout for a research system. You receive
the original request, the primary plan, and a semantic obligation inventory
from another independent scout. Find only material, independently scoreable
answer units that those inputs still leave implicit. Do not answer the request,
state facts, or treat your own knowledge as evidence.

Work at sentence granularity. A proposed check must be satisfiable by one
compact sentence or clause and must have a clear yes/no test in the finished
answer. Prefer checks involving an explicit count, literal name, worked link,
contrast, scope qualifier, or repeated per-part requirement. Do not return a
broad instruction such as "be comprehensive", "give more detail", or "consider
limitations". Do not repeat an existing check in narrower wording.

Use the request's answer archetype as a recall aid:
- For a novice research guide, test for expanded acronyms, named usable
  software, concrete structured and unstructured input examples, one complete
  record-to-result walkthrough, alternative analysis methods, named governing
  mechanisms, enough domain examples to make the study real, and the requested
  task order.
- For a society-wide judgment, test for the requested number of domains and a
  positive, negative, mechanism, and evidence unit in each; named platforms or
  cases from more than one relevant region; a justified time/geography and
  counterfactual; short- versus long-run effects; demographic heterogeneity;
  major technology transitions such as mobile access, ranking, or feedback;
  and a direct contrast between relevant regulatory environments.
- For a board strategy, test for named owners, measurable product edge,
  economics and capital gates, government programs, risk triggers, milestones,
  and long-term strategic options.
- For a proof or possibility answer, test for the exact conclusion, named
  definitions and limits, one end-to-end derivation or counterexample, standard
  dynamics, resource assumptions, and the boundary between conditional and
  universal claims.
- For a tutorial or series, test the requested part count and ensure every part
  gets its own definition, worked example, variation or alternative, pitfall,
  takeaway, and explicit link to earlier parts.

These prompts are not a checklist to copy. Select only checks material to the
actual request. When a named term or example must appear literally, put it in
`must_mention`; otherwise use an empty list. Search phrases are not obligations.
Do not lower a count or relax the request. Rank by expected evaluation value
per answer word.

Return JSON only in exactly one of these shapes:
{"verdict":"pass","additions":[]}
{"verdict":"add","additions":[{"kind":"term|evidence|mechanism|comparison|scope|safety|format|penalty","requirement":"one atomic observable requirement","must_mention":["exact term"],"reason":"why the current inventories can miss it","search_leads":["one compact retrieval query"]}]}

Return at most six additions. Keep each requirement under 28 words, each reason
under 30 words, at most two exact terms, and at most one search lead. Do not
combine independent checks with a list joined by "and". Do not wrap the JSON
in Markdown.
"""


def observable_scout_request(
    query: str,
    primary_plan: str,
    semantic_audit: dict[str, Any],
) -> str:
    """Show what is already covered so the second lens must be complementary."""
    return (
        "ORIGINAL RESEARCH REQUEST\n\n"
        + query.strip()
        + "\n\nPRIMARY PLAN\n\n"
        + primary_plan.strip()
        + "\n\nSEMANTIC OBLIGATIONS ALREADY FOUND\n\n"
        + json.dumps(semantic_audit.get("additions", []), ensure_ascii=False)
    )


def normalize_observable_scout(text: str | None) -> dict[str, Any]:
    """Apply the shared fail-closed schema with the smaller second-pass cap."""
    return normalize_plan_critique(
        text,
        max_additions=6,
        max_leads=1,
        max_mentions=2,
    )


def combine_obligation_audits(
    semantic_audit: dict[str, Any],
    observable_audit: dict[str, Any],
    *,
    max_additions: int = 14,
) -> dict[str, Any]:
    """Combine both ranked lenses while dropping only obvious duplicates."""
    combined: list[dict[str, Any]] = []
    fingerprints: set[tuple[str, tuple[str, ...]]] = set()
    for audit in (semantic_audit, observable_audit):
        for item in audit.get("additions", []):
            requirement = str(item.get("requirement", "")).strip()
            mentions = tuple(
                sorted(str(value).strip().casefold()
                       for value in item.get("must_mention", []) if value)
            )
            words = tuple(
                word for word in requirement.casefold().split()
                if len(word) > 3
            )
            # Exact terms are the strongest identity.  With no exact term,
            # matching the first six content words catches near-identical
            # retries without attempting unsafe semantic deduplication.
            fingerprint = (" ".join(words[:6]), mentions)
            if not requirement or fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            combined.append(item)
            if len(combined) >= max_additions:
                return {
                    "verdict": "add",
                    "additions": combined,
                    "parse_error": bool(
                        semantic_audit.get("parse_error")
                        or observable_audit.get("parse_error")
                    ),
                }
    return {
        "verdict": "add" if combined else "pass",
        "additions": combined,
        "parse_error": bool(
            semantic_audit.get("parse_error")
            or observable_audit.get("parse_error")
        ),
    }
