"""Apply v2's patch stage to the saved hard-topic draft and grade it paired.

The persisted trajectory supplies the exact draft and exact citation-local
evidence packet used by the failed whole-answer writer. Only the finishing
architecture changes, so this is a controlled test of rewrite vs patch.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src/systems"))
sys.path.insert(0, str(ROOT / "evaluation/ragdoll/src"))
sys.path.insert(0, str(ROOT / "tasks/task-comparison/scripts"))

import judge_client  # noqa: E402
import rubric_eval  # noqa: E402
from aus_agent.providers.openai import OpenAIProvider  # noqa: E402
from aus_agent_v2.finish_review import (  # noqa: E402
    FINISH_REVIEW_SYSTEM,
    apply_evidence_patches,
)


def _message_text(item: dict) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "") for block in content
            if isinstance(block, dict)
        ).strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--qid", required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    path = args.trajectory.resolve()
    trajectory = json.loads(path.read_text(encoding="utf-8"))
    messages = trajectory["raw_messages"]
    boundary = next(
        index for index, item in enumerate(messages)
        if item.get("type") == "phase_boundary"
        and item.get("phase") == "research_to_coverage_verifier"
    )
    drafts = [
        _message_text(item) for item in messages[:boundary]
        if item.get("type") == "message" and item.get("role") == "assistant"
    ]
    packets = [
        _message_text(item) for item in messages[boundary:]
        if item.get("role") == "user"
        and "CITATION-LOCAL EVIDENCE CARDS" in _message_text(item)
    ]
    if not drafts or not packets:
        raise SystemExit("saved trajectory lacks a draft or evidence packet")
    draft = drafts[-1]
    packet = packets[0].split("\n\nCOVERAGE AUDIT OF THE DRAFT\n", 1)[0]

    model = str(trajectory["metadata"]["model"])
    patcher = OpenAIProvider(model, max_tokens=4_000)
    patcher.start(FINISH_REVIEW_SYSTEM, [])
    patcher.add_user_message(packet)
    patch_turn = patcher.run_turn()
    patch_response = patch_turn.get("text") or ""
    patched, patch_stats, patch_errors = apply_evidence_patches(
        draft, patch_response, packet)

    print(f"qid={args.qid}")
    print(f"trajectory={path.relative_to(ROOT)}")
    print(f"patch_model={model}")
    print("\n===== EXACT PATCH SYSTEM PROMPT =====")
    print(FINISH_REVIEW_SYSTEM)
    print("\n===== EXACT PATCH USER INPUT =====")
    print(packet)
    print("\n===== RAW PATCH MODEL OUTPUT =====")
    print(patch_response)
    print("\n===== PATCH APPLICATION =====")
    print(json.dumps({
        "stats": patch_stats,
        "errors": patch_errors,
        "draft_words": len(draft.split()),
        "patched_words": len(patched.split()),
        "patch_usage": patch_turn.get("usage") or {},
    }, ensure_ascii=False, indent=2))

    rubric = rubric_eval.load_rubrics()[args.qid]
    criteria = [item for item in rubric["criteria"] if not item["waived"]]
    judge_model = judge_client.default_judge()
    api = judge_client.client(timeout=300.0)
    verdicts_by_stage: dict[str, list[list[str]]] = {}
    scores_by_stage: dict[str, list[float]] = {}
    for label, text in (("draft", draft), ("patched", patched)):
        print(f"\n===== RAW GRADE INPUT: {label} ({len(text.split())} words) =====")
        print(text)
        verdicts_by_stage[label] = []
        scores_by_stage[label] = []
        for repeat in range(args.repeats):
            verdicts = rubric_eval.grade_topic(
                api,
                judge_model,
                args.qid,
                f"{args.run_label}-{label}",
                rubric["query"],
                text,
                criteria,
                repeat=repeat,
            )
            if verdicts is None:
                raise SystemExit(f"{label} repeat {repeat} did not grade")
            verdicts_by_stage[label].append(verdicts)
            score = rubric_eval.score_topic(criteria, verdicts)["score"]
            scores_by_stage[label].append(score)
            print(f"{label} repeat={repeat} score={score:.6f}")

    print("\n===== FULL CRITERION MATRIX =====")
    for index, criterion in enumerate(criteria):
        print(json.dumps({
            "cid": criterion["cid"],
            "axis": criterion.get("axis"),
            "signed_weight": criterion["signed_weight"],
            "text": criterion["text"],
            "draft": [row[index] for row in verdicts_by_stage["draft"]],
            "patched": [row[index] for row in verdicts_by_stage["patched"]],
        }, ensure_ascii=False))

    draft_mean = st.mean(scores_by_stage["draft"])
    patched_mean = st.mean(scores_by_stage["patched"])
    print("\n===== SUMMARY =====")
    print(f"draft_mean={draft_mean:.6f}")
    print(f"patched_mean={patched_mean:.6f}")
    print(f"patched_minus_draft={patched_mean - draft_mean:+.6f}")
    print(judge_client.usage_report(judge_model))


if __name__ == "__main__":
    main()
