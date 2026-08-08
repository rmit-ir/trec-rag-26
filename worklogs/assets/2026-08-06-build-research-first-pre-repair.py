#!/usr/bin/env python3
"""Reconstruct the first accepted draft from each research-first trajectory.

The source and counterfactual share planning, retrieval, committed evidence,
and every model turn up to the verifier.  Only the verifier-directed repair is
removed, which makes the resulting rubric comparison causal for that stage.
"""
from __future__ import annotations

import copy
import glob
import json
from pathlib import Path

from systems.aus_agent_v2.agent import (
    _collapse_to_docs,
    _map_citations,
    _parse_final_prose,
    _word_count,
)


SOURCE_RUN = "sol-aus-v2-research-first-dev30-20260806"
TARGET_RUN = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
OUTPUT_DIR = Path("data/outputs/aus_agent_v2")


def candidate_reports(obj: dict) -> list[tuple[str, list[dict]]]:
    """Return citation-bearing, contract-valid no-tool generations in order."""
    committed = set(obj["trace"]["summary"]["context"]["committed"])
    reports: list[tuple[str, list[dict]]] = []
    for step in obj["trace"]["steps"]:
        output = step.get("output")
        if step.get("type") != "generation" or not isinstance(output, dict):
            continue
        if output.get("tool_calls"):
            continue
        text = output.get("text")
        parsed, _errors, _repairs = _parse_final_prose(
            text, committed, allow_uncited=True)
        if parsed is not None and any(line["citations"] for line in parsed):
            reports.append((str(text), parsed))
    return reports


def main() -> None:
    newest: dict[str, tuple[str, Path, dict]] = {}
    for raw_path in glob.glob(str(OUTPUT_DIR / "*.output.json")):
        path = Path(raw_path)
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("run_id") != SOURCE_RUN:
            continue
        if obj.get("trace", {}).get("status") != "completed":
            continue
        qid = obj["metadata"]["narrative_id"]
        stamp = path.name.split(".", 1)[0]
        if qid not in newest or stamp > newest[qid][0]:
            newest[qid] = (stamp, path, obj)

    if len(newest) != 30:
        raise SystemExit(f"expected 30 completed source topics, found {len(newest)}")

    matrix = []
    for qid, (stamp, path, obj) in sorted(newest.items()):
        reports = candidate_reports(obj)
        repair = obj["trace"]["summary"]["coverage_verify"]
        repair_active = bool(repair["research_repair_active"])
        if repair_active and len(reports) < 2:
            raise RuntimeError(f"{qid}: repair active but only {len(reports)} report(s)")
        _raw, sentences = reports[-2] if repair_active else reports[-1]
        expected_words = int(repair["research_repair_original_words"] or 0)
        actual_words = _word_count(sentences)
        if repair_active and actual_words != expected_words:
            raise RuntimeError(
                f"{qid}: reconstructed {actual_words} words, trace says {expected_words}")

        unit_refs, unit_answer = _map_citations(
            sentences, set(obj["trace"]["summary"]["context"]["committed"]))
        references, answer = _collapse_to_docs(unit_refs, unit_answer)
        counterfactual = copy.deepcopy(obj)
        counterfactual["metadata"]["run_id"] = TARGET_RUN
        counterfactual["metadata"]["run_desc"] = (
            "Counterfactual first valid draft from " + SOURCE_RUN
            + "; verifier-directed research repair removed."
        )
        counterfactual["references"] = references
        counterfactual["answer"] = answer
        counterfactual["trace"]["summary"]["counterfactual"] = {
            "source_run_id": SOURCE_RUN,
            "source_path": str(path),
            "removed_stage": "verifier-directed research repair",
            "repair_was_active": repair_active,
            "candidate_reports": len(reports),
            "pre_repair_words": actual_words,
            "post_repair_words": sum(
                len(item["text"].split()) for item in obj["answer"]),
        }
        target = OUTPUT_DIR / f"{stamp}.pre_repair_counterfactual.output.json"
        target.write_text(
            json.dumps(counterfactual, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        matrix.append({
            "qid": qid,
            "repair_active": repair_active,
            "candidate_reports": len(reports),
            "pre_words": actual_words,
            "post_words": sum(len(item["text"].split()) for item in obj["answer"]),
            "pre_references": len(references),
            "post_references": len(obj["references"]),
            "output": str(target),
        })

    print(json.dumps({
        "source_run": SOURCE_RUN,
        "target_run": TARGET_RUN,
        "topics": len(matrix),
        "matrix": matrix,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
