"""Shared strict-output assembly for Codex CLI and Claude Code research runs.

The model-facing agents receive only the two-tool ClimbMix MCP contract.  This
module owns everything after the CLI exits: it verifies that cited document ids
were actually fetched, converts them to reference indices, replays the private
MCP log into the standard trajectory, validates the organizer object, and saves
the normal ``trajectory.json`` / ``output.json`` pair.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ragrun import (
    TrajectoryBuilder,
    build_rag_output,
    now_iso,
    save_run,
    validate_rag_output,
)
from ragrun.outputs import data_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOPICS = (
    REPO_ROOT / "data/official/trec-rag-2026-data/trec-rag-2026/"
    "development-data/topics/research-rubrics-topics-dev.tsv"
)
FETCH_LOCK_PATH = os.environ.get(
    "CLI_RESEARCH_FETCH_LOCK", "/tmp/trec-rag-cli-research-fetch.lock")
FETCH_MIN_INTERVAL = os.environ.get("CLI_RESEARCH_FETCH_MIN_INTERVAL", "0.5")
LOCAL_DOCSTORE_PATH = os.environ.get(
    "CLI_RESEARCH_LOCAL_DOCSTORE",
    str(REPO_ROOT / "data/built-indexes/climbmix-full/docstore"),
)
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "pattern": r"^(?:\S+\s*){1,30}$",
                    },
                    "citations": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {
                            "type": "string",
                            "pattern": r"^shard_[0-9]+_[0-9]+$",
                        },
                    },
                },
                "required": ["text", "citations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer"],
    "additionalProperties": False,
}


class OutputContractError(ValueError):
    """The CLI returned an answer that cannot be made submission-safe."""


def load_topics(path: Path = DEFAULT_TOPICS) -> list[tuple[str, str]]:
    """Load exact qid/narrative pairs without normalizing narrative content."""
    rows: list[tuple[str, str]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        qid, sep, narrative = raw.partition("\t")
        if not sep or not qid or not narrative:
            raise ValueError(f"malformed topics row {number} in {path}")
        rows.append((qid, narrative))
    return rows


def task_dir(system_name: str, run_id: str, qid: str) -> Path:
    """Keep CLI scratch artifacts under data rather than the source package."""
    safe_run = "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id)
    safe_qid = "".join(c if c.isalnum() or c in "-_." else "_" for c in qid)
    path = data_dir() / "agent-work" / system_name / safe_run / safe_qid
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_answer_schema(path: Path) -> Path:
    """Write the one shared structured-output schema used by both CLIs."""
    path.write_text(json.dumps(ANSWER_SCHEMA, indent=2) + "\n", encoding="utf-8")
    return path


def read_tool_log(path: Path) -> list[dict[str, Any]]:
    """Read the per-agent stdio MCP log, rejecting malformed non-object rows."""
    if not path.exists():
        raise OutputContractError(f"no ClimbMix MCP tool log at {path}")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise OutputContractError(f"tool log row {number} is not an object")
        records.append(row)
    return records


def fetched_docids(records: list[dict[str, Any]]) -> set[str]:
    """Only successful full-document fetches authorize answer citations."""
    return {
        str(hit["docid"])
        for row in records
        if row.get("tool_name") == "fetch" and not row.get("failed")
        for hit in row.get("returned", [])
        if isinstance(hit, dict) and hit.get("docid")
    }


def normalize_answer(
    payload: dict[str, Any], records: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate the model payload and map fetched docids to reference indices."""
    if not isinstance(payload, dict) or set(payload) != {"answer"}:
        raise OutputContractError("final payload must contain exactly 'answer'")
    raw_answer = payload["answer"]
    if not isinstance(raw_answer, list) or not raw_answer:
        raise OutputContractError("answer must be a non-empty list")

    fetched = fetched_docids(records)
    references: list[str] = []
    ref_index: dict[str, int] = {}
    answer: list[dict[str, Any]] = []
    errors: list[str] = []
    total_words = 0
    for index, item in enumerate(raw_answer):
        if not isinstance(item, dict) or set(item) != {"text", "citations"}:
            raise OutputContractError(
                f"answer[{index}] must contain exactly text and citations")
        text = item["text"]
        citations = item["citations"]
        if not isinstance(text, str) or not text.strip():
            raise OutputContractError(f"answer[{index}].text must be non-empty")
        total_words += len(text.split())
        if not isinstance(citations, list) or len(citations) > 3:
            raise OutputContractError(
                f"answer[{index}].citations must contain at most three docids")
        mapped: list[int] = []
        for docid in citations:
            if not isinstance(docid, str):
                raise OutputContractError(
                    f"answer[{index}] has a non-string citation")
            if docid not in fetched:
                errors.append(
                    f"answer[{index}] cites {docid!r}, which was not fetched")
                continue
            if docid not in ref_index:
                ref_index[docid] = len(references)
                references.append(docid)
            position = ref_index[docid]
            if position not in mapped:
                mapped.append(position)
        answer.append({"text": text, "citations": mapped})
    if not fetched:
        errors.append("the agent fetched no full ClimbMix documents")
    if not references:
        errors.append("the answer cites no fetched ClimbMix documents")
    if total_words > 1024:
        errors.append(f"answer is {total_words} words (max 1024)")
    if errors:
        raise OutputContractError("; ".join(errors))
    return references, answer


def _replay_tools(tb: TrajectoryBuilder, records: list[dict[str, Any]]) -> None:
    """Project MCP calls into the repository's strict and rich trace formats."""
    for turn, row in enumerate(records):
        returned = row.get("returned")
        returned_docids = None
        if isinstance(returned, list):
            returned_docids = [
                str(hit["docid"])
                for hit in returned
                if isinstance(hit, dict) and hit.get("docid")
            ]
        tb.add_tool_call(
            str(row.get("tool_name", "unknown")),
            row.get("arguments", {}),
            str(row.get("output_head") or row.get("error") or ""),
            returned=returned if isinstance(returned, list) else None,
            returned_docids=returned_docids,
            failed=bool(row.get("failed")),
            t_start=row.get("t_start"),
            t_end=row.get("t_end"),
            turn=turn,
        )


def _render_answer(answer: list[dict[str, Any]], references: list[str]) -> str:
    """Render the structured answer only for the strict trajectory output item."""
    parts: list[str] = []
    for item in answer:
        markers = "".join(f"[{references[i]}]" for i in item["citations"])
        parts.append(f"{item['text']} {markers}".rstrip())
    return "\n".join(parts)


def save_cli_answer(
    *,
    system_name: str,
    cli_name: str,
    qid: str,
    narrative: str,
    run_id: str,
    run_desc: str,
    model_id: str,
    payload: dict[str, Any],
    tool_log: Path,
    work_dir: Path,
    started_at: str,
    ended_at: str | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build, validate, and persist one CLI-agent run from its private log."""
    records = read_tool_log(tool_log)
    references, answer = normalize_answer(payload, records)
    ended_at = ended_at or now_iso()
    metadata: dict[str, Any] = {
        "system": system_name,
        "agent_cli": cli_name,
        "model": model_id,
        "run_id": run_id,
        "task_dir": str(work_dir),
    }
    if usage:
        metadata["usage"] = usage
    tb = TrajectoryBuilder(qid, narrative, metadata=metadata)
    _replay_tools(tb, records)
    rendered = _render_answer(answer, references)
    tb.add_output_text(rendered, t_start=ended_at, t_end=ended_at)
    tb.set_trace_output({"references": references, "answer": answer})
    trajectory = tb.finalize(
        status="completed", started_at=started_at, ended_at=ended_at)
    output = build_rag_output(
        narrative_id=qid,
        narrative=narrative,
        run_id=run_id,
        run_desc=run_desc,
        references=references,
        answer=answer,
    )
    violations = validate_rag_output(output)
    if violations:
        raise OutputContractError("; ".join(violations))
    paths = save_run(system_name, narrative, trajectory=trajectory, output=output)
    return {
        "paths": paths,
        "references": references,
        "answer_items": len(answer),
        "words": sum(len(item["text"].split()) for item in answer),
        "tool_calls": len(records),
        "status": "completed",
    }


def completed_qids(system_name: str, run_id: str) -> set[str]:
    """Find completed qids so a stopped full-30 run can resume safely."""
    output_dir = data_dir() / "outputs" / system_name
    completed: set[str] = set()
    for path in output_dir.glob("*.output.json") if output_dir.exists() else ():
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if obj.get("metadata", {}).get("run_id") != run_id:
            continue
        if obj.get("trace", {}).get("status") == "completed":
            completed.add(str(obj["metadata"]["narrative_id"]))
    return completed
