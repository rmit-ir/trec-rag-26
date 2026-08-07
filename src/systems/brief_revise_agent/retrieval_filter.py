"""retrieval_filter.py -- iteration 3's ``search_result_filter`` (PLAN.md §3.4
never changed retrieval; this is the first time it does). Per
``worklogs/2026-08-07-brief-revise-agent-iteration3-retrieval-filter.md``: a
genuinely different axis from iterations 1-2's brief/review work, chosen by
gpt-5.6-sol after iteration 2 REGRESSED on the full 15-topic set (11 clean
losses vs iteration 1's 10) -- restore iteration 1's brief/review exactly,
then add retrieval-precision filtering instead of more planning/review.

Wired via ``agent_harness.agent.run_agent``'s existing ``search_result_filter``
hook (already built and tested by a sibling effort in this repo, unused by
this system until now): called after every search, before staging, with the
search call's ``requirement`` argument and the result documents. A
conservative one-shot LLM screener labels each document DIRECT/LEAD/
OFF_TOPIC against the stated evidence need and removes only OFF_TOPIC,
subject to a retention floor so a long-chronology or many-actor topic (the
two clean wins iteration 2 broke) cannot lose more than half its results to
one screening pass.

Deliberately, strongly fail-open (sol's spec, §3's "Parsing and fail-open
rules"): a provider exception, empty/invalid response, wrong document-id
set, or malformed labels all return the ORIGINAL, unfiltered batch. No
retry -- a malformed judgment is treated as "don't filter this batch," not
as something worth spending a second call on.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

from facet_rag.llm import one_shot, strip_fences

from agent_harness.agent import SearchResultPass

log = logging.getLogger(__name__)

LABELS = frozenset({"DIRECT", "LEAD", "OFF_TOPIC"})
_EXCERPT_CHARS = 1800
_BATCH_CHAR_CAP = 18_000
_MIN_REQUIREMENT_CHARS = 20

_PROMPT = """You are a conservative retrieval screener. A research agent issued a search \
for the specific evidence need below. Classify every returned document by \
whether it should be allowed into the agent's staged context.

EVIDENCE NEED:
{requirement}

DOCUMENTS:
{documents}

Use these labels:

DIRECT:
The excerpt contains facts, chronology, names, comparisons, quotations, or \
source material that directly helps satisfy the evidence need.

LEAD:
The excerpt is materially connected and may identify a useful person, event, \
source, terminology, or follow-up route, even if it does not itself fully \
answer the need. When uncertain between LEAD and OFF_TOPIC, choose LEAD.

OFF_TOPIC:
The document is clearly about a different subject, different entity, wrong \
sense of a name, wrong period, or otherwise cannot materially help this \
specific evidence need. Mere incompleteness is not OFF_TOPIC.

Return exactly one row for every supplied document ID. Preserve the IDs \
exactly. Return only JSON:

{{"documents":[
  {{"id":"<exact id>","label":"DIRECT|LEAD|OFF_TOPIC",
   "reason":"<brief document-specific reason>"}}
]}}
"""


def _render_documents(documents: list[dict[str, Any]]) -> str:
    n = max(len(documents), 1)
    per_doc_cap = max(200, _BATCH_CHAR_CAP // n)
    excerpt_cap = min(_EXCERPT_CHARS, per_doc_cap)
    lines = []
    for doc in documents:
        text = str(doc.get("text") or "")[:excerpt_cap]
        title = doc.get("title")
        source = doc.get("source") or doc.get("url")
        header = f"id={doc.get('id')}"
        if title:
            header += f" title={title!r}"
        if source:
            header += f" source={source!r}"
        lines.append(f"[{header}]\n{text}")
    return "\n\n".join(lines)


def _parse_labels(raw: str, valid_ids: list[str]) -> dict[str, str] | None:
    """``None`` on ANY deviation from a clean one-row-per-id response --
    the caller's job is then to fail open, not to salvage a partial
    judgment (sol's spec: no retry, no partial trust)."""
    try:
        payload = json.loads(strip_fences(raw)) if raw else None
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    rows = payload.get("documents")
    if not isinstance(rows, list):
        return None
    labels: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        doc_id = row.get("id")
        label = str(row.get("label", "")).strip().upper()
        if not isinstance(doc_id, str) or doc_id in labels or label not in LABELS:
            return None
        labels[doc_id] = label
    if set(labels) != set(valid_ids):
        return None
    return labels


def _apply_retention_floor(documents: list[dict[str, Any]],
                           labels: dict[str, str]) -> list[dict[str, Any]]:
    """Keep every DIRECT/LEAD; restore OFF_TOPIC documents, in original
    order, until at least ``min_keep`` survive -- a normal 10-result search
    can lose at most half its results to one screening pass, and a batch of
    4 or fewer can never lose anything (sol's spec)."""
    n = len(documents)
    min_keep = min(n, max(4, math.ceil(n / 2)))
    kept_ids = {d["id"] for d in documents if labels.get(str(d["id"])) != "OFF_TOPIC"}
    if len(kept_ids) < min_keep:
        for doc in documents:
            if len(kept_ids) >= min_keep:
                break
            kept_ids.add(doc["id"])
    return [d for d in documents if d["id"] in kept_ids]


def make_filter(provider: Any):
    """Build a ``search_result_filter`` closure bound to one dedicated
    one-shot provider (never the main loop's conversation -- sol's spec)."""

    def filter_results(requirement: str,
                       documents: list[dict[str, Any]]) -> SearchResultPass:
        if not documents or len(requirement.strip()) < _MIN_REQUIREMENT_CHARS:
            return SearchResultPass(documents=documents)
        try:
            valid_ids = [str(d["id"]) for d in documents]
            prompt = _PROMPT.format(
                requirement=requirement, documents=_render_documents(documents))
            raw = one_shot(provider, "", prompt)
            log.info("retrieval_filter: usage=%s",
                     getattr(provider, "_last_usage", None))
            labels = _parse_labels(raw, valid_ids)
            if labels is None:
                log.warning("retrieval_filter: unparseable/mismatched "
                           "response (raw[:200]=%r); passing batch through "
                           "unfiltered", raw[:200])
                return SearchResultPass(documents=documents)
            counts = {lbl: sum(1 for v in labels.values() if v == lbl)
                     for lbl in LABELS}
            if counts["OFF_TOPIC"] == len(documents):
                log.info("retrieval_filter: all %d documents labeled "
                         "OFF_TOPIC; passing batch through unfiltered "
                         "(never empty a search)", len(documents))
                return SearchResultPass(documents=documents)
            retained = _apply_retention_floor(documents, labels)
            log.info("retrieval_filter: %s -> kept %d/%d (%s)",
                     counts, len(retained), len(documents), requirement[:80])
            return SearchResultPass(
                documents=retained,
                note=f"retrieval_filter: {counts}")
        except Exception:
            log.exception("retrieval_filter: failed; passing batch through "
                          "unfiltered")
            return SearchResultPass(documents=documents)

    return filter_results


__all__ = ["make_filter"]
