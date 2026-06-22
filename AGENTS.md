Google Groups mailing list: https://groups.google.com/g/trec-rag-2026-participants
TREC RAG 2026 Official Skills: https://github.com/TREC-RAG/trec-rag-skills.git

## Environment Rules

- **Each task gets its own `uv` env.** Every directory under `tasks/<task>/`
  owns its own `pyproject.toml` and `.venv/`. Run Python inside a task as
  `uv run --project tasks/<task> …` (or `cd tasks/<task> && uv run …`). Tasks
  often target different servers / stacks, so isolation prevents dep conflicts.
- **Do not reuse or share the project root env from a task.** The repo root
  `pyproject.toml`/`.venv` (if any) is for repo-wide tooling only; task scripts
  must never depend on packages installed there, and must never `uv add` into
  the root env from inside a task.
- For command-line tools (`huggingface-cli`/`hf`, etc.), prefer `uvx <tool> …`
  — `uvx` runs each tool in its own ephemeral env, so it never pollutes either
  the system, the root env, or the task env.

## Running Long Commands

For anything that may run longer than a few seconds (downloads, uploads, builds,
migrations, dev/test servers, batch jobs), launch it as a **tracked** background
task (`run_in_background`, not a detached `&`) and `tee` the output to a log
file so it is visible in both places.

```bash
some-command 2>&1 | tee /tmp/<task>.log   # launch as a tracked background task
# then tell the user: tail -f /tmp/<task>.log
```

Do not pipe an in-flight command through `tail`/`head` — piped output is
buffered until the producer exits, so the user sees nothing while progress is
being made.

When launching a tracked background task, print the **full command** verbatim
in the chat response (a fenced block) right after kicking it off, so the user
can post-check exactly what is running. Don't paraphrase or omit env vars.

Proactively clean up: kill background tasks and throwaway resources once
they're no longer needed. Exception: something handed to the user for testing
(e.g. a dev server) stays running until they say they're done.

## Active Tasks

- **Creating local custom index** — working in `tasks/custom_index/`. All scripts, logs, and intermediate artifacts for this task live there.
