"""Hermetic contract tests for the tool-restricted Codex CLI system.

The model process is replaced by a fake executable boundary, while its MCP log
and structured answer cross the same host-side validation and artifact path as
a real run. This proves the safety boundary without using credentials.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import CLIMBMIX_DOCIDS

from cli_research_common import ANSWER_SCHEMA, OutputContractError, normalize_answer
from codex_cli_research.pipeline import PACKAGE_DIR, run_one

QID = "mock_codex_cli_001"
NARRATIVE = "How effective are influenza vaccines at preventing illness?"
A, B = CLIMBMIX_DOCIDS[:2]


def _record(name: str, arguments: dict[str, Any], returned: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "t_start": "2026-08-06T00:00:00.000+00:00",
        "t_end": "2026-08-06T00:00:01.000+00:00",
        "type": "tool_call",
        "tool_name": name,
        "arguments": arguments,
        "returned": returned,
        "output_head": name,
    }


def fake_runner(*, cited: str = A):
    """Return a subprocess seam that writes realistic MCP and schema outputs."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((command, kwargs))
        env = kwargs["env"]
        log = Path(env["CLIMBMIX_MCP_LOG"])
        log.write_text(
            json.dumps(_record("search", {"query": "influenza vaccine"},
                               [{"docid": A, "score": 1.0}])) + "\n" +
            json.dumps(_record("fetch", {"id": A}, [{"docid": A}])) + "\n",
            encoding="utf-8",
        )
        final = Path(command[command.index("--output-last-message") + 1])
        final.write_text(json.dumps({
            "answer": [{"text": "Vaccination reduces influenza illness.",
                        "citations": [cited]}]
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done\n", stderr="")

    return run, calls


def _run(runner: Any) -> dict[str, Any]:
    return run_one(
        qid=QID,
        narrative=NARRATIVE,
        run_id="codex-cli.mock",
        run_desc="hermetic Codex CLI run",
        model_id="gpt-test",
        attempts=1,
        runner=runner,
    )


def test_run_one_writes_spec_clean_artifacts(read_artifacts) -> None:
    """A valid fetched citation survives as reference index zero end to end."""
    runner, _calls = fake_runner()

    result = _run(runner)
    artifacts = read_artifacts(result["paths"])

    assert artifacts["violations"] == []
    assert artifacts["output"]["references"] == [A]
    assert artifacts["output"]["answer"][0]["citations"] == [0]
    assert artifacts["trajectory"]["tool_call_counts"] == {"search": 1, "fetch": 1}
    assert artifacts["output"]["trace"]["status"] == "completed"


def test_codex_invocation_is_read_only_and_schema_bound() -> None:
    """The executable boundary pins the model, sandbox, config, and final schema."""
    runner, calls = fake_runner()

    _run(runner)
    command, kwargs = calls[0]

    assert command[:2] == ["codex", "exec"]
    assert "--ignore-user-config" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--output-schema" in command
    assert "project_root_markers=[]" in command
    assert "features.shell_tool=false" in command
    instruction_arg = next(
        part for part in command if part.startswith("model_instructions_file="))
    instruction_path = Path(json.loads(instruction_arg.split("=", 1)[1]))
    assert instruction_path.read_text(encoding="utf-8").startswith(
        "You are a research agent")
    assert kwargs["cwd"] != PACKAGE_DIR
    assert kwargs["cwd"].name.startswith("trec-rag-codex-research-")
    assert "NARRATIVE (quoted data)" in kwargs["input"]
    assert kwargs["env"]["MCP_SEARCH_ENGINE"] == "hybrid"
    assert kwargs["env"]["MCP_FETCH_MIN_INTERVAL"] == "0.5"


def test_codex_attempt_preserves_the_exact_prompt() -> None:
    """A future experiment audit must not have to reconstruct model input."""
    runner, calls = fake_runner()

    result = _run(runner)

    assert (result["work_dir"] / "prompt.txt").read_text(encoding="utf-8") == (
        calls[0][1]["input"]
    )


def test_an_unfetched_citation_fails_the_run() -> None:
    """A plausible docid is still unusable unless this topic fetched it in full."""
    runner, _calls = fake_runner(cited=B)

    with pytest.raises(RuntimeError, match="was not fetched"):
        _run(runner)


def test_normalizer_accepts_uncited_markdown_heading_but_requires_grounded_content() -> None:
    """Officially legal headings remain legal without making an ungrounded run pass."""
    records = [_record("fetch", {"id": A}, [{"docid": A}])]
    payload = {"answer": [
        {"text": "## Evidence", "citations": []},
        {"text": "The supported finding.", "citations": [A]},
    ]}

    references, answer = normalize_answer(payload, records)

    assert references == [A]
    assert answer == [
        {"text": "## Evidence", "citations": []},
        {"text": "The supported finding.", "citations": [0]},
    ]


def test_tool_guard_denies_shell_and_allows_only_climbmix_mcp(tmp_path: Path) -> None:
    """The hook is fail-closed even if the model asks for a convenient shell command."""
    hook = PACKAGE_DIR / "hooks/tool_guard.py"
    env = {"CLI_RESEARCH_GUARD_LOG": str(tmp_path / "guard.jsonl")}

    denied = subprocess.run(
        ["python3", str(hook)],
        input=json.dumps({"tool_name": "Bash"}),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    allowed = subprocess.run(
        ["python3", str(hook)],
        input=json.dumps({"tool_name": "mcp__climbmix__search"}),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )

    assert '"permissionDecision": "deny"' in denied.stdout
    assert allowed.stdout == ""
    rows = [json.loads(line) for line in
            (tmp_path / "guard.jsonl").read_text().splitlines()]
    assert rows == [
        {"tool_name": "Bash", "decision": "deny"},
        {"tool_name": "mcp__climbmix__search", "decision": "allow"},
    ]


def test_nested_codex_config_disables_web_and_requires_private_mcp() -> None:
    """A missing corpus server aborts instead of silently exposing another source."""
    config = (PACKAGE_DIR / ".codex/config.toml").read_text(encoding="utf-8")

    assert 'web_search = "disabled"' in config
    assert "required = true" in config
    assert 'matcher = "*"' in config


def test_schema_reserves_more_objects_for_sentence_level_coverage() -> None:
    """The 960-word envelope must not force long multi-claim citation units."""
    answer = ANSWER_SCHEMA["properties"]["answer"]

    assert answer["maxItems"] == 32
    assert answer["items"]["properties"]["text"]["pattern"].endswith("{1,30}$")


@pytest.mark.live
def test_run_one_live() -> None:
    """Exercise authenticated Codex plus real ClimbMix search/fetch on demand."""
    result = run_one(
        qid=QID,
        narrative=NARRATIVE,
        run_id="codex-cli.live",
        run_desc="live Codex CLI smoke test",
        attempts=1,
    )
    assert result["references"]
    assert "violations" not in result["paths"]
