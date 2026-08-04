"""Evidence curator — ranks a facet's accumulated evidence pool by relevance
and diversity, like a priority queue (a "heap") where the top item is the
single best piece of evidence for the facet and each one below is slightly
less essential, with near-duplicates sunk out of the way to make room for a
different angle at the top. This is an MMR-style (Maximal Marginal Relevance)
selection — maximize relevance, penalize redundancy with a higher-ranked
item — done via a structured LLM judgment rather than embedding cosine
similarity: this repo has no standalone text-embedding primitive (only
hosted *search* endpoints, which take a query and return ranked hits, not a
vector for arbitrary text), so building real vector MMR would mean adding
new infrastructure. An LLM ranking call reuses the exact structured-JSON
pattern already proven reliable for the analyzer and orchestrator stages.

Called every loop iteration (see ``loop.py``) on the FULL evidence pool
gathered so far for the facet — not just the newest round's passages — so
the ranking reflects cross-round coverage and cross-round redundancy, not
one search's results in isolation.

The curator is the loop's authoritative coverage signal: a facet only stops
once the curator agrees its top-N ranked, de-duplicated items adequately
cover the facet — not just when the analyzer likes the latest round (the
analyzer's ``satisfied`` only judges whether the round it just saw needs a
follow-up; it never re-examines the whole pool for redundancy). The top-N is
also what actually reaches synthesis (``FacetLoopResult.evidence``), so a
facet that gathered 30 passages across many rounds still contributes only
its 3 best, diverse ones downstream — this is the direct fix for the
evidence-bloat problem found by comparing facet_rag's citation precision
against aus_agent's much more selective ``commit_context`` gate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .llm import one_shot, strip_fences, usage_token_stats
from .planner import Facet
from .prompts import CURATOR_PROMPT

DEFAULT_TOP_N = 3


@dataclass
class RankedItem:
    docid: str
    note: str
    text: str
    redundant_with: str | None


@dataclass
class CurationResult:
    ranked: list[RankedItem]   # full pool, best to worst, redundant items sunk
    top: list[RankedItem]      # top_n non-redundant items -- the "heap top"
    gap: str | None
    covered: bool


def _render_evidence_for_curation(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(no evidence yet)"
    return "\n\n".join(f"docid={e['docid']}\nnote: {e['note']}\n{e['text']}"
                       for e in evidence)


def parse_curation(raw: str, evidence_by_docid: dict[str, dict[str, Any]],
                   top_n: int) -> CurationResult:
    """Parse the curator JSON into a ranking.

    Unparseable/empty output falls back to the evidence's existing (i.e.
    unranked, insertion) order with nothing marked redundant, and reports
    ``covered=False`` -- the loop keeps searching rather than trusting a
    broken ranking to have judged coverage.
    """
    try:
        payload = json.loads(strip_fences(raw))
    except json.JSONDecodeError:
        payload = None
    valid_docids = set(evidence_by_docid)

    ranking = payload.get("ranking") if isinstance(payload, dict) else None
    if not isinstance(ranking, list) or not ranking:
        ranked = [RankedItem(docid=d, note=evidence_by_docid[d]["note"],
                             text=evidence_by_docid[d]["text"], redundant_with=None)
                  for d in evidence_by_docid]
        return CurationResult(ranked=ranked, top=ranked[:top_n], gap=None,
                              covered=False)

    seen: set[str] = set()
    ranked: list[RankedItem] = []
    for row in ranking:
        if not isinstance(row, dict):
            continue
        docid = str(row.get("docid", "")).strip()
        if docid not in valid_docids or docid in seen:
            continue
        seen.add(docid)
        redundant_with = row.get("redundant_with")
        redundant_with = (str(redundant_with).strip()
                          if isinstance(redundant_with, str)
                          and redundant_with.strip() in valid_docids else None)
        item = evidence_by_docid[docid]
        ranked.append(RankedItem(docid=docid, note=item["note"], text=item["text"],
                                 redundant_with=redundant_with))
    # Anything the model omitted from the ranking still exists as evidence --
    # append it at the bottom rather than silently losing it.
    for docid in evidence_by_docid:
        if docid not in seen:
            item = evidence_by_docid[docid]
            ranked.append(RankedItem(docid=docid, note=item["note"],
                                     text=item["text"], redundant_with=None))

    top: list[RankedItem] = []
    top_docids: set[str] = set()
    for item in ranked:
        if item.redundant_with is not None:
            continue
        top.append(item)
        top_docids.add(item.docid)
        if len(top) >= top_n:
            break
    if len(top) < top_n:  # not enough non-redundant items -- pad from the rest
        for item in ranked:
            if item.docid in top_docids:
                continue
            top.append(item)
            top_docids.add(item.docid)
            if len(top) >= top_n:
                break

    gap = payload.get("gap")
    gap = str(gap).strip() if isinstance(gap, str) and gap.strip() else None
    covered = bool(payload.get("covered", False))
    return CurationResult(ranked=ranked, top=top, gap=gap, covered=covered)


def curate(provider: Any, *, narrative: str, facet: Facet,
          evidence: list[dict[str, Any]], top_n: int = DEFAULT_TOP_N
          ) -> tuple[CurationResult, dict[str, int] | None]:
    """Rank ``evidence`` (this facet's full accumulated pool) and return the
    result plus token stats. Empty evidence short-circuits to an empty,
    uncovered result -- nothing to rank yet."""
    if not evidence:
        return CurationResult(ranked=[], top=[], gap=None, covered=False), None
    evidence_by_docid = {e["docid"]: e for e in evidence}
    prompt = CURATOR_PROMPT.format(
        narrative=narrative, facet_name=facet.name,
        facet_description=facet.description,
        evidence=_render_evidence_for_curation(evidence), top_n=top_n)
    raw = one_shot(provider, "", prompt)
    stats = usage_token_stats(getattr(provider, "_last_usage", {}))
    return parse_curation(raw, evidence_by_docid, top_n), stats
