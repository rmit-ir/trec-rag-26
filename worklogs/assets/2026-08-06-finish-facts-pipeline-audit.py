#!/usr/bin/env python3
"""Audit baseline formatting and the proximal effects of two AUS interventions.

This is deliberately offline: it reads frozen organizer baselines, saved AUS
artifacts, fixed rubrics, and cached three-repeat Sol judgments.  Its purpose is
to distinguish "the idea did not work" from "the implementation never changed
the behavior it was intended to change."
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "data/outputs/aus_agent"
EVAL = ROOT / "data/task-comparison/test119-eval"
RUBRICS = ROOT / "data/task-comparison/dev-rubrics-fixed.jsonl"
CACHE = ROOT / "data/task-comparison/rubric-eval/gpt-5.6-sol"

VERDICT = {
    "not_satisfied": 0.0,
    "partially_satisfied": 0.5,
    "satisfied": 1.0,
}
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[.,:/-][A-Za-z0-9]+)*")
DIGIT_RE = re.compile(r"\b\d[\d,.:%/-]*\b")
VAGUE_RE = re.compile(
    r"\b(?:can|could|may|might)\s+(?:have|help|improve|reduce|increase|affect)|"
    r"\b(?:significant|important|various|several|many)\b|"
    r"\bstudies suggest\b|\bvar(?:y|ies|ied) considerably\b",
    re.I,
)
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "in", "is", "it", "of", "on", "or", "that", "the", "their",
    "this", "to", "was", "were", "with",
}


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def answer_text(obj: dict) -> str:
    return "\n".join(item["text"] for item in obj.get("answer", []))


def baseline_format() -> None:
    print("## Organizer baseline formatting")
    for filename in ("base-agentic-bm25.jsonl", "base-singlepass.jsonl"):
        records = rows(EVAL / filename)
        topics: dict[str, set[str]] = collections.defaultdict(set)
        objects: collections.Counter[str] = collections.Counter()
        uncited: collections.Counter[str] = collections.Counter()
        for record in records:
            qid = record["metadata"]["narrative_id"]
            for item in record["answer"]:
                text = item["text"]
                lines = text.splitlines()
                kinds = set()
                if any(re.match(r"^\s{0,3}#{1,6}\s", line) for line in lines):
                    kinds.add("heading")
                if any(re.match(r"^\s*\|.*\|\s*$", line) for line in lines):
                    kinds.add("table")
                if any(re.match(r"^\s*[-*+]\s", line) for line in lines):
                    kinds.add("bullet")
                if any(re.match(r"^\s*\d{1,3}[.)]\s", line) for line in lines):
                    kinds.add("numbered")
                if "**" in text:
                    kinds.add("bold")
                for kind in kinds:
                    topics[kind].add(qid)
                    objects[kind] += 1
                    uncited[kind] += not bool(item.get("citations"))
        print(filename, f"topics={len(records)}")
        for kind in ("heading", "table", "bullet", "numbered", "bold"):
            print(
                f"  {kind}: topics={len(topics[kind])} "
                f"ids={sorted(topics[kind])} objects={objects[kind]} "
                f"uncited_objects={uncited[kind]}"
            )


def load_rubrics() -> dict[str, list[dict]]:
    return {
        row["qid"]: [criterion for criterion in row["criteria"]
                     if not criterion.get("waived")]
        for row in rows(RUBRICS)
    }


def judgment(label: str, qid: str, repeat: int) -> list[str] | None:
    suffix = ".json" if repeat == 0 else f".r{repeat}.json"
    path = CACHE / label / f"{qid}{suffix}"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("verdicts")


def transition_name(before: float, after: float) -> str:
    names = {0.0: "missing", 0.5: "partial", 1.0: "satisfied"}
    return f"{names[before]}->{names[after]}"


def criterion_transitions(control: str, arm: str) -> None:
    rubrics = load_rubrics()
    count: collections.Counter[str] = collections.Counter()
    weight: collections.Counter[str] = collections.Counter()
    by_axis: collections.Counter[tuple[str, str]] = collections.Counter()
    qid_delta: collections.Counter[str] = collections.Counter()
    paired = 0
    for qid, criteria in rubrics.items():
        for repeat in range(3):
            left = judgment(control, qid, repeat)
            right = judgment(arm, qid, repeat)
            if left is None or right is None:
                continue
            if len(left) != len(criteria) or len(right) != len(criteria):
                raise ValueError(f"criterion alignment mismatch for {qid} r{repeat}")
            paired += 1
            for criterion, old, new in zip(criteria, left, right):
                signed_weight = float(criterion["signed_weight"])
                if signed_weight <= 0:
                    continue
                before = VERDICT[str(old).strip().lower().replace(" ", "_")]
                after = VERDICT[str(new).strip().lower().replace(" ", "_")]
                transition = transition_name(before, after)
                count[transition] += 1
                weight[transition] += signed_weight
                by_axis[(criterion.get("axis") or "Unknown", transition)] += 1
                qid_delta[qid] += signed_weight * (after - before)

    print(f"## Criterion transitions: {control} -> {arm}")
    print(f"paired_topic_grades={paired}")
    for before in ("missing", "partial", "satisfied"):
        for after in ("missing", "partial", "satisfied"):
            key = f"{before}->{after}"
            print(f"  {key}: n={count[key]} weight={weight[key]:.1f}")
    partial_out = sum(count[f"partial->{x}"] for x in
                      ("missing", "partial", "satisfied"))
    converted = count["partial->satisfied"]
    regressed = count["partial->missing"]
    print(
        f"  partial proximal outcome: converted={converted}/{partial_out} "
        f"({converted / partial_out:.1%}), regressed={regressed}/{partial_out} "
        f"({regressed / partial_out:.1%})"
    )
    print("  per-topic weighted raw numerator delta across 3 repeats:")
    for qid in sorted(qid_delta):
        print(f"    {qid}\t{qid_delta[qid]:+.1f}")


def load_runs(wanted: set[str]) -> dict[str, dict[str, dict]]:
    newest: dict[str, dict[str, tuple[str, dict]]] = {
        run_id: {} for run_id in wanted
    }
    for path in OUTPUTS.glob("*.output.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_id = obj.get("metadata", {}).get("run_id")
        if run_id not in wanted or obj.get("trace", {}).get("status") != "completed":
            continue
        qid = obj["metadata"]["narrative_id"]
        stamp = path.name.split(".", 1)[0]
        old = newest[run_id].get(qid)
        if old is None or stamp > old[0]:
            newest[run_id][qid] = (stamp, obj)
    return {
        run_id: {qid: obj for qid, (_stamp, obj) in records.items()}
        for run_id, records in newest.items()
    }


def normalized(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def token_recall(value: str, answer: str) -> float:
    wanted = [token for token in WORD_RE.findall(value.lower())
              if token not in STOP and len(token) > 1]
    if not wanted:
        return 0.0
    answer_tokens = set(WORD_RE.findall(answer.lower()))
    return sum(token in answer_tokens for token in wanted) / len(wanted)


def cited_docids(obj: dict) -> set[str]:
    refs = obj.get("references", [])
    out = set()
    for item in obj.get("answer", []):
        for citation in item.get("citations", []):
            if isinstance(citation, int) and 0 <= citation < len(refs):
                out.add(refs[citation])
            elif isinstance(citation, str):
                out.add(citation)
    return out


def parent_docid(unit_id: object) -> str:
    """Collapse a retrieved chunk id the same way the submission formatter does."""
    return re.sub(r"_p\d+$", "", str(unit_id or ""))


def facts_from(obj: dict) -> list[dict]:
    out = []
    for step in obj.get("trace", {}).get("steps", []):
        arguments = step.get("arguments") or {}
        if not isinstance(arguments, dict):
            continue
        for document in arguments.get("documents", []):
            if not isinstance(document, dict):
                continue
            for fact in document.get("facts", []):
                if isinstance(fact, dict):
                    out.append({"docid": document.get("id"), **fact})
    return out


def answer_metrics(obj: dict) -> dict[str, float]:
    text = answer_text(obj)
    words = text.split()
    return {
        "words": len(words),
        "digits_per_1k": 1000 * len(DIGIT_RE.findall(text)) / max(1, len(words)),
        "vague_per_1k": 1000 * len(VAGUE_RE.findall(text)) / max(1, len(words)),
        "refs": len(obj.get("references", [])),
    }


def structural_pair(runs: dict[str, dict[str, dict]], control: str, arm: str) -> None:
    qids = sorted(set(runs[control]) & set(runs[arm]))
    print(f"## Answer structure: {control} -> {arm}")
    totals = collections.defaultdict(list)
    for qid in qids:
        left = answer_metrics(runs[control][qid])
        right = answer_metrics(runs[arm][qid])
        print(
            f"  {qid}\twords {left['words']:.0f}->{right['words']:.0f}"
            f"\tdigits/1k {left['digits_per_1k']:.2f}->{right['digits_per_1k']:.2f}"
            f"\tvague/1k {left['vague_per_1k']:.2f}->{right['vague_per_1k']:.2f}"
            f"\trefs {left['refs']:.0f}->{right['refs']:.0f}"
        )
        for key in left:
            totals[("control", key)].append(left[key])
            totals[("arm", key)].append(right[key])
    for key in ("words", "digits_per_1k", "vague_per_1k", "refs"):
        left = totals[("control", key)]
        right = totals[("arm", key)]
        print(
            f"  mean {key}: {sum(left) / len(left):.3f} -> "
            f"{sum(right) / len(right):.3f}"
        )


def fact_carrythrough(runs: dict[str, dict[str, dict]], run_id: str) -> None:
    print(f"## Fact carry-through: {run_id}")
    aggregate = collections.Counter()
    for qid, obj in sorted(runs[run_id].items()):
        facts = facts_from(obj)
        answer = answer_text(obj)
        answer_norm = normalized(answer)
        citations = cited_docids(obj)
        stats = collections.Counter()
        for fact in facts:
            value = str(fact.get("value") or "")
            stats["facts"] += 1
            stats["cited_doc"] += parent_docid(fact.get("docid")) in citations
            stats["exact_value"] += bool(value and normalized(value) in answer_norm)
            stats["lexical_60"] += token_recall(value, answer) >= 0.60
            numbers = DIGIT_RE.findall(value)
            if numbers:
                stats["numeric_facts"] += 1
                answer_numbers = set(DIGIT_RE.findall(answer))
                stats["numeric_carried"] += any(number in answer_numbers
                                                for number in numbers)
        aggregate.update(stats)
        print(
            f"  {qid}\tfacts={stats['facts']} cited_doc={stats['cited_doc']} "
            f"exact={stats['exact_value']} lexical60={stats['lexical_60']} "
            f"numeric={stats['numeric_carried']}/{stats['numeric_facts']}"
        )
    print("  aggregate", dict(aggregate))
    if aggregate["facts"]:
        print(
            "  rates "
            f"cited_doc={aggregate['cited_doc'] / aggregate['facts']:.1%} "
            f"exact={aggregate['exact_value'] / aggregate['facts']:.1%} "
            f"lexical60={aggregate['lexical_60'] / aggregate['facts']:.1%} "
            f"numeric={aggregate['numeric_carried'] / max(1, aggregate['numeric_facts']):.1%}"
        )


def main() -> None:
    baseline_format()
    criterion_transitions("sol-default", "sol-finish-the-claim")
    criterion_transitions("v2l-default", "v2l-facts")
    wanted = {
        "v2-dev30-default",
        "sol-dev30-finish-the-claim",
        "v2l-dev30-default",
        "v2l-dev30-facts",
    }
    runs = load_runs(wanted)
    structural_pair(runs, "v2-dev30-default", "sol-dev30-finish-the-claim")
    structural_pair(runs, "v2l-dev30-default", "v2l-dev30-facts")
    fact_carrythrough(runs, "v2l-dev30-facts")


if __name__ == "__main__":
    main()
