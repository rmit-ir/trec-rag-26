"""Paired full-30 diagnostics for the frozen adaptive routing experiment."""
from __future__ import annotations

import json
import random
import statistics as st
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs/auto-optimize/rubric-results.jsonl"
ROUTES = ROOT / "worklogs/assets/2026-08-06-aus-agent-v2-adaptive-router-dev30.jsonl"
CONTROL = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
ARM = "sol-aus-v2-adaptive-dev30-20260806"


def load_result(variant: str) -> dict:
    matches = [
        json.loads(line) for line in RESULTS.read_text().splitlines()
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

rows = []
for qid in sorted(control["per_topic"]):
    old = control["per_topic"][qid]
    new = arm["per_topic"][qid]
    rows.append((qid, routes[qid], old, new, new - old))

print("qid\troute\tresearch_first\tadaptive\tdelta")
for qid, route, old, new, delta in rows:
    print(f"{qid}\t{route}\t{old:.4f}\t{new:.4f}\t{delta:+.4f}")

print("\naggregates")
for route in ("parallel_evidence", "integrated_research", "ALL"):
    selected = rows if route == "ALL" else [row for row in rows if row[1] == route]
    deltas = [row[4] for row in selected]
    print(
        f"{route}\tn={len(selected)}\t"
        f"control={st.mean(row[2] for row in selected):.4f}\t"
        f"adaptive={st.mean(row[3] for row in selected):.4f}\t"
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

print("\naxis_delta")
for axis in sorted(set(control["axis"]) | set(arm["axis"])):
    before = control["axis"].get(axis, float("nan"))
    after = arm["axis"].get(axis, float("nan"))
    print(f"{axis}\t{before:.4f}\t{after:.4f}\t{after - before:+.4f}")
