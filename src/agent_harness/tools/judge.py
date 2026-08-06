"""Global, opt-in ``judge_relevance`` tool (PLAN.md Phase 4b §7.4, in
``src/systems/facets_agent/PLAN.md``): a second, cheap model checks whether
staged/committed documents actually support a requirement, or are only
topically adjacent to it, and suggests a reformulated query when none do.

Not owned by any one system, unlike ``commit_context``/``search`` in this
same package (those carry facets_agent's own extended schemas layered on
top elsewhere) -- this tool's definition and handler are complete here, so
ANY system opts in with one line: ``run_agent(...,
judge_tool=JUDGE_RELEVANCE_TOOL)``. The model decides for itself when a
batch looks doubtful enough to spend the call; there is no automatic
harness-side trigger. Deliberately NOT wired into any system's
``tool_definitions`` by default -- ``run_agent``'s ``judge_tool`` parameter
defaults to ``None``, so a caller that never passes it is byte-identical to
before this tool existed, same discipline as ``pre_final_hook``.

The judge runs on a FRESH, single-turn conversation with its OWN model --
independent of and orthogonal to whatever model is driving the main loop
(``Provider`` is already model-agnostic, see ``providers/base.py``) -- so
this never touches the primary model's context budget or turn count, only
wall-clock time and the judge model's own (cheap) cost.
"""
from __future__ import annotations

import json
from typing import Any

from ..context import ContextLedger

JUDGE_RELEVANCE_TOOL: dict[str, Any] = {
    "name": "judge_relevance",
    "description": (
        "Ask a fast, separate model whether the given documents actually "
        "support a specific requirement, or are only topically similar to "
        "it -- the case where a query returns plausible-looking results "
        "that are adjacent to the topic but never actually state what the "
        "requirement needs (e.g. general background on a subject when the "
        "requirement needs one specific named entity, figure, or "
        "mechanism). Call this when a batch looks retrievable but you are "
        "not confident it truly answers the requirement, BEFORE spending a "
        "commit_context decision on it -- not on every batch, only a "
        "doubtful one. Costs one inexpensive model call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requirement": {
                "type": "string",
                "description": (
                    "The requirement this batch is meant to serve, in the "
                    "same words used on the search call that staged it."
                ),
            },
            "document_ids": {
                "type": "array",
                "description": (
                    "Staged or committed ids to check, exactly as returned "
                    "by search/get_documents."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["requirement", "document_ids"],
    },
}

# openai.gpt-oss-120b-1:0 is the established, already-verified-working
# choice for a cheap Bedrock judge model in this repo (RAGDoll's
# support/UMBRELA judging pipelines; see providers/bedrock.py's own
# docstring for the region caveat -- it works in the default ap-southeast-2,
# unlike qwen.* which needs us-east-1/us-west-2 under this account).
DEFAULT_JUDGE_BACKEND = "bedrock"
DEFAULT_JUDGE_MODEL = "openai.gpt-oss-120b-1:0"

# Drafted by gpt-5.6-luna (2026-08-06), asked to optimize specifically for
# openai.gpt-oss-120b-1:0 (a smaller open-weight model, not GPT-4-class) on
# three things: reliably telling `adjacent_not_relevant` apart from
# `relevant` (the hardest category and the whole point of the tool), strict
# JSON with no markdown fences, and staying concise since this runs on
# every doubtful batch. See worklogs/assets/2026-08-06-draft-judge-prompt.py
# for the exact meta-prompt used.
_SYSTEM_PROMPT = """\
You are a strict relevance judge for a retrieval system. Your job is to \
classify every document against the REQUIREMENT, not merely judge whether \
it discusses the same broad topic.

## Decision rules

1. Read the REQUIREMENT first. Identify the exact fact, entity, \
relationship, action, mechanism, date, or other detail it requests.
2. Evaluate each DOCUMENT independently using only its text. Do not fill \
gaps with outside knowledge or assumptions.
3. Use these labels:
   - `relevant`: The document explicitly states or directly supports the \
specific information requested. It need not use the same wording, but the \
requested fact must be recoverable from the document.
   - `adjacent_not_relevant`: The document concerns the same subject or \
broad topic, but does not state or support the specific information \
requested.
   - `irrelevant`: The document does not materially concern the requirement.
4. Be conservative. Topic overlap, shared keywords, broad background, or \
plausible implications are not enough for `relevant`.
5. The main error to avoid is calling an adjacent document relevant. \
Example: if the requirement asks for a named company's role in developing \
a game, a document describing the game's general development history \
without naming or linking that company is `adjacent_not_relevant`, not \
`relevant`.
6. A document may be `relevant` even if it is brief or indirect, but only \
when it provides usable evidence for the exact requirement.
7. Preserve every document `id` exactly and return exactly one verdict for \
every input document, in input order.

## Reformulation rule

If and only if no document is labeled `relevant`, set \
`suggested_reformulation` to one concrete, actionable suggestion. Prefer:
- a narrower phrase,
- a missing named entity, exact title, identifier, or relationship for \
`keyword` search,
- or `semantic` search when the requirement is conceptual rather than \
name-specific.

If at least one document is `relevant`, set `suggested_reformulation` to \
`null`.

## Output rules

Return exactly one valid JSON object and nothing else. No explanation, \
preamble, commentary, Markdown, or code fences. Use this exact schema:

{"verdicts":[{"id":"<original id>","verdict":"relevant|adjacent_not_relevant\
|irrelevant","reason":"<one concise sentence>"},...],"suggested_reformulation\
":"<one concrete suggestion, or null>"}

Use valid JSON double quotes. Escape any quotes or special characters \
inside string values. Keep each reason short and evidence-based. Do not \
add fields.\
"""
_USER_TMPL = """REQUIREMENT:
{requirement}

DOCUMENTS:
{documents}
"""


def _documents_by_id(ledger: ContextLedger) -> dict[str, dict[str, Any]]:
    """Every document ever staged, keyed by id.

    ``call_history`` is kept for the life of the run (see
    ``ContextLedger``'s own docstring), unlike ``pending`` which clears on
    each commit -- so this resolves a committed, rejected, or currently
    pending id alike, whatever the model names in ``document_ids``.
    """
    out: dict[str, dict[str, Any]] = {}
    for result in ledger.call_history.values():
        for document in result.documents:
            out.setdefault(str(document["id"]), document)
    return out


def execute_judge_relevance(
        arguments: dict[str, Any], ledger: ContextLedger, *,
        backend: str = DEFAULT_JUDGE_BACKEND,
        model: str = DEFAULT_JUDGE_MODEL) -> str:
    """Run one judge turn on a fresh, separate model conversation.

    Returns the tool-result content (a JSON string) -- never raises. A
    judge failure (bad model id, network error, unparsable response)
    degrades to an error envelope the calling model can read and move past,
    the same "a tool call cannot fail the run" principle every other
    handler here follows.
    """
    requirement = str(arguments.get("requirement", "")).strip()
    document_ids = [str(d) for d in (arguments.get("document_ids") or [])]
    by_id = _documents_by_id(ledger)
    found = [by_id[docid] for docid in document_ids if docid in by_id]
    missing = [docid for docid in document_ids if docid not in by_id]
    if not requirement or not found:
        return json.dumps({
            "error": "no requirement given, or none of document_ids match "
                     "a document staged or committed earlier in this run",
            "missing": missing,
        })

    documents_block = "\n\n".join(
        f"[{doc['id']}]\n{doc.get('text', '')}" for doc in found)
    user = _USER_TMPL.format(
        requirement=requirement, documents=documents_block)
    try:
        # Lazy import: `agent_harness.agent` imports THIS package at module
        # load time, so importing `make_provider` from there at this
        # module's top level would be circular.
        from ..agent import make_provider
        judge = make_provider(backend, model)
        judge.start(_SYSTEM_PROMPT, [])
        judge.add_user_message(user)
        turn = judge.run_turn()
        text = (turn.get("text") or "").strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        obj = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({
            "error": f"judge call failed: {type(exc).__name__}: {exc}"})
    if not isinstance(obj, dict):
        return json.dumps({"error": "judge returned non-object JSON"})
    obj.setdefault("missing", missing)
    return json.dumps(obj, ensure_ascii=False)
