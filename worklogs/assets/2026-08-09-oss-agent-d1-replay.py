"""D1 diagnostic: fixed-evidence replay (worklogs/2026-08-09-oss-agent-open-
weight-system.md, sol+Gemini plan review). Isolates retrieval/curation
quality from synthesis quality: qwen writes the final report with NO
search/commit tools, from a FROZEN evidence package -- either its own live
committed evidence (E-Q, self-check on the replay harness) or
aus_agent_v2's own committed evidence (E-P, the strongest system in the
repo) for the same 15 topics.

Reuses the shared harness's own citation parsing/mapping
(agent_harness.agent._parse_final_prose/_map_citations/_collapse_to_docs)
and document fetch (agent_harness.tools.get_documents.execute_get_documents)
rather than reimplementing either -- this script only replaces the tool
loop with one static evidence block and one write call.

Usage (repo root):
    uv run --group oss-agent python worklogs/assets/2026-08-09-oss-agent-d1-replay.py \
        --source EQ --run-id d1-replay-qwen-EQ-exp15
    uv run --group oss-agent python worklogs/assets/2026-08-09-oss-agent-d1-replay.py \
        --source EP --run-id d1-replay-qwen-EP-exp15
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "src" / "systems"))

from dotenv import load_dotenv

load_dotenv(str(_REPO_ROOT / ".env"))
import os

if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
    os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]

from agent_harness.agent import (  # noqa: E402
    _collapse_to_docs,
    _map_citations,
    _parse_final_prose,
    make_provider,
)
from agent_harness.tools.get_documents import execute_get_documents  # noqa: E402
from facet_rag.llm import one_shot  # noqa: E402
from ragrun.outputs import build_rag_output, save_run  # noqa: E402

WRITER_MODEL = "qwen.qwen3-next-80b-a3b"
WRITER_REGION = "us-east-1"
TOPICS_TSV = (_REPO_ROOT / "worklogs/assets/2026-08-09-oss-agent-exp15-topics.tsv")

SYSTEM_PROMPT = """\
You are a corpus-grounded research assistant. Your evidence-gathering is \
already complete -- everything you may cite is given to you below, labeled \
by id. No search tool is available in this call; write the FINAL report now.

Output contract:
- Plain prose, one sentence per line.
- Every factual sentence ends with inline citation markers naming the exact \
evidence id(s) it is drawn from, e.g. "Peak demand rose 12% in 2019 \
[shard_00123_456_p1]." At most 3 ids per sentence.
- Cite ONLY ids from the evidence block below -- never invent or guess an id.
- Do not use Markdown headings, bullet lists, or code fences.
- Target 700-950 words; the hard cap is 1024 words.
- Write only the report. No preamble, no meta-commentary about the evidence."""


def load_committed(system: str, run_id: str) -> dict[str, list[str]]:
    """qid -> ordered list of committed chunk-unit ids, from an existing
    output.json's trace.summary.context.committed field."""
    out: dict[str, list[str]] = {}
    for path in glob.glob(str(_REPO_ROOT / f"data/outputs/{system}/*.output.json")):
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        md = obj.get("metadata", {})
        if md.get("run_id") != run_id:
            continue
        committed = (obj.get("trace", {}).get("summary", {})
                    .get("context", {}).get("committed", []))
        out[md["narrative_id"]] = list(committed)
    return out


def load_topics() -> list[tuple[str, str]]:
    rows = []
    for line in TOPICS_TSV.read_text().splitlines():
        qid, _, narrative = line.partition("\t")
        if qid.strip():
            rows.append((qid.strip(), narrative.strip()))
    return rows


def render_evidence_block(documents: list[dict]) -> str:
    parts = []
    for doc in documents:
        parts.append(f"=== EVIDENCE [{doc['id']}] ===\n{doc['text']}")
    return "\n\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["EQ", "EP"], required=True,
                    help="EQ = qwen's own live-committed evidence (oss-bakeoff-"
                         "qwen-exp15), EP = aus_agent_v2's committed evidence "
                         "(aus-agent-v2-exp15-luna)")
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    if args.source == "EQ":
        committed_by_qid = load_committed("oss_agent", "oss-bakeoff-qwen-exp15")
    else:
        committed_by_qid = load_committed("aus_agent_v2", "aus-agent-v2-exp15-luna")

    topics = load_topics()
    provider = make_provider("bedrock", WRITER_MODEL, region=WRITER_REGION)

    for qid, narrative in topics:
        committed_ids = committed_by_qid.get(qid)
        if not committed_ids:
            print(f"=== {qid}: NO committed evidence found for source "
                 f"{args.source}, skipping", flush=True)
            continue
        print(f"=== {qid}: {narrative[:70]}... ({len(committed_ids)} docs)",
             flush=True)
        _, documents, missing = execute_get_documents({"ids": committed_ids})
        if missing:
            print(f"  {len(missing)}/{len(committed_ids)} ids not fetchable, "
                 "proceeding with the rest", flush=True)
        evidence_block = render_evidence_block(documents)
        user_text = (f"RESEARCH REQUEST\n\n{narrative}\n\n"
                    f"{evidence_block}")
        raw = one_shot(provider, SYSTEM_PROMPT, user_text)

        seen_ids = {d["id"] for d in documents}
        sentences, errors, repairs = _parse_final_prose(
            raw, seen_ids, allow_uncited=True)
        if sentences is None:
            print(f"  PARSE FAILED: {errors}", flush=True)
            sentences = [{"text": f"Replay parse failed: {errors}",
                         "citations": []}]
        references_unit, answer = _map_citations(sentences, seen_ids)
        references, answer = _collapse_to_docs(references_unit, answer)

        output = build_rag_output(
            narrative_id=qid, narrative=narrative, run_id=args.run_id,
            run_desc=(f"D1 fixed-evidence replay ({args.source}): qwen writes "
                     f"with no tool loop from {len(committed_ids)} frozen "
                     f"committed docs, no live retrieval."),
            references=references, answer=answer)
        paths = save_run("oss_agent", narrative, trajectory={},
                         output=output, write_trajectory=False)
        n_words = sum(len(s["text"].split()) for s in answer)
        print(f"  -> {paths['output']} ({len(answer)} sentences, "
             f"{len(references)} refs, {n_words} words)", flush=True)


if __name__ == "__main__":
    main()
