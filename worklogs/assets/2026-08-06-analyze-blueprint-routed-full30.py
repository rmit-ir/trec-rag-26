"""Paired full-30 diagnostics for the frozen blueprint routing experiment."""
from __future__ import annotations

import json
import random
import statistics as st
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs/auto-optimize/rubric-results.jsonl"
ROUTES = (
    ROOT
    / "worklogs/assets/2026-08-06-aus-agent-v2-blueprint-router-v2-dev30.jsonl"
)
CONTROL = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
ARM = "sol-aus-v2-blueprint-routed-dev30-20260806"


def load_result(variant: str) -> dict:
    """Select the latest durable evaluation row for one exact variant."""
    matches = [
        json.loads(line)
        for line in RESULTS.read_text().splitlines()
        if line.strip() and json.loads(line).get("variant") == variant
    ]
    if not matches:
        raise RuntimeError(f"missing result {variant}")
    return matches[-1]


control = load_result(CONTROL)
arm = load_result(ARM)
routes = {
    row["qid"]: row["route"]
    for row in (json.loads(line) for line in ROUTES.read_text().splitlines())
    if row.get("qid") and row.get("route")
}

if set(control["per_topic"]) != set(arm["per_topic"]):
    raise RuntimeError("control and routed arm do not cover the same full 30 topics")
if set(routes) != set(control["per_topic"]):
    raise RuntimeError("frozen routes do not cover the evaluated full 30 topics")

rows = []
for qid in sorted(control["per_topic"]):
    before = control["per_topic"][qid]
    after = arm["per_topic"][qid]
    rows.append((qid, routes[qid], before, after, after - before))

print("qid\troute\tresearch_first\trouted\tdelta")
for qid, route, before, after, delta in rows:
    print(f"{qid}\t{route}\t{before:.4f}\t{after:.4f}\t{delta:+.4f}")

print("\naggregates")
for route in ("evidence_blueprint", "continuous_synthesis", "ALL"):
    selected = rows if route == "ALL" else [row for row in rows if row[1] == route]
    deltas = [row[4] for row in selected]
    print(
        f"{route}\tn={len(selected)}\t"
        f"control={st.mean(row[2] for row in selected):.4f}\t"
        f"routed={st.mean(row[3] for row in selected):.4f}\t"
        f"delta={st.mean(deltas):+.4f}\t"
        f"wins={sum(delta > 0 for delta in deltas)}\t"
        f"losses={sum(delta < 0 for delta in deltas)}"
    )

rng = random.Random(20260806)
deltas = [row[4] for row in rows]
boot = sorted(
    st.mean(rng.choice(deltas) for _ in deltas)
    for _ in range(50_000)
)
print(
    "paired_bootstrap_95_ci\t"
    f"[{boot[int(0.025 * len(boot))]:+.4f}, "
    f"{boot[int(0.975 * len(boot))]:+.4f}]"
)

print("\naxis\tresearch_first\trouted\tdelta")
axis_before: dict[str, list[float]] = defaultdict(list)
axis_after: dict[str, list[float]] = defaultdict(list)
for qid, *_ in rows:
    for axis, value in control["per_topic_axis"][qid].items():
        axis_before[axis].append(value)
    for axis, value in arm["per_topic_axis"][qid].items():
        axis_after[axis].append(value)
for axis in sorted(set(axis_before) | set(axis_after)):
    before = st.mean(axis_before[axis])
    after = st.mean(axis_after[axis])
    print(f"{axis}\t{before:.4f}\t{after:.4f}\t{after-before:+.4f}")
