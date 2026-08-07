#!/usr/bin/env bash
set -euo pipefail

system_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$system_dir/../../.." && pwd)"

exec uv run --project "$repo_root" --group claude-code-research \
  python "$repo_root/src/mcp/climbmix_server.py"
