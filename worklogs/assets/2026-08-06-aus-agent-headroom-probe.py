#!/usr/bin/env python3
"""Where does the WINNING baseline (aus_agent) still lose points?

Every prior diagnosis in this repo asked why a challenger lost to aus_agent.
This probe asks the opposite question — the one that has to be answered before
designing a system meant to beat aus_agent: on the 30-topic dev set aus_agent
already wins, which of the official ResearchRubrics criteria does it still
fail, and does it leave any answer sentence uncited (weighted citation recall
is scored separately by the organizers, and an uncited sentence scores 0).

Read-only. No network, no API cost. Sources:
  - per-criterion grades produced by the existing scorecard pass:
    evaluation-results/arena/aus_agent-vs-facets_agent-dev30-rubric/criterion-scores/
  - official rubric text/weights/axes:
    data/official/.../research-rubrics-dev-rubrics.jsonl
  - aus_agent's own answers: data/outputs/aus_agent/*.output.json
    (run_id aus-agent-dev30-luna-e2708ab, gpt-5.6-luna, 30/30 topics)

Run from the repo root:  python worklogs/assets/2026-08-06-aus-agent-headroom-probe.py
Numbers it prints are quoted in worklogs/2026-08-06-brief-revise-agent-architecture-plan.md
and in src/systems/brief_revise_agent/PLAN.md §1.
"""
from __future__ import annotations

import collections
import glob
import json
import statistics

RUN_ID = "aus-agent-dev30-luna-e2708ab"
RUBRICS = ("data/official/trec-rag-2026-data/trec-rag-2026/development-data/"
           "researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl")
SCORES = ("evaluation-results/arena/aus_agent-vs-facets_agent-dev30-rubric/"
          "criterion-scores/")


def main() -> None:
    rubrics = {json.loads(line)["qid"]: json.loads(line)["rubrics"]
               for line in open(RUBRICS)}

    # --- answers: length + uncited-sentence rate -------------------------
    words, uncited, sentences, per_topic = [], 0, 0, {}
    for path in glob.glob("data/outputs/aus_agent/*.output.json"):
        obj = json.load(open(path))
        if obj.get("metadata", {}).get("run_id") != RUN_ID:
            continue
        answer = obj["answer"]
        w = sum(len(s["text"].split()) for s in answer)
        u = sum(1 for s in answer if not s["citations"])
        words.append(w)
        uncited += u
        sentences += len(answer)
        per_topic[obj["metadata"]["narrative_id"]] = (u / len(answer), w)
    print(f"answers n={len(words)}  words mean={statistics.mean(words):.0f} "
          f"median={statistics.median(words):.0f} min={min(words)} "
          f"max={max(words)}  (hard cap 1024)")
    print(f"sentences {sentences}, uncited {uncited} "
          f"({uncited / sentences:.1%}) — headings are stripped by "
          f"_parse_final_prose, so these are all prose sentences")

    # --- rubric grades: distribution + per-axis --------------------------
    grades = collections.Counter()
    by_axis: dict[str, list[int]] = collections.defaultdict(list)
    topics = []
    for path in glob.glob(SCORES + "aus_agent__*.json"):
        obj = json.load(open(path))
        rl = rubrics[obj["qid"]]
        for c in obj["criteria_coverage"]:
            grades[c["grade"]] += 1
            by_axis[rl[c["cid"]]["axis"]].append(c["grade"])
        pos = [(rl[c["cid"]]["weight"], c["grade"])
               for c in obj["criteria_coverage"] if rl[c["cid"]]["weight"] > 0]
        implicit = [c["grade"] for c in obj["criteria_coverage"]
                    if rl[c["cid"]]["axis"] == "Implicit Criteria"]
        topics.append((
            sum(w * (3 - g) / 3 for w, g in pos) / sum(w for w, _ in pos),
            obj["qid"], len(obj["criteria_coverage"]),
            statistics.mean(implicit) if implicit else -1.0,
            per_topic.get(obj["qid"], (0.0, 0)),
        ))
    n = sum(grades.values())
    print(f"\ncriteria judged n={n}  grade distribution "
          + str({g: f"{grades[g] / n:.1%}" for g in (0, 1, 2, 3)}))
    print("\nper-axis (grade 0-3, higher is better):")
    for axis, gs in sorted(by_axis.items(), key=lambda kv: -len(kv[1])):
        low = sum(1 for g in gs if g <= 1)
        print(f"  {axis:32s} n={len(gs):4d} mean={statistics.mean(gs):.2f} "
              f"pct<=1={low / len(gs):.0%}")

    print("\nworst topics by fraction of positive rubric weight lost "
          "(pilot-set candidates):")
    topics.sort(reverse=True)
    for lost, qid, ncrit, imp, (unc, w) in topics[:8]:
        print(f"  {lost:.3f} {qid} ncrit={ncrit:2d} implicit_mean={imp:.2f} "
              f"uncited={unc:.0%} words={w}")


if __name__ == "__main__":
    main()
