"""Run one narrative through a tool-restricted non-interactive Codex session."""
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
    FETCH_LOCK_PATH,
    FETCH_MIN_INTERVAL,
    LOCAL_DOCSTORE_PATH,
    save_cli_answer,
    task_dir,
    write_answer_schema,
)
from codex_cli_research.prompts import SYSTEM_PROMPT, build_prompt

SYSTEM_NAME = "codex-cli-research"
PACKAGE_DIR = Path(__file__).resolve().parent

ARCH_STAGES = [
    {"id": "loop", "label": "CODEX RESEARCH LOOP", "kind": "loop",
     "note": "non-interactive Codex executes its internal coverage plan",
     "back_to": "search", "back_from": "fetch", "back_label": "evidence gaps",
     "prompt": ["systems/codex_cli_research/prompts.py::SYSTEM_PROMPT"],
     "code": ["systems/codex_cli_research/pipeline.py::run_one"],
     "tools": [
         {"name": "search", "ref": "mcp/climbmix_server.py"},
         {"name": "fetch", "ref": "mcp/climbmix_server.py"},
     ],
     "tools_note": "Codex hook denies every local tool except these two; web search is disabled"},
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


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Codex did not produce valid structured output: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Codex structured output is not a JSON object")
    return payload


def run_one(
    *,
    qid: str,
    narrative: str,
    run_id: str,
    run_desc: str,
    model_id: str = "gpt-5.6-sol",
    reasoning_effort: str = "xhigh",
    timeout: int = 1800,
    attempts: int = 2,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Run Codex with only ClimbMix MCP search/fetch and save a valid output."""
    base = task_dir(SYSTEM_NAME, run_id, qid)
    errors: list[str] = []
    feedback: str | None = None
    for attempt in range(1, attempts + 1):
        work = base / f"{_stamp()}-attempt-{attempt}"
        work.mkdir(parents=True, exist_ok=False)
        schema = write_answer_schema(work / "answer.schema.json")
        final_path = work / "answer.json"
        tool_log = work / "tool_log.jsonl"
        guard_log = work / "tool_guard.jsonl"
        started_at = now_iso()
        prompt = build_prompt(narrative, feedback)
        instructions = work / "model_instructions.txt"
        _write(instructions, SYSTEM_PROMPT)
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
            "CLI_RESEARCH_GUARD_LOG": str(guard_log),
        })
        command = [
            "codex", "exec", "--ephemeral", "--ignore-user-config",
            "--strict-config", "--sandbox", "read-only",
            "--model", model_id,
            "-c", 'web_search="disabled"',
            "-c", 'approval_policy="never"',
            "-c", "allow_login_shell=false",
            "-c", "project_root_markers=[]",
            "-c", "features.shell_tool=false",
            "-c", f"model_instructions_file={json.dumps(str(instructions))}",
            "-c", 'mcp_servers.climbmix.command="bash"',
            "-c", "mcp_servers.climbmix.args=[" +
            json.dumps(str(PACKAGE_DIR / "scripts/start_climbmix_mcp.sh")) + "]",
            "-c", (
                'mcp_servers.climbmix.env={MCP_TRANSPORT="stdio",'
                'MCP_SEARCH_ENGINE="hybrid",MCP_SEARCH_K="10",'
                'MCP_SNIPPET_CHARS="1000",MCP_FETCH_LOCK_PATH='
                f'{json.dumps(FETCH_LOCK_PATH)},MCP_FETCH_MIN_INTERVAL='
                f'{json.dumps(FETCH_MIN_INTERVAL)},CLIMBMIX_LOCAL_DOCSTORE='
                f'{json.dumps(LOCAL_DOCSTORE_PATH)},CLIMBMIX_MCP_LOG='
                f'{json.dumps(str(tool_log))}' + '}'),
            "-c", "mcp_servers.climbmix.startup_timeout_sec=30",
            "-c", "mcp_servers.climbmix.tool_timeout_sec=180",
            "-c", "mcp_servers.climbmix.required=true",
            "-c", 'mcp_servers.climbmix.enabled_tools=["search","fetch"]',
            "-c", 'mcp_servers.climbmix.default_tools_approval_mode="approve"',
            "-c", ('hooks.PreToolUse=[{matcher="*",hooks=[{type="command",'
                   'command=' + json.dumps(
                       f'python3 {PACKAGE_DIR / "hooks/tool_guard.py"}') +
                   ',timeout=5}]}]'),
            "-c", f'model_reasoning_effort="{reasoning_effort}"',
            "--output-schema", str(schema),
            "--output-last-message", str(final_path), "-",
        ]
        try:
            with tempfile.TemporaryDirectory(
                    prefix="trec-rag-codex-research-") as isolated_cwd:
                proc = runner(
                    command,
                    input=prompt,
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
                    f"codex exec exited {proc.returncode}: {(proc.stderr or '')[-1000:]}")
            result = save_cli_answer(
                system_name=SYSTEM_NAME,
                cli_name="codex",
                qid=qid,
                narrative=narrative,
                run_id=run_id,
                run_desc=run_desc,
                model_id=model_id,
                payload=_read_payload(final_path),
                tool_log=tool_log,
                work_dir=work,
                started_at=started_at,
                ended_at=now_iso(),
            )
            result.update({"work_dir": work, "attempt": attempt})
            return result
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            feedback = errors[-1][-1200:]
            _write(work / "failure.txt", errors[-1] + "\n")
    raise RuntimeError(" | ".join(errors))
