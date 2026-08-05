#!/usr/bin/env python3
"""How does aus_agent actually spend its search budget?

Result 9 of `worklogs/2026-08-04-test119-vs-official-baselines.md`. Reads
`data/outputs/aus_agent/*.trajectory.json` (not archived away) and reports, per
run: rounds per topic, searches per round, and — the number that motivated the
whole section — how often the agent points *both* engines at the *same lead*.

A "round" here is a maximal run of consecutive `search` calls, delimited by a
reasoning item or a `commit_context` call. That matches the staging contract:
everything staged in one round must be committed on the immediately following
turn, so a round is exactly the unit `commit_context` reviews at once.

"Same lead" is approximated by query token Jaccard >= 0.5 between two searches
in one round issued to *different* engines. It is a loose proxy — the agent
rewords per engine by design — but it is loose in the generous direction, so a
low number is meaningful.

    uv run --no-project python \
        worklogs/assets/2026-08-04-search-strategy-diagnosis.py
"""
from __future__ import annotations

import collections
import glob
import itertools
import json
import statistics as st
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
RUNS = ["cmp-base-densesparse", "promptab-default", "promptab-firsthand",
        "chunknav-dev10", "dev-dense-30", "dev-keyword-30",
        "test-semantic-119", "test-keyword-119"]
PAIR_THRESHOLD = 0.5


def query_similarity(a: str, b: str) -> float:
    xs, ys = set(a.lower().split()), set(b.lower().split())
    return len(xs & ys) / len(xs | ys) if xs | ys else 0.0


def rounds_for(traj: dict) -> tuple[list[list[tuple[str, str]]], int]:
    """Split a trajectory into rounds of (engine, query) plus a commit count."""
    rounds: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    commits = 0
    for msg in traj.get("raw_messages", []):
        if not isinstance(msg, dict):
            continue
        if msg.get("name") == "search":
            args = json.loads(msg["arguments"])
            current.append((args.get("search_engine"), args.get("query", "")))
            continue
        if msg.get("name") == "commit_context":
            commits += 1
        if msg.get("type") == "reasoning" or msg.get("name") == "commit_context":
            if current:
                rounds.append(current)
                current = []
    if current:
        rounds.append(current)
    return rounds, commits


def analyse(run_id: str) -> dict | None:
    per_topic_rounds, per_round_size, commits, totals = [], [], [], []
    engines: collections.Counter = collections.Counter()
    dual_engine_rounds = paired_lead_rounds = all_rounds = 0
    statuses: collections.Counter = collections.Counter()
    for path in sorted(glob.glob(str(ROOT / "data/outputs/aus_agent/*.output.json"))):
        meta = json.load(open(path, encoding="utf-8")).get("metadata", {})
        if meta.get("run_id") != run_id:
            continue
        try:
            traj = json.load(open(path.replace(".output.json", ".trajectory.json"),
                                  encoding="utf-8"))
        except FileNotFoundError:
            continue
        statuses[traj.get("status")] += 1
        rounds, n_commits = rounds_for(traj)
        per_topic_rounds.append(len(rounds))
        commits.append(n_commits)
        totals.append(sum(len(r) for r in rounds))
        for group in rounds:
            all_rounds += 1
            per_round_size.append(len(group))
            engines.update(e for e, _ in group)
            if len({e for e, _ in group}) > 1:
                dual_engine_rounds += 1
                best = max((query_similarity(q1, q2)
                            for (e1, q1), (e2, q2) in itertools.combinations(group, 2)
                            if e1 != e2), default=0.0)
                if best >= PAIR_THRESHOLD:
                    paired_lead_rounds += 1
    if not per_topic_rounds:
        return None
    return {
        "topics": len(per_topic_rounds),
        "rounds": st.mean(per_topic_rounds),
        "searches": st.mean(totals),
        "per_round": st.mean(per_round_size),
        "commits": st.mean(commits),
        "dual_rounds": dual_engine_rounds / all_rounds if all_rounds else 0.0,
        "paired_rounds": paired_lead_rounds / all_rounds if all_rounds else 0.0,
        "engines": dict(engines),
        "statuses": dict(statuses),
    }


def main() -> int:
    print(f"{'run':24s} {'topics':>6s} {'rounds':>7s} {'searches':>9s} "
          f"{'/round':>7s} {'commits':>8s} {'both-eng':>9s} {'same-lead':>10s}")
    rows = {}
    for run_id in RUNS:
        row = analyse(run_id)
        if not row:
            continue
        rows[run_id] = row
        print(f"{run_id:24s} {row['topics']:>6d} {row['rounds']:>7.1f} "
              f"{row['searches']:>9.1f} {row['per_round']:>7.1f} {row['commits']:>8.1f} "
              f"{row['dual_rounds']:>8.0%} {row['paired_rounds']:>10.0%}")
    print("\n'both-eng'  = share of rounds using more than one engine at all")
    print(f"'same-lead' = share of rounds where two searches to DIFFERENT engines had"
          f" query Jaccard >= {PAIR_THRESHOLD}")
    print("\nengine mix and termination status per run:")
    for run_id, row in rows.items():
        print(f"  {run_id:24s} {row['engines']}  {row['statuses']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
