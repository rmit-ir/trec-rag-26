"""CLI for the coverage-planned research-agent v2 harness.

Usage (from the repo root):

    uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \\
        --qid 6847465956a0f6376a605492
    uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py \\
        --query "..." [--model au.anthropic.claude-sonnet-5] [--k 10]
    uv run --group aus-agent-v2 python src/systems/aus_agent_v2/run.py --all

Every option's default can also be set via a ``RUN_AUS_AGENT_V2_<OPTION>`` env
var (e.g. ``RUN_AUS_AGENT_V2_BACKEND=openai`` in a
``.env``); an explicit CLI flag still wins.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# The sys.path munge MUST run before any project import. The v2 package imports
# the stable sibling as top-level ``aus_agent``, so script mode needs both
# ``src`` (shared layers / ``systems.*``) and ``src/systems`` (sibling systems),
# while the script's own directory must not lead the path.
_SRC_ROOT = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
_src_root = str(_SRC_ROOT)
_here = str(_HERE)
_systems_root = str(_SYSTEMS_ROOT)
sys.path[:] = [
    entry for entry in sys.path
    if str(Path(entry or ".").resolve()) not in {_here, _src_root, _systems_root}
]
sys.path[0:0] = [_src_root, _systems_root]

from ragrun.outputs import data_dir  # noqa: E402
from systems.aus_agent_v2.agent import (  # noqa: E402
    DEFAULT_MAX_COMMITTED_PER_STEP,
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
    """Topic ids this ``run_id`` has already answered successfully.

    A crashed run still writes a schema-valid artifact whose answer is a single
    "Run failed: ..." sentence, so the run's own status — not the file's
    existence — decides whether a topic is done. Scoping to ``run_id`` means a
    fresh id re-runs everything, while reusing one resumes it.
    """
    out_dir = data_dir() / "outputs" / "aus_agent_v2"
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
    ap = argparse.ArgumentParser(description="research-agent v2 RAG harness")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="ad-hoc query text (qid 'adhoc')")
    src.add_argument("--qid", help="topic id from the topics TSV")
    src.add_argument("--all", action="store_true",
                     help="run every topic in the topics TSV")
    ap.add_argument("--topics", type=Path,
                    default=env("RUN_AUS_AGENT_V2_TOPICS", DEFAULT_TOPICS),
                    help=f"topics TSV (default: {DEFAULT_TOPICS})")
    ap.add_argument("--backend",
                    default=env("RUN_AUS_AGENT_V2_BACKEND", "bedrock"))
    ap.add_argument("--model",
                    default=env("RUN_AUS_AGENT_V2_MODEL", None),
                    help="model id (default: backend's own env/default, e.g. "
                         "BEDROCK_MODEL_ID or OPENAI_MODEL_ID)")
    ap.add_argument("--k", type=int, default=env("RUN_AUS_AGENT_V2_K", 20),
                    help="search results per call (confirmed default: 20)")
    ap.add_argument(
        "--context-token-budget", type=int,
        default=env("RUN_AUS_AGENT_V2_CONTEXT_TOKEN_BUDGET", 500_000),
        help="stop retrieval when one generation's provider-reported input "
             "context reaches this size (default: 500000)")
    ap.add_argument(
        "--safety-max-rounds", "--max-rounds", type=int,
        default=env("RUN_AUS_AGENT_V2_SAFETY_MAX_ROUNDS", 40),
        help="runaway-loop safety backstop, not the normal research budget "
             "(confirmed default: 40)")
    ap.add_argument(
        "--max-committed-per-step", type=int,
        default=env("RUN_AUS_AGENT_V2_MAX_COMMITTED_PER_STEP",
                    DEFAULT_MAX_COMMITTED_PER_STEP),
        help="maximum documents commit_context may retain from one staged "
             f"batch (default: {DEFAULT_MAX_COMMITTED_PER_STEP})")
    ap.add_argument(
        "--coverage-plan", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_COVERAGE_PLAN", True),
        help="isolated request decomposition before research (default: on)")
    ap.add_argument(
        "--coverage-scout", "--plan-critic", dest="plan_critic",
        action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_PLAN_CRITIC", True),
        help="blind request-only coverage inventory (default: on)")
    ap.add_argument(
        "--plan-critic-additions", type=int,
        default=env("RUN_AUS_AGENT_V2_PLAN_CRITIC_ADDITIONS", 8),
        help="maximum ranked blind-scout obligations retained (1-12; "
             "default: 8)")
    ap.add_argument(
        "--compact-scout-plan", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_COMPACT_SCOUT_PLAN", False),
        help="omit redundant search phrases from the research handoff so more "
             "atomic obligations fit the same plan budget (default: off)")
    ap.add_argument(
        "--observable-scout", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_OBSERVABLE_SCOUT", False),
        help="complementary literal/countable completeness inventory "
             "(experimental; default: off)")
    ap.add_argument(
        "--plan-reconcile", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_PLAN_RECONCILE", False),
        help="compile plan + scout into prioritized word-budget contract "
             "(experimental; default: off)")
    ap.add_argument(
        "--coverage-verify", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_COVERAGE_VERIFY", False),
        help="fresh-context draft omission check and one repair "
             "(experimental; default: off)")
    ap.add_argument(
        "--coverage-repair-strategy",
        choices=("patch-first", "research-first"),
        default=env("RUN_AUS_AGENT_V2_COVERAGE_REPAIR_STRATEGY", "patch-first"),
        help="try citation-local patches before research, or return verifier "
             "findings directly to the evidence-owning context (default: "
             "patch-first)")
    ap.add_argument(
        "--audience-verify", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_AUDIENCE_VERIFY", False),
        help="experimental safe reader-expectation insertion audit (default: off)")
    ap.add_argument(
        "--finish-review", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_FINISH_REVIEW", False),
        help="citation-local deterministic line patches (experimental; default: off)")
    ap.add_argument(
        "--answer-blueprint", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_ANSWER_BLUEPRINT", False),
        help="mandatory evidence-to-answer claim map with commit-time fact "
             "replay immediately before final prose (experimental; default: off)")
    ap.add_argument(
        "--coverage-contract", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_COVERAGE_CONTRACT", False),
        help="harness-owned requirement/evidence ledger with terminal "
             "submit_answer validation (experimental; default: off)")
    ap.add_argument(
        "--atomic-contract-plan", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_ATOMIC_CONTRACT_PLAN", False),
        help="use the structured 10-24 row atomic planner for the contract "
             "candidate (experimental; default: off)")
    ap.add_argument(
        "--dynamic-contract-rows", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_DYNAMIC_CONTRACT_ROWS", False),
        help="allow up to six evidence-backed atomic rows promoted during "
             "commit_context (experimental; default: off)")
    ap.add_argument(
        "--terminal-evidence-handoff", action=argparse.BooleanOptionalAction,
        default=env("RUN_AUS_AGENT_V2_TERMINAL_EVIDENCE_HANDOFF", False),
        help="force a harness-owned complete evidence replay before terminal "
             "submission (experimental; default: off)")
    ap.add_argument("--run-id", default=env(
        "RUN_AUS_AGENT_V2_RUN_ID", "aus-agent-v2-dev"))
    ap.add_argument(
        "--prompt-variant", dest="prompt_variant",
        default=env("RUN_AUS_AGENT_V2_PROMPT_VARIANT", "default"),
        help="system-prompt variant = filename stem under prompts/system/ "
             "('default' is the baseline; e.g. 'firsthand' loads "
             "prompts/system/firsthand.md). Recorded in run metadata + run_desc.")
    ap.add_argument(
        "--search-backends", "--engines", dest="search_backends",
        default=env("RUN_AUS_AGENT_V2_SEARCH_BACKENDS", "semantic,keyword"),
        help="comma-separated retrieval backends the search tool may use: "
             "semantic, keyword, ssr, lucene_bool. Default is the dense+sparse "
             "pair semantic,keyword. Restrict to one (e.g. --search-backends "
             "ssr) to test that method's effectiveness in isolation; the model "
             "must name search_engine on every call either way. "
             "Alias: --engines.")
    ap.add_argument(
        "--skip-existing", action="store_true",
        default=env("RUN_AUS_AGENT_V2_SKIP_EXISTING", False),
        help="skip topics this --run-id has already answered successfully, so "
             "an interrupted batch resumes instead of starting over (a failed "
             "run does not count as answered)")
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
            summary = run_agent(qid, query, backend=args.backend,
                                model=args.model, k=args.k,
                                context_token_budget=args.context_token_budget,
                                safety_max_rounds=args.safety_max_rounds,
                                max_committed_per_step=(
                                    args.max_committed_per_step),
                                run_id=args.run_id,
                                prompt_variant=args.prompt_variant,
                                finish_review=args.finish_review,
                                coverage_plan=args.coverage_plan,
                                plan_critic=args.plan_critic,
                                plan_critic_max_additions=(
                                    args.plan_critic_additions),
                                compact_scout_plan=args.compact_scout_plan,
                                observable_scout=args.observable_scout,
                                plan_reconcile=args.plan_reconcile,
                                coverage_verify=args.coverage_verify,
                                coverage_repair_strategy=(
                                    args.coverage_repair_strategy),
                                audience_verify=args.audience_verify,
                                answer_blueprint=args.answer_blueprint,
                                coverage_contract=args.coverage_contract,
                                atomic_contract_plan=(
                                    args.atomic_contract_plan),
                                dynamic_contract_rows=(
                                    args.dynamic_contract_rows),
                                terminal_evidence_handoff=(
                                    args.terminal_evidence_handoff),
                                engines=search_backends)
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
