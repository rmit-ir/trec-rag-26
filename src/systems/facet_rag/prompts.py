"""Prompts for the facet_rag orchestrator/analyzer architecture.

Two roles, five prompts:

- ``PLAN_PROMPT`` (orchestrator, one-shot) — decompose the narrative into
  independent research FACETS: a name, a description of what needs to be
  found, and a complexity-driven iteration budget (1-10). No engine/query is
  prescribed here — the orchestrator decides retrieval strategy live, per
  facet, in ``ORCHESTRATOR_QUERY_PROMPT``.
- ``ORCHESTRATOR_QUERY_PROMPT`` (orchestrator, one-shot per loop iteration) —
  write one query per mandatory engine (semantic/keyword/hybrid) plus an
  optional Boolean-engine query, as structured JSON. NOT native tool-calling:
  gpt-oss-120b via Bedrock Converse never batched more than one tool call per
  turn regardless of prompt wording (checked empirically), so the code
  executes every query in the parsed plan unconditionally instead of relying
  on the model to decide how many/which tool calls to make.
- ``ANALYZER_PROMPT`` (analyzer, one-shot per loop iteration) — read the
  newly retrieved passages against the facet's need, keep what's relevant
  with a supporting note, and report a coverage gap (or "satisfied").
- ``SYNTH_DRAFT_PROMPT`` (orchestrator, one-shot) — draft the final cited
  report from every facet's saved evidence.
- ``FACT_CHECK_PROMPT`` (analyzer, one-shot) — patch the draft so every
  citation is actually supported by the evidence text.
"""
from __future__ import annotations

PLAN_PROMPT = """You are the planning stage of a corpus-grounded research system. \
Your ONLY data source is the ClimbMix document corpus. There is no web search.

Break the research narrative below into a small set of independent RESEARCH \
FACETS. A facet is one distinct sub-question or aspect of the narrative that \
can be investigated on its own. Aim for {min_facets}-{max_facets} facets: \
enough to cover every distinct aspect the narrative raises, no more. Do not \
create two facets that would need the same evidence.

For each facet also estimate how many rounds of search-and-refine it will \
realistically need (``max_iterations``, an integer 1-10): 1-2 for a narrow, \
well-defined sub-question; up to 10 for a broad or ambiguous one likely to \
need several rounds of follow-up search to cover properly.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"facets": [{{"name": "<short aspect label>", \
"description": "<the specific sub-question this facet must answer>", \
"max_iterations": <1-10>}}, ...]}}

RESEARCH NARRATIVE:
{narrative}
"""

ORCHESTRATOR_QUERY_PROMPT = """You are the search planner for one facet of a \
larger research task. Your ONLY data source is the ClimbMix document corpus \
— there is no web search.

FACET: {facet_name}

{facet_description}
{context_block}
Write a DIFFERENT, natural-language query for EACH of these three engines, \
each phrased in that engine's own style (not a copy of the others):
- semantic: {semantic_blurb}
- keyword: {keyword_blurb}
- hybrid: {hybrid_blurb}

If (and only if) this facet genuinely needs Boolean-precise co-occurrence, a \
required term, or a phrase/proximity match that natural language can't \
express, ALSO write one query for a Boolean engine — otherwise leave both \
boolean fields null:
{boolean_blurbs}

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"queries": {{"semantic": "<query>", "keyword": "<query>", "hybrid": "<query>"}}, \
"boolean_engine": "<engine name from the Boolean list above, or null>", \
"boolean_query": "<query in that engine's language, or null>"}}
"""

ANALYZER_PROMPT = """You are the analyst for one facet of a corpus-grounded \
research task. Read the newly retrieved passages below and judge them ONLY \
against this facet's need — ignore anything irrelevant to it.

FACET: {facet_name}

{facet_description}

EVIDENCE ALREADY SAVED FOR THIS FACET:
{evidence_so_far}

NEWLY RETRIEVED PASSAGES:
{passages}

For each newly retrieved passage that supports the facet, keep it. Its note \
must be a pre-written list of the SPECIFIC facts this passage contributes — \
numbers, dates, names, figures — not a topic label ("Detailed 401k vs Roth \
IRA comparison: contribution limits ($22,500/$6,500 2023), RMD age 73, \
employer match" is a usable note; "discusses retirement accounts" is not). \
Also name the passage's ROLE: is it core support, a counter-argument or \
caveat, a concrete example, or background context? Actively look for \
counter-evidence, contradictions, and limitations, not only confirming \
material — a passage that complicates or qualifies the facet's claim is as \
worth keeping as one that supports it, and its note should say so. Then \
judge whether the facet is now adequately covered by the saved + newly kept \
evidence together, or whether a specific gap remains that another search \
could fill (name the gap concretely, e.g. what aspect, entity, or comparison \
is still missing — not "need more info").

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"relevant": [{{"docid": "<docid from the passages above>", \
"note": "<what it supports>"}}, ...], \
"gap": "<specific remaining gap, or null if none>", \
"satisfied": <true if no further search is needed, else false>}}
"""

CURATOR_PROMPT = """You maintain the ranked evidence pool for one facet of a \
research task. Given the research narrative, the facet, and every piece of \
evidence gathered for it so far, rank the evidence from MOST to LEAST useful \
for answering the facet — like a priority queue where the top item is the \
single best piece of evidence and each one below is slightly less essential.

Maximize two things together: RELEVANCE (how directly and specifically each \
item addresses the facet) and COVERAGE (how much of the facet's distinct \
sub-aspects the pool as a whole addresses). An item that states essentially \
the same point as a higher-ranked item is REDUNDANT — mark it \
``redundant_with`` the higher-ranked item's docid and let it sink below \
items that cover a different angle, even if the redundant item is \
individually highly relevant on its own. Two items covering the same narrow \
point should not both sit near the top; prefer diversity of coverage there.

RESEARCH NARRATIVE:
{narrative}

FACET: {facet_name}

{facet_description}

EVIDENCE POOL:
{evidence}

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"ranking": [{{"docid": "<docid>", \
"redundant_with": "<docid of a higher-ranked item this duplicates, or null>"}}, \
...], \
"gap": "<what the top {top_n} still miss to fully address the facet, or null \
if nothing>", \
"covered": <true if the top {top_n}, taken together, adequately address the \
facet, else false>}}
"""

SYNTH_DRAFT_PROMPT = """You are the synthesis stage of a corpus-grounded \
research system. Write a thorough, well-structured answer to the research \
narrative using ONLY the evidence below. Do not use prior knowledge for \
factual claims; every claim must be supported by evidence.

Write clear declarative prose. After each factual sentence, cite ONLY the \
docid(s) that GENUINELY AND DIRECTLY support that exact sentence, in square \
brackets, e.g. [shard_00123_456] — never cite a docid just because it's \
topically nearby; a claim with no genuinely supporting evidence gets no \
citation. Cite at most 3 docids per sentence, ordered strongest to weakest \
support; do not pad to 3 when fewer are actually supported. Only cite docids \
that appear in the evidence below. Keep the whole answer under 1000 words.

RESEARCH NARRATIVE:
{narrative}

EVIDENCE:
{evidence}
"""

FACT_CHECK_PROMPT = """You are the fact-checker for a corpus-grounded \
research report. Below is a draft answer and the evidence it was written \
from. Check EVERY citation individually: read the cited docid's actual \
evidence text and confirm it specifically and directly supports the exact \
claim in the sentence it's attached to — topical closeness is not enough. \
A citation that is merely about the same general subject, without actually \
stating the claim, is NOT supported and must be dropped.

Rewrite the draft, correcting it in place: drop every citation that fails \
that check, remove or soften sentences left with no supporting citation, and \
add a citation from the evidence below to any sentence with a factual claim \
that currently has none but could be genuinely supported. Where a sentence \
keeps multiple citations, order them strongest to weakest support, and never \
add a citation just to reach 3 — 1 correct citation beats 3 where 2 are \
padding. Do not add new claims that are not already in the draft or \
supportable by the evidence.

Return ONLY the corrected prose (no JSON, no commentary, no code fences).

RESEARCH NARRATIVE:
{narrative}

DRAFT:
{draft}

EVIDENCE:
{evidence}
"""
