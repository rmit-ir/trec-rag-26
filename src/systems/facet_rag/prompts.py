"""Prompts for the facet_rag orchestrator/analyzer architecture.

Two roles, five prompts:

- ``PLAN_PROMPT`` (orchestrator, one-shot) — decompose the narrative into
  independent research FACETS: a name, a description of what needs to be
  found, and a complexity-driven iteration budget (1-10). No engine/query is
  prescribed here — the orchestrator decides retrieval strategy live, per
  facet, in ``ORCHESTRATOR_SYSTEM_PROMPT``.
- ``ORCHESTRATOR_SYSTEM_PROMPT`` / ``ORCHESTRATOR_TASK_PROMPT`` (orchestrator,
  tool-calling loop) — search the corpus for one facet, choosing engines
  itself; reacts to a coverage-gap note from the analyzer by searching again.
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

ORCHESTRATOR_SYSTEM_PROMPT = """You are the search orchestrator for one facet \
of a larger research task. Your ONLY data source is the ClimbMix document \
corpus, reached through the `search` tool — there is no web search.

Each turn, call `search` to retrieve passages for the facet below. You choose \
the engine (or call it more than once with different engines, in the same \
turn, if you are unsure which will work best) and write the query in that \
engine's language. After your search, an analyst reviews the results and \
either accepts the facet as adequately covered or reports a specific \
coverage gap — if you receive a coverage gap, issue a new, more targeted \
search addressing exactly that gap. If you judge that no further search \
would add anything, respond with no tool call and a short reason.

AVAILABLE ENGINES:
{engine_blurbs}

QUERY-WRITING GUIDANCE (obey the guidance for the engine you pick):
{query_guidance}
"""

ORCHESTRATOR_TASK_PROMPT = """FACET: {facet_name}

{facet_description}

Search now."""

ORCHESTRATOR_GAP_PROMPT = """Coverage gap reported by the analyst:

{gap}

Search again to address this gap specifically."""

ANALYZER_PROMPT = """You are the analyst for one facet of a corpus-grounded \
research task. Read the newly retrieved passages below and judge them ONLY \
against this facet's need — ignore anything irrelevant to it.

FACET: {facet_name}

{facet_description}

EVIDENCE ALREADY SAVED FOR THIS FACET:
{evidence_so_far}

NEWLY RETRIEVED PASSAGES:
{passages}

For each newly retrieved passage that supports the facet, keep it: note what \
it supports and why. Then judge whether the facet is now adequately covered \
by the saved + newly kept evidence together, or whether a specific gap \
remains that another search could fill (name the gap concretely, e.g. what \
aspect, entity, or comparison is still missing — not "need more info").

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"relevant": [{{"docid": "<docid from the passages above>", \
"note": "<what it supports>"}}, ...], \
"gap": "<specific remaining gap, or null if none>", \
"satisfied": <true if no further search is needed, else false>}}
"""

SYNTH_DRAFT_PROMPT = """You are the synthesis stage of a corpus-grounded \
research system. Write a thorough, well-structured answer to the research \
narrative using ONLY the evidence below. Do not use prior knowledge for \
factual claims; every claim must be supported by evidence.

Write clear declarative prose. After each factual sentence, cite the docid(s) \
of the evidence that support it in square brackets, e.g. [shard_00123_456]. \
Only cite docids that appear in the evidence below. Keep the whole answer \
under 1000 words.

RESEARCH NARRATIVE:
{narrative}

EVIDENCE:
{evidence}
"""

FACT_CHECK_PROMPT = """You are the fact-checker for a corpus-grounded \
research report. Below is a draft answer and the evidence it was written \
from. Check EVERY citation: a citation is only valid if the cited docid's \
evidence text actually supports the sentence it's attached to.

Rewrite the draft, correcting it in place: drop citations that are not \
supported, remove or soften sentences left with no supporting citation, and \
add a citation from the evidence below to any sentence with a factual claim \
that currently has none but could be supported. Do not add new claims that \
are not already in the draft or supportable by the evidence.

Return ONLY the corrected prose (no JSON, no commentary, no code fences).

RESEARCH NARRATIVE:
{narrative}

DRAFT:
{draft}

EVIDENCE:
{evidence}
"""
