"""Grade the live fresh-context smoke's draft and revision on identical rubrics.

The script deliberately extracts both texts from the persisted trajectory so
the experiment input is the exact provider output, not a hand-copied version.
It prints every criterion and every repeated verdict; stdout is the durable raw
result matrix referenced by the session worklog.
"""
from __future__ import annotations

import json
import statistics as st
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "tasks/task-comparison/scripts"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation/ragdoll/src"))
sys.path.insert(0, str(SCRIPTS))

import judge_client  # noqa: E402
import rubric_eval  # noqa: E402

REPEATS = 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--qid", required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args()
    trajectory_path = args.trajectory.resolve()
    trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    messages = trajectory["raw_messages"]
    boundary_index = next((
        index for index, item in enumerate(messages)
        if item.get("type") == "phase_boundary"
        and item.get("phase") in {
            "research_to_coverage_verifier", "finish_review"}),
        len(messages),
    )
    draft_candidates = [
        item["content"][0]["text"]
        for item in messages[:boundary_index]
        if item.get("type") == "message"
        and item.get("role") == "assistant"
        and item.get("content")
    ]
    revision_candidates = [
        item["content"][0]["text"]
        for item in messages[boundary_index:]
        if item.get("type") == "message"
        and item.get("role") == "assistant"
        and item.get("content")
    ]
    if not draft_candidates or not revision_candidates:
        raise SystemExit(
            f"could not locate draft/revision around phase boundary "
            f"{boundary_index}: {len(draft_candidates)=}, "
            f"{len(revision_candidates)=}")
    texts = [draft_candidates[-1], revision_candidates[-1]]

    rubric = rubric_eval.load_rubrics()[args.qid]
    criteria = [criterion for criterion in rubric["criteria"]
                if not criterion["waived"]]
    model = judge_client.default_judge()
    api = judge_client.client(timeout=300.0)
    labels = ("draft", "revision")
    verdicts_by_stage: dict[str, list[list[str]]] = {}
    scores_by_stage: dict[str, list[float]] = {}

    print(f"qid={args.qid}")
    print(f"trajectory={trajectory_path.relative_to(ROOT)}")
    print(f"judge={model} repeats={args.repeats} criteria={len(criteria)}")
    for label, text in zip(labels, texts):
        print(f"\n===== RAW INPUT: {label} ({len(text.split())} words) =====")
        print(text)
        verdicts_by_stage[label] = []
        scores_by_stage[label] = []
        for repeat in range(args.repeats):
            verdicts = rubric_eval.grade_topic(
                api, model, args.qid,
                f"{args.run_label}-{label}",
                rubric["query"], text, criteria, repeat=repeat)
            if verdicts is None:
                raise SystemExit(f"{label} repeat {repeat} did not grade")
            verdicts_by_stage[label].append(verdicts)
            score = rubric_eval.score_topic(criteria, verdicts)["score"]
            scores_by_stage[label].append(score)
            print(f"{label} repeat={repeat} score={score:.6f}")

    print("\n===== FULL CRITERION MATRIX =====")
    for index, criterion in enumerate(criteria):
        draft = [row[index] for row in verdicts_by_stage["draft"]]
        revision = [row[index] for row in verdicts_by_stage["revision"]]
        print(json.dumps({
            "cid": criterion["cid"],
            "axis": criterion.get("axis"),
            "signed_weight": criterion["signed_weight"],
            "text": criterion["text"],
            "draft": draft,
            "revision": revision,
        }, ensure_ascii=False))

    draft_mean = st.mean(scores_by_stage["draft"])
    revision_mean = st.mean(scores_by_stage["revision"])
    print("\n===== SUMMARY =====")
    print(f"draft_mean={draft_mean:.6f}")
    print(f"revision_mean={revision_mean:.6f}")
    print(f"revision_minus_draft={revision_mean - draft_mean:+.6f}")
    print(judge_client.usage_report(model))


if __name__ == "__main__":
    main()
