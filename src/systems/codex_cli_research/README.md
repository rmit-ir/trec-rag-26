# Codex CLI research

This system launches one ephemeral, non-interactive Codex session per TREC RAG
narrative. Codex first makes an internal coverage plan, then executes it using
only the private stdio ClimbMix MCP server's `search` and `fetch` tools.

Each subprocess starts in an empty temporary directory, with parent-project
discovery disabled and the research contract installed through Codex's
`model_instructions_file`. This prevents the repository's coding instructions
from consuming or competing in research context. The nested configuration
disables web and shell tools, runs read-only, loads only the `climbmix` MCP
server, and installs a `PreToolUse` hook that denies every local tool other than
`mcp__climbmix__search` and
`mcp__climbmix__fetch`. The MCP server logs successful searches and full-document
fetches per topic. The shared host assembler rejects any citation to a docid
that was not fetched, maps valid docids to `references` indices, applies the
official 1,024-word / three-citation contract, and writes standard artifacts.

```text
Codex plan -> [MCP search -> MCP fetch]* -> JSON schema
                                      -> fetched-doc gate -> ragrun.save_run
```

Run one topic or the complete 30-topic development set from the repository
root:

```bash
uv run --group codex-cli-research python \
  src/systems/codex_cli_research/run.py --qid <qid>

uv run --group codex-cli-research python \
  src/systems/codex_cli_research/run.py --all --workers 2 \
  --run-id codex-cli-research-dev30
```

On this host, `fetch` reads exact parent documents from the read-only
`data/built-indexes/climbmix-full/docstore`, so the final run does not consume
the official remote document service's quota. A host-wide lock and 0.5-second
minimum interval remain as the remote fallback when that local artifact is not
available.

Scratch logs live under `data/agent-work/codex-cli-research/<run-id>/<qid>/`;
submission-compatible artifacts live under `data/outputs/codex-cli-research/`.
Interrupted runs resume from completed topic artifacts unless `--no-resume` is
passed.

Offline coverage is in `tests/systems/test_codex_cli_research.py`; run the full
hermetic suite with `bash scripts/test.sh`.
