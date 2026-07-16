"""CLI runner for the ClimbMix Tongyi DeepResearch port.

Runs the ported ReAct agent against a live OpenAI-compatible endpoint (vLLM
serving ``Alibaba-NLP/Tongyi-DeepResearch-30B-A3B``, OpenRouter, …) and writes
the two run artifacts via ``ragrun.save_run``:

    data/outputs/ali_deepresearch/<ts>.<slug>.trajectory.json   # full agent trace
    data/outputs/ali_deepresearch/<ts>.<slug>.output.json       # TREC RAG 2026 answer

Endpoint config (env, auto-loaded from repo ``.env`` via python-dotenv):

    ALI_DR_BASE_URL   OpenAI-compatible base URL (…/v1)
    ALI_DR_API_KEY    API key ("EMPTY" for a local vLLM)
    ALI_DR_MODEL      model id (default Alibaba-NLP/Tongyi-DeepResearch-30B-A3B)

Examples:

    uv run --group ali-deepresearch python src/systems/ali_deepresearch/run.py \\
        --qid 683a58c9a7e7fe4e7695846f
    uv run --group ali-deepresearch python src/systems/ali_deepresearch/run.py \\
        --query "..." --k 10 --max-rounds 20
    uv run --group ali-deepresearch python src/systems/ali_deepresearch/run.py --all
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

# --- import surgery ---------------------------------------------------------
# This script lives next to a local ``tools.py`` which would shadow the installed
# ``tools`` package. Drop the script dir from sys.path and expose src/systems so
# our code imports as the ``ali_deepresearch`` package while ``tools``/``utils``/
# ``ragrun`` still resolve to their editable installs.
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

from ragrun import TrajectoryBuilder, build_rag_output, save_run  # noqa: E402

from ali_deepresearch import (  # noqa: E402
    ClimbMixTools,
    ReactAgent,
    SYSTEM_PROMPT,
    format_answer,
)

SYSTEM_NAME = "ali_deepresearch"
DEFAULT_MODEL = "Alibaba-NLP/Tongyi-DeepResearch-30B-A3B"
_REPO_ROOT = Path(_SYSTEMS).resolve().parents[1]
DEFAULT_TOPICS = (_REPO_ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
                  "development-data/topics/research-rubrics-topics-dev.tsv")

# Sampling defaults mirror the reference sample run's metadata.
TEMPERATURE = 0.85
TOP_P = 0.95
PRESENCE_PENALTY = 1.1


class OpenAIChatLLM:
    """``ChatLLM`` over an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, *, base_url: str, api_key: str, model: str,
                 temperature: float = TEMPERATURE, top_p: float = TOP_P,
                 presence_penalty: float = PRESENCE_PENALTY,
                 timeout: float = 600.0, max_tries: int = 5) -> None:
        from openai import OpenAI

        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.presence_penalty = presence_penalty
        self.max_tries = max_tries
        self._client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY",
                              timeout=timeout)

    def complete(self, messages: list[dict[str, str]], *,
                 stop: list[str] | None = None,
                 max_tokens: int | None = None) -> str:
        import time

        last_err: Exception | None = None
        for attempt in range(self.max_tries):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model, messages=messages, stop=stop,
                    temperature=self.temperature, top_p=self.top_p,
                    presence_penalty=self.presence_penalty,
                    max_tokens=max_tokens or 10000)
                content = resp.choices[0].message.content
                if content and content.strip():
                    return content.strip()
            except Exception as e:  # transient endpoint/network errors
                last_err = e
            if attempt < self.max_tries - 1:
                time.sleep(min(2 ** attempt, 30))
        raise RuntimeError(f"endpoint call failed after {self.max_tries} tries: "
                           f"{last_err}")


def build_metadata(query: str, model: str, k: int) -> dict[str, Any]:
    """Trajectory metadata, mirroring the reference sample's field set."""
    return {
        "model": model,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "presence_penalty": PRESENCE_PENALTY,
        "snippet_max_tokens": 64,
        "k": k,
        "searcher_type": "hybrid-rrf",
        "query_style": "plain",
        "retriever_model_name": "jinaai/jina-embeddings-v5-text-nano",
        "index_path": None,
        "dataset_name": "climbmix-400b",
        "pooling": None,
        "normalize": False,
        "torch_dtype": None,
        "task_prefix": None,
        "max_length": None,
        "query_source": query,
    }


def steps_to_trajectory(result, metadata: dict[str, Any]) -> dict[str, Any]:
    """Map an ``AgentResult`` onto a ``TrajectoryBuilder`` trajectory dict.

    Per-step wall-clock ``t_start``/``t_end`` and the 0-based LLM-round
    ``turn`` index recorded by the ReAct loop are carried into the rich
    ``output.json.trace`` projection; trajectory items remain strict.
    """
    tb = TrajectoryBuilder(result.query_id, result.query, metadata=metadata)
    for step in result.steps:
        kind = step["kind"]
        timing = {"t_start": step.get("t_start"), "t_end": step.get("t_end"),
                  "turn": step.get("turn")}
        if kind == "reasoning":
            tb.add_reasoning(step["text"], **timing)
        elif kind == "answer":
            tb.add_output_text(step["text"], **timing)
        elif kind == "tool_call":
            tb.add_tool_call(
                step["name"], step["arguments"], step["output"],
                returned=step.get("returned"),
                returned_docids=step.get("returned_docids"),
                failed=step.get("failed", False),
                **timing,
                **step.get("extras", {}))
    return tb.finalize(status=result.status, raw_messages=result.messages,
                       started_at=result.started_at, ended_at=result.ended_at)


def candidate_docids(result) -> list[str]:
    """Docids the answer may cite: documents opened with get_document first
    (the model actually read them), then docids surfaced by search."""
    opened: list[str] = []
    searched: list[str] = []
    for step in result.steps:
        if step["kind"] != "tool_call":
            continue
        if step["name"] == "get_document" and not step.get("failed"):
            did = step.get("extras", {}).get("docid")
            if did:
                opened.append(did)
        elif step["name"] == "search":
            searched.extend(step.get("returned_docids") or [])
    return list(dict.fromkeys(opened + searched))


def run_one(agent: ReactAgent, *, qid: str, query: str, run_id: str,
            run_desc: str, model: str, k: int,
            format_llm: Any | None) -> dict[str, Path]:
    result = agent.run(query, query_id=qid)
    trajectory = steps_to_trajectory(result, build_metadata(query, model, k))

    references, answer = format_answer(
        result.answer_text or "", candidate_docids(result), llm=format_llm)
    output = build_rag_output(
        narrative_id=qid, narrative=query, run_id=run_id, run_desc=run_desc,
        references=references, answer=answer)

    paths = save_run(SYSTEM_NAME, query, trajectory=trajectory, output=output)
    tag = "OK" if "violations" not in paths else "VIOLATIONS"
    print(f"[{tag}] {qid}: status={result.status} rounds={result.rounds} "
          f"refs={len(references)} -> {paths['output'].name}")
    if "violations" in paths:
        print(f"       violations: {paths['violations'].name}")
    return paths


def load_topics(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        qid, _, narrative = line.partition("\t")
        if qid and narrative:
            rows.append((qid.strip(), narrative.strip()))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Tongyi DeepResearch (ClimbMix port)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--query", help="Run a single ad-hoc narrative.")
    g.add_argument("--qid", help="Run one topic id from the topics TSV.")
    g.add_argument("--all", action="store_true", help="Run every topic in the TSV.")
    ap.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    ap.add_argument("--base-url", default=os.environ.get("ALI_DR_BASE_URL"))
    ap.add_argument("--api-key", default=os.environ.get("ALI_DR_API_KEY", "EMPTY"))
    ap.add_argument("--model",
                    default=os.environ.get("ALI_DR_MODEL", DEFAULT_MODEL))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--max-rounds", type=int, default=20)
    ap.add_argument("--run-id", default="ali_deepresearch.dev")
    ap.add_argument("--run-desc",
                    default="Alibaba Tongyi DeepResearch ReAct agent, ClimbMix "
                            "corpus-only retrieval (hybrid RRF), Tongyi-30B-A3B.")
    ap.add_argument("--no-format-llm", action="store_true",
                    help="Skip the LLM answer-formatting call; use the offline "
                         "heuristic sentence/citation splitter.")
    args = ap.parse_args()

    if not args.base_url:
        ap.error("no endpoint: set ALI_DR_BASE_URL or pass --base-url")

    # Resolve the work items.
    if args.query:
        items = [("adhoc", args.query)]
    else:
        topics = load_topics(args.topics)
        if args.all:
            items = topics
        else:
            items = [(q, n) for q, n in topics if q == args.qid]
            if not items:
                ap.error(f"qid {args.qid!r} not found in {args.topics}")

    llm = OpenAIChatLLM(base_url=args.base_url, api_key=args.api_key,
                        model=args.model)
    format_llm = None if args.no_format_llm else llm
    system_prompt = SYSTEM_PROMPT + str(date.today())

    for qid, query in items:
        agent = ReactAgent(llm, system_prompt, toolbox=ClimbMixTools(),
                           k=args.k, max_rounds=args.max_rounds)
        run_one(agent, qid=qid, query=query, run_id=args.run_id,
                run_desc=args.run_desc, model=args.model, k=args.k,
                format_llm=format_llm)


if __name__ == "__main__":
    main()
