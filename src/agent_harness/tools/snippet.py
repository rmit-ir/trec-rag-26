"""LLM-generated query-relevant search previews (PLAN.md Phase 4d follow-on,
in ``src/systems/facets_agent/PLAN.md``): the user's follow-up to the
positional-truncation two-tier prototype, whose whitespace-collapse/word-
boundary fix (see ``agent.py::_truncate_snippet``) didn't close the
citation-support gap. Instead of slicing a document's OPENING text, ask a
cheap secondary model (same convention as ``judge.py``) to extract the
span most relevant to the QUERY, for every document in one search batch,
capped at a fixed character length.

Global, not facets_agent's own -- lives here so any system's
``search_preview_generator`` can reuse it, same posture as
``judge_relevance``/``judge_documents``. Never citable on its own: like
every other preview mechanism in this family, ``get_documents`` stays the
only path to full, staged, citable text.
"""
from __future__ import annotations

import json
from typing import Any

DEFAULT_SNIPPET_BACKEND = "bedrock"
DEFAULT_SNIPPET_MODEL = "openai.gpt-oss-120b-1:0"
DEFAULT_SNIPPET_MAX_CHARS = 500

_SYSTEM_PROMPT = (
    "You extract short, query-relevant previews from documents. Given the "
    "ORIGINAL REQUEST, the SPECIFIC REQUIREMENT the current search is "
    "trying to satisfy, and a set of DOCUMENTS, write ONE snippet per "
    "document: the span of that document's own text most relevant to the "
    "request and requirement -- prefer the sentence(s) that actually bear "
    "on what's being asked over the document's opening lines, even if "
    "that means quoting from the middle or end. Weigh the SPECIFIC "
    "REQUIREMENT most heavily (that is what this exact search was for),"
    " but keep the ORIGINAL REQUEST's overall intent in view -- a "
    "requirement is one facet of a larger request, and a snippet that "
    "only makes sense narrowly can still mislead about the bigger "
    "picture. Quote or closely paraphrase the document; never add "
    "information the document does not contain. If nothing in a document "
    "is relevant, the snippet may instead be a short, truthful "
    "description of what the document IS about. Each snippet must be "
    "under the given character limit. Return STRICT JSON only, no other "
    "text: "
    '{"snippets": [{"id": "<id>", "snippet": "<text>"}, ...]}'
)
_USER_TMPL = """ORIGINAL REQUEST:
{query}

SPECIFIC REQUIREMENT THIS SEARCH IS FOR:
{requirement}

CHARACTER LIMIT PER SNIPPET: {max_chars}

DOCUMENTS:
{documents}
"""


def generate_snippets(
        query: str, requirement: str, documents: list[dict[str, Any]], *,
        backend: str = DEFAULT_SNIPPET_BACKEND,
        model: str = DEFAULT_SNIPPET_MODEL,
        max_chars: int = DEFAULT_SNIPPET_MAX_CHARS) -> dict[str, str]:
    """One LLM call for the whole batch. ``query`` is the FULL original
    research request (not just the current search's narrower
    ``requirement``) -- passed explicitly per user request, so a snippet
    stays relevant to the overall task even when a facet's own wording is
    narrow. Returns ``{id: snippet}`` -- never raises, and never includes
    an id whose snippet the model didn't return or that fails to parse, so
    a caller falls back to positional truncation
    (``agent.py::_truncate_snippet``) per-document on any gap rather than
    showing nothing. Every returned snippet is hard-capped to ``max_chars``
    server-side -- the prompt asks the model to respect the limit, but
    this never trusts it to.
    """
    query = query.strip()
    if not query or not documents:
        return {}
    documents_block = "\n\n".join(
        f"[{doc['id']}]\n{doc.get('text', '')}" for doc in documents)
    user = _USER_TMPL.format(
        query=query, requirement=requirement.strip() or "(not specified)",
        max_chars=max_chars, documents=documents_block)
    try:
        # Lazy import: `agent_harness.agent` imports THIS package at module
        # load time, so importing `make_provider` from there at this
        # module's top level would be circular (same reason as judge.py).
        from ..agent import make_provider
        provider = make_provider(backend, model)
        provider.start(_SYSTEM_PROMPT, [])
        provider.add_user_message(user)
        turn = provider.run_turn()
        text = (turn.get("text") or "").strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        obj = json.loads(text)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(obj, dict):
        return {}
    snippets = obj.get("snippets")
    if not isinstance(snippets, list):
        return {}
    out: dict[str, str] = {}
    for item in snippets:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("id", "")).strip()
        snippet = item.get("snippet")
        if uid and isinstance(snippet, str) and snippet.strip():
            out[uid] = snippet[:max_chars]
    return out
