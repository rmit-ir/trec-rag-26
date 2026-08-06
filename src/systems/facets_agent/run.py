"""CLI for the facets_agent RAG harness.

Usage (from the repo root):

    uv run --group facets-agent python src/systems/facets_agent/run.py \\
        --qid 6847465956a0f6376a605492
    uv run --group facets-agent python src/systems/facets_agent/run.py \\
        --query "..." [--model gpt-5.6-luna] [--k 10]
    uv run --group facets-agent python src/systems/facets_agent/run.py --all

Every option's default can also be set via a ``RUN_FACETS_AGENT_<OPTION>`` env
var; an explicit CLI flag still wins.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# --- import surgery (facet_rag/run.py's convention, not aus_agent/run.py's) -
# ``agent.py`` does a BARE ``from agent_harness.agent import ...`` (matching
# how the test suite's pythonpath resolves it) -- so this header puts
# src/systems on the path and imports facets_agent itself bare too, rather
# than aus_agent/run.py's "put src/ on the path, import via systems.<name>..."
# style. Mixing the two conventions in one process loads a module twice under
# different names, so patching one copy (as tests do) silently misses the
# other.
# ``ragrun``/``tools``/``utils``/``agent_harness`` need no path entry either
# way -- they are installed editable (see pyproject's
# [tool.hatch.build.targets.wheel]).
_HERE = os.path.dirname(os.path.abspath(__file__))
_SYSTEMS = os.path.dirname(_HERE)
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
if _SYSTEMS not in sys.path:
    sys.path.insert(0, _SYSTEMS)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from ragrun.outputs import data_dir  # noqa: E402
from utils.env import env  # noqa: E402

from facets_agent.agent import (  # noqa: E402
    DEFAULT_ENGINES,
    DEFAULT_HYBRID_K,
    SYSTEM_NAME,
    run_agent,
)

_REPO_ROOT = Path(_SYSTEMS).resolve().parents[1]
DEFAULT_TOPICS = (_REPO_ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
                  "/development-data/topics/research-rubrics-topics-dev.tsv")


def load_topics(path: Path) -> list[tuple[str, str]]:
    """Parse a ``qid \\t narrative`` TSV into (qid, narrative) pairs."""
    topics = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        qid, _, narrative = line.partition("\t")
        topics.append((qid, narrative.strip()))
    return topics


def finished_topics(run_id: str) -> set[str]:
    """Topic ids this ``run_id`` has already answered successfully (see
    aus_agent.run.finished_topics — same resume semantics, own output dir)."""
    out_dir = data_dir() / "outputs" / SYSTEM_NAME
    done: set[str] = set()
    for path in out_dir.glob("*.output.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if obj.get("metadata", {}).get("run_id") != run_id:
            continue
        if obj.get("trace", {}).get("status") in ("completed",
                                                  "budget_exhausted"):
            done.add(str(obj["metadata"]["narrative_id"]))
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="facets_agent RAG harness")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="ad-hoc query text (qid 'adhoc')")
    src.add_argument("--qid", help="topic id from the topics TSV")
    src.add_argument("--all", action="store_true",
                     help="run every topic in the topics TSV")
    ap.add_argument("--topics", type=Path,
                    default=env("RUN_FACETS_AGENT_TOPICS", DEFAULT_TOPICS),
                    help=f"topics TSV (default: {DEFAULT_TOPICS})")
    ap.add_argument("--backend",
                    default=env("RUN_FACETS_AGENT_BACKEND", "openai"),
                    help="bedrock | openai (default: openai, for gpt-5.6-luna)")
    ap.add_argument("--model",
                    default=env("RUN_FACETS_AGENT_MODEL", None),
                    help="model id (default: backend's own default, e.g. "
                         "OPENAI_MODEL_ID or gpt-5.6-luna)")
    ap.add_argument("--k", type=int, default=env("RUN_FACETS_AGENT_K", 10),
                    help="search results per call for non-hybrid engines")
    ap.add_argument("--hybrid-k", type=int,
                    default=env("RUN_FACETS_AGENT_HYBRID_K", DEFAULT_HYBRID_K),
                    help="search results per call for the hybrid engine "
                         f"(default: {DEFAULT_HYBRID_K} -- a wider net for "
                         "its HyDE-style hypothetical-passage query)")
    ap.add_argument(
        "--context-token-budget", type=int,
        default=env("RUN_FACETS_AGENT_CONTEXT_TOKEN_BUDGET", 500_000),
        help="stop retrieval when one generation's provider-reported input "
             "context reaches this size (default: 500000)")
    ap.add_argument(
        "--safety-max-rounds", "--max-rounds", type=int,
        default=env("RUN_FACETS_AGENT_SAFETY_MAX_ROUNDS", 100),
        help="runaway-loop safety backstop, not the normal research budget "
             "(default: 100)")
    ap.add_argument(
        "--max-committed-per-step", type=int,
        default=env("RUN_FACETS_AGENT_MAX_COMMITTED_PER_STEP", 10),
        help="maximum documents commit_context may retain from one staged "
             "batch (default: 10)")
    ap.add_argument("--run-id",
                    default=env("RUN_FACETS_AGENT_RUN_ID", "facets-agent-dev"))
    ap.add_argument(
        "--engines", dest="engines",
        default=env("RUN_FACETS_AGENT_ENGINES",
                    ",".join(DEFAULT_ENGINES)),
        help="comma-separated retrieval backends the search tool may use: "
             "semantic, keyword, hybrid (ssr/lucene_bool are no longer "
             f"supported). Default is all three ({','.join(DEFAULT_ENGINES)}).")
    ap.add_argument(
        "--skip-existing", action="store_true",
        default=env("RUN_FACETS_AGENT_SKIP_EXISTING", False),
        help="skip topics this --run-id has already answered successfully, so "
             "an interrupted batch resumes instead of starting over (a failed "
             "run does not count as answered)")
    ap.add_argument(
        "--search-result-filter", choices=["none", "minimize", "rank"],
        default=env("RUN_FACETS_AGENT_SEARCH_RESULT_FILTER", "none"),
        help="PLAN.md Phase 4c A/B: 'minimize' keeps only judge-relevant "
             "results, 'rank' reorders/annotates but drops nothing. "
             "Default 'none' (no filtering, matches facets_agent's actual "
             "default -- neither config has shipped as the default yet).")
    args = ap.parse_args()
    engines = [e.strip() for e in str(args.engines).split(",") if e.strip()]

    if args.query:
        jobs = [("adhoc", args.query)]
    elif args.qid:
        topics = dict(load_topics(args.topics))
        if args.qid not in topics:
            ap.error(f"qid {args.qid!r} not found in {args.topics}")
        jobs = [(args.qid, topics[args.qid])]
    else:
        jobs = load_topics(args.topics)

    if args.skip_existing:
        done = finished_topics(args.run_id)
        remaining = [job for job in jobs if job[0] not in done]
        print(f"--skip-existing: {len(jobs) - len(remaining)} of {len(jobs)} "
              f"topics already answered by run-id {args.run_id!r}; "
              f"running {len(remaining)}", flush=True)
        jobs = remaining
        if not jobs:
            print("nothing to do", flush=True)
            return

    search_result_filter = None
    if args.search_result_filter != "none":
        from facets_agent.filtering import minimize_filter, rank_filter
        search_result_filter = {
            "minimize": minimize_filter, "rank": rank_filter,
        }[args.search_result_filter]

    failures = 0
    for qid, query in jobs:
        print(f"=== {qid}: {query[:80]}...", flush=True)
        try:
            summary = run_agent(qid, query, backend=args.backend,
                                model=args.model, k=args.k,
                                hybrid_k=args.hybrid_k,
                                context_token_budget=args.context_token_budget,
                                safety_max_rounds=args.safety_max_rounds,
                                max_committed_per_step=(
                                    args.max_committed_per_step),
                                run_id=args.run_id,
                                engines=engines,
                                search_result_filter=search_result_filter)
        except Exception:  # keep --all going
            failures += 1
            logging.exception("run for %s failed", qid)
            continue
        summary["paths"] = {k: str(v) for k, v in summary["paths"].items()}
        print(json.dumps(summary, indent=2), flush=True)
        if summary["status"] == "failed":
            failures += 1
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
