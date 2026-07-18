# RAGDoll Windows agent resolution

## Problem

An UMBRELA Bedrock run launched from Git Bash with `--agent-binary pi.cmd`
recorded `FileNotFoundError: [WinError 2]` for agent invocations. PowerShell's
command discovery resolved the wrapper to
`C:\Users\ADMIN\AppData\Local\pi-node\current\pi.cmd`, while the runner passed
the unresolved `pi.cmd` string directly to `asyncio.create_subprocess_exec`.

The existing output contained 3,181 rows: 339 completed and 2,842 failed.
RAGDoll's resume logic correctly treats only rows whose `status` is
`completed` as done, explaining the message `resume: skipped 339 completed
task(s)`.

## Change

Added `resolve_agent_binary`, which applies `shutil.which` before starting the
subprocess and falls back to the configured value so the existing launch error
reporting remains intact. The runner now uses the resolved path. Added tests
for both resolution and fallback.

## Verification

Run from the repository root with a workspace-local uv cache and pytest temp
directory because the sandbox could not access the user's default locations:

```text
uv run --project evaluation/ragdoll --group dev pytest -p no:cacheprovider --basetemp D:\Work\trec-rag-26\tmp\pytest-ragdoll evaluation/ragdoll/tests/test_runner.py
uv run --project evaluation/ragdoll --group dev ruff check evaluation/ragdoll/src/ragdoll/runner.py evaluation/ragdoll/tests/test_runner.py
```

Results:

- Both new binary-resolution regression tests passed, along with six other
  platform-independent tests.
- Three pre-existing fake-agent tests failed because they create extensionless
  executable Python scripts, which Windows cannot execute directly. They fail
  at subprocess launch and are unrelated to the PATH-resolution change.
- Ruff passed for the changed source and test files.
- A runtime import check resolved `pi.cmd` to
  `C:\Users\ADMIN\AppData\Local\pi-node\current\pi.cmd`.

## Follow-up: Bedrock authentication

After binary resolution was fixed, 480 retried tasks reached Pi and failed
with this exact error:

```text
local agent exited with code 1: No API key found for amazon-bedrock.

Use /login to log into a provider via OAuth or API key.
```

At diagnosis time, `C:\Users\ADMIN\.pi\agent\auth.json` was an empty JSON
object (two bytes), and none of `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`, or
`AWS_BEARER_TOKEN_BEDROCK` was present in the process environment. Pi's local
provider documentation says Amazon Bedrock accepts an AWS profile, IAM keys,
or `AWS_BEARER_TOKEN_BEDROCK`. The repository virtual environment does not
provide provider credentials.
