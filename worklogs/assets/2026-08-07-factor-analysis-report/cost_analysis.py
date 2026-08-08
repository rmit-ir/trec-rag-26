#!/usr/bin/env python3
"""Per-cell and per-factor cost accounting for the brief_revise_agent
factorial/hill-climb workstream (worklogs/2026-08-07-brief-revise-agent-
llm-factorial-design.md sections 1-21 -- NOT the earlier, separately-
reported round B/C/D improvement-loop thread, whose cells are reused here
at zero marginal cost, not re-billed).

`processed_tokens` (agent_harness.agent's own trajectory summary field) is
INPUT+OUTPUT combined already (`_usage_token_stats(usage)["processed"]` =
uncached_input + cache_write + output -- read directly from
src/agent_harness/agent.py). Real per-topic values only exist in the
tee'd stdout logs this session captured under each job's scratchpad/ dir
(never persisted into output.json/trajectory.json) -- this script
re-derives them from those logs rather than reconstructing figures from
memory.

Rates (all placeholders except Bedrock's, see module docstring in the
worklog itself for the full caveat): OpenAI (luna/terra/sol) has NO real
rate card in this repo for gpt-5.6-* -- $5/1M blended across input+output
(likely an UNDERESTIMATE since output is usually priced ~4x input; treat
as a consistent RELATIVE proxy for comparing cells, not an absolute
dollar figure). Bedrock (gpt-oss-120b, qwen) uses the real metered
rate-card file's midpoint (gpt-oss-120b's own file; qwen has no rate file
in this repo, uses the same tier as a documented placeholder). Judge
calls: $0.15/call flat estimate (this session's observed range for
standalone/selector/design calls).

Usage: uv run --group notebook python \
    worklogs/assets/2026-08-07-factor-analysis-report/cost_analysis.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LOG_DIRS = [Path("/tmp/claude-200103037/-home-el7-E103037-repos-trec-rag-26")]
EVAL_DIR = REPO / "evaluation-results/factorial"

OPENAI_RATE_PER_1M = 5.0
BEDROCK_BLENDED_PER_1K = (0.0001545 + 0.000618) / 2
JUDGE_CALL_USD = 0.15

RUN_ID_RE = re.compile(r"run_id=(\S+)")
TOKENS_RE = re.compile(r'"processed_tokens":\s*(\d+)')
BACKEND_RE = re.compile(r"starting:.*backend=(\S+)\s+model=(\S+)")

# Every run_id newly generated THIS workstream (sections 1-21) -> its
# factor-group label (matches section 17's grouping) for the cost-
# effectiveness rollup. Cells reused from the earlier round B/C/D thread
# or from other systems' pre-existing baselines are listed separately in
# REUSED, at $0 generation cost (already paid for elsewhere).
NEW_CELLS: dict[str, str] = {
    "br-model-main-terra-exp15-b1": "generator_model",
    "br-model-main-sol-exp15-b1": "generator_model (BASE)",
    "br-model-main-oss120b-exp15-b1": "generator_model",
    "br-model-main-qwen-exp15-b1": "generator_model",
    "br-divergent-anchor-qwen-adj0-k10-exp15": "adjacent_fetch",
    "br-luna-current-code-exp15": "generator_model",
    "br-hillclimb-sol-adjoff-exp15": "adjacent_fetch",
    "br-hillclimb-sol-preview-exp15": "generic_harness",
    "br-hillclimb-sol-nostage-exp15": "generic_harness",
    "br-hillclimb-sol-jrel-exp15": "generic_harness",
    "br-hillclimb-sol-commitrelease-exp15": "generic_harness",
    "br-hillclimb-sol-widerengines-exp15": "generic_harness",
    "br-hillclimb-sol-jrelcommit-exp15": "generic_harness",
    "br-hillclimb-sol-closurecritic-exp15": "closure_critic",
    "br-replicate-sol-new15": "replication",
    "br-replicate-luna-new15": "replication",
    "br-replicate-sol-rerun-exp15": "replication",
    "br-analystsweep-terra-exp15": "brief_analyst_model",
    "br-analystsweep-oss120b-exp15": "brief_analyst_model",
    "br-analystsweep-qwen-exp15": "brief_analyst_model",
    "br-ensemble-candB-exp15": "ensemble",
    "br-ensemble-candC-exp15": "ensemble",
    "br-ensemble-candD-exp15": "ensemble",
    "br-enginesweep-keyword-exp15": "search_engine",
    "br-enginesweep-semantic-exp15": "search_engine",
    "br-enginesweep-hybrid-exp15": "search_engine",
    "br-enginesweep-hyde-exp15": "search_engine",
}
# run_id -> (system_dir, label) for cells whose GENERATION predates/is
# outside this workstream (reused free) but whose STANDALONE JUDGING was
# newly run here -- generation cost $0, judging cost counts.
REUSED_CELLS: dict[str, tuple[str, str]] = {
    "brief-revise-iter1-exp15": ("brief_revise_agent", "block0_reused"),
    "aus-agent-v2-exp15-luna": ("aus_agent_v2", "baseline_reused"),
    "aus-agent-dev30-luna-e2708ab": ("aus_agent", "baseline_reused"),
    "facets-agent-dev30-e2708ab": ("facets_agent", "baseline_reused"),
}
# The ensemble selector call is a per-topic LLM call not tied to a
# generation run_id -- counted as its own cost line.
SELECTOR_CALLS = {"br-ensemble-bestof4-exp15": 15 * 2}  # 15 topics, ~2 calls avg (1st + some repairs)

SOL_DESIGN_CALLS_USD_EXACT = 0.17 + 0.08 + 0.1212 + 0.1023 + 0.1036 + 0.1036 + 0.1249
TAXONOMY_CALLS_USD_EXACT = 0.33


def find_logs() -> list[Path]:
    out = []
    for d in LOG_DIRS:
        out.extend(d.glob("*/scratchpad/*.log"))
    return out


def parse_log(path: Path) -> dict[str, list]:
    result: dict[str, list] = {}
    current_run_id = None
    current_backend, current_model = "openai", "?"
    for line in path.read_text(errors="ignore").splitlines():
        m = BACKEND_RE.search(line)
        if m:
            current_backend, current_model = m.group(1), m.group(2)
            rm = RUN_ID_RE.search(line)
            if rm:
                current_run_id = rm.group(1)
        m = TOKENS_RE.search(line)
        if m and current_run_id:
            tok = int(m.group(1))
            row = result.setdefault(current_run_id,
                                    [0, 0, current_backend, current_model])
            row[0] += 1
            row[1] += tok
    return result


def gen_cost(tokens: int, backend: str) -> float:
    if backend == "bedrock":
        return tokens / 1000 * BEDROCK_BLENDED_PER_1K
    return tokens / 1e6 * OPENAI_RATE_PER_1M


def _summary_dir(system: str, run_id: str) -> Path:
    baseline = EVAL_DIR / f"baseline-{system}-{run_id}"
    return baseline if baseline.exists() else EVAL_DIR / run_id


def judged_topics(system: str, run_id: str) -> int:
    p = _summary_dir(system, run_id) / "summary.json"
    if not p.exists():
        return 0
    return json.loads(p.read_text()).get("n_completed", 0)


def standalone_score(system: str, run_id: str) -> float | None:
    p = _summary_dir(system, run_id) / "summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("overall_mean")


def main() -> None:
    merged: dict[str, list] = {}
    for log in find_logs():
        for run_id, row in parse_log(log).items():
            if run_id not in NEW_CELLS:
                continue
            prev = merged.get(run_id)
            if prev is None or row[1] > prev[1]:
                merged[run_id] = row

    rows = []
    print(f"{'run_id':42s} {'group':20s} {'n':>3s} {'gen_usd':>8s} "
         f"{'judge_usd':>9s} {'total':>8s} {'score':>6s}")
    total_gen = total_judge = 0.0
    for run_id, group in NEW_CELLS.items():
        row = merged.get(run_id)
        n, tok, backend = (row[0], row[1], row[2]) if row else (0, 0, "?")
        g = gen_cost(tok, backend) if row else 0.0
        j = judged_topics("brief_revise_agent", run_id) * JUDGE_CALL_USD
        score = standalone_score("brief_revise_agent", run_id)
        total_gen += g
        total_judge += j
        rows.append({"run_id": run_id, "group": group, "n_topics": n,
                     "tokens": tok, "backend": backend, "gen_usd": g,
                     "judge_usd": j, "total_usd": g + j, "score": score})
        print(f"{run_id:42s} {group:20s} {n:3d} {g:8.2f} {j:9.2f} "
             f"{g+j:8.2f} {str(score):>6s}")

    print("\n--- reused (generation $0, judging counted) ---")
    for run_id, (system, group) in REUSED_CELLS.items():
        j = judged_topics(system, run_id) * JUDGE_CALL_USD
        score = standalone_score(system, run_id)
        total_judge += j
        rows.append({"run_id": run_id, "group": group, "n_topics":
                     judged_topics(system, run_id), "tokens": 0,
                     "backend": "reused", "gen_usd": 0.0, "judge_usd": j,
                     "total_usd": j, "score": score})
        print(f"{run_id:42s} {group:20s} {'':>3s} {'0.00':>8s} {j:9.2f} "
             f"{j:8.2f} {str(score):>6s}")

    selector_usd = 0.0
    for run_id, n_calls in SELECTOR_CALLS.items():
        c = n_calls * JUDGE_CALL_USD
        selector_usd += c
        j = judged_topics("brief_revise_agent", run_id) * JUDGE_CALL_USD
        score = standalone_score("brief_revise_agent", run_id)
        rows.append({"run_id": run_id, "group": "ensemble_selector", "n_topics": 15,
                     "tokens": 0, "backend": "openai", "gen_usd": c,
                     "judge_usd": j, "total_usd": c + j, "score": score})
        print(f"{run_id:42s} {'ensemble_selector':20s} {15:3d} {c:8.2f} "
             f"{j:9.2f} {c+j:8.2f} {str(score):>6s}")
        total_gen += c
        total_judge += j

    grand_total = (total_gen + total_judge + SOL_DESIGN_CALLS_USD_EXACT
                  + TAXONOMY_CALLS_USD_EXACT)
    print(f"\ngeneration total: ${total_gen:.2f}")
    print(f"judging total: ${total_judge:.2f}")
    print(f"sol design calls (exact): ${SOL_DESIGN_CALLS_USD_EXACT:.2f}")
    print(f"taxonomy calls (exact): ${TAXONOMY_CALLS_USD_EXACT:.2f}")
    print(f"GRAND TOTAL: ${grand_total:.2f}")

    # Per-factor-group rollup.
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    print(f"\n{'group':22s} {'n_cells':>8s} {'avg_cost':>10s} {'avg_score':>10s}")
    group_summary = {}
    for g, items in sorted(groups.items()):
        scored = [it for it in items if it["score"] is not None]
        avg_cost = sum(it["total_usd"] for it in items) / len(items)
        avg_score = (sum(it["score"] for it in scored) / len(scored)
                    if scored else None)
        group_summary[g] = {"n_cells": len(items), "avg_cost_usd": avg_cost,
                            "avg_score": avg_score}
        print(f"{g:22s} {len(items):8d} {avg_cost:10.2f} "
             f"{str(round(avg_score,3)) if avg_score else 'n/a':>10s}")

    out = Path(__file__).resolve().parent / "cost_by_run.json"
    out.write_text(json.dumps({
        "rows": rows, "group_summary": group_summary,
        "generation_total_usd": total_gen, "judging_total_usd": total_judge,
        "sol_design_calls_usd": SOL_DESIGN_CALLS_USD_EXACT,
        "taxonomy_calls_usd": TAXONOMY_CALLS_USD_EXACT,
        "grand_total_usd": grand_total,
    }, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
