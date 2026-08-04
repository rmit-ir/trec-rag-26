"""facet_rag — plan-then-execute multi-facet RAG over ClimbMix (TREC RAG 2026).

The narrative is decomposed into independent search FACETS (one LLM call), each
facet is retrieved with the engine best suited to it (semantic / keyword / ssr /
lucene_bool), and the merged passages are synthesized into a grounded, cited
report (one LLM call). Retrieval is corpus-only — no web search — and every
citation is a ClimbMix docid.

Backends are pluggable via ``aus_agent.providers`` (shared, not duplicated):
``--backend bedrock`` (default) or ``--backend openai``.

Examples (repo root):

    # one dev topic by id, all four engines available to the planner
    uv run --group facet-rag python src/systems/facet_rag/run.py \\
        --qid 6847465956a0f6376a605492

    # ad-hoc narrative, OpenAI backend, semantic+ssr only
    uv run --group facet-rag python src/systems/facet_rag/run.py \\
        --query "How effective are influenza vaccines?" \\
        --backend openai --engines semantic ssr

    # every dev topic
    uv run --group facet-rag python src/systems/facet_rag/run.py --all

Config comes from the repo ``.env`` (auto-loaded): Bedrock uses AWS creds +
``BEDROCK_MODEL_ID``/``BEDROCK_REGION``; OpenAI uses ``OPENAI_API_KEY`` +
``OPENAI_MODEL_ID``. See ``src/systems/aus_agent/providers`` for details.
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
DEFAULT_RUN_DESC = (
    "facet_rag: plan-then-execute multi-facet RAG over ClimbMix. The narrative "
    "is decomposed into engine-pinned search facets (semantic/keyword/ssr/"
    "lucene_bool), one search per facet, then a single grounded synthesis. "
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
        description="Plan-then-execute multi-facet RAG over ClimbMix")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--query", help="ad-hoc narrative text")
    g.add_argument("--qid", help="a single dev-topic id from --topics")
    g.add_argument("--all", action="store_true", help="every dev topic")
    ap.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    ap.add_argument("--backend", choices=("bedrock", "openai"),
                    default="bedrock")
    ap.add_argument("--model", default=None,
                    help="model id override (else the backend's env default)")
    ap.add_argument("--region", default=None,
                    help="Bedrock region override (else BEDROCK_REGION env or "
                         "ap-southeast-2). Non-Anthropic Bedrock models "
                         "(qwen.*, moonshot.*) are only reachable in "
                         "us-east-1/us-west-2 under this account, not "
                         "ap-southeast-2 -- pass --region us-east-1 for those.")
    ap.add_argument("--engines", nargs="+", choices=SEARCH_ENGINES,
                    default=list(SEARCH_ENGINES),
                    help="retrieval engines the planner may choose from "
                         "(default: all four)")
    ap.add_argument("--min-facets", type=int, default=3)
    ap.add_argument("--max-facets", type=int, default=6)
    ap.add_argument("--max-chars", type=int, default=2000,
                    help="max chars of passage text per result fed to synthesis")
    ap.add_argument("--run-id", default="facet_rag.dev")
    ap.add_argument("--run-desc", default=DEFAULT_RUN_DESC)
    ap.add_argument("--no-format-llm", action="store_true",
                    help="use the deterministic offline answer formatter "
                         "instead of an extra LLM formatting call")
    args = ap.parse_args()

    engines = list(dict.fromkeys(args.engines))  # unique, preserve order
    default_engine = engines[0]

    provider = make_provider(args.backend, args.model, region=args.region)

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
            provider, qid=qid, narrative=narrative, engines=engines,
            default_engine=default_engine, run_id=args.run_id,
            run_desc=args.run_desc, model_id=provider.model_id,
            backend=args.backend, max_chars=args.max_chars,
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
