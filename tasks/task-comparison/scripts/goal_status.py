#!/usr/bin/env python3
"""Decide, mechanically, whether the optimization goal is met. Exit 0 if it is.

This exists so ``/goal`` has something to *read* rather than something to judge.
A Stop hook that has to infer "are we done?" from the conversation will get it
wrong in both directions — declaring victory on a lucky single-judge run, or
looping forever past the point where the evidence says stop. Every condition
below is computed from files on disk, and the last line is a single verdict
token.

Prints one of:

    GOAL MET          — all five conditions hold; stop.
    BUDGET EXCEEDED   — spend passed the operator's cap; stop and ask.
    NOT MET           — keep going; the reasons are listed above the verdict.

**Only the score and the budget can stop this loop.** An earlier version also
emitted EXHAUSTED once every single-factor prompt patch had been screened
without one banking, on the theory that a dry search space is a reason to stop.
That was wrong: "we have run out of ideas of one particular kind" is a judgement
for the operator, not for the scoreboard. Prompt patches are one lever among
several — tool changes, model choice, reasoning effort, retrieval — and a loop
that halts when the first lever runs dry stops before the others are tried. The
patch ledger is still reported, as information.

The budget check remains a *stop* condition rather than a warning. An autonomous
loop with a scoreboard and no cap is the one shape of this system that can spend
an unbounded amount of money while looking like it is working.

    uv run --no-project python tasks/task-comparison/scripts/goal_status.py
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
RESULTS = ROOT / "docs/auto-optimize/rubric-results.jsonl"
PATCHES = ROOT / "docs/auto-optimize/patches.md"
OUTPUTS_BY_SYSTEM = {
    "aus_agent": ROOT / "data/outputs/aus_agent",
    "aus_agent_v2": ROOT / "data/outputs/aus_agent_v2",
}

# Goal conditions agreed 2026-08-05 (docs/auto-optimize/README.md).
MEAN_SCORE = 0.80
TOPIC_FLOOR = 0.65
BUDGET_USD = 300.0
N_TOPICS = 30
# The cap covers THIS optimization loop, not the repository's whole history.
# Artifacts from earlier projects sit in aus_agent's directory and would
# otherwise charge months of unrelated work against the budget.  aus_agent_v2
# was created by this optimization session, so every artifact under it is in
# scope; restricting it to ``dev30-`` silently omitted all architecture probes.
# Substring, not prefix: the loop has spawned several run families
# (rubric-dev30-*, sol-dev30-*, v2-dev30-*, v2l-dev30-*) and a prefix match
# would quietly stop charging the newer ones against the cap.
RUN_PREFIX = "dev30-"


def rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    return [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _rates_for(model: str):
    """Rates for a model, matched by region when one is derivable.

    Falls back to a unique table for that model across regions: these are
    published list prices that do not vary by region, and a run whose region
    cannot be recovered from the artifact should still be counted against the
    cap rather than silently costing nothing.
    """
    from ragrun.pricing import PRICES_DIR, UnknownRate, load_rates
    import os
    match = re.search(r"\.([a-z]{2}-[a-z]+-\d)\.",
                      os.environ.get("OPENAI_BASE_URL", "") or "")
    if match:
        try:
            return load_rates(model, match.group(1))
        except UnknownRate:
            pass
    regions = {json.loads(p.read_text(encoding="utf-8")).get("region")
               for p in PRICES_DIR.glob("*.json")
               if json.loads(p.read_text(encoding="utf-8")).get("model_id") == model}
    regions.discard(None)
    if len(regions) == 1:
        return load_rates(model, regions.pop())
    raise UnknownRate(f"no unique rate table for {model!r}")


def agent_spend(
    prefix: str = RUN_PREFIX,
) -> tuple[float, int, int, dict[str, float]]:
    """Return USD/counts plus a per-system generation-cost breakdown.

    Priced from each artifact's ``trace.summary.tokens``, NOT from its
    ``trace.summary.cost``. The cost block only covers turns that carried a
    cost — runs generated before per-turn costing existed have complete token
    counts and an empty cost block, so summing cost understated real spend by
    45% on the first 30-topic run. Tokens are the authoritative record and are
    present on every artifact; pricing from them makes historical and current
    runs comparable and keeps the budget cap honest.
    """
    from ragrun.pricing import call_cost
    total, priced_topics, unpriced_topics = 0.0, 0, 0
    by_system = {system: 0.0 for system in OUTPUTS_BY_SYSTEM}
    for system, output_dir in OUTPUTS_BY_SYSTEM.items():
        for path in glob.glob(str(output_dir / "*.output.json")):
            try:
                obj = json.loads(Path(path).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            run_id = str(obj.get("metadata", {}).get("run_id", ""))
            if system == "aus_agent" and prefix not in run_id:
                continue
            trace = obj.get("trace") or {}
            tokens = (trace.get("summary") or {}).get("tokens") or {}
            # The model id is in trace.metadata, NOT the strict output metadata
            # (which carries only submission fields and run identifiers).
            model = (trace.get("metadata") or {}).get("model")
            if not tokens or not model:
                continue
            try:
                cost = call_cost(
                    {"input_uncached": tokens.get("input_uncached", 0),
                     "output": tokens.get("output", 0),
                     "cache_read": tokens.get("cache_read", 0),
                     "cache_write": tokens.get("cache_write", 0)},
                    _rates_for(model),
                )
            except Exception:  # noqa: BLE001 — unpriced is a normal state
                unpriced_topics += 1
                continue
            usd = float((cost or {}).get("usd") or 0.0)
            total += usd
            by_system[system] += usd
            priced_topics += 1
    return total, priced_topics, unpriced_topics, by_system


def judge_spend(all_rows: list[dict]) -> tuple[float, int]:
    total, unknown = 0.0, 0
    for row in all_rows:
        usd = row.get("judge_usd")
        if usd is None:
            unknown += 1
        else:
            total += float(usd)
    return total, unknown


def patch_status() -> dict[str, int]:
    """Counts from the ledger table, so the exhaustion clause is data-driven."""
    counts = {"untested": 0, "banked": 0, "killed": 0, "inconclusive": 0}
    if not PATCHES.exists():
        return counts
    for line in PATCHES.read_text(encoding="utf-8").splitlines():
        # Statuses are written in bold in the ledger for readability, so strip
        # emphasis before matching -- otherwise every banked patch reads as
        # untested and the exhaustion clause fires on a loop that is working.
        match = re.match(r"\|\s*`([a-z-]+)`\s*\|\s*\**(\w+)\**\s*\|", line)
        if match and match.group(2) in counts:
            counts[match.group(2)] += 1
    return counts


def best_row(all_rows: list[dict]) -> dict | None:
    """Highest mean score among FULL runs. A partial run is not a candidate.

    A 12-topic run can beat a 30-topic one on mean alone; letting it win the
    goal would be scoring the sample, not the system.
    """
    full = [r for r in all_rows if r.get("topics") == N_TOPICS]
    return max(full, key=lambda r: r.get("mean_score", -9)) if full else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=BUDGET_USD)
    parser.add_argument("--mean", type=float, default=MEAN_SCORE)
    parser.add_argument("--floor", type=float, default=TOPIC_FLOOR)
    parser.add_argument("--run-prefix", default=RUN_PREFIX,
                        help="only count runs whose run_id starts with this "
                             "against the budget cap")
    args = parser.parse_args()

    all_rows = rows()
    agent_usd, priced, unpriced, agent_by_system = agent_spend(args.run_prefix)
    judge_usd, unknown = judge_spend(all_rows)
    spent = agent_usd + judge_usd

    print("=== spend ===")
    print(f"  agent  ${agent_usd:8.2f}   ({priced} topics priced from tokens"
          + (f", {unpriced} UNPRICED — true spend is higher" if unpriced else "")
          + ")")
    for system, usd in agent_by_system.items():
        print(f"    {system:<12} ${usd:8.2f}")
    print(f"  judge  ${judge_usd:8.2f}"
          + (f"   ({unknown} eval rows with no price)" if unknown else ""))
    print(f"  total  ${spent:8.2f} / ${args.budget:.2f} cap "
          f"({spent / args.budget:.1%})")

    best = best_row(all_rows)
    print(f"\n=== best full {N_TOPICS}-topic run ===")
    if best is None:
        print(f"  none yet ({len(all_rows)} eval rows, none covering "
              f"{N_TOPICS} topics)")
    else:
        print(f"  variant={best['variant']}  judge={best['judge']}  "
              f"mean={best['mean_score']:.4f}")

    failures: list[str] = []
    if best is None:
        failures.append(f"no full {N_TOPICS}-topic evaluation yet")
    else:
        if best["mean_score"] < args.mean:
            failures.append(f"mean {best['mean_score']:.4f} < {args.mean:.2f}")
        if best.get("topics_below_065", 99) > 0:
            failures.append(
                f"{best['topics_below_065']} topic(s) below {args.floor}")
        if best.get("severe_penalties", 99) > 0:
            failures.append(
                f"{best['severe_penalties']} satisfied |w|>=4 penalty(ies)")
        if best.get("over_word_cap", 99) > 0:
            failures.append(f"{best['over_word_cap']} answer(s) over 1,024 words")
        judges = {r["judge"] for r in all_rows
                  if r.get("variant") == best["variant"]
                  and r.get("topics") == N_TOPICS}
        if len(judges) < 2:
            failures.append(
                f"confirmed by {len(judges)} judge model(s), needs 2 "
                f"(have: {sorted(judges)})")

    counts = patch_status()
    print(f"\n=== patch ledger ===")
    print(f"  banked {counts['banked']}  killed {counts['killed']}  "
          f"inconclusive {counts['inconclusive']}  untested {counts['untested']}")

    print("\n=== conditions ===")
    for reason in failures:
        print(f"  FAIL  {reason}")
    if not failures:
        print("  all five conditions hold")

    # Budget outranks everything: a met goal is still met, but an unmet goal
    # must not keep spending past the cap the operator set.
    if spent >= args.budget and failures:
        print(f"\nBUDGET EXCEEDED")
        return 1
    if not failures:
        print(f"\nGOAL MET")
        return 0
    if counts["untested"] == 0:
        print("  note: every single-factor prompt patch has been screened. "
              "That is information, not a stop — other levers remain (tool "
              "changes, reasoning effort, model, retrieval).")
    print(f"\nNOT MET")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
