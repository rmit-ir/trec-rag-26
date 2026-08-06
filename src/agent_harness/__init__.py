"""agent_harness — shared staged-context, tool-calling research-agent loop.

Extracted from aus_agent so sibling systems (facets_agent, facet_rag) consume
it as a real shared layer (like ``ragrun``/``tools``/``utils``) instead of
importing from another system's package. See ``agent.py`` for the loop
(``run_agent``), ``context.py`` for ``ContextLedger``, ``providers/`` for the
pluggable Bedrock/OpenAI backends, and ``tools/`` for the search/
commit_context/get_documents tool definitions and executors.
"""
