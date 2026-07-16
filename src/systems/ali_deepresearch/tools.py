"""ClimbMix corpus tools for the Tongyi DeepResearch port.

Replaces upstream's web tools (Serper ``search``, ``visit``, ``google_scholar``,
``PythonInterpreter``) with the two the ClimbMix RAG agent is allowed to use at
runtime:

- ``search(query)``       — hybrid dense+sparse RRF retrieval over ClimbMix,
  wired to ``tools.search_tool.run_search_tool``. Accepts a single query string
  or a list of query strings (upstream's batched form); a list is de-duplicated
  and fused into one ranked list.
- ``get_document(docid)`` — full document text, wired to ``utils.fetch_doc``.

``ClimbMixTools`` is **stateful**: like the reference trajectory's retriever it
de-duplicates documents across search steps (a doc surfaced earlier is not shown
again in the main results; it is listed under an "Already-seen" section instead).
Each executed call returns ``(text, meta)`` — ``text`` is the ``<tool_response>``
body the model sees; ``meta`` carries the trajectory extras (``returned``,
``returned_docids``, ``hidden``, ``found_docids_before_search``,
``previous_queries_before_search``, ``k`` …) mirrored from the sample run.
"""
from __future__ import annotations

import json
from typing import Any

from tools.search_tool import run_search_tool
from utils.fetch_doc import fetch_doc

# ClimbMix docids carry no titles; derive a short pseudo-title from the snippet
# so the search block reads like the upstream "[Title]" line.
_TITLE_WORDS = 8


def _pseudo_title(text: str) -> str:
    words = (text or "").split()
    title = " ".join(words[:_TITLE_WORDS]).strip()
    return title or "untitled"


class ClimbMixTools:
    """Stateful corpus toolbox for one agent run."""

    def __init__(self, *, snippet_chars: int = 320) -> None:
        self.snippet_chars = snippet_chars
        self._seen: set[str] = set()          # docids already surfaced by search
        self._queries: list[str] = []         # every query issued so far

    # -- search ------------------------------------------------------------

    def search(self, query: str | list[str], k: int = 10) -> tuple[str, dict[str, Any]]:
        """Run one (possibly batched) search; return ``(response_text, meta)``."""
        if isinstance(query, str):
            queries = [query]
        elif isinstance(query, list):
            queries = [str(q) for q in query if str(q).strip()]
        else:
            queries = [str(query)]
        if not queries:
            return "[Search] Empty query.", {"failed": True}

        primary = queries[0]
        found_before = sorted(self._seen)
        prev_queries = list(self._queries)

        # Gather + fuse candidates across the batched queries (dedupe by docid,
        # keep the best RRF score seen for each).
        cand: dict[str, dict[str, Any]] = {}
        for q in queries:
            raw = json.loads(run_search_tool(q, k=k, max_chars=self.snippet_chars))
            if "error" in raw:
                return f"Search error: {raw['error']}", {"failed": True}
            for r in raw.get("results", []):
                d = r["docid"]
                if d not in cand or r["rrf_score"] > cand[d]["rrf_score"]:
                    cand[d] = r
        ordered = sorted(cand.values(), key=lambda r: r["rrf_score"], reverse=True)

        # Split into new vs. already-seen (cross-step de-duplication).
        new: list[dict[str, Any]] = []
        hidden: list[str] = []
        for r in ordered:
            if r["docid"] in self._seen:
                hidden.append(r["docid"])
            else:
                new.append(r)
        new = new[:k]
        for r in new:
            self._seen.add(r["docid"])
        self._queries.extend(queries)

        text = self._format_search(primary, new, hidden)
        meta: dict[str, Any] = {
            "returned": [{"docid": r["docid"], "score": r["rrf_score"]} for r in new],
            "returned_docids": [r["docid"] for r in new],
            "hidden": hidden,
            "found_docids_before_search": found_before,
            "previous_queries_before_search": prev_queries,
            "k": k,
            "query_style": "plain",
            "original_query": primary,
            "retrieval_query": primary,
        }
        return text, meta

    def _format_search(self, query: str, new: list[dict[str, Any]],
                       hidden: list[str]) -> str:
        lines = [f"A search for '{query}' found {len(new)} results:", "",
                 "## Web Results"]
        for r in new:
            snippet = (r.get("text") or "").strip()
            lines.append(f"DocID:{r['docid']}")
            lines.append(f"[{_pseudo_title(snippet)}]")
            if snippet:
                lines.append(snippet)
            lines.append("")
        if hidden:
            lines.append("## Already-seen (retrieve full text with get_document)")
            for d in hidden:
                lines.append(f"DocID:{d}")
        return "\n".join(lines).strip()

    # -- get_document ------------------------------------------------------

    def get_document(self, docid: str) -> tuple[str, dict[str, Any]]:
        """Fetch full document text; return ``(response_text, meta)``."""
        did = str(docid).strip()
        if not did:
            return "[get_document] Missing docid.", {"failed": True}
        try:
            doc = fetch_doc(did)
        except Exception as e:  # surface as tool output, not an exception
            return (f"Error retrieving document {did}: {type(e).__name__}: {e}",
                    {"docid": did, "failed": True})
        text = (doc.get("text") or "").strip()
        resolved = doc.get("docid", did)
        if not text:
            return f"Document {resolved}: (no content found)", {"docid": resolved}
        return f"Document {resolved}:\n{text}", {"docid": resolved}


def dispatch(toolbox: ClimbMixTools, name: str, args: dict[str, Any],
             *, k: int = 10) -> tuple[str, dict[str, Any], bool]:
    """Execute a parsed tool call. Returns ``(response_text, meta, failed)``.

    Mirrors upstream's ``custom_call_tool`` dispatch but limited to the two
    ClimbMix tools. Unknown tools return an error string (not an exception) so
    the agent can recover.
    """
    if name == "search":
        if "query" not in args:
            return ("[Search] Invalid request: missing 'query'.",
                    {"failed": True}, True)
        text, meta = toolbox.search(args["query"], k=args.get("k", k))
        return text, meta, bool(meta.get("failed"))
    if name == "get_document":
        if "docid" not in args:
            return ("[get_document] Invalid request: missing 'docid'.",
                    {"failed": True}, True)
        text, meta = toolbox.get_document(args["docid"])
        return text, meta, bool(meta.get("failed"))
    return (f"Error: Tool {name} not found. The only available tools are "
            f"search and get_document.", {"failed": True}, True)
