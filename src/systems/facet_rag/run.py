"""facet_rag — orchestrator/analyzer multi-facet RAG over ClimbMix (TREC RAG 2026).

The narrative is decomposed into independent research FACETS (one
orchestrator call); each facet runs its own orchestrator/analyzer
search-analyze-gap loop (up to 10 iterations); the merged, analyst-vetted
evidence is synthesized into a grounded, cited report (orchestrator draft +
analyzer fact-check). Retrieval is corpus-only — no web search — and every
citation is a ClimbMix docid.

Two fixed Bedrock roles (``aus_agent.providers.bedrock.BedrockProvider``,
shared, not duplicated): the ORCHESTRATOR plans + drives search
(default ``openai.gpt-oss-120b-1:0``), the ANALYZER judges passages and
fact-checks (default ``qwen.qwen3-next-80b-a3b``). They commonly need
DIFFERENT Bedrock regions under this account — see ``--analyzer-region``.

Examples (repo root):

    # one dev topic by id, all four engines available to the orchestrator
    uv run --group facet-rag python src/systems/facet_rag/run.py \\
        --qid 6847465956a0f6376a605492

    # ad-hoc narrative, only semantic + ssr
    uv run --group facet-rag python src/systems/facet_rag/run.py \\
        --query "How effective are influenza vaccines?" \\
        --engines semantic ssr

    # every dev topic
    uv run --group facet-rag python src/systems/facet_rag/run.py --all

Config comes from the repo ``.env`` (auto-loaded): AWS creds +
``BEDROCK_REGION``. See ``src/systems/aus_agent/providers/bedrock.py`` for
per-model region caveats (qwen.*/moonshot.* need us-east-1/us-west-2).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# --- import surgery (same pattern as the other systems' run.py) -------------
# Put src/systems on the path and drop this package dir, so ``ragrun``,
# ``ali_deepresearch``, ``aus_agent``, ``tools.*`` and ``utils.*`` all resolve
# whether run from the repo root or from inside the package.
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

from tools.search_tool import SEARCH_ENGINES  # noqa: E402

from aus_agent.agent import make_provider  # noqa: E402  (reuse the factory)

from facet_rag.pipeline import run_one  # noqa: E402

_REPO_ROOT = Path(_SYSTEMS).resolve().parents[1]
DEFAULT_TOPICS = (_REPO_ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
                  "development-data/topics/research-rubrics-topics-dev.tsv")
DEFAULT_ORCHESTRATOR_MODEL = "openai.gpt-oss-120b-1:0"
DEFAULT_ANALYZER_MODEL = "qwen.qwen3-next-80b-a3b"
# Both pinned to a region verified working for that model under this account
# -- NOT left to fall back on the repo's BEDROCK_REGION env, which varies by
# .env (e.g. ap-southeast-1) and 400s as "invalid model identifier" for both
# of these non-Anthropic models. See src/systems/aus_agent/providers/bedrock.py.
DEFAULT_ORCHESTRATOR_REGION = "ap-southeast-2"
DEFAULT_ANALYZER_REGION = "us-east-1"
DEFAULT_RUN_DESC = (
    "facet_rag: orchestrator/analyzer multi-facet RAG over ClimbMix. The "
    "narrative is decomposed into facets, each run through an "
    "orchestrator-search / analyzer-judge / gap loop (<=10 iterations), then "
    "synthesized via an orchestrator draft + analyzer fact-check pass. "
    "Corpus-only; no web search.")


def load_topics(path: Path) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text().splitlines():
        qid, _, narrative = line.partition("\t")
        if qid.strip() and narrative.strip():
            rows.append((qid.strip(), narrative.strip()))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Orchestrator/analyzer multi-facet RAG over ClimbMix")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--query", help="ad-hoc narrative text")
    g.add_argument("--qid", help="a single dev-topic id from --topics")
    g.add_argument("--all", action="store_true", help="every dev topic")
    ap.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    ap.add_argument("--orchestrator-model", default=DEFAULT_ORCHESTRATOR_MODEL,
                    help="Bedrock model id for the planner/search orchestrator "
                         f"(default: {DEFAULT_ORCHESTRATOR_MODEL})")
    ap.add_argument("--orchestrator-region", default=DEFAULT_ORCHESTRATOR_REGION,
                    help="Bedrock region for the orchestrator (default: "
                         f"{DEFAULT_ORCHESTRATOR_REGION})")
    ap.add_argument("--analyzer-model", default=DEFAULT_ANALYZER_MODEL,
                    help="Bedrock model id for the passage analyzer/fact-"
                         f"checker (default: {DEFAULT_ANALYZER_MODEL})")
    ap.add_argument("--analyzer-region", default=DEFAULT_ANALYZER_REGION,
                    help="Bedrock region for the analyzer (default: "
                         f"{DEFAULT_ANALYZER_REGION} -- qwen.*/moonshot.* "
                         "models are not reachable in ap-southeast-2 under "
                         "this account)")
    ap.add_argument("--engines", nargs="+", choices=SEARCH_ENGINES,
                    default=list(SEARCH_ENGINES),
                    help="retrieval engines the orchestrator may choose from "
                         "(default: all four)")
    ap.add_argument("--min-facets", type=int, default=3)
    ap.add_argument("--max-facets", type=int, default=6)
    ap.add_argument("--max-chars", type=int, default=20000,
                    help="max chars of passage text per result fed to the "
                         "analyzer/synthesis (default matches aus_agent's "
                         "4096-token/~20480-char stage depth, PLAN.md §3.1)")
    ap.add_argument("--run-id", default="facet_rag.dev")
    ap.add_argument("--run-desc", default=DEFAULT_RUN_DESC)
    ap.add_argument("--no-format-llm", action="store_true",
                    help="use the deterministic offline answer formatter "
                         "instead of an extra LLM formatting call")
    args = ap.parse_args()

    engines = list(dict.fromkeys(args.engines))  # unique, preserve order

    def make_orchestrator():
        return make_provider("bedrock", args.orchestrator_model,
                             region=args.orchestrator_region)

    def make_analyzer():
        return make_provider("bedrock", args.analyzer_model,
                             region=args.analyzer_region)

    if args.query:
        items = [("adhoc", args.query)]
    else:
        topics = load_topics(args.topics)
        items = topics if args.all else [(q, n) for q, n in topics
                                         if q == args.qid]
        if not items:
            ap.error(f"qid {args.qid!r} not found in {args.topics}")

    for qid, narrative in items:
        result = run_one(
            make_orchestrator, make_analyzer, qid=qid, narrative=narrative,
            engines=engines, run_id=args.run_id, run_desc=args.run_desc,
            orchestrator_model_id=args.orchestrator_model,
            analyzer_model_id=args.analyzer_model,
            orchestrator_region=args.orchestrator_region,
            analyzer_region=args.analyzer_region, max_chars=args.max_chars,
            min_facets=args.min_facets, max_facets=args.max_facets,
            format_llm=not args.no_format_llm)
        paths = result["paths"]
        tag = "OK" if "violations" not in paths else "VIOLATIONS"
        print(f"[{tag}] {qid}: status={result['status']} "
              f"facets={len(result['facets'])} "
              f"refs={len(result['references'])} "
              f"-> {paths['output'].name}")


if __name__ == "__main__":
    main()
