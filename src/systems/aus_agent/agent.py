"""aus_agent — research-agent RAG harness for TREC RAG 2026.

Loop: model turns with full-text ``search`` retrieval. Tool outputs are staged
for exactly one model step, after
which the model must call ``commit_context``: selected documents stay verbatim
in the conversation and rejected documents are compacted to decision markers.
The current provider input-context size, rather than a normal tool/round limit,
determines when research stops. A high round count remains only as a runaway-
loop safety backstop.

The organizer-compatible trajectory stays strict. Rich ``output.json.trace``
steps carry wall-clock ``t_start``/``t_end`` (Melbourne local), token stats,
documents, context decisions, and a 0-based ``turn`` index. Tool calls issued
in one model turn execute in parallel, so overlapping bounds are genuine.

Every citation must identify evidence returned by the available retrieval
tools and explicitly retained by the agent.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

from ragrun import TrajectoryBuilder, build_rag_output, now_iso, save_run

from .context import ContextLedger
from .providers.base import Provider
from .tools import (
    COMMIT_CONTEXT_TOOL,
    SEARCH_TOOL_DEF,
    apply_commit,
    execute_full_text_search,
    expire_staged,
)

DEFAULT_CONTEXT_TOKEN_BUDGET = 500_000
DEFAULT_SAFETY_MAX_ROUNDS = 100
DEFAULT_MAX_COMMITTED_PER_STEP = 6
SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / "system.md")
MAX_COMMITTED_PLACEHOLDER = "__MAX_COMMITTED_DOCS__"

TASK_PROMPT = """\
Research request:

{query}
"""


def load_system_prompt(max_committed: int) -> str:
    """Load the system prompt relative to this module and render one token."""
    template = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    count = template.count(MAX_COMMITTED_PLACEHOLDER)
    if count != 1:
        raise RuntimeError(
            f"{SYSTEM_PROMPT_PATH} must contain exactly one "
            f"{MAX_COMMITTED_PLACEHOLDER} placeholder; found {count}")
    return template.replace(MAX_COMMITTED_PLACEHOLDER, str(max_committed))


def make_provider(backend: str, model: str | None) -> Provider:
    if backend == "bedrock":
        from .providers.bedrock import BedrockProvider
        return BedrockProvider(model)
    raise ValueError(f"unknown backend: {backend!r} (available: bedrock)")


def _execute_tool_calls(calls: list[dict[str, Any]], *, k: int,
                        seen_docids: set[str]) -> list[tuple]:
    """Execute one model turn's tool calls IN PARALLEL (threads; the tools are
    I/O-bound and thread-safe). Returns, in the model's tool_use order, one
    ``(output, trace_output, returned, failed, documents, t_start, t_end,
    duration_ms)``
    tuple per call — each
    call carries its own real wall-clock bounds."""
    def timed(call: dict[str, Any]) -> tuple:
        t0 = now_iso()
        started = perf_counter()
        execution = execute_full_text_search(
            call["arguments"], default_k=k, seen_docids=seen_docids)
        return (execution.output, execution.trace_output,
                execution.returned, execution.failed, execution.documents,
                t0, now_iso(),
                round((perf_counter() - started) * 1000, 3))

    if len(calls) == 1:
        return [timed(calls[0])]
    with ThreadPoolExecutor(max_workers=min(len(calls), 8)) as ex:
        futures = [ex.submit(timed, c) for c in calls]  # submission order
        return [f.result() for f in futures]


# -- final answer parsing / mapping ------------------------------------------

# A citation marker is one bracket group holding one or more docid tokens,
# e.g. ``[shard_00459_61697]`` or ``[shard_a, shard_b]``.
_CITATION_MARKER_RE = re.compile(r"\[([^\[\]]+)\]")
_CITATION_TOKEN_SPLIT_RE = re.compile(r"[,;\s]+")
# Markdown structure the final report must not contain: headings, bullet or
# numbered list markers, blockquotes, and fences.
_MARKDOWN_LINE_RE = re.compile(r"^(#{1,6}\s|[-*+]\s|>\s|\d{1,3}[.)]\s|```)")


def _parse_final_prose(
    text: str | None,
    committed_docids: set[str],
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Parse and validate the attempted final report.

    The contract is prose, one sentence per line, citing committed docids with
    inline ``[docid]`` markers. Markers are stripped from the submitted
    sentence text, so they must never act as grammatical parts of a sentence.
    """
    errors: list[str] = []
    if not text or not text.strip():
        return None, ["response is empty"]
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("```"):
        return None, [
            "the final report must be plain prose lines with [docid] "
            "citation markers, not JSON or a fenced block"
        ]

    sentences: list[dict[str, Any]] = []
    any_citation = False
    for number, raw_line in enumerate(stripped.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        if _MARKDOWN_LINE_RE.match(line) or "**" in line:
            errors.append(
                f"line {number} uses Markdown syntax; write plain prose "
                "sentences without headings, list markers, bold, or fences")
            continue
        citations: list[str] = []
        for match in _CITATION_MARKER_RE.finditer(line):
            for token in _CITATION_TOKEN_SPLIT_RE.split(match.group(1)):
                if token and token not in citations:
                    citations.append(token)
        sentence = _CITATION_MARKER_RE.sub(" ", line)
        sentence = re.sub(r"\s+", " ", sentence).strip()
        sentence = re.sub(r"\s+([.,;:!?])", r"\1", sentence)
        if not sentence:
            errors.append(
                f"line {number} contains citation markers but no sentence "
                "text")
            continue
        if len(citations) > 3:
            errors.append(
                f"line {number} cites {len(citations)} docids; max 3")
        unknown = [
            docid for docid in citations if docid not in committed_docids]
        if unknown:
            errors.append(
                f"line {number} cites uncommitted docids: "
                + ", ".join(unknown))
        if citations:
            any_citation = True
        sentences.append({"text": sentence, "citations": citations})

    if not sentences:
        return None, errors + ["the report contains no sentences"]
    if committed_docids and not any_citation:
        errors.append(
            "no sentence carries a citation; support factual sentences with "
            "committed docids in [docid] markers")
    if _word_count(sentences) > 1024:
        errors.append(
            f"report is {_word_count(sentences)} words; maximum is 1024")
    if errors:
        return None, errors
    return sentences, []


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


# -- harness -------------------------------------------------------------------

def _usage_token_stats(usage: dict[str, Any]) -> dict[str, int]:
    """Normalize direct, cached, logical, and processed token usage."""
    uncached_input = int(
        usage.get("inputTokens", usage.get("input_tokens", 0)) or 0)
    output = int(
        usage.get("outputTokens", usage.get("output_tokens", 0)) or 0)
    cache_read = int(
        usage.get(
            "cacheReadInputTokens",
            usage.get("cache_read_input_tokens", 0),
        ) or 0)
    cache_write = int(
        usage.get(
            "cacheWriteInputTokens",
            usage.get("cache_write_input_tokens", 0),
        ) or 0)
    logical_input = uncached_input + cache_read + cache_write
    processed_input = uncached_input + cache_write
    return {
        "input": logical_input,
        "input_uncached": uncached_input,
        "output": output,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "total": logical_input + output,
        "processed_input": processed_input,
        "processed": processed_input + output,
    }


def _usage_tokens(usage: dict[str, Any]) -> tuple[int, int]:
    stats = _usage_token_stats(usage)
    return stats["input"], stats["output"]


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _budget_status_line(context_tokens: int, context_budget_tokens: int,
                        elapsed_ms: int) -> str:
    percent = (
        context_tokens / context_budget_tokens * 100
        if context_budget_tokens > 0 else 0.0
    )
    total_seconds = elapsed_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return (
        f"[context budget: {context_tokens:,} / "
        f"{context_budget_tokens:,} tokens ({percent:.1f}%) · "
        f"elapsed: {minutes}m {seconds}s]"
    )


def _with_budget_status(content: str, *, context_tokens: int,
                        context_budget_tokens: int,
                        elapsed_ms: int) -> str:
    return (
        content.rstrip()
        + "\n"
        + _budget_status_line(
            context_tokens, context_budget_tokens, elapsed_ms)
    )


def _action_stats(duration_ms: float, *, context_tokens: int,
                  context_budget_tokens: int,
                  elapsed_ms: int,
                  peak_context_tokens: int) -> dict[str, Any]:
    return {
        "duration_ms": duration_ms,
        "context_tokens": context_tokens,
        "peak_context_tokens": peak_context_tokens,
        "context_budget_tokens": context_budget_tokens,
        "elapsed_ms": elapsed_ms,
    }


def _turn_stats(usage: dict[str, Any], duration_ms: float,
                context_tokens: int, *,
                context_budget_tokens: int,
                elapsed_ms: int,
                peak_context_tokens: int) -> dict[str, Any]:
    token_stats = _usage_token_stats(usage)
    token_stats["context"] = token_stats["input"]
    return {
        "duration_ms": duration_ms,
        "context_tokens": context_tokens,
        "peak_context_tokens": peak_context_tokens,
        "context_budget_tokens": context_budget_tokens,
        "elapsed_ms": elapsed_ms,
        "tokens": token_stats,
        "provider_usage": usage,
    }


def _context_snapshot(ledger: ContextLedger) -> dict[str, Any]:
    return {
        "staged": ledger.staged_docids,
        "committed": sorted(ledger.committed_docids),
        "rejected": [],
    }


def _record_turn(tb: TrajectoryBuilder, turn: dict[str, Any], *,
                 narration_as_reasoning: bool = False,
                 model_input: dict[str, Any] | None = None,
                 t_start: str | None = None, t_end: str | None = None,
                 turn_index: int | None = None,
                 stats: dict[str, Any] | None = None,
                 context: dict[str, Any] | None = None) -> str:
    """Record one rich model span plus any strict textual reasoning.

    The model span is unconditional because providers may return signature-only
    reasoning. It fills the timeline between prior tool results and the actions
    produced by this turn.
    """
    visible_reasoning: list[str] = []
    for block in turn["blocks"]:
        if block["type"] == "reasoning":
            if not block["text"]:
                continue
            visible_reasoning.append(block["text"])
            tb.add_reasoning(
                block["text"], t_start=t_start, t_end=t_end, turn=turn_index,
                stats=stats, context=context, record_trace=False)
        elif (block["type"] == "text" and narration_as_reasoning
              and turn["tool_calls"]):
            visible_reasoning.append(block["text"])
            tb.add_reasoning(
                block["text"], t_start=t_start, t_end=t_end, turn=turn_index,
                stats=stats, context=context, record_trace=False)

    return tb.add_model_step(
        input=model_input,
        output={
            "text": turn.get("text"),
            "reasoning": visible_reasoning,
            "tool_calls": turn.get("tool_calls") or [],
            "stop_reason": turn.get("stop_reason"),
        },
        t_start=t_start, t_end=t_end, turn=turn_index,
        stats=stats, context=context)


def run_agent(query_id: str, query: str, *, backend: str = "bedrock",
              model: str | None = None, k: int = 10,
              context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
              safety_max_rounds: int = DEFAULT_SAFETY_MAX_ROUNDS,
              max_committed_per_step: int = DEFAULT_MAX_COMMITTED_PER_STEP,
              run_id: str = "aus-agent-dev",
              run_desc: str | None = None) -> dict[str, Any]:
    """Run one topic end-to-end; saves trajectory + output, returns paths."""
    if context_token_budget <= 0:
        raise ValueError("context_token_budget must be positive")
    provider = make_provider(backend, model)
    tb = TrajectoryBuilder(query_id, query, metadata={
        "model": provider.model_id,
        "backend": backend,
        "k": k,
        "temperature": None,  # sampling params not sent (removed on 4.6+)
        "run_id": run_id,
    })
    seen_docids: set[str] = set()
    ledger = ContextLedger()
    status = "completed"
    stop_reason: str | None = None
    sentences: list[dict[str, Any]] | None = None
    context_tokens = 0
    peak_context_tokens = 0

    run_started = now_iso()
    run_started_perf = perf_counter()
    turn_idx = -1  # 0-based model-turn index; bumped on every provider call
    # Wall-clock bounds + turn index of the last model turn; a successful
    # no-tool final-report turn's bounds end up on the output_text item.
    last_turn: tuple[
        str | None, str | None, int | None, float, dict[str, Any]
    ] = (None, None, None, 0.0, {})

    def timed_turn() -> dict[str, Any]:
        """Run one model turn, tracking wall-clock bounds and turn index."""
        nonlocal turn_idx, last_turn, context_tokens, peak_context_tokens
        turn_idx += 1
        t0 = now_iso()
        started = perf_counter()
        turn = provider.run_turn()
        duration_ms = round((perf_counter() - started) * 1000, 3)
        input_tokens, _ = _usage_tokens(turn.get("usage") or {})
        if input_tokens is not None:
            context_tokens = input_tokens
            peak_context_tokens = max(peak_context_tokens, context_tokens)
        last_turn = (t0, now_iso(), turn_idx, duration_ms,
                     _turn_stats(turn.get("usage") or {}, duration_ms,
                                 context_tokens,
                                 context_budget_tokens=context_token_budget,
                                 elapsed_ms=_elapsed_ms(run_started_perf),
                                 peak_context_tokens=peak_context_tokens))
        return turn

    def action_feedback(content: str, duration_ms: float) -> tuple[
            str, dict[str, Any]]:
        elapsed_ms = _elapsed_ms(run_started_perf)
        return (
            _with_budget_status(
                content,
                context_tokens=context_tokens,
                context_budget_tokens=context_token_budget,
                elapsed_ms=elapsed_ms,
            ),
            _action_stats(
                duration_ms,
                context_tokens=context_tokens,
                context_budget_tokens=context_token_budget,
                elapsed_ms=elapsed_ms,
                peak_context_tokens=peak_context_tokens,
            ),
        )

    def expire_staged_context(reason: str, turn: int | None) -> str:
        """Compact an unresolved batch rather than carrying it another turn."""
        ct0 = now_iso()
        started = perf_counter()
        decision = expire_staged(
            ledger,
            max_documents=max_committed_per_step,
            reason=reason,
        )
        provider.compact_tool_results(decision.replacements)
        payload = json.dumps({
            "automatic": True,
            "error": reason,
            "committed": [],
            "rejected": decision.rejected,
        }, ensure_ascii=False)
        duration_ms = round((perf_counter() - started) * 1000, 3)
        output, feedback_stats = action_feedback(payload, duration_ms)
        tb.add_tool_call(
            "commit_context",
            {"documents": [], "automatic": True},
            output,
            failed=True,
            t_start=ct0,
            t_end=now_iso(),
            turn=turn,
            stats=feedback_stats,
            context=decision.context,
            documents=[],
        )
        return output

    try:
        system_prompt = load_system_prompt(max_committed_per_step)
        tool_definitions = [
            SEARCH_TOOL_DEF,
            COMMIT_CONTEXT_TOOL,
        ]
        user_message = TASK_PROMPT.format(query=query)
        tb.set_trace_input({
            "system_prompt": system_prompt,
            "user_message": user_message,
            "tools": tool_definitions,
        })
        provider.start(system_prompt, tool_definitions)
        provider.add_user_message(user_message)
        next_model_input: dict[str, Any] = {
            "kind": "initial",
            "ref": "trace.input",
        }

        # One continuous agent loop: research actions and the eventual cited
        # prose report are turns in the same provider conversation.
        rounds = 0
        finishing = False
        while True:
            rounds += 1
            turn = timed_turn()
            t0, t1, ti, _, model_stats = last_turn
            generation_id = _record_turn(
                tb,
                turn,
                narration_as_reasoning=True,
                model_input=next_model_input,
                t_start=t0,
                t_end=t1,
                turn_index=ti,
                stats=model_stats,
                context=_context_snapshot(ledger),
            )
            calls = turn["tool_calls"]
            commit_calls = [
                call for call in calls if call["name"] == "commit_context"]

            # A staged batch exists for exactly this turn. Missing, repeated,
            # or non-first commit_context means the batch expires now: compact
            # all occurrences and do not execute the turn's other actions.
            valid_commit_position = (
                len(commit_calls) == 1
                and calls
                and calls[0]["name"] == "commit_context"
            )
            if ledger.has_staged and not valid_commit_position:
                expire_staged_context(
                    "staged batch expired because commit_context was not "
                    "exactly the first action on the immediately following "
                    "model turn",
                    ti,
                )
                if not calls:
                    # The turn may itself be a valid final report. Staged
                    # (uncommitted) evidence can never be cited, so accepting
                    # it after the expiry loses nothing and saves a turn.
                    candidate, _ = _parse_final_prose(
                        turn.get("text"), set(ledger.committed_docids))
                    if candidate is not None:
                        sentences = candidate
                        break
                    if rounds >= safety_max_rounds:
                        raise RuntimeError(
                            "runaway-loop safety backstop reached after a "
                            "staged batch expired without a valid final "
                            "report")
                    feedback = (
                        "The staged batch expired and every unselected "
                        "occurrence was compacted. Continue in the same "
                        "workflow: search again if evidence is still needed, "
                        "or write the final report using only previously "
                        "committed evidence.\n"
                        + _budget_status_line(
                            context_tokens,
                            context_token_budget,
                            _elapsed_ms(run_started_perf))
                    )
                    provider.add_user_message(feedback)
                    next_model_input = {
                        "kind": "user_message",
                        "text": feedback,
                    }
                    continue
                if rounds >= safety_max_rounds:
                    raise RuntimeError(
                        "runaway-loop safety backstop reached while refusing "
                        "actions after a staged batch expired")
                msg, feedback_stats = action_feedback(json.dumps({
                    "error": "actions refused because the staged batch "
                             "expired before a valid first commit_context"
                }), 0)
                results = []
                ts = now_iso()
                for call in calls:
                    tb.add_tool_call(
                        call["name"], call["arguments"], msg, failed=True,
                        t_start=ts, t_end=ts, turn=ti,
                        stats=feedback_stats,
                        context=_context_snapshot(ledger),
                        documents=[],
                        tool_call_id=call["id"],
                    )
                    results.append({
                        "id": call["id"], "content": msg, "is_error": True})
                provider.add_tool_results(results)
                next_model_input = {
                    "kind": "tool_results",
                    "tool_call_ids": [call["id"] for call in calls],
                }
                continue

            if not ledger.has_staged and commit_calls:
                if rounds >= safety_max_rounds:
                    raise RuntimeError(
                        "runaway-loop safety backstop reached while "
                        "commit_context was called with no staged context")
                msg, feedback_stats = action_feedback(json.dumps({
                    "error": "there is no staged context to commit"
                }), 0)
                results = []
                ts = now_iso()
                for call in calls:
                    content = (
                        msg if call["name"] == "commit_context"
                        else action_feedback(json.dumps({
                            "error": "retry without commit_context because "
                                     "there is no staged context"
                        }), 0)[0]
                    )
                    tb.add_tool_call(
                        call["name"], call["arguments"], content, failed=True,
                        t_start=ts, t_end=ts, turn=ti,
                        stats=feedback_stats,
                        context=_context_snapshot(ledger),
                        documents=[],
                        tool_call_id=call["id"],
                    )
                    results.append({
                        "id": call["id"], "content": content, "is_error": True})
                provider.add_tool_results(results)
                next_model_input = {
                    "kind": "tool_results",
                    "tool_call_ids": [call["id"] for call in calls],
                }
                continue

            budget_hit = (
                context_tokens >= context_token_budget)
            safety_hit = rounds >= safety_max_rounds
            if (budget_hit or safety_hit) and not finishing:
                status = "budget_exhausted"
                stop_reason = (
                    "safety_max_rounds"
                    if safety_hit else "generation_context_tokens")
                finishing = True
                generation_step = next(
                    step for step in tb.trace_steps
                    if step["id"] == generation_id)
                generation_step.setdefault("stats", {})[
                    "context_budget_exhausted"] = budget_hit

            if not calls:
                candidate, validation_errors = _parse_final_prose(
                    turn.get("text"), set(ledger.committed_docids))
                if candidate is not None:
                    sentences = candidate
                    break
                if rounds >= safety_max_rounds:
                    raise RuntimeError(
                        "runaway-loop safety backstop reached while correcting "
                        "the final report: " + "; ".join(validation_errors))
                feedback = (
                    "Your attempted final response did not satisfy the final-"
                    "report contract already defined in the system "
                    "instructions.\nProblems:\n- "
                    + "\n- ".join(validation_errors)
                    + "\nCorrect it in the next turn in this same conversation. "
                      "Emit tool calls only if more evidence is genuinely "
                      "needed; otherwise write only the corrected report: "
                      "plain prose, one sentence per line, with [docid] "
                      "citation markers."
                    + "\n"
                    + _budget_status_line(
                        context_tokens,
                        context_token_budget,
                        _elapsed_ms(run_started_perf))
                )
                provider.add_user_message(feedback)
                next_model_input = {
                    "kind": "user_message",
                    "text": feedback,
                }
                continue

            result_by_id: dict[str, dict[str, Any]] = {}

            # Resolve the previous staged batch first, even when the budget was
            # reached on this turn. Compaction is bookkeeping, not retrieval,
            # and gives the next same-loop turn a clean context.
            if commit_calls:
                call = commit_calls[0]
                ct0 = now_iso()
                started = perf_counter()
                pending_before = list(ledger.pending)
                committed_before = set(ledger.committed_docids)
                rejected_before = set(ledger.rejected_docids)
                try:
                    handled = apply_commit(
                        ledger,
                        call["arguments"],
                        max_documents=max_committed_per_step,
                        finishing=finishing,
                    )
                    decision = handled.decision
                except Exception as e:
                    # An invalid selection consumes its one decision turn. The
                    # batch is compacted now rather than carried forward for a
                    # retry.
                    ledger.pending = pending_before
                    ledger.committed_docids = committed_before
                    ledger.rejected_docids = rejected_before
                    decision = expire_staged(
                        ledger,
                        max_documents=max_committed_per_step,
                        reason=(
                            "staged batch expired after invalid "
                            f"commit_context: {type(e).__name__}: {e}"
                        ),
                    )
                    provider.compact_tool_results(decision.replacements)
                    commit_payload = {
                        "error": f"{type(e).__name__}: {e}",
                        "committed": [],
                        "rejected": decision.rejected,
                        "instruction": (
                            "The staged batch was compacted and cannot be "
                            "reselected; search again if the evidence is still "
                            "needed."
                        ),
                    }
                    out = json.dumps(commit_payload, ensure_ascii=False)
                    failed = True
                    context = decision.context
                    documents = []
                else:
                    try:
                        provider.compact_tool_results(decision.replacements)
                    except Exception:
                        # Provider-history compaction is atomic with the ledger
                        # update. A backend failure ends the run rather than
                        # carrying inconsistent context into another turn.
                        ledger.pending = pending_before
                        ledger.committed_docids = committed_before
                        ledger.rejected_docids = rejected_before
                        raise
                    out = json.dumps(handled.payload, ensure_ascii=False)
                    failed = False
                    context = decision.context
                    documents = decision.documents
                ct1 = now_iso()
                duration_ms = round(
                    (perf_counter() - started) * 1000, 3)
                out, feedback_stats = action_feedback(out, duration_ms)
                tb.add_tool_call(
                    call["name"], call["arguments"], out, failed=failed,
                    t_start=ct0, t_end=ct1, turn=ti,
                    stats=feedback_stats,
                    context=context, documents=[],
                    tool_call_id=call["id"],
                )
                result_by_id[call["id"]] = {
                    "id": call["id"], "content": out, "is_error": failed}
                if failed:
                    # The invalid batch has already expired; refuse remaining
                    # same-turn actions so the next turn starts cleanly.
                    ts = now_iso()
                    for other in calls:
                        if other["id"] == call["id"]:
                            continue
                        blocked, blocked_stats = action_feedback(json.dumps({
                            "error": "commit_context failed and the staged "
                                     "batch expired; same-turn actions refused"
                        }), 0)
                        tb.add_tool_call(
                            other["name"], other["arguments"], blocked,
                            failed=True, t_start=ts, t_end=ts, turn=ti,
                            stats=blocked_stats,
                            context=_context_snapshot(ledger), documents=[],
                            tool_call_id=other["id"],
                        )
                        result_by_id[other["id"]] = {
                            "id": other["id"], "content": blocked,
                            "is_error": True,
                        }
                    provider.add_tool_results(
                        [result_by_id[c["id"]] for c in calls])
                    next_model_input = {
                        "kind": "tool_results",
                        "tool_call_ids": [call["id"] for call in calls],
                    }
                    continue

            retrieval_calls = [
                call for call in calls if call["name"] == "search"]
            if retrieval_calls and (budget_hit or safety_hit):
                budget_msg, budget_stats = action_feedback(json.dumps({
                    "error": (
                        "tool call not executed because the preceding "
                        "generation input context reached the research budget; "
                        "write the final report now using the contract "
                        "already defined in the system prompt"
                    ),
                    "context_tokens": context_tokens,
                    "peak_context_tokens": peak_context_tokens,
                    "context_token_budget": context_token_budget,
                }), 0)
                ts = now_iso()
                for call in retrieval_calls:
                    tb.add_tool_call(
                        call["name"], call["arguments"], budget_msg,
                        failed=True, t_start=ts, t_end=ts, turn=ti,
                        stats=budget_stats,
                        context=_context_snapshot(ledger), documents=[],
                        tool_call_id=call["id"],
                    )
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": budget_msg,
                        "is_error": True,
                    }
            elif retrieval_calls:
                # Calls from one model turn execute concurrently. The builder
                # records their real overlapping bounds for the viewer.
                executed = _execute_tool_calls(
                    retrieval_calls, k=k, seen_docids=seen_docids)
                for call, (
                    out, trace_output, returned, failed, documents,
                    ct0, ct1, duration_ms
                ) in zip(retrieval_calls, executed):
                    out, feedback_stats = action_feedback(out, duration_ms)
                    context = {
                        "staged": [
                            str(document["docid"]) for document in documents],
                        "committed": [],
                        "rejected": [],
                    }
                    tb.add_tool_call(
                        call["name"], call["arguments"], out,
                        returned=returned, failed=failed,
                        t_start=ct0, t_end=ct1, turn=ti,
                        stats=feedback_stats,
                        documents=[], context=context,
                        trace_output=trace_output,
                        tool_call_id=call["id"],
                    )
                    if not failed:
                        ledger.stage(
                            call["id"], call["name"], out, documents)
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": out,
                        "is_error": failed,
                    }

            provider.add_tool_results(
                [result_by_id[call["id"]] for call in calls])
            next_model_input = {
                "kind": "tool_results",
                "tool_call_ids": [call["id"] for call in calls],
            }

    except Exception as e:
        status = "failed"
        if not sentences:
            sentences = [{"text": f"Run failed: {type(e).__name__}: {e}",
                          "citations": []}]

    eligible_docids = set(ledger.committed_docids)
    references, answer = _map_citations(sentences, eligible_docids)
    answer_text = " ".join(s["text"] for s in answer)
    tb.set_trace_output({
        "references": references,
        "answer": answer,
    })
    tb.add_output_text(
        answer_text, t_start=last_turn[0], t_end=last_turn[1],
        turn=last_turn[2], stats=last_turn[4],
        context=_context_snapshot(ledger), record_trace=False)

    output = build_rag_output(
        narrative_id=query_id,
        narrative=query,
        run_id=run_id,
        run_desc=run_desc or (
            f"aus_agent research harness ({backend}/{provider.model_id}): "
            f"continuous single-agent full-text search with sparse committed "
            f"context and line-per-sentence cited prose answers parsed into "
            f"the organizer schema."),
        references=references,
        answer=answer,
    )
    trajectory = tb.finalize(status=status, raw_messages=provider.raw_messages,
                             started_at=run_started, ended_at=now_iso())
    trajectory.trace["summary"].setdefault("tokens", {}).update({
        "context_tokens": context_tokens,
        "peak_context_tokens": peak_context_tokens,
        "context_budget_tokens": context_token_budget,
        "budget": context_token_budget,
    })
    trajectory.trace["config"] = {
        "context_token_budget": context_token_budget,
        "safety_max_rounds": safety_max_rounds,
        "max_committed_per_step": max_committed_per_step,
    }
    trajectory.trace["summary"]["context"] = {
        "committed": sorted(ledger.committed_docids),
        "rejected": sorted(ledger.rejected_docids),
    }
    if stop_reason is not None:
        trajectory.trace["summary"]["stop_reason"] = stop_reason
    paths = save_run("aus_agent", query, trajectory=trajectory, output=output)
    return {"status": status, "paths": paths,
            "tool_call_counts": trajectory["tool_call_counts"],
            "n_references": len(references), "n_sentences": len(answer),
            "words": _word_count(answer),
            "context_tokens": context_tokens,
            "peak_context_tokens": peak_context_tokens,
            "processed_tokens": (
                trajectory.trace["summary"]["tokens"].get("processed", 0)),
            "committed_documents": len(ledger.committed_docids),
            "rejected_documents": len(ledger.rejected_docids)}
