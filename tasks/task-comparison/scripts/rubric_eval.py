#!/usr/bin/env python3
"""Score one aus_agent run against the fixed dev rubrics, using RAGDoll's grader.

Grading is RAGDoll's (``render_grade_prompt``, ``parse_verdict_list``, the
ternary satisfied / partially_satisfied / not_satisfied scale). **Scoring is
not**, and cannot be, for two reasons documented at length in
``fix_dev_rubrics.py``:

- RAGDoll's ``score_response`` has no concept of a negative weight; its loader
  deletes those criteria outright. The official dev rubrics carry 97 of them —
  the ones that detect bad behaviour. Deleting them can only inflate a score.
- 45 criteria demand output the TREC RAG 2026 answer contract forbids (images,
  Markdown). Grading them as failures penalizes a system for conforming.

So the verdicts come from RAGDoll and the arithmetic honours the rubric's own
sign convention:

    score = sum(signed_weight * verdict_value) / sum(weight for reward criteria)

over **scorable** (non-waived) criteria. Satisfying a penalty subtracts. The
score is <= 1.0 and can go negative, which is the correct behaviour for an
answer that commits the errors the rubric was written to catch.

Waived criteria are excluded from the denominator *and* never shown to the
judge — asking a model to grade "includes a geometric diagram" against prose
wastes tokens to manufacture a guaranteed failure.

Reports the five goal conditions from ``docs/auto-optimize/README.md``, a
per-axis breakdown (so a patch that lifts one aspect while flat overall is
visible and bankable), and exact token cost.

    PYTHONPATH=src uv run --group aus-agent python \\
        tasks/task-comparison/scripts/rubric_eval.py --run-id rubric-dev30-default
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import statistics as st
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation/ragdoll/src"))
sys.path.insert(0, str(HERE))

import judge_client  # noqa: E402

RUBRICS = ROOT / "data/task-comparison/dev-rubrics-fixed.jsonl"
CACHE = ROOT / "data/task-comparison/rubric-eval"
OUT = ROOT / "docs/auto-optimize/rubric-results.jsonl"
WORD_CAP = 1024
VERDICT_VALUE = {"satisfied": 1.0, "partially_satisfied": 0.5,
                 "not_satisfied": 0.0}


def load_rubrics() -> dict[str, dict]:
    if not RUBRICS.exists():
        raise SystemExit(f"{RUBRICS} missing — run fix_dev_rubrics.py first")
    return {r["qid"]: r for r in
            (json.loads(l) for l in RUBRICS.read_text(encoding="utf-8").splitlines()
             if l.strip())}


def load_run(run_id: str, system: str = "aus_agent") -> tuple[dict[str, dict], int]:
    """Newest COMPLETED artifact per narrative, plus a count of rejected ones.

    A failed run still writes an artifact -- with a one-sentence stub reading
    "Run failed: AuthenticationError ...". Those parse as perfectly valid
    answers and score exactly 0.0 on every criterion, which is indistinguishable
    from a real answer that was very bad. That is how a whole arm got scored as
    a -0.55 catastrophic regression when in fact the credential had expired
    mid-run and no answer was ever written. Status is checked here so a broken
    run is a loud refusal rather than a plausible-looking data point.
    """
    if not system.replace("_", "").replace("-", "").isalnum():
        raise SystemExit(f"invalid system output namespace: {system!r}")
    newest: dict[str, tuple[str, dict]] = {}
    rejected = 0
    pattern = ROOT / "data/outputs" / system / "*.output.json"
    for path in sorted(glob.glob(str(pattern))):
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("run_id") != run_id:
            continue
        if (obj.get("trace") or {}).get("status") != "completed":
            rejected += 1
            continue
        qid = obj["metadata"]["narrative_id"]
        stamp = Path(path).name.split(".")[0]
        if qid not in newest or stamp > newest[qid][0]:
            newest[qid] = (stamp, obj)
    return {qid: obj for qid, (_s, obj) in newest.items()}, rejected


def answer_text(obj: dict) -> str:
    return "\n".join(item["text"] for item in obj.get("answer", []))


def criteria_fingerprint(criteria: list[dict]) -> str:
    """Identity of the exact criteria list a verdict list is aligned to.

    Verdicts are positional. If the rubric changes — a waiver rule added, a
    criterion reworded — a cached verdict list silently maps onto different
    criteria, and every score computed from it is wrong in a way that looks
    completely normal. This bit me between the baseline and the first arm: the
    two were graded against 710 and 702 criteria, making their means
    incomparable while both looked fine. The fingerprint makes that a cache
    miss instead of a wrong answer.
    """
    import hashlib
    joined = "\u0000".join(f"{c['cid']}:{c['text']}" for c in criteria)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def grade_topic(api, model: str, qid: str, run_id: str, query: str,
                answer: str, criteria: list[dict],
                repeat: int = 0) -> list[str] | None:
    """One grading call per (run, topic, repeat); cached. Verdicts in order.

    ``repeat`` exists because the judge is not deterministic. Grading the same
    30 answers against the same criteria twice moved the mean by 0.011 and
    flipped one axis from +0.086 to -0.018 -- larger than several of the effects
    being screened. A CI bootstrapped over topics alone treats each grade as
    fixed and therefore understates uncertainty badly enough to bank noise.
    Averaging K independent gradings per topic shrinks that noise by sqrt(K)
    before the paired test ever runs.
    """
    from ragdoll.rubric.prompts import parse_verdict_list, render_grade_prompt
    cache = CACHE / judge_client.canonical(model) / run_id
    path = cache / (f"{qid}.json" if repeat == 0 else f"{qid}.r{repeat}.json")
    fingerprint = criteria_fingerprint(criteria)
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("criteria_fingerprint") == fingerprint:
            return cached.get("verdicts")
        print(f"    {qid}: rubric changed since this was graded "
              f"({cached.get('n_criteria')} -> {len(criteria)} criteria); re-grading")
    prompt = render_grade_prompt(query=query, answer=answer,
                                 criteria=[{"text": c["text"]} for c in criteria])
    try:
        raw = judge_client.complete(api, model, prompt, max_output_tokens=16000)
        verdicts = parse_verdict_list(raw.strip())
        # A short list silently mis-aligns every later criterion with the wrong
        # verdict, which is worse than no score at all — reject the whole call.
        if verdicts is not None and len(verdicts) != len(criteria):
            verdicts = None
        record = {"qid": qid, "run_id": run_id, "verdicts": verdicts,
                  "n_criteria": len(criteria),
                  "criteria_fingerprint": fingerprint, "raw": raw[:400],
                  "status": "completed" if verdicts else "unparsed"}
    except Exception as exc:  # noqa: BLE001
        record = {"qid": qid, "run_id": run_id, "verdicts": None,
                  "n_criteria": len(criteria),
                  "criteria_fingerprint": fingerprint,
                  "raw": f"{type(exc).__name__}: {exc}", "status": "failed"}
    if record["status"] == "completed":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    else:
        # Deliberately NOT cached. `path.exists()` cannot distinguish "the judge
        # said nothing useful" from "the call never reached the judge", so a
        # transient failure written here would be indistinguishable from a
        # verdict forever after.
        print(f"    {qid}: {record['status']} — {record['raw'][:120]}")
    return record["verdicts"]


def score_topic(criteria: list[dict], verdicts: list[str]) -> dict:
    """Sign-aware weighted score plus the per-axis and penalty breakdowns."""
    numerator = 0.0
    denominator = sum(c["signed_weight"] for c in criteria
                      if c["signed_weight"] > 0)
    by_axis: dict[str, list[float]] = collections.defaultdict(list)
    axis_weight: dict[str, float] = collections.defaultdict(float)
    axis_num: dict[str, float] = collections.defaultdict(float)
    bad_penalties = []
    for criterion, verdict in zip(criteria, verdicts):
        value = VERDICT_VALUE.get(str(verdict).strip().lower().replace(" ", "_"), 0.0)
        signed = criterion["signed_weight"]
        numerator += signed * value
        axis = criterion.get("axis") or "Unknown"
        if signed > 0:
            axis_weight[axis] += signed
            axis_num[axis] += signed * value
        else:
            # A satisfied penalty is a committed error. Track the serious ones
            # separately: goal condition (3) is a safety gate, not an average.
            if value > 0 and abs(signed) >= 4:
                bad_penalties.append({"cid": criterion["cid"],
                                      "weight": signed,
                                      "text": criterion["text"][:160]})
        by_axis[axis].append(value)
    return {
        "score": numerator / denominator if denominator else float("nan"),
        "axis": {a: axis_num[a] / axis_weight[a] for a in axis_weight
                 if axis_weight[a]},
        "severe_penalties": bad_penalties,
        "n_scored": len(criteria),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--system", default="aus_agent",
        help="artifact namespace under data/outputs (default: aus_agent)")
    parser.add_argument("--variant", help="defaults to the run id")
    parser.add_argument("--judge-model", default=judge_client.default_judge())
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3,
                        help="independent gradings per topic, averaged. 1 "
                             "reproduces the old single-shot behaviour and is "
                             "not enough to distinguish a real effect from "
                             "judge noise")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    label = args.variant or args.run_id

    rubrics = load_rubrics()
    run, rejected = load_run(args.run_id, args.system)
    qids = [q for q in rubrics if q in run]
    print(f"run={args.run_id} system={args.system} variant={label} "
          f"judge={args.judge_model}")
    print(f"  {len(qids)}/{len(rubrics)} topics have a COMPLETED answer"
          + (f"; {rejected} artifact(s) rejected as not completed" if rejected else ""))
    if rejected and not qids:
        print("  REFUSING to score: every artifact for this run failed. Re-run "
              "the generation; a failure stub scores 0.0 on every criterion and "
              "would be logged as a catastrophic quality regression.")
        return 1
    if len(qids) < len(rubrics):
        print(f"  NOTE: scoring a partial run; the mean is over {len(qids)} "
              f"topics and is NOT comparable to a full-30 score.")
    if args.dry_run:
        total = sum(len([c for c in rubrics[q]["criteria"] if not c["waived"]])
                    for q in qids)
        print(f"  would make {len(qids)} grading calls covering {total} criteria")
        return 0

    api = judge_client.client(timeout=300.0)
    results: dict[str, dict] = {}
    lock = threading.Lock()

    spread: list[float] = []

    def work(qid: str):
        rubric = rubrics[qid]
        criteria = [c for c in rubric["criteria"] if not c["waived"]]
        graded = []
        for repeat in range(max(1, args.repeats)):
            verdicts = grade_topic(api, args.judge_model, qid, label,
                                   rubric["query"], answer_text(run[qid]),
                                   criteria, repeat=repeat)
            if verdicts is not None:
                graded.append(score_topic(criteria, verdicts))
        if not graded:
            return qid, None
        # Average the repeats into one per-topic score, and record how far
        # apart they were -- that spread IS the judge's noise floor, and any
        # effect smaller than it is unmeasurable however many topics you add.
        scores = [g["score"] for g in graded]
        merged = {
            "score": st.mean(scores),
            "axis": {a: st.mean([g["axis"][a] for g in graded if a in g["axis"]])
                     for a in graded[0]["axis"]},
            # A penalty counts as committed if ANY grading saw it: condition (3)
            # is a safety gate, and averaging away a detected serious error is
            # the wrong direction to be wrong in.
            "severe_penalties": [p for g in graded for p in g["severe_penalties"]],
            "n_scored": graded[0]["n_scored"],
            "gradings": len(graded),
        }
        with lock:
            results[qid] = merged
            if len(scores) > 1:
                spread.append(max(scores) - min(scores))
        return qid, merged

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(work, q) for q in qids]):
            future.result()

    failed = [q for q in qids if q not in results]
    if failed:
        print(f"  WARNING: {len(failed)} topics did not grade: {failed[:5]}")

    scores = [results[q]["score"] for q in results]
    # Dedupe: the same penalty seen in several repeats is one committed error.
    severe = [(q, p) for q in results
              for p in {x["cid"]: x for x in results[q]["severe_penalties"]}.values()]
    words = {q: sum(len(i["text"].split()) for i in run[q].get("answer", []))
             for q in results}
    over = [q for q, w in words.items() if w > WORD_CAP]

    axis_all: dict[str, list[float]] = collections.defaultdict(list)
    for q in results:
        for axis, value in results[q]["axis"].items():
            axis_all[axis].append(value)

    if spread:
        print(f"  judge noise: mean spread across {args.repeats} gradings "
              f"{st.mean(spread):.4f}, max {max(spread):.4f} "
              f"— effects smaller than this are not measurable")
    print(f"\n  === goal conditions ===")
    print(f"  1. mean rubric score      {st.mean(scores):.4f}   "
          f"(median {st.median(scores):.4f}, min {min(scores):.4f}, "
          f"max {max(scores):.4f})")
    below = sorted(q for q in results if results[q]["score"] < 0.65)
    print(f"  2. topics below 0.65      {len(below)}"
          + (f"  {below[:5]}" if below else ""))
    print(f"  3. satisfied |w|>=4 penalties  {len(severe)}"
          + (f"  across {len({q for q, _ in severe})} topics" if severe else ""))
    print(f"  4. second judge           not run here (pass --judge-model again)")
    print(f"  5. over {WORD_CAP} words          {len(over)}"
          + (f"  {over[:5]}" if over else ""))

    print(f"\n  === per-axis (reward criteria only) ===")
    for axis, values in sorted(axis_all.items(),
                               key=lambda kv: -st.mean(kv[1])):
        print(f"    {axis:32s} {st.mean(values):.4f}   n={len(values)}")

    if severe:
        print(f"\n  === serious errors committed (goal condition 3) ===")
        for qid, pen in severe[:8]:
            print(f"    {qid[:12]} w={pen['weight']:+.0f}  {pen['text'][:110]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "run_id": args.run_id, "system": args.system, "variant": label,
            "judge": judge_client.canonical(args.judge_model),
            "topics": len(results),
            "mean_score": round(st.mean(scores), 4),
            "median_score": round(st.median(scores), 4),
            "min_score": round(min(scores), 4),
            "topics_below_065": len(below),
            "severe_penalties": len(severe),
            "over_word_cap": len(over),
            "mean_words": round(st.mean(list(words.values())), 1),
            "axis": {a: round(st.mean(v), 4) for a, v in axis_all.items()},
            # Per-topic axis scores, not just their means. The ledger banks a
            # patch on improvement in ANY aspect, and an aspect can only be
            # tested with a paired per-topic CI -- a difference of two means
            # says nothing about whether it survives topic-to-topic variance.
            "per_topic_axis": {q: {a: round(v, 4)
                                   for a, v in results[q]["axis"].items()}
                               for q in sorted(results)},
            "per_topic": {q: round(results[q]["score"], 4) for q in sorted(results)},
            # Judge spend for THIS invocation, so the budget ledger never has to
            # re-derive it from a token count nobody kept.
            "judge_usage": dict(judge_client.USAGE),
            "judge_usd": judge_client.usd_spent(args.judge_model),
            "repeats": args.repeats,
            "judge_spread": round(st.mean(spread), 4) if spread else None,
        }, ensure_ascii=False) + "\n")
    print(f"\n  appended to {OUT.relative_to(ROOT)}")
    print(judge_client.usage_report(args.judge_model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
