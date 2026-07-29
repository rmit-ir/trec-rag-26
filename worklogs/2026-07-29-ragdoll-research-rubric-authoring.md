# RAGDoll Research Rubric authoring

## Goal

Extend RAGDoll so rubric authoring can generate the complete Research Rubric
JSONL schema, rather than only converting an existing Research Rubric into
RAGDoll's native criteria format. Allow an existing Research Rubric row to be
embedded as a one-shot style example.

## Implementation

- Added `--rubric-style research` to `ragdoll rubric author` and the combined
  `ragdoll rubric eval` pipeline.
- Added `--rubric-example-file` and optional `--rubric-example-qid`.
- Added a Research Rubric author prompt requesting:
  - `domain`
  - `conceptual_breadth`
  - `logical_nesting`
  - `exploration`
  - exactly 20 rubric criteria with `criterion`, `weight`, and `axis`
- The parser validates the official enums, all six axes, non-zero integer
  weights from -5 through 5, and the presence of both positive and negative
  criteria.
- The one-shot selector never uses the target query's own rubric as its
  example. A requested matching qid is rejected for that target and a
  different example is selected.
- Research Rubric output retains `task_id`, `status`, `qid`, and `query` for
  RAGDoll resume/debugging, followed by the complete generated rubric fields.
- Retained the preceding official-schema ingestion support so generated
  Research Rubrics can subsequently be graded directly, including correct
  negative-criterion scoring.

## Validation

Commands:

```powershell
uv run --project evaluation/ragdoll --group dev pytest -p no:cacheprovider evaluation/ragdoll/tests/test_rubric.py -k "research or negative or normalize or direct_grade_inputs or score_response"
uv run --project evaluation/ragdoll --group dev ruff check evaluation/ragdoll/src/ragdoll/cli.py evaluation/ragdoll/src/ragdoll/config.py evaluation/ragdoll/src/ragdoll/rubric/__init__.py evaluation/ragdoll/src/ragdoll/rubric/flows.py evaluation/ragdoll/src/ragdoll/rubric/prompts.py evaluation/ragdoll/src/ragdoll/rubric/stages.py evaluation/ragdoll/tests/test_rubric.py
uv run --project evaluation/ragdoll ragdoll rubric author --help
uv run --project evaluation/ragdoll --group dev pytest -p no:cacheprovider evaluation/ragdoll/tests/test_rubric.py
```

Results:

- Focused prompt/parser/scoring suite: 11 passed.
- Ruff: all changed files passed after formatting.
- CLI help exposes all three new flags.
- Full rubric file: 23 passed and 5 failed. The five failures are existing
  Windows-only fake-agent integration tests: they create extensionless
  executable scripts, which Windows cannot launch and reports as
  `FileNotFoundError: [WinError 2]`. None exercise the new Research Rubric
  prompt/parser path; all platform-independent tests passed.

No live model call was made, so this session produced no experiment run-id or
model output artifact.
