"""Run one narrative through a strict-tool non-interactive Claude Code session."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragrun import now_iso

from cli_research_common import (
    ANSWER_SCHEMA,
    FETCH_LOCK_PATH,
    FETCH_MIN_INTERVAL,
    LOCAL_DOCSTORE_PATH,
    save_cli_answer,
    task_dir,
)

PACKAGE_DIR = Path(__file__).resolve().parent
SYSTEM_NAME = "claude-code-research"

# This file is loaded by path because the system's historical directory name
# contains hyphens and therefore cannot be imported as a Python package.
import importlib.util

_prompt_spec = importlib.util.spec_from_file_location(
    "claude_code_research_prompts", PACKAGE_DIR / "prompts.py")
assert _prompt_spec and _prompt_spec.loader
_prompts = importlib.util.module_from_spec(_prompt_spec)
_prompt_spec.loader.exec_module(_prompts)

ARCH_STAGES = [
    {"id": "loop", "label": "CLAUDE RESEARCH LOOP", "kind": "loop",
     "note": "non-interactive Claude Code executes its internal coverage plan",
     "back_to": "search", "back_from": "fetch", "back_label": "evidence gaps",
     "prompt": ["systems/claude-code-research/prompts.py::SYSTEM_PROMPT"],
     "code": ["systems/claude-code-research/pipeline.py::run_one"],
     "tools": [
         {"name": "search", "ref": "mcp/climbmix_server.py"},
         {"name": "fetch", "ref": "mcp/climbmix_server.py"},
     ],
     "tools_note": "strict MCP config advertises only search/fetch; Claude built-ins are disabled"},
    {"id": "search", "label": "SEARCH", "kind": "retrieval",
     "note": "hybrid dense+sparse RRF over ClimbMix",
     "code": ["mcp/climbmix_server.py::search"]},
    {"id": "fetch", "label": "FETCH", "kind": "retrieval",
     "note": "full ClimbMix document by docid",
     "code": ["mcp/climbmix_server.py::fetch"]},
    {"id": "contract", "label": "OUTPUT CONTRACT", "kind": "format",
     "note": "schema + fetched-doc citation enforcement",
     "code": ["systems/cli_research_common.py::normalize_answer"]},
    {"id": "save", "label": "SAVE", "kind": "artifact",
     "note": "ragrun.save_run -> trajectory + output",
     "code": ["systems/cli_research_common.py::save_cli_answer"]},
]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _read_payload(stdout: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        outer = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude did not return JSON output: {exc}") from exc
    if not isinstance(outer, dict):
        raise RuntimeError("Claude output is not a JSON object")
    if outer.get("is_error"):
        raise RuntimeError(str(outer.get("result") or "Claude reported an error"))
    payload = outer.get("structured_output")
    if payload is None and isinstance(outer.get("result"), str):
        try:
            payload = json.loads(outer["result"])
        except json.JSONDecodeError:
            payload = None
    if not isinstance(payload, dict):
        raise RuntimeError("Claude output has no structured_output object")
    usage = outer.get("usage") if isinstance(outer.get("usage"), dict) else None
    return payload, usage


def _mcp_config(path: Path, tool_log: Path) -> Path:
    config = {
        "mcpServers": {
            "climbmix": {
                "command": "bash",
                "args": [str(PACKAGE_DIR / "scripts/start_climbmix_mcp.sh")],
                "env": {
                    "MCP_TRANSPORT": "stdio",
                    "MCP_SEARCH_ENGINE": "hybrid",
                    "MCP_SEARCH_K": "10",
                    "MCP_SNIPPET_CHARS": "1000",
                    "MCP_FETCH_LOCK_PATH": FETCH_LOCK_PATH,
                    "MCP_FETCH_MIN_INTERVAL": FETCH_MIN_INTERVAL,
                    "CLIMBMIX_LOCAL_DOCSTORE": LOCAL_DOCSTORE_PATH,
                    "CLIMBMIX_MCP_LOG": str(tool_log),
                },
            }
        }
    }
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def run_one(
    *,
    qid: str,
    narrative: str,
    run_id: str,
    run_desc: str,
    model_id: str = "opus",
    effort: str = "max",
    timeout: int = 1800,
    attempts: int = 3,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Run Claude with only ClimbMix MCP search/fetch and save a valid output."""
    base = task_dir(SYSTEM_NAME, run_id, qid)
    errors: list[str] = []
    feedback: str | None = None
    for attempt in range(1, attempts + 1):
        work = base / f"{_stamp()}-attempt-{attempt}"
        work.mkdir(parents=True, exist_ok=False)
        tool_log = work / "tool_log.jsonl"
        mcp_config = _mcp_config(work / "mcp.json", tool_log)
        started_at = now_iso()
        prompt = _prompts.build_prompt(narrative, feedback)
        _write(work / "system_prompt.txt", _prompts.SYSTEM_PROMPT)
        _write(work / "prompt.txt", prompt)
        env = os.environ.copy()
        env.update({
            "MCP_TRANSPORT": "stdio",
            "MCP_SEARCH_ENGINE": "hybrid",
            "MCP_SEARCH_K": "10",
            "MCP_SNIPPET_CHARS": "1000",
            "MCP_FETCH_LOCK_PATH": FETCH_LOCK_PATH,
            "MCP_FETCH_MIN_INTERVAL": FETCH_MIN_INTERVAL,
            "CLIMBMIX_LOCAL_DOCSTORE": LOCAL_DOCSTORE_PATH,
            "CLIMBMIX_MCP_LOG": str(tool_log),
        })
        allowed = "mcp__climbmix__search,mcp__climbmix__fetch"
        denied = (
            "Bash,Read,Edit,Write,Glob,Grep,WebSearch,WebFetch,Task,Agent,"
            "NotebookEdit"
        )
        command = [
            "claude", "--print", "--output-format", "json",
            "--json-schema", json.dumps(ANSWER_SCHEMA, separators=(",", ":")),
            "--model", model_id, "--effort", effort,
            "--permission-mode", "dontAsk", "--no-session-persistence",
            "--disable-slash-commands", "--no-chrome",
            "--strict-mcp-config", "--mcp-config", str(mcp_config),
            "--tools", allowed, "--allowedTools", allowed,
            "--disallowedTools", denied,
            "--system-prompt", _prompts.SYSTEM_PROMPT,
            prompt,
        ]
        try:
            with tempfile.TemporaryDirectory(
                    prefix="trec-rag-claude-research-") as isolated_cwd:
                proc = runner(
                    command,
                    text=True,
                    capture_output=True,
                    cwd=Path(isolated_cwd),
                    env=env,
                    timeout=timeout,
                    check=False,
                )
            _write(work / "stdout.log", proc.stdout or "")
            _write(work / "stderr.log", proc.stderr or "")
            if proc.returncode != 0:
                raise RuntimeError(
                    f"claude exited {proc.returncode}: {(proc.stderr or '')[-1000:]}")
            payload, usage = _read_payload(proc.stdout)
            result = save_cli_answer(
                system_name=SYSTEM_NAME,
                cli_name="claude-code",
                qid=qid,
                narrative=narrative,
                run_id=run_id,
                run_desc=run_desc,
                model_id=model_id,
                payload=payload,
                tool_log=tool_log,
                work_dir=work,
                started_at=started_at,
                ended_at=now_iso(),
                usage=usage,
            )
            result.update({"work_dir": work, "attempt": attempt})
            return result
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            feedback = errors[-1][-1200:]
            _write(work / "failure.txt", errors[-1] + "\n")
    raise RuntimeError(" | ".join(errors))
