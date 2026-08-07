"""adjacent_pages.py -- round B of the sol-vs-aus_agent_v2 improvement loop
(``worklogs/2026-08-07-brief-revise-agent-iteration5-adjacent-pages-and-word-budget.md``):
a ``search_result_augment`` closure (``agent_harness.agent``'s new hook,
added this round) replicating ``aus_agent_v2/search.py``'s auto-adjacent-page
mechanism -- for the top-ranked paginated hits in a search batch, fetch the
immediately preceding and following page and add them to the staged set.

Deliberately zero-LLM-call: unlike everything tried in rounds 1-3 (a brief
schema, a review pass, a retrieval filter), this adds evidence with no new
model decision point and no new failure mode beyond a network fetch, which
already fails open the same way ``tools.get_documents.execute_get_documents``
does (a missing/failed id is just dropped, never raised). Their own stated
motivation, ported verbatim: ClimbMix documents are chunked into pages, and
a search hit's page boundary can cut off exactly the sentence, name, or date
that would have completed a claim; the base agent almost never proactively
calls ``get_documents`` for a neighbor even when it would help.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from agent_harness.tools.get_documents import execute_get_documents

log = logging.getLogger(__name__)

DEFAULT_MAX_SEED_HITS = 5
_PAGE_ID_RE = re.compile(r"^(?P<parent>.+)_p(?P<page>[1-9]\d*)$")


def adjacent_page_ids(unit_ids: list[str], *,
                      max_seed_hits: int = DEFAULT_MAX_SEED_HITS) -> list[str]:
    """Stable, deduplicated +/-1 page ids for the top ``max_seed_hits``
    paginated hits, excluding ids already present in ``unit_ids`` -- ported
    from ``aus_agent_v2/search.py::adjacent_page_ids`` (same algorithm, same
    seed-hit cap), since replicating a working, already-measured mechanism
    exactly is lower-risk than reinventing it."""
    present = set(unit_ids)
    adjacent: list[str] = []
    seeds = 0
    for unit_id in unit_ids:
        match = _PAGE_ID_RE.match(unit_id)
        if match is None:
            continue
        seeds += 1
        if seeds > max_seed_hits:
            break
        parent = match.group("parent")
        page = int(match.group("page"))
        candidates = []
        if page > 1:
            candidates.append(f"{parent}_p{page - 1}")
        candidates.append(f"{parent}_p{page + 1}")
        for candidate in candidates:
            if candidate not in present and candidate not in adjacent:
                adjacent.append(candidate)
    return adjacent


def augment(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``search_result_augment`` closure: derive adjacent ids from the
    current staged batch, fetch them via the existing ``get_documents``
    execution path (same fetch/error handling real ``get_documents`` tool
    calls already use -- a missing id is silently dropped, never raised),
    and return the fetched documents for the harness to merge in. No
    provider/LLM call anywhere in this path."""
    unit_ids = [str(d.get("id", "")) for d in documents if d.get("id")]
    adjacent_ids = adjacent_page_ids(unit_ids)
    if not adjacent_ids:
        return []
    _out, fetched, missing = execute_get_documents({"ids": adjacent_ids})
    if missing:
        log.info("adjacent_pages: %d/%d adjacent ids not found: %s",
                 len(missing), len(adjacent_ids), missing)
    for doc in fetched:
        doc.setdefault("metadata", {})["source"] = "adjacent_pages"
    log.info("adjacent_pages: %d seed hits -> %d adjacent ids -> %d fetched",
             min(len(unit_ids), DEFAULT_MAX_SEED_HITS), len(adjacent_ids),
             len(fetched))
    return fetched


__all__ = ["DEFAULT_MAX_SEED_HITS", "adjacent_page_ids", "augment"]
