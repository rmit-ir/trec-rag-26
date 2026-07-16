"""Trajectory recording — the ``*.trajectory.json`` half of a run.

Produces a dict shaped like the reference sample
``data/sample-files/run_InfoSeekQA_1000_20260625T230857966818Z.json``:

    {
      "metadata":        {... free-form run config; "query_source" = the query},
      "query_id":        "<topic id>",
      "tool_call_counts":     {"search": 6, "get_document": 2},
      "tool_call_counts_all": {...},   # includes failed calls
      "status":          "completed" | "failed" | "budget_exhausted",
      "retrieved_docids": [...],       # sorted union over all tool calls
      "result": [
        {"type": "reasoning",   "tool_name": null, "arguments": null, "output": "<thinking text>"},
        {"type": "tool_call",   "tool_name": "search", "arguments": "<json str>",
         "output": "<tool result str>", "returned_docids": [...],
         "returned": [{"docid": ..., "score": ...}, ...], ...extras},
        {"type": "output_text", "tool_name": null, "arguments": null, "output": "<final answer>"}
      ],
      "raw_messages":    [...]         # provider-native message history, optional
    }

Usage:

    tb = TrajectoryBuilder(query_id, query, metadata={"model": ..., "k": 10})
    tb.add_reasoning(thinking_text)
    tb.add_tool_call("search", args_dict, tool_output_str,
                     returned=[{"docid": d, "score": s}, ...])
    tb.add_output_text(final_answer)
    traj = tb.finalize(status="completed", raw_messages=provider_messages)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Melbourne")


def now_iso() -> str:
    """Melbourne-local ISO timestamp with ms precision and offset for item/run
    timing fields, e.g. ``2026-07-16T18:21:34.342+10:00``."""
    return datetime.now(TZ).isoformat(timespec="milliseconds")


class TrajectoryBuilder:
    def __init__(self, query_id: str, query: str,
                 metadata: dict[str, Any] | None = None) -> None:
        self.query_id = query_id
        self.metadata: dict[str, Any] = dict(metadata or {})
        # The sample format carries the query in metadata.query_source.
        self.metadata.setdefault("query_source", query)
        self.result: list[dict[str, Any]] = []
        self._docids: set[str] = set()

    # -- result items ------------------------------------------------------

    def add_reasoning(self, text: str, *, t_start: str | None = None,
                      t_end: str | None = None, turn: int | None = None) -> None:
        """One block of model thinking (interleaved between tool calls)."""
        if text:
            item: dict[str, Any] = {"type": "reasoning", "tool_name": None,
                                    "arguments": None, "output": text}
            self._add_timing(item, t_start, t_end, turn)
            self.result.append(item)

    def add_tool_call(self, tool_name: str, arguments: Any, output: str, *,
                      returned: list[dict[str, Any]] | None = None,
                      returned_docids: list[str] | None = None,
                      failed: bool = False,
                      t_start: str | None = None, t_end: str | None = None,
                      turn: int | None = None,
                      **extras: Any) -> None:
        """One executed tool call.

        - ``arguments`` may be a dict (JSON-encoded here) or a pre-encoded str.
        - ``returned`` — per-hit ``{"docid": ..., "score": ...}`` when the tool
          returns ranked hits; ``returned_docids`` derived from it if omitted.
        - ``failed=True`` counts the call in ``tool_call_counts_all`` only.
        - ``t_start``/``t_end`` — ISO UTC wall-clock bounds of the call (use
          ``now_iso()``); ``turn`` — 0-based model-turn index. Calls sharing a
          ``turn`` with overlapping times ran in parallel; viewers render them
          in parallel lanes.
        - ``extras`` land verbatim on the item (e.g. ``k``, ``original_query``).
        """
        if returned_docids is None and returned is not None:
            returned_docids = [h["docid"] for h in returned]
        item: dict[str, Any] = {
            "type": "tool_call",
            "tool_name": tool_name,
            "arguments": arguments if isinstance(arguments, str)
                         else json.dumps(arguments, ensure_ascii=False),
            "output": output,
            "failed": failed,
        }
        if returned_docids is not None:
            item["returned_docids"] = list(returned_docids)
            self._docids.update(returned_docids)
        if returned is not None:
            item["returned"] = returned
        self._add_timing(item, t_start, t_end, turn)
        item.update(extras)
        self.result.append(item)

    def add_output_text(self, text: str, *, t_start: str | None = None,
                        t_end: str | None = None,
                        turn: int | None = None) -> None:
        """The final answer text (last item of ``result``)."""
        item: dict[str, Any] = {"type": "output_text", "tool_name": None,
                                "arguments": None, "output": text}
        self._add_timing(item, t_start, t_end, turn)
        self.result.append(item)

    @staticmethod
    def _add_timing(item: dict[str, Any], t_start: str | None,
                    t_end: str | None, turn: int | None) -> None:
        """Attach optional timing/turn fields (additive; old readers ignore)."""
        if t_start is not None:
            item["t_start"] = t_start
        if t_end is not None:
            item["t_end"] = t_end
        if turn is not None:
            item["turn"] = turn

    # -- finalize ------------------------------------------------------------

    def finalize(self, status: str = "completed",
                 raw_messages: list[Any] | None = None, *,
                 started_at: str | None = None,
                 ended_at: str | None = None) -> dict[str, Any]:
        counts_ok: dict[str, int] = {}
        counts_all: dict[str, int] = {}
        for item in self.result:
            if item["type"] != "tool_call":
                continue
            name = item["tool_name"]
            counts_all[name] = counts_all.get(name, 0) + 1
            if not item.get("failed"):
                counts_ok[name] = counts_ok.get(name, 0) + 1
        traj: dict[str, Any] = {
            "metadata": self.metadata,
            "query_id": self.query_id,
            "tool_call_counts": counts_ok,
            "tool_call_counts_all": counts_all,
            "status": status,
            "retrieved_docids": sorted(self._docids),
            "result": self.result,
        }
        if started_at is not None:
            traj["started_at"] = started_at
        if ended_at is not None:
            traj["ended_at"] = ended_at
        if raw_messages is not None:
            traj["raw_messages"] = raw_messages
        return traj
