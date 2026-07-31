#!/usr/bin/env python3
"""Every number in `worklogs/2026-07-31-bm25-consensus-qrels.md`, recomputed.

Reads only committed-shape artifacts under the Stage-A run dir, so the worklog's
judgment calls stay checkable after the session ends:

  consensus-pairs.jsonl        per-pair votes + status (the audit trail)
  scores.csv                   single-judge matrix   (facet-name-v1)
  scores-consensus.csv         consensus matrix      (qrels-consensus.txt)
  scores-per-query.csv         per-(config, query) values behind both
  scores-per-query-consensus.csv

Run:
  python worklogs/assets/2026-07-31-consensus-analysis.py \
      data/bm25-tune/runs/20260731T103000-stageA
"""
from __future__ import annotations

import collections
import csv
import json
import statistics
import sys
from pathlib import Path

METRIC = "ndcg10_exp"
BASELINE = "k1_0.9__b_0.4"
# The three votes, in the order `consensus.combine_pair` records them. Note a
# `single`-status pair (one prompt parse-failed) stores a 1-tuple, so `grades[i]`
# is NOT a safe way to attribute a vote to a prompt — per-prompt distributions
# below come from the cache snapshots, which name their prompt on every row.
VOTES = ("facet-name-v1", "facet-rare3-v1", "facet-v1")
ROLES = ("primary", "secondary", "tiebreak")


def load_pairs(run: Path) -> list[dict]:
    with (run / "consensus-pairs.jsonl").open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_snapshot(run: Path, prompt_version: str) -> dict[tuple[str, str], int]:
    """A prompt's `qrels-<pv>.jsonl` as `(topic, chunk) -> grade`.

    The snapshot is experiment-wide, so callers must intersect it with the run's
    pool — it also carries WP6's calibration sample, which no config retrieved.
    """
    path = (run.parent.parent / "judgments" / "cache"
            / f"qrels-{prompt_version}.jsonl")
    out: dict[tuple[str, str], int] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "cache_meta" or row.get("grade") is None:
                continue
            jkey = row.get("jkey")
            if jkey:
                _, topic, chunk = jkey.split("::", 2)
            else:
                topic, chunk = row["topic_id"], row["chunk_id"]
            out[(topic, chunk)] = int(row["grade"])
    return out


def load_matrix(path: Path) -> dict[str, float]:
    with path.open(encoding="utf-8") as fh:
        return {r["config"]: float(r[METRIC]) for r in csv.DictReader(fh)}


def load_per_query(path: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = collections.defaultdict(dict)
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            value = row.get(METRIC)
            if value not in (None, ""):
                out[row["config"]][row["qkey"]] = float(value)
    return out


def histogram(grades: list[int]) -> tuple[dict[int, int], float]:
    counts = collections.Counter(grades)
    mean = sum(g * n for g, n in counts.items()) / max(len(grades), 1)
    return dict(sorted(counts.items())), mean


def main(run: Path) -> None:
    pairs = load_pairs(run)
    print(f"# {run.name}\n")

    print(f"pairs: {len(pairs)}")
    print("status:", dict(sorted(collections.Counter(
        p["status"] for p in pairs).items())), "\n")

    # --- inter-judge agreement, over pairs both of the first two graded ------
    delta = collections.Counter()
    shapes = collections.Counter()
    for pair in pairs:
        votes = pair["grades"]
        if len(votes) < 2 or votes[0] is None or votes[1] is None:
            continue
        gap = abs(votes[0] - votes[1])
        delta[gap] += 1
        if gap >= 2:
            shapes[tuple(sorted(votes[:2]))] += 1
    total = sum(delta.values())
    print(f"## primary-vs-secondary agreement (n={total})")
    for gap in sorted(delta):
        print(f"  |d|={gap}: {delta[gap]:6d}  {100 * delta[gap] / total:5.1f}%")
    print("  conflict shapes:", dict(sorted(shapes.items())), "\n")

    # --- what each prompt's scale looks like on the SAME passages -----------
    pool = {(p["topic_id"], p["chunk_id"]) for p in pairs}
    per_prompt = {pv: {k: g for k, g in load_snapshot(run, pv).items()
                       if k in pool} for pv in VOTES}
    # The tiebreak only *voted* on the escalated conflicts. Its snapshot also
    # holds in-pool pairs it graded during WP6 calibration, which decided
    # nothing here — restrict it to the votes that actually broke a tie.
    escalated = {(p["topic_id"], p["chunk_id"]) for p in pairs
                 if p["status"] == "resolved"}
    per_prompt[VOTES[2]] = {k: g for k, g in per_prompt[VOTES[2]].items()
                            if k in escalated}
    print("## grade distributions (systematic bias, not noise)")
    for pv, role in zip(VOTES, ROLES):
        counts, mean = histogram(list(per_prompt[pv].values()))
        label = f"{pv} ({role})"
        print(f"  {label:30} n={len(per_prompt[pv]):6d} {counts} mean={mean:.3f}")
    final = [p["consensus"] for p in pairs if p["consensus"] is not None]
    counts, mean = histogram(final)
    print(f"  {'CONSENSUS':30} n={len(final):6d} {counts} mean={mean:.3f}\n")

    # --- how the tiebreak actually voted on each conflict shape -------------
    resolved = [p for p in pairs if p["status"] == "resolved"]
    print(f"## tiebreak outcomes (n={len(resolved)})")
    outcome = collections.Counter(
        (tuple(sorted(p["grades"][:2])), p["consensus"]) for p in resolved)
    for (votes, final_grade), n in sorted(outcome.items()):
        print(f"  votes {votes} + tiebreak -> {final_grade}: {n}")
    print()

    # --- coverage: the ensemble repairs each prompt's parse failures ---------
    print("## coverage (a parse failure in one prompt is covered by the other)")
    for pv in VOTES[:2]:
        print(f"  {pv:30} {len(per_prompt[pv])}/{len(pairs)} pooled pairs graded")
    both = per_prompt[VOTES[0]].keys() | per_prompt[VOTES[1]].keys()
    print(f"  {'union (CONSENSUS)':30} {len(both)}/{len(pairs)}"
          f"  single-vote pairs: "
          f"{sum(1 for p in pairs if p['status'] == 'single')}\n")

    # --- did the label set change the ranking? ------------------------------
    single = load_matrix(run / "scores.csv")
    cons = load_matrix(run / "scores-consensus.csv")
    rank_s = sorted(single, key=lambda c: -single[c])
    rank_c = sorted(cons, key=lambda c: -cons[c])
    print(f"## {METRIC}: single-judge vs consensus")
    print(f"  {'config':18} {'single':>8} {'rk':>3} {'cons':>8} {'rk':>3} "
          f"{'dRank':>6}")
    for config in rank_s:
        print(f"  {config:18} {single[config]:8.4f} {rank_s.index(config) + 1:3d} "
              f"{cons[config]:8.4f} {rank_c.index(config) + 1:3d} "
              f"{rank_s.index(config) - rank_c.index(config):+6d}")
    n = len(rank_s)
    d2 = sum((rank_s.index(c) - rank_c.index(c)) ** 2 for c in rank_s)
    print(f"\n  Spearman rho = {1 - 6 * d2 / (n * (n * n - 1)):.4f} over {n} cells")
    for label, matrix, order in (("single", single, rank_s),
                                 ("consensus", cons, rank_c)):
        print(f"  {label:9} winner={order[0]} {matrix[order[0]]:.4f}  "
              f"baseline={matrix[BASELINE]:.4f} "
              f"delta={matrix[order[0]] - matrix[BASELINE]:+.4f}  "
              f"baseline_rank={order.index(BASELINE) + 1}  "
              f"spread={matrix[order[0]] - matrix[order[-1]]:.4f}")
    print(f"  top-3 single   : {rank_s[:3]}")
    print(f"  top-3 consensus: {rank_c[:3]}\n")

    # --- paired per-query spread: is the winner's margin real? -------------
    print(f"## winner vs {BASELINE}, paired per query")
    for label, path in (("single", "scores-per-query.csv"),
                        ("consensus", "scores-per-query-consensus.csv")):
        per_query = load_per_query(run / path)
        winner = (rank_s if label == "single" else rank_c)[0]
        keys = sorted(set(per_query[BASELINE]) & set(per_query[winner]))
        diffs = [per_query[winner][q] - per_query[BASELINE][q] for q in keys]
        wins = sum(1 for d in diffs if d > 1e-9)
        losses = sum(1 for d in diffs if d < -1e-9)
        print(f"  {label:9} n={len(keys)} mean={statistics.mean(diffs):+.5f} "
              f"sd={statistics.stdev(diffs):.4f} "
              f"win/loss/tie={wins}/{losses}/{len(diffs) - wins - losses}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1
              else "data/bm25-tune/runs/20260731T103000-stageA"))
