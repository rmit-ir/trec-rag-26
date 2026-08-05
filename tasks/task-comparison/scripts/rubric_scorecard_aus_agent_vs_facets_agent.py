#!/usr/bin/env python3
"""Per-criterion rubric scorecard: aus_agent vs facets_agent, over the same
15 topics and rubrics as ``arena_aus_agent_vs_facets_agent_rubric.py``.

That script's pairwise arena judge produces one holistic win/loss per battle
-- it never says WHICH criteria drove a verdict. This script answers the
follow-up question from the arena worklog: do the topics aus_agent won
cluster on identifiable rubric axes (e.g. "Instruction Following",
"Communication Quality") that facets_agent's answers are systematically
missing, versus the topics facets_agent won?

Approach, adapted from the existing single-run rubric judge
(``tasks/task-comparison/rubric-judge/judge_answers.py``): ONE LLM call per
(system, topic) grades EVERY rubric criterion against that answer,
0 (not satisfied) / 1 (partial) / 2 (full), plus a holistic overall grade.
Two differences from that script, both necessary for this specific question:

- ``judge_answers.py`` restricts to ``INFO_AXES`` (Explicit/Implicit
  Criteria, Synthesis of Information) and drops every negative-weight
  penalty criterion, because it exists to score INFORMATION coverage of
  retrieved docs. This script keeps ALL axes and ALL criteria (including
  penalties) -- axes like "Instruction Following" and "Communication
  Quality" are exactly what the arena worklog's hypothesis is about, and
  they would be invisible under that filter.
- ``judge_answers.py``'s aggregation (``sum(w for grade>=1) / total_weight``)
  is only valid because every weight it sees is positive. With penalty
  criteria included, a satisfied NEGATIVE-weight criterion means the answer
  committed the flagged mistake and must SUBTRACT, not add -- see
  ``per_axis_score`` below.

Judge model: ``gpt-5.6-terra`` by default, matching the arena comparison's
choice for the same reason (generated neither system's answers here -- both
ran on gpt-5.6-luna -- so no self-preference risk carries into the scoring
either).

Usage (repo root; needs OPENAI creds -- see ``load_env``):

    uv run --group aus-agent python \
        tasks/task-comparison/scripts/rubric_scorecard_aus_agent_vs_facets_agent.py
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

RUN_IDS = {"aus_agent": "aus-agent-15topic", "facets_agent": "facets-agent-15topic"}
RESEARCH_RUBRICS = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
                    "development-data/researchrubrics-dev-rubrics/"
                    "research-rubrics-dev-rubrics.jsonl")
# The arena's win/loss grouping (worklogs/2026-08-05-aus-agent-vs-facets-agent-
# rubric-arena.md) -- used only to print the scorecard split by group, not
# recomputed here.
ARENA_GROUPS = {
    "aus_agent": ["683a58c9a7e7fe4e76958498", "684397d188c1deceb49af325",
                 "6847465956a0f6376a605391", "6847465956a0f6376a605476",
                 "6847465956a0f6376a60547e", "6847465956a0f6376a60547f",
                 "6847465956a0f6376a605492"],
    "facets_agent": ["684397d188c1deceb49af32d", "6847465956a0f6376a605387",
                     "6847465956a0f6376a605493"],
    "ambiguous": ["6847465956a0f6376a60535d", "6847465956a0f6376a605367",
                 "6847465956a0f6376a605404", "6847465956a0f6376a60542a",
                 "6847465956a0f6376a6054a7"],
}
OUT_DIR = ROOT / "evaluation-results/arena/aus_agent-vs-facets_agent-15topic-rubric"
SCORE_DIR = OUT_DIR / "criterion-scores"

SYSTEM_PROMPT = (
    "You are a strict evaluator for a research assistant's answer. Given a "
    "research request, its rubric criteria (cid = stable id, each with a "
    "weight and an axis), and the assistant's FINAL ANSWER, grade how well "
    "the answer satisfies EACH criterion -- including negative-weight "
    "criteria, which describe a MISTAKE to avoid: grade those on whether the "
    "answer committed that mistake, not on avoiding it. Judge only the "
    "answer text shown. Return STRICT JSON only.")
USER_TMPL = """REQUEST:
{query}

RUBRIC CRITERIA (cid = stable id):
{criteria}

ASSISTANT'S FINAL ANSWER:
\"\"\"
{answer}
\"\"\"

Return STRICT JSON:
{{"criteria_coverage": [{{"cid": <int>, "grade": <0|1|2>}}, ...], "overall": <0|1|2|3>}}
For a POSITIVE-weight criterion: 0 = not satisfied, 1 = partially, 2 = fully satisfied.
For a NEGATIVE-weight criterion (a mistake to avoid): 0 = mistake not made, \
1 = mistake partially/mildly present, 2 = mistake clearly made.
Include EVERY cid from the list, using ONLY cids from the list above. \
overall = holistic answer quality (0 poor ... 3 excellent).
"""


def load_env() -> None:
    import os
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]


def client():
    import os
    from openai import OpenAI
    return OpenAI(base_url=os.environ["OPENAI_BASE_URL"],
                  api_key=os.environ["OPENAI_API_KEY"],
                  timeout=180.0, max_retries=4)


def load_answers_from_outputs(system_dir: Path, run_id: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(glob.glob(str(system_dir / "*.output.json"))):
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        metadata = obj.get("metadata", {})
        if metadata.get("run_id") != run_id:
            continue
        qid = metadata["narrative_id"]
        rows[qid] = {
            "qid": qid, "query": metadata["narrative"],
            "answer_text": "\n".join(s["text"] for s in obj["answer"]),
        }
    return rows


def load_criteria(path: Path) -> dict[str, list[dict[str, Any]]]:
    """qid -> [{cid, text, weight, axis}, ...], ALL axes, stable cid = index."""
    out: dict[str, list[dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        criteria = [
            {"cid": i, "text": c["criterion"], "weight": float(c["weight"]),
             "axis": c["axis"]}
            for i, c in enumerate(row.get("rubrics", []))
            if str(c.get("criterion", "")).strip()
        ]
        out[row["qid"]] = criteria
    return out


def fmt_criteria(criteria: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"  [cid {c['cid']}] (weight={c['weight']}, axis={c['axis']}) {c['text']}"
        for c in criteria)


def score_one(api, model: str, system: str, qid: str, query: str,
             answer_text: str, criteria: list[dict[str, Any]],
             cache: Path) -> dict[str, Any]:
    path = cache / f"{system}__{qid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    user = USER_TMPL.format(query=query, criteria=fmt_criteria(criteria),
                            answer=answer_text[:16000])
    valid_cids = {c["cid"] for c in criteria}
    try:
        response = api.chat.completions.create(
            model=model, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}])
        obj = json.loads(response.choices[0].message.content)
        coverage = [
            {"cid": int(x["cid"]), "grade": max(0, min(2, int(x["grade"])))}
            for x in obj.get("criteria_coverage", [])
            if int(x.get("cid", -1)) in valid_cids
        ]
        record = {"system": system, "qid": qid,
                  "overall": max(0, min(3, int(obj.get("overall", 0)))),
                  "criteria_coverage": coverage, "status": "completed"}
    except Exception as exc:  # noqa: BLE001
        record = {"system": system, "qid": qid, "status": "failed",
                  "error": f"{type(exc).__name__}: {exc}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def per_axis_score(coverage: list[dict[str, Any]], criteria: list[dict[str, Any]]
                   ) -> dict[str, float]:
    """axis -> normalized score in [-1, 1].

    ``contribution = weight * grade / 2`` per criterion: a fully-satisfied
    POSITIVE-weight criterion contributes +weight (good); a fully-COMMITTED
    NEGATIVE-weight criterion (grade=2, i.e. the answer made that mistake)
    contributes -|weight| (bad) since weight is already negative; grade=0
    always contributes 0 regardless of sign. Normalized by the axis's total
    |weight| so axes with different numbers/scales of criteria are
    comparable.
    """
    grade_by_cid = {c["cid"]: c["grade"] for c in coverage}
    by_axis: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for c in criteria:
        by_axis[c["axis"]].append((c["weight"], grade_by_cid.get(c["cid"], 0)))
    scores: dict[str, float] = {}
    for axis, pairs in by_axis.items():
        total_abs_weight = sum(abs(w) for w, _ in pairs) or 1.0
        scores[axis] = sum(w * g / 2 for w, g in pairs) / total_abs_weight
    return scores


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--model", default="gpt-5.6-terra")
    args = parser.parse_args()

    answers = {
        "aus_agent": load_answers_from_outputs(
            ROOT / "data/outputs/aus_agent", RUN_IDS["aus_agent"]),
        "facets_agent": load_answers_from_outputs(
            ROOT / "data/outputs/facets_agent", RUN_IDS["facets_agent"]),
    }
    criteria_by_qid = load_criteria(RESEARCH_RUBRICS)
    qids = sorted(set(answers["aus_agent"]) & set(answers["facets_agent"]))

    jobs = [(system, qid) for system in ("aus_agent", "facets_agent") for qid in qids]
    todo = [(s, q) for s, q in jobs
           if not (SCORE_DIR / f"{s}__{q}.json").exists()]
    print(f"{len(qids)} topics x 2 systems = {len(jobs)} scorecards, "
          f"{len(todo)} not cached, judge={args.model}")

    api = client()
    done, lock = 0, threading.Lock()

    def work(job):
        nonlocal done
        system, qid = job
        row = answers[system][qid]
        record = score_one(api, args.model, system, qid, row["query"],
                           row["answer_text"], criteria_by_qid[qid], SCORE_DIR)
        with lock:
            done += 1
            print(f"  [{done}/{len(todo)}] {system} {qid}", flush=True)
        return record

    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(work, j) for j in jobs
                                        if j in todo]):
                future.result()

    records = {(s, q): json.loads((SCORE_DIR / f"{s}__{q}.json").read_text())
              for s, q in jobs}
    failed = [k for k, r in records.items() if r["status"] != "completed"]
    if failed:
        print(f"\n{len(failed)} scorecards failed: {failed}", file=sys.stderr)

    # -- per-topic, per-axis score for each system ---------------------------
    axis_scores: dict[tuple[str, str], dict[str, float]] = {}
    overall: dict[tuple[str, str], int] = {}
    for (system, qid), record in records.items():
        if record["status"] != "completed":
            continue
        axis_scores[(system, qid)] = per_axis_score(
            record["criteria_coverage"], criteria_by_qid[qid])
        overall[(system, qid)] = record["overall"]

    all_axes = sorted({axis for scores in axis_scores.values() for axis in scores})

    def group_avg(group: list[str], system: str) -> dict[str, float]:
        vals: dict[str, list[float]] = defaultdict(list)
        for qid in group:
            scores = axis_scores.get((system, qid))
            if scores is None:
                continue
            for axis in all_axes:
                vals[axis].append(scores.get(axis, 0.0))
        return {axis: (sum(v) / len(v) if v else float("nan"))
               for axis, v in vals.items()}

    print("\n=== per-axis average score by arena-outcome group "
         "(positive = better; range roughly [-1, 1]) ===")
    header = f"{'axis':30s}" + "".join(
        f"{g + '(aus)':>16s}{g + '(facets)':>16s}{'diff':>10s}"
        for g in ("aus_agent", "facets_agent", "ambiguous"))
    print(header)
    for axis in all_axes:
        row = f"{axis:30s}"
        for group_name in ("aus_agent", "facets_agent", "ambiguous"):
            group = ARENA_GROUPS[group_name]
            a = group_avg(group, "aus_agent").get(axis, float("nan"))
            f = group_avg(group, "facets_agent").get(axis, float("nan"))
            row += f"{a:16.3f}{f:16.3f}{a - f:10.3f}"
        print(row)

    print("\n=== overall grade (0-3) by arena-outcome group ===")
    for group_name, group in ARENA_GROUPS.items():
        aus_vals = [overall[("aus_agent", q)] for q in group if ("aus_agent", q) in overall]
        facets_vals = [overall[("facets_agent", q)] for q in group if ("facets_agent", q) in overall]
        aus_avg = sum(aus_vals) / len(aus_vals) if aus_vals else float("nan")
        facets_avg = sum(facets_vals) / len(facets_vals) if facets_vals else float("nan")
        print(f"  {group_name:14s} n={len(group):2d}  aus_agent={aus_avg:.2f}  "
              f"facets_agent={facets_avg:.2f}")

    out = {
        "judge_model": args.model,
        "axis_scores_by_topic": {
            f"{s}__{q}": scores for (s, q), scores in axis_scores.items()},
        "overall_by_topic": {f"{s}__{q}": v for (s, q), v in overall.items()},
        "arena_groups": ARENA_GROUPS,
    }
    out_path = OUT_DIR / "criterion_scorecard_summary.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
