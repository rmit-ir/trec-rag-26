"""Prompts for the facet_rag plan-then-execute system.

Two LLM stages only:

- ``PLAN_PROMPT`` — decompose the narrative into independent search *facets*,
  each pinned to one retrieval engine and a query written in that engine's
  language. The engine list, per-engine "when to use" blurbs, and query-writing
  guidance are injected at runtime from ``tools.search_tool`` so they always
  match the enabled engines (single source of truth — never restated here).
- ``SYNTHESIZE_PROMPT`` — write the grounded prose report from the retrieved
  passages. The strict sentence/citation shape the track requires is produced
  downstream by ``ali_deepresearch.answer_format.format_answer``; this stage
  only needs faithful, citable prose.
"""
from __future__ import annotations

PLAN_PROMPT = """You are the planning stage of a corpus-grounded research system. \
Your ONLY data source is the ClimbMix document corpus, reached through a `search` \
tool. There is no web search.

Break the research narrative below into a small set of independent SEARCH FACETS. \
A facet is one distinct sub-question or aspect of the narrative that can be \
answered by a single focused search. Aim for {min_facets}-{max_facets} facets: \
enough to cover every distinct aspect the narrative raises, no more. Do not \
create two facets that would return the same documents.

For each facet choose the retrieval ENGINE best suited to it and write the QUERY \
in that engine's query language.

AVAILABLE ENGINES:
{engine_blurbs}

QUERY-WRITING GUIDANCE (obey the guidance for the engine you pick):
{query_guidance}

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{{"facets": [{{"name": "<short aspect label>", "engine": "<engine name>", \
"query": "<query in that engine's language>", "k": <how many passages, 5-20>}}, ...]}}

RESEARCH NARRATIVE:
{narrative}
"""

SYNTHESIZE_PROMPT = """You are the synthesis stage of a corpus-grounded research \
system. Write a thorough, well-structured answer to the research narrative using \
ONLY the retrieved passages below. Do not use prior knowledge for factual claims; \
every claim must be supported by a passage. If the passages do not cover part of \
the narrative, say so rather than inventing an answer.

Write clear declarative prose. After each factual sentence, cite the docid(s) of \
the passage(s) that support it in square brackets, e.g. [shard_00123_456]. Only \
cite docids that appear in the passages below. Keep the whole answer under 1000 \
words.

RESEARCH NARRATIVE:
{narrative}

RETRIEVED PASSAGES:
{passages}
"""
