"""Assemble the two standard run artifacts for a claude-code-research task.

Post-research step: reads the task folder's ``scratchpad/tool_log.jsonl``
(written by ``scripts/corpus.py``) and the lead agent's answer-sentences JSON,
rebuilds the trajectory via ``ragrun.TrajectoryBuilder``, maps docid citations
to reference indices, and persists both artifacts with ``ragrun.save_run`` to
``data/outputs/claude-code-research/<ts>.<slug>.{trajectory,output}.json``.

Usage (root env):

    uv run python scripts/save_run.py --task-dir <task-dir> --qid <qid> \
        (--query "<narrative>" | --topics <topics.tsv>) \
        --answer-json <task-dir>/answer_sentences.json

answer-json schema (written by the lead agent at the end of research):

    {"run_id": "<run id>", "run_desc": "<one-line run description>",
     "answer": [{"text": "<sentence>",
                 "citations": ["<climbmix docid>", ...]},   # at most 3
                ...]}

Citations must be docids returned by logged tool calls; any docid never
retrieved is dropped with a warning. If ``scratchpad/reasoning.md`` exists its
content is recorded as a leading reasoning item. Exits non-zero when the
output object violates the track rules (violations are printed and also saved
alongside the artifacts).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ragrun import TrajectoryBuilder, build_rag_output, save_run, validate_rag_output

SYSTEM_NAME = "claude-code-research"


def load_narrative(topics_tsv: Path, qid: str) -> str:
    """Look up a topic narrative by qid in a ``qid\\tnarrative`` TSV."""
    with topics_tsv.open(encoding="utf-8") as f:
        for line in f:
            tid, _, narrative = line.rstrip("\n").partition("\t")
            if tid == qid:
                return narrative
    sys.exit(f"save_run.py: qid {qid!r} not found in {topics_tsv}")


def read_tool_log(task_dir: Path) -> list[dict[str, Any]]:
    """Parse ``scratchpad/tool_log.jsonl`` (one record per corpus.py call)."""
    log = task_dir / "scratchpad" / "tool_log.jsonl"
    if not log.exists():
        sys.exit(f"save_run.py: no tool log at {log} — research must go "
                 "through scripts/corpus.py")
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def build_trajectory(tb: TrajectoryBuilder, records: list[dict[str, Any]]) -> set[str]:
    """Replay logged tool calls into ``tb``; return all retrieved docids."""
    retrieved: set[str] = set()
    for rec in records:
        name = rec.get("tool_name", "")
        arguments = rec.get("arguments", {})
        output = rec.get("output_head", "")
        failed = bool(rec.get("failed"))
        returned = rec.get("returned")
        returned_docids: list[str] | None = None
        if returned is not None:
            returned_docids = [h["docid"] for h in returned]
        elif name == "get_document" and not failed:
            returned_docids = [arguments["docid"]]
        if returned_docids:
            retrieved.update(returned_docids)
        # t_start/t_end: wall-clock bounds logged by corpus.py. No ``turn`` —
        # CLI calls have no model-turn concept.
        tb.add_tool_call(name, arguments, output, returned=returned,
                         returned_docids=returned_docids, failed=failed,
                         t_start=rec.get("t_start"), t_end=rec.get("t_end"),
                         ts=rec.get("ts"))
    return retrieved


def map_citations(sentences: list[dict[str, Any]],
                  retrieved: set[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """Map per-sentence docid citations to reference-list indices.

    References are the cited docids in first-appearance order; docids not in
    ``retrieved`` are dropped with a warning on stderr.
    """
    references: list[str] = []
    index: dict[str, int] = {}
    answer: list[dict[str, Any]] = []
    for i, sent in enumerate(sentences):
        cits: list[int] = []
        for docid in sent.get("citations", []):
            if docid not in retrieved:
                print(f"save_run.py: WARNING answer[{i}] cites {docid!r}, "
                      "which no logged tool call returned — dropped",
                      file=sys.stderr)
                continue
            if docid not in index:
                index[docid] = len(references)
                references.append(docid)
            if index[docid] not in cits:
                cits.append(index[docid])
        answer.append({"text": sent["text"], "citations": cits})
    return references, answer


def render_answer_text(sentences: list[dict[str, Any]]) -> str:
    """Flatten sentences to one cited answer string: ``text [docid][docid]``."""
    parts = []
    for sent in sentences:
        cites = "".join(f"[{d}]" for d in sent.get("citations", []))
        parts.append(f"{sent['text']} {cites}".rstrip())
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Assemble trajectory + output artifacts from a task folder")
    ap.add_argument("--task-dir", required=True, help="the research task folder")
    ap.add_argument("--qid", required=True, help="topic / narrative id")
    ap.add_argument("--query", help="topic narrative text")
    ap.add_argument("--topics", type=Path,
                    help="topics TSV (qid\\tnarrative) to look the narrative up in")
    ap.add_argument("--answer-json", required=True, type=Path,
                    help="answer-sentences JSON written by the lead agent")
    args = ap.parse_args()

    if not args.query and not args.topics:
        ap.error("pass --query or --topics")
    query = args.query or load_narrative(args.topics, args.qid)
    task_dir = Path(args.task_dir)

    payload = json.loads(args.answer_json.read_text(encoding="utf-8"))
    run_id = payload["run_id"]
    run_desc = payload["run_desc"]
    sentences = payload["answer"]

    tb = TrajectoryBuilder(args.qid, query, metadata={
        "system": SYSTEM_NAME,
        "run_id": run_id,
        "run_desc": run_desc,
        "task_dir": str(task_dir),
    })
    reasoning = task_dir / "scratchpad" / "reasoning.md"
    if reasoning.exists():
        tb.add_reasoning(reasoning.read_text(encoding="utf-8"))
    retrieved = build_trajectory(tb, read_tool_log(task_dir))
    tb.add_output_text(render_answer_text(sentences))
    trajectory = tb.finalize(status="completed")

    references, answer = map_citations(sentences, retrieved)
    output = build_rag_output(narrative_id=args.qid, narrative=query,
                              run_id=run_id, run_desc=run_desc,
                              references=references, answer=answer)

    violations = validate_rag_output(output)
    paths = save_run(SYSTEM_NAME, query, trajectory=trajectory, output=output)
    print("trajectory:", paths["trajectory"])
    print("output:    ", paths["output"])
    print("tool_call_counts:", json.dumps(trajectory["tool_call_counts"]))
    if violations:
        print(f"VIOLATIONS ({len(violations)}):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)
    print("violations: none")


if __name__ == "__main__":
    main()
