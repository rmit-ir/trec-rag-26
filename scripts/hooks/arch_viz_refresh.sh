#!/usr/bin/env bash
# Keep docs/architecture.html in sync with src/systems/ during Claude Code
# sessions (see skills/trec-rag-new-system/SKILL.md).
#
# Wired up in .claude/settings.json:
#   PostToolUse (Edit|Write|MultiEdit) -> regenerate silently when the systems
#                                         layer or the generator changed.
#   Stop --verify                      -> last-word check; if the diagram is
#                                         still stale, tell the agent to fix it.
#
# Hook contract: stdin is a JSON event. Exit 0 = pass. On the Stop hook, exit 2
# feeds stderr back to the model as a blocking reason.
set -uo pipefail

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT" ]] && exit 0
cd "$REPO_ROOT" || exit 0

GEN="skills/trec-rag-new-system/scripts/gen_arch_viz.py"
[[ -f "$GEN" ]] || exit 0

PY="$(command -v python3 || command -v python)"
[[ -z "$PY" ]] && exit 0

VERIFY=0
[[ "${1:-}" == "--verify" ]] && VERIFY=1

# Read the event (PostToolUse carries the edited path); ignore parse failures.
EVENT="$(cat 2>/dev/null || true)"

if [[ $VERIFY -eq 0 ]]; then
  # Only act when the edit touched the systems layer or the generator itself.
  FILE="$("$PY" -c '
import json,sys
try:
    d = json.loads(sys.stdin.read() or "{}")
except Exception:
    print(""); raise SystemExit
ti = d.get("tool_input") or {}
print(ti.get("file_path") or ti.get("path") or "")
' <<<"$EVENT" 2>/dev/null)"
  case "$FILE" in
    */src/systems/*|*/gen_arch_viz.py) ;;
    *) exit 0 ;;
  esac
  # Regenerate quietly; a broken tree mid-edit must not spam the session.
  "$PY" "$GEN" >/dev/null 2>&1
  exit 0
fi

# --- Stop: verify the committed artifact is fresh --------------------------
if "$PY" "$GEN" --check >/dev/null 2>&1; then
  exit 0
fi

# Try once to fix it ourselves, then re-check.
"$PY" "$GEN" >/dev/null 2>&1
if "$PY" "$GEN" --check >/dev/null 2>&1; then
  exit 0
fi

cat >&2 <<'MSG'
docs/architecture.html does not match src/systems/ and could not be regenerated
automatically. Run this, resolve any error, and confirm the diagram is correct:

    python skills/trec-rag-new-system/scripts/gen_arch_viz.py --open
MSG
exit 2
