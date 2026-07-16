"""End-to-end mock test for the ClimbMix Tongyi DeepResearch port.

No live model endpoint is required. A scripted in-process ``ChatLLM`` drives a
2-round conversation through the REAL ReAct loop and the REAL ClimbMix search /
get_document tools (the plumbing is proven, not stubbed):

    round 1: <think> … </think> <tool_call> search </tool_call>
    round 2: <think> … </think> <tool_call> get_document </tool_call>  (real docid)
    round 3: <think> … </think> <answer> … </answer>

Answer formatting uses the OFFLINE heuristic (no formatting endpoint), so the
whole path is exercised with zero network model calls. The test then asserts
both run artifacts are written with no ``.violations.json``, correct
``tool_call_counts``, a non-empty ``retrieved_docids``, and interleaved
reasoning/tool-call items.

Run:  uv run --group ali-deepresearch python src/systems/ali_deepresearch/test_mock.py
(``--group ali-deepresearch`` is optional here — the mock needs no ``openai``.)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_SYSTEMS = os.path.dirname(_HERE)
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
if _SYSTEMS not in sys.path:
    sys.path.insert(0, _SYSTEMS)

from ali_deepresearch import ClimbMixTools, ReactAgent, SYSTEM_PROMPT  # noqa: E402
from ali_deepresearch.run import (  # noqa: E402  (reuse the real assembly helpers)
    build_metadata,
    candidate_docids,
    steps_to_trajectory,
)
from ragrun import build_rag_output, save_run, validate_rag_output  # noqa: E402

_DOCID_RE = re.compile(r"DocID:(\S+)")
_DOC_HEADER_RE = re.compile(r"Document (\S+):")


class ScriptedLLM:
    """Deterministic mock that reacts to real tool responses in the history."""

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _last_tool_response(messages: list[dict[str, str]]) -> str:
        for m in reversed(messages):
            if m["role"] == "user" and "<tool_response>" in m["content"]:
                return m["content"]
        return ""

    def complete(self, messages, *, stop=None, max_tokens=None) -> str:
        self.calls += 1
        if self.calls == 1:
            return ("<think>The user asks about influenza vaccine "
                    "effectiveness. I will search the corpus.</think>\n"
                    "<tool_call>\n"
                    '{"name": "search", "arguments": {"query": '
                    '"influenza vaccine effectiveness"}}\n'
                    "</tool_call>")
        if self.calls == 2:
            resp = self._last_tool_response(messages)
            m = _DOCID_RE.search(resp)
            docid = m.group(1) if m else "shard_00000_0"
            return ("<think>The top result looks relevant. I will open it to "
                    "read the full text.</think>\n"
                    "<tool_call>\n"
                    f'{{"name": "get_document", "arguments": '
                    f'{{"docid": "{docid}"}}}}\n'
                    "</tool_call>")
        resp = self._last_tool_response(messages)
        m = _DOC_HEADER_RE.search(resp)
        docid = m.group(1) if m else "the source"
        return ("<think>I now have enough to answer.</think>\n"
                "<answer>\n"
                "Influenza vaccines reduce the risk of laboratory-confirmed "
                "influenza illness among vaccinated individuals. Vaccine "
                "effectiveness varies by season and by the match between the "
                "vaccine and circulating strains.\n"
                "</answer>")


def main() -> int:
    query = "How effective are influenza vaccines at preventing illness?"
    qid = "mock_flu_001"

    llm = ScriptedLLM()
    agent = ReactAgent(llm, SYSTEM_PROMPT + str(date.today()),
                       toolbox=ClimbMixTools(), k=5, max_rounds=6)
    result = agent.run(query, query_id=qid)

    trajectory = steps_to_trajectory(
        result, build_metadata(query, "mock/tongyi-deepresearch", 5))
    references, answer = format_answer_offline(result)
    output = build_rag_output(
        narrative_id=qid, narrative=query, run_id="ali_deepresearch.mock",
        run_desc="mock end-to-end test", references=references, answer=answer)

    paths = save_run("ali_deepresearch", query, trajectory=trajectory,
                     output=output)

    # ---- assertions -----------------------------------------------------
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    check("status completed", result.status == "completed")
    check("trajectory file written", paths["trajectory"].exists())
    check("output file written", paths["output"].exists())
    check("no violations file", "violations" not in paths)
    check("validate_rag_output clean", validate_rag_output(output) == [])

    check("tool_call_counts == search:1, get_document:1",
          trajectory["tool_call_counts"] == {"search": 1, "get_document": 1})
    check("retrieved_docids non-empty", len(trajectory["retrieved_docids"]) > 0)
    check("references non-empty", len(references) > 0)

    kinds = [it["type"] for it in trajectory["result"]]
    check("interleaved reasoning/tool_call/output_text",
          kinds == ["reasoning", "tool_call", "reasoning", "tool_call",
                    "reasoning", "output_text"])
    check("raw_messages present", "raw_messages" in trajectory)
    check("trajectory top-level keys match reference schema",
          set(trajectory) == {
              "metadata", "query_id", "tool_call_counts",
              "tool_call_counts_all", "status", "retrieved_docids",
              "result", "raw_messages",
          })

    # search tool_call carries the sample's extras
    search_item = next(it for it in trajectory["result"]
                       if it["type"] == "tool_call" and it["tool_name"] == "search")
    check("search item has returned+extras",
          "returned" in search_item and "original_query" in search_item
          and "k" in search_item)

    # every reference index is cited
    cited = {c for s in answer for c in s["citations"]}
    check("every reference cited", cited == set(range(len(references))))

    # ---- strict trajectory + rich output trace ---------------------------
    items = trajectory["result"]
    check("trajectory omits viewer-only timing fields",
          all(not ({"t_start", "t_end", "turn", "stats", "context",
                    "documents"} & it.keys()) for it in items)
          and "started_at" not in trajectory and "ended_at" not in trajectory)
    trace = output.get("trace", {})
    trace_items = trace.get("steps", [])
    check("output.trace has run bounds",
          isinstance(trace.get("started_at"), str)
          and isinstance(trace.get("ended_at"), str)
          and trace["started_at"] <= trace["ended_at"])
    check("every trace step has t_start/t_end/turn",
          all(isinstance(it.get("t_start"), str)
              and isinstance(it.get("t_end"), str)
              and isinstance(it.get("turn"), int) for it in trace_items))
    check("each trace step t_start <= t_end",
          all(it["t_start"] <= it["t_end"] for it in trace_items))
    starts = [it["t_start"] for it in trace_items]
    check("item t_start non-decreasing (sequential loop)",
          all(a <= b for a, b in zip(starts, starts[1:])))
    check("turn indices are [0, 0, 1, 1, 2, 2]",
          [it["turn"] for it in trace_items] == [0, 0, 1, 1, 2, 2])
    check("items lie within run bounds",
          trace["started_at"] <= trace_items[0]["t_start"]
          and trace_items[-1]["t_end"] <= trace["ended_at"])

    print()
    print(f"trajectory: {paths['trajectory']}")
    print(f"output:     {paths['output']}")
    print(json.dumps({"tool_call_counts": trajectory["tool_call_counts"],
                      "retrieved_docids": trajectory["retrieved_docids"],
                      "references": references}, indent=2)[:600])
    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def format_answer_offline(result):
    """Offline (heuristic) answer formatting — no formatting endpoint."""
    from ali_deepresearch import format_answer
    return format_answer(result.answer_text or "", candidate_docids(result),
                         llm=None)


if __name__ == "__main__":
    raise SystemExit(main())
