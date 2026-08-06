"""facets_agent's ``search_result_filter`` configurations (PLAN.md Phase 4c,
in ``src/systems/facets_agent/PLAN.md``): two experimental variants of a
post-search relevance pass, both calling the same batch judge
(``agent_harness.tools.judge_documents``) once per search — they differ
only in what happens to the verdicts, not in the judging mechanism itself.

- ``minimize_filter`` ("Version A"): keeps only ``relevant``, drops the
  rest. Tests the user's original hypothesis directly — does the main
  model do BETTER when it sees LESS.
- ``rank_filter`` ("Version B", gpt-5.6-terra's suggested alternative, see
  ``worklogs/assets/2026-08-06-terra-review-prefilter-plan.txt``): drops
  NOTHING — reorders ``relevant`` → ``adjacent_not_relevant`` →
  ``irrelevant`` and annotates each with its verdict. Recall is
  structurally protected by construction (nothing removed); tests whether
  ordering/annotation alone reduces wasted triage effort without the
  recall cost minimize_filter risks.

Neither is facets_agent's default — ``run_agent``'s own
``search_result_filter`` parameter stays ``None`` pending the A/B
experiment's result (see the Phase 4c worklog).

Both fail OPEN per-document, not just on total judge failure: a document
the judge's response omits a verdict for is treated as unverdicted
(``None``), and both configurations keep an unverdicted document rather
than risk silently discarding evidence the judge simply didn't cover.
"""
from __future__ import annotations

from typing import Any

from agent_harness.agent import SearchResultPass
from agent_harness.tools import judge_documents

# Only the first N results (by the engine's own rank) are judged per search
# call -- cost/latency control (one judge round-trip already adds real
# per-search latency; unbounded batch size would make that worse and risks
# the judge prompt truncating). Anything beyond this passes through
# unfiltered/unranked, appended after the judged portion -- never dropped.
MAX_JUDGED_PER_SEARCH = 20

_RANK_ORDER = {"relevant": 0, "adjacent_not_relevant": 1, "irrelevant": 2}


def _judge(requirement: str, documents: list[dict[str, Any]]
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Judge up to MAX_JUDGED_PER_SEARCH documents against ``requirement``.

    Returns ``(judged, overflow)``: ``judged`` entries are copies of the
    input dicts with a ``verdict`` key added (``None`` if the judge failed
    entirely or simply omitted that id from its response); ``overflow`` is
    the untouched remainder beyond the batch cap.
    """
    if not requirement or not documents:
        return [dict(d, verdict=None) for d in documents], []
    head = documents[:MAX_JUDGED_PER_SEARCH]
    overflow = documents[MAX_JUDGED_PER_SEARCH:]
    result = judge_documents(requirement, head)
    verdicts = result.get("verdicts")
    verdict_by_id: dict[str, str | None] = {}
    if "error" not in result and isinstance(verdicts, list):
        verdict_by_id = {
            str(v.get("id")): v.get("verdict")
            for v in verdicts if isinstance(v, dict)
        }
    judged = [dict(d, verdict=verdict_by_id.get(str(d["id"]))) for d in head]
    return judged, overflow


def minimize_filter(requirement: str, documents: list[dict[str, Any]]
                    ) -> SearchResultPass:
    """Version A: keep only documents judged ``relevant`` (plus any the
    judge didn't verdict at all, per this module's fail-open policy)."""
    judged, overflow = _judge(requirement, documents)
    kept = [
        {"id": d["id"], "judge_verdict": d["verdict"]} for d in judged
        if d["verdict"] in ("relevant", None)
    ]
    dropped = len(judged) - len(kept)
    note = (
        f'{dropped} of {len(judged)} results dropped as not relevant '
        f'to "{requirement}"'
    ) if dropped else None
    kept += [{"id": d["id"]} for d in overflow]
    return SearchResultPass(documents=kept, note=note)


def rank_filter(requirement: str, documents: list[dict[str, Any]]
               ) -> SearchResultPass:
    """Version B: keep EVERY document, reordered relevant ->
    adjacent_not_relevant -> irrelevant and annotated. Nothing is ever
    dropped, so this configuration has no recall-regression risk by
    construction (an unverdicted document sits in the middle tier, same as
    ``adjacent_not_relevant`` — and Python's stable sort means a total
    judge failure, where every document is unverdicted, leaves the
    original order untouched)."""
    judged, overflow = _judge(requirement, documents)
    ranked = sorted(judged, key=lambda d: _RANK_ORDER.get(d["verdict"], 1))
    kept = [{"id": d["id"], "judge_verdict": d["verdict"]} for d in ranked]
    kept += [{"id": d["id"]} for d in overflow]
    return SearchResultPass(documents=kept, note=None)
