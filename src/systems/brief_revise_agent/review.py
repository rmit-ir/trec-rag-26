"""review.py -- brief_revise_agent's ``pre_final_hook`` (PLAN.md §3.3, v2 per
``worklogs/2026-08-07-brief-revise-agent-sol-improvement-analysis.md`` Priority 1).

Fires at most once, per the harness contract (``agent_harness.agent.run_agent``'s
``pre_final_hook`` docstring): the first time the model produces a report that
already passed ``_parse_final_prose``'s own citation/length checks. Sequence:

1. A deterministic uncited-sentence scan over ``context["candidate_sentences"]``
   -- no LLM call.
2. One reviewer call (``facet_rag.llm.one_shot``) that grades EVERY brief
   requirement FULL/PARTIAL/MISSING (not a free-form "up to N issues" list --
   sol's root-cause analysis of the 14 clean losses against aus_agent_v2's
   predecessor found the dominant loss pattern was searched-and-briefed
   content that never made it into the final answer, which a bounded,
   optional issue list can silently miss on any given topic; a per-requirement
   grade cannot skip one), plus up to 4 non-requirement issues
   (UNCITED_CLAIM/WEAK_SENTENCE) and an evidence inventory read LOCALLY from
   ``context["ledger"].call_history`` (no re-fetch, no network).
3. Nothing PARTIAL/MISSING, no issues, no uncited sentences -> ``None``
   (byte-identical to no hook). Otherwise, a PATCH-framed feedback string:
   name every gap and its fix, explicitly forbid touching a FULL-graded
   requirement's supporting sentence, and attach the live word-budget
   arithmetic.
4. **Fail-CLOSED parsing** (the sol-analysis correction to v1's behavior):
   an unparseable reviewer response is retried ONCE with a stricter repair
   prompt; if the retry also fails to parse, the draft is accepted as-is and
   the failure is logged at WARNING (not silently treated as "zero issues"
   found -- v1 did that, and sol's analysis caught a real instance of it
   in the wild, topic `6847465956a0f6376a605493`, that this fixes).
5. The ENTIRE body is still wrapped in one blanket exception guard: any
   failure (a raising provider, a malformed ``ledger``) is logged and
   degrades to ``None``. A review failure must never fail a topic.

Deliberately NOT built this iteration (still targets citation *recall*, not
citation *precision* -- see the improvement-analysis worklog's Priority 6):
full-text entailment checking of every citation, and the harness-level
regression guard (revert if a FULL requirement drops to PARTIAL after
revision) sol's plan also proposed -- that needs the hook to see the
REVISED draft, and ``pre_final_hook`` fires at most once by harness design;
building that is a shared-code change, out of scope for one iteration.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from facet_rag.llm import one_shot, strip_fences

from agent_harness.agent import MAX_REPORT_WORDS

from .brief import Requirement
from .prompts import REVIEW_PROMPT, REVIEW_PROMPT_WITH_CLOSURE

log = logging.getLogger(__name__)

MAX_ISSUES = 4
ISSUE_TYPES = frozenset({"UNCITED_CLAIM", "WEAK_SENTENCE"})
# closure-critic hill-climb (worklogs section 12): overclaim/entailment +
# contradiction, checked in the SAME single review pass -- the harness's
# pre_final_hook fires at most once, so this widens the existing hook's
# issue taxonomy rather than adding a second scout/plan/verify stage.
CLOSURE_ISSUE_TYPES = frozenset({"UNSUPPORTED_CLAIM", "CONTRADICTION"})
REQ_STATUSES = frozenset({"FULL", "PARTIAL", "MISSING"})
# How much of a committed document's text to quote back to the reviewer --
# enough to judge relevance, not the full ~4K-token staged budget.
_SNIPPET_CHARS = 400
_REPAIR_SUFFIX = (
    "\n\nYour previous response did not parse as the exact JSON object "
    "shape requested above. Return ONLY that JSON object -- no prose, no "
    "code fences, no explanation before or after it.")


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


def _parse_review(raw: str, valid_ids: set[str], issue_types: frozenset[str]
                  ) -> tuple[list[dict[str, str]], list[dict[str, str]], bool]:
    """Parse the reviewer's JSON into ``(requirement_grades, issues, parsed_ok)``.

    ``parsed_ok`` is ``False`` only when the top-level shape itself didn't
    parse (not valid JSON, or missing/malformed ``requirements``/``issues``
    keys) -- that's what triggers ``hook``'s fail-closed retry. A
    well-formed-but-empty response (``{"requirements": [], "issues": []}``)
    is ``parsed_ok=True`` with nothing to report, which is a legitimate
    "everything is FULL" answer on a short/narrow topic, not a failure.

    Rows naming an id outside ``valid_ids`` (a hallucinated requirement id)
    are dropped -- the feedback must only ever reference the brief's own
    entries."""
    try:
        payload = json.loads(strip_fences(raw)) if raw else None
    except (json.JSONDecodeError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        return [], [], False
    req_rows = payload.get("requirements")
    issue_rows = payload.get("issues")
    if not isinstance(req_rows, list) or not isinstance(issue_rows, list):
        return [], [], False

    grades: list[dict[str, str]] = []
    for row in req_rows:
        if not isinstance(row, dict):
            continue
        req_id = _clean_field(row.get("id"), max_len=20)
        status = _clean_field(row.get("status"), max_len=20).upper()
        if req_id not in valid_ids or status not in REQ_STATUSES:
            continue
        grades.append({
            "id": req_id, "status": status,
            "missing_specific": _clean_field(row.get("missing_specific")),
            "fix": _clean_field(row.get("fix")),
        })

    issues: list[dict[str, str]] = []
    for row in issue_rows:
        if len(issues) >= MAX_ISSUES:
            break
        if not isinstance(row, dict):
            continue
        issue_type = _clean_field(row.get("type"), max_len=40).upper()
        fix = _clean_field(row.get("fix"))
        if issue_type not in issue_types or not fix:
            continue
        issues.append({
            "type": issue_type,
            "target": _clean_field(row.get("target"), max_len=80),
            "problem": _clean_field(row.get("problem")),
            "fix": fix,
        })
    return grades, issues, True


def _render_feedback(grades: list[dict[str, str]],
                     issues: list[dict[str, str]],
                     uncited: list[tuple[int, str]],
                     word_count: int,
                     requirements: list[Requirement]) -> str:
    by_id = {r.id: r for r in requirements}
    gaps = [g for g in grades if g["status"] != "FULL" and g["fix"]]
    lines = [
        f"Before this report is accepted: it is {word_count} words against a "
        f"{MAX_REPORT_WORDS}-word hard cap, so any addition below must come "
        "with a cut. This is a PATCH pass: do not touch or shorten any "
        "sentence that already supports a requirement graded FULL below -- "
        "only the gaps listed need work."
    ]
    if uncited:
        lines.append(
            f"{len(uncited)} sentence(s) carry no citation: "
            + ", ".join(f"#{i}" for i, _ in uncited) + ".")
    for g in gaps:
        req = by_id.get(g["id"])
        req_text = req.requirement if req else g["id"]
        missing = f" Missing: {g['missing_specific']}." if g["missing_specific"] else ""
        lines.append(f"- [{g['status']}] [{g['id']}] {req_text}{missing} "
                     f"Fix: {g['fix']}")
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
        provider: Any = None, closure_check: bool = False) -> str | None:
    """``pre_final_hook``: ``None`` accepts the draft; a string sends the
    model back once. ``requirements`` and ``provider`` are supplied by
    ``agent.run_agent`` via a closure (the harness calls this with a single
    positional ``context`` dict, so both must already be bound by the time
    the harness invokes it) -- see that module for the wiring.

    ``closure_check`` (hill-climb, worklogs section 12): when ``True``,
    also checks for overclaim/entailment and internal contradiction in the
    SAME single pass (``REVIEW_PROMPT_WITH_CLOSURE``, ``CLOSURE_ISSUE_TYPES``)
    -- not a second hook, since ``pre_final_hook`` fires at most once.

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

        req_list = list(requirements)
        valid_ids = {r.id for r in req_list}
        issue_types = ISSUE_TYPES | CLOSURE_ISSUE_TYPES if closure_check else ISSUE_TYPES
        template = REVIEW_PROMPT_WITH_CLOSURE if closure_check else REVIEW_PROMPT
        prompt = template.format(
            narrative=context.get("query", ""),
            brief=_render_brief(req_list),
            draft=_render_draft(sentences),
            uncited=_render_uncited(uncited),
            evidence=_render_evidence(inventory),
            word_count=word_count,
            max_words=MAX_REPORT_WORDS,
        )
        raw = one_shot(provider, "", prompt)
        log.info("review.hook: usage=%s", getattr(provider, "_last_usage", None))
        grades, issues, parsed_ok = _parse_review(raw, valid_ids, issue_types)

        if not parsed_ok:
            # Fail-CLOSED, not fail-open: retry once with a repair prompt
            # rather than silently treating an unparseable response as "no
            # issues found" (v1's behavior -- sol's improvement analysis
            # caught a real instance of this masking a genuine review
            # failure, topic 6847465956a0f6376a605493).
            log.warning("review.hook: reviewer response did not parse "
                       "(raw[:200]=%r); retrying once with a repair prompt",
                       raw[:200])
            raw = one_shot(provider, "", prompt + _REPAIR_SUFFIX)
            log.info("review.hook: retry usage=%s",
                     getattr(provider, "_last_usage", None))
            grades, issues, parsed_ok = _parse_review(raw, valid_ids, issue_types)
            if not parsed_ok:
                log.warning("review.hook: repair retry also failed to "
                           "parse (raw[:200]=%r); accepting draft as-is, "
                           "review_failed=true", raw[:200])
                if uncited:
                    # The deterministic scan is not an LLM output and does
                    # not depend on the reviewer parsing -- an uncited-only
                    # draft still gets sent back even when the LLM-sourced
                    # grading is unusable.
                    return _render_feedback([], [], uncited, word_count, req_list)
                return None

        if not any(g["status"] != "FULL" and g["fix"] for g in grades) \
                and not issues and not uncited:
            return None
        return _render_feedback(grades, issues, uncited, word_count, req_list)
    except Exception:
        log.exception("review.hook failed; accepting the draft unchanged")
        return None


__all__ = ["MAX_ISSUES", "hook"]
