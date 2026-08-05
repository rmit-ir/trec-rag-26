"""Strict trajectory projection plus rich ``output.json.trace`` recording.

``trajectory.json`` must stay schema-compatible with:
``data/sample-files/run_InfoSeekQA_1000_20260625T230857966818Z.json``.

Timings, token usage, retrieved document IDs, and staged/committed context are
recorded separately in ``TrajectoryArtifact.trace``. ``save_run``
embeds that trace under the internal ``output.json`` artifact without leaking
viewer-only fields into ``trajectory.json``.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Melbourne")
TRACE_SCHEMA_VERSION = "trec-rag-trace/2"


def now_iso() -> str:
    """Melbourne-local ISO timestamp with ms precision and UTC offset."""
    return datetime.now(TZ).isoformat(timespec="milliseconds")


class TrajectoryArtifact(dict[str, Any]):
    """A strict trajectory dict carrying a non-serialized rich trace."""

    trace: dict[str, Any]

    def __init__(self, *args: Any, trace: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.trace = trace


class TrajectoryBuilder:
    def __init__(self, query_id: str, query: str,
                 metadata: dict[str, Any] | None = None) -> None:
        self.query_id = query_id
        self.metadata: dict[str, Any] = dict(metadata or {})
        self.metadata.setdefault("query_source", query)
        # Strict sample-compatible items.
        self.result: list[dict[str, Any]] = []
        # Rich steps embedded only in output.json.trace.
        self.trace_steps: list[dict[str, Any]] = []
        self._docids: set[str] = set()
        self._generation_ids: dict[int, str] = {}
        self._trace_input: Any = {"query": query}
        self._trace_output: Any = None

    def set_trace_input(self, value: Any) -> None:
        """Set the run-level input shown at the root of the rich trace."""
        self._trace_input = value

    def set_trace_output(self, value: Any) -> None:
        """Set the run-level output shown at the root of the rich trace."""
        self._trace_output = value

    def add_reasoning(
        self,
        text: str,
        *,
        t_start: str | None = None,
        t_end: str | None = None,
        turn: int | None = None,
        stats: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        parent_id: str | None = None,
        record_trace: bool = True,
    ) -> None:
        if not text:
            return
        strict = {
            "type": "reasoning",
            "tool_name": None,
            "arguments": None,
            "output": text,
        }
        self.result.append(strict)
        if record_trace:
            self.trace_steps.append(self._trace_step(
                strict, t_start=t_start, t_end=t_end, turn=turn, stats=stats,
                context=context, parent_id=parent_id))

    def add_model_step(
        self,
        output: Any = "",
        *,
        input: Any = None,
        t_start: str | None = None,
        t_end: str | None = None,
        turn: int | None = None,
        stats: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        parent_id: str | None = None,
        **extras: Any,
    ) -> str:
        """Add a rich-only model/generation span.

        Some providers return signature-only reasoning plus tool calls, leaving
        no textual reasoning item for model latency and token accounting. This
        method records that span in output.trace without adding anything to
        the strict trajectory result.
        """
        base: dict[str, Any] = {
            "type": "generation",
            "tool_name": None,
            "input": input,
            "output": output,
        }
        base.update(extras)
        step = self._trace_step(
            base, t_start=t_start, t_end=t_end, turn=turn, stats=stats,
            context=context, parent_id=parent_id)
        self.trace_steps.append(step)
        if turn is not None:
            self._generation_ids[turn] = step["id"]
        return str(step["id"])

    def add_tool_call(
        self,
        tool_name: str,
        arguments: Any,
        output: str,
        *,
        returned: list[dict[str, Any]] | None = None,
        returned_docids: list[str] | None = None,
        failed: bool = False,
        t_start: str | None = None,
        t_end: str | None = None,
        turn: int | None = None,
        stats: dict[str, Any] | None = None,
        documents: list[dict[str, Any]] | None = None,
        trace_output: Any = None,
        context: dict[str, Any] | None = None,
        parent_id: str | None = None,
        tool_call_id: str | None = None,
        **extras: Any,
    ) -> str:
        """Record one tool action in strict and rich projections.

        ``extras`` remain on the strict trajectory item because the reference
        sample uses tool-specific fields such as ``k`` and
        ``previous_queries_before_search``. Rich-only fields have explicit
        parameters above and never enter trajectory.json.
        """
        if returned_docids is None and returned is not None:
            returned_docids = [hit["docid"] for hit in returned]
        encoded_arguments = (
            arguments if isinstance(arguments, str)
            else json.dumps(arguments, ensure_ascii=False)
        )
        strict: dict[str, Any] = {
            "type": "tool_call",
            "tool_name": tool_name,
            "arguments": encoded_arguments,
            "output": output,
        }
        if returned_docids is not None:
            strict["returned_docids"] = list(returned_docids)
            self._docids.update(returned_docids)
        if returned is not None:
            strict["returned"] = returned
        strict.update(extras)
        self.result.append(strict)

        rich_base = dict(strict)
        # Preserve the structured input in the rich trace.
        rich_base["arguments"] = arguments
        if trace_output is not None:
            rich_base["output"] = trace_output
        rich_base["failed"] = failed
        if tool_call_id is not None:
            rich_base["tool_call_id"] = tool_call_id
        if stats is None and returned_docids is not None:
            stats = {"returned_documents": len(returned_docids)}
        if context is None and returned_docids:
            context = {"staged": list(returned_docids)}
        step = self._trace_step(
            rich_base, t_start=t_start, t_end=t_end, turn=turn, stats=stats,
            documents=documents, context=context, parent_id=parent_id)
        self.trace_steps.append(step)
        return str(step["id"])

    def add_output_text(
        self,
        text: str,
        *,
        t_start: str | None = None,
        t_end: str | None = None,
        turn: int | None = None,
        stats: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        parent_id: str | None = None,
        record_trace: bool = True,
    ) -> str | None:
        strict = {
            "type": "output_text",
            "tool_name": None,
            "arguments": None,
            "output": text,
        }
        self.result.append(strict)
        if not record_trace:
            return None
        step = self._trace_step(
            strict, t_start=t_start, t_end=t_end, turn=turn, stats=stats,
            context=context, parent_id=parent_id)
        self.trace_steps.append(step)
        return str(step["id"])

    def _trace_step(
        self,
        base: dict[str, Any],
        *,
        t_start: str | None,
        t_end: str | None,
        turn: int | None,
        stats: dict[str, Any] | None = None,
        documents: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        index = len(self.trace_steps)
        step = dict(base)
        step["id"] = f"step-{index:04d}"
        if t_start is not None:
            step["t_start"] = t_start
        if t_end is not None:
            step["t_end"] = t_end
        if turn is not None:
            step["turn"] = turn
        if parent_id is not None:
            step["parent_id"] = parent_id
        elif base.get("type") == "generation":
            step["parent_id"] = "run"
        elif turn is not None and turn in self._generation_ids:
            step["parent_id"] = self._generation_ids[turn]
        else:
            step["parent_id"] = "run"

        duration_ms = _duration_ms(t_start, t_end)
        if duration_ms is not None or stats is not None:
            step["stats"] = {
                **({"duration_ms": duration_ms}
                   if duration_ms is not None else {}),
                **(stats or {}),
            }
        if documents:
            step["documents"] = [{
                "docid": str(document.get("docid", document.get("id", ""))),
            } for document in documents]
        if context is not None:
            step["context"] = context
        return step

    def finalize(
        self,
        status: str = "completed",
        raw_messages: list[Any] | None = None,
        *,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> TrajectoryArtifact:
        counts_ok: dict[str, int] = {}
        counts_all: dict[str, int] = {}
        for step in self.trace_steps:
            if step["type"] != "tool_call":
                continue
            name = str(step["tool_name"])
            counts_all[name] = counts_all.get(name, 0) + 1
            if not step.get("failed"):
                counts_ok[name] = counts_ok.get(name, 0) + 1

        messages = raw_messages or []
        cumulative_tokens = _attach_cumulative_token_usage(self.trace_steps)
        cost_summary = _cost_summary(self.trace_steps)
        strict = {
            "metadata": self.metadata,
            "query_id": self.query_id,
            "tool_call_counts": counts_ok,
            "tool_call_counts_all": counts_all,
            "status": status,
            "retrieved_docids": sorted(self._docids),
            "result": self.result,
            "raw_messages": messages,
        }
        trace: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "query_id": self.query_id,
            "status": status,
            "metadata": dict(self.metadata),
            "summary": {
                "tool_call_counts": counts_ok,
                "tool_call_counts_all": counts_all,
                "retrieved_docids": sorted(self._docids),
                **({"tokens": cumulative_tokens}
                   if cumulative_tokens else {}),
                **({"cost": cost_summary} if cost_summary else {}),
            },
            "input": self._trace_input,
            "steps": self.trace_steps,
        }
        if self._trace_output is not None:
            trace["output"] = self._trace_output
        if started_at is not None:
            trace["started_at"] = started_at
        if ended_at is not None:
            trace["ended_at"] = ended_at
        duration_ms = _duration_ms(started_at, ended_at)
        if duration_ms is not None:
            trace["duration_ms"] = duration_ms
        duration_summary = _duration_summary(self.trace_steps, duration_ms)
        if duration_summary:
            trace["summary"]["duration"] = duration_summary
        if "usage" in self.metadata:
            trace["summary"]["usage"] = self.metadata["usage"]
        return TrajectoryArtifact(strict, trace=trace)


def _duration_ms(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start)
        b = datetime.fromisoformat(end)
    except ValueError:
        return None
    delta = int((b - a).total_seconds() * 1000)
    return delta if delta >= 0 else None


def _attach_cumulative_token_usage(
    steps: list[dict[str, Any]],
) -> dict[str, int]:
    """Attach running model-token throughput to every subsequent step."""
    keys = (
        "input", "input_uncached", "output", "cache_read", "cache_write",
        "total", "processed_input", "processed",
    )
    cumulative = {key: 0 for key in keys}
    saw_usage = False
    for step in steps:
        stats = step.get("stats")
        if not isinstance(stats, dict):
            continue
        direct = stats.get("tokens")
        if isinstance(direct, dict):
            saw_usage = True
            for key in keys:
                value = direct.get(key)
                if isinstance(value, (int, float)):
                    cumulative[key] += int(value)
        if saw_usage:
            stats["cumulative_tokens"] = dict(cumulative)
    return cumulative if saw_usage else {}


def _cost_summary(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum every step's ``stats.cost`` (PLAN §6.1) into a run-level total.

    Pure aggregation over whatever cost blocks the caller already attached
    per step (see ``ragrun.pricing.cost_for_provider``) -- a system that never
    attaches ``stats.cost`` gets no cost summary, not a fabricated zero.
    """
    total_usd = 0.0
    priced_calls = 0
    unpriced_calls = 0
    for step in steps:
        stats = step.get("stats")
        if not isinstance(stats, dict):
            continue
        if stats.get("tokens") is None:
            continue
        cost = stats.get("cost")
        if isinstance(cost, dict) and isinstance(cost.get("usd"), (int, float)):
            total_usd += cost["usd"]
            priced_calls += 1
        else:
            unpriced_calls += 1
    if priced_calls == 0 and unpriced_calls == 0:
        return {}
    return {
        "usd": round(total_usd, 8),
        "priced_calls": priced_calls,
        "unpriced_calls": unpriced_calls,
    }


def _duration_summary(steps: list[dict[str, Any]],
                      total_duration_ms: int | None) -> dict[str, Any]:
    """Roll per-step ``stats.duration_ms`` up by step ``type`` (PLAN §6.2).

    Answers "how much of this run's wall-clock was retrieval vs. LLM calls
    vs. formatting" without re-deriving it by hand from raw steps. Coverage
    counts are included because most systems only timestamp a subset of
    steps today (the loop's replayed events don't set ``t_start``/``t_end``),
    so a caller can tell a genuine breakdown from a sparse one.
    """
    by_type: dict[str, int] = {}
    steps_with_duration = 0
    for step in steps:
        stats = step.get("stats")
        if not isinstance(stats, dict):
            continue
        duration_ms = stats.get("duration_ms")
        if not isinstance(duration_ms, (int, float)):
            continue
        steps_with_duration += 1
        step_type = str(step.get("type") or "unknown")
        by_type[step_type] = by_type.get(step_type, 0) + int(duration_ms)
    if total_duration_ms is None and not by_type:
        return {}
    return {
        **({"total_ms": total_duration_ms} if total_duration_ms is not None else {}),
        "by_type_ms": by_type,
        "steps_with_duration": steps_with_duration,
        "steps_total": len(steps),
    }
