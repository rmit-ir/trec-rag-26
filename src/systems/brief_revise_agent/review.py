"""review.py -- brief_revise_agent's ``pre_final_hook`` (PLAN.md §3.3).

Fires at most once, per the harness contract (``agent_harness.agent.run_agent``'s
``pre_final_hook`` docstring): the first time the model produces a report that
already passed ``_parse_final_prose``'s own citation/length checks. Sequence:

1. A deterministic uncited-sentence scan over ``context["candidate_sentences"]``
   -- no LLM call. This is the one check PLAN.md §2.1 identifies as NOT already
   enforced upstream (the harness only refuses a report when *every* sentence
   is uncited, not when *some* are) and it alone justifies the hook: PLAN.md
   §1(c), 26.0% of aus_agent's answer sentences carry no citation.
2. One reviewer call (``facet_rag.llm.one_shot``), given the narrative, the
   requirements brief, the numbered draft, the uncited-sentence list, and an
   evidence inventory read LOCALLY from ``context["ledger"].call_history``
   (PLAN.md §2.2 -- no re-fetch, no network, no new failure mode).
3. No issues and no uncited sentences -> ``None`` (byte-identical to no hook).
   Otherwise, a feedback string naming every issue and uncited sentence, with
   the live word-budget arithmetic attached (PLAN.md §1(d): the median draft
   is already close to the 1024-word cap, so feedback must read as a
   substitution, not a bare addition).
4. The ENTIRE body is wrapped in one blanket exception guard: any failure
   (bad JSON, a raising provider, a malformed ``ledger``) is logged and
   degrades to ``None`` -- accepting the draft as-is. A review failure must
   never fail a topic; this is not negotiable (PLAN.md §3.3 step 4).

Deliberately NOT built (PLAN.md §3.3, §5(e)): full-text entailment checking
of every citation. That targets citation *precision*; the measured hole is
citation *recall* (uncited sentences), which the deterministic scan already
catches for free.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from facet_rag.llm import one_shot, strip_fences

from agent_harness.agent import MAX_REPORT_WORDS

from .brief import Requirement
from .prompts import REVIEW_PROMPT

log = logging.getLogger(__name__)

MAX_ISSUES = 6
ISSUE_TYPES = frozenset(
    {"MISSING_REQUIREMENT", "SHALLOW", "UNCITED_CLAIM", "WEAK_SENTENCE"})
# How much of a committed document's text to quote back to the reviewer --
# enough to judge relevance, not the full ~4K-token staged budget.
_SNIPPET_CHARS = 400


def _word_count(sentences: list[dict[str, Any]]) -> int:
    return sum(len(s["text"].split()) for s in sentences)


def _uncited_sentences(sentences: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """1-based ``(index, text)`` pairs for every sentence with no citations."""
    return [(i, s["text"]) for i, s in enumerate(sentences, 1)
            if not s.get("citations")]


def _evidence_inventory(ledger: Any, committed_ids: set[str]) -> dict[str, str]:
    """committed unit id -> a short text snippet, read locally from the
    ledger's own ``call_history`` (PLAN.md §2.2): the original full-text
    document each committed id came from is already held in memory for the
    life of the run, so this needs no search, no fetch, and no network.
    """
    call_history = getattr(ledger, "call_history", None) or {}
    committed_call_id = getattr(ledger, "committed_call_id", None) or {}
    inventory: dict[str, str] = {}
    for uid in committed_ids:
        call_id = committed_call_id.get(uid)
        result = call_history.get(call_id) if call_id else None
        documents = getattr(result, "documents", None) if result else None
        if not documents:
            continue
        for doc in documents:
            if str(doc.get("id")) == uid:
                inventory[uid] = str(doc.get("text") or "")[:_SNIPPET_CHARS]
                break
    return inventory


def _render_draft(sentences: list[dict[str, Any]]) -> str:
    lines = []
    for i, s in enumerate(sentences, 1):
        cites = ", ".join(s.get("citations") or []) or "(none)"
        lines.append(f"{i}. {s['text']} [{cites}]")
    return "\n".join(lines)


def _render_brief(requirements: list[Requirement]) -> str:
    if not requirements:
        return "(none -- no requirements brief was produced for this topic)"
    return "\n".join(
        f"- [{r.id}] ({r.origin}) {r.requirement} -- specific form: "
        f"{r.specific_form}" for r in requirements)


def _render_uncited(uncited: list[tuple[int, str]]) -> str:
    if not uncited:
        return "(none)"
    return "\n".join(f"- #{i}: {text}" for i, text in uncited)


def _render_evidence(inventory: dict[str, str]) -> str:
    if not inventory:
        return "(no evidence has been committed)"
    return "\n".join(f"- {uid}: {text}" for uid, text in inventory.items())


def _clean_field(value: Any, max_len: int = 500) -> str:
    """``value`` as a stripped, length-capped string -- or ``""`` for
    anything that was not actually a JSON string (``None``, a list, a dict).
    Mirrors ``brief._clean_field``: without this, ``str(row.get("fix"))`` on
    a JSON ``null`` becomes the literal text ``"None"``, which is truthy and
    would read as a real (nonsensical) fix instruction in the rendered
    feedback (gpt-5.6-sol code review finding)."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_len]


def _parse_issues(raw: str) -> list[dict[str, str]]:
    """Parse the reviewer's JSON into validated issues; malformed/garbage
    input -> ``[]`` rather than raising (the local half of the blanket
    guard -- ``hook``'s own try/except is the other half, for a provider
    that raises outright rather than returning parseable-but-bad text).

    ``[]`` here is deliberately indistinguishable from "the reviewer looked
    and found nothing" -- both mean the LLM-sourced issue list contributes
    nothing to the feedback. That is NOT the same as accepting the draft:
    the deterministic uncited-sentence scan in ``hook`` runs independently
    of whether this parse succeeded, so a garbled reviewer response still
    triggers one revision when uncited sentences exist. Only logged, not
    surfaced as a distinct return value, since nothing downstream currently
    needs to tell the two cases apart (gpt-5.6-sol code review raised this;
    the parse-failure log line below is the fix -- a policy change was not,
    see this function's own reasoning above)."""
    try:
        payload = json.loads(strip_fences(raw)) if raw else None
        rows = payload.get("issues") if isinstance(payload, dict) else None
    except (json.JSONDecodeError, AttributeError, TypeError):
        rows = None
    if not isinstance(rows, list):
        if raw:
            log.info("review.hook: reviewer response did not parse as the "
                     "expected {issues: [...]} shape; treating as zero "
                     "issues (raw[:200]=%r)", raw[:200])
        return []
    issues: list[dict[str, str]] = []
    for row in rows:
        if len(issues) >= MAX_ISSUES:
            break
        if not isinstance(row, dict):
            continue
        issue_type = _clean_field(row.get("type"), max_len=40).upper()
        fix = _clean_field(row.get("fix"))
        if issue_type not in ISSUE_TYPES or not fix:
            continue
        issues.append({
            "type": issue_type,
            "target": _clean_field(row.get("target"), max_len=80),
            "problem": _clean_field(row.get("problem")),
            "fix": fix,
        })
    return issues


def _render_feedback(issues: list[dict[str, str]],
                     uncited: list[tuple[int, str]],
                     word_count: int) -> str:
    lines = [
        f"Before this report is accepted: it is {word_count} words against a "
        f"{MAX_REPORT_WORDS}-word hard cap, so any addition below must come "
        "with a cut."
    ]
    if uncited:
        lines.append(
            f"{len(uncited)} sentence(s) carry no citation: "
            + ", ".join(f"#{i}" for i, _ in uncited) + ".")
    for issue in issues:
        target = f" ({issue['target']})" if issue["target"] else ""
        problem = f" {issue['problem']}" if issue["problem"] else ""
        lines.append(
            f"- [{issue['type']}]{target}{problem} Fix: {issue['fix']}")
    lines.append(
        "Revise in this same conversation: keep every claim you already "
        "support, prefer attaching an existing committed docid to an "
        "uncited sentence over deleting it, and use a new search only if a "
        "required item is genuinely unsupported -- extra searches may be "
        "refused if the research budget is already spent."
    )
    return "\n".join(lines)


def hook(context: dict[str, Any], *,
        requirements: list[Requirement] = (),  # type: ignore[assignment]
        provider: Any = None) -> str | None:
    """``pre_final_hook``: ``None`` accepts the draft; a string sends the
    model back once. ``requirements`` and ``provider`` are supplied by
    ``agent.run_agent`` via a closure (the harness calls this with a single
    positional ``context`` dict, so both must already be bound by the time
    the harness invokes it) -- see that module for the wiring.

    Never raises: PLAN.md §3.3 step 4's blanket guard, because a review
    failure must degrade to plain aus_agent behaviour (accept the draft), not
    a failed topic.
    """
    try:
        sentences = context.get("candidate_sentences") or []
        uncited = _uncited_sentences(sentences)
        word_count = _word_count(sentences)

        ledger = context.get("ledger")
        committed_ids = set(getattr(ledger, "committed_ids", None) or ())
        inventory = _evidence_inventory(ledger, committed_ids)

        prompt = REVIEW_PROMPT.format(
            narrative=context.get("query", ""),
            brief=_render_brief(list(requirements)),
            draft=_render_draft(sentences),
            uncited=_render_uncited(uncited),
            evidence=_render_evidence(inventory),
            word_count=word_count,
            max_words=MAX_REPORT_WORDS,
        )
        raw = one_shot(provider, "", prompt)
        # Same accounting gap as brief.get_requirements: this call's tokens
        # never reach the harness's own trajectory (gpt-5.6-sol code review
        # finding).
        log.info("review.hook: usage=%s", getattr(provider, "_last_usage", None))
        issues = _parse_issues(raw)

        if not issues and not uncited:
            return None
        return _render_feedback(issues, uncited, word_count)
    except Exception:
        log.exception("review.hook failed; accepting the draft unchanged")
        return None


__all__ = ["MAX_ISSUES", "hook"]
