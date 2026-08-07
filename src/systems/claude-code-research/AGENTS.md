# Claude Code corpus research runner

This directory is a TREC RAG 2026 system, not a general web-research
workspace. Run it through `run.py`; do not manually create task folders under
the source tree.

For every narrative:

- ClimbMix is the only evidence source.
- The only enabled research tools are the private MCP server's `search` and
  `fetch` methods. WebSearch, WebFetch, browser, shell, filesystem editing, and
  delegation are disabled by the runner.
- Fetch every document before citing it. A search snippet cannot authorize a
  citation.
- Return the schema-bound `answer[]` objects requested by the runner. Each item
  has non-empty `text` and zero to three ClimbMix docids in `citations`.
- Keep the total at or below 1,024 words. Markdown headings, labels, and table
  rows are structurally permitted, but factual answer objects need direct
  support.

The host assembler verifies cited docids against the private MCP log, maps them
to `references`, validates the official format, and writes artifacts under
`data/outputs/claude-code-research/`. Scratch files go under
`data/agent-work/claude-code-research/`, never under this package.

Run from the repository root:

```bash
uv run --group claude-code-research python \
  src/systems/claude-code-research/run.py --all --workers 4
```
