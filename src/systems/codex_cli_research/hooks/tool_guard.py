"""Codex PreToolUse hook: permit only the two private ClimbMix MCP tools.

Keep this file compatible with the host's minimal ``/usr/bin/python3`` because
hooks run outside the task's uv environment.
"""

import json
import os
import sys
from pathlib import Path

ALLOWED = {"mcp__climbmix__search", "mcp__climbmix__fetch"}


def main() -> int:
    """Log the attempted tool and deny anything outside the research surface."""
    event = json.load(sys.stdin)
    tool_name = str(event.get("tool_name", ""))
    allowed = tool_name in ALLOWED
    log_path = os.environ.get("CLI_RESEARCH_GUARD_LOG")
    if log_path:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"tool_name": tool_name,
                                     "decision": "allow" if allowed else "deny"})
                         + "\n")
    if allowed:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "This research runner permits only ClimbMix MCP search and fetch."),
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
