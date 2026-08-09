"""CLI for the oss_agent RAG harness -- open-weight models only.

Usage (from the repo root):

    uv run --group oss-agent python src/systems/oss_agent/run.py \\
        --qid 6847465956a0f6376a605492
    uv run --group oss-agent python src/systems/oss_agent/run.py \\
        --query "..." --model qwen.qwen3-next-80b-a3b
    uv run --group oss-agent python src/systems/oss_agent/run.py --all

``--model`` (and ``--brief-model``/``--review-model``/``--scout-model``) must
be one of ``agent.ALLOWED_MODELS`` -- anything else raises before any API
call is made. Every option's default can also be set via a
``RUN_OSS_AGENT_<OPTION>`` env var; an explicit CLI flag still wins (same
convention as brief_revise_agent/run.py, this file's template).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# The sys.path munge MUST run before any project import -- see
# brief_revise_agent/run.py's own comment for why (this file is a copy of
# that convention). Both `src` AND `src/systems` go on the path: agent.py
# imports `facet_rag.llm`/`systems.aus_agent_v2.plan_critic`/
# `systems.brief_revise_agent.*` bare, matching pytest's own
# `pythonpath = ["src", "src/systems", "tests"]`.
_SRC_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
for _entry in (str(_SRC_ROOT), str(_SYSTEMS_ROOT)):
    sys.path[:] = [p for p in sys.path if p != _entry]
    sys.path.insert(0, _entry)

try:
    from dotenv import load_dotenv

    load_dotenv()
    # openai backend is diagnostic-only here (--brief/--scout/--review-backend
    # openai, see agent.py's own docstring) -- the repo's .env only has
    # AZURE_OPENAI_API_KEY, and the OpenAI SDK reads OPENAI_API_KEY
    # specifically (rubric_scorecard_aus_agent_vs_facets_agent.py's own
    # load_env does the same fallback for the same reason).
    if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]
except ImportError:  # pragma: no cover
    pass

from ragrun.outputs import data_dir  # noqa: E402
from systems.brief_revise_agent.agent import (  # noqa: E402
    DEFAULT_MAX_COMMITTED_PER_STEP,
)
from systems.oss_agent.agent import (  # noqa: E402
    ALLOWED_MODELS,
    DEFAULT_ENGINES,
    DEFAULT_MODEL,
    DEFAULT_REGION_BY_MODEL,
    SYSTEM_NAME,
    load_base_system_prompt,
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
    brief_revise_agent.run.finished_topics -- same resume semantics, own
    output dir)."""
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


def _model_arg(ap: argparse.ArgumentParser, flag: str, env_name: str,
               default: str, help_suffix: str) -> None:
    ap.add_argument(flag, default=env(env_name, default),
                    choices=sorted(ALLOWED_MODELS),
                    help=f"{help_suffix} (default: {default}; open-weight "
                         "only, see agent.ALLOWED_MODELS)")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="oss_agent RAG harness -- open-weight models only")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="ad-hoc query text (qid 'adhoc')")
    src.add_argument("--qid", help="topic id from the topics TSV")
    src.add_argument("--all", action="store_true",
                     help="run every topic in the topics TSV")
    ap.add_argument("--topics", type=Path,
                    default=env("RUN_OSS_AGENT_TOPICS", DEFAULT_TOPICS))
    _model_arg(ap, "--model", "RUN_OSS_AGENT_MODEL", DEFAULT_MODEL,
              "main research/writer model")
    ap.add_argument(
        "--brief-model", default=env("RUN_OSS_AGENT_BRIEF_MODEL", DEFAULT_MODEL),
        help="requirements-brief analyst model. Open-weight only UNLESS "
             "--brief-backend=openai (diagnostic role-decoupling only, see "
             "--brief-backend)")
    ap.add_argument(
        "--review-model", default=env("RUN_OSS_AGENT_REVIEW_MODEL", DEFAULT_MODEL),
        help="reviewer model. Open-weight only UNLESS --review-backend=openai")
    ap.add_argument(
        "--scout-model", default=env("RUN_OSS_AGENT_SCOUT_MODEL", DEFAULT_MODEL),
        help="blind-scout model. Open-weight only UNLESS --scout-backend=openai")
    ap.add_argument(
        "--brief-backend", choices=["bedrock", "openai"],
        default=env("RUN_OSS_AGENT_BRIEF_BACKEND", "bedrock"),
        help="DIAGNOSTIC ONLY: \"openai\" lets --brief-model be a "
             "proprietary model (e.g. gpt-5.6-luna), bypassing the "
             "open-weight allowlist for this ONE support role -- for the "
             "offline role-decoupling experiment localizing the -0.200 "
             "mixed-pipeline gap (worklogs/assets/2026-08-09-oss-agent-sol-"
             "plan-review.md). Output from a non-bedrock run is NOT "
             "submission-eligible. Default: bedrock (open-weight enforced).")
    ap.add_argument(
        "--review-backend", choices=["bedrock", "openai"],
        default=env("RUN_OSS_AGENT_REVIEW_BACKEND", "bedrock"),
        help="DIAGNOSTIC ONLY, same contract as --brief-backend, for the "
             "reviewer role.")
    ap.add_argument(
        "--scout-backend", choices=["bedrock", "openai"],
        default=env("RUN_OSS_AGENT_SCOUT_BACKEND", "bedrock"),
        help="DIAGNOSTIC ONLY, same contract as --brief-backend, for the "
             "blind-scout role.")
    ap.add_argument("--region", default=env("RUN_OSS_AGENT_REGION", None),
                    help="Bedrock region override for the MAIN model "
                         "(default: DEFAULT_REGION_BY_MODEL[--model], e.g. "
                         "us-east-1 for qwen/kimi)")
    ap.add_argument("--brief-region", default=env("RUN_OSS_AGENT_BRIEF_REGION", None))
    ap.add_argument("--review-region", default=env("RUN_OSS_AGENT_REVIEW_REGION", None))
    ap.add_argument("--scout-region", default=env("RUN_OSS_AGENT_SCOUT_REGION", None))
    ap.add_argument("--k", type=int, default=env("RUN_OSS_AGENT_K", 10))
    ap.add_argument(
        "--engines", default=env("RUN_OSS_AGENT_ENGINES",
                                 ",".join(DEFAULT_ENGINES)),
        help="comma-separated retrieval backends (default: hybrid only -- "
             "S6, confirmed the one cheap+quality win in the factor-"
             "analysis report). semantic,keyword is brief_revise_agent's "
             "own default.")
    ap.add_argument(
        "--context-token-budget", type=int,
        default=env("RUN_OSS_AGENT_CONTEXT_TOKEN_BUDGET", 500_000))
    ap.add_argument(
        "--safety-max-rounds", "--max-rounds", type=int,
        default=env("RUN_OSS_AGENT_SAFETY_MAX_ROUNDS", 100))
    ap.add_argument(
        "--max-committed-per-step", type=int,
        default=env("RUN_OSS_AGENT_MAX_COMMITTED_PER_STEP",
                    DEFAULT_MAX_COMMITTED_PER_STEP))
    ap.add_argument("--run-id", default=env("RUN_OSS_AGENT_RUN_ID", "oss-agent-dev"))
    ap.add_argument(
        "--no-plan-critic", dest="plan_critic", action="store_false",
        default=env("RUN_OSS_AGENT_PLAN_CRITIC", True),
        help="disable the blind scout stage (default: on)")
    ap.add_argument(
        "--disable-adjacent-pages", action="store_true",
        default=env("RUN_OSS_AGENT_DISABLE_ADJACENT_PAGES", False),
        help="pass search_result_augment=None (default: on, S5)")
    ap.add_argument(
        "--synthesis-compiler", action="store_true",
        default=env("RUN_OSS_AGENT_SYNTHESIS_COMPILER", False),
        help="use blueprint.hook instead of review.hook as the "
             "pre_final_hook -- forces a validated obligation-covering "
             "structure before final prose instead of critiquing an "
             "already-written draft. EMPIRICALLY REJECTED (worklogs/2026-"
             "08-09-oss-agent-open-weight-system.md): scored 0.933 vs. "
             "1.467 for plain review.hook. Default: off. Kept as a "
             "documented negative result, not deleted.")
    ap.add_argument(
        "--review-scout-obligations", action="store_true",
        default=env("RUN_OSS_AGENT_REVIEW_SCOUT_OBLIGATIONS", False),
        help="widen review.hook's own requirement list to also grade the "
             "blind scout's additions (S1, S2, ...), not just the "
             "brief's own -- the additive follow-up both sol and Opus "
             "converged on after --synthesis-compiler's negative result. "
             "Default: off (brief requirements only).")
    ap.add_argument(
        "--no-review", action="store_true",
        default=env("RUN_OSS_AGENT_NO_REVIEW", False),
        help="pass pre_final_hook=None, disabling the review/revise pass "
             "(S4) entirely -- the subtractive diagnostic sol and Opus "
             "both asked for after two additive Tier-2 attempts hurt "
             "Citation Quality: isolates whether the ALWAYS-ON review "
             "pass itself already costs citation quality on glm-5, "
             "distinct from today's two failed additions to it. Default: "
             "off (review.hook, unmodified).")
    ap.add_argument(
        "--skip-existing", action="store_true",
        default=env("RUN_OSS_AGENT_SKIP_EXISTING", False))
    args = ap.parse_args()
    engines = [e.strip() for e in str(args.engines).split(",") if e.strip()]

    # The MAIN loop's provider is built inside agent_harness.agent.run_agent
    # itself, which has no per-call region parameter -- set BEDROCK_REGION
    # in the environment for this whole invocation, per
    # agent_harness.providers.bedrock's documented convention (see
    # agent.run_agent's own docstring for why the brief/review/scout roles
    # don't need this: those providers are built directly, with an explicit
    # region kwarg).
    main_region = args.region or DEFAULT_REGION_BY_MODEL.get(args.model)
    if main_region:
        os.environ["BEDROCK_REGION"] = main_region

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
            system_prompt = load_base_system_prompt(args.max_committed_per_step)
            run_kwargs: dict = {}
            if args.disable_adjacent_pages:
                run_kwargs["search_result_augment"] = None
            if args.no_review:
                run_kwargs["pre_final_hook"] = None
            summary = run_agent(
                qid, query, model=args.model, region=args.region,
                brief_model=args.brief_model, brief_region=args.brief_region,
                brief_backend=args.brief_backend,
                review_model=args.review_model, review_region=args.review_region,
                review_backend=args.review_backend,
                scout_model=args.scout_model, scout_region=args.scout_region,
                scout_backend=args.scout_backend,
                plan_critic=args.plan_critic,
                synthesis_compiler=args.synthesis_compiler,
                review_scout_obligations=args.review_scout_obligations, k=args.k,
                context_token_budget=args.context_token_budget,
                safety_max_rounds=args.safety_max_rounds,
                max_committed_per_step=args.max_committed_per_step,
                run_id=args.run_id, system_prompt=system_prompt,
                engines=engines, **run_kwargs)
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
