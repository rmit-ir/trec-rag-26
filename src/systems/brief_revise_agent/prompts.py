"""Prompts for brief_revise_agent's two additions to the aus_agent fork
(PLAN.md §3): the pre-flight requirements brief (``brief.py``) and the
post-draft reviewer (``review.py``). Both are tool-less one-shot calls
(``facet_rag.llm.one_shot``) with an empty system prompt and the full
instructions folded into the user text — the same convention
``facet_rag/prompts.py``'s own planner/analyzer/curator prompts use.

``APPENDIX_TEMPLATE``/``ENTRY_TEMPLATE`` render PLAN.md §3.2's "Appendix A":
the per-topic requirements list appended to the forked system prompt at call
time (``brief.render_appendix``). "Appendix B" (the static review-contract
paragraph) needs no template here — it carries no per-topic content, so it is
baked directly into ``prompts/system/default.md`` alongside the byte-copied
aus_agent prompt it extends.

``REVIEW_PROMPT`` is still a Phase 0 stub (``""``) -- Phase 2 (``review.py``)
fills it in.
"""
from __future__ import annotations

BRIEF_PROMPT = """You are the requirements analyst for a corpus-grounded research \
agent, working BEFORE any searching begins. Read the research request below and \
produce a short checklist of what a complete, high-scoring answer must do -- the \
concrete obligations a careful reader would infer from the request in about ten \
seconds, whether the request states them outright or only implies them.

Two kinds of entry:
- "explicit": something the request states directly (a named comparison, a \
requested format, a named entity or period to cover).
- "implicit": something the request does not state but clearly implies -- e.g. a \
request that names several financial instruments for a beginner audience implies \
each should be briefly defined at first use. Every implicit entry's `why` must \
quote or closely paraphrase the specific wording in the request that implies it. \
An implicit entry you cannot trace to actual wording in the request is a hunch, \
not a requirement -- leave it out.

For every entry, also write `specific_form`: what actually COUNTS as satisfying \
it, in the concrete shape a grader would look for (a named entity, a number, a \
mechanism, a comparison) -- never a topic label. "Covers the major stock \
indexes" is not a specific_form; "names the S&P 500, Dow Jones, Nasdaq, and \
Russell 2000" is.

Hard caps: at most 8 entries total, at most 4 of them "implicit". Every entry \
you add competes for the answer's fixed word budget, so do not pad -- fewer \
well-justified entries beat a full list of filler. If the request is narrow and \
already fully explicit, return fewer entries, or none.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"requirements": [{{"id": "R1", "requirement": "<what the answer must do>", \
"origin": "explicit or implicit", "why": "<quote the wording that implies this; \
empty string for an explicit entry>", "specific_form": "<what counts as \
covering it>"}}, ...]}}

RESEARCH REQUEST:
{narrative}
"""

APPENDIX_TEMPLATE = """

## Requirements brief (advisory)

Before this run began, a requirements analyst read the request above and drew \
up the checklist below: obligations a careful reader would infer from the \
request, some stated outright, some implied. It is a checklist to search \
against and to check the finished report against -- not an outline the report \
must follow, and not a substitute for the request itself: the request remains \
the authority, and if the corpus contradicts an entry, amend the entry rather \
than force it -- but never silently drop one without saying so in the report. \
Give every entry below at least one targeted search. An entry only counts as \
covered when the report states it in the specific form named, not as a \
category label.

{entries}
"""

ENTRY_TEMPLATE = "- [{id}] ({origin}) {requirement} -- counts as covered when: {specific_form}"

REVIEW_PROMPT = ""  # Phase 2

__all__ = ["APPENDIX_TEMPLATE", "BRIEF_PROMPT", "ENTRY_TEMPLATE", "REVIEW_PROMPT"]
