# 2026-07-21 — RAGDOLL single-file converter

Updated `scripts/resolve-rag-output-references.py` so conversion of aus-agent
output artifacts produces only the consolidated RAGDOLL `answers.resolved.jsonl`
file. The previous `--output-dir` argument and per-artifact resolved JSON copies
were removed because RAGDOLL consumes the combined JSONL input.

The converter continues to validate citation indices, resolve passage text from
companion trajectory files with API fallback, normalize the RAGDOLL row schema,
and deduplicate repeated `(run_id, qid)` cells by retaining the newest artifact.

Verification used the existing artifact
`20260717T123214514216+1000.can_you_critically_evaluate_the.output.json` and its
companion trajectory. The command resolved all 12 cited references locally and
wrote one RAGDOLL JSONL row containing 25 answer sentences. Python compilation
and the updated `--help` command also completed successfully. The repository's
`uv.exe` WinGet link could not be launched in the sandbox, so verification used
the repository-root `.venv/Scripts/python.exe` interpreter instead.

Follow-up: changed the converter's default destination from RAGDOLL's ignored
submodule-local `evaluation/ragdoll/results/aus-agent/` directory to the parent
repository's tracked `evaluation-results/aus-agent/` directory. Callers can now
omit `--ragdoll-output`; the consolidated file defaults to
`evaluation-results/aus-agent/answers.resolved.jsonl`.
