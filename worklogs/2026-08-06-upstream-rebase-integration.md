# Upstream rebase and research-system integration

Date: 2026-08-06

## Objective

Preserve the research-agent systems and their findings while rebasing the 17
local commits onto the latest `origin/main`, prefer upstream for unrelated
changes, and finish with a tested, clean worktree.

## Inputs

- Pre-rebase local tip: `24f1bcb8` (`Add constrained CLI research systems`)
- Upstream base fetched for the rebase: `708cbafa`
- Initial divergence: 39 upstream-only commits and 17 local-only commits
- Rebase command: `git rebase origin/main`

## Conflict decisions

- Kept upstream's extraction of the staged-context loop from `aus_agent` into
  the shared `agent_harness` package. The baseline `aus_agent` therefore stays
  a thin prompt/configuration system instead of regaining its old private loop.
- Migrated `aus_agent_v2` imports and architecture references from the removed
  `aus_agent.context`, `aus_agent.providers`, and `aus_agent.tools` modules to
  their `agent_harness` equivalents.
- Combined upstream's architecture shared-edge completeness logic with the
  local `ARCH_VARIANTS` branch-lane renderer. Generated HTML conflicts were
  discarded and `docs/architecture.html` was regenerated from merged source.
- Kept all three optional dependency groups when `pyproject.toml` conflicted:
  upstream `facets-agent` plus local `codex-cli-research` and
  `claude-code-research`; regenerated `uv.lock` with `uv lock`.
- Preserved the proven locale-neutral behavior by making
  `agent_harness.agent.now_full` convert timestamps to UTC and emit the literal
  `UTC`, rather than retaining a host-specific numeric offset.

## Verification

- Architecture generator focused tests after merging both generator branches:
  `16 passed`.
- Architecture regeneration:
  `8 systems, 28 edges, 5 engines`; opened at `#aus_agent_v2`.
- First full hermetic suite: `1901 passed, 1 failed, 10 deselected`. The single
  failure identified the host-offset/UTC semantic conflict described above.
- Focused UTC regression after the fix: `1 passed`.
- Final full hermetic suite after the UTC correction: `1902 passed, 10
  deselected, 1 warning` in 29.01 seconds. The warning is Starlette's existing
  `httpx`-client deprecation notice in `test_mcp_server.py`.
- Final architecture freshness: `--check` passed for the regenerated diagram.

## Result

The rebased branch retains the verified research-first control, its isolated
architecture candidates and worklogs, both constrained CLI research systems,
and upstream's newer shared harness and facets-agent work. No live model or
search API calls were made during integration.
