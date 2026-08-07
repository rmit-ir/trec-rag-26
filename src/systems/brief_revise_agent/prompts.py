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

``REVIEW_PROMPT`` is rendered per-call by ``review.hook`` (PLAN.md §3.3).
"""
from __future__ import annotations

BRIEF_PROMPT = """You are the requirements analyst for a corpus-grounded research \
agent, working BEFORE any searching begins. Read the research request below and \
produce a checklist of small, independently-gradable checks a complete, \
expert-quality answer must satisfy.

Two kinds of entry:
- "REQUEST": something the request states or clearly structurally implies \
(a named comparison, a requested format, a named entity or period to cover).
- "EXPERT_COMPLETION": something the request does not say at all, but that a \
domain expert would expect in a genuinely complete answer to this kind of \
question -- e.g. a clinical-evaluation request implies a prospective \
validation stage even if the word "prospective" never appears; a systems- \
design request implies failure-mode and rollback handling even if the word \
"failure" never appears. This is NOT limited to the request's own wording --  \
name the check that would be missing even from an otherwise-compliant answer. \
Every EXPERT_COMPLETION entry needs `why_needed`: one concrete sentence on why \
an expert reader would consider the answer incomplete without it. An entry you \
cannot give a concrete reason for is decoration, not a requirement -- leave it \
out.

Keep every entry ATOMIC: one independently-gradable check per entry, never a \
bundle. "Address subgroup testing, false negatives, and human review" is THREE \
entries, not one -- a grader must be able to mark each TRUE or FALSE without \
the others. If you notice yourself joining two checks with "and" or a comma \
list of topics, split them.

For every entry, also write `answer_form`: what actually COUNTS as satisfying \
it, in the concrete shape a grader would look for (a named entity, a number, a \
mechanism, a comparison) -- never a topic label. "Covers the major stock \
indexes" is not an answer_form; "names the S&P 500, Dow Jones, Nasdaq, and \
Russell 2000" is.

Hard caps: at most 14 entries total, at most 6 of them "EXPERT_COMPLETION". \
Every entry you add competes for the answer's fixed word budget, so do not pad \
-- fewer well-justified entries beat a full list of filler. If the request is \
narrow and already fully explicit, return fewer entries.

Return ONLY a JSON object of this exact shape (no prose, no code fences, no \
"id" field -- ids are assigned by the harness):
{{"requirements": [{{"kind": "REQUEST or EXPERT_COMPLETION", "requirement": \
"<the check, one atomic proposition>", "answer_form": "<what counts as \
covering it>", "why_needed": "<for EXPERT_COMPLETION: the concrete reason; \
empty string for REQUEST>"}}, ...]}}

RESEARCH REQUEST:
{narrative}
"""

APPENDIX_TEMPLATE = """

## Requirements brief (advisory)

Before this run began, a requirements analyst read the request above and drew \
up the checklist below: atomic checks a complete answer must satisfy, some \
stated by the request (REQUEST), some added because an expert reader would \
expect them even though the request never says so (EXPERT_COMPLETION). It is \
a checklist to search against and to check the finished report against -- not \
an outline the report must follow, and not a substitute for the request \
itself: the request remains the authority, and an EXPERT_COMPLETION entry may \
be marked unavailable if the corpus does not support it -- but never silently \
dropped without saying so. Give every entry below at least one targeted \
search. An entry only counts as covered when the report states it in the \
answer form named, not as a category label.

{entries}
"""

ENTRY_TEMPLATE = "- [{id}] ({kind}) {requirement} -- counts as covered when: {answer_form}"

REVIEW_PROMPT = """You are reviewing a draft research report before it is \
submitted to its reader. You do not rewrite the report yourself -- you \
grade the draft against EVERY requirement in the brief, one by one, and \
flag citation problems, so the writer can PATCH the draft in one more pass \
rather than rewrite it.

RESEARCH REQUEST:
{narrative}

REQUIREMENTS BRIEF:
{brief}

DRAFT (one sentence per line, numbered, citations shown in brackets):
{draft}

SENTENCES WITH NO CITATION (found automatically by a deterministic scan, listed \
by number):
{uncited}

COMMITTED EVIDENCE ALREADY AVAILABLE (already retrieved and held by the writer -- \
point the writer at one of these ids rather than asking for a new search when an \
existing one would resolve the gap):
{evidence}

Current length: {word_count} words. Hard maximum: {max_words} words.

First, grade EVERY SINGLE requirement in the brief, in order, one grade \
each -- your `requirements` array must have EXACTLY one entry per id listed \
above, same ids, no id skipped, none repeated, none invented:
- FULL: the draft states it in the answer form the brief names (a named \
mechanism, number, or entity), not a category label, and it is cited.
- PARTIAL: the draft mentions the topic but stays at a category label, or \
covers only part of what the requirement asks.
- MISSING: the draft does not address it at all.
For PARTIAL or MISSING, name the missing specific in one phrase (a term, a \
number, a name -- something the writer can go add) and always give a `fix`, \
even a short one -- never leave it empty. Check the evidence inventory above \
first: if it already contains something that would resolve the gap, say so \
by id instead of asking for a new search.

Second, list AT MOST 4 additional issues not already covered by a \
requirement grade, each ONE of:
- UNCITED_CLAIM: a factual sentence (name its number) with no citation that \
the evidence inventory above could support.
- WEAK_SENTENCE: a sentence too vague or hedged to earn credit, that a \
specific fact already in the evidence above would fix.

This is a PATCH, not a rewrite: the fix for each PARTIAL/MISSING requirement \
or issue must say what to cut to make room, since the draft is already close \
to the {max_words}-word cap. A sentence that is the ONLY support for a \
requirement already graded FULL must not be deleted or have its supported \
fact weakened -- but it MAY be compressed, merged with a neighboring \
sentence, or moved, as long as the same fact and citation survive; prefer \
cutting from PARTIAL/MISSING/low-value material first. Do not invent a \
requirement grade or issue you cannot name a concrete fix for.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"requirements": [{{"id": "<id from the brief, one entry per id, none \
skipped>", "status": "FULL, PARTIAL, or MISSING", "missing_specific": "<the \
specific term/number/name still needed, or empty string if FULL>", "fix": \
"<what to cut to make room for what -- REQUIRED and non-empty whenever \
status is not FULL>"}}, ...], "issues": [{{"type": "UNCITED_CLAIM or \
WEAK_SENTENCE", "target": "<sentence number>", "problem": "<what is wrong, \
briefly>", "fix": "<the substitution>"}}]}}
"""

__all__ = ["APPENDIX_TEMPLATE", "BRIEF_PROMPT", "ENTRY_TEMPLATE", "REVIEW_PROMPT"]
