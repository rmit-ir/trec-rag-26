"""agent_harness — shared staged-context, tool-calling research-agent loop.

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

``run_agent`` is a shared harness, not aus_agent's private implementation:
``system_name``, ``system_prompt``, ``engines``, ``default_k_by_engine``,
``commit_context_tool``, and ``search_tool_def`` are all caller-overridable so
a sibling system (e.g. ``facets_agent``) can drive the exact same loop with its
own prompt and tool schemas. ``system_prompt`` is REQUIRED here: callers with
their own prompt-variant scheme (like aus_agent's ``prompts/system/*.md``)
resolve it themselves before calling in, rather than this module reaching back
into any one caller's file layout.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from ragrun import (
    TrajectoryBuilder,
    build_rag_output,
    now_iso,
    run_timestamp,
    save_run,
)
from .context import ContextLedger
from .providers.base import Provider
from .tools import (
    COMMIT_CONTEXT_TOOL,
    GET_DOCUMENTS_TOOL,
    apply_commit,
    build_search_tool_def,
    execute_full_text_search,
    execute_get_documents,
    execute_judge_relevance,
    expire_staged,
)

# Dense + sparse, both enabled by default; the model must name one per call.
DEFAULT_ENGINES = ["semantic", "keyword"]

DEFAULT_CONTEXT_TOKEN_BUDGET = 500_000
# A run rewrites its output.json as it goes so the outputs viewer can follow it
# live. The trace grows to ~1 MB, so an unthrottled rewrite on every step would
# burn real I/O for no visible benefit — nobody reads a viewer faster than this.
PARTIAL_SAVE_MIN_INTERVAL_S = 2.0
DEFAULT_SAFETY_MAX_ROUNDS = 100
# Rounds allowed after safety_max_rounds flips `finishing`. Reaching
# safety_max_rounds is a graceful "wrap up now" — retrieval is refused and the
# model still needs a few rounds to write the report and correct it. This grace
# bounds that tail; past it the loop is not making progress and must stop.
FINISHING_ROUNDS_GRACE = 10
DEFAULT_MAX_COMMITTED_PER_STEP = 10
DEFAULT_PROMPT_VARIANT = "default"

# The current time goes in the user message, NOT the system prompt. Bedrock
# chains tools -> system -> messages, and the static cachePoint sits at the end
# of system, so every topic in a batch shares those bytes: 29 of 30 topics in
# the last dev batch read that prefix from cache instead of writing it. A
# timestamp in system.md would make the prefix unique per run and turn every one
# of those reads into a write. Here it is free — this message is already unique
# per run and falls after the breakpoint.
TASK_PROMPT = """\
Current date and time: {now}

Research request:

{query}
"""


log = logging.getLogger(__name__)


def now_full(now: datetime | None = None) -> str:
    """The wall clock, spelled out unambiguously for the model, in UTC.

    Weekday and month name so nothing hinges on reading a numeric date in the
    right order. UTC makes "today" and recency judgments well defined without
    leaking either the host's IANA zone or its local offset into every request.
    """
    now = now or datetime.now(timezone.utc)
    return f"{now.astimezone(timezone.utc):%A, %d %B %Y, %H:%M:%S} UTC"


def make_provider(backend: str, model: str | None,
                  region: str | None = None) -> Provider:
    if backend == "bedrock":
        from .providers.bedrock import BedrockProvider
        return BedrockProvider(model, region=region)
    if backend == "openai":
        from .providers.openai import OpenAIProvider
        return OpenAIProvider(model)
    raise ValueError(
        f"unknown backend: {backend!r} (available: bedrock, openai)")


@dataclass
class SearchResultPass:
    """One caller-supplied reduction/reordering of a search call's results,
    returned by ``search_result_filter`` (PLAN.md Phase 4c, in
    ``src/systems/facets_agent/PLAN.md``). ``documents`` should be a
    (possibly reordered, possibly reduced) selection of the ORIGINAL
    documents the filter was given, each optionally carrying a
    ``judge_verdict`` annotation -- the harness only trusts an entry's
    ``id`` and that one field; everything else (text, metadata) is always
    re-read from the true original, so a filter cannot fabricate,
    duplicate, or mutate content into a run (see
    ``_apply_search_result_filter``)."""
    documents: list[dict[str, Any]]
    note: str | None = None


def _apply_search_result_filter(
        search_result_filter: (
            Callable[[str, list[dict[str, Any]]], SearchResultPass] | None),
        requirement: str, out: str, documents: list[dict[str, Any]],
        ) -> tuple[str, list[dict[str, Any]]]:
    """Run ``search_result_filter`` (if given) and rebuild BOTH the
    tool-result text (``out``, what the model reads) and the staged
    ``documents`` list (what the ledger tracks) so they never desync --
    the one place both are rewritten together. Fails open (returns the
    untouched originals) on any exception, so a broken filter can never
    starve a facet of evidence."""
    if search_result_filter is None or not documents:
        return out, documents
    try:
        original_by_id = {str(d["id"]): d for d in documents}
        pass_ = search_result_filter(requirement, documents)
        validated: list[dict[str, Any]] = []
        seen: set[str] = set()
        for doc in pass_.documents:
            uid = str(doc.get("id", ""))
            if uid in original_by_id and uid not in seen:
                seen.add(uid)
                merged = dict(original_by_id[uid])
                if "judge_verdict" in doc:
                    merged["judge_verdict"] = doc["judge_verdict"]
                validated.append(merged)
        data = json.loads(out)
        results_by_id = {
            str(r.get("id", r.get("docid"))): r
            for r in data.get("results", [])}
        new_results = []
        for doc in validated:
            base = results_by_id.get(str(doc["id"]))
            if base is None:
                continue
            result = dict(base)
            if "judge_verdict" in doc:
                result["judge_verdict"] = doc["judge_verdict"]
            new_results.append(result)
        data["results"] = new_results
        dropped = len(documents) - len(validated)
        if dropped:
            data["filtered_count"] = dropped
        if pass_.note:
            data["filter_note"] = pass_.note
        return json.dumps(data, ensure_ascii=False), validated
    except Exception:
        return out, documents


def _truncate_snippet(text: str, max_chars: int) -> tuple[str, bool]:
    """piika-style preview (``pyserini_rest/adapter.ts::truncateSnippet``,
    verified against its source 2026-08-06): collapse ALL whitespace
    (including newlines) to single spaces first, so a preview budget is
    never wasted on line breaks the original chunk text happens to carry.
    Improves on piika's own version in one way (per user request): never
    cuts mid-word -- backs up to the last space before the limit, or hard-
    cuts only if the very first ``max_chars`` characters contain no space
    at all (a pathological single long token)."""
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact, False
    cut = compact.rfind(" ", 0, max_chars)
    if cut <= 0:
        cut = max_chars
    return compact[:cut].rstrip() + "...", True


def _apply_search_preview(
        out: str, documents: list[dict[str, Any]],
        preview_chars: int | None, *, requirement: str = "",
        preview_generator: (
            Callable[[str, list[dict[str, Any]]], dict[str, str]]
            | None) = None) -> tuple[str, list[dict[str, Any]]]:
    """Shrink every result's ``text`` to a preview (PLAN.md Phase 4d,
    piika-inspired two-tier retrieval, in
    ``src/systems/facets_agent/PLAN.md``): a short, cheap preview shown at
    search time, with ``get_documents`` (already unpaginated full-text,
    already staged) as the deliberate, explicit action for reading
    something in full. ``None`` for both ``preview_chars`` and
    ``preview_generator`` is a no-op (today's exact behavior).

    ``preview_generator`` (PLAN.md Phase 4d follow-on) — when given — is
    called ONCE per search batch with ``(requirement, documents)`` and
    should return ``{id: snippet}`` (e.g.
    ``tools.generate_snippets``, an LLM-generated query-relevant span
    instead of the document's own opening text). Any id it doesn't cover
    (a partial/failed generation) falls back to positional truncation
    (``_truncate_snippet``) so a preview is never simply missing. Every
    generated snippet is ALSO hard-capped to ``preview_chars`` here — never
    trusts the generator's own length discipline. Fails open (returns the
    untouched originals) on any exception, same discipline as
    ``_apply_search_result_filter``."""
    if preview_chars is None and preview_generator is None:
        return out, documents
    try:
        generated: dict[str, str] = {}
        if preview_generator is not None:
            try:
                generated = preview_generator(requirement, documents) or {}
            except Exception:  # noqa: BLE001
                generated = {}

        def preview_for(uid: str, text: str) -> tuple[str, bool]:
            snippet = generated.get(uid)
            if snippet:
                if preview_chars is not None and len(snippet) > preview_chars:
                    return _truncate_snippet(snippet, preview_chars)
                return snippet, True
            if preview_chars is None:
                return text, False
            return _truncate_snippet(text, preview_chars)

        data = json.loads(out)
        for result in data.get("results", []):
            text = result.get("text")
            uid = str(result.get("id", ""))
            if isinstance(text, str):
                snippet, truncated = preview_for(uid, text)
                result["text"] = snippet
                if truncated:
                    result["preview_truncated"] = True
                    if uid in generated:
                        result["preview_generated"] = True
        new_documents = []
        for d in documents:
            text = d.get("text")
            uid = str(d.get("id", ""))
            if isinstance(text, str):
                snippet, _truncated = preview_for(uid, text)
                d = {**d, "text": snippet}
            new_documents.append(d)
        return json.dumps(data, ensure_ascii=False), new_documents
    except Exception:
        return out, documents


def _execute_tool_calls(calls: list[dict[str, Any]], *, k: int,
                        seen_docids: set[str],
                        engines: list[str] | None = None,
                        default_k_by_engine: dict[str, int] | None = None,
                        ) -> list[tuple]:
    """Execute one model turn's tool calls IN PARALLEL (threads; the tools are
    I/O-bound and thread-safe). Returns, in the model's tool_use order, one
    ``(output, trace_output, returned, failed, documents, t_start, t_end,
    duration_ms)``
    tuple per call — each
    call carries its own real wall-clock bounds. ``engines`` is the run's
    enabled set, named back to the model when a call omits the required
    ``search_engine``. ``default_k_by_engine`` overrides ``k`` for a named
    engine when the model's call omits ``k`` (e.g. a HyDE-style hybrid query
    benefits from a wider net than a short keyword query)."""
    def timed(call: dict[str, Any]) -> tuple:
        t0 = now_iso()
        started = perf_counter()
        engine = call["arguments"].get("search_engine")
        eff_default_k = (default_k_by_engine or {}).get(engine, k)
        execution = execute_full_text_search(
            call["arguments"], default_k=eff_default_k, seen_docids=seen_docids,
            engines=engines)
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
# A marker holds docid-shaped tokens only (word chars, dots, dashes). Bracketed
# anything-else stays in the sentence: gpt-5.6-terra wrote the DPO derivation
# as "β log[π_r(y|x)/π_ref(y|x)]" and the old any-content pattern stripped the
# ratio out of the mathematics as if it were a citation.
_CITATION_MARKER_RE = re.compile(r"\[([\w.-]+(?:[,;\s]+[\w.-]+)*)\]")
_CITATION_TOKEN_SPLIT_RE = re.compile(r"[,;\s]+")
# Markdown the model may reach for despite the contract. Headings and fences
# carry no citable claim and are dropped; the rest is unwrapped in place.
_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_LIST_MARKER_RE = re.compile(r"^([-*+]|\d{1,3}[.)])\s+")
_QUOTE_RE = re.compile(r"^>\s+")
_EMPHASIS_RE = re.compile(r"\*{1,3}([^*]+)\*{1,3}|__([^_]+)__|`([^`]+)`")
MAX_REPORT_WORDS = 1024
TARGET_REPORT_WORDS = 950
# An uncited report is bounced so the model goes and gets evidence, but the
# search backend may genuinely have nothing to offer. After this many refusals
# an honest evidence-gap answer beats looping to the safety backstop and
# failing the run outright.
MAX_UNCITED_REFUSALS = 2
_UNCITED_ERRORS = (
    "no sentence carries a citation",
    "no evidence has been committed",
)


def _strip_markers(line: str) -> str:
    """Remove citation markers and tidy the whitespace they leave behind."""
    text = _CITATION_MARKER_RE.sub(" ", line)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def _extract_citations(line: str) -> list[str]:
    citations: list[str] = []
    for match in _CITATION_MARKER_RE.finditer(line):
        for token in _CITATION_TOKEN_SPLIT_RE.split(match.group(1)):
            if token and token not in citations:
                citations.append(token)
    return citations


def _parse_final_prose(
    text: str | None,
    committed_ids: set[str],
    *,
    allow_uncited: bool = False,
) -> tuple[list[dict[str, Any]] | None, list[str], list[str]]:
    """Parse the attempted final report into cited sentences.

    The contract is prose, one sentence per line, citing committed docids with
    inline ``[docid]`` markers. The parser repairs anything whose intent is
    unambiguous and only rejects what it cannot resolve on the model's behalf,
    because every rejection costs a full correction turn at full context size.

    Repaired (recorded in the returned notes, never bounced back):
      * a citation-only line — the model routinely puts a sentence's markers on
        the line below it, so they fold into the preceding sentence;
      * Markdown — fences and headings are dropped (no citable claim), list and
        quote markers and emphasis are unwrapped in place;
      * more than three citations on a sentence — the extras are dropped; and
      * a docid that was never committed — that citation is dropped.

    Rejected (only what the model itself must resolve): an empty response, a
    report with no sentences, a report that cites nothing, and an over-length
    report — truncating that one would cut the conclusion, so the model
    re-prioritizes instead.

    An uncited report is refused even when *nothing* has been committed: with no
    evidence retained, every claim can only have come from prior knowledge,
    which the contract forbids. ``allow_uncited`` is the escape hatch for the
    cases where refusing again would be worse than accepting — an exhausted
    budget, or a corpus that genuinely has nothing to offer after the model has
    been sent back for evidence ``MAX_UNCITED_REFUSALS`` times. An honest
    evidence-gap answer beats looping to the safety backstop and failing.
    """
    repairs: list[str] = []
    if not text or not text.strip():
        return None, ["response is empty"], repairs

    sentences: list[dict[str, Any]] = []
    for number, raw_line in enumerate(text.strip().splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        if _FENCE_RE.match(line):
            repairs.append(f"line {number}: dropped a Markdown code fence")
            continue
        if _HEADING_RE.match(line):
            repairs.append(f"line {number}: dropped a Markdown heading")
            continue
        marker = _LIST_MARKER_RE.match(line) or _QUOTE_RE.match(line)
        if marker:
            line = line[marker.end():].strip()
            repairs.append(
                f"line {number}: unwrapped a Markdown list/quote marker")
        unemphasised = _EMPHASIS_RE.sub(
            lambda m: next(g for g in m.groups() if g is not None), line)
        if unemphasised != line:
            repairs.append(f"line {number}: unwrapped Markdown emphasis")
            line = unemphasised

        citations = _extract_citations(line)
        sentence = _strip_markers(line)
        if not sentence:
            if citations and sentences:
                previous = sentences[-1]["citations"]
                previous.extend(
                    docid for docid in citations if docid not in previous)
                repairs.append(
                    f"line {number}: folded a citation-only line into the "
                    "preceding sentence")
            else:
                repairs.append(
                    f"line {number}: dropped citation markers with no sentence")
            continue
        sentences.append({"text": sentence, "citations": citations})

    if not sentences:
        return None, ["the report contains no sentences"], repairs

    for index, sentence in enumerate(sentences, 1):
        unknown = [
            docid for docid in sentence["citations"]
            if docid not in committed_ids
        ]
        if unknown:
            sentence["citations"] = [
                docid for docid in sentence["citations"]
                if docid in committed_ids
            ]
            repairs.append(
                f"sentence {index}: dropped uncommitted docids "
                + ", ".join(unknown))
        if len(sentence["citations"]) > 3:
            repairs.append(
                f"sentence {index}: dropped citations beyond the first 3 "
                + ", ".join(sentence["citations"][3:]))
            sentence["citations"] = sentence["citations"][:3]

    errors: list[str] = []
    if not allow_uncited and not any(s["citations"] for s in sentences):
        if committed_ids:
            errors.append(
                "no sentence carries a citation; support factual sentences "
                "with committed docids in [docid] markers at the end of the "
                "sentence")
        else:
            errors.append(
                "no evidence has been committed, so every claim in this "
                "report would be unsupported prior knowledge; search for "
                "evidence and retain the supporting documents with "
                "commit_context before writing the final report")
    words = _word_count(sentences)
    if words > MAX_REPORT_WORDS:
        errors.append(
            f"report is {words} words; the hard maximum is {MAX_REPORT_WORDS}"
            f" — rewrite it at about {TARGET_REPORT_WORDS} words, cutting the "
            "least load-bearing material rather than trimming a few words")
    if errors:
        return None, errors, repairs
    return sentences, [], repairs


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


def _collapse_to_docs(references: list[str], answer: list[dict[str, Any]]
                      ) -> tuple[list[str], list[dict[str, Any]]]:
    """Collapse unit-id references (chunk ids) to parent docids for the
    organizer submission: pages of the same document dedup to one reference,
    and each sentence's citation indices are remapped onto the parent-doc
    reference list (deduped, capped at three). The internal/trace side keeps
    the chunk-native unit ids; this is the final-format transform only.
    """
    doc_refs: list[str] = []
    unit_to_doc: dict[int, int] = {}
    for i, uid in enumerate(references):
        docid = re.sub(r"_p\d+$", "", uid)  # strip the _p<page> chunk suffix
        if docid not in doc_refs:
            doc_refs.append(docid)
        unit_to_doc[i] = doc_refs.index(docid)
    doc_answer: list[dict[str, Any]] = []
    for sent in answer:
        idxs: list[int] = []
        for u_idx in sent["citations"]:
            d_idx = unit_to_doc.get(u_idx)
            if d_idx is not None and d_idx not in idxs:
                idxs.append(d_idx)
            if len(idxs) >= 3:
                break
        doc_answer.append({"text": sent["text"], "citations": idxs})
    return doc_refs, doc_answer


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
        "staged": ledger.staged_ids,
        "committed": sorted(ledger.committed_ids),
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
              run_desc: str | None = None,
              prompt_variant: str = DEFAULT_PROMPT_VARIANT,
              engines: list[str] | None = None,
              system_name: str = "aus_agent",
              system_prompt: str,
              default_k_by_engine: dict[str, int] | None = None,
              commit_context_tool: dict[str, Any] | None = None,
              search_tool_def: dict[str, Any] | None = None,
              pre_final_hook: (
                  Callable[[dict[str, Any]], str | None] | None) = None,
              judge_tool: dict[str, Any] | None = None,
              search_result_filter: (
                  Callable[[str, list[dict[str, Any]]], SearchResultPass]
                  | None) = None,
              search_preview_chars: int | None = None,
              search_preview_generator: (
                  Callable[[str, list[dict[str, Any]]], dict[str, str]]
                  | None) = None,
              stage_search_results: bool = True,
              ) -> dict[str, Any]:
    """Run one topic end-to-end; saves trajectory + output, returns paths.

    ``engines`` selects which retrieval backends the search tool exposes (e.g.
    ``["ssr"]`` to test SSR Boolean in isolation); defaults to the hybrid
    ``semantic`` + ``keyword`` pair.

    This is the shared staged-context harness: ``system_name`` picks the
    ``data/outputs/<system_name>/`` artifact directory (a sibling system reusing
    this loop, e.g. ``facets_agent``, passes its own name so the two never mix
    outputs). ``system_prompt`` is REQUIRED — every caller resolves its own
    system prompt (aus_agent's own ``prompts/system/<variant>.md`` files via
    ``aus_agent.agent.load_system_prompt``, or facets_agent's single-variant
    ``prompts.SYSTEM_PROMPT``) before calling in; this module has no file layout
    of its own to fall back to. ``prompt_variant`` is recorded on the trajectory
    as a plain provenance label only — it has no effect here.
    ``default_k_by_engine`` overrides the per-call result
    count for a named engine when the model's call omits ``k``.
    ``commit_context_tool`` — when given — is advertised to the model instead
    of this module's own ``COMMIT_CONTEXT_TOOL``; ``apply_commit`` already
    handles a ``release`` argument whenever the call carries one regardless of
    which tool definition advertised it, so a caller only needs to supply a
    schema that documents the field (e.g. one extending ``COMMIT_CONTEXT_TOOL``
    with a ``release`` property) to expose it. ``search_tool_def`` — when
    given — is advertised instead of this module's own
    ``build_search_tool_def(engines)``; unlike ``commit_context_tool`` the
    search definition is ENGINE-DEPENDENT (its ``search_engine`` enum and
    query guidance are derived from ``engines``, which this function also
    uses separately in the error path when a call omits ``search_engine``),
    so a caller must build its override from the same ``engines`` list this
    call was given — never pass a module-level constant built for a
    different engine set, or the advertised enum and the run's actual
    enabled engines will desync.
    ``pre_final_hook`` — when given — is called at most ONCE per run, the
    first time the model produces a valid final report (a candidate that
    already passed ``_parse_final_prose``'s citation/length checks), before
    that report is accepted. It receives a plain dict (``query_id``,
    ``query``, ``ledger``, ``candidate_sentences``, ``last_commit_arguments``
    — the most recent ``commit_context`` call's normalized ``arguments``
    dict, or ``None`` if nothing was ever committed — and ``raw_messages``
    for anything provider-native) and returns either ``None`` (accept the
    report; behavior is byte-identical to not passing a hook at all) or a
    feedback string, which is injected as a user-message continuation — the
    same shape as an existing rejected-report retry — so the model gets
    exactly one more look before finalizing. Firing at most once makes an
    infinite loop structurally impossible; the harness stays system-agnostic
    because all schema-specific parsing (e.g. a caller's own coverage
    ledger) lives in the hook function the caller supplies, not here.
    ``last_commit_arguments`` — not ``raw_messages`` — is the right source
    for that: ``raw_messages`` is each provider's OWN native format (see
    ``providers/base.py``), so a hook that parses it directly only works
    against one backend.
    ``judge_tool`` — when given (pass ``tools.JUDGE_RELEVANCE_TOOL``) —
    advertises a fourth tool, ``judge_relevance``, that spins up a SEPARATE,
    single-turn model conversation (``tools.judge.execute_judge_relevance``,
    a cheap model by default) to check whether staged/committed documents
    actually support a requirement the model names, or are only topically
    adjacent to it. The model decides for itself when to call it; there is
    no automatic trigger. ``None`` (the default) means neither the tool
    definition nor its dispatch branch does anything different from before
    this parameter existed.
    ``search_result_filter`` — when given — is called after EVERY
    successful ``search`` result, before it is staged, with the call's
    ``requirement`` argument (``""`` if the caller's schema has none) and
    the returned documents; see ``SearchResultPass``'s own docstring for
    the return contract and the validation that keeps a filter from
    injecting content it didn't actually receive. Unlike ``judge_tool``,
    this is not something the model opts into per call — it runs on every
    search a caller enables it for. ``None`` (the default) means no
    filtering, byte-identical to before this parameter existed.
    ``search_preview_chars``/``search_preview_generator``/
    ``stage_search_results`` (PLAN.md Phase 4d, piika-inspired two-tier
    retrieval) — together, the "browse cheap, read deliberately" split:
    when ``search_preview_chars`` is set, every ``search`` result's text
    is truncated to that many characters (regardless of the model's own
    ``budget_tokens_per_result``); when ``search_preview_generator`` is
    ALSO given (a callable, e.g. ``tools.generate_snippets`` — a cheap
    secondary-model call that extracts the QUERY-relevant span instead of
    the document's own opening text), it runs once per search batch and
    ``search_preview_chars`` becomes its hard safety cap rather than a
    positional-truncation length; when ``stage_search_results`` is
    ``False``, search results never enter the ledger at all
    (``get_documents`` is unaffected either way — it already stages full,
    unpaginated text, and is the deliberate "read this in full" action
    these params are designed to work alongside). All three default to
    today's exact behavior (no truncation, no generation, search results
    staged normally).
    """
    if context_token_budget <= 0:
        raise ValueError("context_token_budget must be positive")
    engines = list(engines) if engines else list(DEFAULT_ENGINES)
    provider = make_provider(backend, model)
    tb = TrajectoryBuilder(query_id, query, metadata={
        "model": provider.model_id,
        "backend": backend,
        "k": k,
        "temperature": None,  # sampling params not sent (removed on 4.6+)
        "run_id": run_id,
        "prompt_variant": prompt_variant,
        "engines": engines,
    })
    log.info("[%s] starting: backend=%s model=%s k=%d run_id=%s budget=%d",
             query_id, backend, provider.model_id, k, run_id,
             context_token_budget)
    seen_docids: set[str] = set()
    ledger = ContextLedger()
    status = "completed"
    stop_reason: str | None = None
    sentences: list[dict[str, Any]] | None = None
    repairs: list[str] = []
    uncited_refusals = 0
    pre_final_hook_fired = False
    last_commit_arguments: dict[str, Any] | None = None
    context_tokens = 0
    peak_context_tokens = 0

    # Allocate the run's stamp ONCE: every incremental write below and the
    # final save must land on the same pair of files.
    run_ts = run_timestamp()
    run_started = now_iso()
    run_started_perf = perf_counter()
    last_partial_save = 0.0
    turn_idx = -1  # 0-based model-turn index; bumped on every provider call
    # Wall-clock bounds + turn index of the last model turn; a successful
    # no-tool final-report turn's bounds end up on the output_text item.
    last_turn: tuple[
        str | None, str | None, int | None, float, dict[str, Any]
    ] = (None, None, None, 0.0, {})

    def build_output(references: list[str],
                     answer: list[dict[str, Any]]) -> dict[str, Any]:
        return build_rag_output(
            narrative_id=query_id,
            narrative=query,
            run_id=run_id,
            run_desc=run_desc or (
                f"{system_name} research harness ({backend}/{provider.model_id}, "
                f"prompt={prompt_variant}, "
                f"engines={'+'.join(engines)}): "
                f"continuous single-agent full-text search with sparse "
                f"committed context and line-per-sentence cited prose answers "
                f"parsed into the organizer schema."),
            references=references,
            answer=answer,
        )

    def build_trajectory(final_status: str) -> Any:
        """Finalize the builder and decorate the trace with the run summary.

        Shared by the partial and final saves so a live artifact carries the
        same trace shape as the finished one — only ``status`` differs.
        """
        trajectory = tb.finalize(
            status=final_status,
            raw_messages=(
                provider.raw_messages if final_status != "running" else None),
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
            "committed": sorted(ledger.committed_ids),
            "rejected": sorted(ledger.rejected_ids),
        }
        # Repairs are applied silently to save a correction turn; record them so
        # the leniency stays auditable rather than invisible.
        trajectory.trace["summary"]["report_repairs"] = repairs
        if stop_reason is not None:
            trajectory.trace["summary"]["stop_reason"] = stop_reason
        return trajectory

    def save_partial(*, force: bool = False) -> None:
        """Rewrite output.json mid-run with ``trace.status == "running"``.

        Only ``output.json`` is written: the viewer never reads
        trajectory.json, and the trajectory carries the full raw provider
        message history (~1.2 MB and growing) — rewriting it every couple of
        seconds would be pure cost. Validation is off because an unfinished run
        has no answer yet, and validating it would leave a misleading
        violations file next to a run that is still going.

        A "running" artifact is invisible to everything downstream: both
        ``run.finished_topics`` (--skip-existing) and the submission exporter
        gate on ``trace.status in ("completed", "budget_exhausted")``.
        """
        nonlocal last_partial_save
        now = perf_counter()
        if not force and now - last_partial_save < PARTIAL_SAVE_MIN_INTERVAL_S:
            return
        last_partial_save = now
        try:
            save_run(system_name, query,
                     trajectory=build_trajectory("running"),
                     output=build_output([], []),
                     timestamp=run_ts, validate=False,
                     write_trajectory=False)
        except Exception:
            # Progress reporting must never take the run down with it.
            pass

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

    def run_pre_final_hook(candidate: list[dict[str, Any]]) -> str | None:
        """Fire ``pre_final_hook`` at most once; see its param docstring."""
        nonlocal pre_final_hook_fired
        if pre_final_hook is None or pre_final_hook_fired:
            return None
        pre_final_hook_fired = True
        return pre_final_hook({
            "query_id": query_id,
            "query": query,
            "ledger": ledger,
            "candidate_sentences": candidate,
            "last_commit_arguments": last_commit_arguments,
            "raw_messages": provider.raw_messages,
        })

    def expire_staged_context(reason: str, turn: int | None, *,
                              failed: bool = True,
                              docid_reason: str = "not retained") -> str:
        """Compact an unresolved batch rather than carrying it another turn.

        ``failed=False`` for the case where the model simply issued no
        commit_context: that is a legitimate "retain none of these" decision,
        not an error, and marking it failed would misreport it in the trace and
        in tool_call_counts.

        ``reason`` explains the batch and is said once; ``docid_reason`` is
        stamped on every rejected document, so it stays terse. They were the
        same string until a 10-document batch turned one 60-word explanation
        into 600 words of identical text — per expiry, in the model's context.
        A per-document reason only earns its length when documents differ
        (duplicate, over the per-step cap, simply unselected); here they never
        do.
        """
        ct0 = now_iso()
        started = perf_counter()
        decision = expire_staged(
            ledger,
            max_documents=max_committed_per_step,
            reason=docid_reason,
        )
        provider.compact_tool_results(decision.replacements)
        payload = json.dumps({
            "automatic": True,
            ("error" if failed else "note"): reason,
            "committed": [],
            "rejected": decision.rejected,
        }, ensure_ascii=False)
        duration_ms = round((perf_counter() - started) * 1000, 3)
        output, feedback_stats = action_feedback(payload, duration_ms)
        tb.add_tool_call(
            "commit_context",
            {"documents": [], "automatic": True},
            output,
            failed=failed,
            t_start=ct0,
            t_end=now_iso(),
            turn=turn,
            stats=feedback_stats,
            context=decision.context,
            documents=[],
        )
        return output

    try:
        tool_definitions = [
            search_tool_def or build_search_tool_def(engines),
            GET_DOCUMENTS_TOOL,
            commit_context_tool or COMMIT_CONTEXT_TOOL,
        ]
        if judge_tool is not None:
            tool_definitions.append(judge_tool)
        user_message = TASK_PROMPT.format(now=now_full(), query=query)
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
        # Publish the artifact before the first (multi-second) model turn so
        # the run shows up in the viewer as soon as it starts.
        save_partial(force=True)

        # One continuous agent loop: research actions and the eventual cited
        # prose report are turns in the same provider conversation.
        rounds = 0
        finishing = False
        hard_round_cap = safety_max_rounds + FINISHING_ROUNDS_GRACE
        while True:
            # The one backstop every path passes through. Individual branches
            # check safety_max_rounds too, but a turn can now consist entirely
            # of neutralised no-ops (a commit_context with nothing staged),
            # which executes nothing and reaches none of those checks — so
            # without this the loop could spin forever making no progress.
            if rounds >= hard_round_cap:
                raise RuntimeError(
                    "runaway-loop safety backstop reached: "
                    f"{rounds} rounds (safety_max_rounds={safety_max_rounds} "
                    f"+ {FINISHING_ROUNDS_GRACE} to finish)")
            # Two save points cover the whole loop body with no bookkeeping at
            # each of its many `continue`s: this one flushes everything the
            # previous iteration's actions produced, and the one below flushes
            # the model turn itself (the tool calls then run against a fresh
            # artifact).
            save_partial()
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
            save_partial()
            calls = turn["tool_calls"]
            log.info("[%s] round %d: turn %s took %.1fs, context %s tok, "
                     "%d tool call(s)", query_id, rounds, ti,
                     last_turn[3] / 1000, f"{context_tokens:,}", len(calls))
            commit_calls = [
                call for call in calls if call["name"] == "commit_context"]

            # A staged batch exists for exactly this turn, and exactly one
            # commit_context resolves it. Position does not matter: commit_calls
            # are applied below before retrieval_calls regardless of the order
            # the model listed them in, so demanding "first" only rejected turns
            # the harness would have handled correctly anyway.
            valid_commit = len(commit_calls) == 1
            if ledger.has_staged and not valid_commit:
                # No commit_context at all means the model kept none of the
                # staged documents — which is exactly what an empty selection
                # says. Record that as a deliberate reject-all and let the rest
                # of the turn run, rather than treating it as a protocol breach
                # and refusing the turn's other actions: the model's intent
                # (keep nothing, search again) is unambiguous and harmless, and
                # refusing it cost a full turn each time. Multiple
                # commit_context calls are genuinely ambiguous, so those still
                # expire the batch and lose the turn.
                expire_staged_context(
                    "no commit_context was issued on the turn after this batch "
                    "was staged, so it is treated as an explicit decision to "
                    "retain none of these documents. The turn's other actions "
                    "still ran. To keep a document, call commit_context on the "
                    "turn immediately after the search that staged it."
                    if not commit_calls else
                    "staged batch expired because the turn issued "
                    f"{len(commit_calls)} commit_context calls; exactly one "
                    "resolves a staged batch",
                    ti,
                    failed=bool(commit_calls),
                )
                if not calls:
                    # The turn may itself be a valid final report. Staged
                    # (uncommitted) evidence can never be cited, so accepting
                    # it after the expiry loses nothing and saves a turn.
                    candidate, _, notes = _parse_final_prose(
                        turn.get("text"), set(ledger.committed_ids),
                        allow_uncited=(
                            finishing
                            or uncited_refusals >= MAX_UNCITED_REFUSALS))
                    if candidate is not None:
                        hook_feedback = run_pre_final_hook(candidate)
                        if hook_feedback:
                            provider.add_user_message(hook_feedback)
                            next_model_input = {
                                "kind": "user_message", "text": hook_feedback}
                            continue
                        sentences = candidate
                        repairs = notes
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
                if commit_calls:
                    # Ambiguous: several commit_context calls, so there is no
                    # single selection to honour. The batch is already gone;
                    # refuse the rest of the turn so the next one starts clean.
                    if rounds >= safety_max_rounds:
                        raise RuntimeError(
                            "runaway-loop safety backstop reached while "
                            "refusing actions after a staged batch expired")
                    msg, feedback_stats = action_feedback(json.dumps({
                        "error": "actions refused because the turn issued "
                                 f"{len(commit_calls)} commit_context calls; "
                                 "exactly one resolves a staged batch"
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
                # No commit_context: the batch is now expired as a deliberate
                # reject-all and the ledger is clear, so fall through and run
                # this turn's searches — they stage a fresh batch normally.

            # commit_context with nothing staged is a no-op, not a failure:
            # there is simply nothing left to decide about. Answer that call and
            # let the turn's searches run. Refusing the whole turn here was the
            # other half of a wasteful loop — the model would search without
            # committing (expiring the batch), dutifully send commit_context on
            # the next turn to comply, find nothing staged, and lose that turn's
            # searches too. Both turns were spent on bookkeeping while the
            # model's actual intent was unambiguous.
            noop_commit_ids: set[str] = set()
            if not ledger.has_staged and commit_calls:
                noop_msg, noop_stats = action_feedback(json.dumps({
                    "note": "no staged batch is open, so there was nothing to "
                            "commit and this call did nothing. A batch is only "
                            "open on the turn immediately after the search that "
                            "staged it.",
                    "committed": [],
                    "rejected": [],
                }), 0)
                ts = now_iso()
                for call in commit_calls:
                    noop_commit_ids.add(call["id"])
                    tb.add_tool_call(
                        call["name"], call["arguments"], noop_msg, failed=False,
                        t_start=ts, t_end=ts, turn=ti,
                        stats=noop_stats,
                        context=_context_snapshot(ledger),
                        documents=[],
                        tool_call_id=call["id"],
                    )
                commit_calls = []

            budget_hit = (
                context_tokens >= context_token_budget)
            safety_hit = rounds >= safety_max_rounds
            if (budget_hit or safety_hit) and not finishing:
                status = "budget_exhausted"
                stop_reason = (
                    "safety_max_rounds"
                    if safety_hit else "generation_context_tokens")
                finishing = True
                log.info("[%s] budget reached (%s); finishing",
                         query_id, stop_reason)
                generation_step = next(
                    step for step in tb.trace_steps
                    if step["id"] == generation_id)
                generation_step.setdefault("stats", {})[
                    "context_budget_exhausted"] = budget_hit

            if not calls:
                candidate, validation_errors, notes = _parse_final_prose(
                    turn.get("text"), set(ledger.committed_ids),
                    allow_uncited=(
                        finishing or uncited_refusals >= MAX_UNCITED_REFUSALS))
                if candidate is not None:
                    hook_feedback = run_pre_final_hook(candidate)
                    if hook_feedback:
                        provider.add_user_message(hook_feedback)
                        next_model_input = {
                            "kind": "user_message", "text": hook_feedback}
                        continue
                    sentences = candidate
                    repairs = notes
                    break
                log.info("[%s] final report rejected: %s",
                         query_id, "; ".join(validation_errors))
                if any(error.startswith(_UNCITED_ERRORS)
                       for error in validation_errors):
                    uncited_refusals += 1
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
            # Every tool_use must be answered, including the no-op commits
            # neutralised above — an unanswered call is a provider error.
            for call_id in noop_commit_ids:
                result_by_id[call_id] = {
                    "id": call_id, "content": noop_msg, "is_error": False}

            # Resolve the previous staged batch first, even when the budget was
            # reached on this turn. Compaction is bookkeeping, not retrieval,
            # and gives the next same-loop turn a clean context.
            if commit_calls:
                call = commit_calls[0]
                last_commit_arguments = call["arguments"]
                ct0 = now_iso()
                started = perf_counter()
                pending_before = list(ledger.pending)
                committed_before = set(ledger.committed_ids)
                rejected_before = set(ledger.rejected_ids)
                committed_call_id_before = dict(ledger.committed_call_id)
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
                    ledger.committed_ids = committed_before
                    ledger.rejected_ids = rejected_before
                    ledger.committed_call_id = committed_call_id_before
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
                    # A release (if any) touches call_ids OUTSIDE this turn's
                    # staged batch, so it is merged into the SAME compaction
                    # call as the normal commit -- one atomic provider-history
                    # rewrite either way.
                    replacements = dict(decision.replacements)
                    if handled.release is not None:
                        replacements.update(handled.release.replacements)
                    try:
                        provider.compact_tool_results(replacements)
                    except Exception:
                        # Provider-history compaction is atomic with the ledger
                        # update. A backend failure ends the run rather than
                        # carrying inconsistent context into another turn.
                        ledger.pending = pending_before
                        ledger.committed_ids = committed_before
                        ledger.rejected_ids = rejected_before
                        ledger.committed_call_id = committed_call_id_before
                        raise
                    out = json.dumps(handled.payload, ensure_ascii=False)
                    failed = False
                    context = decision.context
                    if handled.release is not None:
                        context = {**context,
                                  "released": handled.release.released}
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
                    log.warning("[%s] commit_context FAILED (batch expired)",
                                query_id)
                else:
                    log.info("[%s] commit_context: %d committed, %d rejected "
                             "(%d total)", query_id, len(documents),
                             len(decision.rejected),
                             len(ledger.committed_ids))
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
                    retrieval_calls, k=k, seen_docids=seen_docids,
                    engines=engines, default_k_by_engine=default_k_by_engine)
                for call, (
                    out, trace_output, returned, failed, documents,
                    ct0, ct1, duration_ms
                ) in zip(retrieval_calls, executed):
                    if not failed:
                        # Filter/reorder/truncate BEFORE the budget-status
                        # footer is appended below -- that footer is plain
                        # text after the JSON payload, so applying either
                        # pass after would break their own `json.loads(out)`.
                        requirement = str(
                            call["arguments"].get("requirement", ""))
                        out, documents = _apply_search_result_filter(
                            search_result_filter, requirement, out, documents)
                        out, documents = _apply_search_preview(
                            out, documents, search_preview_chars,
                            requirement=requirement,
                            preview_generator=search_preview_generator)
                    out, feedback_stats = action_feedback(out, duration_ms)
                    context = {
                        "staged": (
                            [str(document["id"]) for document in documents]
                            if stage_search_results else []),
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
                    log.info(
                        "[%s] search %r: %s", query_id,
                        call["arguments"].get("query", ""),
                        "FAILED" if failed
                        else (f"{len(documents)} docs staged"
                              if stage_search_results
                              else f"{len(documents)} docs previewed "
                                   "(not staged)"))
                    if not failed and stage_search_results:
                        ledger.stage(
                            call["id"], call["name"], out, documents)
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": out,
                        "is_error": failed,
                    }

            # get_documents: fetch specific units by id and stage like search,
            # so the same commit_context step retains them next turn.
            get_docs_calls = [
                call for call in calls if call["name"] == "get_documents"]
            if get_docs_calls and (budget_hit or safety_hit):
                gd_msg, gd_stats = action_feedback(json.dumps({
                    "error": (
                        "tool call not executed because the preceding "
                        "generation input context reached the research budget; "
                        "write the final report now using the contract "
                        "already defined in the system prompt"),
                    "context_tokens": context_tokens,
                    "peak_context_tokens": peak_context_tokens,
                    "context_token_budget": context_token_budget,
                }), 0)
                ts = now_iso()
                for call in get_docs_calls:
                    tb.add_tool_call(
                        call["name"], call["arguments"], gd_msg,
                        failed=True, t_start=ts, t_end=ts, turn=ti,
                        stats=gd_stats,
                        context=_context_snapshot(ledger), documents=[],
                        tool_call_id=call["id"])
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": gd_msg, "is_error": True}
            elif get_docs_calls:
                for call in get_docs_calls:
                    ct0 = now_iso()
                    try:
                        out, documents, missing = execute_get_documents(
                            call["arguments"])
                        failed = False
                    except Exception as exc:  # a fetch failure is not fatal
                        out = json.dumps(
                            {"error": f"{type(exc).__name__}: {exc}"})
                        documents, missing, failed = [], [], True
                    ct1 = now_iso()
                    out, feedback_stats = action_feedback(out, 0.0)
                    # ``returned`` mirrors the search branch's hit shape —
                    # add_tool_call derives strict returned_docids via
                    # hit["docid"], so it must be dicts, not id strings.
                    returned = [{"docid": str(d["docid"]),
                                 "score": d.get("score")} for d in documents]
                    context = {
                        "staged": [str(d["id"]) for d in documents],
                        "committed": [], "rejected": []}
                    tb.add_tool_call(
                        call["name"], call["arguments"], out,
                        returned=returned, failed=failed,
                        t_start=ct0, t_end=ct1, turn=ti,
                        stats=feedback_stats, documents=[], context=context,
                        tool_call_id=call["id"])
                    log.info("[%s] get_documents: %d staged, %d missing",
                             query_id, len(documents), len(missing))
                    if not failed and documents:
                        ledger.stage(
                            call["id"], call["name"], out, documents)
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": out, "is_error": failed}

            # judge_relevance: a side-call to a SEPARATE model, opt-in via
            # judge_tool. Never stages/commits anything of its own — it only
            # reads what the ledger already holds (see
            # tools.judge._documents_by_id) — so there is nothing here for
            # the budget/safety gates the search and get_documents branches
            # apply; it is a judgment on existing material, not new
            # retrieval, and is exactly as useful while `finishing`.
            judge_calls = [
                call for call in calls if call["name"] == "judge_relevance"]
            for call in judge_calls:
                ct0 = now_iso()
                started = perf_counter()
                out = execute_judge_relevance(call["arguments"], ledger)
                duration_ms = round((perf_counter() - started) * 1000, 3)
                out, feedback_stats = action_feedback(out, duration_ms)
                tb.add_tool_call(
                    call["name"], call["arguments"], out, failed=False,
                    t_start=ct0, t_end=now_iso(), turn=ti,
                    stats=feedback_stats,
                    context=_context_snapshot(ledger), documents=[],
                    tool_call_id=call["id"])
                result_by_id[call["id"]] = {
                    "id": call["id"], "content": out, "is_error": False}

            provider.add_tool_results(
                [result_by_id[call["id"]] for call in calls])
            next_model_input = {
                "kind": "tool_results",
                "tool_call_ids": [call["id"] for call in calls],
            }

    except Exception as e:
        status = "failed"
        log.exception("[%s] run failed", query_id)
        if not sentences:
            sentences = [{"text": f"Run failed: {type(e).__name__}: {e}",
                          "citations": []}]

    eligible_ids = set(ledger.committed_ids)
    # Internal citations are unit ids (chunk ids): the agent cites the exact id
    # it committed, unedited. references_unit/answer are chunk-native.
    references_unit, answer = _map_citations(sentences, eligible_ids)
    answer_text = " ".join(s["text"] for s in answer)
    # Organizer submission cites doc-level ids: collapse pages of a document to
    # the parent docid and remap citation indices (the final-format transform).
    # The trace keeps the chunk-native unit ids in references_full so reviewers
    # see exactly which page supported each reference.
    references, answer = _collapse_to_docs(references_unit, answer)
    tb.set_trace_output({
        "references": references,
        "references_full": references_unit,
        "answer": answer,
    })
    tb.add_output_text(
        answer_text, t_start=last_turn[0], t_end=last_turn[1],
        turn=last_turn[2], stats=last_turn[4],
        context=_context_snapshot(ledger), record_trace=False)

    log.info("[%s] finished status=%s: %d sentences, %d references, "
             "%d committed docs", query_id, status, len(answer),
             len(references), len(ledger.committed_ids))
    output = build_output(references, answer)
    trajectory = build_trajectory(status)
    # The final save is the only one that writes the trajectory, validates, and
    # carries a terminal status — it overwrites the last partial in place.
    paths = save_run(system_name, query, trajectory=trajectory, output=output,
                     timestamp=run_ts)
    return {"status": status, "paths": paths,
            "tool_call_counts": trajectory["tool_call_counts"],
            "n_references": len(references), "n_sentences": len(answer),
            "words": _word_count(answer),
            "context_tokens": context_tokens,
            "peak_context_tokens": peak_context_tokens,
            "processed_tokens": (
                trajectory.trace["summary"]["tokens"].get("processed", 0)),
            "committed_documents": len(ledger.committed_ids),
            "rejected_documents": len(ledger.rejected_ids)}
