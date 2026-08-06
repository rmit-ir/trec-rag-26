"""aus_agent_v2 — coverage-planned, evidence-patched RAG for TREC RAG 2026.

Loop: model turns with full-text ``search`` retrieval. Tool outputs are normally
staged for one model step, after which the model must call ``commit_context``:
selected documents stay verbatim in the conversation and rejected documents
are compacted to decision markers. The executable-contract candidate may keep
the same batch through two bounded correction turns when only its support
annotation is invalid; no compaction occurs until correction or expiry.
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
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from ragrun import (
    TrajectoryBuilder,
    build_rag_output,
    now_iso,
    run_timestamp,
    save_run,
)
from ragrun.trajectory import TZ
from ragrun.pricing import cost_for_provider

from aus_agent.context import ContextLedger
from .coverage_plan import (
    COVERAGE_PLAN_SYSTEM,
    coverage_plan_request,
    normalize_coverage_plan,
)
from .atomic_plan import (
    ATOMIC_PLAN_SYSTEM,
    atomic_plan_request,
    normalize_atomic_plan,
)
from .coverage_verify import (
    COVERAGE_VERIFY_SYSTEM,
    coverage_repair_request,
    coverage_verify_request,
    normalize_coverage_audit,
)
from .claim_finish import (
    CLAIM_FINISH_SYSTEM,
    apply_claim_patches,
    build_claim_finish_packet,
)
from .audience_verify import (
    AUDIENCE_PATCH_SYSTEM,
    AUDIENCE_VERIFY_SYSTEM,
    apply_audience_insertions,
    audience_verify_request,
    build_audience_patch_packet,
    normalize_audience_audit,
)
from .plan_critic import (
    PLAN_CRITIC_SYSTEM,
    merge_plan_critique,
    normalize_plan_critique,
    plan_critic_request,
)
from .observable_scout import (
    OBSERVABLE_SCOUT_SYSTEM,
    combine_obligation_audits,
    normalize_observable_scout,
    observable_scout_request,
)
from .plan_reconcile import (
    PLAN_RECONCILE_SYSTEM,
    missing_must_mentions,
    normalize_reconciled_plan,
    plan_reconcile_request,
)
from .search import build_search_tool_def, execute_full_text_search
from .finish_review import (
    FINISH_REVIEW_SYSTEM,
    FactLedger,
    apply_evidence_patches,
    build_finish_review_packet,
    capture_committed_facts,
)
from .answer_blueprint import (
    PREPARE_ANSWER_TOOL,
    answer_blueprint_request,
    build_answer_handoff,
    commit_context_tool_with_facts,
    normalize_answer_blueprint,
)
from .answer_form import (
    infer_answer_form_policy,
    render_terminal_system_addendum,
)
from .coverage_contract import (
    EvidenceLedger,
    build_atomic_coverage_contract,
    build_coverage_contract,
    commit_tool_with_contract,
    contract_trace,
    normalize_commit_supports,
    normalize_commit_promotions,
    normalize_requirement_ids,
    render_contract_status,
    render_terminal_evidence_handoff,
    render_research_contract,
    search_tool_with_contract,
    submit_answer_tool,
    submit_answer_request,
    validate_support_routes,
    validate_submission,
)
from aus_agent.providers.base import Provider
from aus_agent.tools import (
    COMMIT_CONTEXT_TOOL,
    apply_commit,
    execute_get_documents,
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
MAX_COVERAGE_REPAIR_SEARCH_BATCHES = 1
# A stricter commit schema is useful only if a typo does not destroy the
# evidence it is trying to annotate. Keep the full staged result through two
# corrective commit turns; the third invalid attempt expires it so malformed
# tool loops remain bounded.
MAX_COVERAGE_COMMIT_CORRECTIONS = 2


class _CoverageSupportValidationError(ValueError):
    """A model-authored support annotation can be corrected in-place."""

# A structural step, not a prompt rule: the ONE time the agent first tries to
# write its report, the harness interrupts and requires a coverage audit.
#
# Motivation is the single largest measured gap. Implicit Criteria carry 38.4%
# of all rubric weight, sit at 0.651, and hold 0.134 recoverable -- nine times
# any other axis. They are the requirements a question IMPLIES but never states:
# a retirement question implying Roth against traditional, a market question
# implying the major indexes by name, a diagnostic-model question implying who
# provides ground-truth labels. Of the high-weight implicit criteria the best
# run misses, 20 of 20 name an entity the question never mentions.
#
# Twenty-two single-factor arms failed to move this, including one that removed
# the prompt rule forbidding such searches -- so the agent is not blocked from
# looking, it does not work out that it should. Telling it so in the system
# prompt is what every failed arm did. Interrupting the loop at the moment it
# has decided it is finished is a different intervention: the decision is made,
# the evidence is in context, and the question "what would a knowledgeable
# reader expect here that you have not covered?" is answerable exactly then.
COVERAGE_AUDIT = (
    "Before you write the report, audit its coverage once.\n"
    "List what a knowledgeable reader would expect a complete answer to this "
    "request to contain — including the requirements the request implies but "
    "never states: the standard options anyone comparing would weigh, the terms "
    "that must be defined, the named instruments or bodies in this domain, the "
    "regulation that governs it, the cost or scale dimension, the failure modes "
    "of whatever you are recommending.\n"
    "For each item, say whether your committed evidence supports it.\n"
    "Then act: search for the gaps worth closing, commit what you find, and "
    "write the report on a later turn. If nothing is missing, say so in one "
    "line and write the report now. Do not assert anything you have not "
    "retrieved — a gap you cannot close is left out or named as unestablished."
)
# One full system prompt per file under prompts/system/. `default.md` is the
# live baseline; other files are variants selected by their filename stem
# (e.g. --prompt-variant firsthand -> prompts/system/firsthand.md).
SYSTEM_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts" / "system"
DEFAULT_PROMPT_VARIANT = "default"
MAX_COMMITTED_PLACEHOLDER = "__MAX_COMMITTED_DOCS__"

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


def _coverage_audit_enabled() -> bool:
    """Opt-in, so the arm measures this change and nothing else."""
    import os
    return os.environ.get("AUS_AGENT_COVERAGE_AUDIT", "").strip().lower() in (
        "1", "true", "yes", "on")


def now_full(now: datetime | None = None) -> str:
    """The wall clock, spelled out unambiguously for the model, in UTC.

    Weekday and month name so nothing hinges on reading a numeric date in the
    right order.

    **UTC, not the host's zone.** This string is the first line of every request
    the model sees, and it used to read "(Australia/Melbourne)". That is a
    locale signal on every single topic, and it plausibly drove a measured
    defect: 9 of 119 test narratives came back with volunteered Australian
    framing -- an emergency number, a regulator, an employment-law regime the
    request never mentioned -- scoring 0.278 against 0.509 where it happened.
    A prompt rule telling the model not to localise was fighting a cue the
    harness itself was supplying. Artifact timestamps stay in local time; this
    is only what the model is told.
    """
    now = now or datetime.now(timezone.utc)
    return f"{now.astimezone(timezone.utc):%A, %d %B %Y, %H:%M:%S} UTC"


def load_system_prompt(max_committed: int,
                       variant: str = DEFAULT_PROMPT_VARIANT) -> str:
    """Load the system prompt for ``variant`` and render one token.

    Each variant is a full prompt file ``prompts/system/<variant>.md``;
    ``default`` is the live baseline. The rendered ``__MAX_COMMITTED_DOCS__``
    token must appear exactly once.
    """
    path = SYSTEM_PROMPTS_DIR / f"{variant}.md"
    if not path.exists():
        raise RuntimeError(f"unknown prompt variant {variant!r}: "
                           f"{path} not found")
    template = path.read_text(encoding="utf-8")
    count = template.count(MAX_COMMITTED_PLACEHOLDER)
    if count != 1:
        raise RuntimeError(
            f"prompt variant {variant!r} must contain exactly one "
            f"{MAX_COMMITTED_PLACEHOLDER} placeholder; found {count}")
    return template.replace(MAX_COMMITTED_PLACEHOLDER, str(max_committed))


def make_provider(backend: str, model: str | None,
                  region: str | None = None) -> Provider:
    """Use the v2-local transport policy without changing baseline AUS."""
    from .provider import make_provider as make_v2_provider

    return make_v2_provider(backend, model, region=region)


def _execute_tool_calls(calls: list[dict[str, Any]], *, k: int,
                        seen_docids: set[str],
                        engines: list[str] | None = None) -> list[tuple]:
    """Execute one model turn's tool calls IN PARALLEL (threads; the tools are
    I/O-bound and thread-safe). Returns, in the model's tool_use order, one
    ``(output, trace_output, returned, failed, documents, t_start, t_end,
    duration_ms)``
    tuple per call — each
    call carries its own real wall-clock bounds. ``engines`` is the run's
    enabled set, named back to the model when a call omits the required
    ``search_engine``."""
    def timed(call: dict[str, Any]) -> tuple:
        t0 = now_iso()
        started = perf_counter()
        execution = execute_full_text_search(
            call["arguments"], default_k=k, seen_docids=seen_docids,
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
    # Billed as output, invisible as text. Reported separately so a
    # reasoning-effort change can be costed rather than guessed at.
    reasoning = int(usage.get("reasoning_tokens", 0) or 0)
    return {
        "reasoning": reasoning,
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
                peak_context_tokens: int,
                provider: Any = None) -> dict[str, Any]:
    """Per-turn stats, including cost when the provider's rates are known.

    ``ragrun.trajectory._cost_summary`` aggregates whatever ``stats.cost`` the
    caller attaches and fabricates nothing, so a run whose turns carry no cost
    block reports every call as *unpriced* — which is what happened here until
    this line existed. Attaching it at the one place every turn passes through
    keeps the run-level total honest by construction.

    ``cost_for_provider`` returns ``None`` for a model with no committed rate
    table, so an unpriced model still runs; it just reports tokens without
    dollars rather than guessing a rate.
    """
    token_stats = _usage_token_stats(usage)
    token_stats["context"] = token_stats["input"]
    stats = {
        "duration_ms": duration_ms,
        "context_tokens": context_tokens,
        "peak_context_tokens": peak_context_tokens,
        "context_budget_tokens": context_budget_tokens,
        "elapsed_ms": elapsed_ms,
        "tokens": token_stats,
        "provider_usage": usage,
    }
    if provider is not None:
        cost = cost_for_provider(provider, token_stats)
        if cost is not None:
            stats["cost"] = cost
    return stats


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
              finish_review: bool = False,
              coverage_plan: bool = True,
              plan_critic: bool = True,
              plan_critic_max_additions: int = 8,
              compact_scout_plan: bool = False,
              observable_scout: bool = True,
              plan_reconcile: bool = True,
              coverage_verify: bool = True,
              coverage_repair_strategy: str = "patch-first",
              audience_verify: bool = False,
              answer_blueprint: bool = False,
              coverage_contract: bool = False,
              atomic_contract_plan: bool = False,
              dynamic_contract_rows: bool = False,
              terminal_evidence_handoff: bool = False,
              engines: list[str] | None = None) -> dict[str, Any]:
    """Run one topic end-to-end; saves trajectory + output, returns paths.

    ``engines`` selects which retrieval backends the search tool exposes (e.g.
    ``["ssr"]`` to test SSR Boolean in isolation); defaults to the hybrid
    ``semantic`` + ``keyword`` pair.
    """
    if context_token_budget <= 0:
        raise ValueError("context_token_budget must be positive")
    if answer_blueprint and coverage_contract:
        raise ValueError(
            "answer_blueprint and coverage_contract are alternative terminal "
            "handoffs and cannot both be enabled")
    if coverage_contract and not coverage_plan:
        raise ValueError("coverage_contract requires coverage_plan")
    if atomic_contract_plan and not coverage_contract:
        raise ValueError("atomic_contract_plan requires coverage_contract")
    if dynamic_contract_rows and not coverage_contract:
        raise ValueError("dynamic_contract_rows requires coverage_contract")
    if terminal_evidence_handoff and not coverage_contract:
        raise ValueError("terminal_evidence_handoff requires coverage_contract")
    if coverage_repair_strategy not in {"patch-first", "research-first"}:
        raise ValueError(
            "coverage_repair_strategy must be 'patch-first' or 'research-first'")
    if not 1 <= plan_critic_max_additions <= 12:
        raise ValueError("plan_critic_max_additions must be between 1 and 12")
    answer_form_policy = infer_answer_form_policy(query)
    engines = list(engines) if engines else list(DEFAULT_ENGINES)
    provider = make_provider(backend, model)
    tb = TrajectoryBuilder(query_id, query, metadata={
        "model": provider.model_id,
        "backend": backend,
        "k": k,
        "temperature": None,  # sampling params not sent (removed on 4.6+)
        "run_id": run_id,
        "prompt_variant": prompt_variant,
        "finish_review": finish_review,
        "coverage_plan": coverage_plan,
        "plan_critic": plan_critic,
        "plan_critic_max_additions": plan_critic_max_additions,
        "compact_scout_plan": compact_scout_plan,
        "observable_scout": observable_scout,
        "plan_reconcile": plan_reconcile,
        "coverage_verify": coverage_verify,
        "coverage_repair_strategy": coverage_repair_strategy,
        "audience_verify": audience_verify,
        "answer_blueprint": answer_blueprint,
        "coverage_contract": coverage_contract,
        "atomic_contract_plan": atomic_contract_plan,
        "dynamic_contract_rows": dynamic_contract_rows,
        "terminal_evidence_handoff": terminal_evidence_handoff,
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
    context_tokens = 0
    peak_context_tokens = 0
    audit_done = False
    finish_review_checked = False
    finish_review_requested = False
    finish_review_stats = {
        "cards": 0, "documents": 0, "packet_chars": 0,
        "inferred_citations": 0,
    }
    finish_review_original: list[dict[str, Any]] | None = None
    finish_review_original_notes: list[str] = []
    finish_review_original_text = ""
    finish_review_original_words = 0
    finish_review_revision_words = 0
    finish_review_fallback = False
    finish_review_patch_stats = {"proposed": 0, "accepted": 0, "rejected": 0}
    finish_review_patch_errors: list[str] = []
    finish_review_packet = ""
    finish_review_audit = ""
    finish_review_audit_pending = False
    finish_review_writer_started = False
    fact_ledger: FactLedger = {}
    answer_blueprint_value: dict[str, Any] | None = None
    answer_blueprint_prepared = False
    answer_blueprint_requests = 0
    answer_blueprint_attempts = 0
    answer_blueprint_invalidations = 0
    answer_blueprint_errors: list[str] = []
    answer_handoff_chars = 0
    coverage_contract_items = []
    atomic_plan_rows: list[dict[str, Any]] = []
    coverage_evidence = EvidenceLedger()
    coverage_submission_attempts = 0
    coverage_submission_errors: list[str] = []
    coverage_submission_stats: dict[str, Any] = {}
    coverage_terminal_handoff_sent = False
    coverage_terminal_handoff_chars = 0
    coverage_dynamic_promotions = 0
    coverage_commit_corrections = 0
    coverage_commit_expirations = 0
    coverage_commit_batch_failures = 0
    coverage_commit_validation_errors: list[str] = []
    committed_documents: dict[str, dict[str, Any]] = {}
    archived_raw_messages: list[Any] = []
    auxiliary_raw_messages: list[Any] = []
    coverage_plan_text = ""
    coverage_plan_initial = ""
    coverage_plan_merged_words = 0
    coverage_plan_requested = False
    plan_critic_requested = False
    plan_critic_raw = ""
    plan_critic_audit: dict[str, Any] = {
        "verdict": "pass", "additions": []}
    plan_critic_errors: list[str] = []
    observable_scout_requested = False
    observable_scout_raw = ""
    observable_scout_audit: dict[str, Any] = {
        "verdict": "pass", "additions": []}
    observable_scout_errors: list[str] = []
    obligation_audit: dict[str, Any] = {
        "verdict": "pass", "additions": []}
    plan_reconcile_requested = False
    plan_reconcile_applied = False
    plan_reconcile_raw = ""
    plan_reconcile_errors: list[str] = []
    plan_reconcile_missing_mentions: list[str] = []
    coverage_verify_checked = False
    coverage_verify_requested = False
    coverage_verify_audit: dict[str, Any] = {
        "verdict": "pass", "missing": []}
    coverage_verify_raw = ""
    coverage_verify_errors: list[str] = []
    coverage_patch_requested = False
    coverage_patch_raw = ""
    coverage_patch_errors: list[str] = []
    coverage_patch_stats = {"proposed": 0, "accepted": 0, "rejected": 0}
    coverage_patch_packet_chars = 0
    audience_verify_requested = False
    audience_verify_checked = False
    audience_verify_audit: dict[str, Any] = {
        "verdict": "pass", "missing": []}
    audience_verify_raw = ""
    audience_verify_errors: list[str] = []
    audience_patch_requested = False
    audience_patch_raw = ""
    audience_patch_errors: list[str] = []
    audience_patch_stats = {"proposed": 0, "accepted": 0, "rejected": 0}
    audience_patch_packet_chars = 0
    coverage_repair_active = False
    coverage_repair_search_batches = 0
    coverage_repair_original: list[dict[str, Any]] | None = None
    coverage_repair_original_notes: list[str] = []
    coverage_repair_original_words = 0
    coverage_repair_fallback = False

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
                f"aus_agent_v2 research harness ({backend}/{provider.model_id}, "
                f"prompt={prompt_variant}, "
                f"finish_review={finish_review}, "
                f"coverage_plan={coverage_plan}, "
                f"plan_critic={plan_critic}, "
                f"coverage_contract={coverage_contract}, "
                f"engines={'+'.join(engines)}): "
                + (
                    "isolated coverage planning, staged-context full-text "
                    "research, fresh coverage verification, and a fresh "
                    "citation-local evidence writer; "
                    if coverage_plan and finish_review else
                    "staged-context full-text research with optional isolated "
                    "finishing stages; "
                    if coverage_plan or finish_review else
                    "continuous single-agent full-text research; "
                )
                + (
                    "requirement-tagged terminal answer is validated and "
                    "mapped into the organizer schema."
                    if coverage_contract else
                    "line-per-sentence cited prose is parsed into the "
                    "organizer schema."
                )),
            references=references,
            answer=answer,
        )

    def build_trajectory(final_status: str) -> Any:
        """Finalize the builder and decorate the trace with the run summary.

        Shared by the partial and final saves so a live artifact carries the
        same trace shape as the finished one — only ``status`` differs.
        """
        raw_messages = None
        if final_status != "running":
            raw_messages = (
                archived_raw_messages
                + list(provider.raw_messages)
                + auxiliary_raw_messages
            )
        trajectory = tb.finalize(
            status=final_status,
            raw_messages=raw_messages,
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
            "finish_review": finish_review,
            "coverage_plan": coverage_plan,
            "plan_critic": plan_critic,
            "plan_critic_max_additions": plan_critic_max_additions,
            "compact_scout_plan": compact_scout_plan,
            "observable_scout": observable_scout,
            "plan_reconcile": plan_reconcile,
            "coverage_verify": coverage_verify,
            "coverage_repair_strategy": coverage_repair_strategy,
            "audience_verify": audience_verify,
            "answer_blueprint": answer_blueprint,
            "coverage_contract": coverage_contract,
            "atomic_contract_plan": atomic_contract_plan,
            "dynamic_contract_rows": dynamic_contract_rows,
            "terminal_evidence_handoff": terminal_evidence_handoff,
        }
        trajectory.trace["summary"]["context"] = {
            "committed": sorted(ledger.committed_ids),
            "rejected": sorted(ledger.rejected_ids),
        }
        trajectory.trace["summary"]["finish_review"] = {
            "enabled": finish_review,
            "checked": finish_review_checked,
            "requested": finish_review_requested,
            "fact_cards": sum(len(facts) for facts in fact_ledger.values()),
            "documents_with_facts": len(fact_ledger),
            "evidence_cards": finish_review_stats["cards"],
            "evidence_documents": finish_review_stats["documents"],
            "packet_chars": finish_review_stats["packet_chars"],
            "inferred_citations": finish_review_stats["inferred_citations"],
            "fresh_context": finish_review_requested,
            "original_words": finish_review_original_words,
            "revision_words": finish_review_revision_words,
            "coverage_fallback": finish_review_fallback,
            "patches": dict(finish_review_patch_stats),
            "patch_errors": list(finish_review_patch_errors),
            "coverage_audit_chars": len(finish_review_audit),
            "coverage_audit_words": len(finish_review_audit.split()),
            "writer_started": finish_review_writer_started,
        }
        trajectory.trace["summary"]["answer_blueprint"] = {
            "enabled": answer_blueprint,
            "prepared": answer_blueprint_prepared,
            "requests": answer_blueprint_requests,
            "attempts": answer_blueprint_attempts,
            "invalidations": answer_blueprint_invalidations,
            "requirements": (
                len(answer_blueprint_value.get("requirements", []))
                if answer_blueprint_value else 0
            ),
            "mapped_claims": (
                sum(len(item.get("claims", [])) for item in
                    answer_blueprint_value.get("requirements", []))
                if answer_blueprint_value else 0
            ),
            "handoff_chars": answer_handoff_chars,
            "errors": list(answer_blueprint_errors),
            "fact_cards": sum(len(cards) for cards in fact_ledger.values()),
        }
        trajectory.trace["summary"]["coverage_contract"] = {
            "enabled": coverage_contract,
            "answer_form": answer_form_policy.trace(),
            "commit_corrections": coverage_commit_corrections,
            "commit_expirations": coverage_commit_expirations,
            "commit_validation_errors": list(
                coverage_commit_validation_errors),
            "submission_attempts": coverage_submission_attempts,
            "submission_errors": list(coverage_submission_errors),
            "submission": dict(coverage_submission_stats),
            "terminal_handoff_sent": coverage_terminal_handoff_sent,
            "terminal_handoff_chars": coverage_terminal_handoff_chars,
            "dynamic_promotions": coverage_dynamic_promotions,
            **contract_trace(coverage_contract_items, coverage_evidence),
        }
        trajectory.trace["summary"]["coverage_plan"] = {
            "enabled": coverage_plan,
            "requested": coverage_plan_requested,
            "chars": len(coverage_plan_text),
            "words": len(coverage_plan_text.split()),
        }
        trajectory.trace["summary"]["plan_critic"] = {
            "enabled": plan_critic,
            "max_additions": plan_critic_max_additions,
            "compact_handoff": compact_scout_plan,
            "requested": plan_critic_requested,
            "verdict": plan_critic_audit.get("verdict"),
            "additions": list(plan_critic_audit.get("additions", [])),
            "parse_error": bool(plan_critic_audit.get("parse_error")),
            "raw_chars": len(plan_critic_raw),
            "attempt_errors": list(plan_critic_errors),
            "initial_plan_words": len(coverage_plan_initial.split()),
            "merged_plan_words": coverage_plan_merged_words,
        }
        trajectory.trace["summary"]["observable_scout"] = {
            "enabled": observable_scout,
            "requested": observable_scout_requested,
            "verdict": observable_scout_audit.get("verdict"),
            "additions": list(observable_scout_audit.get("additions", [])),
            "parse_error": bool(observable_scout_audit.get("parse_error")),
            "raw_chars": len(observable_scout_raw),
            "attempt_errors": list(observable_scout_errors),
            "combined_additions": len(obligation_audit.get("additions", [])),
        }
        trajectory.trace["summary"]["plan_reconcile"] = {
            "enabled": plan_reconcile,
            "requested": plan_reconcile_requested,
            "applied": plan_reconcile_applied,
            "raw_chars": len(plan_reconcile_raw),
            "attempt_errors": list(plan_reconcile_errors),
            "missing_must_mentions": list(plan_reconcile_missing_mentions),
            "final_plan_words": len(coverage_plan_text.split()),
        }
        trajectory.trace["summary"]["coverage_verify"] = {
            "enabled": coverage_verify,
            "repair_strategy": coverage_repair_strategy,
            "checked": coverage_verify_checked,
            "requested": coverage_verify_requested,
            "verdict": coverage_verify_audit.get("verdict"),
            "missing": list(coverage_verify_audit.get("missing", [])),
            "parse_error": bool(coverage_verify_audit.get("parse_error")),
            "raw_chars": len(coverage_verify_raw),
            "attempt_errors": list(coverage_verify_errors),
            "patch_requested": coverage_patch_requested,
            "patch_raw_chars": len(coverage_patch_raw),
            "patch_packet_chars": coverage_patch_packet_chars,
            "patches": dict(coverage_patch_stats),
            "patch_errors": list(coverage_patch_errors),
            "repair_search_batches": coverage_repair_search_batches,
            "repair_search_batch_cap": MAX_COVERAGE_REPAIR_SEARCH_BATCHES,
            "research_repair_active": coverage_repair_active,
            "research_repair_original_words": coverage_repair_original_words,
            "research_repair_fallback": coverage_repair_fallback,
        }
        trajectory.trace["summary"]["audience_verify"] = {
            "enabled": audience_verify,
            "checked": audience_verify_checked,
            "requested": audience_verify_requested,
            "verdict": audience_verify_audit.get("verdict"),
            "missing": list(audience_verify_audit.get("missing", [])),
            "parse_error": bool(audience_verify_audit.get("parse_error")),
            "raw_chars": len(audience_verify_raw),
            "attempt_errors": list(audience_verify_errors),
            "patch_requested": audience_patch_requested,
            "patch_raw_chars": len(audience_patch_raw),
            "patch_packet_chars": audience_patch_packet_chars,
            "patches": dict(audience_patch_stats),
            "patch_errors": list(audience_patch_errors),
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
            save_run("aus_agent_v2", query,
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
                                 peak_context_tokens=peak_context_tokens,
                                 provider=provider))
        return turn

    def fresh_auxiliary_turn(
        system: str,
        request: str,
        *,
        kind: str,
        max_attempts: int = 2,
        error_sink: list[str] | None = None,
    ) -> tuple[Provider, dict[str, Any], list[str]]:
        """Run a small isolated stage, retrying one transient gateway failure.

        Fresh stages intentionally do not inherit the research conversation.
        A failed attempt also cannot poison the retry because every attempt
        gets a new provider instance.  Successful turns are recorded in the
        same trajectory timeline, while callers decide where their raw message
        packet belongs relative to phase boundaries.
        """
        nonlocal turn_idx
        errors = error_sink if error_sink is not None else []
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            auxiliary = make_provider(backend, model)
            try:
                auxiliary.start(system, [])
                auxiliary.add_user_message(request)
                auxiliary_turn_index = turn_idx + 1
                t0 = now_iso()
                started = perf_counter()
                turn = auxiliary.run_turn()
                turn_idx = auxiliary_turn_index
                duration_ms = round((perf_counter() - started) * 1000, 3)
                t1 = now_iso()
                auxiliary_context, _ = _usage_tokens(turn.get("usage") or {})
                stats = _turn_stats(
                    turn.get("usage") or {},
                    duration_ms,
                    auxiliary_context or 0,
                    context_budget_tokens=context_token_budget,
                    elapsed_ms=_elapsed_ms(run_started_perf),
                    peak_context_tokens=auxiliary_context or 0,
                    provider=auxiliary,
                )
                _record_turn(
                    tb,
                    turn,
                    narration_as_reasoning=False,
                    model_input={
                        "kind": kind,
                        "text": request,
                        "attempt": attempt,
                    },
                    t_start=t0,
                    t_end=t1,
                    turn_index=auxiliary_turn_index,
                    stats=stats,
                    context=_context_snapshot(ledger),
                )
                return auxiliary, turn, errors
            except Exception as exc:
                last_error = exc
                message = f"attempt {attempt}: {type(exc).__name__}: {exc}"
                errors.append(message)
                log.warning(
                    "[%s] %s failed (%d/%d): %s",
                    query_id, kind, attempt, max_attempts, exc,
                )
        assert last_error is not None
        raise last_error

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
        nonlocal coverage_commit_batch_failures
        ct0 = now_iso()
        started = perf_counter()
        decision = expire_staged(
            ledger,
            max_documents=max_committed_per_step,
            reason=docid_reason,
        )
        coverage_commit_batch_failures = 0
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

    def finish_feedback(draft: str | None) -> str | None:
        """Return the one citation-local review packet this run may receive."""
        nonlocal finish_review_checked, finish_review_stats
        nonlocal finish_review_original_text
        if not finish_review or finish_review_checked or not draft:
            return None
        finish_review_checked = True
        built = build_finish_review_packet(
            query, draft, committed_documents, fact_ledger,
            coverage_plan=coverage_plan_text)
        if built is None:
            return None
        packet, stats = built
        finish_review_original_text = draft
        finish_review_stats = stats
        return packet

    def coverage_patch_draft(draft: str | None) -> str | None:
        """Audit once, then patch locally or reopen one bounded research turn."""
        nonlocal coverage_verify_checked, coverage_verify_requested
        nonlocal coverage_verify_audit, coverage_verify_raw
        nonlocal coverage_verify_errors
        nonlocal coverage_patch_requested, coverage_patch_raw
        nonlocal coverage_patch_errors, coverage_patch_stats
        nonlocal coverage_patch_packet_chars
        nonlocal coverage_repair_active
        if (not coverage_verify or not coverage_plan_text
                or coverage_verify_checked or not draft):
            return draft
        coverage_verify_checked = True
        request = coverage_verify_request(query, coverage_plan_text, draft)
        try:
            verifier, verify_turn, coverage_verify_errors = (
                fresh_auxiliary_turn(
                    COVERAGE_VERIFY_SYSTEM,
                    request,
                    kind="fresh_coverage_verify",
                    error_sink=coverage_verify_errors,
                )
            )
            coverage_verify_requested = True
            coverage_verify_raw = str(verify_turn.get("text") or "")
            coverage_verify_audit = normalize_coverage_audit(
                verify_turn.get("text"))
            auxiliary_raw_messages.extend([
                {
                    "type": "phase_boundary",
                    "phase": "draft_to_fresh_coverage_verifier",
                    "note": "auxiliary context diagnoses omissions only",
                },
                *list(verifier.raw_messages),
                {
                    "type": "phase_boundary",
                    "phase": "coverage_verifier_to_claim_patcher",
                    "note": "fresh patcher receives citation-local evidence",
                },
            ])
        except Exception as exc:
            coverage_verify_audit = {
                "verdict": "pass",
                "missing": [],
                "parse_error": True,
            }
            coverage_verify_raw = f"verifier failed: {type(exc).__name__}: {exc}"
            log.warning(
                "[%s] coverage verifier failed; retaining valid draft: %s",
                query_id, exc,
            )
            return draft

        log.info(
            "[%s] coverage verifier verdict=%s gaps=%d",
            query_id,
            coverage_verify_audit["verdict"],
            len(coverage_verify_audit["missing"]),
        )
        if coverage_verify_audit["verdict"] != "repair":
            return draft

        def request_research_repair() -> None:
            """Return gaps to the evidence-owning context when local evidence fails."""
            nonlocal coverage_repair_active
            coverage_repair_active = True
            feedback = coverage_repair_request(
                coverage_verify_audit, coverage_plan_text)
            provider.add_user_message(feedback)
            log.info(
                "[%s] claim completion had no grounded patch; reopening one "
                "bounded coverage-repair search batch",
                query_id,
            )

        if coverage_repair_strategy == "research-first":
            request_research_repair()
            return None

        built = build_claim_finish_packet(
            query, draft, coverage_verify_audit, committed_documents)
        if built is None:
            request_research_repair()
            return None
        packet, allowed = built
        coverage_patch_packet_chars = len(packet)
        try:
            patcher, patch_turn, coverage_patch_errors = fresh_auxiliary_turn(
                CLAIM_FINISH_SYSTEM,
                packet,
                kind="fresh_claim_patcher",
                error_sink=coverage_patch_errors,
            )
            coverage_patch_requested = True
            coverage_patch_raw = str(patch_turn.get("text") or "")
            patched, coverage_patch_stats, apply_errors = apply_claim_patches(
                draft, patch_turn.get("text"), allowed)
            coverage_patch_errors.extend(apply_errors)
            auxiliary_raw_messages.extend(list(patcher.raw_messages))
            log.info(
                "[%s] claim completion patcher: %d/%d accepted",
                query_id,
                coverage_patch_stats["accepted"],
                coverage_patch_stats["proposed"],
            )
            if coverage_patch_stats["accepted"] == 0:
                request_research_repair()
                return None
            return patched
        except Exception as exc:
            coverage_patch_raw = (
                f"claim patcher failed: {type(exc).__name__}: {exc}")
            log.warning(
                "[%s] claim patcher failed; requesting bounded research "
                "repair: %s",
                query_id, exc,
            )
            request_research_repair()
            return None

    def audience_patch_draft(draft: str | None) -> str | None:
        """Insert compact grounded additions without rewriting any draft line."""
        nonlocal audience_verify_checked, audience_verify_requested
        nonlocal audience_verify_audit, audience_verify_raw
        nonlocal audience_verify_errors, audience_patch_requested
        nonlocal audience_patch_raw, audience_patch_errors
        nonlocal audience_patch_stats, audience_patch_packet_chars
        if not audience_verify or audience_verify_checked or not draft:
            return draft
        audience_verify_checked = True
        request = audience_verify_request(query, draft)
        try:
            verifier, verify_turn, audience_verify_errors = fresh_auxiliary_turn(
                AUDIENCE_VERIFY_SYSTEM,
                request,
                kind="fresh_audience_verify",
                error_sink=audience_verify_errors,
            )
            audience_verify_requested = True
            audience_verify_raw = str(verify_turn.get("text") or "")
            audience_verify_audit = normalize_audience_audit(
                verify_turn.get("text"))
            auxiliary_raw_messages.extend([
                {
                    "type": "phase_boundary",
                    "phase": "accepted_draft_to_audience_verifier",
                    "note": "request and draft only; no planning anchor",
                },
                *list(verifier.raw_messages),
            ])
        except Exception as exc:
            audience_verify_audit = {
                "verdict": "pass", "missing": [], "parse_error": True}
            audience_verify_raw = (
                f"audience verifier failed: {type(exc).__name__}: {exc}")
            log.warning(
                "[%s] audience verifier failed; retaining accepted draft: %s",
                query_id, exc,
            )
            return draft

        if audience_verify_audit["verdict"] != "repair":
            return draft
        built = build_audience_patch_packet(
            query, draft, audience_verify_audit, committed_documents)
        if built is None:
            return draft
        packet, allowed = built
        audience_patch_packet_chars = len(packet)
        try:
            patcher, patch_turn, audience_patch_errors = fresh_auxiliary_turn(
                AUDIENCE_PATCH_SYSTEM,
                packet,
                kind="fresh_audience_patcher",
                error_sink=audience_patch_errors,
            )
            audience_patch_requested = True
            audience_patch_raw = str(patch_turn.get("text") or "")
            patched, audience_patch_stats, apply_errors = (
                apply_audience_insertions(
                    draft, patch_turn.get("text"), allowed)
            )
            audience_patch_errors.extend(apply_errors)
            auxiliary_raw_messages.extend([
                {
                    "type": "phase_boundary",
                    "phase": "audience_verifier_to_insertion_patcher",
                    "note": "patcher can insert but cannot rewrite draft lines",
                },
                *list(patcher.raw_messages),
            ])
            log.info(
                "[%s] audience insertion patcher: %d/%d accepted",
                query_id,
                audience_patch_stats["accepted"],
                audience_patch_stats["proposed"],
            )
            return patched
        except Exception as exc:
            audience_patch_raw = (
                f"audience patcher failed: {type(exc).__name__}: {exc}")
            log.warning(
                "[%s] audience patcher failed; retaining accepted draft: %s",
                query_id, exc,
            )
            return draft

    def start_finish_review(packet: str) -> None:
        """Replace research history with a non-destructive evidence patcher."""
        nonlocal finish_review_requested, finish_review_packet
        nonlocal finish_review_writer_started
        archived_raw_messages.extend(list(provider.raw_messages))
        archived_raw_messages.append({
            "type": "phase_boundary",
            "phase": "research_to_evidence_patcher",
            "note": "fresh evidence-patcher context starts after this item",
        })
        finish_review_packet = packet
        provider.start(FINISH_REVIEW_SYSTEM, [])
        provider.add_user_message(packet)
        finish_review_writer_started = True
        finish_review_requested = True

    def protect_finish_coverage(
        candidate: list[dict[str, Any]],
        notes: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Reject a revision that recreates cite-or-cut by shrinking coverage."""
        nonlocal finish_review_revision_words, finish_review_fallback
        nonlocal coverage_repair_fallback
        if coverage_repair_original is not None:
            repaired_words = _word_count(candidate)
            if (coverage_repair_original_words <= MAX_REPORT_WORDS
                    and repaired_words < 0.85 * coverage_repair_original_words):
                coverage_repair_fallback = True
                log.warning(
                    "[%s] coverage research repair removed too much coverage "
                    "(%d -> %d words); retaining the first valid draft",
                    query_id, coverage_repair_original_words, repaired_words,
                )
                return (coverage_repair_original,
                        coverage_repair_original_notes)
        if not finish_review_requested or finish_review_original is None:
            return candidate, notes
        finish_review_revision_words = _word_count(candidate)
        if (finish_review_original_words <= MAX_REPORT_WORDS
                and finish_review_revision_words
                < 0.85 * finish_review_original_words):
            finish_review_fallback = True
            log.warning(
                "[%s] finish review removed too much coverage (%d -> %d "
                "words); retaining the valid research draft",
                query_id, finish_review_original_words,
                finish_review_revision_words,
            )
            return finish_review_original, finish_review_original_notes
        return candidate, notes

    try:
        system_prompt = load_system_prompt(max_committed_per_step,
                                            prompt_variant)
        if coverage_contract:
            system_prompt += (
                "\n\n" + render_terminal_system_addendum(answer_form_policy)
            )
            if terminal_evidence_handoff:
                system_prompt += (
                    "\n\nThe first otherwise-valid submit_answer call opens "
                    "a mandatory harness-owned terminal evidence handoff; its "
                    "draft is not evaluated. After reading that tool result, "
                    "call submit_answer once more with the complete answer."
                )
        search_tool_definition = build_search_tool_def(engines)
        if coverage_contract:
            search_tool_definition = search_tool_with_contract(
                search_tool_definition)
        tool_definitions = [
            search_tool_definition,
            # Fact cards are requested only for the evidence-to-answer arm.
            # The original system and the v2 control retain the unchanged
            # commit schema, keeping this a clean architectural intervention.
            (commit_tool_with_contract(
                allow_promotions=dynamic_contract_rows)
             if coverage_contract else
             commit_context_tool_with_facts()
             if answer_blueprint else COMMIT_CONTEXT_TOOL),
        ]
        if answer_blueprint:
            tool_definitions.append(PREPARE_ANSWER_TOOL)
        if coverage_contract:
            tool_definitions.append(submit_answer_tool(answer_form_policy))
        user_message = TASK_PROMPT.format(now=now_full(), query=query)
        if coverage_plan:
            coverage_plan_system = (
                ATOMIC_PLAN_SYSTEM
                if atomic_contract_plan else COVERAGE_PLAN_SYSTEM
            )
            provider.start(coverage_plan_system, [])
            planner_request = (
                atomic_plan_request(query)
                if atomic_contract_plan else coverage_plan_request(query)
            )
            provider.add_user_message(planner_request)
            save_partial(force=True)
            plan_turn = timed_turn()
            plan_t0, plan_t1, plan_ti, _, plan_stats = last_turn
            _record_turn(
                tb,
                plan_turn,
                narration_as_reasoning=False,
                model_input={"kind": "coverage_plan_request",
                             "text": planner_request},
                t_start=plan_t0,
                t_end=plan_t1,
                turn_index=plan_ti,
                stats=plan_stats,
                context=_context_snapshot(ledger),
            )
            coverage_plan_requested = True
            if atomic_contract_plan:
                atomic_plan_rows = normalize_atomic_plan(
                    plan_turn.get("text"))
                if not atomic_plan_rows:
                    raise RuntimeError(
                        "atomic coverage planner returned no valid complete "
                        "10-24 row inventory")
                rendered_rows: list[str] = []
                for index, row in enumerate(atomic_plan_rows, 1):
                    label = (
                        "PENALTY" if row["mode"] == "avoid"
                        else str(row["kind"]).upper()
                    )
                    line = f"{index}. {label}: {row['requirement']}"
                    literals = (
                        row.get("must_avoid", [])
                        if row["mode"] == "avoid"
                        else row.get("must_mention", [])
                    )
                    if literals:
                        line += " EXACT: " + "; ".join(literals)
                    if row.get("minimum_count", 1) > 1:
                        line += f" MINIMUM: {row['minimum_count']}"
                    rendered_rows.append(line + ".")
                coverage_plan_initial = "\n".join(rendered_rows)
            else:
                coverage_plan_initial = normalize_coverage_plan(
                    plan_turn.get("text"))
            coverage_plan_text = coverage_plan_initial
            log.info(
                "[%s] coverage plan: %d words in fresh planning context",
                query_id, len(coverage_plan_text.split()),
            )
            archived_raw_messages.extend(list(provider.raw_messages))
            if plan_critic and coverage_plan_text:
                archived_raw_messages.append({
                    "type": "phase_boundary",
                    "phase": "coverage_plan_to_plan_critic",
                    "note": "independent context challenges plan omissions",
                })
                critic_request = plan_critic_request(query)
                try:
                    critic, critic_turn, plan_critic_errors = (
                        fresh_auxiliary_turn(
                            PLAN_CRITIC_SYSTEM,
                            critic_request,
                            kind="fresh_plan_critic",
                            error_sink=plan_critic_errors,
                        )
                    )
                    plan_critic_requested = True
                    plan_critic_raw = str(critic_turn.get("text") or "")
                    plan_critic_audit = normalize_plan_critique(
                        critic_turn.get("text"),
                        max_additions=plan_critic_max_additions)
                    coverage_plan_text = merge_plan_critique(
                        coverage_plan_text,
                        plan_critic_audit,
                        include_search_leads=not compact_scout_plan)
                    coverage_plan_merged_words = len(
                        coverage_plan_text.split())
                    archived_raw_messages.extend(list(critic.raw_messages))
                    log.info(
                        "[%s] plan critic verdict=%s additions=%d; "
                        "merged plan=%d words",
                        query_id,
                        plan_critic_audit["verdict"],
                        len(plan_critic_audit["additions"]),
                        len(coverage_plan_text.split()),
                    )
                except Exception as exc:
                    plan_critic_audit = {
                        "verdict": "pass",
                        "additions": [],
                        "parse_error": True,
                    }
                    plan_critic_raw = (
                        f"plan critic failed: {type(exc).__name__}: {exc}")
                    log.warning(
                        "[%s] plan critic failed; retaining initial plan: %s",
                        query_id, exc,
                    )
                obligation_audit = plan_critic_audit
                if observable_scout:
                    archived_raw_messages.append({
                        "type": "phase_boundary",
                        "phase": "plan_critic_to_observable_scout",
                        "note": (
                            "complementary context finds literal and countable "
                            "units the semantic inventory compressed"
                        ),
                    })
                    observable_request = observable_scout_request(
                        query, coverage_plan_initial, plan_critic_audit)
                    try:
                        observable_provider, observable_turn, (
                            observable_scout_errors
                        ) = fresh_auxiliary_turn(
                            OBSERVABLE_SCOUT_SYSTEM,
                            observable_request,
                            kind="fresh_observable_scout",
                            error_sink=observable_scout_errors,
                        )
                        observable_scout_requested = True
                        observable_scout_raw = str(
                            observable_turn.get("text") or "")
                        observable_scout_audit = normalize_observable_scout(
                            observable_turn.get("text"))
                        obligation_audit = combine_obligation_audits(
                            plan_critic_audit, observable_scout_audit)
                        archived_raw_messages.extend(
                            list(observable_provider.raw_messages))
                        log.info(
                            "[%s] observable scout verdict=%s additions=%d; "
                            "combined obligations=%d",
                            query_id,
                            observable_scout_audit["verdict"],
                            len(observable_scout_audit["additions"]),
                            len(obligation_audit["additions"]),
                        )
                    except Exception as exc:
                        observable_scout_audit = {
                            "verdict": "pass",
                            "additions": [],
                            "parse_error": True,
                        }
                        observable_scout_raw = (
                            "observable scout failed: "
                            f"{type(exc).__name__}: {exc}")
                        log.warning(
                            "[%s] observable scout failed; retaining semantic "
                            "inventory: %s", query_id, exc,
                        )
                coverage_plan_text = merge_plan_critique(
                    coverage_plan_initial,
                    obligation_audit,
                    include_search_leads=not compact_scout_plan)
                coverage_plan_merged_words = len(coverage_plan_text.split())
                if (plan_reconcile and obligation_audit.get("additions")
                        and coverage_plan_initial):
                    archived_raw_messages.append({
                        "type": "phase_boundary",
                        "phase": "plan_critic_to_plan_reconcile",
                        "note": "fresh context compiles competing priorities",
                    })
                    reconcile_request = plan_reconcile_request(
                        query, coverage_plan_initial, obligation_audit)
                    try:
                        reconciler, reconcile_turn, plan_reconcile_errors = (
                            fresh_auxiliary_turn(
                                PLAN_RECONCILE_SYSTEM,
                                reconcile_request,
                                kind="fresh_plan_reconcile",
                                error_sink=plan_reconcile_errors,
                            )
                        )
                        plan_reconcile_requested = True
                        plan_reconcile_raw = str(
                            reconcile_turn.get("text") or "")
                        compiled = normalize_reconciled_plan(
                            reconcile_turn.get("text"))
                        plan_reconcile_missing_mentions = (
                            missing_must_mentions(compiled, obligation_audit))
                        if (compiled is not None
                                and not plan_reconcile_missing_mentions):
                            coverage_plan_text = compiled
                            plan_reconcile_applied = True
                        else:
                            # The additive merge is intentionally broader than
                            # the answer budget. If arbitration fails, the
                            # compact primary plan is the safe handoff.
                            coverage_plan_text = coverage_plan_initial
                        archived_raw_messages.extend(
                            list(reconciler.raw_messages))
                        log.info(
                            "[%s] plan reconciler applied=%s; plan=%d words",
                            query_id,
                            plan_reconcile_applied,
                            len(coverage_plan_text.split()),
                        )
                    except Exception as exc:
                        coverage_plan_text = coverage_plan_initial
                        plan_reconcile_raw = (
                            f"plan reconciler failed: "
                            f"{type(exc).__name__}: {exc}")
                        log.warning(
                            "[%s] plan reconciler failed; retaining primary "
                            "plan: %s", query_id, exc,
                        )
                archived_raw_messages.append({
                    "type": "phase_boundary",
                    "phase": "plan_critic_to_research",
                    "note": (
                        "fresh research context receives reconciled priorities"
                        if plan_reconcile_applied else
                        "fresh research context receives compact primary plan"
                    ),
                })
            else:
                archived_raw_messages.append({
                    "type": "phase_boundary",
                    "phase": "coverage_plan_to_research",
                    "note": "fresh research context starts after this item",
                })
            if coverage_plan_text and not atomic_contract_plan:
                user_message += (
                    "\n\nPre-research coverage plan from an isolated planning "
                    "stage. Treat it as a checklist of evidence needs and "
                    "deliverable constraints, not as evidence. Honor its "
                    "answer-word budget: complete every repeated must-have "
                    "inside each planned part before spending words or search "
                    "turns on optional breadth. Once every must-have has usable "
                    "evidence, draft instead of searching exhaustively:\n\n"
                    + coverage_plan_text
                )
            if coverage_contract:
                if atomic_contract_plan:
                    coverage_contract_items = build_atomic_coverage_contract(
                        atomic_plan_rows,
                        list(obligation_audit.get("additions", [])),
                        answer_form=answer_form_policy,
                    )
                else:
                    coverage_contract_items = build_coverage_contract(
                        coverage_plan_text,
                        list(obligation_audit.get("additions", [])),
                        answer_form=answer_form_policy,
                    )
                if not coverage_contract_items:
                    raise RuntimeError(
                        "coverage plan produced no executable contract items")
                user_message += (
                    "\n\n"
                    + render_research_contract(
                        coverage_contract_items, answer_form_policy)
                )
        trace_input = {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "tools": tool_definitions,
        }
        if coverage_plan:
            trace_input.update({
                "coverage_plan_system": coverage_plan_system,
                "coverage_plan_initial": coverage_plan_initial or None,
                "coverage_plan": coverage_plan_text or None,
            })
            if atomic_contract_plan:
                trace_input["atomic_plan_rows"] = list(atomic_plan_rows)
        if plan_critic and coverage_plan:
            trace_input.update({
                "plan_critic_system": PLAN_CRITIC_SYSTEM,
                "plan_critic": plan_critic_audit,
            })
        if observable_scout and plan_critic and coverage_plan:
            trace_input.update({
                "observable_scout_system": OBSERVABLE_SCOUT_SYSTEM,
                "observable_scout": observable_scout_audit,
                "obligation_inventory": obligation_audit,
            })
        if plan_reconcile and coverage_plan:
            trace_input["plan_reconcile_system"] = PLAN_RECONCILE_SYSTEM
        if coverage_contract:
            trace_input["coverage_contract"] = contract_trace(
                coverage_contract_items, coverage_evidence)
            trace_input["answer_form"] = answer_form_policy.trace()
        if coverage_verify:
            trace_input["coverage_verify_system"] = COVERAGE_VERIFY_SYSTEM
            trace_input["claim_finish_system"] = CLAIM_FINISH_SYSTEM
        if audience_verify:
            trace_input["audience_verify_system"] = AUDIENCE_VERIFY_SYSTEM
            trace_input["audience_patch_system"] = AUDIENCE_PATCH_SYSTEM
        tb.set_trace_input(trace_input)
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
            correcting_contract_commit = (
                coverage_contract and coverage_commit_batch_failures > 0)

            # A staged batch normally exists for exactly this turn, and exactly
            # one commit_context resolves it. The contract-only correction state
            # is the narrow exception: the same batch remains open after a
            # support-annotation error. Position does not matter: commit_calls
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
                    if coverage_contract:
                        feedback = submit_answer_request(
                            coverage_contract_items, coverage_evidence)
                        provider.add_user_message(feedback)
                        next_model_input = {
                            "kind": "submit_answer_request",
                            "text": feedback,
                        }
                        continue
                    if answer_blueprint and not answer_blueprint_prepared:
                        answer_blueprint_requests += 1
                        feedback = answer_blueprint_request(coverage_plan_text)
                        provider.add_user_message(feedback)
                        next_model_input = {
                            "kind": "answer_blueprint_request",
                            "text": feedback,
                        }
                        continue
                    candidate, _, notes = _parse_final_prose(
                        turn.get("text"), set(ledger.committed_ids),
                        allow_uncited=(
                            finishing
                            or uncited_refusals >= MAX_UNCITED_REFUSALS))
                    if candidate is not None:
                        original_text = turn.get("text")
                        accepted_text = coverage_patch_draft(original_text)
                        if accepted_text is None:
                            coverage_repair_original = candidate
                            coverage_repair_original_notes = notes
                            coverage_repair_original_words = _word_count(candidate)
                            next_model_input = {
                                "kind": "coverage_repair_request",
                                "ref": "verifier findings replayed to research",
                            }
                            continue
                        if accepted_text != original_text:
                            patched_candidate, _, patched_notes = (
                                _parse_final_prose(
                                    accepted_text,
                                    set(ledger.committed_ids),
                                    allow_uncited=(
                                        finishing or uncited_refusals
                                        >= MAX_UNCITED_REFUSALS),
                                )
                            )
                            if patched_candidate is not None:
                                candidate = patched_candidate
                                notes = patched_notes
                            else:
                                accepted_text = original_text
                                coverage_patch_errors.append(
                                    "patched draft failed final prose validation")
                        audience_text = audience_patch_draft(accepted_text)
                        if audience_text != accepted_text:
                            patched_candidate, _, patched_notes = (
                                _parse_final_prose(
                                    audience_text,
                                    set(ledger.committed_ids),
                                    allow_uncited=(
                                        finishing or uncited_refusals
                                        >= MAX_UNCITED_REFUSALS),
                                )
                            )
                            if patched_candidate is not None:
                                candidate = patched_candidate
                                notes = patched_notes
                                accepted_text = audience_text
                            else:
                                audience_patch_errors.append(
                                    "patched draft failed final prose validation")
                        review = finish_feedback(accepted_text)
                        if review is not None:
                            log.info(
                                "[%s] evidence-aware finish review requested",
                                query_id,
                            )
                            finish_review_original = candidate
                            finish_review_original_notes = notes
                            finish_review_original_words = _word_count(candidate)
                            start_finish_review(review)
                            next_model_input = {
                                "kind": "fresh_evidence_patcher",
                                "ref": "research draft + citation-local evidence",
                            }
                            continue
                        candidate, notes = protect_finish_coverage(
                            candidate, notes)
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

            if not calls and _coverage_audit_enabled() and not audit_done:
                # Fires once, on the first report attempt only: a second
                # interruption would just cost turns on an agent that has
                # already been asked.
                audit_done = True
                log.info("[%s] coverage audit requested before report", query_id)
                provider.add_user_message(COVERAGE_AUDIT)
                rounds += 1
                continue

            if not calls:
                report_text = turn.get("text")
                if coverage_contract:
                    feedback = submit_answer_request(
                        coverage_contract_items, coverage_evidence)
                    provider.add_user_message(feedback)
                    next_model_input = {
                        "kind": "submit_answer_request",
                        "text": feedback,
                    }
                    continue
                if answer_blueprint and not answer_blueprint_prepared:
                    answer_blueprint_requests += 1
                    feedback = answer_blueprint_request(coverage_plan_text)
                    provider.add_user_message(feedback)
                    next_model_input = {
                        "kind": "answer_blueprint_request",
                        "text": feedback,
                    }
                    continue
                if (finish_review_requested and finish_review_writer_started
                        and finish_review_original is not None):
                    patched, patch_stats, patch_errors = apply_evidence_patches(
                        finish_review_original_text,
                        report_text,
                        finish_review_packet,
                        max_words=MAX_REPORT_WORDS,
                    )
                    finish_review_patch_stats = patch_stats
                    finish_review_patch_errors = patch_errors
                    finish_review_revision_words = len(patched.split())
                    report_text = patched
                    log.info(
                        "[%s] evidence patcher: %d/%d patches accepted",
                        query_id, patch_stats["accepted"],
                        patch_stats["proposed"],
                    )
                candidate, validation_errors, notes = _parse_final_prose(
                    report_text, set(ledger.committed_ids),
                    allow_uncited=(
                        finishing or uncited_refusals >= MAX_UNCITED_REFUSALS))
                if candidate is not None:
                    accepted_text = coverage_patch_draft(report_text)
                    if accepted_text is None:
                        coverage_repair_original = candidate
                        coverage_repair_original_notes = notes
                        coverage_repair_original_words = _word_count(candidate)
                        next_model_input = {
                            "kind": "coverage_repair_request",
                            "ref": "verifier findings replayed to research",
                        }
                        continue
                    if accepted_text != report_text:
                        patched_candidate, _, patched_notes = _parse_final_prose(
                            accepted_text,
                            set(ledger.committed_ids),
                            allow_uncited=(
                                finishing
                                or uncited_refusals >= MAX_UNCITED_REFUSALS),
                        )
                        if patched_candidate is not None:
                            candidate = patched_candidate
                            notes = patched_notes
                            report_text = accepted_text
                        else:
                            accepted_text = report_text
                            coverage_patch_errors.append(
                                "patched draft failed final prose validation")
                    audience_text = audience_patch_draft(accepted_text)
                    if audience_text != accepted_text:
                        patched_candidate, _, patched_notes = _parse_final_prose(
                            audience_text,
                            set(ledger.committed_ids),
                            allow_uncited=(
                                finishing
                                or uncited_refusals >= MAX_UNCITED_REFUSALS),
                        )
                        if patched_candidate is not None:
                            candidate = patched_candidate
                            notes = patched_notes
                            report_text = audience_text
                            accepted_text = audience_text
                        else:
                            audience_patch_errors.append(
                                "patched draft failed final prose validation")
                    review = finish_feedback(accepted_text)
                    if review is not None:
                        log.info(
                            "[%s] evidence-aware finish review requested",
                            query_id,
                        )
                        finish_review_original = candidate
                        finish_review_original_notes = notes
                        finish_review_original_words = _word_count(candidate)
                        start_finish_review(review)
                        next_model_input = {
                            "kind": "fresh_evidence_patcher",
                            "ref": "research draft + citation-local evidence",
                        }
                        continue
                    candidate, notes = protect_finish_coverage(candidate, notes)
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
                ct0 = now_iso()
                started = perf_counter()
                pending_before = list(ledger.pending)
                committed_before = set(ledger.committed_ids)
                rejected_before = set(ledger.rejected_ids)
                retry_preserved = False
                promoted_items = []
                try:
                    contract_supports = {}
                    if coverage_contract:
                        contract_supports, support_errors = (
                            normalize_commit_supports(
                                call["arguments"], coverage_contract_items)
                        )
                        if dynamic_contract_rows:
                            selected_ids: list[str] = []
                            for raw_document in call["arguments"].get(
                                    "documents", []):
                                if not isinstance(raw_document, dict):
                                    continue
                                document_id = str(
                                    raw_document.get("id") or "").strip()
                                if (document_id
                                        and document_id not in selected_ids
                                        and document_id not in
                                        ledger.committed_ids):
                                    selected_ids.append(document_id)
                            eligible_ids = set(
                                selected_ids[:max_committed_per_step])
                            promoted_items, promoted_supports, promotion_errors = (
                                normalize_commit_promotions(
                                    call["arguments"],
                                    coverage_contract_items,
                                    eligible_document_ids=eligible_ids,
                                )
                            )
                            support_errors.extend(promotion_errors)
                            for requirement_id, anchors in (
                                    promoted_supports.items()):
                                contract_supports.setdefault(
                                    requirement_id, []).extend(anchors)
                        support_errors.extend(validate_support_routes(
                            contract_supports,
                            [
                                document
                                for pending in ledger.pending
                                for document in pending.documents
                            ],
                        ))
                        if support_errors:
                            raise _CoverageSupportValidationError(
                                "; ".join(support_errors))
                    handled = apply_commit(
                        ledger,
                        call["arguments"],
                        max_documents=max_committed_per_step,
                        finishing=finishing,
                    )
                    decision = handled.decision
                except Exception as e:
                    ledger.pending = pending_before
                    ledger.committed_ids = committed_before
                    ledger.rejected_ids = rejected_before
                    if not isinstance(e, ValueError):
                        # Provider/history failures and implementation defects
                        # are not model-correctable. Continuing would hide the
                        # defect, discard evidence, and leave the conversation
                        # in an unproved state.
                        raise
                    recoverable = isinstance(
                        e, _CoverageSupportValidationError)
                    if recoverable:
                        coverage_commit_batch_failures += 1
                        coverage_commit_validation_errors.append(
                            f"{type(e).__name__}: {e}")
                    turns_remaining = hard_round_cap - rounds
                    if (recoverable and coverage_commit_batch_failures
                            <= MAX_COVERAGE_COMMIT_CORRECTIONS
                            and turns_remaining >= 2):
                        retry_preserved = True
                        coverage_commit_corrections += 1
                        remaining = min(
                            MAX_COVERAGE_COMMIT_CORRECTIONS
                            - coverage_commit_batch_failures,
                            max(0, turns_remaining - 2),
                        )
                        commit_payload = {
                            "error": f"{type(e).__name__}: {e}",
                            "committed": [],
                            "rejected": [],
                            "staged": list(ledger.staged_ids),
                            "instruction": (
                                "The staged evidence remains available. On the "
                                "next turn, issue exactly one corrected "
                                "commit_context call and no other action. "
                                f"{remaining} further correction attempt(s) "
                                "remain after that turn."
                            ),
                        }
                        context = _context_snapshot(ledger)
                        documents = []
                    else:
                        if recoverable:
                            coverage_commit_expirations += 1
                        decision = expire_staged(
                            ledger,
                            max_documents=max_committed_per_step,
                            reason=(
                                "staged batch expired after invalid "
                                f"commit_context: {type(e).__name__}: {e}"
                            ),
                        )
                        coverage_commit_batch_failures = 0
                        provider.compact_tool_results(decision.replacements)
                        commit_payload = {
                            "error": f"{type(e).__name__}: {e}",
                            "committed": [],
                            "rejected": decision.rejected,
                            "instruction": (
                                "The staged batch was compacted and cannot be "
                                "reselected; search again if the evidence is "
                                "still needed."
                            ),
                        }
                        context = decision.context
                        documents = []
                    out = json.dumps(commit_payload, ensure_ascii=False)
                    failed = True
                else:
                    try:
                        provider.compact_tool_results(decision.replacements)
                    except Exception:
                        # Provider-history compaction is atomic with the ledger
                        # update. A backend failure ends the run rather than
                        # carrying inconsistent context into another turn.
                        ledger.pending = pending_before
                        ledger.committed_ids = committed_before
                        ledger.rejected_ids = rejected_before
                        raise
                    coverage_commit_batch_failures = 0
                    out = json.dumps(handled.payload, ensure_ascii=False)
                    failed = False
                    context = decision.context
                    documents = decision.documents
                    committed_documents.update({
                        str(document["id"]): dict(document)
                        for document in documents
                    })
                    if coverage_contract:
                        committed_now = set(decision.committed)
                        retained_promotions = [
                            item for item in promoted_items
                            if any(
                                anchor.document_id in committed_now
                                for anchor in contract_supports.get(item.id, [])
                            )
                        ]
                        coverage_contract_items.extend(retained_promotions)
                        coverage_dynamic_promotions += len(retained_promotions)
                        coverage_evidence.record_supports({
                            requirement_id: [
                                anchor for anchor in anchors
                                if anchor.document_id in committed_now
                            ]
                            for requirement_id, anchors in contract_supports.items()
                            if any(anchor.document_id in committed_now
                                   for anchor in anchors)
                        })
                    facts_added = capture_committed_facts(
                        call["arguments"], decision.committed, fact_ledger)
                    if facts_added:
                        log.info(
                            "[%s] commit_context: captured %d fact cards "
                            "(%d cumulative)",
                            query_id,
                            facts_added,
                            sum(len(facts) for facts in fact_ledger.values()),
                        )
                    if coverage_contract:
                        commit_payload = json.loads(out)
                        if retained_promotions:
                            commit_payload["promoted_requirements"] = [
                                {
                                    "id": item.id,
                                    "kind": item.kind,
                                    "requirement": item.requirement,
                                    "must_mention": list(item.must_mention),
                                    "minimum_count": item.minimum_count,
                                }
                                for item in retained_promotions
                            ]
                        commit_payload["coverage_contract_status"] = (
                            render_contract_status(
                                coverage_contract_items, coverage_evidence)
                        )
                        out = json.dumps(commit_payload, ensure_ascii=False)
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
                    log.warning(
                        "[%s] commit_context FAILED (batch %s)",
                        query_id,
                        "preserved for correction"
                        if retry_preserved else "expired",
                    )
                else:
                    log.info("[%s] commit_context: %d committed, %d rejected "
                             "(%d total)", query_id, len(documents),
                             len(decision.rejected),
                             len(ledger.committed_ids))
                if failed:
                    # A correction owns the next turn while the full staged
                    # result remains visible. Other same-turn actions would
                    # either mix a second batch into it or try to answer before
                    # the evidence decision is settled, so refuse them in both
                    # the retry and expiry cases.
                    ts = now_iso()
                    for other in calls:
                        if other["id"] == call["id"]:
                            continue
                        blocked, blocked_stats = action_feedback(json.dumps({
                            "error": (
                                "commit_context failed and the staged batch "
                                + (
                                    "remains open for a corrected commit; "
                                    if retry_preserved else
                                    "expired; "
                                )
                                + "same-turn actions refused"
                            )
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
                if correcting_contract_commit and len(calls) > 1:
                    # A successful corrected commit settles the retained batch,
                    # but the correction turn has no second purpose. Refuse
                    # parallel searches/submission so the model cannot smuggle
                    # a new staged batch through a turn whose feedback required
                    # exactly one corrected commit_context call.
                    ts = now_iso()
                    for other in calls:
                        if other["id"] == call["id"]:
                            continue
                        blocked, blocked_stats = action_feedback(json.dumps({
                            "error": (
                                "action refused because a commit_context "
                                "correction must be the only action in its turn"
                            )
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
                        [result_by_id[item["id"]] for item in calls])
                    next_model_input = {
                        "kind": "tool_results",
                        "tool_call_ids": [item["id"] for item in calls],
                    }
                    continue

            submit_calls = [
                call for call in calls if call["name"] == "submit_answer"]
            if submit_calls:
                coverage_submission_attempts += len(submit_calls)
                concurrent = [
                    call for call in calls
                    if call["name"] != "submit_answer"
                    and call["id"] not in noop_commit_ids
                ]
                submission_errors: list[str] = []
                submitted: list[dict[str, Any]] | None = None
                opened_handoff = False
                if not coverage_contract:
                    submission_errors.append(
                        "submit_answer is unavailable in this architecture")
                if len(submit_calls) != 1:
                    submission_errors.append(
                        "exactly one submit_answer call is allowed per turn")
                if ledger.has_staged:
                    submission_errors.append(
                        "resolve the staged evidence batch before submission")
                if concurrent:
                    submission_errors.append(
                        "submit_answer cannot share a turn with other actions")
                if (not submission_errors
                        and terminal_evidence_handoff
                        and not coverage_terminal_handoff_sent):
                    handoff = render_terminal_evidence_handoff(
                        coverage_contract_items, coverage_evidence)
                    coverage_terminal_handoff_sent = True
                    coverage_terminal_handoff_chars = len(handoff)
                    opened_handoff = True
                elif not submission_errors:
                    submitted, submission_errors, coverage_submission_stats = (
                        validate_submission(
                            submit_calls[0]["arguments"],
                            coverage_contract_items,
                            coverage_evidence,
                            set(ledger.committed_ids),
                            answer_form=answer_form_policy,
                            max_words=MAX_REPORT_WORDS,
                        )
                    )
                coverage_submission_errors.extend(submission_errors)
                if opened_handoff:
                    payload = json.dumps({
                        "accepted": False,
                        "handoff_required": True,
                        "instruction": handoff,
                    }, ensure_ascii=False)
                    failed = False
                elif submitted is None:
                    payload = json.dumps({
                        "error": "invalid terminal answer submission",
                        "problems": submission_errors,
                        "instruction": (
                            "Fix every problem and call submit_answer again. "
                            "Do not emit free prose or other tool calls."
                        ),
                        "terminal_evidence_handoff": (
                            render_terminal_evidence_handoff(
                                coverage_contract_items, coverage_evidence)
                            if terminal_evidence_handoff else None
                        ),
                    }, ensure_ascii=False)
                    failed = True
                else:
                    payload = json.dumps({
                        "accepted": True,
                        "sentences": len(submitted),
                        "coverage": coverage_submission_stats,
                    }, ensure_ascii=False)
                    failed = False
                payload, feedback_stats = action_feedback(payload, 0.0)
                ts = now_iso()
                submit_ids = {call["id"] for call in submit_calls}
                for call in calls:
                    if (call["id"] in noop_commit_ids
                            or call["id"] in result_by_id):
                        continue
                    call_failed = failed or call["id"] not in submit_ids
                    call_payload = payload
                    if call["id"] not in submit_ids:
                        call_payload, _ = action_feedback(json.dumps({
                            "error": "action refused because submit_answer "
                                     "must be the only action in its turn"
                        }), 0.0)
                    tb.add_tool_call(
                        call["name"], call["arguments"], call_payload,
                        failed=call_failed, t_start=ts, t_end=ts, turn=ti,
                        stats=feedback_stats,
                        context=_context_snapshot(ledger), documents=[],
                        tool_call_id=call["id"],
                    )
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": call_payload,
                        "is_error": call_failed,
                    }
                provider.add_tool_results(
                    [result_by_id[call["id"]] for call in calls])
                if submitted is not None:
                    sentences = submitted
                    repairs = []
                    break
                next_model_input = {
                    "kind": "tool_results",
                    "tool_call_ids": [call["id"] for call in calls],
                }
                continue

            prepare_calls = [
                call for call in calls if call["name"] == "prepare_answer"]
            if prepare_calls:
                concurrent_retrieval = any(
                    call["name"] in {"search", "get_documents"}
                    for call in calls
                )
                for call in prepare_calls:
                    answer_blueprint_attempts += 1
                    bt0 = now_iso()
                    errors: list[str] = []
                    normalized: dict[str, Any] | None = None
                    if len(prepare_calls) != 1:
                        errors.append(
                            "exactly one prepare_answer call is allowed per turn")
                    if ledger.has_staged:
                        errors.append(
                            "resolve the staged evidence batch before preparing")
                    if concurrent_retrieval:
                        errors.append(
                            "prepare_answer cannot share a turn with retrieval")
                    if not errors:
                        normalized, errors = normalize_answer_blueprint(
                            call["arguments"], set(ledger.committed_ids))
                    if normalized is None:
                        answer_blueprint_errors.extend(errors)
                        payload = json.dumps({
                            "error": "invalid evidence-to-answer blueprint",
                            "problems": errors,
                            "instruction": (
                                "Call prepare_answer again after fixing every "
                                "problem; do not write the report first."
                            ),
                        }, ensure_ascii=False)
                        failed = True
                    else:
                        answer_blueprint_value = normalized
                        payload = build_answer_handoff(
                            query, coverage_plan_text, normalized, fact_ledger)
                        answer_handoff_chars = len(payload)
                        answer_blueprint_prepared = True
                        failed = False
                    bt1 = now_iso()
                    payload, feedback_stats = action_feedback(payload, 0.0)
                    tb.add_tool_call(
                        call["name"], call["arguments"], payload,
                        failed=failed, t_start=bt0, t_end=bt1, turn=ti,
                        stats=feedback_stats,
                        context=_context_snapshot(ledger), documents=[],
                        tool_call_id=call["id"],
                    )
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": payload,
                        "is_error": failed,
                    }

            retrieval_calls = [
                call for call in calls if call["name"] == "search"]
            repair_search_blocked = (
                coverage_repair_active
                and coverage_repair_search_batches
                >= MAX_COVERAGE_REPAIR_SEARCH_BATCHES
            )
            if retrieval_calls and (budget_hit or safety_hit
                                    or repair_search_blocked):
                blocked_reason = (
                    "coverage repair already used its one parallel search "
                    "batch; finish the repaired full report now from committed "
                    "evidence, stating a precise limitation for anything still "
                    "unavailable"
                    if repair_search_blocked else
                    "tool call not executed because the preceding generation "
                    "input context reached the research budget; write the final "
                    "report now using the contract already defined in the "
                    "system prompt"
                )
                budget_msg, budget_stats = action_feedback(json.dumps({
                    "error": blocked_reason,
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
                if coverage_repair_active:
                    coverage_repair_search_batches += 1
                executable_calls: list[dict[str, Any]] = []
                if coverage_contract:
                    ts = now_iso()
                    for call in retrieval_calls:
                        requirement_ids, requirement_errors = (
                            normalize_requirement_ids(
                                call["arguments"].get("for_requirements"),
                                coverage_contract_items,
                            )
                        )
                        if requirement_errors:
                            invalid, invalid_stats = action_feedback(json.dumps({
                                "error": "invalid search coverage routing",
                                "problems": requirement_errors,
                            }, ensure_ascii=False), 0.0)
                            tb.add_tool_call(
                                call["name"], call["arguments"], invalid,
                                failed=True, t_start=ts, t_end=ts, turn=ti,
                                stats=invalid_stats,
                                context=_context_snapshot(ledger), documents=[],
                                tool_call_id=call["id"],
                            )
                            result_by_id[call["id"]] = {
                                "id": call["id"], "content": invalid,
                                "is_error": True,
                            }
                            continue
                        coverage_evidence.record_search(
                            requirement_ids,
                            str(call["arguments"].get("query") or ""),
                        )
                        executable_calls.append(call)
                else:
                    executable_calls = retrieval_calls
                # Calls from one model turn execute concurrently. The builder
                # records their real overlapping bounds for the viewer.
                executed = _execute_tool_calls(
                    executable_calls, k=k, seen_docids=seen_docids,
                    engines=engines) if executable_calls else []
                for call, (
                    out, trace_output, returned, failed, documents,
                    ct0, ct1, duration_ms
                ) in zip(executable_calls, executed):
                    out, feedback_stats = action_feedback(out, duration_ms)
                    context = {
                        "staged": [
                            str(document["id"]) for document in documents],
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
                    log.info("[%s] search %r: %s", query_id,
                             call["arguments"].get("query", ""),
                             "FAILED" if failed
                             else f"{len(documents)} docs staged")
                    if not failed:
                        ledger.stage(
                            call["id"], call["name"], out, documents)
                        if answer_blueprint_prepared:
                            answer_blueprint_prepared = False
                            answer_blueprint_value = None
                            answer_blueprint_invalidations += 1
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
                        if answer_blueprint_prepared:
                            answer_blueprint_prepared = False
                            answer_blueprint_value = None
                            answer_blueprint_invalidations += 1
                    result_by_id[call["id"]] = {
                        "id": call["id"], "content": out, "is_error": failed}

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
    paths = save_run("aus_agent_v2", query, trajectory=trajectory, output=output,
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
