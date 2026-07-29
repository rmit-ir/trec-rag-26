"""End-to-end mock test for facet_rag — no live model endpoint required.

A scripted in-process ``Provider`` drives the three real pipeline stages
against the REAL ClimbMix search backend (retrieval is proven, not stubbed):

    turn 1 (plan)       -> facets JSON (two facets, distinct engines)
    turn 2 (synthesize) -> grounded prose with inline [docid] citations
    turn 3 (format)     -> strict {"sentences": [...]} JSON

The scripted provider reads the real retrieved docids out of the synthesis
prompt so its citations are guaranteed to be in the allow-list. The test then
asserts both artifacts are written with no ``.violations.json``, correct
``tool_call_counts``, non-empty ``retrieved_docids``, and the plan/tool_call/
synthesis step structure.

Run:  uv run --group facet-rag python src/systems/facet_rag/test_mock.py
(``--group facet-rag`` is optional here — the mock needs no boto3/openai.)
"""
from __future__ import annotations

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SYSTEMS = os.path.dirname(_HERE)
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
if _SYSTEMS not in sys.path:
    sys.path.insert(0, _SYSTEMS)

from ragrun import validate_rag_output  # noqa: E402

from facet_rag.pipeline import run_one  # noqa: E402

_PASSAGE_DOCID_RE = re.compile(r"docid=(\S+)")


class ScriptedProvider:
    """Deterministic mock implementing the aus_agent Provider contract.

    Only the turn API the pipeline uses is implemented (start / add_user_message
    / run_turn). Each ``run_turn`` inspects the pending user text to decide
    whether it is the plan, synthesis, or format stage.
    """

    model_id = "mock/facet-rag"

    def __init__(self) -> None:
        self._pending = ""
        self.turns = 0

    def start(self, system_prompt, tools) -> None:  # noqa: ANN001
        self._pending = ""

    def add_user_message(self, text) -> None:  # noqa: ANN001
        self._pending = text

    def _plan_turn(self) -> str:
        # Two facets on distinct engines; the planner keeps whichever engines
        # are enabled and coerces the rest — semantic+keyword are always on.
        return json.dumps({"facets": [
            {"name": "effectiveness", "engine": "semantic",
             "query": "influenza vaccine effectiveness", "k": 5},
            {"name": "strain match", "engine": "keyword",
             "query": "influenza vaccine strain match season", "k": 5},
        ]})

    def _synthesize_turn(self) -> str:
        docids = _PASSAGE_DOCID_RE.findall(self._pending)
        cite = f"[{docids[0]}]" if docids else ""
        return (
            "Influenza vaccines reduce the risk of laboratory-confirmed "
            f"influenza illness among vaccinated people {cite}. "
            "Vaccine effectiveness varies by season and by how well the "
            f"vaccine matches circulating strains {cite}.")

    def _format_turn(self) -> str:
        # format_answer hands us the draft + ALLOWED DOCIDS; echo back valid
        # sentences citing the first allowed docid.
        m = re.search(r"ALLOWED DOCIDS:\s*(\[.*?\])", self._pending, re.DOTALL)
        docids = json.loads(m.group(1)) if m else []
        first = docids[0] if docids else None
        cites = [first] if first else []
        return json.dumps({"sentences": [
            {"text": "Influenza vaccines reduce the risk of confirmed "
                     "influenza illness.", "citations": cites},
            {"text": "Effectiveness varies by season and strain match.",
             "citations": cites},
        ]})

    def run_turn(self):
        self.turns += 1
        if "SEARCH FACETS" in self._pending or "facets" in self._pending.lower() \
                and "RESEARCH NARRATIVE" in self._pending:
            text = self._plan_turn()
        elif "ALLOWED DOCIDS" in self._pending:
            text = self._format_turn()
        else:
            text = self._synthesize_turn()
        return {"blocks": [{"type": "text", "text": text}],
                "reasoning_blocks": [], "tool_calls": [], "text": text,
                "stop_reason": "end_turn", "usage": {}, "raw": {}}

    def add_tool_results(self, results) -> None:  # noqa: ANN001
        raise AssertionError("facet_rag makes no tool calls to the provider")

    @property
    def raw_messages(self):
        return []


def main() -> int:
    narrative = "How effective are influenza vaccines at preventing illness?"
    qid = "mock_facet_001"

    provider = ScriptedProvider()
    result = run_one(
        provider, qid=qid, narrative=narrative,
        engines=["semantic", "keyword"], default_engine="semantic",
        run_id="facet_rag.mock", run_desc="mock end-to-end test",
        model_id=provider.model_id, backend="mock", max_chars=800,
        min_facets=2, max_facets=4, format_llm=True)

    paths = result["paths"]
    output = json.loads(paths["output"].read_text())
    trajectory = json.loads(paths["trajectory"].read_text())

    # Like ali_deepresearch/test_mock.py, this exercises the REAL ClimbMix
    # search backend. If every facet search failed (e.g. no SEARCH_API_KEY set
    # -> HTTP 401), the retrieval-dependent checks below can't pass — flag it as
    # an environment gap rather than a code failure so it isn't mistaken for a
    # bug in the pipeline.
    if not trajectory["retrieved_docids"]:
        errors = {fr.error for fr in result["retrieval"].per_facet if fr.failed}
        print("  [SKIP] live ClimbMix search returned nothing — check "
              "credentials/reachability (SEARCH_API_KEY / PYSERINI_API_TOKEN).")
        for e in sorted(x for x in errors if x):
            print(f"         search error: {e}")
        print("\nRESULT: SKIPPED (no retrieval; not a code failure)")
        return 0

    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
        ok = ok and cond

    check("status completed", result["status"] == "completed")
    check("trajectory file written", paths["trajectory"].exists())
    check("output file written", paths["output"].exists())
    check("no violations file", "violations" not in paths)
    check("validate_rag_output clean", validate_rag_output(output) == [])

    check("two facets planned", len(result["facets"]) == 2)
    check("two search tool calls",
          trajectory["tool_call_counts"].get("search") == 2)
    check("retrieved_docids non-empty",
          len(trajectory["retrieved_docids"]) > 0)
    check("references non-empty", len(result["references"]) > 0)

    kinds = [it["type"] for it in trajectory["result"]]
    check("plan reasoning + 2 tool_calls + output_text",
          kinds == ["reasoning", "tool_call", "tool_call", "output_text"])

    search_items = [it for it in trajectory["result"]
                    if it["type"] == "tool_call"]
    check("each search item names its facet + engine",
          all("facet" in it and json.loads(it["arguments"]).get("search_engine")
              in ("semantic", "keyword") for it in search_items))

    cited = {c for s in output["answer"] for c in s["citations"]}
    check("every reference cited", cited == set(range(len(output["references"]))))

    # rich trace present in output.json only
    trace = output.get("trace", {})
    check("output.trace present with steps",
          isinstance(trace.get("steps"), list) and len(trace["steps"]) >= 4)
    check("trajectory omits trace", "trace" not in trajectory)

    print()
    print(f"trajectory: {paths['trajectory']}")
    print(f"output:     {paths['output']}")
    print(json.dumps({"facets": [f.__dict__ for f in result["facets"]],
                      "tool_call_counts": trajectory["tool_call_counts"],
                      "references": result["references"]}, indent=2)[:700])
    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
