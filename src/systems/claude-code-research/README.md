# Claude Code research

This system now has a reproducible non-interactive runner. Each development
narrative gets one Claude Code session with a strict MCP configuration exposing
only ClimbMix `search` and `fetch`; Bash, filesystem, web, browser, delegation,
and editing tools are disabled. Claude returns JSON matching the same answer
schema used by the Codex CLI system. The subprocess working directory is an
empty temporary directory, so unrelated parent-repository instructions do not
enter the research context.

The host-side assembler requires every cited docid to appear in that topic's
successful full-document fetch log, maps citations into the official
`references` array, validates the 1,024-word and at-most-three-citations rules,
and saves the standard output and trajectory artifacts.

```text
Claude plan -> [MCP search -> MCP fetch]* -> JSON schema
                                       -> fetched-doc gate -> ragrun.save_run
```

Run one topic or all 30 development topics:

```bash
uv run --group claude-code-research python \
  src/systems/claude-code-research/run.py --qid <qid>

uv run --group claude-code-research python \
  src/systems/claude-code-research/run.py --all --workers 2 \
  --run-id claude-code-research-dev30
```

On this host, `fetch` reads exact parent documents from the read-only
`data/built-indexes/climbmix-full/docstore`. A host-wide 0.5-second fetch pacer
is retained only for installations that must fall back to the official remote
document endpoint.

Scratch logs are under `data/agent-work/claude-code-research/`; organizer and
internal artifacts are under `data/outputs/claude-code-research/`. Completed
topics are reused on restart unless `--no-resume` is passed.
