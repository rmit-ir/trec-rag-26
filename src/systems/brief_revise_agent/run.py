"""CLI for the brief_revise_agent RAG harness.

Usage (from the repo root):

    uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py \\
        --qid 6847465956a0f6376a605492
    uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py \\
        --query "..." [--model au.anthropic.claude-sonnet-5] [--k 10]
    uv run --group brief-revise-agent python src/systems/brief_revise_agent/run.py --all

Every option's default can also be set via a ``RUN_BRIEF_REVISE_AGENT_<OPTION>``
env var (e.g. ``RUN_BRIEF_REVISE_AGENT_BACKEND=openai``,
``RUN_BRIEF_REVISE_AGENT_MODEL=...`` in a ``.env``); an explicit CLI flag
still wins. A copy of ``aus_agent/run.py`` (same import-surgery convention,
same topics file, same defaults) with its env-var prefix and output
directory renamed to this system's own.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# The sys.path munge MUST run before any project import: in script mode the
# script's own dir (src/systems/brief_revise_agent) leads sys.path, where the
# local `tools`/`prompts` names could shadow src/tools etc. Hence the
# noqa: E402 on the imports below -- an import sorter hoisting them above this
# block breaks script execution (see aus_agent/run.py, the source of this
# convention).
#
# Both `src` AND `src/systems` go on the path (not just `src`, unlike
# aus_agent/run.py, which never cross-imports a sibling system package):
# brief.py/review.py import `facet_rag.llm` bare (facets_agent's own
# convention for a same-level sibling import), which only resolves with
# `src/systems` itself on sys.path. Mirrors pytest's own
# `pythonpath = ["src", "src/systems", "tests"]` (pyproject.toml) exactly --
# discovered because the offline test suite passed (pytest sets up both) but
# `run.py` alone did not, before this fix.
_SRC_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
for _entry in (str(_SRC_ROOT), str(_SYSTEMS_ROOT)):
    sys.path[:] = [p for p in sys.path if p != _entry]
    sys.path.insert(0, _entry)

# aus_agent/run.py (this file's source) never needed this: its default
# backend is `bedrock`, which reads AWS creds straight from the environment
# (a shell export or an AWS profile), not from `.env`. `--backend openai`
# (needed here to match aus_agent's own gpt-5.6-luna baseline runs -- see
# PLAN.md §6 Phase 4) needs OPENAI_API_KEY/OPENAI_BASE_URL, which live in
# `.env` and are never loaded without this -- facets_agent's run.py already
# has this same block since it defaults to openai. Found running the live
# pilot: every --qid call failed on a credentials error before this fix.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from ragrun.outputs import data_dir  # noqa: E402
from systems.brief_revise_agent.agent import (  # noqa: E402
    DEFAULT_MAX_COMMITTED_PER_STEP,
    SYSTEM_NAME,
    load_system_prompt,
    run_agent,
)
from utils.env import env  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[3]
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
    aus_agent.run.finished_topics -- same resume semantics, own output dir)."""
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
    ap = argparse.ArgumentParser(description="brief_revise_agent RAG harness")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="ad-hoc query text (qid 'adhoc')")
    src.add_argument("--qid", help="topic id from the topics TSV")
    src.add_argument("--all", action="store_true",
                     help="run every topic in the topics TSV")
    ap.add_argument("--topics", type=Path,
                    default=env("RUN_BRIEF_REVISE_AGENT_TOPICS", DEFAULT_TOPICS),
                    help=f"topics TSV (default: {DEFAULT_TOPICS})")
    ap.add_argument("--backend",
                    default=env("RUN_BRIEF_REVISE_AGENT_BACKEND", "bedrock"))
    ap.add_argument("--model",
                    default=env("RUN_BRIEF_REVISE_AGENT_MODEL", None),
                    help="model id (default: backend's own env/default, e.g. "
                         "BEDROCK_MODEL_ID or OPENAI_MODEL_ID)")
    ap.add_argument("--k", type=int, default=env("RUN_BRIEF_REVISE_AGENT_K", 10),
                    help="search results per call")
    ap.add_argument(
        "--context-token-budget", type=int,
        default=env("RUN_BRIEF_REVISE_AGENT_CONTEXT_TOKEN_BUDGET", 500_000),
        help="stop retrieval when one generation's provider-reported input "
             "context reaches this size (default: 500000)")
    ap.add_argument(
        "--safety-max-rounds", "--max-rounds", type=int,
        default=env("RUN_BRIEF_REVISE_AGENT_SAFETY_MAX_ROUNDS", 100),
        help="runaway-loop safety backstop, not the normal research budget "
             "(default: 100)")
    ap.add_argument(
        "--max-committed-per-step", type=int,
        default=env("RUN_BRIEF_REVISE_AGENT_MAX_COMMITTED_PER_STEP",
                    DEFAULT_MAX_COMMITTED_PER_STEP),
        help="maximum documents commit_context may retain from one staged "
             f"batch (default: {DEFAULT_MAX_COMMITTED_PER_STEP})")
    ap.add_argument("--run-id",
                    default=env("RUN_BRIEF_REVISE_AGENT_RUN_ID",
                                "brief-revise-agent-dev"))
    ap.add_argument(
        "--prompt-variant", dest="prompt_variant",
        default=env("RUN_BRIEF_REVISE_AGENT_PROMPT_VARIANT", "default"),
        help="system-prompt variant = filename stem under prompts/system/ "
             "('default' is the only variant this fork ships). Recorded in "
             "run metadata + run_desc.")
    ap.add_argument(
        "--search-backends", "--engines", dest="search_backends",
        default=env("RUN_BRIEF_REVISE_AGENT_SEARCH_BACKENDS",
                    "semantic,keyword"),
        help="comma-separated retrieval backends the search tool may use: "
             "semantic, keyword, ssr, lucene_bool. Default is aus_agent's own "
             "dense+sparse pair semantic,keyword (PLAN.md §3.4: unchanged). "
             "The model must name search_engine on every call either way. "
             "Alias: --engines.")
    ap.add_argument(
        "--skip-existing", action="store_true",
        default=env("RUN_BRIEF_REVISE_AGENT_SKIP_EXISTING", False),
        help="skip topics this --run-id has already answered successfully, so "
             "an interrupted batch resumes instead of starting over (a failed "
             "run does not count as answered)")
    ap.add_argument(
        "--disable-adjacent-pages", action="store_true",
        default=env("RUN_BRIEF_REVISE_AGENT_DISABLE_ADJACENT_PAGES", False),
        help="pass search_result_augment=None, disabling round B's "
             "adjacent-page auto-retrieval (agent.py's default is ON) -- "
             "for an isolated A/B/C/D comparison of the sol-vs-aus_agent_v2 "
             "improvement-loop rounds")
    args = ap.parse_args()
    search_backends = [e.strip() for e in str(args.search_backends).split(",")
                       if e.strip()]

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

    failures = 0
    for qid, query in jobs:
        print(f"=== {qid}: {query[:80]}...", flush=True)
        try:
            system_prompt = load_system_prompt(args.max_committed_per_step,
                                               args.prompt_variant)
            run_kwargs = {}
            if args.disable_adjacent_pages:
                run_kwargs["search_result_augment"] = None
            summary = run_agent(qid, query, backend=args.backend,
                                model=args.model, k=args.k,
                                context_token_budget=args.context_token_budget,
                                safety_max_rounds=args.safety_max_rounds,
                                max_committed_per_step=(
                                    args.max_committed_per_step),
                                run_id=args.run_id,
                                prompt_variant=args.prompt_variant,
                                system_prompt=system_prompt,
                                engines=search_backends, **run_kwargs)
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
