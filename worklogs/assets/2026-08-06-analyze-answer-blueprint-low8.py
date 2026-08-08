"""Paired diagnostics for the evidence-to-answer blueprint low-eight gate."""
from __future__ import annotations

import json
import random
import statistics as st
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs/auto-optimize/rubric-results.jsonl"
TOPICS = ROOT / "data/task-comparison/topics-aus-v2-low8.tsv"
CONTROL = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
ARM = "sol-aus-v2-answer-blueprint-low8-20260806"


def load(variant: str) -> dict:
    rows = [
        json.loads(line) for line in RESULTS.read_text().splitlines()
        if line.strip() and json.loads(line).get("variant") == variant
    ]
    if not rows:
        raise RuntimeError(f"missing result {variant}")
    return rows[-1]


control = load(CONTROL)
arm = load(ARM)
qids = [line.split("\t", 1)[0] for line in TOPICS.read_text().splitlines()
        if line.strip()]
rows = []
print("qid\tresearch_first\tanswer_blueprint\tdelta")
for qid in qids:
    before = control["per_topic"][qid]
    after = arm["per_topic"][qid]
    rows.append((qid, before, after, after - before))
    print(f"{qid}\t{before:.4f}\t{after:.4f}\t{after-before:+.4f}")

deltas = [row[3] for row in rows]
print(
    "\naggregate\t"
    f"n={len(rows)}\tcontrol={st.mean(row[1] for row in rows):.4f}\t"
    f"blueprint={st.mean(row[2] for row in rows):.4f}\t"
    f"delta={st.mean(deltas):+.4f}\t"
    f"wins={sum(delta > 0 for delta in deltas)}\t"
    f"losses={sum(delta < 0 for delta in deltas)}"
)

rng = random.Random(20260806)
boot = sorted(
    st.mean(rng.choice(deltas) for _ in deltas)
    for _ in range(50_000)
)
print(
    "paired_bootstrap_95_ci\t"
    f"[{boot[int(.025*len(boot))]:+.4f}, "
    f"{boot[int(.975*len(boot))]:+.4f}]"
)

axis_before: dict[str, list[float]] = defaultdict(list)
axis_after: dict[str, list[float]] = defaultdict(list)
for qid in qids:
    for axis, value in control["per_topic_axis"][qid].items():
        axis_before[axis].append(value)
    for axis, value in arm["per_topic_axis"][qid].items():
        axis_after[axis].append(value)
print("\naxis\tresearch_first\tanswer_blueprint\tdelta")
for axis in sorted(set(axis_before) | set(axis_after)):
    before = st.mean(axis_before[axis])
    after = st.mean(axis_after[axis])
    print(f"{axis}\t{before:.4f}\t{after:.4f}\t{after-before:+.4f}")
