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

Also allocate a WORD BUDGET (round C): set `target_total_words` to a number \
between 500 and 1000 (the hard track limit is 1024, leave room for revision), \
and give each entry a `target_words` share of that total -- the per-entry \
numbers must sum to approximately `target_total_words`. Give the most words to \
requirements that need a concrete example, mechanism, or worked case to satisfy \
their `specific_form`; give fewer to requirements that need only a brief \
mention. This is the depth budget the writer should aim to actually spend on \
each item, not a minimum -- do not inflate it just to fill space.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"target_total_words": <int 500-1000>, "requirements": [{{"id": "R1", \
"requirement": "<what the answer must do>", "origin": "explicit or implicit", \
"why": "<quote the wording that implies this; empty string for an explicit \
entry>", "specific_form": "<what counts as covering it>", \
"target_words": <int, this entry's share of target_total_words>}}, ...]}}

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
{total_line}
{entries}
"""

ENTRY_TEMPLATE = ("- [{id}] ({origin}) {requirement} -- counts as covered "
                  "when: {specific_form}{budget}")

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

First, grade EVERY requirement in the brief -- do not skip any, even ones \
that look fine:
- FULL: the draft states it in the specific form the brief names (a named \
mechanism, number, or entity), not a category label, and it is cited.
- PARTIAL: the draft mentions the topic but stays at a category label, or \
covers only part of what the requirement asks.
- MISSING: the draft does not address it at all.
For PARTIAL or MISSING, name the missing specific in one phrase (a term, a \
number, a name -- something the writer can go add) and check the evidence \
inventory above first: if it already contains something that would resolve \
the gap, say so by id instead of asking for a new search.

Second, list AT MOST 4 additional issues not already covered by a \
requirement grade, each ONE of:
- UNCITED_CLAIM: a factual sentence (name its number) with no citation that \
the evidence inventory above could support.
- WEAK_SENTENCE: a sentence too vague or hedged to earn credit, that a \
specific fact already in the evidence above would fix.

This is a PATCH, not a rewrite: the fix for each PARTIAL/MISSING requirement \
or issue must be a SUBSTITUTION naming what to cut to make room, since the \
draft is already close to the {max_words}-word cap. Never suggest cutting or \
touching a sentence that supports a requirement already graded FULL -- that \
content stays exactly as written. Do not invent a requirement grade or issue \
you cannot name a concrete fix for.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"requirements": [{{"id": "<id from the brief>", "status": "FULL, PARTIAL, \
or MISSING", "missing_specific": "<the specific term/number/name still \
needed, or empty string if FULL>", "fix": "<the substitution: what to cut \
to make room for what, or empty string if FULL>"}}, ...one entry per brief \
requirement...], "issues": [{{"type": "UNCITED_CLAIM or WEAK_SENTENCE", \
"target": "<sentence number>", "problem": "<what is wrong, briefly>", \
"fix": "<the substitution>"}}]}}
"""

# Closure-critic variant (hill-climb, worklogs/2026-08-07-brief-revise-agent-
# llm-factorial-design.md section 12): same review pass, plus two issue
# types review.py's own docstring flagged as NOT built -- overclaim/
# entailment (a citation that does not actually say what the sentence
# claims) and internal contradiction. Deliberately NOT a second scout/plan/
# verify pipeline (sol's explicit constraint) -- same single hook, same one
# bounded revision, just a wider issue taxonomy checked in the one pass the
# harness allows (pre_final_hook fires at most once).
REVIEW_PROMPT_WITH_CLOSURE = """You are reviewing a draft research report before it is \
submitted to its reader. You do not rewrite the report yourself -- you \
grade the draft against EVERY requirement in the brief, one by one, and \
flag citation and evidence problems, so the writer can PATCH the draft in \
one more pass rather than rewrite it.

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
existing one would resolve the gap; this is also what each citation's evidence \
must actually say):
{evidence}

Current length: {word_count} words. Hard maximum: {max_words} words.

First, grade EVERY requirement in the brief -- do not skip any, even ones \
that look fine:
- FULL: the draft states it in the specific form the brief names (a named \
mechanism, number, or entity), not a category label, and it is cited.
- PARTIAL: the draft mentions the topic but stays at a category label, or \
covers only part of what the requirement asks.
- MISSING: the draft does not address it at all.
For PARTIAL or MISSING, name the missing specific in one phrase (a term, a \
number, a name -- something the writer can go add) and check the evidence \
inventory above first: if it already contains something that would resolve \
the gap, say so by id instead of asking for a new search.

Second, list AT MOST 4 additional issues not already covered by a \
requirement grade, each ONE of:
- UNCITED_CLAIM: a factual sentence (name its number) with no citation that \
the evidence inventory above could support.
- WEAK_SENTENCE: a sentence too vague or hedged to earn credit, that a \
specific fact already in the evidence above would fix.
- UNSUPPORTED_CLAIM: a cited sentence that claims MORE than its cited \
evidence actually states (a number, scope, or causal claim the evidence \
text does not contain) -- an overclaim, not a missing citation.
- CONTRADICTION: two sentences in the draft that cannot both be true, or a \
sentence that contradicts its own cited evidence text.

This is a PATCH, not a rewrite: the fix for each PARTIAL/MISSING requirement \
or issue must be a SUBSTITUTION naming what to cut to make room, since the \
draft is already close to the {max_words}-word cap. Never suggest cutting or \
touching a sentence that supports a requirement already graded FULL -- that \
content stays exactly as written. Do not invent a requirement grade or issue \
you cannot name a concrete fix for.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"requirements": [{{"id": "<id from the brief>", "status": "FULL, PARTIAL, \
or MISSING", "missing_specific": "<the specific term/number/name still \
needed, or empty string if FULL>", "fix": "<the substitution: what to cut \
to make room for what, or empty string if FULL>"}}, ...one entry per brief \
requirement...], "issues": [{{"type": "UNCITED_CLAIM, WEAK_SENTENCE, \
UNSUPPORTED_CLAIM, or CONTRADICTION", "target": "<sentence number>", \
"problem": "<what is wrong, briefly>", "fix": "<the substitution>"}}]}}
"""

__all__ = ["APPENDIX_TEMPLATE", "BRIEF_PROMPT", "ENTRY_TEMPLATE", "REVIEW_PROMPT",
          "REVIEW_PROMPT_WITH_CLOSURE"]
