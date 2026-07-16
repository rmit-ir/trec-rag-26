"""aus_agent — research-agent RAG harness for TREC RAG 2026.

Loop: model turns with ``search`` (hybrid ClimbMix retrieval) + ``get_document``
(full text by docid) tools until the model stops calling tools or the round
budget is hit, then one strict-JSON final-answer step. Every reasoning block
and tool call is recorded (in order) into a ``ragrun`` trajectory; the answer
is mapped to a track-valid output object and both are saved via ``save_run``.

Timing: every item carries wall-clock ``t_start``/``t_end`` (``ragrun.now_iso``,
Melbourne local) and a 0-based ``turn`` index; tool calls issued in one model
turn are executed in parallel (threads), so same-``turn`` items with
overlapping bounds genuinely ran concurrently. ``finalize`` records run-level
``started_at``/``ended_at``.

Corpus-only: the agent retrieves exclusively from ClimbMix; every citation is
a ClimbMix docid the agent actually saw during this run.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run
from tools.search_tool import SEARCH_TOOL, run_search_tool
from utils.fetch_doc import fetch_doc

from providers.base import Provider

DOC_MAX_CHARS = 8000  # cap get_document output fed back to the model

GET_DOCUMENT_TOOL: dict[str, Any] = {
    "name": "get_document",
    "description": (
        "Fetch the full text of a ClimbMix document by its docid (e.g. "
        "shard_00459_61697). Use this after search to read a promising "
        "passage's full document before relying on it as evidence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "docid": {
                "type": "string",
                "description": "ClimbMix document id from a search result.",
            },
        },
        "required": ["docid"],
    },
}

SYSTEM_PROMPT = """\
You are a research agent for TREC RAG 2026. Given a research request, you
produce a well-organized, evidence-grounded research report using ONLY the
ClimbMix corpus, accessed through your tools. You have no web access and must
not rely on your own prior knowledge for factual claims.

Method:
- Break the request into subtopics and search for each. Start broad, then
  iterate with refined and alternative phrasings; issue multiple searches.
- Before each batch of tool calls, state briefly in plain text what you are
  looking for and why (one or two sentences).
- Read search snippets critically; call get_document on the most promising
  docids to read full documents before treating them as evidence.
- Track which docid supports which fact — every claim in your final report
  must be attributable to specific ClimbMix docids you retrieved.
- Cover the request's aspects with multiple sections; prefer breadth of
  well-supported evidence over speculation.
- When you have gathered enough evidence, stop calling tools and wait for
  the final-answer instruction.

Rules:
- Cite only ClimbMix docids returned by your tools in this conversation.
- Do not fabricate docids or facts. If the corpus lacks coverage on a point,
  say so rather than inventing support.
"""

TASK_PROMPT = """\
Research request:

{query}

Research this thoroughly using the search and get_document tools. Once you \
have enough evidence, I will ask you for the final structured report.
"""

FINAL_PROMPT = """\
Now write the final research report. Respond with ONLY a JSON object — no \
prose, no markdown fences — in exactly this format:

{{"answer": [{{"text": "<one sentence>", "citations": ["<docid>", ...]}}, ...]}}

Rules:
- Each item is ONE sentence of the report, in reading order (you may organize
  the report into logical sections; each sentence is still its own item).
- "citations" lists 0-3 ClimbMix docids that directly support that sentence.
- Use ONLY docids you actually retrieved in this conversation, e.g.: {docids}
- Every factual sentence should carry at least one citation.
- The whole report must be at most 1024 words in total.
"""

RETRY_PROMPT = (
    'Your reply was not valid JSON of the form {"answer": [{"text": ..., '
    '"citations": [...]}]}. Respond again with ONLY that JSON object.'
)

COMPRESS_PROMPT = (
    "Your report is {n} words; the hard limit is 1024 words total. Rewrite it "
    "more concisely in the SAME JSON format (JSON object only, no prose), "
    "keeping the citations."
)


def make_provider(backend: str, model: str | None) -> Provider:
    if backend == "bedrock":
        from providers.bedrock import BedrockProvider
        return BedrockProvider(model)
    raise ValueError(f"unknown backend: {backend!r} (available: bedrock)")


# -- tool execution ----------------------------------------------------------

def _execute_tool(name: str, args: dict[str, Any], *, k: int,
                  seen_docids: set[str]) -> tuple[str, list[dict] | None, bool]:
    """Run one tool call; returns (output_str, returned hits, failed)."""
    if name == "search":
        out = run_search_tool(query=str(args.get("query", "")),
                              k=int(args.get("k", k)))
        data = json.loads(out)
        if "error" in data:
            return out, None, True
        returned = [{"docid": r["docid"], "score": r["rrf_score"]}
                    for r in data["results"]]
        seen_docids.update(h["docid"] for h in returned)
        return out, returned, False
    if name == "get_document":
        docid = str(args.get("docid", ""))
        try:
            doc = fetch_doc(docid)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"}), None, True
        seen_docids.add(doc["docid"])
        out = json.dumps({"docid": doc["docid"],
                          "text": doc["text"][:DOC_MAX_CHARS]},
                         ensure_ascii=False)
        return out, [{"docid": doc["docid"], "score": None}], False
    return json.dumps({"error": f"unknown tool {name!r}"}), None, True


def _execute_tool_calls(calls: list[dict[str, Any]], *, k: int,
                        seen_docids: set[str]) -> list[tuple]:
    """Execute one model turn's tool calls IN PARALLEL (threads; the tools are
    I/O-bound and thread-safe). Returns, in the model's tool_use order, one
    ``(output_str, returned, failed, t_start, t_end)`` tuple per call — each
    call carries its own real wall-clock bounds."""
    def timed(call: dict[str, Any]) -> tuple:
        t0 = now_iso()
        out, returned, failed = _execute_tool(
            call["name"], call["arguments"], k=k, seen_docids=seen_docids)
        return out, returned, failed, t0, now_iso()

    if len(calls) == 1:
        return [timed(calls[0])]
    with ThreadPoolExecutor(max_workers=min(len(calls), 8)) as ex:
        futures = [ex.submit(timed, c) for c in calls]  # submission order
        return [f.result() for f in futures]


# -- final answer parsing / mapping ------------------------------------------

def _parse_answer_json(text: str | None) -> list[dict[str, Any]] | None:
    """Extract {"answer": [...]} from model text; None if unparseable."""
    if not text:
        return None
    t = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
    answer = obj.get("answer") if isinstance(obj, dict) else None
    if not isinstance(answer, list) or not answer:
        return None
    sents = []
    for item in answer:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        cits = item.get("citations", [])
        sents.append({"text": str(item["text"]).strip(),
                      "citations": [str(c) for c in cits]
                      if isinstance(cits, list) else []})
    return sents or None


def _map_citations(sentences: list[dict[str, Any]],
                   seen_docids: set[str]) -> tuple[list[str], list[dict]]:
    """docid citations -> reference indices; references = unique cited docids
    in first-cited order; citations of never-retrieved docids are dropped."""
    references: list[str] = []
    answer: list[dict[str, Any]] = []
    for sent in sentences:
        idxs: list[int] = []
        for docid in sent["citations"]:
            if len(idxs) >= 3:  # cap BEFORE registering, or refs go uncited
                break
            if docid not in seen_docids:
                continue
            if docid not in references:
                references.append(docid)
            idx = references.index(docid)
            if idx not in idxs:
                idxs.append(idx)
        answer.append({"text": sent["text"], "citations": idxs})
    return references, answer


def _word_count(sentences: list[dict[str, Any]]) -> int:
    return sum(len(s["text"].split()) for s in sentences)


def _truncate_to_limit(sentences: list[dict[str, Any]],
                       limit: int = 1024) -> list[dict[str, Any]]:
    """Deterministic last resort: drop trailing sentences until under limit."""
    kept: list[dict[str, Any]] = []
    total = 0
    for s in sentences:
        n = len(s["text"].split())
        if total + n > limit:
            break
        kept.append(s)
        total += n
    return kept or sentences[:1]


# -- harness -------------------------------------------------------------------

def _record_turn(tb: TrajectoryBuilder, turn: dict[str, Any], *,
                 narration_as_reasoning: bool = False,
                 t_start: str | None = None, t_end: str | None = None,
                 turn_index: int | None = None) -> None:
    """Record a turn's reasoning (tool calls are recorded on execute).

    Sonnet 5 on Bedrock returns signature-only ``reasoningContent`` (empty
    text), so with ``narration_as_reasoning`` the model's plain-text narration
    interleaved with tool calls is recorded as reasoning too.

    ``t_start``/``t_end`` are the provider call's wall-clock bounds; every
    reasoning block of the turn shares them (and ``turn_index``).
    """
    for block in turn["blocks"]:
        if block["type"] == "reasoning":
            tb.add_reasoning(block["text"], t_start=t_start, t_end=t_end,
                             turn=turn_index)
        elif (block["type"] == "text" and narration_as_reasoning
              and turn["tool_calls"]):
            tb.add_reasoning(block["text"], t_start=t_start, t_end=t_end,
                             turn=turn_index)


def run_agent(query_id: str, query: str, *, backend: str = "bedrock",
              model: str | None = None, k: int = 10, max_rounds: int = 12,
              run_id: str = "aus-agent-dev",
              run_desc: str | None = None) -> dict[str, Any]:
    """Run one topic end-to-end; saves trajectory + output, returns paths."""
    provider = make_provider(backend, model)
    tb = TrajectoryBuilder(query_id, query, metadata={
        "model": provider.model_id,
        "backend": backend,
        "k": k,
        "max_rounds": max_rounds,
        "temperature": None,  # sampling params not sent (removed on 4.6+)
        "run_id": run_id,
    })
    seen_docids: set[str] = set()
    status = "completed"
    sentences: list[dict[str, Any]] | None = None

    run_started = now_iso()
    turn_idx = -1  # 0-based model-turn index; bumped on every provider call
    # Wall-clock bounds + turn index of the LAST model turn (the final-answer
    # turn's bounds end up on the output_text item).
    last_turn: tuple[str | None, str | None, int | None] = (None, None, None)

    def timed_turn() -> dict[str, Any]:
        """Run one model turn, tracking wall-clock bounds and turn index."""
        nonlocal turn_idx, last_turn
        turn_idx += 1
        t0 = now_iso()
        turn = provider.run_turn()
        last_turn = (t0, now_iso(), turn_idx)
        return turn

    try:
        provider.start(SYSTEM_PROMPT, [SEARCH_TOOL, GET_DOCUMENT_TOOL])
        provider.add_user_message(TASK_PROMPT.format(query=query))

        # -- research loop ---------------------------------------------------
        rounds = 0
        while True:
            rounds += 1
            turn = timed_turn()
            t0, t1, ti = last_turn
            _record_turn(tb, turn, narration_as_reasoning=True,
                         t_start=t0, t_end=t1, turn_index=ti)
            if not turn["tool_calls"]:
                break
            if rounds >= max_rounds:
                status = "budget_exhausted"
                budget_msg = json.dumps({"error": "tool budget exhausted; "
                                         "produce the final answer now"})
                ts = now_iso()  # calls are refused, not run: zero-width bounds
                results = []
                for call in turn["tool_calls"]:
                    tb.add_tool_call(call["name"], call["arguments"],
                                     budget_msg, failed=True,
                                     t_start=ts, t_end=ts, turn=ti)
                    results.append({"id": call["id"], "content": budget_msg,
                                    "is_error": True})
                provider.add_tool_results(results)
                break
            # All tool calls of this turn run in parallel; items are appended
            # (and results returned to the provider) in the model's tool_use
            # order regardless of completion order.
            executed = _execute_tool_calls(turn["tool_calls"], k=k,
                                           seen_docids=seen_docids)
            results = []
            for call, (out, returned, failed, ct0, ct1) in zip(
                    turn["tool_calls"], executed):
                tb.add_tool_call(call["name"], call["arguments"], out,
                                 returned=returned, failed=failed,
                                 t_start=ct0, t_end=ct1, turn=ti)
                results.append({"id": call["id"], "content": out,
                                "is_error": failed})
            provider.add_tool_results(results)

        # -- final structured-answer step -------------------------------------
        docids_hint = ", ".join(sorted(seen_docids)[:60]) or "(none retrieved)"
        provider.add_user_message(FINAL_PROMPT.format(docids=docids_hint))
        for attempt in range(3):
            turn = timed_turn()
            t0, t1, ti = last_turn
            _record_turn(tb, turn, t_start=t0, t_end=t1, turn_index=ti)
            if turn["tool_calls"]:  # tools are off-limits now
                msg = json.dumps({"error": "tool use is disabled in the "
                                  "final-answer step; respond with the JSON "
                                  "object only"})
                provider.add_tool_results(
                    [{"id": c["id"], "content": msg, "is_error": True}
                     for c in turn["tool_calls"]])
                continue
            sentences = _parse_answer_json(turn["text"])
            if sentences:
                break
            if attempt < 2:
                provider.add_user_message(RETRY_PROMPT)
        if not sentences:
            raise RuntimeError("model never produced a parseable final answer")

        # -- word limit (ask once to compress, then hard-truncate) -----------
        if _word_count(sentences) > 1024:
            provider.add_user_message(
                COMPRESS_PROMPT.format(n=_word_count(sentences)))
            turn = timed_turn()
            t0, t1, ti = last_turn
            _record_turn(tb, turn, t_start=t0, t_end=t1, turn_index=ti)
            compressed = _parse_answer_json(turn["text"])
            if compressed and _word_count(compressed) <= 1024:
                sentences = compressed
            else:
                sentences = _truncate_to_limit(compressed or sentences)

    except Exception as e:
        status = "failed"
        if not sentences:
            sentences = [{"text": f"Run failed: {type(e).__name__}: {e}",
                          "citations": []}]

    references, answer = _map_citations(sentences, seen_docids)
    answer_text = " ".join(s["text"] for s in answer)
    tb.add_output_text(answer_text, t_start=last_turn[0], t_end=last_turn[1],
                       turn=last_turn[2])

    output = build_rag_output(
        narrative_id=query_id,
        narrative=query,
        run_id=run_id,
        run_desc=run_desc or (
            f"aus_agent research harness ({backend}/{provider.model_id}): "
            f"iterative hybrid dense+sparse ClimbMix search + document fetch, "
            f"strict-JSON cited sentence answers."),
        references=references,
        answer=answer,
    )
    trajectory = tb.finalize(status=status, raw_messages=provider.raw_messages,
                             started_at=run_started, ended_at=now_iso())
    paths = save_run("aus_agent", query, trajectory=trajectory, output=output)
    return {"status": status, "paths": paths,
            "tool_call_counts": trajectory["tool_call_counts"],
            "n_references": len(references), "n_sentences": len(answer),
            "words": _word_count(answer)}
