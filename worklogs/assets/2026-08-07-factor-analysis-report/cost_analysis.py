#!/usr/bin/env python3
"""PRODUCTION running-cost accounting for brief_revise_agent, per component
(worklogs/2026-08-07-brief-revise-agent-llm-factorial-design.md sections
1-28). Deliberately excludes judging/design/taxonomy costs entirely --
those are one-off evaluation overhead paid once during this analysis, not
a per-topic expense the deployed system pays every time it runs. The
question this script answers is: "if we ship this component, how much
does it cost to run PER TOPIC, and is that worth the effect it buys?" --
not "how much did it cost us to test it."

`processed_tokens` (agent_harness.agent's own trajectory summary field) is
INPUT+OUTPUT combined already (`_usage_token_stats(usage)["processed"]` =
uncached_input + cache_write + output -- read directly from
src/agent_harness/agent.py). Real per-topic values only exist in the
tee'd stdout logs this session captured under each job's scratchpad/ dir
(never persisted into output.json/trajectory.json) -- this script
re-derives them from those logs rather than reconstructing figures from
memory.

Rates (placeholders except Bedrock's -- see the report's own caveat, §7):
OpenAI (luna/terra/sol) has NO real rate card in this repo for
gpt-5.6-* -- $5/1M blended across input+output (likely an UNDERESTIMATE
since output is usually priced ~4x input; treat as a consistent RELATIVE
proxy for comparing components, not an absolute dollar figure). Bedrock
(gpt-oss-120b, qwen) uses the real metered rate-card file's midpoint.

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

RUN_ID_RE = re.compile(r"run_id=(\S+)")
TOKENS_RE = re.compile(r'"processed_tokens":\s*(\d+)')
BACKEND_RE = re.compile(r"starting:.*backend=(\S+)\s+model=(\S+)")

BASE_RUN_ID = "br-model-main-sol-exp15-b1"

# Every cell whose GENERATION run_id is real and log-derivable this
# workstream, mapped to (component, level) -- one row per tested
# component/level, all compared against BASE_RUN_ID's own per-topic cost.
# "generator_model" rows compare a full model swap; everything else holds
# the model at sol and swaps exactly one structural/harness factor.
CELLS: dict[str, tuple[str, str]] = {
    BASE_RUN_ID: ("generator_model", "sol (BASE)"),
    "br-model-main-terra-exp15-b1": ("generator_model", "terra"),
    "br-model-main-oss120b-exp15-b1": ("generator_model", "gpt-oss-120b"),
    "br-model-main-qwen-exp15-b1": ("generator_model", "qwen"),
    "br-luna-current-code-exp15": ("generator_model", "luna"),
    "br-hillclimb-sol-adjoff-exp15": ("adjacent_page_fetch", "OFF (default ON)"),
    "br-hillclimb-sol-preview-exp15": ("search_preview_chars", "20480-char cap (default: full)"),
    "br-hillclimb-sol-nostage-exp15": ("stage_search_results", "OFF (default ON)"),
    "br-hillclimb-sol-jrel-exp15": ("judge_relevance_tool", "ON (default OFF)"),
    "br-hillclimb-sol-commitrelease-exp15": ("commit_release", "ON (default OFF)"),
    "br-hillclimb-sol-widerengines-exp15": ("retrieval_engine_set", "+ssr+lucene_bool (default semantic,keyword)"),
    "br-hillclimb-sol-jrelcommit-exp15": ("judge_relevance+commit_release", "both ON"),
    "br-hillclimb-sol-closurecritic-exp15": ("closure_critic", "ON (default OFF)"),
    "br-analystsweep-terra-exp15": ("brief_analyst_model", "terra (default luna)"),
    "br-analystsweep-oss120b-exp15": ("brief_analyst_model", "gpt-oss-120b (default luna)"),
    "br-analystsweep-qwen-exp15": ("brief_analyst_model", "qwen (default luna)"),
    "br-enginesweep-keyword-exp15": ("retrieval_engine_set", "keyword only (default semantic,keyword)"),
    "br-enginesweep-semantic-exp15": ("retrieval_engine_set", "semantic only (default semantic,keyword)"),
    "br-enginesweep-hybrid-exp15": ("retrieval_engine_set", "hybrid only (default semantic,keyword)"),
    "br-enginesweep-hyde-exp15": ("retrieval_engine_set", "hybrid+HyDE only (default semantic,keyword)"),
}


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


def standalone_score(run_id: str) -> float | None:
    p = EVAL_DIR / run_id / "summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("overall_mean")


def main() -> None:
    merged: dict[str, list] = {}
    for log in find_logs():
        for run_id, row in parse_log(log).items():
            if run_id not in CELLS:
                continue
            prev = merged.get(run_id)
            if prev is None or row[1] > prev[1]:
                merged[run_id] = row

    base_row = merged[BASE_RUN_ID]
    base_per_topic = gen_cost(base_row[1], base_row[2]) / base_row[0]
    base_score = standalone_score(BASE_RUN_ID)

    print(f"BASE (sol, default config): ${base_per_topic:.3f}/topic, "
         f"score={base_score:.3f}\n")

    rows = []
    print(f"{'component':30s} {'level':38s} {'$/topic':>9s} "
         f"{'marginal $':>11s} {'score':>6s} {'Δ score':>8s}")
    for run_id, (component, level) in CELLS.items():
        row = merged.get(run_id)
        if row is None:
            print(f"{component:30s} {level:38s}  (no log data found)")
            continue
        n, tok, backend, _model = row
        per_topic = gen_cost(tok, backend) / n
        marginal = per_topic - base_per_topic
        score = standalone_score(run_id)
        delta_score = (score - base_score) if score is not None else None
        rows.append({
            "run_id": run_id, "component": component, "level": level,
            "n_topics": n, "cost_per_topic_usd": per_topic,
            "marginal_cost_per_topic_usd": marginal,
            "score": score, "delta_score": delta_score,
        })
        ds = f"{delta_score:+.3f}" if delta_score is not None else "n/a"
        sc = f"{score:.3f}" if score is not None else "n/a"
        print(f"{component:30s} {level:38s} {per_topic:9.3f} "
             f"{marginal:+11.3f} {sc:>6s} {ds:>8s}")

    out = Path(__file__).resolve().parent / "cost_by_run.json"
    out.write_text(json.dumps({
        "base_run_id": BASE_RUN_ID,
        "base_cost_per_topic_usd": base_per_topic,
        "base_score": base_score,
        "rows": rows,
    }, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
